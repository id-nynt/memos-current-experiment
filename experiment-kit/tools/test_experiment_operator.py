"""Revision and dispatch contract tests; no Docker, GitHub, or deployment."""
import copy
import json
from pathlib import Path
import uuid
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from unittest.mock import Mock
import pinned_conventional as pinned

import experiment as e
import bdi_reset


class OperatorTests(unittest.TestCase):
    def setUp(self):
        # Retain these tiny fixtures; Windows sandbox temp ACLs are unreliable.
        self.root = e.ROOT / 'results/implementation/master-audit-20260928/tests' / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.manifest = e.read(e.MANIFEST)
        self.frozen = e.read(e.ROOT / self.manifest['release_manifest'])
        (self.root / 'protocol').mkdir()
        e.save_new(self.root / 'protocol/operator-revisions.json', self.manifest)
        e.save_new(self.root / self.manifest['release_manifest'], self.frozen)
        (self.root / 'tools').mkdir()
        for name in ('experiment.py', 'pinned_conventional.py', 'bdi_policy.py', 'bdi_attribution.py', 'bdi_reset.py'):
            (self.root / 'tools' / name).write_bytes((e.ROOT / 'tools' / name).read_bytes())
        (self.root / 'protocol/bdi-policy-contract.json').write_bytes((e.ROOT / 'protocol/bdi-policy-contract.json').read_bytes())
        (self.root / 'protocol/bdi-policy-final-source.json').write_bytes((e.ROOT / 'protocol/bdi-policy-final-source.json').read_bytes())

    def fake_git(self, repo, *args):
        arm = 'bdi' if Path(repo).name == 'memos-bdi' else 'conventional'
        spec = self.manifest[arm]
        if args[0] == 'rev-parse':
            if args[1].startswith('refs/tags/'):
                return spec['control_sha']
            sha = args[1].split('^')[0]
            return next(v['tree'] for v in self.frozen['releases'].values() if v['application_sha'] == sha)
        if args[1].endswith('experiment/protocol.json'):
            return json.dumps({'pair': {k: v['application_sha'] for k, v in self.frozen['releases'].items()}})
        return json.dumps(self.frozen)

    def select(self, fake=None):
        with patch.object(e, 'ROOT', self.root), patch.object(e, 'MANIFEST', self.root / 'protocol/operator-revisions.json'), patch.object(e, 'git', side_effect=fake or self.fake_git):
            return e.selection('conventional')

    def test_both_arms_use_identical_frozen_pair(self):
        _, actual = self.select()
        self.assertEqual(actual, self.frozen)

    def test_wrong_tag_fails_even_for_other_arm(self):
        def wrong(repo, *args):
            if Path(repo).name == 'memos-bdi' and args[1].startswith('refs/tags/'):
                return '0' * 40
            return self.fake_git(repo, *args)
        with self.assertRaisesRegex(ValueError, 'tag/SHA mismatch'):
            self.select(wrong)

    def test_changed_image_copy_rejected(self):
        def wrong(repo, *args):
            if args[0] == 'show' and args[1].endswith('frozen-releases.json'):
                changed = copy.deepcopy(self.frozen)
                changed['releases']['v2']['image_id'] = 'sha256:wrong'
                return json.dumps(changed)
            return self.fake_git(repo, *args)
        with self.assertRaisesRegex(ValueError, 'release manifest differs'):
            self.select(wrong)

    def test_protocol_pair_drift_rejected(self):
        def wrong(repo, *args):
            if args[0] == 'show' and args[1].endswith('experiment/protocol.json'):
                return json.dumps({'pair': {'v1': 'wrong', 'v2': 'wrong'}})
            return self.fake_git(repo, *args)
        with self.assertRaisesRegex(ValueError, 'protocol/application pair mismatch'):
            self.select(wrong)

    def test_published_tag_drift_fails_before_dispatch(self):
        spec = self.manifest['conventional']
        with patch.object(e, 'output', return_value='0' * 40):
            with self.assertRaisesRegex(ValueError, 'differs from operator pin'):
                e.published(spec, 'conventional')

    def test_dirty_pinned_runtime_is_not_repaired_or_reused(self):
        spec = self.manifest['bdi']
        target = self.root / spec['checkout'] / 'experiment/results/control-runtime' / spec['control_sha']
        target.mkdir(parents=True)
        with patch.object(e, 'ROOT', self.root), patch.object(e, 'git', return_value=spec['control_sha']), patch.object(e, 'clean', return_value=False):
            with self.assertRaisesRegex(ValueError, 'Pinned runtime changed'):
                e.runtime(spec, 'bdi')

    def test_reset_candidate_plans_select_matching_native_receipt(self):
        target = self.root / 'runtime'
        (target / 'experiment').mkdir(parents=True)
        e.save_new(target / 'experiment/runtime.json', {'state': '~/memos-bdi-state'})
        prior = {'native_directory': str(target / 'experiment/results/reset-unique')}
        for arm in ('conventional', 'bdi'):
            spec = self.manifest[arm]
            reset, reset_native, config = e.plan(arm, 'reset', 'S0', target, spec, self.root / 'reset-unique')
            with patch.object(bdi_reset, 'candidate_reference', return_value='qualified/controller/controller-result.json'):
                candidate, _, config = e.plan(arm, 'run', 'S0', target, spec, self.root / 'candidate-unique', prior)
            if arm == 'bdi':
                self.assertTrue(any(str(x).endswith('bdi_reset.py') for x in reset))
                self.assertNotIn('baseline', reset)
                self.assertIn('candidate', candidate)
                self.assertEqual(candidate[candidate.index('--reset-receipt') + 1], str(Path(prior['native_directory']) / 'reset-receipt.json'))
                self.assertEqual(config['control_sha'], spec['control_sha'])
                self.assertEqual(set(config), {'approach', 'repository', 'control_sha', 'control_ref', 'state', 'bdi_known_good'})
            else:
                self.assertIn('reset', reset)
                self.assertEqual(reset_native, self.root / 'reset-unique')
                self.assertEqual(candidate[candidate.index('--release') + 1], 'v2')
                self.assertEqual(candidate[candidate.index('--mode') + 1], 'github')

    def test_evidence_is_never_overwritten(self):
        path = self.root / 'evidence.json'
        e.save_new(path, {'original': True})
        with self.assertRaises(FileExistsError):
            e.save_new(path, {'original': False})
        self.assertEqual(e.read(path), {'original': True})

    def test_conventional_dispatch_uses_pinned_tag_and_exact_correlation(self):
        spec = self.manifest['conventional']
        native = SimpleNamespace(CFG={'repository': spec['repository']},
            command=Mock(side_effect=[spec['control_sha'], spec['control_sha'], '', json.dumps([
                {'databaseId': 999, 'displayTitle': 'conventional-unique', 'headSha': 'wrong'},
                {'databaseId': 123, 'displayTitle': 'conventional-unique', 'headSha': spec['control_sha']}])]),
            save=Mock(), collect_run=Mock(), now=lambda: 'test-time')
        finished = {}
        pinned.github_run(native, spec, 'v2', 'unique', 'S0', self.root, finished)
        dispatch = native.command.call_args_list[2].args
        self.assertEqual(dispatch[dispatch.index('--ref') + 1], spec['control_ref'])
        self.assertNotIn('main', dispatch)
        self.assertEqual(finished, {'run_id': 123})
        native.collect_run.assert_called_once_with(123, self.root, finished)

    def test_changed_published_tag_never_dispatches(self):
        spec = self.manifest['conventional']
        native = SimpleNamespace(CFG={'repository': spec['repository']},
                                 command=Mock(side_effect=[spec['control_sha'], 'wrong']))
        with self.assertRaisesRegex(ValueError, 'tag changed'):
            pinned.github_run(native, spec, 'v2', 'unique', 'S0', self.root, {})
        self.assertEqual(native.command.call_count, 2)

    def test_unsupported_case_runtime_fails_before_baseline_consumption(self):
        target = self.root / 'runtime'
        target.mkdir()
        with patch.object(e, 'selection', return_value=(self.manifest, self.frozen)), \
             patch.object(e, 'MANIFEST', self.root / 'protocol/operator-revisions.json'), \
             patch.object(e, 'published'), patch.object(e, 'runtime', return_value=target), \
             patch.object(e, 'policy_report', return_value={'status':'consistent'}), \
             patch.object(e, 'os', SimpleNamespace(name='posix')), \
             patch.object(e.subprocess, 'run'), patch.object(e.subprocess, 'call') as launch, \
             patch.object(e.sys, 'argv', ['experiment.py','run','bdi','--scenario','S3',
                                        '--case','case.json','--allow-fault-execution']):
            with self.assertRaisesRegex(ValueError,'does not support parameterised cases'):
                e.main()
            launch.assert_not_called()
            self.assertFalse((self.root/'results/operator-state').exists())

    def test_full_bdi_reset_run_consumes_baseline_and_retains_selection(self):
        target = self.root / 'runtime'
        (target / 'experiment').mkdir(parents=True)
        e.save_new(target / 'experiment/runtime.json', {'state': str(self.root / 'private')})
        calls = []

        def native(command, **kwargs):
            calls.append(command)
            destination = Path(command[command.index('--directory') + 1])
            destination.mkdir(parents=True)
            if any(str(x).endswith('bdi_reset.py') for x in command):
                e.save_new(destination / 'reset-receipt.json', {
                    'control_sha': self.manifest['bdi']['control_sha'], 'approach': 'bdi',
                    'environments': {name: {'verified': True, 'release_sha': self.frozen['releases']['v1']['application_sha']}
                                     for name in ('staging', 'production')}})
            return 0

        with patch.object(e, 'ROOT', self.root), patch.object(e, 'MANIFEST', self.root / 'protocol/operator-revisions.json'), \
             patch.object(e, 'selection', return_value=(self.manifest, self.frozen)), \
             patch.object(e, 'published'), patch.object(e, 'runtime', return_value=target), \
             patch.object(e, 'policy_report', return_value={'status': 'consistent'}), \
             patch.object(e, 'os', SimpleNamespace(name='posix')), \
             patch.object(e.subprocess, 'run'), patch.object(e.subprocess, 'call', side_effect=native), \
             patch.object(bdi_reset, 'candidate_reference', return_value='qualified/controller/controller-result.json'):
            with patch.object(e.sys, 'argv', ['experiment.py', 'reset', 'bdi']):
                self.assertEqual(e.main(), 0)
            with patch.object(e.sys, 'argv', ['experiment.py', 'run', 'bdi']):
                self.assertEqual(e.main(), 0)
            with patch.object(e.sys, 'argv', ['experiment.py', 'run', 'bdi']):
                with self.assertRaisesRegex(ValueError, 'unused baseline required'):
                    e.main()
        self.assertEqual(len(calls), 2)
        selections = list((self.root / 'results/operator-runs').glob('*/selection.json'))
        self.assertEqual(len(selections), 2)
        self.assertTrue(all(e.read(p)['release_manifest'] == self.frozen for p in selections))
        self.assertTrue(all((p.parent / 'resolved-policy.json').exists() for p in selections))
        self.assertTrue(all((p.parent / 'horizon-attribution.json').exists() for p in selections))


if __name__ == '__main__':
    unittest.main()
