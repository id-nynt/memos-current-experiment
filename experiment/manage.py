"""Repository-owned conventional preparation, execution and passive evidence CLI."""
import argparse
import contextlib
import datetime as dt
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
import image_identity as images_identity
import frozen_artifacts
from fixture import validate
import runtime_fixture
from measurement_records import request_record
from final_timing import HORIZON, window as timing_window, require_current_scenario

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
            'controller_policy': CFG['controller_policy'],
            'files': {p.relative_to(ROOT).as_posix(): digest(p) for p in paths}}


@contextlib.contextmanager
def lock(name='experiment.lock'):
    """Shared Linux exclusive-create lease; original Windows byte lock retained."""
    if os.name != 'nt':
        STATE.mkdir(parents=True, exist_ok=True)
        lease = STATE / (name + '.linux-lease')
        with lease.open('xb'):
            try:
                yield
            finally:
                lease.unlink()
        return
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
    variables = dict(os.environ, MEMOS_IMAGE=images_identity.runtime_id(RELEASES[release]),
                     MEMOS_RESTART_POLICY='no', MEMOS_HOST_PORT=str(port(env)), MEMOS_DATA_VOLUME=project(env) + '_data')
    return command('docker', 'compose', '-f', ROOT / 'scripts/local-cd/compose.yaml',
                   '-p', project(env), *args, env=variables)


def measurement(env='production', release='v2', trial='verification', scenario='S0', mode='local'):
    r = RELEASES[release]
    return dict(approach='conventional', scenario=scenario, trial_id=trial,
                control_sha=command('git', 'rev-parse', 'HEAD'), application_sha=r['application_sha'],
                image_identity=images_identity.frozen_digest(r), frozen_oci_digest=images_identity.frozen_digest(r), runtime_image_id=images_identity.runtime_id(r), execution_mode=mode, releases=RELEASES,
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
    runtime_fixture.frozen_check()
    for name in ('git', 'docker', 'powershell' if os.name == 'nt' else 'pwsh', 'tar', 'gh'):
        if not shutil.which(name):
            raise RuntimeError(f'Missing prerequisite: {name}')
    if command('docker', 'version', '--format', '{{.Server.Os}}/{{.Server.Arch}}') != 'linux/amd64':
        raise RuntimeError('Docker Linux/amd64 is required')
    for name, release in RELEASES.items():
        if command('git', 'rev-parse', release['application_sha'] + '^{tree}') != release['tree']:
            raise RuntimeError(f'{name}: source tree mismatch; fetch the frozen tags')
        images_identity.resolve(release, lambda value: json.loads(command('docker', 'image', 'inspect', value))[0])
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
    destination.mkdir(parents=True, exist_ok=False, mode=0o700)
    # Root must read the stopped database volume, but the new private archive
    # belongs to the host operator. Change metadata only, never the tar payload.
    archive_command = 'umask 077; tar -czf /backup/data.tar.gz -C /data .; tar -tzf /backup/data.tar.gz >/dev/null'
    if os.name == 'posix':
        archive_command += f'; chown {os.getuid()}:{os.getgid()} /backup/data.tar.gz'
    archive_command += '; chmod 600 /backup/data.tar.gz'
    command('docker', 'run', '--rm', '--network', 'none', '--user', '0', '--entrypoint', '/bin/sh',
            '--mount', f'type=volume,source={project(env)}_data,target=/data,readonly',
            '--mount', f'type=bind,source={destination},target=/backup', images_identity.runtime_id(RELEASES['v1']),
            '-ec', archive_command)
    return digest(destination / 'data.tar.gz')


def restore(env, source):
    assert_owned(env)
    # Only a statically named, ownership-checked conventional volume is cleared.
    command('docker', 'run', '--rm', '--network', 'none', '--user', '0', '--entrypoint', '/bin/sh',
            '--mount', f'type=volume,source={project(env)}_data,target=/data',
            '--mount', f'type=bind,source={source},target=/seed,readonly', images_identity.runtime_id(RELEASES['v1']),
            '-ec', 'find /data -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +; tar -xzf /seed/data.tar.gz -C /data')


def no_remote_work():
    # Fail closed if GitHub is unavailable; never race a queued remote deployment.
    for workflow in ('frozen-cd.yml', 'local-cd.yml'):
        pages = json.loads(command('gh', 'api', '--paginate', '--slurp',
            f"repos/{CFG['repository']}/actions/workflows/{workflow}/runs?per_page=100"))
        if any(r['status'] != 'completed' for page in pages for r in page['workflow_runs']):
            raise RuntimeError('A remote conventional deployment is queued/running; reconcile it first')


def deploy(release, trial, scenario='S0', **kwargs):
    args = ['powershell.exe' if os.name == 'nt' else 'pwsh', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
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


def candidate_launch(directory, finished, trial, release='v2'):
    finished['candidate_launch_at'] = now()
    finished['candidate_launch_monotonic'] = time.monotonic()
    save(directory / 'measurement-boundaries.json', {
        'schema_version': 2, 'role': 'candidate' if release == 'v2' else 'qualification',
        'trial_id': trial, 'candidate_launch_at': finished['candidate_launch_at'],
        'clock': 'host_utc', 'native_terminal_source': 'correlated GitHub terminal metadata'})


def github_run(release, trial, scenario, directory, finished):
    repo = CFG['repository']
    sha = command('git', 'rev-parse', 'HEAD')
    remote = command('gh', 'api', f'repos/{repo}/commits/main', '--jq', '.sha')
    if remote != sha:
        raise RuntimeError('Publish this control revision to origin/main before a GitHub trial')
    candidate_launch(directory, finished, trial, release)
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
    collect_run(run_id, directory, finished)


def collect_run(run_id, directory, finished):
    repo = CFG['repository']
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
    require_current_scenario(args.scenario)
    validate(args.scenario)
    if args.scenario != 'S0' and args.release != 'v2':
        raise RuntimeError('Fault scenarios require v2')
    if args.scenario in ('S1', 'S6', 'CI01', 'CI02', 'CI03') and args.mode != 'github':
        raise RuntimeError('CI fault scenarios require real GitHub quality jobs, not a local rehearsal')
    runtime = args.scenario in runtime_fixture.SCHEDULES
    if runtime and args.mode != 'github':
        raise RuntimeError('Runtime fixtures require the GitHub runner adapter')
    preflight()
    no_remote_work()
    if args.release == 'v2':
        verify('v1')
        if not (STATE / 'baseline.json').exists():
            raise RuntimeError('Initialize/reset first')
        if read(STATE / 'baseline.json').get('used_by'):
            raise RuntimeError('Baseline already used by a trial; reset before the next attempt')
    trial = args.trial
    directory = runtime_fixture.trial_directory(ROOT, trial)
    directory.mkdir(parents=True, exist_ok=False)
    config = measurement(release=args.release, trial=trial, scenario=args.scenario,
                         mode='github' if args.mode == 'github' else 'local')
    save(directory / 'manifest.json', dict(identity=identity(), config=config, release=RELEASES[args.release],
         scope=args.mode, baseline=read(STATE / 'baseline.json'), resources=command('docker', 'info', '--format', '{{.NCPU}} CPUs; {{.MemTotal}} bytes')))
    baseline = read(STATE / 'baseline.json')
    if args.release == 'v2':
        baseline['used_by'] = trial
        save(STATE / 'baseline.json', baseline)
    pointer = directory / 'runtime-pointer.txt'
    meta = dict(pipeline_start=now(), pipeline_end=None, exit_code=None)
    save(directory / 'launch.json', meta)
    if args.scenario.startswith('P') or args.scenario in ('S6', 'CI01', 'CI02', 'CI03'):
        seed_manifest=read(STATE/'seed/manifest.json')
        if digest(STATE/'seed/data.tar.gz') != seed_manifest['archive_sha256'] or read(STATE/'baseline.json')['seed_sha256'] != seed_manifest['archive_sha256']:
            raise ValueError('Controlled seed baseline mismatch')
        save(directory/'reset-state.json',dict(data_semantics='shared-controlled-seed',
            archive_sha256=seed_manifest['archive_sha256'],application_sha=RELEASES['v1']['application_sha'],
            image_id=baseline['observations']['production']['image_id'],
            **images_identity.evidence(RELEASES['v1'], baseline['observations']['production']['image_id']),verified=True,role='infrastructure-reset',treatment_cost=False))
    finished = {}
    stop_workload = threading.Event()
    injector = runtime_fixture.Fixture(directory, args.scenario, config, sample) if runtime else None
    if injector:
        injector.arm()
    staging_observer = None
    if injector and injector.environment == 'staging':
        from staging_observer import StagingObserver
        staging_observer = StagingObserver(measurement('staging', release=args.release, trial=trial), directory)
        staging_observer.start()

    def workload():
        credential = read(config['credential_file'])
        ordinal = 0
        with (directory / 'workload.jsonl').open('w', encoding='utf-8') as stream:
            while not stop_workload.is_set():
                start = time.monotonic()
                ordinal += 1
                record = {'timestamp': now(), 'request_id': 'production-' + str(ordinal)}
                with (directory / 'workload-starts.jsonl').open('a', encoding='utf-8') as starts:
                    starts.write(json.dumps(dict(request_id=record['request_id'],request_started_at=record['timestamp']))+'\n')
                request = urllib.request.Request(config['production_url'] + '/api/v1/' + credential['sentinel_name'],
                                                 headers={'Authorization': 'Bearer ' + credential['token'], 'X-Experiment-Stream': 'independent','X-Experiment-Request':record['request_id']})
                status = valid = matches = failure = None
                try:
                    with urllib.request.urlopen(request, timeout=3) as response:
                        status = response.status
                        body = json.load(response)
                        valid = isinstance(body, dict)
                        matches = body.get('content') == credential['sentinel_content'] if valid else None
                except Exception as exc:
                    failure = exc
                    status = getattr(exc, 'code', status)
                record.update(request_record(record['timestamp'], now(), time.monotonic() - start,
                                             status, valid, matches, failure))
                stream.write(json.dumps(record) + '\n'); stream.flush()
                stop_workload.wait(max(0, 1 - record['duration_seconds']))

    def controller():
        try:
            if args.mode == 'github':
                github_run(args.release, trial, args.scenario, directory, finished)
            else:
                with (directory / 'controller.log').open('w', encoding='utf-8') as log:
                    candidate_launch(directory, finished, trial, args.release)
                    finished['exit_code'] = deploy(args.release, trial, args.scenario,
                        env=dict(os.environ, LOCAL_CD_EVIDENCE_POINTER=str(pointer)), stdout=log, stderr=subprocess.STDOUT)
            finished.setdefault('native_terminal', now())
            finished['operator_terminal'] = now()
        except Exception as exc:
            finished.update(error=str(exc), exit_code=None)

    def workload_safe():
        try:
            workload()
        except Exception as exc:
            save(directory / 'measurement-errors.json', {
                'timestamp': now(), 'role': 'independent_workload',
                'error_type': type(exc).__name__, 'affects_native_outcome': False})

    traffic = threading.Thread(target=workload_safe, daemon=True)
    worker = threading.Thread(target=controller, daemon=True)
    traffic.start(); worker.start()
    samples = []
    pipeline_samples = None
    endpoint = None
    evaluation_epoch = None
    try:
        with (directory / 'common-observations.jsonl').open('w', encoding='utf-8') as stream:
            while True:
                observation = sample(config)
                observation['role'] = 'EXPERIMENT MEASUREMENT'
                observation['controller_terminal_seen'] = finished.get('native_terminal') is not None
                samples.append(observation)
                stream.write(json.dumps(observation) + '\n'); stream.flush()
                if args.mode == 'github' and endpoint is None and (injector and injector.started is not None or finished.get('native_terminal')):
                    anchor = instant(injector.t0).timestamp() if injector and injector.t0 else instant(finished['native_terminal']).timestamp()
                    horizon = timing_window(anchor)
                    evaluation_epoch = horizon['endpoint_epoch']
                    endpoint = time.monotonic() + max(0, evaluation_epoch - time.time())
                    save(directory / 'observation-horizon.json', horizon)
                if not worker.is_alive() and pipeline_samples is None:
                    meta.update(pipeline_end=now() if finished.get('exit_code') is not None else None,
                                exit_code=finished.get('exit_code'))
                    pipeline_samples = list(samples)
                    if endpoint is None:
                        # Incomplete native evidence: preserve outcome, do not invent a valid horizon.
                        endpoint = time.monotonic()
                if endpoint is not None and time.monotonic() >= endpoint and not worker.is_alive():
                    break
                time.sleep(2)
    finally:
        stop_workload.set(); traffic.join()
        if staging_observer:
            staging_observer.close()
        if injector:
            save(directory / 'final-state-before-cleanup.json',
                 {env: sample(measurement(env)) for env in ('staging', 'production')})
            injector.close()
    native_evidence(directory, pointer)
    config['github_run_ids'] = [finished['run_id']] if finished.get('run_id') else []
    interventions = [read(p) for p in sorted((directory / 'interventions').glob('*.json'))]
    if interventions or args.no_interventions:
        save(directory / 'human-interventions.json', interventions)
    save(directory / 'launch.json', {**meta, **finished})
    save(directory / 'measurement-boundaries.json', {
        'schema_version': 2, 'role': 'candidate' if args.release == 'v2' else 'qualification', 'trial_id': trial,
        'candidate_launch_at': finished.get('candidate_launch_at'),
        'native_terminal_at': finished.get('native_terminal'),
        'native_terminal_source': 'correlated GitHub updatedAt; completion proxy',
        'collection_completed_at': finished.get('operator_terminal'),
        'observation_completed_at': now(), 'clock': 'host UTC / GitHub UTC',
        'duration_quality': 'cross_clock', 'reset_included': False})
    # Preserve contract-v1 terminal semantics; follow-up is separate evidence.
    result = summarize(config, directory, meta, pipeline_samples or samples)
    if (directory / 'github/collection-warning.json').exists():
        result['evidence_complete'] = False
    save(directory / 'common-measurement.json', result)
    evaluation_time = dt.datetime.fromtimestamp(evaluation_epoch, dt.timezone.utc) if evaluation_epoch is not None else instant(now())
    window = [s for s in samples if 0 <= (evaluation_time - instant(s['timestamp'])).total_seconds() <= 30]
    coverage = (evaluation_epoch is not None and len(window) >= 3
                and (evaluation_time - instant(window[0]['timestamp'])).total_seconds() >= (25 if args.scenario in ('S4R', 'S5R') else 15)
                and (evaluation_time - instant(window[-1]['timestamp'])).total_seconds() <= 5
                and all((instant(b['timestamp']) - instant(a['timestamp'])).total_seconds() <= 15
                        for a, b in zip(window, window[1:])))
    endpoint_health = all(s['healthy'] for s in window) if coverage and args.mode == 'github' else None
    save(directory / 'evaluation.json', dict(role='EXPERIMENT MEASUREMENT', affects_controller_outcome=False, scope=args.mode, followup_seconds=HORIZON if args.mode == 'github' else 0,
         endpoint_time=evaluation_time.isoformat(), endpoint_health=endpoint_health,
         candidate_delivered_at_endpoint=(endpoint_health and window[-1]['application_sha'] == config['application_sha']
             and images_identity.matches(RELEASES[args.release], window[-1]['image_id'])) if endpoint_health is not None else None,
         observation_coverage=coverage, terminal_health=result['final_health'],
         fault_not_reached=args.scenario != 'S0' and not any(any(name in p.read_text(encoding='utf-8-sig') for name in ('deterministic_failure', 'injected_response', 'transient_dependency_failure'))
                 for p in directory.rglob('*.jsonl'))))
    if args.scenario in ('S4R', 'S5R'):
        import paired_rq1 as paired
        native_path = directory / 'native-events.jsonl'
        native = [json.loads(x) for x in native_path.read_text(encoding='utf-8-sig').splitlines() if x.strip()] if native_path.exists() else []
        ends = [x['timestamp'] for x in native if x.get('event') == 'pipeline_end']
        probes = [x for x in native if x.get('event') == 'health_observation' and x.get('environment') == 'production']
        save(directory / 'active-opportunity.json', paired.opportunity(
            instant(injector.t0).timestamp() if injector and injector.t0 else None,
            ends[-1] if ends else None, probes, args.scenario))
    save(directory / 'raw-result.json', raw_result(directory, config, result, samples, injector))
    save(directory / 'hashes.json', {p.relative_to(directory).as_posix(): digest(p)
                                   for p in directory.rglob('*') if p.is_file()})
    print('Evidence: ' + str(directory))
    return finished.get('exit_code') if finished.get('exit_code') is not None else 2


def raw_result(directory, config, common, samples, injector):
    """Factual inventory only. No cross-approach scoring or success prediction."""
    from measure_trial import events
    records = list(events(directory, common['pipeline_start']))
    jobs = read(directory / 'github/jobs-all-attempts.json') if (directory / 'github/jobs-all-attempts.json').exists() else []
    evaluation = read(directory / 'evaluation.json')
    endpoint = instant(evaluation['endpoint_time'])
    at_endpoint = [s for s in samples if instant(s['timestamp']) <= endpoint]
    final = at_endpoint[-1] if at_endpoint else {}
    return dict(**common, frozen_controller=runtime_fixture.frozen_check()['revision'],
                harness_identity=identity(), endpoint=evaluation, endpoint_observation=final,
                candidate_retained=(final.get('application_sha') == config['application_sha'] and
                                    images_identity.matches(next(r for r in RELEASES.values() if r['application_sha']==config['application_sha']), final.get('image_id'))) if final else None,
                deployment_events=[e for e in records if e.get('event') in ('deployment_start', 'deployment_end')],
                fault_events=[e for e in records if e.get('event') in ('deterministic_failure', 'fault_started', 'fault_boundary', 'fault_ended', 'transient_dependency_failure', 'transient_condition_cleared')],
                native_probe_rounds=sum(e.get('event') == 'health_observation' for e in records),
                external_health_sample_count=len(samples),
                fixture_valid=(bool(injector.t0) and not injector.error and
                               (directory / 'fixture-hook.json').exists() and
                               0 <= read(directory / 'fixture-hook.json')['synchronization_seconds'] <= 2) if injector else None,
                jobs=jobs, raw_evidence_path=str(directory),
                note='Null is unknown; endpoint retention does not imply health or pipeline acceptance.')


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
        frozen_artifacts.verify_bundle(path, {'releases': RELEASES})
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
    run_parser.add_argument('--scenario', choices=['S0', 'S1', 'S2', 'S3', 'S4', 'S5', 'S4R', 'S5R', 'S6', 'CI01', 'CI02', 'CI03'] + list(runtime_fixture.final_scenarios.catalogue()), default='S0')
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
