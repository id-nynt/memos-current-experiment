"""Deterministic study design compiler; no execution, network or runtime mutation."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import scenario_runtime as runtime

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'protocol/phase8-case-matrix.json'


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def episode(start, end, error=0, delay=0):
    return dict(start=start,end=end,error_percent=error,delay_ms=delay,mode='request',status=503,
                error_model='exact_count',block_size=100,failure_count=error)


def build():
    base=json.loads((ROOT/'protocol/scenario-catalogue.json').read_text())['scenarios']
    cases=[]
    def add(test_set,parent,family,episodes,stage='production',mechanism=None):
        index=len(cases)+1; local=(index-1)%50+1
        cid=f'M{index:03d}'
        sid=mechanism or f'P8{index:03d}'
        seed=820000+index
        spec=None
        if mechanism is None:
            spec=copy.deepcopy(base[parent])
            spec.update(id=sid,title=f'{cid} {stage} {family}',family=family,stage=stage,seed=seed,
                        episodes=[dict(e,id=f'e{n+1}') for n,e in enumerate(episodes)],status='implemented')
            runtime.validate(spec)
        params=dict(stage=stage,seed=seed,episodes=episodes)
        cases.append(dict(case_id=f'M{index:03d}',pair_key=f'M{index:03d}',baseline=parent,
            scenario=sid,family=family,test_set=test_set,analysis_stratum='ci' if mechanism else 'service',
            parameters=params,spec=spec,spec_sha256=sha(spec or {'scenario':sid,'fixed_fixture':True}),
            treatments=['conventional','bdi'] if local%2 else ['bdi','conventional'],
            anchor='native_terminal' if mechanism else 'schedule_activation',horizon_seconds=300,
            reset='shared-controlled-seed',execution_status='requires_published_controls',
            seed_affects_fault_positions=any(e['failure_count'] not in (0,100) for e in episodes)))
    for test_set in ('A','B'):
        b=test_set=='B'
        add(test_set,'P00','reference',[])
        add(test_set,'P34' if b else 'P33','deterministic_control',[], 'ci','CI03' if b else 'CI02')
        add(test_set,'P01','ci_retry',[],'ci','CI01')
        add(test_set,'P00','reference',[])
        for severity,onset in ((10,0),(30,0),(60,0),(100,0),(60,25 if b else 20)):
            add(test_set,'P02','persistent',[episode(onset,300,severity)])
        durations=(20,40,60,75,100) if b else (15,30,45,75,110)
        for severity,end in zip((30,60,100,60,30),durations):
            add(test_set,'P03','transient',[episode(0,end,severity)])
        for severity,end in zip((30,60,100),(150,175,165) if b else (145,175,175)):
            add(test_set,'P04','long_transient',[episode(0,end,severity)])
        for severity,gap in zip((30,60,100),(20,40,30) if b else (15,40,20)):
            add(test_set,'P05','relapse',[episode(0,30,severity),episode(30+gap,150,severity)])
        for severity,width in zip((30,60,60),(15,20,30) if b else (10,20,35)):
            add(test_set,'P06','intermittent',[episode(t,min(t+width,140),severity) for t in range(0,140,2*width)])
        for onset,persistent in zip((15,30,60,110,180) if b else (10,25,50,100,180),(True,False,True,False,True)):
            add(test_set,'P07' if persistent else 'P08','delayed',[episode(onset,300 if persistent else onset+30,60)])
        for severity in (4,5,6):
            add(test_set,'P10','threshold',[episode(0,180,severity)])
        for n,rates in enumerate(((4,6,30),(60,30,10),(10,30,60))):
            cuts=(0,30,65,180) if b and n!=1 else (0,25,60,180)
            add(test_set,'P14' if n==1 else 'P13','trajectory',
                [episode(cuts[i],cuts[i+1],rate) for i,rate in enumerate(rates)])
        for severity in ((4,60,100) if b else (6,30,100)):
            add(test_set,'P15','staging',[episode(0,300,severity)],'staging')
        for severity,end in ((30,60 if b else 45),(100,90)):
            add(test_set,'P16','staging',[episode(0,end,severity)],'staging')
        add(test_set,'P17','staging',[episode(0,30,60),episode(65 if b else 50,130,60)],'staging')
        add(test_set,'P30','staging',[episode(0,90,delay=550 if b else 500)],'staging')
        for delay in ((450,500,550,1000,2000,4000) if b else (450,500,550,800,1500,4000)):
            add(test_set,'P18','latency',[episode(0,90,delay=delay)])
        add(test_set,'P20','latency',[episode(30 if b else 25,150,delay=800)])
        for severity,delay in ((6,550 if b else 500),(30,800)):
            add(test_set,'P23','mixed',[episode(0,120,severity,delay)])
        assert len(cases)==(100 if b else 50)
    groups={}
    for c in cases:
        key=sha(dict(family=c['family'],stage=c['parameters']['stage'],episodes=c['parameters']['episodes'],
                     mechanism=c['scenario'] if c['spec'] is None else None))
        c['exposure_group']=key
        groups.setdefault(key,[]).append(c['case_id'])
    for c in cases:
        c['repeat_members']=groups[c['exposure_group']]
        c['repeat_rationale']='Limited robustness/reference repeat; distinct seed, not a powered replicate study' if len(c['repeat_members'])>1 else None
    return dict(schema_version=2,study_id='memos-final-exact-v2',status='designed_not_executed',
        supersedes='Unexecuted probability-based memos-final-local-v1 matrix; retained under revision evidence',
        unit='100 paired conditions; 200 candidate executions, excluding resets/qualification',
        test_sets={'A':50,'B':50},ordering='Sequential M order per set; 25 pairs of each first-treatment order per set',
        inference='Balanced coverage with limited different-seed robustness repeats; no full replication/power claim',
        timing_contract='memos-final-phase6-v1',measurement_extension='memos-exact-count-v1',cases=cases)


def validate(value):
    if value!=build():raise ValueError('Matrix differs from deterministic reviewed generator')
    ids=set();seeds=set()
    for c in value['cases']:
        if c['case_id'] in ids or c['parameters']['seed'] in seeds:raise ValueError('Duplicate case/seed')
        ids.add(c['case_id']);seeds.add(c['parameters']['seed'])
        assert set(c['treatments'])=={'conventional','bdi'} and c['horizon_seconds']==300
        assert c['scenario'] in ('CI01','CI02','CI03') or c['scenario'].startswith('P8')
        if c['spec']:
            runtime.validate(c['spec']);assert c['spec_sha256']==sha(c['spec'])
            for ep in c['spec']['episodes']:
                assert ep['mode']=='request' and ep['error_model']=='exact_count'
                assert ep['block_size']==100 and type(ep['failure_count']) is int
        if c['family']=='threshold':assert c['parameters']['episodes'][0]['failure_count'] in (4,5,6)
    return dict(cases=len(ids),candidate_executions=2*len(ids),test_sets=value['test_sets'],valid=True,live_execution=False)


def write():
    value=build();validate(value)
    MANIFEST.write_text(json.dumps(value,indent=2)+'\n')
    profiles={'schema_version':2,'matrix_sha256':sha(value),'scenarios':{c['scenario']:c['spec'] for c in value['cases'] if c['spec']}}
    for folder in ('protocol','tools','memos-current/experiment','memos-bdi/experiment/scripts'):
        (ROOT/folder/'matrix-scenarios.json').write_text(json.dumps(profiles,indent=2)+'\n')
    native=ROOT/'memos-current/experiment/scenarios.json';enabled=json.loads(native.read_text())
    enabled={k:v for k,v in enabled.items() if not k.startswith('P8')}
    for c in value['cases']:enabled[c['scenario']]={'enabled':True,'description':c['family']+'; final exact-count study'}
    native.write_text(json.dumps(enabled,indent=2)+'\n')
    lines=['# Phase 8 exact-count case matrix','',value['unit']+'.','',
        'Study identity: `memos-final-exact-v2`. This supersedes the unexecuted probability matrix.',
        'Set A and Set B each contain 50 treatment pairs, including two healthy references.',
        'Both arms within a condition use the same seed, configuration and controlled v1 database.',
        'The sets balance family and broad severity/timing coverage, with intentional different-seed',
        'repeats and comparable alternatives. This is limited robustness checking, not a powered study.',
        'Independent workload remains serial, approximately 1 request/second; no fixed-start concurrency.',
        'Runtime windows start at target v2 schedule activation and end exactly 300 seconds later.',
        'CI controls use native terminal + 300 seconds. BDI has at most 150 seconds of native observation,',
        'not a mandatory dwell. Reobservation 5 seconds and rollback reconsideration 60 seconds remain.',
        'Every error episode uses K/100 seeded positions separately for independent and native traffic.',
        'Blocks restart per episode; native methods share their stream block. Partial blocks have no',
        'exact realized-rate claim. Delays apply to non-error memo requests across both streams.',
        'Configured additive delay does not equal observed p95. BDI rolling rates have a different',
        'population/window from block counts. Telemetry-loss and semantic faults are reserves only.',
        '', '[Machine manifest](../protocol/phase8-case-matrix.json); regenerate with',
        '`python -B tools/phase8_matrix.py --write`, validate with `--check`. No cases executed.',
        'Use `batch_runner.py dry-run --test-set A` or `--test-set B`; execution gates remain closed.',
        '', '| Family | A pairs | B pairs |','|---|---|---|']
    for family in dict.fromkeys(c['family'] for c in value['cases']):
        counts=[sum(c['family']==family and c['test_set']==name for c in value['cases']) for name in ('A','B')]
        lines.append(f"| {family} | {counts[0]} | {counts[1]} |")
    for name in ('A','B'):
        lines += ['',f'## Test Set {name}','','50 paired conditions; 100 candidate executions.','',
            '| ID | Baseline / execution | Family | Stage | Seed | Episodes: start-end seconds / K of 100 / delay ms | First treatment |',
            '|---|---|---|---|---|---|---|']
        for c in value['cases']:
            if c['test_set']!=name:continue
            ep='; '.join(f"{e['start']}-{e['end']} / {e['failure_count']}/100 / {e['delay_ms']}" for e in c['parameters']['episodes']) or ('healthy' if c['spec'] else c['scenario'])
            lines.append(f"| {c['case_id']} | {c['baseline']} / {c['scenario']} | {c['family']} | {c['parameters']['stage']} | {c['parameters']['seed']} | {ep} | {c['treatments'][0]} |")
    lines += ['','## Deliberate repeats','',
        'Same exposure/configuration, different seeds. A new seed changes positions only when 0 < K < 100;',
        'healthy, pure-latency, 100% and CI repeats check run-to-run behavior, not random fault positions.','',
        '| Conditions | Family | Seed changes selected error positions? |','|---|---|---|']
    seen=set()
    for c in value['cases']:
        if c['repeat_rationale'] and c['exposure_group'] not in seen:
            seen.add(c['exposure_group'])
            lines.append(f"| {', '.join(c['repeat_members'])} | {c['family']} | {c['seed_affects_fault_positions']} |")
    lines += ['','CI02 is one permanent build-boundary failure in A; CI03 one permanent test-boundary',
        'failure in B. These are explicit required-operation fixture failures, not claims that the',
        'frozen application has a compiler/test defect. CI01 remains the transient dependency case.',
        'No controller retry/recovery rule or measured rollback policy is changed.','']
    (ROOT/'docs/PHASE8_CASE_MATRIX.md').write_text('\n'.join(lines),encoding='utf-8')
    return validate(value)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--write',action='store_true');p.add_argument('--check',action='store_true')
    a=p.parse_args()
    print(json.dumps(write() if a.write else validate(json.loads(MANIFEST.read_text())),indent=2))
