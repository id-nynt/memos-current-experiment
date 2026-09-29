"""Offline S6 regression tests. Temporary loopback HTTP only; never dispatches CI."""
import contextlib
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import shutil
import uuid
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'memos-bdi/experiment/scripts'
sys.path.insert(0, str(SCRIPTS))
import s6_fixture as fixture
import s6_approval


@contextlib.contextmanager
def temporary_directory():
    parent = (ROOT / 'results/implementation/s6-preparation/unit-tmp').resolve()
    path = parent / uuid.uuid4().hex
    path.mkdir(parents=True)
    try:
        yield str(path)
    finally:
        path.resolve().relative_to(parent)
        shutil.rmtree(path)


def identity(attempt=1):
    return dict(scenario='S6', campaign_id='offline-unit', release_sha='a'*40,
                control_sha='b'*40, entity='test', attempt=attempt,
                execution_id='exec-' + str(attempt), github_run_id=str(attempt), github_run_attempt=1)


class FixtureTest(unittest.TestCase):
    def test_current_ci_identity_retained_across_native_retry(self):
        first=self.probe(scenario='CI01')
        second=self.probe(2,scenario='CI01')
        self.assertEqual(first['identity']['scenario'],'CI01')
        self.assertEqual(first['primary_status'],503)
        self.assertEqual(second['primary_status'],200)

    def test_historical_receipt_cannot_be_used_by_current_ci(self):
        self.probe()
        with self.assertRaises(ValueError):self.probe(2,scenario='CI01')
    def setUp(self):
        self.tmp = temporary_directory()
        self.root = Path(self.tmp.__enter__())
        self.addCleanup(self.tmp.__exit__, None, None, None)

    def probe(self, attempt=1, **overrides):
        return fixture.run_fixture(self.root/'state', self.root/('evidence-'+str(attempt)),
                                   dict(identity(attempt), **overrides))

    def test_actual_503_clears_without_any_retry_then_new_execution_passes(self):
        first = self.probe()
        self.assertEqual([503, 200], [r['status'] for r in first['responses']])
        self.assertEqual('transient_failure', first['result'])
        self.assertTrue((self.root/'state/consumed.json').exists())
        second = self.probe(2)
        self.assertEqual([200, 200], [r['status'] for r in second['responses']])
        self.assertEqual('success', second['result'])
        self.assertIsNotNone(second['previous_receipt_sha256'])

    def test_second_attempt_without_first_is_invalid(self):
        with self.assertRaises(FileNotFoundError): self.probe(2)

    def test_foreign_campaign_cannot_reuse_clearance(self):
        self.probe()
        with self.assertRaises(ValueError): self.probe(2, campaign_id='another')

    def test_manual_github_rerun_is_invalid(self):
        with self.assertRaises(ValueError): self.probe(github_run_attempt=2)

    def test_execution_identity_must_change(self):
        self.probe()
        with self.assertRaises(ValueError): self.probe(2, execution_id='exec-1')

    def test_native_attempt_cannot_be_replayed(self):
        self.probe()
        with self.assertRaises(ValueError): self.probe()

    def test_exhausted_attempt_is_invalid(self):
        with self.assertRaises(ValueError): self.probe(3)

    def test_server_setup_error_never_produces_transient_result(self):
        with patch.object(fixture, 'HTTPServer', side_effect=OSError('offline injected setup failure')):
            with self.assertRaises(OSError): self.probe()
        self.assertFalse((self.root/'evidence-1/s6-receipt.json').exists())
        self.assertTrue((self.root/'state/fixture.lock').exists())

    def test_tampered_clearance_is_invalid(self):
        self.probe()
        path = self.root/'state/attempt-1.json'
        value = json.loads(path.read_text()); value['clearance_status'] = 503
        path.write_text(json.dumps(value))
        with self.assertRaises(ValueError): self.probe(2)


class IntegrationTest(unittest.TestCase):
    def test_current_ci_uses_normal_study_authorization(self):
        import scenarios
        with temporary_directory() as tmp:
            state=Path(tmp)
            record=dict(human_approved=True,bdi_healthy_verified=True,
                        v2_sha=scenarios.PROTOCOL['pair']['v2'],bdi_control_sha='b'*40,
                        protocol_sha256=hashlib.sha256((scenarios.ROOT/'protocol.json').read_bytes()).hexdigest())
            (state/'approved-study.json').write_text(json.dumps(record))
            with patch.object(s6_approval,'approved_s6',side_effect=AssertionError('historical gate')):
                self.assertEqual(scenarios.approved(state,'bdi','b'*40,'CI01'),record)
            record['bdi_healthy_verified']=False
            (state/'approved-study.json').write_text(json.dumps(record))
            with self.assertRaises(ValueError):scenarios.approved(state,'bdi','b'*40,'CI01')
    def test_conventional_frozen_deployment_and_upstream_checks_unchanged(self):
        repo=ROOT/'memos-current'
        frozen=json.loads((repo/'experiment/frozen-control.json').read_text())
        for name,expected in frozen['files'].items():
            self.assertEqual(expected,hashlib.sha256((repo/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest(),name)

    def test_no_fault_phase8_can_establish_healthy_approval_but_fault_cannot(self):
        import scenarios
        with temporary_directory() as tmp:
            self.assertTrue(scenarios.approved(tmp,'bdi','b'*40,'P8001')['healthy_reference'])
            with self.assertRaises(FileNotFoundError):scenarios.approved(tmp,'bdi','b'*40,'P8006')

    def test_authorization_requires_actual_v1_baseline_not_s0_candidate(self):
        with temporary_directory() as tmp:
            p=Path(tmp); (p/'controller').mkdir()
            v1=json.loads((ROOT/'memos-bdi/experiment/protocol.json').read_text())['pair']['v1']
            trial=dict(mode='baseline',scenario='healthy',application_sha=v1,control_sha='b'*40,
                       config={'repository':'offline/mock'})
            receipt=dict(approach='bdi',control_sha='b'*40,environments={
                e:dict(verified=True,release_sha=v1,control_sha='b'*40) for e in ('staging','production')})
            result=dict(mode='github',outcome='achieved',release_sha=v1,repository='offline/mock')
            for name,data in [('trial.json',trial),('reset-receipt.json',receipt),
                              ('controller/controller-result.json',result),('remote-terminal.json',{'github_runs':[1]})]:
                (p/name).write_text(json.dumps(data))
            self.assertEqual(receipt,s6_approval.check_baseline(p,'b'*40,'offline/mock'))
            trial['mode']='candidate'; (p/'trial.json').write_text(json.dumps(trial))
            with self.assertRaises(ValueError): s6_approval.check_baseline(p,'b'*40,'offline/mock')

    def test_unarmed_gate_has_no_fixture_side_effect(self):
        import s6_gate
        with patch.dict('os.environ',{'TRIAL_ID':'unit','RELEASE_SHA':'a'*40}), \
             patch.object(s6_gate.subprocess,'check_output',return_value='b'*40), \
             patch.object(s6_gate,'selected',return_value=None), \
             patch.object(s6_gate,'run_fixture') as probe:
            s6_gate.main()
            probe.assert_not_called()

    def test_old_workflow_jobs_unchanged(self):
        for repo, path, baseline, target in [
            ('memos-current','.github/workflows/frozen-cd.yml','d6900c6553484e6503d0c88a684eb0a973975f6f','fixture'),
            ('memos-bdi','.github/workflows/entity-execution.yml','4d0b382df14bf674b483ef35d3a17486fd840385','test')]:
            old=yaml.safe_load(subprocess.check_output(['git','show',baseline+':'+path],cwd=ROOT/repo))
            current=yaml.safe_load((ROOT/repo/path).read_text())
            for name,job in old['jobs'].items():
                if name != target:
                    # Approved Phase 11 placement/routing only; job bodies remain protected.
                    expected = dict(job)
                    if expected.get('runs-on') == 'ubuntu-latest':
                        expected['runs-on']=['self-hosted','linux','memos-bdi-deploy']
                    if expected.get('uses','').startswith('./.github/workflows/') and expected['uses'].split('/')[-1] in ('backend-tests.yml','frontend-tests.yml','proto-linter.yml','upgrade-smoke.yml'):
                        expected['uses']=expected['uses'].replace('/workflows/','/workflows/experiment-')
                    # Phase 5 keeps artifact-upload failure separate from native outcome.
                    if name == 'upgrade':
                        expected['with'] = dict(expected['with'], previous_image='neosmemo/memos@sha256:24c2707ddd8fbd2ceaa7a61ecab86a53cdcde640b24ce572b73da14b00b5785f')
                    for step in expected.get('steps',[]):
                        if step.get('uses','').startswith('actions/upload-artifact@'):
                            actual=next(x for x in current['jobs'][name]['steps'] if x.get('uses')==step['uses'] and x.get('with',{}).get('name')==step.get('with',{}).get('name'))
                            if actual.get('continue-on-error') is True:step['continue-on-error']=True
                    actual = dict(current['jobs'][name])
                    if repo == 'memos-current' and name == 'deploy':
                        expected['runs-on']=['self-hosted','linux','memos-bdi-deploy']
                        for step in expected['steps']:
                            if step.get('name')=='Deliver frozen image through conventional stages':
                                step['shell']='bash'
                                step['run']='python3 experiment/runtime_fixture.py\n'
                        # Approved permanent build-boundary fixture and its evidence
                        # upload are additional controls, not deployment policy.
                        actual['steps'] = [step for step in actual['steps']
                            if step.get('name') != 'Explicit permanent build control'
                            and step.get('with',{}).get('name') != 'build-control-${{ inputs.trial_id }}']
                    self.assertEqual(expected,actual)

    def test_offline_evidence_cannot_pass_as_live(self):
        from check_s6_evidence import assess
        with temporary_directory() as tmp:
            directory=Path(tmp); (directory/'OFFLINE_MOCK_ONLY.txt').write_text('unit test')
            with self.assertRaises(ValueError): assess(directory,'bdi')

    def test_same_underlying_fixture_bytes(self):
        self.assertEqual((SCRIPTS/'s6_fixture.py').read_bytes(),
                         (ROOT/'memos-current/experiment/s6_fixture.py').read_bytes())

    def test_transient_marker_is_only_reached_from_successful_measured_probe(self):
        worker = yaml.safe_load((ROOT/'memos-bdi/.github/workflows/entity-execution.yml').read_text())
        steps = worker['jobs']['test']['steps']
        probe = next(s for s in steps if s.get('id') == 's6')
        marker = next(s for s in steps if s.get('run') == 'exit 42')
        self.assertEqual("steps.s6.outputs.result != '' && steps.s6.outputs.result != 'success'", marker['if'])
        self.assertNotIn('continue-on-error', probe)
        self.assertNotIn('always()', marker['if'])
        self.assertLess(steps.index(probe), steps.index(marker))
        self.assertEqual('${{ inputs.attempt }}', probe['env']['ENTITY_ATTEMPT'])
        self.assertIn("assert os.environ['FAILURE_MODE'] == 'none'", (SCRIPTS/'validate_dispatch.py').read_text())

    def test_old_scenario_definitions_unchanged(self):
        for repo, path, key in [('memos-current','experiment/scenarios.json',None),
                                ('memos-bdi','experiment/protocol.json','scenarios')]:
            baseline = {'memos-current':'d6900c6553484e6503d0c88a684eb0a973975f6f',
                        'memos-bdi':'4d0b382df14bf674b483ef35d3a17486fd840385'}[repo]
            original = json.loads(subprocess.check_output(['git','show',baseline+':'+path], cwd=ROOT/repo))
            current = json.loads((ROOT/repo/path).read_text())
            if key:
                self.assertEqual(original[key],{k:current[key][k] for k in original[key]})
            else:
                self.assertEqual(original,{k:current[k] for k in original})

    def test_v1_is_exempt_in_existing_arm_selection(self):
        import scenarios
        with temporary_directory() as tmp:
            root = Path(tmp); (root/'bdi').mkdir()
            (root/'bdi/armed-scenario.json').write_text(json.dumps({'scenario':'S6'}))
            self.assertIsNone(scenarios.selected(root,'bdi','unused',scenarios.PROTOCOL['pair']['v1'],'unused'))

    def test_s6_does_not_use_legacy_healthy_validation_approval(self):
        import scenarios
        with patch.object(s6_approval, 'approved_s6', return_value={'scenario':'S6'}) as approve:
            self.assertEqual({'scenario':'S6'}, scenarios.approved('state','bdi','sha','S6'))
            approve.assert_called_once_with('state','sha')
        with temporary_directory() as tmp:
            with self.assertRaises(FileNotFoundError): scenarios.approved(tmp,'bdi','sha','S1')


if __name__ == '__main__':
    unittest.main()
