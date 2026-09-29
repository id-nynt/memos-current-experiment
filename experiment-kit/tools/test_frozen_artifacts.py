"""Offline cross-store migration tests. No Docker daemon or live execution."""
import copy
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import frozen_artifacts as f
import server_execution as server


def bundle(directory, label='source', architecture='amd64', corrupt_layer=False, duplicate=False, release_label='v1'):
    blobs = {}
    def blob(data, media):
        digest = 'sha256:' + hashlib.sha256(data).hexdigest()
        blobs['blobs/sha256/' + digest.split(':')[1]] = data
        return dict(digest=digest, size=len(data), mediaType=media)
    def document(value, media):
        return blob(json.dumps(value).encode(), media)
    plain = b'fixed layer bytes'
    layer = blob(gzip.compress(plain, mtime=0), 'application/vnd.oci.image.layer.v1.tar+gzip')
    config = document(dict(os='linux', architecture=architecture,
        config={'Labels': {'experiment.release_sha': label, 'experiment.release': release_label}},
        rootfs={'type': 'layers', 'diff_ids': ['sha256:' + hashlib.sha256(plain).hexdigest()]}), f.CONFIG)
    manifest = document(dict(schemaVersion=2, mediaType=f.MANIFEST, config=config, layers=[layer]), f.MANIFEST)
    manifest['platform'] = dict(os='linux', architecture=architecture)
    index = document(dict(schemaVersion=2, mediaType=f.INDEX, manifests=[manifest]), f.INDEX)
    blobs['index.json'] = json.dumps(dict(schemaVersion=2, manifests=[index])).encode()
    blobs['oci-layout'] = b'{"imageLayoutVersion":"1.0.0"}'
    if corrupt_layer:
        blobs['blobs/sha256/' + layer['digest'].split(':')[1]] = b'corrupted'
    path = directory / 'v1.tar'
    with tarfile.open(path, 'w') as archive:
        for name, data in blobs.items():
            entry = tarfile.TarInfo(name); entry.size = len(data)
            archive.addfile(entry, io.BytesIO(data))
        if duplicate:
            entry = tarfile.TarInfo('index.json'); entry.size = len(blobs['index.json'])
            archive.addfile(entry, io.BytesIO(blobs['index.json']))
    release = dict(image_id=index['digest'], application_sha='source', tree='tree', version='v1', tag='tag')
    (directory / 'images.json').write_text(json.dumps({'v1': dict(sha256=f.sha(path), **release)}))
    return dict(releases={'v1': release}), config['digest']


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.frozen, self.config_id = bundle(self.root)

    def test_index_and_config_are_distinct_verified_identities(self):
        value = f.verify_bundle(self.root, self.frozen)['v1']
        self.assertEqual(value['config_digest'], self.config_id)
        self.assertEqual(value['frozen_index_digest'], self.frozen['releases']['v1']['image_id'])
        self.assertNotEqual(value['config_digest'], value['frozen_index_digest'])

    def test_wrong_frozen_root_rejected_even_with_matching_archive_checksum(self):
        changed = copy.deepcopy(self.frozen)
        changed['releases']['v1']['image_id'] = 'sha256:' + '0'*64
        manifest = json.loads((self.root/'images.json').read_text())
        manifest['v1']['image_id'] = changed['releases']['v1']['image_id']
        (self.root/'images.json').write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'root differs'):
            f.verify_bundle(self.root, changed)

    def test_config_id_cannot_replace_index_id(self):
        release = dict(self.frozen['releases']['v1'], image_id=self.config_id)
        with self.assertRaisesRegex(ValueError, 'root differs'):
            f.verify_archive(self.root/'v1.tar', release)

    def test_checksum_tampering_rejected(self):
        with (self.root/'v1.tar').open('ab') as stream: stream.write(b'tampering')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            f.verify_bundle(self.root, self.frozen)

    def test_blob_tampering_rejected_even_with_updated_archive_checksum(self):
        frozen, _ = bundle(self.root, corrupt_layer=True)
        with self.assertRaisesRegex(ValueError, 'digest/size'):
            f.verify_bundle(self.root, frozen)

    def test_wrong_application_label_rejected(self):
        frozen, _ = bundle(self.root, label='other')
        with self.assertRaisesRegex(ValueError, 'source label'):
            f.verify_bundle(self.root, frozen)

    def test_wrong_release_label_rejected(self):
        frozen, _ = bundle(self.root, release_label='v2')
        with self.assertRaisesRegex(ValueError, 'source label'):
            f.verify_bundle(self.root, frozen)

    def test_wrong_platform_rejected(self):
        frozen, _ = bundle(self.root, architecture='arm64')
        with self.assertRaisesRegex(ValueError, 'linux/amd64'):
            f.verify_bundle(self.root, frozen)

    def test_duplicate_member_rejected(self):
        frozen, _ = bundle(self.root, duplicate=True)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            f.verify_bundle(self.root, frozen)

    def test_other_release_metadata_checked(self):
        self.frozen['releases']['v1']['tree'] = 'other'
        with self.assertRaisesRegex(ValueError, 'metadata'):
            f.verify_bundle(self.root, self.frozen)

    def test_both_stores_supported(self):
        for status in ([], [['driver-type','io.containerd.snapshotter.v1']]):
            f.require_linux_store(dict(OSType='linux', Architecture='x86_64', DriverStatus=status))
        with self.assertRaises(ValueError):
            f.require_linux_store(dict(OSType='linux', Architecture='arm64'))

    def test_verify_never_calls_docker(self):
        with patch.object(server.batch, 'read', return_value=self.frozen), patch.object(server.subprocess, 'call') as call, patch.object(server.subprocess, 'check_output') as output:
            self.assertEqual(server.artifacts('verify', self.root), 0)
            call.assert_not_called(); output.assert_not_called()

    def test_import_classic_uses_existing_native_importer(self):
        info = dict(OSType='linux', Architecture='amd64', DriverStatus=[])
        with patch.object(server.batch, 'read', return_value=self.frozen), patch.object(server.subprocess, 'call', return_value=0) as call, patch.object(server.subprocess, 'check_output', return_value=json.dumps(info)):
            self.assertEqual(server.artifacts('import', self.root), 0)
            call.assert_called_once()

    def test_import_does_not_require_images_before_native_load(self):
        info = dict(OSType='linux', Architecture='amd64', DriverStatus=[['driver-type', 'io.containerd.snapshotter.v1']])
        with patch.object(server.batch, 'read', return_value=self.frozen), patch.object(server.subprocess, 'call', return_value=0) as call, patch.object(server.subprocess, 'check_output', return_value=json.dumps(info)) as output:
            self.assertEqual(server.artifacts('import', self.root), 0)
            output.assert_called_once_with(['docker', 'info', '--format', '{{json .}}'], text=True)
            self.assertEqual(call.call_args.args[0][-3:], ['images', 'import', str(self.root.resolve())])


if __name__ == '__main__':
    unittest.main()
