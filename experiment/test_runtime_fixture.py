"""Fixture-only unit tests. No Docker, GitHub dispatch, or live application faults."""
import json
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import manage
import runtime_fixture as rf
import trial


class FixtureTests(unittest.TestCase):
    def proxy_handler(self, directory):
        """Build the HTTP handler with mock server/clock/readiness; no sockets."""
        (directory / 'fixture-up.json').write_text('{}')
        fixture = rf.Fixture(directory, 'S3', {'application_sha': 'candidate'},
                             lambda _: {'healthy': True, 'application_sha': 'candidate'})
        fixture.stop = Mock()
        fixture.stop.is_set.return_value = False
        fixture.stop.wait.side_effect = [False, True]
        with patch.object(rf, 'ThreadingHTTPServer') as server, patch.object(rf.threading, 'Thread'):
            fixture.serve()
            self.assertIsNone(fixture.error)
            handler = server.call_args.args[1]
        return fixture, handler

    def request(self, handler, verb='GET', route='/api/v1/memos/private'):
        request = handler.__new__(handler)
        request.command, request.path = verb, route
        request.headers = {'Authorization': 'Bearer PRIVATE_TEST_TOKEN'}
        request.rfile, request.wfile = io.BytesIO(), io.BytesIO()
        request.send_response, request.send_header, request.end_headers = Mock(), Mock(), Mock()
        request.proxy()
        return request

    def test_mock_transport_faults_all_methods_without_leaking_credentials(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            fixture, handler = self.proxy_handler(directory)
            connection = Mock()
            connection.getresponse.return_value.read.return_value = b'{"commit":"candidate"}'
            with patch.object(rf.http.client, 'HTTPConnection', return_value=connection), \
                 patch.object(rf.time, 'monotonic', return_value=fixture.started + 1):
                for verb in ('GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS', 'CUSTOM'):
                    request = self.request(handler, verb)
                    request.send_response.assert_called_once_with(503)
                    self.assertEqual(request.wfile.getvalue(), b'' if verb == 'HEAD' else b'External experiment fixture')
            self.assertNotIn('PRIVATE_TEST_TOKEN', (directory / 'fault-events.jsonl').read_text())
            self.assertNotIn('/private', (directory / 'fault-events.jsonl').read_text())

    def test_mock_transport_passes_v1_and_preserves_authorization(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture, handler = self.proxy_handler(Path(temp))
            identity, upstream = Mock(), Mock()
            identity.getresponse.return_value.read.return_value = b'{"commit":"v1"}'
            response = upstream.getresponse.return_value
            response.status, response.read.return_value = 200, b'{"content":"sentinel"}'
            response.getheaders.return_value = [('Content-Type', 'application/json'), ('Content-Length', '22')]
            with patch.object(rf.http.client, 'HTTPConnection', side_effect=[identity, upstream]), \
                 patch.object(rf.time, 'monotonic', return_value=fixture.started + 1):
                request = self.request(handler)
            request.send_response.assert_called_once_with(200)
            self.assertEqual(request.wfile.getvalue(), b'{"content":"sentinel"}')
            self.assertEqual(upstream.request.call_args.args[3]['Authorization'], 'Bearer PRIVATE_TEST_TOKEN')

    def test_all_frozen_controller_files(self):
        self.assertEqual(rf.frozen_check()['revision'], '67c4731e67ee1ff0a8cc8d3cbfd7459a23ffe667')

    def test_schedule_boundaries(self):
        cases = {'S3': [(0, True), (59.999, True), (60, False)],
                 'S4': [(599, True), (899.999, True), (900, False)],
                 'S5': [(0, True), (60, False), (119.999, False), (120, True), (240, False)]}
        for scenario, samples in cases.items():
            for elapsed, expected in samples:
                self.assertEqual(rf.fault_active(scenario, elapsed, '/api/v1/memos/item?q=x', True), expected)

    def test_release_and_route_scope(self):
        for scenario in rf.SCHEDULES:
            for route in ('/healthz', '/', '/api/v1/instance/profile', '/api/v1/memosOther', '/assets/app.js'):
                self.assertFalse(rf.fault_active(scenario, 1, route, True))
            self.assertFalse(rf.fault_active(scenario, 1, '/api/v1/memos', False))
            self.assertFalse(rf.fault_active(scenario, -1, '/api/v1/memos', True))

    def test_adapter_only_modifies_production_up(self):
        prefix = ['compose', '--file', 'base.yaml', '--project-name', rf.PROJECT]
        original = prefix + ['up', '-d', '--no-build', '--pull', 'never', 'memos']
        adapted, changed = rf.adapted_arguments(original, 'fixture.yaml')
        self.assertTrue(changed)
        self.assertEqual(adapted, ['compose', '--file', 'base.yaml', '--file', 'fixture.yaml'] + original[3:])
        for args in (prefix + ['stop', '--timeout', '30', 'memos'], ['inspect', 'container'],
                     ['compose', '--file', 'base.yaml', '--project-name', 'foreign'] + original[-6:]):
            self.assertEqual(rf.adapted_arguments(args, 'fixture.yaml'), (args, False))

    def test_unexpected_up_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, 'Unexpected'):
            rf.adapted_arguments(['compose', '--file', 'base', '--project-name', rf.PROJECT, 'up', '--build'], 'fixture')

    def test_trial_path_cannot_escape(self):
        for name in ('..', '.', '../other', 'a/b', 'a\\b', ''):
            with self.assertRaises(ValueError):
                rf.trial_directory(rf.ROOT, name)

    def test_duplicate_trial_refused_before_reset(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rf.trial_directory(root, 'S1-existing').mkdir(parents=True)
            with patch.object(manage, 'ROOT', root), patch.object(trial, 'ready') as ready, patch.object(manage, 'reset') as reset:
                with self.assertRaisesRegex(RuntimeError, 'already exists'):
                    trial.run(SimpleNamespace(trial='S1-existing'))
                ready.assert_not_called()
                reset.assert_not_called()

    def test_adapter_propagates_real_docker_failure_without_arming(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(rf.os.environ, MEMOS_FIXTURE_DIRECTORY=temp, MEMOS_REAL_DOCKER='docker.exe'), \
                 patch.object(rf.subprocess, 'run', return_value=SimpleNamespace(returncode=17)):
                args = ['compose', '--file', 'base', '--project-name', rf.PROJECT,
                        'up', '-d', '--no-build', '--pull', 'never', 'memos']
                self.assertEqual(rf.docker_adapter(args), 17)
                self.assertFalse((Path(temp) / 'fixture-up.json').exists())

    def test_stale_observer_fails_hook(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            rf.atomic(directory / 'fixture-heartbeat.json', {'timestamp': '2000-01-01T00:00:00+00:00'})
            with patch.dict(rf.os.environ, MEMOS_FIXTURE_DIRECTORY=temp, MEMOS_REAL_DOCKER='docker.exe'), \
                 patch.object(rf.subprocess, 'run', return_value=SimpleNamespace(returncode=0)):
                args = ['compose', '--file', 'base', '--project-name', rf.PROJECT,
                        'up', '-d', '--no-build', '--pull', 'never', 'memos']
                with self.assertRaisesRegex(RuntimeError, 'disconnected'):
                    rf.docker_adapter(args)

    def test_controller_wrapper_does_not_hide_exit_status(self):
        with patch.dict(rf.os.environ, SCENARIO='S2', RELEASE='v2', RELEASE_SHA='a' * 40, TRIAL_ID='unit'), \
             patch.object(rf.subprocess, 'run', return_value=SimpleNamespace(returncode=42)) as run:
            self.assertEqual(rf.runner(), 42)
            self.assertEqual(run.call_args.args[0][-2:], ['-Scenario', 'S2'])

    def lifecycle_case(self, temp, terminal):
        root = Path(temp)
        state = root / 'private'
        state.mkdir()
        rf.atomic(state / 'baseline.json', {'observations': 'mock verified v1'})
        directory = rf.trial_directory(root, 'unit')

        def collect(_):
            directory.mkdir()
            (directory / 'github').mkdir()
            (directory / 'github/raw-logs.zip').write_bytes(b'archive already validated by collector')
            rf.atomic(directory / 'github/jobs-all-attempts.json', [])
            rf.atomic(directory / 'release.json', {})
            (directory / 'native-events.jsonl').write_text('{"event":"pipeline_end"}\n')
            rf.atomic(directory / 'launch.json', {'exit_code': 1 if terminal else None})
            rf.atomic(directory / 'raw-result.json', {'github_run_ids': [123], 'fixture_valid': None,
                      'endpoint': {'observation_coverage': True, 'fault_not_reached': False}})
            return 1 if terminal else 2

        with patch.object(manage, 'ROOT', root), patch.object(manage, 'STATE', state), \
             patch.object(manage, 'run', side_effect=collect), patch.object(manage, 'reset') as reset, \
             patch.object(manage, 'identity', return_value={}), patch.object(trial, 'ready'), \
             patch.object(manage, 'measurement', return_value={}), \
             patch.object(manage, 'sample', return_value={'healthy': False}):
            args = SimpleNamespace(trial='unit', scenario='S2', no_interventions=True)
            if terminal:
                self.assertEqual(trial.run(args), 0)
                self.assertEqual(reset.call_count, 2)
            else:
                with self.assertRaisesRegex(RuntimeError, 'unresolved'):
                    trial.run(args)
                self.assertEqual(reset.call_count, 1)

    def test_expected_pipeline_failure_still_collects_and_resets(self):
        with tempfile.TemporaryDirectory() as temp:
            self.lifecycle_case(temp, True)

    def test_unresolved_pipeline_never_triggers_post_trial_reset(self):
        with tempfile.TemporaryDirectory() as temp:
            self.lifecycle_case(temp, False)


if __name__ == '__main__':
    unittest.main()
