"""Read-only four-environment logical SQLite comparison; outputs hashes, never data."""
import image_identity as images_identity
import hashlib
import argparse
import json
from pathlib import Path
import sqlite3
import subprocess
import tarfile
import tempfile
import controlled_seed
import experiment


LOGICAL = '''import sqlite3,json,hashlib,shutil,tempfile,pathlib
with tempfile.TemporaryDirectory() as tmp:
 for p in pathlib.Path('/data').glob('memos_prod.db*'): shutil.copyfile(p,pathlib.Path(tmp)/p.name)
 db=sqlite3.connect(str(pathlib.Path(tmp)/'memos_prod.db'))
 result=[];raw_result=[];tables={}
 for name,sql in db.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name"):
  quote='"'+name.replace('"','""')+'"'
  rows=[[{'blob':v.hex()} if isinstance(v,bytes) else v for v in row] for row in db.execute('SELECT * FROM '+quote)]
  columns=[x[1] for x in db.execute('PRAGMA table_info('+quote+')')]
  raw_result.append([name,sql,sorted(json.loads(json.dumps(rows)),key=lambda r:json.dumps(r,sort_keys=True))])
  if name=='user_setting':
   for row in rows:
    if row[columns.index('key')]=='PERSONAL_ACCESS_TOKENS':
     value=json.loads(row[columns.index('value')])
     for token in value.get('tokens',[]):
      token.pop('lastUsedAt',None);token.pop('last_used_at',None)
     row[columns.index('value')]=json.dumps(value,sort_keys=True,separators=(',',':'))
  result.append([name,sql,sorted(rows,key=lambda r:json.dumps(r,sort_keys=True))])
  tables[name]={'rows':len(rows),'columns':{column:hashlib.sha256(json.dumps(sorted([r[i] for r in rows],key=str),sort_keys=True).encode()).hexdigest() for i,column in enumerate(columns)}}
 print(json.dumps({'database':hashlib.sha256(json.dumps(result,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'raw_database':hashlib.sha256(json.dumps(raw_result,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'tables':tables}))
'''


def output(args):return subprocess.check_output(args,text=True).strip()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True,help='New evidence path; never overwrite historical comparisons')
    args=parser.parse_args()
    if args.output.exists():raise ValueError('Output already exists; preserve prior evidence')
    root=experiment.ROOT;state=Path.home()/'memos-bdi-state'
    manifest,frozen=experiment.selection('bdi');v1=frozen['releases']['v1']
    seed=controlled_seed.validate(state/'phase7-seed',v1)
    adapter=json.loads((state/'adapters'/(manifest['bdi']['control_sha']+'.json')).read_text())['image_id']
    hashes={};versions={};details={}
    for prefix in ['memos-current-experiment','memos-experiment-bdi']:
        for env in ['staging','production']:
            project=prefix+'-'+env;volume=project+'_data'
            meta=json.loads(output(['docker','volume','inspect',volume]))[0]
            if meta.get('Labels',{}).get('com.docker.compose.project')!=project:raise ValueError('Foreign volume')
            cid=output(['docker','ps','-q','--filter','label=com.docker.compose.project='+project,'--filter','label=com.docker.compose.service=memos'])
            container=json.loads(output(['docker','inspect',cid]))[0]
            if not images_identity.matches(v1, container['Image']):raise ValueError('Environment is not immutable v1')
            versions[project]=container['Image']
            details[project]=json.loads(output(['docker','run','--rm','--pull','never','--network','none','--user','0',
                '--mount','type=volume,source='+volume+',target=/data,readonly',adapter,'python','-c',LOGICAL]))
            hashes[project]=details[project]['database']
    with tempfile.TemporaryDirectory(dir=state) as tmp:
        with tarfile.open(seed['directory']/'data.tar.gz') as archive:
            (Path(tmp)/'memos_prod.db').write_bytes(archive.extractfile('./memos_prod.db').read())
        details['controlled_seed']=json.loads(output(['docker','run','--rm','--pull','never','--network','none','--user','0',
            '--mount','type=bind,source='+tmp+',target=/data,readonly',adapter,'python','-c',LOGICAL]))
        hashes['controlled_seed']=details['controlled_seed']['database']
    report=dict(equal=len(set(hashes.values()))==1,logical_sha256=hashes,image_ids=versions,
                archive_sha256=seed['manifest']['archive_sha256'],read_only=True,details=details,
                excluded_operational_fields=['user_setting.PERSONAL_ACCESS_TOKENS.tokens[].lastUsedAt (or last_used_at)'],
                exclusion_reason='Authenticated verification reads update PAT last-used time asynchronously; no application rows, token identity or permissions excluded')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as stream:json.dump(report,stream,indent=2)
    if not report['equal']:raise ValueError('Controlled logical database state differs; inspect retained hash report')
    print('Both treatments, both environments: identical logical database state and frozen v1 image.')


if __name__=='__main__':main()
