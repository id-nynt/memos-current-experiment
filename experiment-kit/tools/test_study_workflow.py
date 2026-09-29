"""Offline regressions for allocation, shared images, checkpoints and fail-closed helpers."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import batch_runner as batch
import image_identity as images
import job_events
import phase5_metrics as metrics
import phase8_matrix as matrix
import server_prepare
import study_batches as batches
import study_execution as execution
import pull_results
from test_pull_results import fixture
from test_local_batch import MockDriver


class StudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.design=matrix.build();cls.allocation=batches.build(cls.design)

    def test_allocation_exact_margins_and_corruption(self):
        self.assertEqual(batches.validate(self.allocation,self.design)['pairs'],100)
        bad=copy.deepcopy(self.allocation)
        bad['batches'][0]['cases'][0]=bad['batches'][1]['cases'][0]
        with self.assertRaises(ValueError):batches.validate(bad,self.design)
        bad=copy.deepcopy(self.allocation);bad['batches'][0]['cases'][0]['seed']+=1
        with self.assertRaises(ValueError):batches.validate(bad,self.design)

    def test_same_native_lifecycle_resumes_without_replaying(self):
        ids=[r['case_id'] for r in self.allocation['batches'][0]['cases']]
        with tempfile.TemporaryDirectory() as tmp:
            driver=MockDriver();path=Path(tmp)/'batch'
            batch.run(self.design,{},path,ids,driver=driver)
            candidates=[c for c in driver.calls if c[0]=='candidate']
            self.assertEqual([c[1] for c in candidates[::2]],ids)
            self.assertEqual(len(candidates),40)
            driver.calls.clear();batch.run(self.design,{},path,ids,driver=driver)
            self.assertEqual(driver.calls,[])

    def test_job_actions_count_and_conflicting_vocabulary_rejected(self):
        native=dict(complete=True,events=[dict(event='job_execution_started',job='production',attempt=1),
                                        dict(event='job_execution_started',job='rollback',attempt=2)],runs=[],run_ids=set())
        value=metrics.action_counts(native,'bdi')
        self.assertEqual((value['retries'],value['deployment_attempts'],value['rollbacks_started']),(1,2,1))
        with self.assertRaises(ValueError):job_events.normalize(dict(job='build',entity='test'))
        legacy=job_events.normalize(dict(event='entity_execution_finished',entity='test'))
        self.assertEqual(legacy,dict(event='job_execution_finished',job='test'))

    def test_shared_server_freeze_and_session_tamper(self):
        source=batch.read(batch.ROOT/'protocol/frozen-releases.json')
        proofs=batch.read(batch.ROOT/'tools/frozen-runtime-identities.json')
        # Use valid existing OCI proof but a different legacy source selector.
        frozen=copy.deepcopy(source);source=copy.deepcopy(source)
        source['releases']['v1']['image_id']='sha256:'+'a'*64
        body=dict(schema_version=1,source_releases=source,frozen_releases=frozen,proofs=proofs)
        body['sha256']=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        with tempfile.TemporaryDirectory() as tmp,patch.object(images.Path,'home',return_value=Path(tmp)):
            path=Path(tmp)/'.memos-experiment-images/session.json';batch.save(path,body)
            release=source['releases']['v1'];proof,config=images.proof(release)
            self.assertEqual(images.frozen_digest(release),frozen['releases']['v1']['image_id'])
            self.assertFalse(images.matches(release,release['image_id']))
            meta=dict(Id=proof['config_digest'],Os='linux',Architecture='amd64',Config=config['config'],RootFS={'Layers':config['rootfs']['diff_ids']})
            self.assertEqual(images.resolve(release,lambda _:meta)['image_session_sha256'],body['sha256'])
            effective=dict(application_sha=release['application_sha'],image_id=images.frozen_digest(release))
            self.assertTrue(images.matches(effective,meta['Id']))
            body['frozen_releases']['releases']['v1']['image_id']='changed';batch.save(path,body)
            with self.assertRaises(ValueError):images.session()

    def test_preparation_stages_preserve_failed_state(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(server_prepare,'SETUP',Path(tmp)):
            calls=[]
            server_prepare.step('good',lambda:calls.append('once'))
            server_prepare.step('good',lambda:calls.append('repeated'))
            self.assertEqual(calls,['once'])
            with self.assertRaises(RuntimeError):server_prepare.step('bad',lambda:(_ for _ in ()).throw(RuntimeError('infrastructure')))
            with self.assertRaisesRegex(ValueError,'Incomplete'):server_prepare.step('bad',lambda:calls.append('unsafe'))
            self.assertTrue((Path(tmp)/'bad/started.json').exists())

    def test_fixture_variable_targets_selected_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            selected=Path(tmp)/'detached-control'
            pins={'conventional':{'repository':'owner/conventional','control_sha':'a'*40}}
            with patch.object(server_prepare,'SETUP',Path(tmp)),patch('experiment.runtime',return_value=selected),\
                 patch.object(server_prepare,'run') as command,patch.object(server_prepare.subprocess,'check_output',return_value=str(selected)):
                server_prepare.fixture_root(pins)
            self.assertEqual(command.call_args.args[0][-1],selected)
            self.assertEqual(batch.read(Path(tmp)/'conventional-fixture-root.json')['path'],str(selected))

    def test_image_session_removal_stops_next_treatment(self):
        with patch.object(batch,'source_hashes',return_value={'source':'same'}),patch.object(batch.images_identity,'session',return_value=None):
            with self.assertRaisesRegex(ValueError,'image freeze'):
                batch.require_source_lock({'source':'same'},{'sha256':'expected'})

    def test_m001_first_checkpoint_does_not_run_faults(self):
        config={'execution_mode':'validation'};calls=[]
        with tempfile.TemporaryDirectory() as tmp,patch.object(execution,'ROOT',Path(tmp)),patch.object(execution,'SETUP',Path(tmp)/'setup'),\
             patch.object(execution.batch,'read',return_value=config),patch.object(execution,'execute',side_effect=lambda d,i,c:calls.extend(i)),\
             patch.object(execution,'healthy'),patch.object(execution.server,'approve_faults',return_value=0),patch.object(execution,'reference',return_value={}):
            execution.smoke(first=True)
        self.assertEqual(calls,['M001'])

    def test_missing_startup_evidence_cannot_enable_study(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(execution,'ROOT',Path(tmp)):
            with self.assertRaises(FileNotFoundError):execution.calibration({})

    def test_aggregate_requires_all_batches_and_same_configuration(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(execution,'ROOT',Path(tmp)),\
             patch.object(execution,'checked',return_value={'execution_mode':'study'}) as checked,\
             patch.object(execution.batch.metrics,'aggregate',return_value={}) as aggregated:
            config={'study_batches_sha256':batch.digest(batches.PATH)}
            for n in range(1,6):
                directory=Path(tmp)/f'results/study/batch-{n}'
                batch.save(directory/'batch.json',{'configuration':config})
                for case in execution.ids_for(f'batch-{n}'):
                    for arm in ('conventional','bdi'):batch.save(directory/case/arm/'metrics.json',{})
            execution.aggregate();self.assertEqual(checked.call_count,5)
            changed=Path(tmp)/'results/study/batch-5/batch.json'
            batch.save(changed,{'configuration':{**config,'controlled_seed_sha256':'changed'}})
            with self.assertRaisesRegex(ValueError,'configuration'):execution.aggregate()
            changed.unlink()
            with self.assertRaises(FileNotFoundError):execution.aggregate()
            self.assertEqual(aggregated.call_count,1)

    def test_download_one_independent_batch(self):
        entry=self.allocation['batches'][0];ids=[r['case_id'] for r in entry['cases']]
        with tempfile.TemporaryDirectory() as tmp:
            session=dict(frozen_releases=batch.read(batch.ROOT/'protocol/frozen-releases.json'))
            session['sha256']=hashlib.sha256(json.dumps(session,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            extra=dict(image_session=session,kit_commit='a'*40,study_batches_sha256=batch.digest(batches.PATH))
            root=Path(tmp);archive=fixture(root,ids,'study',extra_config=extra)
            extracted=root/'unpacked';manifest=pull_results.extract_verified(archive,extracted)
            output=root/'review';output.mkdir()
            self.assertEqual(pull_results.review([(extracted,manifest)],[],[],output,['batch-1']),0)
            self.assertEqual(pull_results.read(output/'review.json')['metric_records'],40)
            output=root/'wrong';output.mkdir()
            self.assertEqual(pull_results.review([(extracted,manifest)],[],[],output,['batch-2']),2)


if __name__=='__main__':unittest.main()
