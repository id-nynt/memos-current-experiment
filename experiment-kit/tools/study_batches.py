"""Deterministic, balanced selections over the unchanged 100-case protocol."""
from collections import Counter
import argparse
import json
import math
from pathlib import Path
import random
import phase8_matrix as matrix

PATH = matrix.ROOT/'protocol/study-batches.json'


def dimensions(case):
    episodes = case['parameters']['episodes']
    temporal = ('healthy' if case['family']=='reference' else
                'ci' if case['analysis_stratum']=='ci' else
                'persistent' if any(e['end']>=300 for e in episodes) else 'finite')
    return {'family':case['family'], 'stage':case['parameters']['stage'],
            'exposure':temporal, 'first':case['treatments'][0], 'set':case['test_set'],
            'repeat_group':case['exposure_group']}


def build(manifest):
    matrix.validate(manifest)
    cases=manifest['cases']; rng=random.Random(20260930)
    features=[set(dimensions(c).items()) for c in cases]
    totals=Counter(v for f in features for v in f)
    groups={}
    for i,c in enumerate(cases):groups.setdefault((c['test_set'],c['treatments'][0]),[]).append(i)
    bins=[[] for _ in range(5)]
    for group in groups.values():
        rng.shuffle(group)
        for i,case in enumerate(group):bins[i%5].append(case)
    counts=[Counter(v for i in b for v in features[i]) for b in bins]
    def penalty(n,key):
        low=totals[key]//5; high=math.ceil(totals[key]/5)
        return max(low-n,0,n-high)**2
    score=sum(penalty(n[k],k) for n in counts for k in totals)
    # Swapping within set/first-treatment strata preserves exact 10/10 margins.
    # Only accept improving or neutral moves; fixed PRNG makes allocation reproducible.
    for _ in range(200000):
        if score==0:break
        a,b=rng.sample(range(5),2); x=rng.choice(bins[a])
        options=[y for y in bins[b] if (cases[y]['test_set'],cases[y]['treatments'][0])==(cases[x]['test_set'],cases[x]['treatments'][0])]
        y=rng.choice(options); removed=features[x]-features[y]; added=features[y]-features[x]
        delta=0
        for key in removed:
            delta+=penalty(counts[a][key]-1,key)+penalty(counts[b][key]+1,key)-penalty(counts[a][key],key)-penalty(counts[b][key],key)
        for key in added:
            delta+=penalty(counts[a][key]+1,key)+penalty(counts[b][key]-1,key)-penalty(counts[a][key],key)-penalty(counts[b][key],key)
        if delta<=0:
            bins[a][bins[a].index(x)]=y;bins[b][bins[b].index(y)]=x
            for key in removed:counts[a][key]-=1;counts[b][key]+=1
            for key in added:counts[a][key]+=1;counts[b][key]-=1
            score+=delta
    if score:raise ValueError('Could not satisfy integer proportional bounds')
    rows=[]
    for number,items in enumerate(bins,1):
        remaining=sorted(items,key=lambda i:cases[i]['case_id']); ordered=[]; previous=None
        while remaining:
            first='conventional' if len(ordered)%2==0 else 'bdi'
            candidates=[i for i in remaining if cases[i]['treatments'][0]==first]
            used_sets=Counter(cases[i]['test_set'] for i in ordered)
            item=min(candidates,key=lambda i:(used_sets[cases[i]['test_set']],cases[i]['family']==previous,cases[i]['case_id']))
            ordered.append(item);remaining.remove(item);previous=cases[item]['family']
        rows.append(dict(batch_id=f'batch-{number}',cases=[dict(case_id=cases[i]['case_id'],
            scenario=cases[i]['scenario'],family=cases[i]['family'],seed=cases[i]['parameters']['seed'],
            repetition_group=cases[i]['exposure_group'],repeat_members=cases[i]['repeat_members'],
            treatment_order=cases[i]['treatments'],strata=dimensions(cases[i])) for i in ordered]))
    return dict(schema_version=1,matrix_sha256=matrix.sha(manifest),algorithm='stratified swaps v1; seed 20260930; integer floor/ceiling margins',batches=rows)


def validate(value,manifest):
    cases={c['case_id']:c for c in manifest['cases']}
    ids=[c['case_id'] for b in value['batches'] for c in b['cases']]
    if len(ids)!=100 or len(set(ids))!=100 or set(ids)!=set(cases):raise ValueError('Missing/duplicate study case')
    totals=Counter(v for c in cases.values() for v in dimensions(c).items())
    for b in value['batches']:
        if len(b['cases'])!=20:raise ValueError('Batch must contain 20 pairs')
        counts=Counter(v for row in b['cases'] for v in dimensions(cases[row['case_id']]).items())
        for key,n in totals.items():
            if not n//5<=counts[key]<=math.ceil(n/5):raise ValueError('Unbalanced '+str(key))
    if value!=build(manifest):raise ValueError('Allocation or recorded case metadata differs from deterministic compiler')
    return dict(status='PASS',batches=5,pairs=100,per_batch=20,first_treatment='10/10',test_set='10 A / 10 B',proportions='every recorded stratum within floor/ceiling of its total / 5')


def load():
    manifest=json.loads(matrix.MANIFEST.read_text())
    value=json.loads(PATH.read_text());validate(value,manifest)
    return value


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--write',action='store_true');a=p.parse_args()
    manifest=json.loads(matrix.MANIFEST.read_text());value=build(manifest)
    if a.write:PATH.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    else:value=json.loads(PATH.read_text())
    print(json.dumps(validate(value,manifest)))
