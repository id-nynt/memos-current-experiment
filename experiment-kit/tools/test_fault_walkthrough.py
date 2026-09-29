"""Offline approval/collector guards only; never executes a scenario or simulation."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('fault_walkthrough', Path(__file__).with_name('memos_fault_walkthrough.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class GuardTests(unittest.TestCase):
    def test_only_collector_change_is_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            old, new = Path(folder) / 'old.py', Path(folder) / 'new.py'
            old.write_text('def collect(): return 1\ndef dispatch(): return 2\n')
            new.write_text('def collect(): return 3\ndef dispatch(): return 2\n')
            self.assertEqual(module.collector_only(old, new).name, 'collect')
            new.write_text('def collect(): return 3\ndef dispatch(): return 4\n')
            with self.assertRaisesRegex(RuntimeError, 'Unrelated'):
                module.collector_only(old, new)

    def test_missing_or_stale_scope_cannot_dispatch(self):
        for stale in (False, True):
            with self.subTest(stale=stale), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                repair = root / 'repair.py'
                repair.write_text('def collect(): pass\n')
                if stale:
                    scope = root / 'fault-walkthrough-approvals'
                    scope.mkdir()
                    (scope / 'S5.json').write_text('{}')
                config = {'bdi': {'state': str(root)}, 'conventional': {'state': str(root)}}
                with patch.object(module, 'STUDY', root), patch.object(module, 'context', return_value=(config, {}, repair)), patch.object(module.subprocess, 'run') as run, patch.object(module.subprocess, 'check_output') as output, patch.object(sys, 'argv', ['tool', 'run', '--scenario', 'S5', '--approach', 'bdi']):
                    with self.assertRaises((FileNotFoundError, RuntimeError)):
                        module.main()
                    run.assert_not_called()
                    output.assert_not_called()

    @unittest.skipIf(sys.platform == 'win32', 'Linux lock API')
    def test_declined_approval_writes_no_authorization(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            repair = root / 'repair.py'
            repair.write_text('def collect(): pass\n')
            config = {'bdi': {'state': str(root)}, 'conventional': {'state': str(root)}}
            with patch.object(module, 'STUDY', root), patch.object(module, 'context', return_value=(config, {}, repair)), patch('builtins.input', return_value='NO'), patch.object(sys, 'argv', ['tool', 'approve', '--scenario', 'S5']):
                with self.assertRaisesRegex(RuntimeError, 'Not approved'):
                    module.main()
            self.assertFalse((root / 'approved-study.json').exists())
            self.assertFalse((root / 'fault-walkthrough-approvals').exists())


if __name__ == '__main__':
    unittest.main()
