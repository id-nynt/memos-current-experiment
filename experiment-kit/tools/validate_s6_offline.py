"""Offline integration test: real Jason + GitHub adapter against loopback mocks.

Not an experiment. No GitHub, Docker, credentials or real deployment is accessed.
Mock workflow results are derived from the shared fixture's actual HTTP probes.
Cached Java dependencies are required; this tool never downloads dependencies.
"""
import argparse
import hashlib
import io
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK = ROOT / 'memos-bdi/bdi-cicd-framework'
sys.path.insert(0, str(ROOT / 'memos-bdi/experiment/scripts'))
from s6_fixture import run_fixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True, type=Path)
    args = parser.parse_args()
    directory = args.directory.resolve()
    directory.relative_to((ROOT / 'results/implementation/s6-preparation').resolve())
    directory.mkdir(parents=True, exist_ok=False)
    (directory / 'OFFLINE_MOCK_ONLY.txt').write_text(__doc__)
    cache = Path.home() / '.gradle/caches/modules-2/files-2.1'
    jars = sorted(p for p in cache.rglob('*.jar') if not p.name.endswith(('-sources.jar','-javadoc.jar')))
    if not jars:
        raise RuntimeError('No cached dependencies; do not launch live tooling as a substitute')
    classes = directory / 'classes'; classes.mkdir()
    classpath = os.pathsep.join(str(p) for p in jars)
    sources = sorted((FRAMEWORK / 'bdi/harness').glob('*.java'))
    sources += sorted((FRAMEWORK / 'monitoring').rglob('*.java'))
    sources += sorted((FRAMEWORK / 'actions').rglob('*.java'))
    compile_args = ['--release','21','-encoding','UTF-8','-cp',classpath,'-d',str(classes), *map(str,sources)]
    argfile = directory / 'javac.args'
    argfile.write_text('\n'.join('"' + value.replace('\\','/') + '"' for value in compile_args), encoding='utf-8')
    with (directory/'compile.log').open('w') as log:
        subprocess.run(['javac','@'+str(argfile)], stdout=log, stderr=subprocess.STDOUT, check=True, timeout=60)
    record = {'scope':'OFFLINE MOCK ONLY - not live evidence'}
    for src, name, key in [
        (FRAMEWORK/'models/03_workflow_model.yaml','03_workflow_model.yaml','workflow_sha256'),
        (FRAMEWORK/'bdi/controller_agent.asl','controller_agent.asl','generated_agent_sha256'),
        (FRAMEWORK/'bdi/controller.mas2j','controller.mas2j','mas_sha256')]:
        shutil.copyfile(src, directory/name)
        record[key] = hashlib.sha256(src.read_bytes()).hexdigest()
    manifest = directory/'generation-manifest.json'
    manifest.write_text(json.dumps(record))
    runs, errors, requests = {}, [], []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass

        def reply(self, data, status=200):
            raw = json.dumps(data).encode()
            self.send_response(status); self.send_header('Content-Length', str(len(raw)))
            self.end_headers(); self.wfile.write(raw)

        def do_POST(self):
            try:
                if self.path != '/repos/offline/mock/actions/workflows/job-execution.yml/dispatches':
                    raise ValueError('Unexpected mock path')
                inputs = json.loads(self.rfile.read(int(self.headers['Content-Length'])))['inputs']
                run_id = len(runs) + 1
                result = 'success'
                if inputs['job'] == 'test':
                    receipt = run_fixture(directory/'fixture-state', directory/('probe-'+inputs['attempt']),
                        dict(scenario='S6', campaign_id=inputs['campaign_id'], release_sha=inputs['release_sha'],
                             job='test', attempt=int(inputs['attempt']), execution_id=inputs['execution_id'],
                             github_run_id=str(run_id), github_run_attempt=1, control_sha='b'*40))
                    result = receipt['result']
                runs[run_id] = {'inputs':inputs, 'fixture_result':result}
                requests.append({'timestamp':time.time(), 'run_id':run_id, **inputs})
                self.reply({'workflow_run_id':run_id})
            except Exception as error:
                errors.append(repr(error)); self.reply({'error':'mock failed'},500)

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == '/ready': return self.reply({'ready':True})
            if parsed.path == '/api/v1/query':
                q = parse_qs(parsed.query)['query'][0]
                value = 0 if q.startswith('time()') else 1 if 'min(memos_experiment_ready' in q else 10 if 'histogram_quantile' in q else 0
                return self.reply({'status':'success','data':{'resultType':'vector','result':[{'metric':{},'value':[time.time(),str(value)]}]}})
            try:
                parts = parsed.path.split('/')
                run = runs[int(parts[6])]
                if '/actions/artifacts/' in parsed.path and parsed.path.endswith('/zip'):
                    receipt={**run['inputs'],'schema_version':1,'github_run_id':int(parts[6]),
                             'github_run_attempt':1,'outcome':run['fixture_result']}
                    payload=io.BytesIO()
                    with zipfile.ZipFile(payload,'w') as archive:archive.writestr('adapter-result.json',json.dumps(receipt))
                    data=payload.getvalue();self.send_response(200);self.end_headers();self.wfile.write(data)
                elif parsed.path.endswith('/artifacts'):
                    self.reply({'total_count':1,'artifacts':[{'id':int(parts[6]),'name':'bdi-result-'+run['inputs']['execution_id'],
                               'expired':False,'size_in_bytes':500}]})
                elif parsed.path.endswith('/jobs'):
                    failed = run['fixture_result'] == 'transient_failure'
                    self.reply({'jobs':[{'name':run['inputs']['job'].capitalize()+' job',
                        'status':'completed','conclusion':'failure' if failed else 'success',
                        'steps':[{'name':'Controlled transient failure','conclusion':'failure' if failed else 'skipped'}]}]})
                else: self.reply({'status':'completed'})
            except Exception as error:
                errors.append(repr(error)); self.reply({'error':'mock failed'},500)

    with ThreadingHTTPServer(('127.0.0.1',0),Handler) as server:
        thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        base = 'http://127.0.0.1:'+str(server.server_port)
        env = {k:v for k,v in os.environ.items() if not k.startswith(('BDI_', 'GITHUB_', 'GH_', 'EXPERIMENT_'))}
        env.update(GITHUB_API_URL=base,GITHUB_REPOSITORY='offline/mock',GITHUB_TOKEN='offline-not-a-credential',
            BDI_RELEASE_SHA='a'*40,BDI_KNOWN_GOOD_SHA='c'*40,BDI_CAMPAIGN_ID='offline-s6',
            BDI_WORKFLOW_REF='offline',BDI_PROJECT_FILE=str(directory/'03_workflow_model.yaml'),
            BDI_MANIFEST_FILE=str(manifest),BDI_MAS_FILE=str(directory/'controller.mas2j'),
            BDI_RESULT_FILE=str(directory/'controller-result.json'),BDI_JOURNAL_FILE=str(directory/'controller-journal.jsonl'),
            BDI_LOCK_FILE=str(directory/'controller.lock'),BDI_EXECUTION_STATE_FILE=str(directory/'pending.json'),
            BDI_READY_URL=base+'/ready',BDI_PROMETHEUS_URL=base,BDI_GUI='false',
            BDI_LOG_CONFIG=str(FRAMEWORK/'bdi/logging.properties'))
        try:
            with (directory/'controller-console.log').open('w') as log:
                result = subprocess.run(['java','-cp',str(classes)+os.pathsep+classpath,'harness.ControllerMain'],
                    cwd=directory,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=90)
        finally:
            server.shutdown(); thread.join(timeout=5)
    (directory/'mock-dispatches.json').write_text(json.dumps(requests,indent=2))
    if errors or result.returncode:
        raise RuntimeError('Offline integration failed: '+repr(errors)+'; inspect '+str(directory))
    events = [json.loads(line) for line in (directory/'controller-journal.jsonl').read_text().splitlines()]
    test_runs = [r for r in requests if r['job']=='test']
    assert [r['attempt'] for r in test_runs] == ['1','2']
    assert test_runs[0]['execution_id'] != test_runs[1]['execution_id']
    assert any(e.get('decision')=='retry' and e.get('job')=='test' for e in events)
    assert [e['status'] for e in events if e.get('event')=='job_execution_finished' and e['job']=='test'] == ['transient_failure','success']
    assert [r['job'] for r in requests] == ['build','test','test','security','staging','production']
    assert json.loads((directory/'controller-result.json').read_text())['outcome']=='achieved'
    (directory/'validation.json').write_text(json.dumps({'scope':'OFFLINE MOCK ONLY','passed':True,
        'native_agent_and_adapter':True,'real_loopback_fixture':True,'github_or_deployment_accessed':False},indent=2))
    print('PASS: native Jason retry and distinct second dispatch; OFFLINE MOCK ONLY:',directory)


if __name__ == '__main__': main()
