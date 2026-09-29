"""Verify frozen OCI archives without extracting, rebuilding or changing identity."""
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tarfile

INDEX = 'application/vnd.oci.image.index.v1+json'
MANIFEST = 'application/vnd.oci.image.manifest.v1+json'
CONFIG = 'application/vnd.oci.image.config.v1+json'


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_archive(path, release, release_name=None):
    """Bind index -> platform manifest -> config/layers to the frozen digest."""
    with tarfile.open(path) as archive:
        members = {}
        for entry in archive:
            name = PurePosixPath(entry.name)
            if (name.is_absolute() or '..' in name.parts or entry.name in members
                    or not (entry.isfile() or entry.isdir())):
                raise ValueError('Unsafe/duplicate archive member: ' + entry.name)
            members[entry.name] = entry

        def raw(name):
            entry = members.get(name)
            if entry is None or not entry.isfile():
                raise ValueError('Missing archive blob: ' + name)
            return archive.extractfile(entry).read()

        def blob(descriptor):
            digest = descriptor['digest']
            if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
                raise ValueError('Unsupported blob digest')
            data = raw('blobs/sha256/' + digest.split(':')[1])
            if len(data) != descriptor['size'] or 'sha256:' + hashlib.sha256(data).hexdigest() != digest:
                raise ValueError('Blob digest/size mismatch: ' + digest)
            return data

        layout = json.loads(raw('oci-layout'))
        if layout.get('imageLayoutVersion') != '1.0.0':
            raise ValueError('Unsupported OCI layout')
        top = json.loads(raw('index.json'))
        roots = top.get('manifests', [])
        if len(roots) != 1 or roots[0].get('digest') != release['image_id']:
            raise ValueError('Archive root differs from frozen index identity')
        if roots[0].get('mediaType') != INDEX:
            raise ValueError('Expected retained OCI index; do not convert/refreeze it')
        candidates = []

        def visit(descriptor, depth=0):
            if depth > 8:
                raise ValueError('OCI descriptor nesting too deep')
            obj = json.loads(blob(descriptor))
            kind = descriptor['mediaType']
            if obj.get('schemaVersion') != 2 or obj.get('mediaType') != kind:
                raise ValueError('OCI descriptor type mismatch')
            if kind == INDEX:
                for child in obj['manifests']:
                    visit(child, depth + 1)
            elif kind == MANIFEST:
                config = json.loads(blob(obj['config']))
                layers = [blob(layer) for layer in obj['layers']]
                platform = descriptor.get('platform', {})
                if platform.get('os') == 'linux' and platform.get('architecture') == 'amd64':
                    if (obj['config']['mediaType'] != CONFIG or config.get('os') != 'linux'
                            or config.get('architecture') != 'amd64'
                            or config.get('config', {}).get('Labels', {}).get('experiment.release_sha') != release['application_sha']
                            or (release_name is not None and config.get('config', {}).get('Labels', {}).get('experiment.release') != release_name)):
                        raise ValueError('Frozen platform/source label mismatch')
                    diffs = []
                    for layer, data in zip(obj['layers'], layers):
                        media = layer['mediaType']
                        if media == 'application/vnd.oci.image.layer.v1.tar+gzip':
                            data = gzip.decompress(data)
                        elif media != 'application/vnd.oci.image.layer.v1.tar':
                            raise ValueError('Unsupported frozen layer encoding')
                        diffs.append('sha256:' + hashlib.sha256(data).hexdigest())
                    if config.get('rootfs') != {'type': 'layers', 'diff_ids': diffs}:
                        raise ValueError('Config rootfs/layer mismatch')
                    candidates.append(dict(platform='linux/amd64', manifest_digest=descriptor['digest'],
                                           config_digest=obj['config']['digest'], diff_ids=diffs))
            else:
                raise ValueError('Unsupported OCI descriptor type: ' + kind)

        visit(roots[0])
        if len(candidates) != 1:
            raise ValueError('Exactly one frozen linux/amd64 platform is required')
        return dict(frozen_index_digest=release['image_id'], application_sha=release['application_sha'],
                    **candidates[0])


def verify_bundle(directory, frozen):
    directory = Path(directory)
    exported = json.loads((directory / 'images.json').read_text(encoding='utf-8-sig'))
    if set(exported) != set(frozen['releases']):
        raise ValueError('Frozen archive release set mismatch')
    result = {}
    for name, release in frozen['releases'].items():
        entry = exported[name]
        if any(entry.get(key) != value for key, value in release.items()):
            raise ValueError(name + ': exported release metadata differs from frozen contract')
        path = directory / (name + '.tar')
        digest = sha(path)
        if digest != entry['sha256']:
            raise ValueError(name + ': archive checksum mismatch')
        result[name] = dict(archive_sha256=digest, **verify_archive(path, release, name))
    return result


def require_linux_store(info):
    if info.get('OSType') != 'linux' or info.get('Architecture') not in ('amd64', 'x86_64'):
        raise ValueError('Frozen imports require Linux/amd64 Docker')
