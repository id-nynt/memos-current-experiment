"""Server preparation regressions; no candidate, Docker, or GitHub execution."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import batch_runner as b
import phase8_matrix as m
import server_execution as server
from test_local_batch import MockDriver


class ServerTests(unittest.TestCase):
    def test_only_bounded_platform_changes_to_deployment(self):
        import hashlib
        p=b.ROOT/'results/implementation/server-preparation/before/deploy.ps1'
        expected=b.read(b.ROOT/'results/implementation/phase7/verification.json')['changed_files']['memos-current/scripts/local-cd/deploy.ps1']
        self.assertEqual(b.digest(p),expected)
        text=(b.ROOT/'memos-current/scripts/local-cd/deploy.ps1').read_text()
        text=text.replace('            $identityTool = Join-Path $repo \'scripts/experiment-measurement/image_identity.py\'\n            $python = if ($linuxHost) { \'python3\' } else { \'python\' }\n            $identity = ((Invoke-Native $python @($identityTool, \'--manifest\', (Join-Path $repo \'scripts/local-cd/frozen-releases.json\'), \'--release\', $FrozenRelease)) -join "`n" | ConvertFrom-Json)\n            $image = $identity.runtime_image_id\n            $record.frozen_oci_digest = $identity.frozen_oci_digest\n            $record.runtime_image_id = $image\n', '            $image = $frozen.image_id\n')
        text=text.replace('and cross-platform PowerShell 7.','and PowerShell 7.')
        text=text.replace('$linuxHost = [Environment]::OSVersion.Platform -eq [PlatformID]::Unix\n','')
        text=text.replace("    $stateParent = if ($env:LOCALAPPDATA) { $env:LOCALAPPDATA } else { [Environment]::GetFolderPath('UserProfile') }\n    $StateDirectory = Join-Path $stateParent 'memos-current-experiment'","    $StateDirectory = Join-Path $env:LOCALAPPDATA 'memos-current-experiment'")
        text=text.replace('$linuxLease = $null\n','')
        start=text.index('    if ($linuxHost) {');end=text.index('    $runKey =',start)
        text=text[:start]+"    $deploymentLock = [IO.File]::Open((Join-Path $StateDirectory 'deployment.lock'), 'OpenOrCreate', 'ReadWrite', 'None')\n"+text[end:]
        text=text.replace('    if ($linuxLease) { [IO.File]::Delete($linuxLease) }\n','')
        self.assertEqual(text,p.read_text())

    def test_validation_claims_do_not_consume_study_cases(self):
        manifest=m.build()
        self.assertNotEqual(b.claim_ledger(manifest,{}),b.claim_ledger(manifest,dict(execution_mode='validation',validation_campaign='host-001')))
        with self.assertRaises(ValueError):b.claim_ledger(manifest,dict(execution_mode='validation',validation_campaign='../study'))

    def test_smoke_gate_exception_only_for_explicit_validation(self):
        config=b.read(b.ROOT/'protocol/batch-readiness.template.json')
        config.update(execution_mode='validation',validation_campaign='host-001')
        # Keep the historical-control check independent of later operator promotion.
        original_read = b.read
        def historical_read(path):
            value = original_read(path)
            if Path(path) == b.ROOT/'protocol/operator-revisions.json':
                value = copy.deepcopy(value)
                value['bdi']['control_sha'] = '87ecb07dd7c7ec4ef314715ce968708c71928d2e'
            return value
        with patch.object(b, 'read', side_effect=historical_read):
            errors=b.readiness(config,m.build())
        self.assertNotIn('representative_smoke_verified',errors)
        self.assertIn('execution_authorized',errors)
        self.assertIn('matching target-server evidence required',errors)
        self.assertTrue(any('historical control' in x for x in errors))
        config['execution_mode']='study'
        self.assertIn('representative_smoke_verified',b.readiness(config,m.build()))

    def test_validation_cannot_enter_primary_aggregate(self):
        with self.assertRaisesRegex(ValueError,'excluded'):
            b.metrics.aggregate([dict(execution_mode='validation')])

    def test_draft_never_authorizes_execution(self):
        with patch.object(b,'source_hashes',return_value={}):value=server.draft_config('validation','host-001')
        self.assertFalse(value['execution_authorized'])
        self.assertIsNone(value['server_evidence'])

    def test_case_and_set_use_same_real_batch_entry(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg=Path(temp)/'config.json';b.save(cfg,{})
            with patch.object(b,'run') as run,patch.object(server,'inspect_results',return_value={}):
                server.main(['run-case','M001','--config',str(cfg),'--directory',str(Path(temp)/'case')])
                self.assertEqual(run.call_args.args[3],['M001'])
                self.assertEqual(len(run.call_args.args),4) # No substitute driver.
                server.main(['run-set','A','--config',str(cfg),'--directory',str(Path(temp)/'set')])
                self.assertEqual(len(run.call_args.args[3]),50)

    def test_validation_config_rejected_for_sets(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg=Path(temp)/'config.json';b.save(cfg,dict(execution_mode='validation'))
            with patch.object(b,'run') as run,self.assertRaises(SystemExit):
                server.main(['run-set','A','--config',str(cfg),'--directory',str(Path(temp)/'set')])
            run.assert_not_called()

    def test_stop_finishes_current_arm_then_safe_resume_skips_it(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp)/'batch';driver=MockDriver();original=driver.candidate
            def candidate(*args):
                value=original(*args);(directory/'STOP').touch();return value
            driver.candidate=candidate
            b.run(m.build(),{},directory,['M001'],driver)
            self.assertEqual(sum(c[0]=='candidate' for c in driver.calls),1)
            self.assertFalse((directory/'active.lock').exists())
            self.assertEqual(b.read(directory/'M001/conventional/status.json')['status'],'valid')
            (directory/'STOP').unlink()
            resumed=MockDriver();b.run(m.build(),{},directory,['M001'],resumed)
            self.assertEqual([c[2] for c in resumed.calls if c[0]=='candidate'],['bdi'])

    def test_status_missing_attempt_is_incomplete_not_pending(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp);(directory/'M001/conventional').mkdir(parents=True)
            value=server.inspect_results(directory,m.build(),['M001'])
            self.assertEqual(value['counts']['valid'],0)
            self.assertEqual(value['cases'][0]['arms'][0]['status'],'incomplete')

    def test_result_validation_cannot_launch(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(b,'run') as run:
            result=server.inspect_results(temp,m.build(),['M001'],derive=True)
            self.assertFalse(result['all_selected_valid']);run.assert_not_called()

    def test_final_workflow_is_all_linux(self):
        from workflow_audit import reachable
        self.assertTrue(all(j['runner']==['self-hosted','linux','memos-bdi-deploy'] for j in reachable()))

    def test_offline_readiness_cannot_claim_target_checks(self):
        import server_readiness as readiness
        with patch.object(readiness,'probe',return_value=(False,'')) as probe, \
             patch.object(b,'source_hashes',return_value={}),patch('experiment.selection'):
            result=readiness.report(False)
        self.assertFalse(result['target_checks'])
        self.assertFalse(result['launch_authorized'])
        self.assertTrue(all(call.args[0][0]=='git' for call in probe.call_args_list))
        self.assertTrue(any(c['status']==readiness.DEFERRED for c in result['checks']))

    def test_smoke_cases_cover_required_mechanisms(self):
        cases=server.selection(m.build())
        chosen=[c for c in cases if c['case_id'] in server.SMOKE_CASES]
        self.assertEqual(len(chosen),9)
        self.assertTrue({'reference','deterministic_control','ci_retry','persistent','transient','intermittent','latency','staging'} <= {c['family'] for c in chosen})


if __name__=='__main__':unittest.main()
