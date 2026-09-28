"""Linux plumbing tests with no Docker, network, or measured deployment."""
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import manage
import runtime_fixture as fixture


@unittest.skipIf(os.name=='nt','POSIX execution test')
class LinuxParity(unittest.TestCase):
    def test_reset_lease_matches_powershell_exclusive_create_path(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(manage,'STATE',Path(tmp)):
            path=Path(tmp)/'deployment.lock.linux-lease'
            with manage.lock('deployment.lock'):
                self.assertTrue(path.exists())
                with self.assertRaises(FileExistsError):
                    with manage.lock('deployment.lock'):pass
            self.assertFalse(path.exists())
            path.write_text('unreconciled')
            with self.assertRaises(FileExistsError):
                with manage.lock('deployment.lock'):pass
            self.assertEqual(path.read_text(),'unreconciled')

    def test_native_deploy_selects_pwsh_without_changing_arguments(self):
        with patch.object(manage.subprocess,'run') as run:
            manage.deploy('v1','test')
        args=run.call_args.args[0]
        self.assertEqual(args[0],'pwsh')
        self.assertEqual(args[args.index('-FrozenRelease')+1],'v1')
        self.assertEqual(args[args.index('-Scenario')+1],'S0')

    def test_posix_shim_preserves_arguments_and_quoted_paths(self):
        with tempfile.TemporaryDirectory(prefix="memos space '") as tmp:
            root=Path(tmp);directory=root/'experiment/results/unit';directory.mkdir(parents=True)
            script=root/"fixture ' quoted.py"
            script.write_text('import json,sys\nprint(json.dumps(sys.argv[1:]))\n')
            fixture.atomic(directory/'fixture-arm.json',dict(scenario='P8001',control_sha='a'*40,trial_id='unit',environment='production'))
            fixture.atomic(directory/'fixture-heartbeat.json',dict(timestamp=dt.datetime.now(dt.timezone.utc).isoformat()))
            env=dict(RELEASE='v2',RELEASE_SHA='b'*40,TRIAL_ID='unit',SCENARIO='P8001',MEMOS_EXPERIMENT_ROOT=str(root))
            with patch.dict(os.environ,env),patch.object(fixture,'frozen_check'),patch.object(fixture,'__file__',str(script)), \
                 patch.object(fixture.subprocess,'check_output',return_value='a'*40), \
                 patch.object(fixture.shutil,'which',return_value='/usr/bin/docker'),patch.object(fixture.subprocess,'run') as run:
                run.return_value.returncode=0
                self.assertEqual(fixture.runner(),0)
                self.assertEqual(run.call_args.args[0][0],'pwsh')
            shim=directory/'docker-adapter/docker'
            self.assertTrue(os.access(shim,os.X_OK))
            result=subprocess.check_output([str(shim),'compose','path with space',"quote'argument"],text=True)
            self.assertEqual(json.loads(result),['docker','compose','path with space',"quote'argument"])


if __name__=='__main__':unittest.main()
