"""Validate and bundle one idle result directory; never sweep private state/images."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import tarfile
import zipfile

import batch_runner as batch
import phase8_matrix as matrix
from server_execution import inspect_results

SECRET = re.compile(rb'(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----|Bearer\s+(?!\*\*\*)[A-Za-z0-9_.-]{20,}|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)')
PRIVATE = {'credential.json', 'credentials.json', '.env', 'data.tar.gz', 'v1.tar', 'v2.tar', 'source.tar'}


def check_payload(name, data):
    parts = name.replace('\\', '/').lower().split('/')
    if parts[-1] in PRIVATE or 'credentials' in parts or parts[-1].endswith(('.tar', '.gz', '.tgz', '.db', '.sqlite', '.sqlite3')):
        raise ValueError('Private/archive payload in ' + name)
    if SECRET.search(data):
        raise ValueError('Potential secret in ' + name + '; no bundle created')
    if name.endswith('.zip'):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for info in archive.infolist():
                if info.file_size > 100 * 1024**2:
                    raise ValueError('Oversized archive member: ' + name)
                check_payload(name + '/' + info.filename, archive.read(info))
    elif name.endswith('.json'):
        try:
            value = json.loads(data)
        except (ValueError, UnicodeError):
            return
        def walk(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key.lower() in ('password', 'token', 'access_token', 'refresh_token', 'pat', 'client_secret', 'private_key') and item and item != '***':
                        raise ValueError('Private credential value in ' + name)
                    walk(item)
            elif isinstance(value, list):
                for item in value: walk(item)
        walk(value)


def export(directory, destination, allow_incomplete=False):
    directory, destination = Path(directory).resolve(), Path(destination).resolve()
    if directory == destination or directory in destination.parents:
        raise ValueError('Write the bundle outside the selected results directory')
    if destination.exists() or Path(str(destination)+'.sha256').exists():
        raise ValueError('Bundle/checksum already exists; choose a new output name')
    if not (directory/'batch.json').is_file():
        raise ValueError('Select one run-case/run-set directory containing batch.json')
    if (directory/'active.lock').exists() or (batch.ROOT/'results/operator-state/batch.lock').exists():
        raise ValueError('Active/unresolved batch; reconcile before export')
    report = inspect_results(directory, batch.read(matrix.MANIFEST), derive=True)
    if not report['all_selected_valid'] and not allow_incomplete:
        raise ValueError('Results not all valid; --allow-incomplete explicitly preserves an incomplete/invalid run')
    files = {}
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            raise ValueError('Symlink in results: ' + str(path))
        if not path.is_file():
            continue
        name = path.relative_to(directory).as_posix()
        if path.name.lower() in PRIVATE or any(part.lower() in ('credentials', '.git', 'node_modules', '__pycache__') for part in path.relative_to(directory).parts) or path.suffix.lower() in ('.tar', '.gz', '.tgz', '.db', '.sqlite', '.sqlite3', '.pyc', '.tmp'):
            raise ValueError('Unexpected private/binary/temporary file in selected results: ' + name)
        data = path.read_bytes()
        check_payload(name, data)
        files[name] = hashlib.sha256(data).hexdigest()
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation: failed exports never overwrite an earlier bundle.
    with destination.open('xb') as stream:
        try:
            with tarfile.open(fileobj=stream, mode='w:gz') as archive:
                for name, digest in files.items():
                    path = directory/name
                    data = path.read_bytes()
                    if hashlib.sha256(data).hexdigest() != digest:
                        raise ValueError('Evidence changed during export: ' + name)
                    info = tarfile.TarInfo('results/' + name); info.size = len(data); info.mode = 0o600
                    archive.addfile(info, io.BytesIO(data))
                payload = json.dumps(dict(validation=report, files=files, original_directory=str(directory)), indent=2).encode()
                info = tarfile.TarInfo('bundle-manifest.json'); info.size=len(payload); info.mode=0o600
                archive.addfile(info, io.BytesIO(payload))
            if batch.hashes(directory) != files:
                raise ValueError('Evidence changed during export')
        except BaseException:
            stream.close(); destination.unlink(); raise
    checksum = batch.digest(destination)
    with destination.with_name(destination.name+'.sha256').open('x') as stream:
        stream.write(checksum + '  ' + destination.name + '\n')
    print('EXPORTED:', destination)
    print('SHA256:', checksum)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--verify', type=Path, help='Verify a downloaded bundle and its adjacent .sha256 file')
    parser.add_argument('--allow-incomplete', action='store_true')
    args = parser.parse_args()
    if args.verify:
        verify(args.verify)
        return
    if not args.directory or not args.output:
        parser.error('--directory and --output are required for export')
    export(args.directory, args.output, args.allow_incomplete)


def verify(path):
    path = Path(path)
    expected = Path(str(path)+'.sha256').read_text().split()[0]
    if batch.digest(path) != expected:
        raise ValueError('Bundle checksum mismatch')
    with tarfile.open(path) as archive:
        manifest = json.load(archive.extractfile('bundle-manifest.json'))
        seen = set()
        for member in archive:
            if member.name in seen or not member.isfile():
                raise ValueError('Duplicate or non-file bundle member')
            seen.add(member.name)
            if member.name == 'bundle-manifest.json': continue
            name = member.name.removeprefix('results/')
            if not member.name.startswith('results/') or name not in manifest['files'] or '..' in Path(name).parts or '\\' in name:
                raise ValueError('Unexpected bundle member')
            if hashlib.sha256(archive.extractfile(member).read()).hexdigest() != manifest['files'][name]:
                raise ValueError('Bundle evidence hash mismatch')
        if seen != {'bundle-manifest.json'} | {'results/'+name for name in manifest['files']}:
            raise ValueError('Incomplete result bundle')
    print('VERIFIED: bundle checksum and all evidence files match; server validation retained.')
    return manifest


if __name__ == '__main__':
    main()
