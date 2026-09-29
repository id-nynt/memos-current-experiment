"""Offline verification of classic/containerd identities and shared treatment rules."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import image_identity as identity
import frozen_artifacts
import phase5_metrics

ROOT = Path(__file__).resolve().parents[1]
RELEASES = json.loads((ROOT/'protocol/frozen-releases.json').read_text())['releases']


def metadata(release, classic=True):
    row, config = identity.proof(release)
    return dict(Id=row['config_digest'] if classic else release['image_id'], Os='linux', Architecture='amd64',
                Config=config['config'], RootFS={'Type':'layers','Layers':config['rootfs']['diff_ids']})


def historical_rollback(source):
    new = """    frozen = json.loads((ROOT / 'frozen-releases.json').read_text())['releases']['v1']
    if not (images_identity.matches(frozen, saved_image['image_id']) and images_identity.matches(frozen, known['image_id'])):"""
    old = "    if saved_image['image_id'] != known['image_id']:"
    return source.replace(new, old)


class PortableIdentityTests(unittest.TestCase):
    def test_both_models_preserve_same_canonical_artifact(self):
        for release in RELEASES.values():
            for classic in (False, True):
                image=metadata(release,classic)
                def inspect(ref):
                    if ref != image['Id']: raise subprocess.CalledProcessError(1, 'inspect')
                    return image
                actual=identity.resolve(release,inspect)
                self.assertEqual(actual['frozen_oci_digest'],release['image_id'])
                self.assertEqual(actual['runtime_image_id'],image['Id'])

    def test_expected_real_mapping(self):
        self.assertEqual(identity.proof(RELEASES['v1'])[0]['config_digest'],
                         'sha256:e3ef9fef43919ceb308c941146cabbf399d3856bc3e5a9eb131dfa8fb72460c1')
        self.assertEqual(identity.proof(RELEASES['v2'])[0]['config_digest'],
                         'sha256:63533b70ed9390081afd85ee38cc9dbe7a7aad8ecce0e440f7b3b581de7cd73d')

    def test_wrong_loaded_image_platform_labels_or_layers_rejected(self):
        release=RELEASES['v1']
        mutations=[('Id','sha256:'+'f'*64),('Os','windows'),('Architecture','arm64')]
        for key,value in mutations:
            image=metadata(release);image[key]=value
            with self.assertRaises(ValueError):identity.verify_image(release,image)
        for label in ('experiment.release_sha','experiment.release'):
            image=metadata(release);image['Config']['Labels'][label]='wrong'
            with self.assertRaises(ValueError):identity.verify_image(release,image)
        image=metadata(release);image['RootFS']['Layers'].reverse()
        with self.assertRaises(ValueError):identity.verify_image(release,image)

    def test_v1_v2_swapped_rejected(self):
        for classic in (False,True):
            with self.assertRaises(ValueError):identity.verify_image(RELEASES['v1'],metadata(RELEASES['v2'],classic))
            self.assertFalse(identity.matches(RELEASES['v1'],metadata(RELEASES['v2'],classic)['Id']))

    def test_valid_id_with_bad_metadata_does_not_fall_back(self):
        image=metadata(RELEASES['v1'],False);image['Architecture']='arm64'
        with self.assertRaises(ValueError):identity.resolve(RELEASES['v1'],lambda _:image)

    def test_proof_tampering_cannot_bless_arbitrary_config(self):
        source=json.loads((ROOT/'protocol/frozen-runtime-identities.json').read_text())
        for field in ('config_digest','config_json','index_json','platform_manifest_digest','release'):
            changed=copy.deepcopy(source);changed['releases']['v1'][field]='wrong'
            with tempfile.TemporaryDirectory() as temp:
                Path(temp,'frozen-runtime-identities.json').write_text(json.dumps(changed))
                with patch.object(identity,'__file__',str(Path(temp,'image_identity.py'))):
                    with self.assertRaises((ValueError,KeyError)):identity.proof(RELEASES['v1'])

    def test_alternate_identity_needs_proof_for_matching_application(self):
        changed=dict(RELEASES['v1'],application_sha=RELEASES['v2']['application_sha'])
        self.assertFalse(identity.matches(changed,metadata(RELEASES['v1'])['Id']))

    def test_both_treatments_ship_identical_rules_and_proof(self):
        for folder in ('memos-current/scripts/experiment-measurement','memos-bdi/experiment/scripts','memos-bdi/experiment/measurement'):
            for name in ('image_identity.py','frozen-runtime-identities.json'):
                self.assertEqual((ROOT/folder/name).read_bytes(),(ROOT/'tools'/name).read_bytes())
        self.assertEqual((ROOT/'protocol/frozen-runtime-identities.json').read_bytes(),
                         (ROOT/'tools/frozen-runtime-identities.json').read_bytes())

    def test_measurement_classifies_same_release_on_both_stores(self):
        for name,release in RELEASES.items():
            states=[]
            for classic in (False,True):
                row=dict(healthy=True,application_sha=release['application_sha'],image_id=metadata(release,classic)['Id'])
                states.append(phase5_metrics.service_state(row,RELEASES))
            self.assertEqual(states[0],states[1])

    def test_missing_images_fail_closed(self):
        def absent(_):raise subprocess.CalledProcessError(1,'inspect')
        with self.assertRaisesRegex(ValueError,'absent'):identity.resolve(RELEASES['v1'],absent)

    def test_bdi_logged_inspect_failure_uses_verified_classic_id(self):
        release=RELEASES['v1']
        def inspect(ref):
            if ref==release['image_id']:raise RuntimeError('frozen-image failed; see preserved command logs')
            return metadata(release)
        self.assertEqual(identity.resolve(release,inspect)['runtime_image_id'],metadata(release)['Id'])

    def test_archive_verifier_copies_are_identical(self):
        for folder in ('memos-current/scripts/experiment-measurement','memos-bdi/experiment/scripts'):
            self.assertEqual((ROOT/folder/'frozen_artifacts.py').read_bytes(),(ROOT/'tools/frozen_artifacts.py').read_bytes())

    def test_native_bdi_build_receipt_records_both_store_models(self):
        from test_phase5_instrumentation import module
        ops=module('portable_operate',ROOT/'memos-bdi/experiment/scripts/operate.py')
        release=RELEASES['v1']
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp);(path/'scripts').mkdir();(path/'scripts/entrypoint.sh').write_text('#!/bin/sh\n',newline='\n')
            args=SimpleNamespace(app=str(path),release='v1',release_sha=release['application_sha'],
                evidence=path,state=path,approach='bdi',control_sha='control')
            for classic in (False,True):
                saved={};image=metadata(release,classic)
                def command(argv,*a,**kw):
                    if argv[-1]!=image['Id']:raise RuntimeError('frozen-image failed')
                    return json.dumps([image])
                with patch.object(ops.subprocess,'check_output',side_effect=[release['application_sha'].encode(),b'',release['tree']]), \
                     patch.object(ops,'command',side_effect=command), \
                     patch.object(ops,'save',side_effect=lambda p,v:saved.update({p.name:v})):
                    ops.build(args)
                receipt=saved['build-receipt.json']
                self.assertEqual(receipt['frozen_oci_digest'],release['image_id'])
                self.assertEqual(receipt['runtime_image_id'],image['Id'])
                self.assertEqual(receipt['image_id'],image['Id'])


if __name__ == '__main__':unittest.main()
