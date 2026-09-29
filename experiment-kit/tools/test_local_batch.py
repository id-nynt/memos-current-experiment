"""Offline matrix, failure-path, resume and workflow tests. No Docker/GitHub."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import batch_runner as b
import phase8_matrix as m
import scenario_runtime as s
import workflow_audit as w


class MockDriver:
    """Synthetic lifecycle only; never imported by the command-line runner."""
    def __init__(self,fail=None):self.calls=[];self.fail=fail;self.serial=0
    def call(self,name,case,arm):
        self.calls.append((name,case['case_id'],arm))
        if self.fail==name:raise RuntimeError('injected infrastructure failure')
    def prerequisites(self,c,a,p):self.call('prerequisites',c,a);p.mkdir()
    def reset(self,c,a,p):
        self.call('reset',c,a);p.mkdir();self.serial+=1
        return dict(verified=True,seed_sha256='a'*64,receipt_sha256=str(self.serial))
    def candidate(self,c,a,p):self.call('candidate',c,a);p.mkdir();return p
    def collect(self,c,a,n,p,t):
        self.call('collect',c,a);p.mkdir()
        b.save(p/'synthetic.json',dict(synthetic=True,case=c['case_id'],arm=a),new=True)
        b.save(p.parent/'metrics.json',dict(synthetic=True,validity='valid'),new=True)
        b.save(p.parent/'evidence-seal.json',b.hashes(p),new=True)
        return dict(validity='valid',native_outcome='failure' if a=='conventional' else 'achieved',metrics_sha256=b.digest(p.parent/'metrics.json'))


class MatrixTests(unittest.TestCase):
    def test_two_disjoint_balanced_sets_without_historical_scenarios(self):
        from collections import Counter
        cases=m.build()['cases']
        groups={name:[c for c in cases if c['test_set']==name] for name in ('A','B')}
        self.assertEqual([len(x) for x in groups.values()],[50,50])
        self.assertFalse({c['case_id'] for c in groups['A']} & {c['case_id'] for c in groups['B']})
        counts={k:Counter(c['family'] for c in v) for k,v in groups.items()}
        for family in set(counts['A'])|set(counts['B']):
            self.assertLessEqual(abs(counts['A'][family]-counts['B'][family]),1)
        for group in groups.values():
            self.assertEqual(sum(c['treatments'][0]=='bdi' for c in group),25)
        self.assertFalse(any(c['scenario'].startswith('S') for c in cases))
        self.assertEqual(cases[2]['scenario'],'CI01')
    def test_exact_reproducibility(self):
        value=b.read(m.MANIFEST);self.assertEqual(value,m.build());self.assertEqual(m.validate(value)['cases'],100)
    def test_all_profiles_copied_and_resolve(self):
        original=(b.ROOT/'protocol/matrix-scenarios.json').read_bytes()
        for folder in ('tools','memos-current/experiment','memos-bdi/experiment/scripts'):
            self.assertEqual(original,(b.ROOT/folder/'matrix-scenarios.json').read_bytes())
        for c in m.build()['cases']:
            if c['spec']:self.assertEqual(s.resolve(c['scenario']),c['spec'])
    def test_pairing_seed_and_window(self):
        for c in m.build()['cases']:
            self.assertEqual(set(c['treatments']),{'conventional','bdi'})
            self.assertEqual(c['horizon_seconds'],300)
            self.assertIsInstance(c['parameters']['seed'],int)
            if c['spec']:self.assertEqual(m.sha(c['spec']),c['spec_sha256'])
    def test_tampered_parameters_rejected(self):
        value=m.build();value['cases'][4]['spec']['seed']+=1
        with self.assertRaises(ValueError):m.validate(value)
    def test_unknown_selection_rejected(self):
        with self.assertRaises(ValueError):b.plan(m.build(),['M999'])
    def test_selection_order_stable(self):
        self.assertEqual([c['case_id'] for c in b.selected(m.build(),['M005','M001'])],['M005','M001'])
        with self.assertRaises(ValueError):b.selected(m.build(),['M001','M001'])
    def test_plan_all_lifecycle_steps(self):
        rows=b.plan(m.build());self.assertEqual(len(rows),200)
        self.assertTrue(all(r['steps']==list(b.STEPS) for r in rows))
    def test_diagnostic_stratum_separate(self):
        diag=[c for c in m.build()['cases'] if c['analysis_stratum']=='dependency_diagnostic']
        self.assertEqual(len(diag),0)
    def test_thresholds_and_late_faults(self):
        episodes=[e for c in m.build()['cases'] for e in c['parameters']['episodes']]
        self.assertTrue({4,5,6}.issubset({e['error_percent'] for e in episodes}))
        self.assertTrue({450,500,550}.issubset({e['delay_ms'] for e in episodes}))
        self.assertTrue(any(e['start']>150 for e in episodes))


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'batch';self.manifest=m.build();self.config={'synthetic':True}
    def run_mock(self,driver=None,ids=None):
        driver=driver or MockDriver()
        b.run(self.manifest,self.config,self.path,ids or ['M001'],driver=driver)
        return driver
    def test_full_200_candidate_mock_lifecycle(self):
        driver=self.run_mock(ids=[c['case_id'] for c in self.manifest['cases']])
        self.assertEqual(sum(x[0]=='candidate' for x in driver.calls),200)
        self.assertEqual(b.read(self.path/'index.json')['valid'],200)
        self.assertFalse((self.path/'active.lock').exists())
    def test_native_failure_can_be_valid(self):
        self.run_mock();row=b.read(self.path/'M001/conventional/status.json')
        self.assertEqual(row['status'],'valid');self.assertEqual(row['result']['native_outcome'],'failure')
    def test_completed_candidates_never_rerun(self):
        self.run_mock();second=self.run_mock();self.assertEqual(second.calls,[])
    def test_every_failure_retains_lock_and_stops(self):
        for operation in ('prerequisites','reset','candidate','collect'):
            with self.subTest(operation=operation),tempfile.TemporaryDirectory() as tmp:
                p=Path(tmp)/'batch';driver=MockDriver(operation)
                with self.assertRaises(RuntimeError):b.run(self.manifest,self.config,p,['M001'],driver)
                self.assertTrue((p/'active.lock').exists())
                self.assertEqual(b.read(p/'index.json')['valid'],0)
                with self.assertRaises(FileExistsError):b.run(self.manifest,self.config,p,['M001'],MockDriver())
    def test_reboot_or_foreign_lock_not_stolen(self):
        self.path.mkdir();(self.path/'active.lock').mkdir()
        with self.assertRaises(FileExistsError):self.run_mock()
    def test_partial_case_not_rerun_even_after_manual_lock_reconciliation(self):
        self.path.mkdir();p=self.path/'M001/conventional';p.mkdir(parents=True)
        b.save(p/'status.json',{'status':'in_progress'})
        with self.assertRaises(ValueError):self.run_mock()
    def test_seal_tampering_stops_resume(self):
        self.run_mock();(self.path/'M001/conventional/evidence/synthetic.json').write_text('{}')
        with self.assertRaises(ValueError):self.run_mock()
    def test_metric_tampering_stops_resume(self):
        self.run_mock();(self.path/'M001/conventional/metrics.json').write_text('{}')
        with self.assertRaises(ValueError):self.run_mock()
    def test_config_drift_stops_resume(self):
        self.run_mock();self.config['changed']=True
        with self.assertRaises(ValueError):self.run_mock()
    def test_unverified_reset_cannot_launch(self):
        d=MockDriver();d.reset=lambda *args:{'verified':False}
        with self.assertRaises(ValueError):self.run_mock(d)
        self.assertFalse(any(c[0]=='candidate' for c in d.calls))
    def test_measurement_failure_is_not_treatment_success(self):
        d=MockDriver();d.collect=lambda *args:{'validity':'incomplete'}
        with self.assertRaises(ValueError):self.run_mock(d)
        row=b.read(self.path/'M001/conventional/status.json')
        self.assertEqual(row['status'],'invalid_or_incomplete')
    def test_post_reset_failure_not_marked_complete(self):
        d=MockDriver();original=d.reset
        def reset(*args):
            result=original(*args)
            if d.serial==2:result['seed_sha256']='different'
            return result
        d.reset=reset
        with self.assertRaises(ValueError):self.run_mock(d)
        self.assertEqual(b.read(self.path/'index.json')['valid'],0)
    def test_interrupt_preserves_unresolved_state(self):
        d=MockDriver();d.candidate=lambda *args:(_ for _ in ()).throw(KeyboardInterrupt())
        with self.assertRaises(KeyboardInterrupt):self.run_mock(d)
        self.assertTrue((self.path/'active.lock').exists())
        self.assertEqual(b.read(self.path/'M001/conventional/status.json')['status'],'interrupted')
    def test_path_escape_rejected(self):
        with self.assertRaises(ValueError):b.local_path('/tmp/foreign-evidence')
    def test_template_cannot_execute(self):
        config=b.read(b.ROOT/'protocol/batch-readiness.template.json')
        with self.assertRaises(ValueError):b.readiness(config,self.manifest,live=True)
    def test_cross_batch_claim_prevents_duplicate_execution(self):
        ledger=Path(self.tmp.name)/'ledger';case=self.manifest['cases'][0]
        b.claim_case(ledger,case,'bdi',self.path)
        with self.assertRaises(FileExistsError):b.claim_case(ledger,case,'bdi',self.path/'new-batch')
    def test_ci_receipt_provenance_and_fault_time(self):
        p=Path(self.tmp.name)/'ci';p.mkdir()
        release=b.read(b.ROOT/'protocol/frozen-releases.json')['releases']['v2']['application_sha']
        native=dict(campaign_id='campaign',control_sha='control')
        receipt=dict(identity=dict(attempt=1,campaign_id='campaign',control_sha='control',release_sha=release),
            responses=[dict(status=503,timestamp='2026-09-29T00:00:01Z')],primary_status=503,clearance_status=200)
        b.save(p/'s6-receipt.json',receipt)
        with patch.object(b.metrics,'native_case',return_value=native):
            fault=b.ci_fault(p,'bdi');self.assertEqual(fault['kind'],'ci')
        self.assertEqual(json.loads((p/'batch-derived-ci.jsonl').read_text())['timestamp'],'2026-09-29T00:00:01Z')
    def test_ci_foreign_receipt_rejected(self):
        p=Path(self.tmp.name)/'ci';p.mkdir()
        b.save(p/'s6-receipt.json',{'identity':{'attempt':1,'campaign_id':'foreign'}})
        with patch.object(b.metrics,'native_case',return_value=dict(campaign_id='expected',control_sha='control')):
            with self.assertRaises(ValueError):b.ci_fault(p,'bdi')


class WorkflowTests(unittest.TestCase):
    def test_approved_coverage_cannot_be_relaxed(self):
        config=b.read(b.ROOT/'protocol/batch-readiness.template.json')
        config['measurement_policy']['coverage']['minimum_fraction']=.5
        self.assertIn('measurement policy differs from approved final coverage contract',
                      b.readiness(config,m.build()))
    def test_common_immutable_upgrade_baseline(self):
        import yaml
        values=[]
        for repo,entry in [('memos-current','frozen-cd.yml'),('memos-bdi','entity-execution.yml')]:
            if repo == 'memos-bdi':
                entry=b.read(b.ROOT/repo/'experiment/adapter-contract.json')['workflow_file']
            doc=yaml.safe_load((b.ROOT/repo/'.github/workflows'/entry).read_text())
            values.append(doc['jobs']['upgrade']['with']['previous_image'])
        self.assertEqual(values[0],values[1])
        self.assertRegex(values[0],r'^neosmemo/memos@sha256:[0-9a-f]{64}$')
    def test_mid_batch_source_drift_rejected(self):
        with patch.object(b,'source_hashes',return_value={'file':'changed'}):
            with self.assertRaises(ValueError):b.require_source_lock({'file':'reviewed'})
    def test_source_lock_includes_controller_but_not_generated_or_private_state(self):
        sources=b.source_hashes()
        self.assertIn('memos-bdi/bdi-cicd-framework/run_controller.py',sources)
        self.assertIn('memos-bdi/bdi-cicd-framework/generator/controller_generic.asl',sources)
        for path in sources:
            self.assertFalse(set(Path(path).parts)&{'.venv','venv','runs','results','bin','build','.runtime'})
    def test_entire_executable_closure_self_hosted(self):
        jobs=w.reachable();self.assertGreater(len(jobs),15)
        self.assertTrue(all('self-hosted' in j['runner'] for j in jobs))
    def test_quality_copies_preserve_job_bodies(self):
        for repo in w.ENTRIES:
            folder=b.ROOT/repo/'.github/workflows'
            for name in ('backend-tests','frontend-tests','proto-linter','upgrade-smoke'):
                original=w.load(folder/(name+'.yml'));current=w.load(folder/('experiment-'+name+'.yml'))
                for job in original['jobs'].values():job['runs-on']=w.ALLOWED[0]
                if name == 'upgrade-smoke':
                    # Authorized experiment-only reuse of retained images. All actual
                    # smoke assertions and other quality jobs must remain unchanged.
                    steps=current['jobs']['release-smoke']['steps']
                    steps[:]=[s for s in steps if s.get('name') not in (
                        'Checkout selected control for frozen identities', 'Resolve retained experiment candidate')]
                    smoke=next(s for s in steps if s.get('name')=='Run release smoke test')
                    self.assertEqual(smoke['env'].pop('MEMOS_SMOKE_CANDIDATE_IMAGE'), '${{ steps.frozen.outputs.image }}')
                    previous=next(s for s in original['jobs']['release-smoke']['steps'] if s.get('name')=='Run release smoke test')
                    if 'env' not in previous:
                        self.assertEqual(smoke.pop('env'), {'MEMOS_SMOKE_PREVIOUS_IMAGE':'${{ inputs.previous_image }}'})
                self.assertEqual(original['jobs'],current['jobs'])
                self.assertEqual(set(current['on']),{'workflow_call'})
    def test_hosted_or_remote_reusable_insertion_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for repo,entry in w.ENTRIES.items():
                p=root/repo/'.github/workflows';p.mkdir(parents=True)
                (p/entry).write_text('on: {workflow_dispatch: {}}\njobs:\n  test:\n    runs-on: ubuntu-latest\n')
            with self.assertRaises(ValueError):w.reachable(root)
            for repo,entry in w.ENTRIES.items():
                (root/repo/'.github/workflows'/entry).write_text('jobs:\n  test:\n    uses: foreign/repo/.github/workflows/x.yml@main\n')
            with self.assertRaises(ValueError):w.reachable(root)
    def test_current_matrix_enabled_for_conventional(self):
        enabled=b.read(b.ROOT/'memos-current/experiment/scenarios.json')
        for c in m.build()['cases']:self.assertTrue(enabled[c['scenario']]['enabled'])


class NativeCollectionTests(unittest.TestCase):
    def test_both_native_trace_formats_normalize_through_real_batch_adapter(self):
        import test_phase5_metrics as fixtures
        fixture=fixtures.Metrics();fixture.setUp()
        try:
            case=m.build()['cases'][0]
            config=b.read(b.ROOT/'protocol/batch-readiness.template.json')
            config.update(controlled_seed_sha256='a'*64,clock_alignment_verified=True)
            driver=b.NativeDriver(config)
            results=[]
            for arm in ('conventional','bdi'):
                spec=fixture.fixture(arm);root=Path(spec['evidence_directory'])
                row=json.loads((root/'workload.jsonl').read_text().splitlines()[0])
                sample=json.loads((root/'common-observations.jsonl').read_text().splitlines()[0])
                fixture.write(root,'workload.jsonl',[dict(row,request_id='production-'+str(t),timestamp=fixtures.at(t),request_started_at=fixtures.at(t),request_completed_at=fixtures.at(t)) for t in range(301)],True)
                fixture.write(root,'workload-starts.jsonl',[dict(request_id='production-'+str(t),request_started_at=fixtures.at(t)) for t in range(301)],True)
                fixture.write(root,'common-observations.jsonl',[dict(sample,timestamp=fixtures.at(t)) for t in range(301)],True)
                release=fixture.releases['v2'];start=float(b.metrics.stamp(fixtures.at(0)))
                identity=dict(release='v2',release_sha=release['application_sha'],image_id=release['image_id'],environment='production',project='owned',trial_id='campaign' if arm=='bdi' else 'trial')
                fixture.write(root,'scenario-schedule.json',s.lease(case['spec'],identity,start,0))
                fixture.write(root,'fault-summary.json',dict(version=s.VERSION,groups=[],blocks=[],exact_requests=[],evidence_complete=True))
                fixture.write(root,'observation-horizon.json',dict(horizon_seconds=300,measurement_start_epoch=start,endpoint_epoch=start+300))
                v1=fixture.releases['v1']
                fixture.write(root,'reset-state.json',dict(archive_sha256='a'*64,verified=True,data_semantics='shared-controlled-seed',application_sha=v1['application_sha'],image_id=v1['image_id']))
                target=fixture.root/'collected'/case['case_id']/arm;target.mkdir(parents=True)
                before=b.hashes(root)
                with patch.object(driver,'operator'):
                    result=driver.collect(case,arm,root,target/'evidence',fixtures.at(0))
                self.assertEqual(before,b.hashes(root));self.assertEqual(result['validity'],'valid')
                normalized=b.read(target/'metrics.json');results.append(normalized)
                self.assertEqual(normalized['cost']['candidate_seconds'],10)
                self.assertEqual(normalized['reliability']['requests_total'],300)
                self.assertEqual(normalized['reliability']['error_rate'],0)
                self.assertTrue(normalized['validity']['reset_excluded'])
                b.save(target/'status.json',dict(case_id=case['case_id'],treatment=arm,spec_sha256=case['spec_sha256'],
                    status='valid',step='complete',result=result,final_reset={'verified':True}))
            self.assertEqual(b.metrics.aggregate(results)['complete_pair_n'],1)
            b.save(fixture.root/'collected/batch.json',dict(identity=dict(matrix_sha256=m.sha(m.build()),selection=[case['case_id']],execution_mode='study')))
            from server_execution import inspect_results
            validated=inspect_results(fixture.root/'collected',m.build(),derive=True)
            self.assertTrue(validated['all_selected_valid'],validated)
            self.assertEqual(validated['aggregate']['complete_pair_n'],1)
        finally:fixture.doCleanups()


if __name__=='__main__':unittest.main()
