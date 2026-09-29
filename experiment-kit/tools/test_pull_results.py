"""Synthetic local bundles and mocked SCP only; no server or experiment access."""
import copy
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import pull_results as pull


def fixture(root, ids=('M001',), mode='validation', name='trial.tar.gz', failure=False, extra_config=None):
    design=pull.matrix_document(); cases={c['case_id']:c for c in design['cases']}
    files={}
    def put(name,value):
        data=json.dumps(value).encode(); files[name]=data
        return hashlib.sha256(data).hexdigest()
    configuration=dict(controlled_seed_sha256='a'*64,source_hashes={'source':'hash'},
                       matrix_sha256=pull.matrix.sha(design),operator_manifest_sha256='b'*64,measurement_policy={'fixed':True})
    configuration.update(extra_config or {})
    put('batch.json',dict(identity=dict(selection=list(ids),execution_mode=mode,matrix_sha256=pull.matrix.sha(design)),configuration=configuration))
    server=[]
    for cid in ids:
        case=cases[cid]
        server.append(dict(case_id=cid,status='valid',arms=[dict(treatment=a,status='valid') for a in ('conventional','bdi')]))
        for arm in ('conventional','bdi'):
            folder=cid+'/'+arm+'/'
            metrics=dict(identity=dict(case_id=cid,treatment=arm),boundaries={},execution_mode=mode,
                reliability=dict(requests_total=10,requests_failed=0,requests_successful=10,error_rate=0,
                    availability_estimate=0.99,coverage=0.99,endpoint_health=True,endpoint_release='healthy_v2',
                    candidate_delivered=True,native_outcome='achieved'),
                resilience=dict(applicable=False,recovery_seconds=None),cost=dict(candidate_seconds=30),
                validity=dict(status='valid',observation_complete=True,evidence_complete=True),
                exact_count_measurement=dict(workload={env:dict(requests_started=10,requests_completed=10,
                    pending_or_missing_completions=0,request_duration_ms=dict(n=10,p95_ms=20)) for env in ('production','staging')}))
            if case['parameters']['stage']=='staging':metrics['staging']={'error_rate':0}
            if configuration.get('image_session'):
                release=configuration['image_session']['frozen_releases']['releases']['v2']
                metrics['identity'].update(application_sha=release['application_sha'],frozen_oci_digest=release['image_id'])
            if failure:metrics['reliability']['native_outcome']='failure'
            mh=put(folder+'metrics.json',metrics)
            sh=put(folder+'metric-spec.json',dict(case_id=cid,treatment=arm))
            put(folder+'declaration.json',dict(case=case))
            raw=put(folder+'evidence/synthetic.json',dict(synthetic=True))
            put(folder+'evidence-seal.json',{'synthetic.json':raw})
            receipt=dict(verified=True,synthetic=True)
            before=put(folder+'reset_before/baseline-receipt.json',receipt)
            after=put(folder+'reset_after/baseline-receipt.json',receipt)
            put(folder+'status.json',dict(status='valid',case_id=cid,treatment=arm,spec_sha256=case['spec_sha256'],
                result=dict(metrics_sha256=mh,metric_spec_sha256=sh),
                baseline=dict(verified=True,seed_sha256='a'*64,receipt_sha256=before),
                final_reset=dict(verified=True,seed_sha256='a'*64,receipt_sha256=after)))
    manifest=dict(validation=dict(execution_mode=mode,completed_pairs=len(ids),all_selected_valid=True,cases=server),
                  files={name:hashlib.sha256(data).hexdigest() for name,data in files.items()})
    target=root/name
    with tarfile.open(target,'w:gz') as archive:
        for path,data in [('bundle-manifest.json',json.dumps(manifest).encode()),*[('results/'+n,d) for n,d in files.items()]]:
            member=tarfile.TarInfo(path);member.size=len(data);archive.addfile(member,io.BytesIO(data))
    Path(str(target)+'.sha256').write_text(pull.digest(target)+'  '+target.name+'\n')
    return target


class PullTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def test_first_trial_all_metrics_and_no_automatic_approval(self):
        bundle=fixture(self.root);out=self.root/'download'
        self.assertEqual(pull.main(['--bundles',str(bundle),'--expect-case','M001','--output',str(out)]),0)
        report=pull.read(out/'review.json')
        self.assertEqual(report['metric_records'],2)
        self.assertFalse(report['study_approved'])
        self.assertTrue(report['human_review_required'])
        self.assertIsNone(report['records'][0]['metrics']['resilience']['recovery_seconds'])
        self.assertIn('exact_count_measurement.workload.production.request_duration_ms.p95_ms',(out/'metrics.csv').read_text(encoding='utf-8-sig'))

    def test_both_final_sets_and_wrong_mode_rejected(self):
        groups={s:[c['case_id'] for c in pull.matrix_document()['cases'] if c['test_set']==s] for s in ('A','B')}
        a=fixture(self.root,groups['A'],'study','A.tar.gz',failure=True)
        b=fixture(self.root,groups['B'],'study','B.tar.gz',failure=True)
        out=self.root/'all'
        self.assertEqual(pull.main(['--bundles',str(a),str(b),'--expect-sets','A','B','--output',str(out)]),0)
        self.assertEqual(pull.read(out/'review.json')['metric_records'],200)
        self.assertEqual(pull.main(['--bundles',str(a),'--expect-case','M001','--output',str(self.root/'wrong')]),2)

    def test_bad_healthy_outcome_needs_attention(self):
        bundle=fixture(self.root,failure=True)
        self.assertEqual(pull.main(['--bundles',str(bundle),'--expect-case','M001','--output',str(self.root/'review')]),2)

    def test_changed_evidence_and_missing_reset_are_rejected(self):
        bundle=fixture(self.root)
        extracted=self.root/'extracted'
        manifest=pull.extract_verified(bundle,extracted)
        arm=extracted/'results/M001/conventional'
        (arm/'evidence/synthetic.json').write_text('{}')
        state=pull.read(arm/'status.json')
        state['final_reset']['verified']=False
        (arm/'status.json').write_text(json.dumps(state))
        cases={c['case_id']:c for c in pull.matrix_document()['cases']}
        check=pull.check_bundle(extracted,manifest,cases,'validation')
        self.assertTrue(any('evidence seal' in e for e in check['errors']))
        self.assertTrue(any('reset_after not verified' in e for e in check['errors']))

    def test_scp_download_uses_argv_and_downloads_checksum(self):
        bundle=fixture(self.root);calls=[]
        def scp(argv,**kwargs):
            calls.append(argv)
            source=Path(str(bundle)+('.sha256' if argv[-2].endswith('.sha256') else ''))
            Path(argv[-1]).write_bytes(source.read_bytes())
        with patch.object(pull.subprocess,'run',side_effect=scp):
            code=pull.main(['--server','user@host','--remote','~/experiment/trial.tar.gz',
                            '--expect-case','M001','--output',str(self.root/'scp')])
        self.assertEqual(code,0);self.assertEqual(len(calls),2)
        self.assertEqual(calls[0][:4],['scp','-P','22','--'])

    def test_checksum_failure_preserves_files_without_extraction(self):
        bundle=fixture(self.root);bundle.write_bytes(bundle.read_bytes()+b'tamper')
        out=self.root/'bad'
        self.assertEqual(pull.main(['--bundles',str(bundle),'--expect-case','M001','--output',str(out)]),1)
        self.assertTrue((out/'download-error.json').exists())
        self.assertEqual(list((out/'unpacked').iterdir()),[])

    def test_unsafe_paths_and_remote_shell_syntax_rejected(self):
        for path in ('../x','/etc/passwd','results/../x','results/C:/x','results/a\\b','results/NUL','results/file.','results//x'):
            with self.assertRaises(ValueError):pull.safe_member(path)
        for server, remote in [('-oProxyCommand=x','~/x.tar.gz'),('user@host','~/x;id.tar.gz'),('user@host','~/../x.tar.gz')]:
            with self.assertRaises(ValueError):pull.remote_sources(server,[remote])

    def test_existing_destination_preserved(self):
        bundle=fixture(self.root);out=self.root/'exists';out.mkdir()
        with self.assertRaises(FileExistsError):
            pull.main(['--bundles',str(bundle),'--expect-case','M001','--output',str(out)])


if __name__=='__main__':unittest.main()
