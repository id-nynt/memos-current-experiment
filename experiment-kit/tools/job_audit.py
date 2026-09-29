"""Offline Job contract audit; refresh explicit fingerprints only when requested locally."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def audit(refresh=False):
    repo=ROOT/'memos-bdi'
    conventional=ROOT/'memos-current'
    frozen_path=conventional/'experiment/frozen-control.json'
    frozen=json.loads(frozen_path.read_text())
    hashes={name:hashlib.sha256((conventional/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for name in frozen['files']}
    if refresh:
        frozen['files']=hashes
        frozen['server_preparation_note']='Current source fingerprints for the shared Linux image session; actual control selection belongs to the versioned experiment kit.'
        frozen_path.write_text(json.dumps(frozen,indent=2)+'\n',encoding='utf-8',newline='\n')
    elif hashes!=frozen['files']:raise ValueError('Stale Conventional frozen-control fingerprints')
    for relative,key in [('experiment/adapter-contract.json','reviewed_sources')]:
        path=repo/relative;doc=json.loads(path.read_text())
        actual={name:hashlib.sha256((repo/name).read_text(encoding='utf-8').encode()).hexdigest() for name in doc[key]}
        if refresh:doc[key]=actual;path.write_text(json.dumps(doc,indent=2)+'\n',encoding='utf-8',newline='\n')
        elif actual!=doc[key]:raise ValueError('Stale adapter fingerprints')
    path=ROOT/'protocol/bdi-policy-final-source.json';doc=json.loads(path.read_text())
    names=[n.replace('entity-execution.yml','job-execution.yml').replace('GitHubEntityExecution.java','GitHubJobExecution.java') for n in doc['reviewed_code_sha256']]
    actual={name:hashlib.sha256((repo/name).read_text(encoding='utf-8').encode()).hexdigest() for name in names}
    if refresh:
        doc['reviewed_code_sha256']=actual
        doc['purpose']='Current Job control policy fingerprint; historical policy contract remains separate.'
        path.write_text(json.dumps(doc,indent=2)+'\n',encoding='utf-8',newline='\n')
    elif actual!=doc['reviewed_code_sha256']:raise ValueError('Stale shared Job policy fingerprints')
    subprocess.run([sys.executable,'-B',str(repo/'bdi-cicd-framework/run_controller.py'),'--validate-only'],check=True)
    # Production framework/model/worker code must not keep the removed vocabulary.
    stale=[]
    for base in ('bdi-cicd-framework','experiment/scripts','.github/workflows'):
        for folder,dirs,files in os.walk(repo/base):
            dirs[:]=[d for d in dirs if d not in ('results','runs','target','build','bin','__pycache__','.gradle','fixtures','test')]
            for name in files:
                path=Path(folder)/name
                if name.startswith('test_') or path.suffix not in ('.py','.java','.asl','.yaml','.yml'):continue
                if re.search(r'\bentity\b|\bentities\b|EntityExecution|ENTITY_TIMEOUT',path.read_text(encoding='utf-8')):stale.append(str(path.relative_to(repo)))
    if stale:raise ValueError('Stale production Entity terminology: '+str(stale))
    print('PASS: Job models, generation, agent, adapter and worker contracts')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--refresh-fingerprints',action='store_true');a=p.parse_args()
    audit(a.refresh_fingerprints)
