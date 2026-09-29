"""Build the unchanged application pair once; stage a new, verifiable image freeze.

Never publishes Git, edits selected controls, or starts an experimental candidate.
"""
import argparse
import copy
import hashlib
import io
import json
import os
import platform
from pathlib import Path
import subprocess
import tarfile
import tempfile
import time
import urllib.request
import uuid

import frozen_artifacts as artifacts

ROOT = Path(__file__).resolve().parents[1]


def frozen_upgrade_workflow(text):
    """Wire the existing smoke script's prebuilt-image interface in either control."""
    marker = '      - name: Resolve retained experiment candidate'
    if marker in text:
        return text
    if '      previous_image:' not in text:
        anchor = '        default: ""\n'
        if text.count(anchor) != 1:
            raise ValueError('Unrecognized upgrade workflow inputs')
        text = text.replace(anchor, anchor + '      previous_image:\n        type: string\n        required: false\n        default: ""\n', 1)
    anchor = '      - name: Run release smoke test\n'
    if text.count(anchor) != 1:
        raise ValueError('Unrecognized release smoke step')
    step = '''      - name: Checkout selected control for frozen identities
        if: inputs.release_sha != ''
        uses: actions/checkout@v6
        with:
          ref: ${{ github.sha }}
          path: experiment-control
          persist-credentials: false

      - name: Resolve retained experiment candidate
        if: inputs.release_sha != ''
        id: frozen
        env:
          RELEASE_SHA: ${{ inputs.release_sha }}
        run: |
          python3 - <<'PY'
          import json, os, sys
          from pathlib import Path
          root = Path('experiment-control')
          conventional = (root/'scripts/local-cd/frozen-releases.json').exists()
          manifest = root/('scripts/local-cd/frozen-releases.json' if conventional else 'experiment/frozen-releases.json')
          sys.path.insert(0, str(root/('scripts/experiment-measurement' if conventional else 'experiment/scripts')))
          import image_identity
          releases = json.loads(manifest.read_text())['releases']
          matches = [r for r in releases.values() if r['application_sha'] == os.environ['RELEASE_SHA']]
          if len(matches) != 1:
              raise ValueError('Smoke source is not the frozen application pair')
          identity = image_identity.resolve(matches[0])
          with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
              output.write('image=' + identity['runtime_image_id'] + '\\n')
          print(json.dumps(identity))
          PY

'''
    text = text.replace(anchor, step + anchor)
    old = anchor + '        env:\n          MEMOS_SMOKE_PREVIOUS_IMAGE: ${{ inputs.previous_image }}\n'
    if old in text:
        text = text.replace(old, old + '          MEMOS_SMOKE_CANDIDATE_IMAGE: ${{ steps.frozen.outputs.image }}\n')
    elif anchor + '        run: ./scripts/release_smoke_test.sh' in text:
        text = text.replace(anchor, anchor + '        env:\n          MEMOS_SMOKE_PREVIOUS_IMAGE: ${{ inputs.previous_image }}\n          MEMOS_SMOKE_CANDIDATE_IMAGE: ${{ steps.frozen.outputs.image }}\n')
    else:
        raise ValueError('Unrecognized smoke environment; preserve and inspect workflow')
    return text


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def canonical_archive(source, destination):
    """Wrap BuildKit's platform index so the retained archive has a frozen root."""
    with tarfile.open(source) as src:
        raw = src.extractfile('index.json').read()
        index = json.loads(raw)
        # BuildKit exporters may already wrap their image index.
        if len(index['manifests']) == 1 and index['manifests'][0]['mediaType'] == artifacts.INDEX:
            descriptor = index['manifests'][0]
            wrapped = True
        else:
            descriptor = dict(mediaType=artifacts.INDEX, size=len(raw),
                              digest='sha256:' + hashlib.sha256(raw).hexdigest())
            wrapped = False
        with tarfile.open(destination, 'x') as dst:
            for entry in src:
                if entry.name == 'index.json' and not wrapped:
                    continue
                dst.addfile(entry, src.extractfile(entry) if entry.isfile() else None)
            if not wrapped:
                for name, data in [('blobs/sha256/' + descriptor['digest'].split(':')[1], raw),
                                   ('index.json', json.dumps(dict(schemaVersion=2, mediaType=artifacts.INDEX,
                                                                 manifests=[descriptor])).encode())]:
                    entry = tarfile.TarInfo(name); entry.size = len(data)
                    dst.addfile(entry, io.BytesIO(data))
    return descriptor['digest']


def identity_proof(path, release, label):
    verified = artifacts.verify_archive(path, release, label)
    with tarfile.open(path) as archive:
        def blob(digest):
            return archive.extractfile('blobs/sha256/' + digest.split(':')[1]).read().decode()
        return dict(release=label, frozen_oci_digest=release['image_id'],
                    application_sha=release['application_sha'], archive_sha256=artifacts.sha(path),
                    platform_manifest_digest=verified['manifest_digest'], config_digest=verified['config_digest'],
                    index_json=blob(release['image_id']), manifest_json=blob(verified['manifest_digest']),
                    config_json=blob(verified['config_digest']))


def health(image, release, log):
    name = 'memos-image-check-' + uuid.uuid4().hex[:12]
    command = ['docker', 'run', '-d', '--name', name, '-p', '127.0.0.1::5230', image]
    subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT)
    try:
        obj = json.loads(subprocess.check_output(['docker', 'inspect', name]))[0]
        port = obj['NetworkSettings']['Ports']['5230/tcp'][0]['HostPort']
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen('http://127.0.0.1:' + port + '/api/v1/instance/profile', timeout=5) as response:
                    profile = json.load(response)
                if profile.get('commit') != release['application_sha']:
                    raise ValueError('Built application reports wrong source commit')
                return dict(healthy=True, application_sha=profile['commit'], image_id=image)
            except (OSError, TimeoutError):
                time.sleep(2)
        raise ValueError('Built image did not become healthy within 180 seconds')
    finally:
        subprocess.run(['docker', 'logs', name], stdout=log, stderr=subprocess.STDOUT)
        subprocess.run(['docker', 'rm', '-f', '-v', name], check=True, stdout=log, stderr=subprocess.STDOUT)


def prepare(directory, publication_required=True):
    directory = Path(directory).resolve()
    if platform.system() != 'Linux':
        raise ValueError('Build preparation must run on Linux')
    original = read(ROOT/'protocol/frozen-releases.json')
    if (directory/'COMPLETE.json').exists():
        frozen = read(directory/'frozen-releases.json')
        for label in ('v1', 'v2'):
            for key in ('application_sha', 'tree', 'version'):
                if frozen['releases'][label][key] != original['releases'][label][key]:
                    raise ValueError('Preparation belongs to a different source pair')
        artifacts.verify_bundle(directory, frozen)
        print('PREPARED: existing frozen bundle verified; no rebuild:', directory)
        return
    if directory.exists():
        raise ValueError('Incomplete preparation retained. Inspect logs and use a new directory; never overwrite it.')
    info = json.loads(subprocess.check_output(['docker', 'info', '--format', '{{json .}}']))
    artifacts.require_linux_store(info)
    for label, release in original['releases'].items():
        for repo in ('memos-current', 'memos-bdi'):
            tree = subprocess.check_output(['git', '-C', str(ROOT/repo), 'rev-parse', release['application_sha']+'^{tree}'], text=True).strip()
            if tree != release['tree']:
                raise ValueError(repo + ': frozen source tree mismatch')
    directory.mkdir(parents=True)
    save(directory/'previous-frozen-releases.json', original)
    frozen = copy.deepcopy(original)
    proofs = dict(schema_version=1, derivation='Fresh Linux build; verified OCI content and health before publication', releases={})
    receipts = {}
    builder = 'memos-freeze-' + uuid.uuid4().hex[:12]
    with (directory/'build.log').open('w') as log:
        subprocess.run(['docker', 'pull', 'node:24-bookworm'], check=True, stdout=log, stderr=subprocess.STDOUT)
        frontend_image = json.loads(subprocess.check_output(['docker', 'image', 'inspect', 'node:24-bookworm']))[0]['Id']
        save(directory/'build-tools.json', dict(frontend_image=frontend_image, pnpm='11.0.1', platform='linux/amd64'))
        subprocess.run(['docker', 'buildx', 'create', '--name', builder, '--driver', 'docker-container'], check=True, stdout=log, stderr=subprocess.STDOUT)
        try:
            for label, release in frozen['releases'].items():
                with tempfile.TemporaryDirectory(prefix='memos-freeze-') as temporary:
                    work = Path(temporary); source = work/'source'; source.mkdir()
                    subprocess.run(['git', '-C', str(ROOT/'memos-current'), 'archive', '-o', str(work/'source.tar'), release['application_sha']], check=True)
                    with tarfile.open(work/'source.tar') as archive:
                        archive.extractall(source, filter='data')
                    subprocess.run(['docker', 'run', '--rm', '--user', str(os.getuid())+':'+str(os.getgid()),
                        '-e', 'HOME=/tmp', '-v', str(source)+':/src', '-w', '/src/web', frontend_image,
                        'sh', '-ec', 'npm install --prefix /tmp/pnpm pnpm@11.0.1 && /tmp/pnpm/node_modules/.bin/pnpm install --frozen-lockfile && /tmp/pnpm/node_modules/.bin/pnpm release'],
                        check=True, stdout=log, stderr=subprocess.STDOUT)
                    release['tag'] = 'memos-linux-frozen:' + label + '-' + builder.removeprefix('memos-freeze-')
                    subprocess.run(['docker', 'buildx', 'build', '--builder', builder, '--platform', 'linux/amd64',
                        '--provenance=false', '--output', 'type=oci,compression=gzip,dest='+str(work/'image.tar'),
                        '-f', 'scripts/Dockerfile', '--build-arg', 'VERSION='+release['version'],
                        '--build-arg', 'COMMIT='+release['application_sha'], '--label', 'experiment.release='+label,
                        '--label', 'experiment.release_sha='+release['application_sha'], '-t', release['tag'], '.'],
                        cwd=source, check=True, stdout=log, stderr=subprocess.STDOUT)
                    release['image_id'] = canonical_archive(work/'image.tar', directory/(label+'.tar'))
                proof = identity_proof(directory/(label+'.tar'), release, label)
                proofs['releases'][label] = proof
                subprocess.run(['docker', 'load', '-i', str(directory/(label+'.tar'))], check=True, stdout=log, stderr=subprocess.STDOUT)
                runtime = proof['config_digest']
                # Some containerd stores expose the root index ID instead of config ID.
                inspected = subprocess.run(['docker', 'image', 'inspect', runtime], capture_output=True)
                if inspected.returncode:
                    runtime = release['image_id']
                subprocess.run(['docker', 'tag', runtime, release['tag']], check=True, stdout=log, stderr=subprocess.STDOUT)
                receipts[label] = health(runtime, release, log)
        finally:
            subprocess.run(['docker', 'buildx', 'rm', builder], stdout=log, stderr=subprocess.STDOUT)
    save(directory/'frozen-releases.json', frozen)
    save(directory/'frozen-runtime-identities.json', proofs)
    save(directory/'images.json', {k: dict(v, sha256=proofs['releases'][k]['archive_sha256']) for k,v in frozen['releases'].items()})
    artifacts.verify_bundle(directory, frozen)
    save(directory/'COMPLETE.json', dict(health=receipts, publication_required=publication_required))
    print('PREPARED: build/health/archive verification passed.' + (' Publish this new freeze before execution:' if publication_required else ' Activate the shared server image session:'), directory)


def stage(directory):
    directory = Path(directory)
    if not (directory/'COMPLETE.json').is_file():
        raise ValueError('Preparation did not complete')
    frozen = read(directory/'frozen-releases.json')
    artifacts.verify_bundle(directory, frozen)
    proofs = read(directory/'frozen-runtime-identities.json')
    for label, release in frozen['releases'].items():
        if proofs['releases'][label] != identity_proof(directory/(label+'.tar'), release, label):
            raise ValueError('Staged runtime proof differs from verified archive')
    old = read(ROOT/'protocol/frozen-releases.json')
    if old not in (read(directory/'previous-frozen-releases.json'), frozen):
        raise ValueError('Selected freeze changed since preparation')
    for lock in (ROOT/'results/operator-state/batch.lock', ROOT/'results/operator-state/bdi.lock', ROOT/'results/operator-state/conventional.lock'):
        if lock.exists():
            raise ValueError('Active/unresolved operator: ' + str(lock))
    state = Path.home()/'memos-bdi-state'
    for name in ('active-campaign.json', 'bdi-campaign.lock', 'bdi-operation.lock'):
        if (state/name).exists():
            raise ValueError('Active/unresolved BDI state: ' + str(state/name))
    destinations = ['protocol/frozen-releases.json', 'memos-current/scripts/local-cd/frozen-releases.json', 'memos-bdi/experiment/frozen-releases.json']
    workflows = {ROOT/repo/'.github/workflows/experiment-upgrade-smoke.yml': None for repo in ('memos-current','memos-bdi')}
    for path in workflows:
        workflows[path] = frozen_upgrade_workflow(path.read_text(encoding='utf-8'))
    for name in destinations:
        if read(ROOT/name) not in (old, frozen):
            raise ValueError('Preserve independently changed native freeze: ' + name)
    for name in destinations:
        (ROOT/name).write_bytes((directory/'frozen-releases.json').read_bytes())
    for folder in ('protocol', 'tools', 'memos-current/scripts/experiment-measurement', 'memos-bdi/experiment/scripts', 'memos-bdi/experiment/measurement'):
        (ROOT/folder/'frozen-runtime-identities.json').write_bytes((directory/'frozen-runtime-identities.json').read_bytes())
    for path, text in workflows.items():
        path.write_text(text, encoding='utf-8', newline='\n')
    print('Freeze staged consistently. Commit/publish NEW immutable controls and update operator-revisions.json before setup/trials.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'stage-freeze'])
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    (prepare if args.action == 'prepare' else stage)(args.directory)


if __name__ == '__main__':
    main()
