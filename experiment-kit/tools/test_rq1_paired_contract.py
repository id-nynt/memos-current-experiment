"""Offline-only contract/regression checks. No Docker, GitHub or live faults."""
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import paired_rq1 as p


class PairedContractTests(unittest.TestCase):
    def setUp(self):
        self.identity = dict(environment='production', release_sha=p.contract()['v2'],
                             image_id=p.contract()['v2_image'], trial_id='campaign-test',
                             project='isolated-production', deploymentRunId='first')
        self.schedule = p.create('S4R', self.identity, 'trial-test', 1000, 100)

    def test_contract_and_module_identical(self):
        canonical = (ROOT / 'protocol/rq1-s4r-s5r.json').read_bytes()
        for folder in ['tools', 'memos-current/experiment', 'memos-bdi/experiment/scripts']:
            self.assertEqual(canonical, (ROOT / folder / 'rq1-s4r-s5r.json').read_bytes())
            self.assertEqual((ROOT / 'tools/paired_rq1.py').read_bytes(), (ROOT / folder / 'paired_rq1.py').read_bytes())

    def test_s4_boundary_all_replacements(self):
        for execution in ['first', 'recreated', 'again']:
            identity = dict(self.identity, deploymentRunId=execution)
            for seconds in [0, 328, 600, 899.999]:
                self.assertTrue(p.active(self.schedule, identity, seconds))
            self.assertFalse(p.active(self.schedule, identity, 900))

    def test_v1_other_trial_environment_image_exempt(self):
        for field, value in [('release_sha', p.contract()['v1']), ('trial_id', 'other'),
                             ('environment', 'staging'), ('project', 'other'), ('image_id', 'other')]:
            self.assertFalse(p.active(self.schedule, dict(self.identity, **{field: value}), 328))

    def test_rollback_guard_does_not_change_schedule(self):
        before=copy.deepcopy(self.schedule)
        p.worker_guard(self.schedule, self.identity, p.contract()['v1'],'campaign-test')
        p.worker_guard(self.schedule, dict(self.identity, deploymentRunId='new'), p.contract()['v2'],'campaign-test')
        self.assertEqual(before, self.schedule)
        self.assertTrue(p.active(self.schedule,self.identity,350))
        with self.assertRaises(ValueError):p.worker_guard(self.schedule,dict(self.identity,trial_id='foreign'),p.contract()['v1'],'campaign-test')

    def test_cleanup_not_at_endpoint(self):
        for t in [0,328,600,899.999]:self.assertFalse(p.clearance_allowed(self.schedule,t))
        self.assertTrue(p.clearance_allowed(self.schedule,900))

    def test_s5_schedule_exact(self):
        s=p.create('S5R',self.identity,'trial-test',1000,100)
        for t,want in [(0,True),(59.9,True),(60,False),(69.9,False),(70,True),(189.9,True),(190,False),(600,False)]:
            self.assertEqual(p.active(s,self.identity,t),want)

    def test_clock_reboot_refused(self):
        with patch.object(p,'boot_id',return_value='different'):
            with self.assertRaises(ValueError):p.elapsed(self.schedule)

    def test_early_terminal_is_not_extended(self):
        result=p.opportunity(0,'1970-01-01T00:01:00Z',[], 'S5R')
        self.assertEqual(result['classification'],'terminated_before_relapse')
        self.assertIsNone(result['changed_evidence_received'])

    def test_probe_start_not_changed_state(self):
        result=p.opportunity(0,'1970-01-01T00:02:00Z',[{'timestamp':'1970-01-01T00:01:15Z','event':'health_observation'}],'S5R')
        self.assertEqual(result['classification'],'native_probe_started_during_relapse')
        self.assertIsNone(result['changed_evidence_received'])

    def test_fresh_native_transition_and_postterminal_excluded(self):
        events=[dict(timestamp='1970-01-01T00:01:05Z',event='telemetry_measurement',data_status='fresh',error_rate=0),
                dict(timestamp='1970-01-01T00:01:15Z',event='telemetry_measurement',data_status='fresh',error_rate=1)]
        self.assertTrue(p.opportunity(0,'1970-01-01T00:02:00Z',events,'S5R')['changed_evidence_received'])
        self.assertIsNone(p.opportunity(0,'1970-01-01T00:01:10Z',events,'S5R')['changed_evidence_received'])

    def test_historical_bdi_evidence_and_conventional_files_unchanged(self):
        import zipfile
        before=json.loads((ROOT/'results/implementation/s4r-s5r/source-before.json').read_text())
        for repo,data in before.items():
            for name,digest in data['files'].items():
                protected=(name.startswith('bdi-cicd-framework/') or name.startswith('scripts/local-cd/')
                           or name in ['experiment/frozen-releases.json','experiment/frozen-control.json']
                           or (name.startswith('.github/workflows/') and Path(name).name!='frozen-cd.yml'))
                if protected:
                    # Later approved phases change current source, not historical snapshots.
                    with zipfile.ZipFile(ROOT/'results/implementation/s4r-s5r'/f'{repo}-before.zip') as archive:
                        content=archive.read(name)
                    self.assertEqual(hashlib.sha256(content).hexdigest(),digest,name)

    def test_historical_names_retained_but_not_final_executable(self):
        from final_timing import require_current_scenario
        for name in ('S3','S4','S5','S4R','S5R'):
            with self.assertRaises(ValueError):require_current_scenario(name)
        scenarios=json.loads((ROOT/'memos-current/experiment/scenarios.json').read_text())
        self.assertIn('S4R',scenarios);self.assertIn('S5R',scenarios)

    def test_bdi_clear_guard_blocks_real_temp_file(self):
        sys.path.insert(0,str(ROOT/'memos-bdi/experiment/scripts'))
        import scenarios
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'bdi/production/fault';folder.mkdir(parents=True)
            file=folder/'active.json';file.write_text(json.dumps(self.schedule))
            with patch.object(p,'elapsed',return_value=600):
                with self.assertRaises(ValueError):scenarios.clear_matching(temp,'bdi','trial-test',Path(temp)/'evidence')
            self.assertTrue(file.exists())
            with patch.object(p,'elapsed',return_value=900):scenarios.clear_matching(temp,'bdi','trial-test',Path(temp)/'evidence')
            self.assertFalse(file.exists())

    def test_bdi_worker_revised_branch_has_no_clear(self):
        worker=(ROOT/'memos-bdi/experiment/scripts/operate.py').read_text()
        self.assertIn('retain_fault_for_recovery(',worker)
        tree=ast.parse((ROOT/'memos-bdi/experiment/scripts/scenarios.py').read_text())
        branch=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='retain_fault_for_recovery')
        revised=ast.unparse(branch)
        self.assertNotIn('unlink',revised);self.assertIn('worker_guard',revised)

    def test_reactivation_keeps_original_bytes(self):
        sys.path.insert(0,str(ROOT/'memos-bdi/experiment/scripts'))
        import paired_owner
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)/'bdi/production/fault';folder.mkdir(parents=True)
            file=folder/'active.json';file.write_text(json.dumps(self.schedule));before=file.read_bytes()
            with patch.object(paired_owner,'event'):
                paired_owner.request_activation(temp,{'trial_id':'trial-test'},
                    dict(self.identity,deploymentRunId='replacement'),Path(temp))
            self.assertEqual(file.read_bytes(),before)

    def test_fixed_endpoint_and_expiry_wait_without_real_wait(self):
        sys.path.insert(0,str(ROOT/'memos-bdi/experiment/scripts'))
        # Exercise the retained historical observer, not the new 300-second path.
        import types, subprocess
        observe=types.ModuleType('historical_observe')
        observe.__file__=str(ROOT/'memos-bdi/experiment/scripts/observe.py')
        source=subprocess.check_output(['git','-C',str(ROOT/'memos-bdi'),'show',
            '4d0b382df14bf674b483ef35d3a17486fd840385:experiment/scripts/observe.py']).decode()
        exec(compile(source,observe.__file__,'exec'),observe.__dict__)
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/'fault-events.jsonl').write_text(json.dumps({'event':'switch_written','start_epoch':1000})+'\n')
            samples=[{'timestamp':__import__('datetime').datetime.fromtimestamp(t,__import__('datetime').timezone.utc).isoformat(),
                      'healthy':True,'release_sha':p.contract()['v2']} for t in [1571,1580,1590,1599]]
            (root/'common-observations.jsonl').write_text(''.join(json.dumps(s)+'\n' for s in samples))
            observer=observe.TrialObserver({},root,'S4R')
            observer.thread=Mock();observer.thread.is_alive.return_value=False
            observer.workload=Mock();observer.workload.is_alive.return_value=False
            clock=[1605.0]
            def sleep(seconds):clock[0]+=seconds
            with patch.object(observe.time,'time',side_effect=lambda:clock[0]),patch.object(observe.time,'sleep',side_effect=sleep),patch.object(observe,'sample',return_value={'healthy':True}),patch.object(observe,'event'):
                observer.finish()
            self.assertGreaterEqual(clock[0],1900)
            self.assertEqual(json.loads((root/'endpoint.json').read_text())['endpoint_epoch'],1600)

    def test_conventional_early_cleanup_waits_offline(self):
        spec=importlib.util.spec_from_file_location('rq1_fixture',ROOT/'memos-current/experiment/runtime_fixture.py')
        fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
        with tempfile.TemporaryDirectory() as temp:
            f=fixture.Fixture(temp,'S4R',{},None);f.started=100
            clock=[700.0]
            with patch.object(fixture.time,'monotonic',side_effect=lambda:clock[0]),patch.object(fixture.time,'sleep',side_effect=lambda seconds:clock.__setitem__(0,clock[0]+seconds)):
                f.close()
            self.assertGreaterEqual(clock[0],1000)

    def test_historical_scenario_definitions_retained(self):
        import zipfile
        for repo,name in [('memos-current','experiment/scenarios.json'),('memos-bdi','experiment/protocol.json')]:
            with zipfile.ZipFile(ROOT/'results/implementation/s4r-s5r'/f'{repo}-before.zip') as z:old=json.loads(z.read(name))
            new=json.loads((ROOT/repo/name).read_text())
            if repo=='memos-bdi':old,new=old['scenarios'],new['scenarios']
            for scenario in ['S0','S1','S2','S3','S4','S5']:self.assertEqual(old[scenario],new[scenario])

    def test_owner_does_not_activate_after_ack_timeout(self):
        sys.path.insert(0,str(ROOT/'memos-bdi/experiment/scripts'))
        import paired_owner, observe
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'bdi/production/fault';root.mkdir(parents=True)
            (root/'paired-request.json').write_text(json.dumps(dict(trial_id='trial-test',expected=self.identity,requested_monotonic=0)))
            stop=Mock();stop.wait.return_value=False
            with patch.object(observe,'sample',return_value=dict(healthy=True,release_sha=p.contract()['v2'],image_id=p.contract()['v2_image'])),patch.object(paired_owner.time,'monotonic',return_value=3):
                with self.assertRaises(ValueError):paired_owner.own_schedule({'state':temp},Path(temp)/'evidence',{'scenario':'S4R','trial_id':'trial-test'},stop)
            self.assertFalse((root/'active.json').exists())

    def test_owner_interruption_retains_schedule_and_fails(self):
        sys.path.insert(0,str(ROOT/'memos-bdi/experiment/scripts'))
        import paired_owner, observe
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'bdi/production/fault';root.mkdir(parents=True)
            (root/'paired-request.json').write_text(json.dumps(dict(trial_id='trial-test',expected=self.identity,requested_monotonic=100)))
            stop=Mock();stop.wait.side_effect=[False,True]
            with patch.object(observe,'sample',return_value=dict(healthy=True,release_sha=p.contract()['v2'],image_id=p.contract()['v2_image'])),patch.object(paired_owner.time,'monotonic',return_value=100):
                with self.assertRaises(ValueError):paired_owner.own_schedule({'state':temp},Path(temp)/'evidence',{'scenario':'S4R','trial_id':'trial-test'},stop)
            self.assertEqual(json.loads((root/'active.json').read_text())['owner'],'operator-harness')


if __name__=='__main__':unittest.main(verbosity=2)
