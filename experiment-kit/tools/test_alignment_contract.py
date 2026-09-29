"""Cross-arm measurement semantics and immutable release-contract checks."""
import importlib.util
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('measurement', ROOT / 'tools/measure_trial.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Alignment(unittest.TestCase):
    def test_release_objects_and_reviewed_measurement_contracts(self):
        pair = m.read(ROOT / 'protocol/frozen-releases.json')
        for repo, manifest in [('memos-current', 'scripts/local-cd/frozen-releases.json'), ('memos-bdi', 'experiment/frozen-releases.json')]:
            self.assertEqual(pair, m.read(ROOT / repo / manifest))
            for release in pair['releases'].values():
                tree = subprocess.check_output(['git', '-C', str(ROOT/repo), 'rev-parse', release['application_sha']+'^{tree}'], text=True).strip()
                self.assertEqual(tree, release['tree'])
                self.assertEqual(release['version'], 'local-' + release['application_sha'])
            measurement = 'experiment/measurement' if repo == 'memos-bdi' else 'scripts/experiment-measurement'
            if repo == 'memos-bdi':
                # The BDI adapter intentionally uses Compose identity and native journals.
                # Byte equality is not cross-arm metric equivalence (deferred Issue 4).
                reviewed=m.read(ROOT/'protocol/bdi-policy-final-source.json')['reviewed_code_sha256']
                self.assertEqual(hashlib.sha256((ROOT/repo/measurement/'measure_trial.py').read_text().encode()).hexdigest(),
                                 reviewed['experiment/measurement/measure_trial.py'])
            else:
                self.assertEqual((ROOT/repo/measurement/'measure_trial.py').read_bytes(), (ROOT/'tools/measure_trial.py').read_bytes())
            expected=m.read(ROOT/'protocol/measurement-contract.json')
            if repo == 'memos-bdi':
                expected['fields']['approach']='bdi'
                expected['fields']['reobservation_count']=expected['fields']['reobservation_count'].replace(
                    '; conventional uses health_observation.', '.')
            self.assertEqual(m.read(ROOT/repo/measurement/'contract.json'), expected)

    def derive(self, approach, events, samples, remote=False, runs=None):
        config = dict(approach=approach, scenario='S0', trial_id='test', control_sha='c', application_sha='v2', image_identity='image2', execution_mode='github' if remote else 'local')
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root = Path(tmp)
            (root/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
            m.save(root/'human-interventions.json', [])
            for n, run in enumerate(runs or []): m.save(root/f'run-{n}.json', run)
            return m.summarize(config, root, dict(pipeline_start='2026-09-25T00:00:00+00:00', pipeline_end='2026-09-25T00:01:00+00:00', exit_code=0), samples)

    @staticmethod
    def event(name, second=1, **fields):
        return dict(timestamp=f'2026-09-25T00:00:{second:02d}Z', event=name, **fields)

    def test_same_raw_definitions_across_controllers(self):
        samples = [dict(timestamp='2026-09-25T00:00:05+00:00', healthy=False, application_sha='v1', image_id='image1'),
                   dict(timestamp='2026-09-25T00:00:10+00:00', healthy=True, application_sha='v2', image_id='image2')]
        common = [self.event('deployment_start', 2, environment='production'), self.event('deployment_end', 4, environment='production')]
        current = self.derive('conventional', common+[self.event('pipeline_start'),self.event('pipeline_end',20),self.event('health_observation',8,round=2)], samples)
        bdi = self.derive('bdi', common+[self.event('controller_started'),self.event('controller_finished',20),self.event('telemetry_measurement',8,round=2)], samples)
        for key in current:
            if key != 'approach': self.assertEqual(current[key], bdi[key], key)
        self.assertTrue(current['candidate_delivered'])
        self.assertEqual(current['reobservation_count'], 1)
        self.assertEqual(current['first_recovered_healthy_time'], samples[1]['timestamp'])

    def test_incomplete_evidence_is_unknown_not_zero(self):
        result = self.derive('bdi', [], [], remote=True)
        for key in ('retry_count','reobservation_count','recovery_rollback_selected','recovery_rollback_executed','candidate_delivered','final_health','github_workflow_count'):
            self.assertIsNone(result[key], key)
        self.assertFalse(result['evidence_complete'])

    def test_selected_rollback_is_not_execution_or_delivery(self):
        native = [self.event('controller_started'), self.event('rollback_selected'), self.event('controller_finished',20)]
        result = self.derive('bdi', native, [dict(timestamp='2026-09-25T00:00:20Z',healthy=True,application_sha='v1',image_id='image1')])
        self.assertTrue(result['recovery_rollback_selected'])
        self.assertFalse(result['recovery_rollback_executed'])
        self.assertFalse(result['candidate_delivered'])

    def test_missing_acknowledged_run_is_incomplete(self):
        native=[self.event('controller_started'),self.event('dispatch_acknowledged',github_run_id=100),self.event('dispatch_acknowledged',github_run_id=101),self.event('controller_finished',20)]
        result=self.derive('bdi',native,[],True,[dict(databaseId=100,status='completed',jobs=[])])
        self.assertIsNone(result['github_workflow_count'])

    def test_direct_recovery_selection_without_reconsideration(self):
        native=[self.event('controller_started'),self.event('bdi_recovery_decision',entity='rollback'),self.event('controller_finished',20)]
        result=self.derive('bdi',native,[])
        self.assertTrue(result['recovery_rollback_selected'])
        self.assertFalse(result['recovery_rollback_executed'])


if __name__ == '__main__': unittest.main()
