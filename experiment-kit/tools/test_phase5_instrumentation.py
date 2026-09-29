from test_image_identity import historical_rollback
"""Offline mocked integration checks for native observers; no live HTTP/Docker."""
import ast
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec)
    with patch.object(sys,'path',[str(path.parent),*sys.path]):spec.loader.exec_module(value)
    return value


class Instrumentation(unittest.TestCase):
    def test_bdi_single_request_uses_same_timeout_cadence_and_normalized_record(self):
        observer=module('phase5_observer',ROOT/'memos-bdi/experiment/scripts/observe.py')
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            state=Path(tmp); (state/'bdi/production').mkdir(parents=True)
            (state/'bdi/production/credential.json').write_text(json.dumps(dict(token='synthetic',sentinel_name='memos/test',sentinel_content='expected')))
            trial=observer.TrialObserver(dict(state=tmp),state,'S0'); captured=[]
            def stop_after_one(wait):
                self.assertGreaterEqual(wait,0); self.assertLessEqual(wait,1); trial.stop.set()
            with patch.object(observer,'http',return_value=(200,b'{"content":"expected"}')) as request, \
                 patch.object(observer,'event',side_effect=lambda *a,**kw:captured.append(kw)), \
                 patch.object(trial.stop,'wait',side_effect=stop_after_one):
                trial.run_workload()
            request.assert_called_once(); self.assertEqual(request.call_args.kwargs['timeout'],3)
            self.assertIn('request_id',captured[0]);self.assertTrue(captured[1]['success']); self.assertEqual(captured[1]['measurement_version'],2)
            self.assertIsNone(trial.error)

    def test_docker_observer_failure_does_not_become_service_outage(self):
        observer=module('phase5_observer2',ROOT/'memos-bdi/experiment/scripts/observe.py')
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            state=Path(tmp); (state/'bdi/production').mkdir(parents=True)
            (state/'bdi/production/credential.json').write_text('{}')
            with patch.object(observer.subprocess,'check_output',side_effect=subprocess.TimeoutExpired('docker',5)):
                row=observer.sample(dict(state=tmp))
            self.assertTrue(row['measurement_error']); self.assertFalse(row['healthy'])

    def test_conventional_active_health_boolean_preserved_on_observer_failure(self):
        observer=module('phase5_common',ROOT/'memos-current/scripts/experiment-measurement/measure_trial.py')
        with patch.object(observer,'read',return_value={}),patch.object(observer.subprocess,'check_output',side_effect=OSError('offline')):
            row=observer.sample(dict(credential_file='unused',production_container='unused'))
        self.assertTrue(row['measurement_error']); self.assertFalse(row['healthy'])

    def test_observer_scheduling_and_timeout_literals_unchanged_from_pin(self):
        files=[('memos-bdi','experiment/scripts/observe.py','87ecb07dd7c7ec4ef314715ce968708c71928d2e'),
               ('memos-current','experiment/manage.py','a3bd68d3561b19e2eba3121ac0345f63eafbbd0b')]
        def timing(source):
            tree=ast.parse(source)
            result=[]
            for n in ast.walk(tree):
                if isinstance(n,ast.Call):
                    name=ast.unparse(n.func)
                    if name in ('time.sleep','self.stop.wait','stop_workload.wait','time.monotonic') or any(k.arg=='timeout' for k in n.keywords):
                        # New monotonic reads are instrumentation, not waits.
                        if name not in ('time.monotonic','thread.join'):
                            # Phase 7 adds staging targeting and request stream labels.
                            # Compare timing policy, not the approved routing arguments.
                            timeout=[ast.dump(k.value,include_attributes=False) for k in n.keywords if k.arg=='timeout']
                            result.append((name,tuple(timeout)) if timeout else (name,ast.dump(n,include_attributes=False)))
            return sorted(result)
        for repo,name,pin in files:
            old=subprocess.check_output(['git','-C',str(ROOT/repo),'show',pin+':'+name],text=True)
            self.assertEqual(timing(old),timing((ROOT/repo/name).read_text()),name)

    def test_native_rollback_body_unchanged_from_verified_pin(self):
        name='experiment/scripts/operate.py'; repo=ROOT/'memos-bdi'
        old=subprocess.check_output(['git','-C',str(repo),'show','87ecb07dd7c7ec4ef314715ce968708c71928d2e:'+name],text=True)
        def body(source):return ast.dump(next(n for n in ast.parse(historical_rollback(source)).body if isinstance(n,ast.FunctionDef) and n.name=='rollback'),include_attributes=False)
        self.assertEqual(body(old),body((repo/name).read_text()))


if __name__=='__main__':unittest.main()
