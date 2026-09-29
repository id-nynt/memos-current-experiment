"""Offline workflow reachability and runner audit. Never contacts GitHub."""
import argparse
import hashlib
import json
import os
import json
from pathlib import Path
import yaml

ROOT=Path(__file__).resolve().parents[1]
ENTRIES={'memos-current':'frozen-cd.yml','memos-bdi':'job-execution.yml'}
ALLOWED=[['self-hosted','linux','memos-bdi-deploy']]


def load(path):
    # BaseLoader preserves the GitHub "on" key; no YAML 1.1 boolean coercion.
    return yaml.load(path.read_text(encoding='utf-8-sig'),Loader=yaml.BaseLoader)


def reachable(root=ROOT):
    records=[]
    for repo,entry in ENTRIES.items():
        if repo == 'memos-bdi':
            contract = root/repo/'experiment/adapter-contract.json'
            if contract.exists():
                entry = json.loads(contract.read_text())['workflow_file']
                if entry not in ('entity-execution.yml', 'job-execution.yml'):
                    raise ValueError('Unreviewed BDI worker entry')
        visited=set()
        def walk(name,chain):
            if name in visited:return
            visited.add(name)
            path=root/repo/'.github/workflows'/name
            data=load(path)
            if chain and 'workflow_call' not in (data.get('on') or {}):
                raise ValueError('Reusable workflow lacks workflow_call: '+str(path))
            for job_id,job in data['jobs'].items():
                if 'uses' in job:
                    target=job['uses']
                    if not target.startswith('./.github/workflows/') or '${{' in target or '..' in target.split('/')[1:]:
                        raise ValueError('Unreviewed remote/dynamic reusable workflow: '+target)
                    walk(target.split('/')[-1],chain+[name+'/'+job_id]);continue
                runner=job.get('runs-on')
                if runner not in ALLOWED:raise ValueError('Unapproved/hosted runner: '+str(path)+'/'+job_id+' '+str(runner))
                # Actions may not silently introduce another dispatch mechanism.
                for step in job.get('steps',[]):
                    command=step.get('run','')
                    if any(x in command for x in ('gh workflow run','workflow_dispatch','repository_dispatch','gh api repos/')):
                        raise ValueError('Nested dispatch needs explicit audit: '+str(path))
                records.append(dict(repository=repo,workflow=name,job=job_id,runner=runner,
                    chain=chain+[name+'/'+job_id],matrix=job.get('strategy',{}).get('matrix'),
                    timeout_minutes=job.get('timeout-minutes','GitHub default (unchanged)'),
                    permissions=data.get('permissions','inherited/default; review repository setting'),
                    concurrency=data.get('concurrency'),
                    artifacts=[s for s in job.get('steps',[]) if 'artifact@' in s.get('uses','')],
                    source_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        walk(entry,[])
    return records


def inventory(root=ROOT):
    found=[];errors=[]
    def error(exc):errors.append(str(exc))
    for folder,dirs,files in os.walk(root,onerror=error,followlinks=False):
        dirs[:]=[d for d in dirs if d not in ('.git','node_modules','.pnpm-store','.venv','venv','__pycache__',
                                           'bin','build','target','dist','.gradle')]
        p=Path(folder)
        if p.name!='workflows' or p.parent.name!='.github':continue
        for name in files:
            if not name.endswith(('.yml','.yaml')):continue
            path=p/name;relative=path.relative_to(root).as_posix()
            data=load(path)
            rows=[dict(job=k,runner=v.get('runs-on'),uses=v.get('uses')) for k,v in (data.get('jobs') or {}).items()]
            current=any(relative.startswith(r+'/.github/workflows/') for r in ENTRIES)
            historical=('/results/' in relative or relative.startswith('results/'))
            found.append(dict(path=relative,classification='current: classify by reachable closure' if current else 'historical/provenance; not selected' if historical else 'upstream/reference or preparation; not selected',
                triggers=data.get('on'),jobs=rows,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    return found,errors


def report(root=ROOT):
    paths,errors=inventory(root)
    jobs=reachable(root)
    closure={r['repository']+'/.github/workflows/'+r['workflow'] for r in jobs}
    for p in paths:
        if p['path'] in closure:p['classification']='final source execution path'
        elif p['classification'].startswith('current:'):p['classification']='current unrelated/manual/upstream; not batch dispatched'
    return dict(schema_version=1,scope='Working-source closure; historical selected pins remain blocked',
        executable_jobs=jobs,workflow_inventory=paths,scan_errors=errors,
        excluded_generated_directories=['.git','node_modules','.pnpm-store','.venv','venv','__pycache__','bin','build','target','dist','.gradle'],
        hosted_jobs_in_final_source=0,live_runner_validation=False)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path)
    a=p.parse_args();value=report()
    text=json.dumps(value,indent=2)
    if a.output:a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(text+'\n')
    else:print(text)
