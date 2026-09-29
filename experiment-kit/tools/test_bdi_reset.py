from test_image_identity import historical_rollback
"""Offline qualification, lifecycle and boundary checks; no live faults."""
import contextlib
import copy
import json
from pathlib import Path
import sys
import types
import unittest
import uuid
from unittest.mock import Mock, patch

import bdi_reset as r


class ResetTests(unittest.TestCase):
    def setUp(self):
        self.root = r.operator.ROOT / 'results/implementation/phase4/tests' / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.config = {'control_sha': 'a' * 40, 'repository': 'owner/repo', 'approach': 'bdi',
                       'control_ref': 'memos-control-test', 'state': str(self.root / 'state')}
        self.v1 = r.operator.read(r.operator.ROOT / 'protocol/frozen-releases.json')['releases']['v1']
        self.v1 = dict(self.v1, **r.images_identity.evidence(self.v1, self.v1['image_id']))
        self.frozen = {'releases': {'v1': self.v1}}
        self.q = self.root / 'qualification'
        self.receipts = {env: {'verified': True, 'release_sha': self.v1['application_sha'],
            'image_id': self.v1['image_id'], 'control_sha': self.config['control_sha'],
            'environment': env, 'project': 'memos-experiment-bdi-' + env,
            'deploymentRunId': 'old-' + env, 'container_id': 'container-' + env}
            for env in r.ENVIRONMENTS}
        result = {'mode': 'github', 'outcome': 'achieved', 'mechanism': 'bdi', 'project': 'memos',
            'repository': self.config['repository'], 'release_sha': self.v1['application_sha'],
            'executions': {}, 'verified_releases': {}}
        for run, entity in enumerate(('build', 'test', 'security', 'staging', 'production'), 1):
            result['executions'][entity] = {'status': 'success', 'githubRunId': run}
            self.write(self.q / ('github-1/' + str(run) + '.json'),
                {'headSha': self.config['control_sha'], 'status': 'completed', 'conclusion': 'success'})
            if entity in r.ENVIRONMENTS:
                result['verified_releases'][entity] = {'environment': entity, 'release_sha': self.v1['application_sha'],
                    'github_run_id': run, 'execution_id': 'old-' + entity}
        self.write(self.q / 'controller/controller-result.json', result)
        self.write(self.q / 'identity.json', {**self.config, 'releases': self.frozen})
        self.write(self.q / 'trial.json', {**self.config, 'mode': 'baseline', 'application_sha': self.v1['application_sha']})
        self.write(self.q / 'reset-receipt.json', {**self.config, 'environments': self.receipts})
        self.write(self.q / 'final-state.json', {'environments': self.receipts})
        self.write(self.q / 'remote-terminal.json', {'github_runs': [1, 2, 3, 4, 5]})
        self.seal()
        self.path = self.q / 'controller/controller-result.json'
        self.write(Path(self.config['state']) / 'bdi/study-known-good.json',
                   {'control_sha': self.config['control_sha'], 'path': str(self.path)})

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def seal(self):
        self.write(self.q / 'evidence-sha256-1.json', {p.relative_to(self.q).as_posix(): r.digest(p)
            for p in self.q.rglob('*.json') if not p.name.startswith('evidence-sha256')})

    def test_genuine_matching_qualification(self):
        self.assertEqual(r.qualified_reference(self.config, self.frozen)['image_id'], self.v1['image_id'])

    def test_changed_sealed_evidence_rejected(self):
        self.write(self.path, {})
        with self.assertRaisesRegex(ValueError, 'seal mismatch'):
            r.qualified_reference(self.config, self.frozen)

    def test_wrong_control_artifact_failed_campaign_and_missing_worker_rejected(self):
        for change in ('control', 'artifact', 'failed', 'worker'):
            with self.subTest(change=change):
                config, frozen = copy.deepcopy(self.config), copy.deepcopy(self.frozen)
                original = self.path.read_bytes()
                if change == 'control': config['control_sha'] = 'e' * 40
                if change == 'artifact': frozen['releases']['v1']['image_id'] = 'wrong'
                if change in ('failed', 'worker'):
                    data = json.loads(original)
                    if change == 'failed': data['outcome'] = 'stopped'
                    else: data['executions'].pop('test')
                    self.write(self.path, data)
                    self.seal()
                with self.assertRaises(ValueError): r.qualification(self.path, config, frozen)
                self.path.write_bytes(original)
                self.seal()

    def test_no_build_pull_and_compose_has_explicit_local_only_flags(self):
        for command in (['docker', 'build', '.'], ['docker', 'pull', 'x'], ['docker', 'buildx', 'build']):
            with self.assertRaises(ValueError): r.reset_command(command)
        self.assertEqual(r.reset_command(['docker', 'compose', 'up', '-d', 'memos'])[-3:], ['--no-build', '--pull', 'never'])

    def test_fresh_reset_reference_then_consumption_and_staleness(self):
        receipt = self.root / 'reset/reset-receipt.json'
        self.write(receipt, {'kind': 'infrastructure-reset', **self.config,
            'qualification': r.qualified_reference(self.config, self.frozen), 'environments': self.receipts})
        self.write(receipt.parent / 'evidence-sha256-1.json', {'reset-receipt.json': r.digest(receipt)})
        for env, value in self.receipts.items(): self.write(Path(self.config['state']) / 'bdi' / env / 'current.json', value)
        self.assertEqual(r.candidate_reference(receipt, self.config, self.frozen), str(self.path))
        consumed = Path(str(receipt) + '.consumed')
        consumed.write_text('candidate-1')
        with self.assertRaisesRegex(ValueError, 'consumed'): r.candidate_reference(receipt, self.config, self.frozen)
        consumed.unlink()
        live = copy.deepcopy(self.receipts['production'])
        live['deploymentRunId'] = 'newer'
        self.write(Path(self.config['state']) / 'bdi/production/current.json', live)
        with self.assertRaisesRegex(ValueError, 'stale'): r.candidate_reference(receipt, self.config, self.frozen)

    def test_unresolved_fault_or_remote_worker_prevents_reset(self):
        state = Path(self.config['state'])
        self.write(self.root / 'experiment/adapter-contract.json', {'workflow_file': 'job-execution.yml'})
        with patch.object(r.operator, 'git', return_value=str(self.root / 'git')), patch.object(r.operator, 'output', return_value='{"workflow_runs": []}'):
            for relative in ('active-campaign.json', 'bdi/armed-scenario.json', 'bdi/production/fault/active.json'):
                path = state / relative
                self.write(path, {})
                with self.assertRaisesRegex(ValueError, 'Unresolved'): r.guard_state(self.root, self.config)
                path.unlink()
            with patch.object(r.operator, 'output', return_value='{"workflow_runs": [{"status":"in_progress"}]}') as remote:
                with self.assertRaisesRegex(ValueError, 'queued/running'): r.guard_state(self.root, self.config)
                self.assertIn('/actions/workflows/job-execution.yml/', remote.call_args.args[0][3])

    def fake_modules(self, fail=False):
        ops = types.ModuleType('operate')
        def setup(a):
            a.state = Path(a.state)
            a.evidence = Path(a.evidence)
            a.evidence.mkdir(parents=True)
            a.environment_state = a.state / 'bdi' / a.environment
            a.project = 'memos-experiment-bdi-' + a.environment
            a.control_sha = self.config['control_sha']
        ops.setup, ops.preflight = setup, Mock()
        ops.images = lambda a: {'prometheus': 'prom@sha256:abc'}
        from test_image_identity import metadata
        ops.command = Mock(return_value=json.dumps([metadata(self.v1, False)]))
        ops.deploy = Mock()
        def monitor(a):
            if fail and a.environment == 'production': return False
            self.write(a.evidence / 'verified-deployment.json', {**self.receipts[a.environment], 'deploymentRunId': a.execution_id})
            return True
        ops.monitor = Mock(side_effect=monitor)
        common = types.ModuleType('common')
        common.exclusive_lock = lambda p: contextlib.nullcontext()
        common.state_path = lambda p: Path(p)
        common.now = lambda: '2026-09-28T00:00:00Z'
        common.save = self.write
        provenance = types.ModuleType('provenance')
        provenance.snapshot, provenance.seal = Mock(), Mock()
        return ops, {'operate': ops, 'common': common, 'provenance': provenance}

    def test_success_and_partial_failure_do_not_touch_qualification_or_candidate(self):
        self.write(Path(self.config['state']) / 'bdi/images' / (self.v1['application_sha'] + '.json'), self.v1)
        before = r.digest(self.path)
        candidate = self.root / 'candidate/controller-result.json'
        self.write(candidate, {'outcome': 'stopped', 'recovery_outcome': 'restored'})
        candidate_hash = r.digest(candidate)
        for fail in (False, True):
            ops, modules = self.fake_modules(fail)
            destination = self.root / ('failed-reset' if fail else 'good-reset')
            with patch.dict(sys.modules, modules), patch.object(r, 'guard_state'), patch.object(r, 'owned'), patch.object(r.controlled_seed, 'validate', return_value={}), patch.object(r.controlled_seed, 'restore_verified', return_value={'data_semantics':'shared-controlled-seed'}):
                if fail:
                    with self.assertRaisesRegex(RuntimeError, 'telemetry'): r.execute(self.root, self.config, destination, self.frozen)
                    self.assertFalse((destination / 'reset-receipt.json').exists())
                    self.assertTrue((Path(self.config['state']) / 'active-campaign.json').exists())
                else:
                    r.execute(self.root, self.config, destination, self.frozen)
                    self.assertEqual(ops.deploy.call_count, 2)
                    self.assertEqual(ops.monitor.call_count, 2)
                    timing = r.operator.read(destination / 'reset-timing.json')
                    self.assertEqual(timing['passive_candidate_followup_seconds'], 0)
                    self.assertFalse(timing['controller_dispatched'])
                    self.assertEqual(set(r.operator.read(destination / 'reset-receipt.json')['environments']), set(r.ENVIRONMENTS))
                self.assertEqual(r.digest(self.path), before)
                self.assertEqual(r.digest(candidate), candidate_hash)

    def test_native_rollback_body_is_not_replaced_by_reset(self):
        source = r.operator.ROOT / 'memos-bdi/experiment/scripts/operate.py'
        import ast
        tree = ast.parse(source.read_text())
        rollback = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'rollback')
        calls = []
        self.write(self.root / 'frozen-releases.json', self.frozen)
        scope = {'ROOT': self.root, 'images_identity': r.images_identity, 'json': json, 'PROTOCOL': {'pair': {'v1': self.v1['application_sha']}},
                 'event': lambda *a, **k: calls.append('event'),
                 'deploy': lambda a: calls.append('deploy'), 'monitor': lambda a: calls.append('monitor') or True}
        exec(compile(ast.Module(body=[rollback], type_ignores=[]), '<native rollback>', 'exec'), scope)
        state = Path(self.config['state'])
        self.write(state / 'bdi/production/known-good.json', self.receipts['production'])
        self.write(state / 'bdi/images' / (self.v1['application_sha'] + '.json'), self.v1)
        args = types.SimpleNamespace(state=state, approach='bdi', environment_state=state / 'bdi/production',
            project=self.receipts['production']['project'], control_sha=self.config['control_sha'], evidence=self.root)
        scope['rollback'](args)
        self.assertEqual(calls, ['event', 'deploy', 'monitor'])
        self.assertTrue(args.recovering)
        self.assertEqual(args.release_sha, self.v1['application_sha'])

    def test_missing_image_stops_before_any_deployment(self):
        self.write(Path(self.config['state']) / 'bdi/images' / (self.v1['application_sha'] + '.json'), self.v1)
        ops, modules = self.fake_modules()
        ops.command.side_effect = RuntimeError('image unavailable')
        destination = self.root / 'missing-image'
        with patch.dict(sys.modules, modules), patch.object(r, 'guard_state'), patch.object(r, 'owned'), patch.object(r.controlled_seed, 'validate', return_value={}), patch.object(r.controlled_seed, 'restore_verified', return_value={'data_semantics':'shared-controlled-seed'}):
            with self.assertRaisesRegex(RuntimeError, 'unavailable'):
                r.execute(self.root, self.config, destination, self.frozen)
        ops.deploy.assert_not_called()
        self.assertFalse((destination / 'reset-receipt.json').exists())

    def test_foreign_volume_rejected(self):
        ops = types.SimpleNamespace(command=Mock(return_value='[{"Labels":{"com.docker.compose.project":"foreign"}}]'))
        args = types.SimpleNamespace(project='owned', evidence=self.root)
        with self.assertRaisesRegex(ValueError, 'Foreign volume'):
            r.owned(ops, args)

    def test_rollback_source_matches_selected_control(self):
        import ast
        root = r.operator.ROOT / 'memos-bdi'
        sha = r.operator.read(r.operator.MANIFEST)['bdi']['control_sha']
        pinned = r.operator.git(root, 'show', sha + ':experiment/scripts/operate.py')
        current = (root / 'experiment/scripts/operate.py').read_text()
        def body(source):
            return ast.dump(next(n for n in ast.parse(historical_rollback(source)).body if isinstance(n, ast.FunctionDef) and n.name == 'rollback'))
        self.assertEqual(body(pinned), body(current))


if __name__ == '__main__':
    unittest.main()
