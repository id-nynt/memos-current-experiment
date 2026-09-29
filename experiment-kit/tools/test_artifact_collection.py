"""Focused collector checks; no GitHub calls, deployments or fault scenarios."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'memos-bdi/experiment/scripts'))
spec = importlib.util.spec_from_file_location('collector_trial', root / 'memos-bdi/experiment/scripts/trial.py')
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


class CollectionTests(unittest.TestCase):
    def collect(self, pages, download_error=None):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / 'controller').mkdir()
            (directory / 'controller/controller-journal.jsonl').write_text(json.dumps({'event':'dispatch_acknowledged','github_run_id':123})+'\n')
            def gh(args):
                if '--log' in args:
                    return 'preserved job log'
                if '--paginate' in args and any('/jobs?' in str(x) for x in args):
                    return json.dumps({'jobs':[]})
                if '--paginate' in args:
                    if isinstance(pages, Exception):
                        raise pages
                    return '\n'.join(json.dumps(page) for page in pages)
                return json.dumps({'status': 'completed', 'databaseId': 123, 'headSha':'control'})
            with patch.object(trial, 'gh', side_effect=gh), patch.object(trial.subprocess, 'run', side_effect=download_error) as download:
                result = trial.collect({'repository': 'example/app', 'state': tmp, 'approach': 'bdi', 'control_sha':'control'}, directory)
                self.assertEqual(result, [123])
                self.assertTrue(list(directory.glob('github-*/*-artifacts.json')))
                self.assertTrue(list(directory.glob('github-*/*.log')))
                return download.call_count

    def test_empty_inventory_keeps_logs_without_download(self):
        self.assertEqual(self.collect([{'total_count': 0, 'artifacts': []}]), 0)

    def test_multiple_pages_download(self):
        self.assertEqual(self.collect([{'artifacts': [{'expired': False}]}, {'artifacts': [{'expired': False}]}]), 1)

    def test_expired_artifact_fails(self):
        with self.assertRaises(ValueError):
            self.collect([{'artifacts': [{'expired': True}]}])

    def test_inventory_error_fails(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.collect(subprocess.CalledProcessError(1, 'gh api'))

    def test_download_error_fails(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.collect([{'artifacts': [{'expired': False}]}], subprocess.CalledProcessError(1, 'gh download'))


if __name__ == '__main__':
    unittest.main()
