"""Offline execution of observer boundaries, policy guards and historical preservation."""
import ast
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import yaml
import final_timing as timing
from test_phase5_instrumentation import module
import test_phase5_metrics as fixtures
from test_phase5_metrics import at
import phase5_metrics as metrics

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / 'results/implementation/phase6'


class Timing(unittest.TestCase):
    def test_contract_and_native_copies(self):
        directories = ['tools', 'memos-current/scripts/experiment-measurement', 'memos-bdi/experiment/scripts']
        for name in ('final_timing.py', 'phase6-timing.json'):
            for directory in directories:
                self.assertEqual((ROOT/directories[0]/name).read_bytes(), (ROOT/directory/name).read_bytes())
        self.assertEqual(json.loads((ROOT/'protocol/phase6-timing.json').read_text()), timing.CONTRACT)
        self.assertEqual(timing.HORIZON, 300)

    def test_only_controller_observation_policy_changes(self):
        previous = yaml.safe_load((CHECK/'source-before-4.txt').read_text())
        current = yaml.safe_load((ROOT/'memos-bdi/bdi-cicd-framework/config/controller_policy.yaml').read_text())
        previous['execution']['observation_timeout_seconds'] = 150
        self.assertEqual(current, previous)
        self.assertEqual(current['execution']['observation_interval_seconds'], 5)
        self.assertEqual(current['execution']['retry_interval_seconds'], 5)
        self.assertEqual(current['execution']['healthy_observations'], 2)
        self.assertEqual(current['rollback_reconsideration']['production']['window_seconds'], 60)
        old = json.loads((CHECK/'source-before-3.txt').read_text())
        new = json.loads((ROOT/'memos-bdi/experiment/protocol.json').read_text())
        self.assertEqual(old['policy'], new['policy'])  # rollback/reset monitor stays 180
        self.assertEqual(new['observation']['followup_seconds'], 300)
        self.assertEqual(old['scenarios'], new['scenarios'])

    def test_generated_agent_has_only_approved_budget_change(self):
        old = (CHECK/'source-before-6.txt').read_text()
        new = (ROOT/'memos-bdi/bdi-cicd-framework/bdi/controller_agent.asl').read_text()
        self.assertNotEqual(old, new)
        self.assertEqual(old.replace('180000)', '150000)'), new)

    def test_fixed_endpoint_and_invalid_anchor(self):
        self.assertEqual(timing.window(100)['endpoint_epoch'], 400)
        self.assertFalse(timing.window(100)['affects_native_outcome'])
        for value in (float('inf'), float('nan')):
            with self.assertRaises(ValueError): timing.window(value)

    def test_historical_schedules_not_final_cases(self):
        for scenario in ('S3', 'S4', 'S5', 'S4R', 'S5R'):
            with self.assertRaisesRegex(ValueError, 'Phase 7'): timing.require_current_scenario(scenario)
        for scenario in ('healthy', 'S0', 'S1', 'S2', 'S6'):
            timing.require_current_scenario(scenario)
        for path in ('memos-current/experiment/manage.py', 'memos-bdi/experiment/scripts/trial.py'):
            self.assertIn('require_current_scenario(args.scenario)', (ROOT/path).read_text())

    def test_bdi_late_collection_does_not_extend_endpoint_or_write_native_result(self):
        observer = module('phase6_observer', ROOT/'memos-bdi/experiment/scripts/observe.py')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'controller').mkdir()
            (root/'controller/controller-journal.jsonl').write_text(json.dumps(dict(event='controller_finished',timestamp=at(100))))
            (root/'common-observations.jsonl').write_text('')
            native = root/'result.json'; native.write_text('{"outcome":"achieved"}')
            trial = observer.TrialObserver({}, root, 'S0'); trial.started = 0
            trial.thread = Mock(); trial.thread.is_alive.return_value = False
            trial.workload = Mock(); trial.workload.is_alive.return_value = False
            saved = {}
            with patch.object(observer.time, 'time', return_value=float(metrics.stamp(at(1000)))), \
                 patch.object(observer.time, 'sleep') as sleep, \
                 patch.object(observer, 'sample', return_value={}), patch.object(observer, 'event'), \
                 patch.object(observer, 'save', side_effect=lambda path, value: saved.update({path.name:value})):
                trial.finish()
            sleep.assert_not_called()
            self.assertEqual(saved['observation-horizon.json']['endpoint_epoch'], float(metrics.stamp(at(400))))
            self.assertEqual(saved['endpoint.json']['endpoint_epoch'], float(metrics.stamp(at(400))))
            self.assertEqual(native.read_text(), '{"outcome":"achieved"}')

    def test_conventional_actual_loop_keeps_recorded_endpoint(self):
        tree = ast.parse((ROOT/'memos-current/experiment/manage.py').read_text())
        run = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'run')
        loop = next(n for n in ast.walk(run) if isinstance(n, ast.While) and 'evaluation_epoch' in ast.unparse(n))
        saved = {}; samples = []
        worker = Mock(); worker.is_alive.return_value = False
        namespace = dict(args=types.SimpleNamespace(mode='github'), sample=lambda _: {}, config={}, finished={'native_terminal':at(100),'exit_code':0},
            injector=None, endpoint=None, evaluation_epoch=None, samples=samples, stream=io.StringIO(), json=json,
            timing_window=timing.window, instant=lambda s:dt.datetime.fromisoformat(s),
            time=types.SimpleNamespace(time=lambda:float(metrics.stamp(at(1000))),monotonic=lambda:1000,
                                       sleep=lambda _:self.fail('Late collection must not add a horizon')),
            save=lambda path,value:saved.update({path.name:value}), directory=Path('unused'),
            worker=worker,pipeline_samples=None,meta={},now=lambda:at(1000))
        exec(compile(ast.Module(body=[loop],type_ignores=[]),'<actual conventional loop>','exec'), namespace)
        self.assertEqual(namespace['evaluation_epoch'], float(metrics.stamp(at(400))))
        self.assertEqual(saved['observation-horizon.json']['horizon_seconds'],300)
        self.assertEqual(namespace['finished']['exit_code'],0)

    def test_phase5_equal_300_second_windows_and_native_cost(self):
        fixture = fixtures.Metrics(); fixture.setUp()
        try:
            results=[]
            for arm in ('conventional','bdi'):
                spec=fixture.fixture(arm)
                spec['window']['end']=at(300)
                root=Path(spec['evidence_directory'])
                # Extend only passive synthetic traffic; native outcome still ends at 10.
                row=json.loads((root/'workload.jsonl').read_text().splitlines()[0])
                rows=[]
                for second in range(301):
                    rows.append({**row,'timestamp':at(second),'request_started_at':at(second),'request_completed_at':at(second)})
                fixture.write(root,'workload.jsonl',rows,True)
                result=metrics.normalize(spec); results.append(result)
                self.assertEqual(result['reliability']['requests_total'],300)
                self.assertEqual(result['reliability']['error_rate'],0)
                self.assertEqual(result['cost']['candidate_seconds'],10)
                self.assertEqual(result['boundaries']['observation_end'],at(300))
            self.assertEqual(results[0]['reliability']['error_rate'],results[1]['reliability']['error_rate'])
        finally: fixture.doCleanups()

    def test_retained_evidence_and_unrelated_sources_unchanged(self):
        for path, digest in json.loads((CHECK/'before-evidence.json').read_text()).items():
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),digest,path)
        snapshots=json.loads((CHECK/'before-source.json').read_text())
        # Phase 7 intentionally extends injector plumbing and infrastructure reset.
        # Their new guards are tested by test_phase7; native rollback stays frozen.
        for path in ['protocol/bdi-policy-contract.json','protocol/rq1-s4r-s5r.json']:
            self.assertEqual(hashlib.sha256((ROOT/path).read_bytes()).hexdigest(),snapshots[path]['sha256'],path)


if __name__ == '__main__': unittest.main()
