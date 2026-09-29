"""Portable frozen artifact identity. Identical copies ship in both native controls."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def session():
    """One server-local image freeze, shared by operator and both runner services."""
    path=Path.home()/'.memos-experiment-images/session.json'
    if not path.exists():return None
    value=json.loads(path.read_text(encoding='utf-8'))
    body={k:v for k,v in value.items() if k!='sha256'}
    digest=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if value.get('sha256')!=digest:raise ValueError('Server image session changed')
    return value


def frozen_digest(release):
    value=session()
    if value is None:return release['image_id']
    matches=[name for name,row in value['source_releases']['releases'].items()
             if row['application_sha']==release['application_sha'] and release['image_id'] in
             (row['image_id'],value['frozen_releases']['releases'][name]['image_id'])]
    if len(matches)!=1:raise ValueError('Release does not belong to this server image session')
    return value['frozen_releases']['releases'][matches[0]]['image_id']


def proof(release):
    source = Path(__file__).with_name('frozen-runtime-identities.json')
    active=session()
    records = active['proofs']['releases'] if active else json.loads(source.read_text(encoding='utf-8'))['releases']
    selected_digest=frozen_digest(release)
    row = next((r for r in records.values() if r['frozen_oci_digest'] == selected_digest), None)
    if row is None or row['application_sha'] != release['application_sha']:
        raise ValueError('No archive-derived identity proof for frozen release')
    def decode(text, digest):
        if 'sha256:' + hashlib.sha256(text.encode()).hexdigest() != digest:
            raise ValueError('Frozen identity proof digest mismatch')
        return json.loads(text)
    index = decode(row['index_json'], selected_digest)
    selected = [d for d in index['manifests'] if d.get('platform') == {'architecture': 'amd64', 'os': 'linux'}]
    if len(selected) != 1 or selected[0]['digest'] != row['platform_manifest_digest']:
        raise ValueError('Frozen platform manifest mismatch')
    manifest = decode(row['manifest_json'], selected[0]['digest'])
    if manifest['config']['digest'] != row['config_digest']:
        raise ValueError('Config does not belong to frozen index')
    config = decode(row['config_json'], row['config_digest'])
    if (config['os'] != 'linux' or config['architecture'] != 'amd64'
            or config['config']['Labels'].get('experiment.release_sha') != release['application_sha']
            or config['config']['Labels'].get('experiment.release') != row['release']):
        raise ValueError('Frozen platform/application/release label mismatch')
    return row, config


def matches(release, image_id):
    # Historical canonical-only evidence remains readable. Alternate IDs require proof.
    if image_id == frozen_digest(release):
        return True
    try:
        row, _ = proof(release)
        return image_id == row['config_digest']
    except (KeyError, ValueError):
        return False


def evidence(release, image_id):
    if not matches(release, image_id):
        raise ValueError('Runtime image is not the frozen artifact')
    active=session()
    return dict(frozen_oci_digest=frozen_digest(release), runtime_image_id=image_id,
                **({'image_session_sha256':active['sha256']} if active else {}))


def verify_image(release, image):
    row, config = proof(release)
    labels = image.get('Config', {}).get('Labels') or {}
    if (image.get('Id') not in (frozen_digest(release), row['config_digest'])
            or image.get('Os') != 'linux' or image.get('Architecture') != 'amd64'
            or labels.get('experiment.release_sha') != release['application_sha']
            or labels.get('experiment.release') != row['release']
            or image.get('RootFS', {}).get('Layers') != config['rootfs']['diff_ids']):
        raise ValueError('Loaded image identity/platform/labels/layers mismatch')
    return evidence(release, image['Id'])


def resolve(release, inspect=None):
    row, _ = proof(release)
    if inspect is None:
        def inspect(image_id):
            return json.loads(subprocess.check_output(
                ['docker', 'image', 'inspect', image_id], text=True, stderr=subprocess.PIPE))[0]
    for image_id in (frozen_digest(release), row['config_digest']):
        try:
            image = inspect(image_id)
        except (subprocess.CalledProcessError, RuntimeError):
            # Native BDI command logging wraps nonzero exits in RuntimeError.
            # Metadata validation stays outside this handler and never falls back.
            continue
        return verify_image(release, image)
    raise ValueError('Verified frozen image absent; import the retained archive first')


def runtime_id(release, inspect=None):
    return resolve(release, inspect)['runtime_image_id']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--release', choices=['v1', 'v2'], required=True)
    args = parser.parse_args()
    release = json.loads(args.manifest.read_text(encoding='utf-8-sig'))['releases'][args.release]
    print(json.dumps(resolve(release)))
