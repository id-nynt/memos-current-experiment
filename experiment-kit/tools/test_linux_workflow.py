"""Offline regressions for fresh-image provenance and result transfer."""
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import linux_prepare as prep
import export_results as export
import batch_runner as batch
from test_frozen_artifacts import bundle


class LinuxWorkflowTests(unittest.TestCase):
    def test_upgrade_workflows_reuse_verified_image_and_accept_baseline_input(self):
        import ast
        import subprocess
        import yaml
        pins = batch.read(batch.ROOT/'protocol/operator-revisions.json')
        for arm in ('conventional', 'bdi'):
            repo = batch.ROOT/pins[arm]['checkout']
            name = '.github/workflows/experiment-upgrade-smoke.yml'
            old = subprocess.check_output(['git','-C',str(repo),'show',pins[arm]['control_sha']+':'+name], text=True)
            updated = prep.frozen_upgrade_workflow(old)
            self.assertEqual(updated, prep.frozen_upgrade_workflow(updated))
            self.assertEqual(updated, (repo/name).read_text())
            workflow = yaml.load(updated, Loader=yaml.BaseLoader)
            self.assertIn('previous_image', workflow['on']['workflow_call']['inputs'])
            steps = workflow['jobs']['release-smoke']['steps']
            resolve = next(s for s in steps if s.get('id') == 'frozen')
            code = resolve['run'].split("<<'PY'\n",1)[1].rsplit('\nPY',1)[0]
            ast.parse(code)
            self.assertIn('image_identity.resolve', code)
            self.assertEqual(resolve['if'], "inputs.release_sha != ''")
            smoke = next(s for s in steps if s['name'] == 'Run release smoke test')
            self.assertEqual(smoke['env']['MEMOS_SMOKE_CANDIDATE_IMAGE'], '${{ steps.frozen.outputs.image }}')
            self.assertEqual(smoke['env']['MEMOS_SMOKE_PREVIOUS_IMAGE'], '${{ inputs.previous_image }}')

    def test_reset_receipt_is_portable_and_byte_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); op = root/'op'; op.mkdir()
            release = batch.read(batch.ROOT/'protocol/frozen-releases.json')['releases']['v1']
            receipt = dict(seed_sha256='a'*64, observations={env: dict(healthy=True,
                application_sha=release['application_sha'], image_id=release['image_id'])
                for env in ('staging', 'production')})
            (op/'baseline-receipt.json').write_text(json.dumps(receipt, indent=4)+'\n')
            driver = batch.NativeDriver(dict(controlled_seed_sha256='a'*64))
            with patch.object(driver, 'operator', return_value=(op, op)):
                result = driver.reset({}, 'conventional', root/'reset')
            self.assertTrue(result['verified'])
            self.assertEqual(batch.digest(root/'reset/baseline-receipt.json'), result['receipt_sha256'])

    def test_fresh_archive_proof_and_unwrapped_buildkit_index(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frozen, config = bundle(root)
            release = frozen['releases']['v1']
            # Model the OCI exporter whose index.json directly lists platforms.
            with tarfile.open(root/'v1.tar') as src, tarfile.open(root/'buildkit.tar', 'w') as dst:
                for entry in src:
                    if entry.name == 'index.json':
                        data = src.extractfile('blobs/sha256/'+release['image_id'].split(':')[1]).read()
                        entry = tarfile.TarInfo('index.json'); entry.size = len(data)
                        dst.addfile(entry, io.BytesIO(data))
                    elif entry.name != 'blobs/sha256/'+release['image_id'].split(':')[1]:
                        dst.addfile(entry, src.extractfile(entry))
            digest = prep.canonical_archive(root/'buildkit.tar', root/'canonical.tar')
            self.assertEqual(digest, release['image_id'])
            proof = prep.identity_proof(root/'canonical.tar', release, 'v1')
            self.assertEqual(proof['config_digest'], config)

    def test_export_preserves_files_and_rejects_secret_or_image(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); run = root/'run'; run.mkdir()
            (run/'batch.json').write_text('{}')
            (run/'metrics.json').write_text('{"errors": 7}')
            with patch.object(export, 'inspect_results', return_value={'all_selected_valid': True}), patch.object(export.batch, 'ROOT', root):
                output = root/'bundle.tar.gz'
                export.export(run, output)
                with tarfile.open(output) as archive:
                    self.assertEqual(archive.extractfile('results/metrics.json').read(), (run/'metrics.json').read_bytes())
                self.assertTrue(Path(str(output)+'.sha256').is_file())
                export.verify(output)
                with output.open('ab') as stream: stream.write(b'tamper')
                with self.assertRaisesRegex(ValueError, 'checksum'):
                    export.verify(output)
                (run/'private.json').write_text('{"access_token":"secret"}')
                with self.assertRaisesRegex(ValueError, 'credential'):
                    export.export(run, root/'secret.tar.gz')
                (run/'private.json').unlink()
                (run/'v1.tar').write_bytes(b'image')
                with self.assertRaisesRegex(ValueError, 'private/binary'):
                    export.export(run, root/'image.tar.gz')

    def test_secret_inside_zip_rejected(self):
        import zipfile
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('raw.log', 'Bearer ' + 'x'*30)
        with self.assertRaisesRegex(ValueError, 'secret'):
            export.check_payload('logs.zip', stream.getvalue())

    def test_export_cannot_write_inside_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, 'outside'):
                export.export(temporary, Path(temporary)/'bundle.tar.gz')


if __name__ == '__main__':
    unittest.main()
