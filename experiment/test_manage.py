"""Safety and identity tests; no Docker mutations or network requests."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import zipfile
from unittest.mock import patch

import fixture
import manage


class OwnershipTests(unittest.TestCase):
    def test_full_log_archive_extracts_nested_job_logs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / 'logs.zip'
            with zipfile.ZipFile(archive, 'w') as bundle:
                bundle.writestr('reusable-job/step.txt', 'raw job output')
            manage.extract_logs(archive, root / 'output')
            self.assertEqual((root / 'output/reusable-job/step.txt').read_text(), 'raw job output')

    def test_log_archive_cannot_escape_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / 'logs.zip'
            with zipfile.ZipFile(archive, 'w') as bundle:
                bundle.writestr('../outside.txt', 'must not be written')
            with self.assertRaisesRegex(ValueError, 'escapes evidence'):
                manage.extract_logs(archive, root / 'output')
            self.assertFalse((root / 'outside.txt').exists())

    def test_foreign_volume_is_refused(self):
        with patch.object(manage, 'command', return_value=json.dumps([{'Labels': {'com.docker.compose.project': 'foreign'}}])):
            with self.assertRaisesRegex(RuntimeError, 'foreign volume'):
                manage.assert_owned('production')

    def test_foreign_container_is_refused(self):
        responses = [json.dumps([{'Labels': {'com.docker.compose.project': manage.project('production')}}]),
                     'container-id', json.dumps([{'Config': {'Labels': {'com.docker.compose.project': 'foreign'}}}])]
        with patch.object(manage, 'command', side_effect=responses):
            with self.assertRaisesRegex(RuntimeError, 'Foreign container'):
                manage.assert_owned('production')

    def test_configuration_cannot_redirect_reset(self):
        with patch.dict(manage.CFG, projects=['other-staging', 'other-production']):
            with self.assertRaisesRegex(RuntimeError, 'Only conventional'):
                manage.assert_owned('production')

    def test_live_candidate_requires_exact_sha(self):
        with patch.object(manage, 'sample', return_value={'healthy': True, 'application_sha': 'wrong'}), patch.object(manage, 'command', return_value='control'):
            with self.assertRaisesRegex(RuntimeError, 'verification failed'):
                manage.verify('v2')

    def test_evidence_pointer_cannot_escape_state(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            pointer = directory / 'pointer'
            pointer.write_text(temp)
            with self.assertRaisesRegex(RuntimeError, 'escapes owned state'):
                manage.native_evidence(directory, pointer)

    def test_queued_remote_work_blocks_reset(self):
        with patch.object(manage, 'command', return_value=json.dumps([{'workflow_runs': [{'status': 'queued'}]}])):
            with self.assertRaisesRegex(RuntimeError, 'queued/running'):
                manage.no_remote_work()

    def test_missing_remote_evidence_is_not_silent(self):
        with patch.object(manage, 'command', side_effect=RuntimeError('offline')):
            with self.assertRaisesRegex(RuntimeError, 'offline'):
                manage.no_remote_work()

    def test_only_declared_scenarios_enabled(self):
        for scenario in ('S0', 'S1', 'S2', 'S3', 'S4', 'S5'):
            fixture.validate(scenario)
        with self.assertRaises(ValueError):
            fixture.validate('unknown')

    def test_runtime_rehearsal_never_reaches_docker(self):
        with patch.object(manage, 'preflight') as preflight:
            with self.assertRaisesRegex(RuntimeError, 'GitHub runner adapter'):
                manage.run(SimpleNamespace(scenario='S3', release='v2', mode='rehearsal'))
            preflight.assert_not_called()

    def test_releases_are_distinct_and_frozen(self):
        self.assertNotEqual(manage.RELEASES['v1']['application_sha'], manage.RELEASES['v2']['application_sha'])
        for release in manage.RELEASES.values():
            self.assertEqual(release['version'], 'local-' + release['application_sha'])
            self.assertRegex(release['image_id'], r'^sha256:[0-9a-f]{64}$')

    def test_controller_verification_policy_unchanged(self):
        import subprocess
        baseline = subprocess.check_output(['git', 'show', manage.CFG['policy_baseline'] + ':scripts/local-cd/deploy.ps1'], cwd=manage.ROOT).decode()
        current = (manage.ROOT / 'scripts/local-cd/deploy.ps1').read_text()
        # The complete readiness routine (deadline, retries, probes) is frozen.
        def routine(source):
            return source.split('function Assert-Deployment {', 1)[1].split('function Save-Diagnostics', 1)[0].replace('\r\n', '\n')
        self.assertEqual(routine(baseline), routine(current))


if __name__ == '__main__':
    unittest.main()
