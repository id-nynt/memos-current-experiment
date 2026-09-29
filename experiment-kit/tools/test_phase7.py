from test_image_identity import historical_rollback
"""Offline deterministic fault, measurement and controlled-seed verification."""
import copy
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import time
import unittest
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import scenario_runtime as s
import controlled_seed as seed
import phase5_metrics as m
from test_phase5_metrics import at
import test_phase5_metrics as fixtures
from test_phase5_instrumentation import module

ROOT=Path(__file__).resolve().parents[1]


class ScenarioTests(unittest.TestCase):
    def engine(self,name='P31',**kwargs):
        spec=copy.deepcopy(s.resolve(name))
        ident=dict(trial_id='trial',project='owned-'+spec['stage'],environment=spec['stage'],release='v2',release_sha='b'*40,image_id='sha256:'+'c'*64)
        return s.Engine(s.lease(spec,ident,0,0),ident,clock=lambda:1,**kwargs)

    def test_reproducible_rates_and_realized_counts(self):
        a,b=self.engine(),self.engine();rows=[]
        a.emit=rows.append
        for _ in range(600):
            x=a.decision('/api/v1/memos/sentinel','GET','independent');y=b.decision('/api/v1/memos/sentinel','GET','independent')
            self.assertEqual({k:v for k,v in x.items() if k!='engine_instance'},{k:v for k,v in y.items() if k!='engine_instance'});a.record(x,503 if x['injected_error'] else 200,1,True)
        report=s.summary(rows)[0]
        self.assertEqual(report['requests'],600)
        self.assertEqual(report['requested_error_percent'],30)
        self.assertTrue(.22<report['realized_error_rate']<.38)
        self.assertEqual(report['delivered_errors'],report['injected_errors'])

    def test_native_request_count_cannot_shift_independent_sequence(self):
        a,b=self.engine(),self.engine()
        for _ in range(99):a.decision('/api/v1/memos','POST')
        self.assertEqual(a.decision('/api/v1/memos/x','GET','independent')['selected_failure_positions'],b.decision('/api/v1/memos/x','GET','independent')['selected_failure_positions'])

    def test_seed_changes_sequence(self):
        a,b=self.engine(),self.engine();b.value['spec']['seed']+=1
        self.assertNotEqual([a.decision('/api/v1/memos/x','GET')['injected_error'] for _ in range(100)],
                            [b.decision('/api/v1/memos/x','GET')['injected_error'] for _ in range(100)])

    def test_scope_guards(self):
        for field,value in [('environment','staging'),('release','v1'),('image_id','foreign'),('trial_id','foreign'),('project','foreign')]:
            engine=self.engine();engine.identity={**engine.identity,field:value}
            self.assertIsNone(engine.decision('/api/v1/memos/x','GET'))
        self.assertIsNone(self.engine().decision('/healthz','GET'))

    def test_episode_edges(self):
        e=self.engine('P05')
        self.assertEqual([e.episode(t)['id'] if e.episode(t) else None for t in [0,39.999,40,59.99,60,119.9,120,300]],
                         ['e1','e1',None,None,'e2','e2',None,None])
        self.assertEqual(len(list(s.boundaries(e.value))),4)

    def test_delay_and_unchanged_threshold(self):
        with patch.object(s.time,'sleep') as sleeping:
            e=self.engine('P20',sleep=sleeping)
            e.delay(e.decision('/api/v1/memos/x','GET'));sleeping.assert_called_once_with(.8)
        self.assertIn('latency_p95_ms_high_gt: 500',(ROOT/'memos-bdi/bdi-cicd-framework/config/controller_policy.yaml').read_text())

    def test_real_short_delay(self):
        e=self.engine('P18');start=time.monotonic();e.delay(e.decision('/api/v1/memos/x','GET'))
        self.assertGreaterEqual(time.monotonic()-start,.24)

    def test_telemetry_is_not_service_failure(self):
        e=self.engine('P24')
        self.assertTrue(e.telemetry_missing())
        self.assertIsNone(e.decision('/api/v1/memos/x','GET'))
        event=dict(event='telemetry_measurement',data_status='unavailable')
        self.assertTrue(m.native_detection(event,dict(signal='telemetry')))
        self.assertFalse(m.native_detection(event,dict(signal='service')))

    def test_latency_detection_strict_threshold(self):
        event=dict(event='telemetry_measurement',data_status='fresh',readiness='ready',error_rate=0,availability=1)
        self.assertFalse(m.native_detection(dict(event,latency_p95_ms=500),{}))
        self.assertTrue(m.native_detection(dict(event,latency_p95_ms=501),{}))

    def test_multi_episode_recovery(self):
        e=self.engine('P05');e.value['start_epoch']=float(m.stamp(at(0)))
        samples=[dict(timestamp=at(t),healthy=not(t<40 or 60<=t<120)) for t in range(301)]
        rows=m.episode_metrics(e.value,samples,dict(events=[]),m.stamp(at(300)),dict(minimum_samples=3,minimum_span_seconds=10,maximum_gap_seconds=15))
        self.assertEqual([x['recovery_onset'] for x in rows],[at(40),at(120)])
        self.assertEqual([x['recovery_confirmation'] for x in rows],[at(50),at(130)])
        self.assertFalse(any(x['censored'] for x in rows))

    def test_short_gap_cannot_confirm_recovery(self):
        e=self.engine('P05');e.value['start_epoch']=float(m.stamp(at(0)));e.value['spec']['episodes'][1]['start']=45
        samples=[dict(timestamp=at(t),healthy=40<=t<45 or t>=120) for t in range(301)]
        rows=m.episode_metrics(e.value,samples,dict(events=[]),m.stamp(at(300)),dict(minimum_samples=3,minimum_span_seconds=10,maximum_gap_seconds=15))
        self.assertTrue(rows[0]['censored']);self.assertIsNone(rows[0]['recovery_confirmation'])

    def test_all_catalogue_entries_and_copies(self):
        self.assertGreaterEqual(len(s.catalogue()),30)
        for value in s.catalogue().values():
            if value['status']=='implemented_ci':
                self.assertEqual(value['stage'],'ci');self.assertIn(value['execution_scenario'],('CI01','CI02','CI03'))
                with self.assertRaises(ValueError):s.validate(value)  # never a proxy lease
            else:s.validate(value)
        for directory in ['memos-current/experiment','memos-bdi/experiment/scripts']:
            for name in ['scenario_runtime.py','scenario-catalogue.json']:
                self.assertEqual((ROOT/'tools'/name).read_bytes(),(ROOT/directory/name).read_bytes())
        for name in ['P26','P27','P29']:
            with self.assertRaises(ValueError):s.resolve(name)

    def test_invalid_schedules_rejected(self):
        for field,value in [('error_percent',101),('delay_ms',float('nan')),('end',301),('start',-1)]:
            spec=copy.deepcopy(s.resolve('P02'));spec['episodes'][0][field]=value
            with self.assertRaises(ValueError):s.validate(spec)

    def test_sealed_evidence_unchanged(self):
        for p,digest in json.loads((ROOT/'results/implementation/phase7/before-evidence.json').read_text()).items():
            self.assertEqual(hashlib.sha256((ROOT/p).read_bytes()).hexdigest(),digest)

    def test_new_normalizer_staging_is_separate_and_cost_excludes_reset(self):
        fixture=fixtures.Metrics();fixture.setUp()
        try:
            output=[]
            for arm in ('conventional','bdi'):
                spec=fixture.fixture(arm);root=Path(spec['evidence_directory'])
                spec['window']['end']=at(300);spec['scenario_contract']=s.VERSION
                ident=dict(trial_id='trial',project='owned-staging',environment='staging',release='v2',
                    release_sha=fixture.releases['v2']['application_sha'],image_id=fixture.releases['v2']['image_id'])
                fixture.write(root,'scenario-schedule.json',s.lease(s.resolve('P16'),ident,float(m.stamp(at(0))),0))
                fixture.write(root,'reset-state.json',dict(data_semantics='shared-controlled-seed',archive_sha256='e'*64,
                    application_sha=fixture.releases['v1']['application_sha'],image_id=fixture.releases['v1']['image_id'],verified=True,
                    role='infrastructure-reset',treatment_cost=False))
                workload=[json.loads(x) for x in (root/'workload.jsonl').read_text().splitlines()]
                samples=[json.loads(x) for x in (root/'common-observations.jsonl').read_text().splitlines()]
                fixture.write(root,'staging-workload.jsonl',[dict(x,status=503,response_valid=None,content_matches=None,failure_category='http_5xx') for x in workload],True)
                fixture.write(root,'staging-observations.jsonl',[dict(x,healthy=False) for x in samples],True)
                result=m.normalize(spec);output.append(result)
                self.assertEqual(result['reliability']['requests_failed'],0)
                self.assertEqual(result['staging']['failed'],31)
                self.assertEqual(result['cost']['candidate_seconds'],10)
                self.assertTrue(result['episodes'][0]['censored'])
            self.assertEqual(output[0]['reliability']['requests_total'],output[1]['reliability']['requests_total'])
            output[1]['controlled_seed_sha256']='f'*64
            with self.assertRaisesRegex(ValueError,'seed'):m.aggregate(output)
        finally:fixture.doCleanups()

    def test_contiguous_severity_changes_are_not_clearance(self):
        engine=self.engine('P13')
        events=list(s.boundaries(engine.value))
        self.assertEqual([e['event'] for e in events],['episode_started','episode_ended','episode_started','episode_ended','episode_started','episode_cleared'])

    def test_worker_functions_unchanged_except_adapter_catalogue_hash(self):
        import ast
        def funcs(path):return {x.name:ast.dump(x) for x in ast.parse(path.read_text()).body if isinstance(x,ast.FunctionDef)}
        old=funcs(ROOT/'results/implementation/phase7/before-7.txt');new=funcs(ROOT/'memos-bdi/experiment/scripts/operate.py')
        self.assertEqual([k for k in old if old[k]!=new[k]],['build', 'adapter_source_hash', 'deploy', 'rollback'])

    def test_bdi_activation_and_cleanup_keep_campaign_and_operator_ids_distinct(self):
        scenarios=module('phase7_activation',ROOT/'memos-bdi/experiment/scripts/scenarios.py')
        with tempfile.TemporaryDirectory() as tmp:
            state=Path(tmp);evidence=state/'evidence';evidence.mkdir()
            arm=dict(scenario='P16',trial_id='operator-trial',directory=str(evidence))
            expected=dict(trial_id='native-campaign',project=scenarios.project_name('staging'),environment='staging',
                release='v2',release_sha='b'*40,image_id='sha256:'+'c'*64,control_sha='a'*40)
            with patch.object(scenarios,'selected',return_value=arm):
                scenarios.activate(state,'bdi',expected,evidence)
                self.assertFalse((state/'bdi/production/fault/active.json').exists())
                path=state/'bdi/staging/fault/active.json';value=json.loads(path.read_text())
                self.assertEqual(value['target']['trial_id'],'native-campaign')
                self.assertEqual(value['owner_trial_id'],'operator-trial')
                with self.assertRaises(ValueError):scenarios.clear_matching(state,'bdi','operator-trial',evidence)
                with patch.object(scenarios.time,'time',return_value=value['end_epoch']+1):
                    with self.assertRaises(ValueError):scenarios.clear_matching(state,'bdi','foreign-trial',evidence)
                    self.assertTrue(path.exists())
                    scenarios.clear_matching(state,'bdi','operator-trial',evidence)
                self.assertFalse(path.exists())

    def test_conventional_policy_unchanged_except_environment_hook(self):
        old=(ROOT/'results/implementation/phase7/before-4.txt').read_text()
        # Preserve the Phase 7 comparison; Linux plumbing is bounded separately
        # against this SHA-verified checkpoint by test_server_execution.
        new=(ROOT/'results/implementation/server-preparation/before/deploy.ps1').read_text()
        old_lines=[x for x in old.splitlines() if 'if ($Experiment -and $Environment -eq 1 -and $env:MEMOS_FIXTURE_DIRECTORY)' not in x]
        new_lines=[x for x in new.splitlines() if "if ($Experiment -and (@('staging', 'production')[$Environment]" not in x]
        self.assertEqual(old_lines,new_lines)


class SeedTests(unittest.TestCase):
    def test_import_identical_seed_and_tamper_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'conventional';(source/'seed').mkdir(parents=True)
            (source/'credentials/staging').mkdir(parents=True)
            with tarfile.open(source/'seed/data.tar.gz','w:gz') as tar:
                item=tarfile.TarInfo('memos_prod.db');item.size=4;tar.addfile(item,io.BytesIO(b'data'))
            v1=dict(application_sha='b'*40)
            (source/'seed/manifest.json').write_text(json.dumps(dict(owner='memos-current-experiment',application_sha=v1['application_sha'],archive_sha256=seed.digest(source/'seed/data.tar.gz'))))
            (source/'credentials/staging/credential.json').write_text(json.dumps(dict(token='synthetic',sentinel_name='memos/test',sentinel_content='sentinel')))
            value=seed.import_seed(source,root/'bdi',v1)
            self.assertEqual(value['manifest']['archive_sha256'],seed.digest(source/'seed/data.tar.gz'))
            (root/'bdi/data.tar.gz').write_bytes(b'changed')
            with self.assertRaises(ValueError):seed.validate(root/'bdi',v1)

    def test_restore_scoped_no_pull_and_not_rollback(self):
        command=seed.helper_command('sha256:abc','memos-experiment-bdi-staging_data',Path('.'),'restore')
        self.assertIn('never',command);self.assertIn(seed.RESTORE,command)
        with self.assertRaises(ValueError):seed.helper_command('sha256:abc','foreign_data',Path('.'),'restore')
        import ast
        def rollback(p):return ast.dump(next(n for n in ast.parse(historical_rollback(p.read_text())).body if isinstance(n,ast.FunctionDef) and n.name=='rollback'))
        self.assertEqual(rollback(ROOT/'results/implementation/phase7/before-7.txt'),rollback(ROOT/'memos-bdi/experiment/scripts/operate.py'))


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.identity=dict(trial_id='trial',project='owned-production',environment='production',release='v2',release_sha='b'*40,image_id='sha256:'+'c'*64,deploymentRunId='test-deployment')
        commit=self.identity['release_sha']
        class Backend(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                body=json.dumps({'commit':commit,'content':'expected'}).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        self.backend=ThreadingHTTPServer(('127.0.0.1',0),Backend)
        threading.Thread(target=self.backend.serve_forever,daemon=True).start()
        self.addCleanup(self.backend.server_close);self.addCleanup(self.backend.shutdown)

    def test_actual_bdi_proxy_delay_and_missing_metrics(self):
        original=Path.read_text
        with patch.object(Path,'read_text',lambda p,*a,**kw:json.dumps(self.identity) if str(p)=='/state/identity.json' else original(p,*a,**kw)):
            proxy=module('phase7_http_proxy',ROOT/'memos-bdi/experiment/scripts/proxy.py')
        proxy.BACKEND='http://127.0.0.1:'+str(self.backend.server_port)
        engine=s.Engine(s.lease(s.resolve('P18'),self.identity,0,0),self.identity,clock=lambda:1)
        server=ThreadingHTTPServer(('127.0.0.1',0),proxy.Handler)
        with patch.object(proxy,'scheduled_engine',return_value=engine),patch.object(proxy,'event'):
            threading.Thread(target=server.serve_forever,daemon=True).start()
            try:
                start=time.monotonic()
                with urllib.request.urlopen('http://127.0.0.1:'+str(server.server_port)+'/api/v1/memos/test') as response:
                    self.assertEqual(response.status,200);self.assertEqual(json.load(response)['content'],'expected')
                self.assertGreaterEqual(time.monotonic()-start,.24)
                engine.value['spec']=s.resolve('P24')
                with self.assertRaises(urllib.error.HTTPError) as result:
                    urllib.request.urlopen('http://127.0.0.1:'+str(server.server_port)+'/metrics')
                self.assertEqual(result.exception.code,503);result.exception.close()
                with urllib.request.urlopen('http://127.0.0.1:'+str(server.server_port)+'/api/v1/memos/test') as response:self.assertEqual(response.status,200)
            finally:server.shutdown();server.server_close()

    def test_actual_conventional_proxy_injects_and_protects_v1(self):
        fixture_module=module('phase7_conventional_proxy',ROOT/'memos-current/experiment/runtime_fixture.py')
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            fixture=fixture_module.Fixture(directory,'P02',dict(application_sha=self.identity['release_sha'],image_identity=self.identity['image_id']),None)
            fixture.backend_port=self.backend.server_port;fixture.public_port=0
            fixture_module.atomic(directory/'fixture-up.json',{})
            fixture_module.atomic(directory/'fixture-startup-ready.json',dict(timestamp=fixture_module.stamp()))
            fixture.thread=threading.Thread(target=fixture.serve,daemon=True);fixture.thread.start()
            try:
                deadline=time.monotonic()+3
                while not (directory/'fixture-start.json').exists() and time.monotonic()<deadline:time.sleep(.01)
                self.assertIsNotNone(fixture.engine)
                base='http://127.0.0.1:'+str(fixture.server.server_port)
                with self.assertRaises(urllib.error.HTTPError) as result:urllib.request.urlopen(base+'/api/v1/memos/test')
                self.assertEqual(result.exception.code,503);result.exception.close()
                fixture.config['application_sha']='v1-does-not-match'
                with urllib.request.urlopen(base+'/api/v1/memos/test') as response:self.assertEqual(response.status,200)
            finally:
                fixture.stop.set();fixture.thread.join(timeout=3)
                if fixture.server:fixture.server.shutdown();fixture.server.server_close()


if __name__=='__main__':unittest.main()
