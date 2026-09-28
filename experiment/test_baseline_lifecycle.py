"""Controller outcome isolation; all external effects and timing are mocked."""
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import manage as m
import runtime_fixture as rf


class ImmediateController:
    def __init__(self, target, **_):
        self.target = target

    def start(self):
        if self.target.__name__ == 'controller':
            self.target()

    def is_alive(self):
        return False

    def join(self):
        pass


class BaselineLifecycleTests(unittest.TestCase):
    def test_passive_health_cannot_rewrite_pass_or_fail_or_reset(self):
        for exit_code in (0, 1):
            for healthy in (False, True):
                with self.subTest(exit_code=exit_code, passive_health=healthy), tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
                    root = Path(temp)
                    state = root / 'state'
                    state.mkdir()
                    m.save(state / 'baseline.json', {})
                    config = dict(application_sha='candidate', image_identity='image')
                    stack.enter_context(patch.object(m, 'ROOT', root))
                    stack.enter_context(patch.object(m, 'STATE', state))
                    for name in ('preflight', 'no_remote_work', 'verify', 'native_evidence'):
                        stack.enter_context(patch.object(m, name))
                    reset = stack.enter_context(patch.object(m, 'reset'))
                    stack.enter_context(patch.object(m, 'identity', return_value={}))
                    stack.enter_context(patch.object(m, 'command', return_value='mock resources'))
                    stack.enter_context(patch.object(m, 'measurement', return_value=config))
                    stack.enter_context(patch.object(m.threading, 'Thread', ImmediateController))
                    stack.enter_context(patch.object(m, 'deploy', return_value=exit_code))
                    stack.enter_context(patch.object(m, 'sample', side_effect=lambda _: dict(timestamp=m.now(), healthy=healthy)))
                    stack.enter_context(patch.object(m, 'summarize', return_value={'final_health': healthy}))
                    stack.enter_context(patch.object(m, 'raw_result', return_value={}))
                    self.assertEqual(m.run(SimpleNamespace(scenario='S0', release='v2', mode='rehearsal', trial='unit', no_interventions=True)), exit_code)
                    directory = root / 'experiment/results/unit'
                    self.assertEqual(m.read(directory / 'launch.json')['exit_code'], exit_code)
                    evaluation = m.read(directory / 'evaluation.json')
                    self.assertFalse(evaluation['affects_controller_outcome'])
                    observation = json.loads((directory / 'common-observations.jsonl').read_text())
                    self.assertEqual(observation['role'], 'EXPERIMENT MEASUREMENT')
                    self.assertTrue(observation['controller_terminal_seen'])
                    reset.assert_not_called()

    def test_real_fixture_ipc_has_no_second_readiness_gate(self):
        # Real threads/files; fake HTTP server and Docker. No injected traffic.
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            rf.atomic(directory / 'fixture-arm.json', {'scenario':'P8001', 'project':rf.PROJECT, 'backend_port':5543})
            sampler = Mock(side_effect=AssertionError('Duplicate health gate'))
            fixture = rf.Fixture(directory, 'P8001', {'application_sha': 'candidate', 'image_identity':'image'}, sampler)
            rf.atomic(directory / 'fixture-heartbeat.json', {'timestamp': rf.stamp()})
            with patch.object(rf, 'ThreadingHTTPServer'), patch.dict(rf.os.environ, MEMOS_FIXTURE_DIRECTORY=temp, MEMOS_REAL_DOCKER='docker'), patch.object(rf.subprocess, 'run', return_value=SimpleNamespace(returncode=0)):
                fixture.thread = rf.threading.Thread(target=fixture.serve, daemon=True)
                fixture.thread.start()
                try:
                    args = ['compose', '--file', 'base', '--project-name', rf.PROJECT, 'up', '--detach', '--no-build', '--pull', 'never', 'memos']
                    self.assertEqual(rf.docker_adapter(args), 0)
                    self.assertIsNone(fixture.started)
                    self.assertEqual(rf.activate(), 0)
                    self.assertIsNotNone(fixture.started)
                    self.assertIsNone(fixture.error)
                    activation=rf.read(directory/'fixture-start.json')['t0']
                    self.assertEqual(rf.read(directory/'scenario-schedule.json')['start_epoch'],rf.dt.datetime.fromisoformat(activation).timestamp())
                    sampler.assert_not_called()
                finally:
                    # Test teardown only: no real fault or server exists here.
                    fixture.stop.set()
                    fixture.thread.join(timeout=3)
                self.assertFalse(fixture.thread.is_alive())


if __name__ == '__main__':
    unittest.main()
