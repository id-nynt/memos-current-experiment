"""Repository-owned conventional preparation, execution and passive evidence CLI."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'experiment'
sys.path.insert(0, str(ROOT / 'scripts/experiment-measurement'))
from measure_trial import now, read, save, sample, summarize, instant
from fixture import validate

CFG = read(HERE / 'config.json')
RELEASES = read(ROOT / CFG['release_manifest'])['releases']
STATE = Path(os.environ.get('LOCALAPPDATA', Path.home())) / CFG['owner']
RESULTS = HERE / 'results'


def command(*args, **kwargs):
    return subprocess.check_output([str(a) for a in args], cwd=ROOT, text=True,
                                   encoding='utf-8', errors='replace', **kwargs).strip()


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def identity():
    paths = sorted([p for base in (HERE, ROOT / 'scripts/local-cd', ROOT / 'scripts/experiment-measurement')
                    for p in base.rglob('*') if p.is_file() and not any(x in p.parts for x in
                    ('results', '.venv', '__pycache__')) and p.name != 'machine.json'])
    paths.append(ROOT / '.github/workflows/frozen-cd.yml')
    return {'control_sha': command('git', 'rev-parse', 'HEAD'),
            'policy_baseline': CFG['policy_baseline'],
            'files': {p.relative_to(ROOT).as_posix(): digest(p) for p in paths}}


@contextlib.contextmanager
def lock(name='experiment.lock'):
    """Windows byte lock plus deployment's exclusive-open check during reset."""
    import msvcrt
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / name).open('a+b') as stream:
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError('Another conventional experiment operation is active') from exc
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def project(env):
    return CFG['projects'][('staging', 'production').index(env)]


def port(env):
    return CFG[env + '_port']


def compose(env, release, *args):
    variables = dict(os.environ, MEMOS_IMAGE=RELEASES[release]['image_id'],
                     MEMOS_HOST_PORT=str(port(env)), MEMOS_DATA_VOLUME=project(env) + '_data')
    return command('docker', 'compose', '-f', ROOT / 'scripts/local-cd/compose.yaml',
                   '-p', project(env), *args, env=variables)


def measurement(env='production', release='v2', trial='verification', scenario='S0', mode='local'):
    r = RELEASES[release]
    return dict(approach='conventional', scenario=scenario, trial_id=trial,
                control_sha=command('git', 'rev-parse', 'HEAD'), application_sha=r['application_sha'],
                image_identity=r['image_id'], execution_mode=mode, releases=RELEASES,
                production_url=f'http://127.0.0.1:{port(env)}',
                production_container=project(env) + '-memos-1',
                credential_file=str(STATE / 'credentials' / env / 'credential.json'))


def verify(release=None):
    observations = {env: sample(measurement(env)) for env in ('staging', 'production')}
    if not all(s['healthy'] and (not release or s['application_sha'] == RELEASES[release]['application_sha'])
               for s in observations.values()):
        raise RuntimeError('Live verification failed: ' + json.dumps(observations))
    return observations


def preflight():
    if os.name != 'nt':
        raise RuntimeError('This conventional runner requires Windows')
    for name in ('git', 'docker', 'powershell', 'tar', 'gh'):
        if not shutil.which(name):
            raise RuntimeError(f'Missing prerequisite: {name}')
    if command('docker', 'version', '--format', '{{.Server.Os}}/{{.Server.Arch}}') != 'linux/amd64':
        raise RuntimeError('Docker Linux/amd64 is required')
    for name, release in RELEASES.items():
        if command('git', 'rev-parse', release['application_sha'] + '^{tree}') != release['tree']:
            raise RuntimeError(f'{name}: source tree mismatch; fetch the frozen tags')
        image = json.loads(command('docker', 'image', 'inspect', release['image_id']))[0]
        if (image['Id'] != release['image_id'] or image['Os'] != 'linux' or image['Architecture'] != 'amd64'
                or image['Config'].get('Labels', {}).get('experiment.release_sha') != release['application_sha']):
            raise RuntimeError(f'{name}: frozen image metadata mismatch')
    print('Prerequisites, source trees and frozen images verified')


def api(base, route, data=None, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    request = urllib.request.Request(base + route, data=json.dumps(data).encode() if data is not None else None,
                                     headers=headers)
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)


def await_ready(env):
    base = f'http://127.0.0.1:{port(env)}'
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            p = api(base, '/api/v1/instance/profile')
            if p['commit'] == RELEASES['v1']['application_sha'] and p['instanceUrl'] == base:
                return base
        except Exception:
            pass
        time.sleep(3)
    raise RuntimeError('Seed v1 did not become ready within 180 seconds')


def assert_owned(env):
    if CFG['projects'] != ['memos-current-experiment-staging', 'memos-current-experiment-production']:
        raise RuntimeError('Only conventional experiment projects may be mutated')
    name = project(env) + '_data'
    volume = json.loads(command('docker', 'volume', 'inspect', name))[0]
    if volume.get('Labels', {}).get('com.docker.compose.project') != project(env):
        raise RuntimeError('Refusing foreign volume: ' + name)
    containers = command('docker', 'ps', '-aq', '--filter', 'volume=' + name).splitlines()
    for cid in containers:
        container = json.loads(command('docker', 'inspect', cid))[0]
        if container['Config'].get('Labels', {}).get('com.docker.compose.project') != project(env):
            raise RuntimeError('Foreign container attached to owned volume')


def archive(env, destination):
    assert_owned(env)
    destination.mkdir(parents=True, exist_ok=False)
    command('docker', 'run', '--rm', '--network', 'none', '--user', '0', '--entrypoint', '/bin/sh',
            '--mount', f'type=volume,source={project(env)}_data,target=/data,readonly',
            '--mount', f'type=bind,source={destination},target=/backup', RELEASES['v1']['image_id'],
            '-ec', 'tar -czf /backup/data.tar.gz -C /data .; tar -tzf /backup/data.tar.gz >/dev/null')
    return digest(destination / 'data.tar.gz')


def restore(env, source):
    assert_owned(env)
    # Only a statically named, ownership-checked conventional volume is cleared.
    command('docker', 'run', '--rm', '--network', 'none', '--user', '0', '--entrypoint', '/bin/sh',
            '--mount', f'type=volume,source={project(env)}_data,target=/data',
            '--mount', f'type=bind,source={source},target=/seed,readonly', RELEASES['v1']['image_id'],
            '-ec', 'find /data -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +; tar -xzf /seed/data.tar.gz -C /data')


def no_remote_work():
    # Fail closed if GitHub is unavailable; never race a queued remote deployment.
    for workflow in ('frozen-cd.yml', 'local-cd.yml'):
        pages = json.loads(command('gh', 'api', '--paginate', '--slurp',
            f"repos/{CFG['repository']}/actions/workflows/{workflow}/runs?per_page=100"))
        if any(r['status'] != 'completed' for page in pages for r in page['workflow_runs']):
            raise RuntimeError('A remote conventional deployment is queued/running; reconcile it first')


def deploy(release, trial, scenario='S0', **kwargs):
    args = ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
            str(ROOT / 'scripts/local-cd/deploy.ps1'), '-Experiment', '-FrozenRelease', release,
            '-Commit', RELEASES[release]['application_sha'], '-TrialId', trial, '-Scenario', scenario]
    return subprocess.run(args, cwd=ROOT, **kwargs).returncode


def initialize():
    preflight()
    no_remote_work()
    if (STATE / 'seed').exists() or (STATE / 'credentials').exists():
        raise RuntimeError('Seed/state already exists. Use reset; partial initialization requires inspection.')
    for env in ('staging', 'production'):
        if command('docker', 'volume', 'ls', '-q', '--filter', f'name=^{project(env)}_data$'):
            raise RuntimeError('Refusing to seed an existing volume')
    credentials = None
    try:
        for env in ('staging', 'production'):
            compose(env, 'v1', 'up', '-d', '--no-build', '--pull', 'never', 'memos')
            base = await_ready(env)
            if env == 'staging':
                password = secrets.token_urlsafe(32)
                user = api(base, '/api/v1/users', dict(username='experiment', password=password,
                                                      role='ADMIN', displayName='Conventional experiment'))
                login = api(base, '/api/v1/auth/signin', {'passwordCredentials': {'username': 'experiment', 'password': password}})
                token = api(base, '/api/v1/' + user['name'] + '/personalAccessTokens',
                            {'description': 'Conventional local experiment', 'expiresInDays': 0}, login['accessToken'])['token']
                memo = api(base, '/api/v1/memos', {'content': 'conventional-experiment-sentinel-v1', 'visibility': 'PRIVATE'}, token)
                credentials = dict(token=token, sentinel_name=memo['name'], sentinel_content=memo['content'])
                compose(env, 'v1', 'stop', '--timeout', '30', 'memos')
                seed_hash = archive(env, STATE / 'seed')
            else:
                compose(env, 'v1', 'stop', '--timeout', '30', 'memos')
                restore(env, STATE / 'seed')
            path = STATE / 'credentials' / env
            path.mkdir(parents=True)
            save(path / 'credential.json', credentials)
        save(STATE / 'seed' / 'manifest.json', dict(owner=CFG['owner'], archive_sha256=seed_hash,
             created_at=now(), application_sha=RELEASES['v1']['application_sha'], identity=identity()))
    except Exception:
        print('Partial initialization retained for inspection; no automatic deletion or recovery.', file=sys.stderr)
        raise
    if deploy('v1', 'initialize-' + secrets.token_hex(6)):
        raise RuntimeError('Baseline deployment failed; diagnostics retained')
    save(STATE / 'baseline.json', dict(created_at=now(), seed_sha256=seed_hash, observations=verify('v1')))


def reset():
    preflight()
    no_remote_work()
    seed = read(STATE / 'seed/manifest.json')
    if seed['owner'] != CFG['owner'] or digest(STATE / 'seed/data.tar.gz') != seed['archive_sha256']:
        raise RuntimeError('Seed ownership/checksum mismatch')
    receipt = STATE / 'resets' / (time.strftime('%Y%m%dT%H%M%S') + '-' + secrets.token_hex(4))
    receipt.mkdir(parents=True)
    save(receipt / 'reset.json', dict(start=now(), seed=seed['archive_sha256'], status='started'))
    with lock('deployment.lock'):
        for env in ('staging', 'production'):
            assert_owned(env)
        for env in ('staging', 'production'):
            compose(env, 'v1', 'stop', '--timeout', '30', 'memos')
        for env in ('staging', 'production'):
            archive(env, receipt / env)
        for env in ('staging', 'production'):
            restore(env, STATE / 'seed')
        if (STATE / 'accepted.json').exists():
            shutil.copy2(STATE / 'accepted.json', receipt / 'previous-accepted.json')
            (STATE / 'accepted.json').unlink()
    if deploy('v1', 'reset-' + secrets.token_hex(6)):
        raise RuntimeError('Reset deployment failed; backups and seed retained')
    baseline = dict(created_at=now(), seed_sha256=seed['archive_sha256'], observations=verify('v1'), reset_receipt=str(receipt))
    save(STATE / 'baseline.json', baseline)
    save(receipt / 'reset.json', dict(start=read(receipt / 'reset.json')['start'], end=now(), status='verified', baseline=baseline))
    print('Reset to verified v1; previous data preserved at ' + str(receipt))


def native_evidence(directory, pointer):
    if not pointer.exists():
        return
    source = Path(pointer.read_text(encoding='utf-8-sig').strip()).resolve()
    if not source.is_relative_to((STATE / 'releases').resolve()):
        raise RuntimeError('Evidence pointer escapes owned state')
    # Explicit allowlist: never copy credentials, seed DBs or backups into evidence.
    for name in ('native-events.jsonl', 'release.json'):
        if (source / name).exists():
            shutil.copy2(source / name, directory / name)


def extract_logs(archive, target):
    """Preserve GitHub's full archive, including reusable-workflow job logs."""
    target = Path(target).resolve()
    with zipfile.ZipFile(archive) as bundle:
        if not bundle.namelist() or bundle.testzip() is not None:
            raise ValueError('Empty or corrupt GitHub log archive')
        if not all((target / name).resolve().is_relative_to(target) for name in bundle.namelist()):
            raise ValueError('GitHub log archive path escapes evidence directory')
        bundle.extractall(target)


def github_run(release, trial, scenario, directory, finished):
    repo = CFG['repository']
    sha = command('git', 'rev-parse', 'HEAD')
    remote = command('gh', 'api', f'repos/{repo}/commits/main', '--jq', '.sha')
    if remote != sha:
        raise RuntimeError('Publish this control revision to origin/main before a GitHub trial')
    command('gh', 'workflow', 'run', 'frozen-cd.yml', '--repo', repo, '--ref', 'main',
            '-f', 'release=' + release, '-f', 'trial_id=' + trial, '-f', 'scenario=' + scenario)
    # Unique title AND exact control SHA. Never select the latest run.
    deadline = time.monotonic() + 120
    run_id = None
    while time.monotonic() < deadline:
        runs = json.loads(command('gh', 'run', 'list', '--repo', repo, '--workflow', 'frozen-cd.yml',
                                 '--event', 'workflow_dispatch', '--limit', '100', '--json', 'databaseId,displayTitle,headSha'))
        matches = [r for r in runs if r['displayTitle'] == 'conventional-' + trial and r['headSha'] == sha]
        if len(matches) > 1:
            raise RuntimeError('Ambiguous run identity')
        if matches:
            run_id = matches[0]['databaseId']
            break
        time.sleep(3)
    if not run_id:
        raise RuntimeError('Dispatch uncorrelated; reconcile GitHub before reset')
    finished['run_id'] = run_id
    save(directory / 'dispatch.json', dict(github_run_id=run_id, control_sha=sha, timestamp=now()))
    ghdir = directory / 'github'
    ghdir.mkdir()
    deadline = time.monotonic() + 7200
    while time.monotonic() < deadline:
        run = json.loads(command('gh', 'run', 'view', str(run_id), '--repo', repo, '--json',
                                'databaseId,status,conclusion,headSha,startedAt,updatedAt,jobs,url'))
        save(ghdir / 'run.json', run)
        if run['status'] == 'completed':
            break
        time.sleep(5)
    else:
        raise RuntimeError('120-minute observation cap: run unresolved, not cancelled; reconcile manually')
    finished['native_terminal'] = run['updatedAt']
    pages = json.loads(command('gh', 'api', '--paginate', '--slurp',
                       f'repos/{repo}/actions/runs/{run_id}/jobs?filter=all&per_page=100'))
    jobs = [j for page in pages for j in page['jobs']]
    save(ghdir / 'jobs-all-attempts.json', jobs)
    run['jobs'] = [dict(id=j['id'], startedAt=j.get('started_at'), conclusion=j['conclusion']) for j in jobs]
    save(ghdir / 'run.json', run)
    try:
        logs = command('gh', 'run', 'view', str(run_id), '--repo', repo, '--log')
        (ghdir / 'logs.txt').write_text(logs, encoding='utf-8')
        archive = ghdir / 'raw-logs.zip'
        with archive.open('wb') as output:
            subprocess.run(['gh', 'api', f'repos/{repo}/actions/runs/{run_id}/logs'],
                           cwd=ROOT, stdout=output, check=True)
        extract_logs(archive, ghdir / 'raw-logs')
        command('gh', 'run', 'download', str(run_id), '--repo', repo, '--dir', ghdir / 'artifacts')
    except (subprocess.CalledProcessError, OSError, zipfile.BadZipFile, ValueError):
        save(ghdir / 'collection-warning.json', {'reason': 'Logs or artifacts unavailable; retained metadata'})
    for name in ('native-events.jsonl', 'release.json'):
        paths = list((ghdir / 'artifacts').rglob(name)) if (ghdir / 'artifacts').exists() else []
        if len(paths) == 1:
            shutil.copy2(paths[0], directory / name)
    finished.update(run_id=run_id, exit_code=0 if run['conclusion'] == 'success' else 1)


def run(args):
    validate(args.scenario)
    if args.scenario != 'S0' and args.release != 'v2':
        raise RuntimeError('Fault scenarios require v2')
    if args.scenario == 'S1' and args.mode != 'github':
        raise RuntimeError('S1 requires real GitHub quality jobs, not a local rehearsal')
    preflight()
    no_remote_work()
    if args.release == 'v2':
        verify('v1')
        if not (STATE / 'baseline.json').exists():
            raise RuntimeError('Initialize/reset first')
        if read(STATE / 'baseline.json').get('used_by'):
            raise RuntimeError('Baseline already used by a trial; reset before the next attempt')
    trial = args.trial
    if not trial or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-' for c in trial):
        raise ValueError('Use a unique alphanumeric trial ID')
    directory = RESULTS / trial
    directory.mkdir(parents=True, exist_ok=False)
    config = measurement(release=args.release, trial=trial, scenario=args.scenario,
                         mode='github' if args.mode == 'github' else 'local')
    save(directory / 'manifest.json', dict(identity=identity(), config=config, release=RELEASES[args.release],
         scope=args.mode, baseline=read(STATE / 'baseline.json'), resources=command('docker', 'info', '--format', '{{.NCPU}} CPUs; {{.MemTotal}} bytes')))
    if args.release == 'v2':
        baseline = read(STATE / 'baseline.json')
        baseline['used_by'] = trial
        save(STATE / 'baseline.json', baseline)
    pointer = directory / 'runtime-pointer.txt'
    meta = dict(pipeline_start=now(), pipeline_end=None, exit_code=None)
    save(directory / 'launch.json', meta)
    finished = {}
    stop_workload = threading.Event()

    def workload():
        credential = read(config['credential_file'])
        with (directory / 'workload.jsonl').open('w', encoding='utf-8') as stream:
            while not stop_workload.is_set():
                start = time.monotonic()
                record = {'timestamp': now()}
                request = urllib.request.Request(config['production_url'] + '/api/v1/' + credential['sentinel_name'],
                                                 headers={'Authorization': 'Bearer ' + credential['token']})
                try:
                    with urllib.request.urlopen(request, timeout=3) as response:
                        record.update(status=response.status, content_matches=json.load(response).get('content') == credential['sentinel_content'])
                except Exception as exc:
                    record.update(status=getattr(exc, 'code', None), error_type=type(exc).__name__)
                record['duration_seconds'] = time.monotonic() - start
                stream.write(json.dumps(record) + '\n'); stream.flush()
                stop_workload.wait(max(0, 1 - record['duration_seconds']))

    def controller():
        try:
            if args.mode == 'github':
                github_run(args.release, trial, args.scenario, directory, finished)
            else:
                with (directory / 'controller.log').open('w', encoding='utf-8') as log:
                    finished['exit_code'] = deploy(args.release, trial, args.scenario,
                        env=dict(os.environ, LOCAL_CD_EVIDENCE_POINTER=str(pointer)), stdout=log, stderr=subprocess.STDOUT)
            finished.setdefault('native_terminal', now())
            finished['operator_terminal'] = now()
        except Exception as exc:
            finished.update(error=str(exc), exit_code=None)

    traffic = threading.Thread(target=workload)
    worker = threading.Thread(target=controller)
    traffic.start(); worker.start()
    samples = []
    pipeline_samples = None
    endpoint = None
    try:
        with (directory / 'common-observations.jsonl').open('w', encoding='utf-8') as stream:
            while True:
                observation = sample(config)
                samples.append(observation)
                stream.write(json.dumps(observation) + '\n'); stream.flush()
                if not worker.is_alive() and endpoint is None:
                    meta.update(pipeline_end=now() if finished.get('exit_code') is not None else None,
                                exit_code=finished.get('exit_code'))
                    pipeline_samples = list(samples)
                    endpoint = time.monotonic() + (600 if args.mode == 'github' and meta['pipeline_end'] else 0)
                if endpoint is not None and time.monotonic() >= endpoint:
                    break
                time.sleep(2)
    finally:
        stop_workload.set(); traffic.join()
    native_evidence(directory, pointer)
    config['github_run_ids'] = [finished['run_id']] if finished.get('run_id') else []
    if args.no_interventions:
        save(directory / 'human-interventions.json', [])
    save(directory / 'launch.json', {**meta, **finished})
    # Preserve contract-v1 terminal semantics; follow-up is separate evidence.
    result = summarize(config, directory, meta, pipeline_samples or samples)
    if (directory / 'github/collection-warning.json').exists():
        result['evidence_complete'] = False
    save(directory / 'common-measurement.json', result)
    evaluation_time = instant(now())
    window = [s for s in samples if (evaluation_time - instant(s['timestamp'])).total_seconds() <= 30]
    coverage = (len(window) >= 3
                and (evaluation_time - instant(window[0]['timestamp'])).total_seconds() >= 15
                and (evaluation_time - instant(window[-1]['timestamp'])).total_seconds() <= 5
                and all((instant(b['timestamp']) - instant(a['timestamp'])).total_seconds() <= 15
                        for a, b in zip(window, window[1:])))
    endpoint_health = all(s['healthy'] for s in window) if coverage and args.mode == 'github' else None
    save(directory / 'evaluation.json', dict(scope=args.mode, followup_seconds=600 if args.mode == 'github' else 0,
         endpoint_time=evaluation_time.isoformat(), endpoint_health=endpoint_health,
         candidate_delivered_at_endpoint=(endpoint_health and samples[-1]['application_sha'] == config['application_sha']
             and samples[-1]['image_id'] == config['image_identity']) if endpoint_health is not None else None,
         observation_coverage=coverage, terminal_health=result['final_health'],
         fault_not_reached=args.scenario != 'S0' and not any('deterministic_failure' in p.read_text(encoding='utf-8-sig')
                 for p in directory.rglob('*.jsonl'))))
    save(directory / 'hashes.json', {p.relative_to(directory).as_posix(): digest(p)
                                   for p in directory.rglob('*') if p.is_file()})
    print('Evidence: ' + str(directory))
    return finished.get('exit_code') if finished.get('exit_code') is not None else 2


def images(action, path):
    path = Path(path).resolve()
    if action == 'export':
        preflight()
        path.mkdir(parents=True, exist_ok=True)
        for name, release in RELEASES.items():
            archive_path = path / (name + '.tar')
            if archive_path.exists():
                raise RuntimeError('Refusing to overwrite frozen image archive')
            command('docker', 'save', '-o', archive_path, release['image_id'])
        save(path / 'images.json', {name: {'sha256': digest(path / (name + '.tar')), **r} for name, r in RELEASES.items()})
    else:
        manifest = read(path / 'images.json')
        for name, release in RELEASES.items():
            if manifest[name]['image_id'] != release['image_id'] or digest(path / (name + '.tar')) != manifest[name]['sha256']:
                raise RuntimeError('Frozen archive mismatch')
            command('docker', 'load', '-i', path / (name + '.tar'))
        preflight()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    for name in ('check', 'init', 'reset', 'verify'):
        sub.add_parser(name)
    image_parser = sub.add_parser('images')
    image_parser.add_argument('operation', choices=['export', 'import'])
    image_parser.add_argument('path')
    run_parser = sub.add_parser('run')
    run_parser.add_argument('--release', choices=['v1', 'v2'], default='v2')
    run_parser.add_argument('--scenario', choices=['S0', 'S1', 'S2', 'S3', 'S4', 'S5'], default='S0')
    run_parser.add_argument('--mode', choices=['rehearsal', 'github'], default='rehearsal')
    run_parser.add_argument('--trial', required=True)
    run_parser.add_argument('--no-interventions', action='store_true')
    args = parser.parse_args()
    if args.action == 'check':
        preflight()
    elif args.action == 'verify':
        print(json.dumps(verify(), indent=2))
    else:
        with lock():
            if args.action == 'init': initialize()
            elif args.action == 'reset': reset()
            elif args.action == 'run': return run(args)
            elif args.action == 'images': images(args.operation, args.path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
