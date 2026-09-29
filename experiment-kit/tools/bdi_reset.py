"""Infrastructure-only reset using unchanged, clean pinned BDI worker primitives.

Qualification is an achieved historical campaign, never a synthetic controller
result. No controller, workflow dispatch, build, pull or passive trial observer.
"""
import image_identity as images_identity
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid
from types import SimpleNamespace

import experiment as operator
import controlled_seed

ENVIRONMENTS = ('staging', 'production')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def qualification(path, config, frozen):
    """Require sealed native evidence, including successful correlated workers."""
    path = Path(path).resolve()
    directory = path.parent.parent
    if path != directory / 'controller/controller-result.json':
        raise ValueError('Qualification must be a native controller result')
    names = ['controller/controller-result.json', 'identity.json', 'trial.json',
             'reset-receipt.json', 'final-state.json', 'remote-terminal.json']
    seals = sorted(directory.glob('evidence-sha256-*.json'))
    if not seals:
        raise ValueError('Qualification has no native evidence seal')
    # The original seal is the authority; later resealing cannot bless changes.
    seal = operator.read(seals[0])
    hashes = {}

    def sealed(name):
        key = name.replace('\\', '/')
        expected = {k.replace('\\', '/'): v for k, v in seal.items()}.get(key)
        actual = digest(directory / name)
        if not expected or actual != expected:
            raise ValueError('Qualification seal mismatch: ' + name)
        hashes[name] = actual
        return operator.read(directory / name)

    result, identity, trial, reset, final, terminal = [sealed(n) for n in names]
    v1 = frozen['releases']['v1']
    if (result.get('mode') != 'github' or result.get('outcome') != 'achieved'
            or result.get('mechanism') != 'bdi' or result.get('project') != 'memos'
            or result.get('repository') != config['repository']
            or result.get('release_sha') != v1['application_sha']
            or trial.get('mode') not in ('baseline', 'reset')
            or trial.get('application_sha') != v1['application_sha']
            or identity.get('repository') != config['repository']
            or identity.get('control_ref') != config['control_ref']
            or identity.get('releases') != frozen):
        raise ValueError('Not a matching achieved v1 qualification campaign')
    for record in (identity, trial, reset):
        if record.get('control_sha') != config['control_sha'] or record.get('approach') != 'bdi':
            raise ValueError('Qualification control/approach mismatch')
    for env in ENVIRONMENTS:
        verified = result.get('verified_releases', {}).get(env, {})
        if verified.get('release_sha') != v1['application_sha'] or verified.get('environment') != env:
            raise ValueError('Qualification lacks verified environment')
        for record in (reset, final):
            receipt = record.get('environments', {}).get(env, {})
            if (not receipt.get('verified') or receipt.get('release_sha') != v1['application_sha']
                    or not images_identity.matches(v1, receipt.get('image_id'))
                    or not verified.get('execution_id')
                    or receipt.get('deploymentRunId') != verified['execution_id']
                    or receipt.get('control_sha') != config['control_sha']):
                raise ValueError('Qualification artifact/environment mismatch')
    for job in ('build', 'test', 'security', 'staging', 'production'):
        execution = result.get('executions', {}).get(job, {})
        run = execution.get('githubRunId')
        if execution.get('status') != 'success' or not run or run not in terminal.get('github_runs', []):
            raise ValueError('Qualification lacks successful terminal workers')
        matches = sorted(directory.glob('github-*/' + str(run) + '.json'))
        if not matches:
            raise ValueError('Qualification lacks retained GitHub evidence')
        remote = sealed(matches[0].relative_to(directory).as_posix())
        if remote.get('headSha') != config['control_sha'] or remote.get('status') != 'completed' or remote.get('conclusion') != 'success':
            raise ValueError('Qualification worker identity/outcome mismatch')
        if job in ENVIRONMENTS and result['verified_releases'][job].get('github_run_id') != run:
            raise ValueError('Qualification verification/run mismatch')
    return {'path': str(path), 'sha256': hashes[names[0]], 'evidence_sha256': hashes,
            'seal_path': str(seals[0]), 'seal_sha256': digest(seals[0]),
            'control_sha': config['control_sha'], 'image_id': v1['image_id']}


def qualified_reference(config, frozen, path=None):
    if path is None:
        pointer = operator.read(Path(config['state']) / 'bdi/study-known-good.json')
        if pointer.get('control_sha') != config['control_sha']:
            raise ValueError('No qualification for selected control; run explicit baseline')
        path = pointer['path']
    return qualification(path, config, frozen)


def candidate_reference(receipt_path, config, frozen):
    receipt = operator.read(receipt_path)
    if receipt.get('kind') != 'infrastructure-reset':
        # Existing genuine baseline receipts retain their native interface.
        return qualification(Path(receipt_path).parent / 'controller/controller-result.json', config, frozen)['path']
    seals = sorted(Path(receipt_path).parent.glob('evidence-sha256-*.json'))
    if not seals or operator.read(seals[0]).get('reset-receipt.json') != digest(receipt_path):
        raise ValueError('Infrastructure reset receipt seal mismatch')
    reference = qualification(receipt['qualification']['path'], config, frozen)
    if reference != receipt['qualification']:
        raise ValueError('Reset qualification reference changed')
    if receipt.get('control_sha') != config['control_sha'] or receipt.get('approach') != 'bdi':
        raise ValueError('Reset control/approach mismatch')
    for env in ENVIRONMENTS:
        live = operator.read(Path(config['state']) / 'bdi' / env / 'current.json')
        v = receipt['environments'][env]
        if (not v.get('verified') or v['release_sha'] != frozen['releases']['v1']['application_sha']
                or not images_identity.matches(frozen['releases']['v1'], v['image_id'])
                or any(v[k] != live[k] for k in ('deploymentRunId', 'container_id', 'image_id', 'control_sha', 'project'))):
            raise ValueError('Reset receipt stale or wrong artifact')
    if Path(str(receipt_path) + '.consumed').exists():
        raise ValueError('Reset receipt already consumed')
    return reference['path']


def guard_state(target, config):
    state = Path(config['state'])
    common = Path(operator.git(target, 'rev-parse', '--path-format=absolute', '--git-common-dir'))
    paths = [common / 'bdi-execution-pending.json', state / 'active-campaign.json',
             state / 'bdi/armed-scenario.json']
    paths += [state / 'bdi' / env / 'fault/active.json' for env in ENVIRONMENTS]
    if any(p.exists() for p in paths):
        raise ValueError('Unresolved campaign/execution/fault; reconcile before infrastructure reset')
    worker = operator.read(target / 'experiment/adapter-contract.json')['workflow_file']
    if worker not in ('entity-execution.yml', 'job-execution.yml'):
        raise ValueError('Unreviewed BDI worker entry')
    raw = operator.output(['gh', 'api', '--paginate',
        'repos/' + config['repository'] + '/actions/workflows/' + worker + '/runs?per_page=100',
        '--jq', '{workflow_runs: .workflow_runs}'])
    pages = [json.loads(line) for line in raw.splitlines() if line.strip()]
    if not pages:
        raise ValueError('Missing remote worker inventory')
    if any(r['status'] != 'completed' for page in pages for r in page['workflow_runs']):
        raise ValueError('Remote BDI worker queued/running; reset blocked')


def reset_command(command):
    """Reset-only enforcement; never patch the measured rollback implementation."""
    command = list(command)
    allowed = (command[:2] in (['docker', 'inspect'], ['docker', 'ps'])
               or command[:3] in (['docker', 'image', 'inspect'], ['docker', 'volume', 'inspect'])
               or (command[:2] == ['docker', 'compose'] and any(x in command for x in ('up', 'stop', 'ps'))))
    if not allowed:
        raise ValueError('Build/pull or unexpected command forbidden during infrastructure reset')
    if command[:2] == ['docker', 'compose'] and 'up' in command:
        command += ['--no-build', '--pull', 'never']
    return command


def owned(ops, args):
    volume = args.project + '_data'
    meta = json.loads(ops.command(['docker', 'volume', 'inspect', volume], args.evidence, 'owned-volume'))[0]
    if meta.get('Labels', {}).get('com.docker.compose.project') != args.project:
        raise ValueError('Foreign volume ownership')
    ids = ops.command(['docker', 'ps', '-aq', '--filter', 'volume=' + volume], args.evidence, 'volume-containers').split()
    if not ids:
        raise ValueError('Missing owned deployment; inspect environment before reset')
    for cid in ids:
        container = json.loads(ops.command(['docker', 'inspect', cid], args.evidence, 'owned-container'))[0]
        if container['Config'].get('Labels', {}).get('com.docker.compose.project') != args.project:
            raise ValueError('Foreign container attached to data volume')
    live = operator.read(args.environment_state / 'current.json')
    if live.get('project') != args.project or live.get('control_sha') != args.control_sha or live.get('environment') != args.environment:
        raise ValueError('Environment receipt ownership/control mismatch')


def execute(target, config, directory, frozen):
    sys.path.insert(0, str(target / 'experiment/scripts'))
    import operate as ops
    from common import exclusive_lock, now, save, state_path
    from provenance import snapshot, seal
    state = state_path(config['state'])
    # Hold all native lifecycle/worker locks for the complete two-environment reset.
    with exclusive_lock(state / 'bdi-study.lock'), exclusive_lock(state / 'bdi-campaign.lock'), exclusive_lock(state / 'bdi-operation.lock'):
        guard_state(target, config)
        reference = qualified_reference(config, frozen)
        seed = controlled_seed.validate(state / 'phase7-seed', frozen['releases']['v1'])
        directory.mkdir(parents=True, exist_ok=False)
        snapshot(directory, config)
        (directory / 'bdi_reset.py').write_bytes(Path(__file__).read_bytes())
        (directory / 'controlled_seed.py').write_bytes(Path(controlled_seed.__file__).read_bytes())
        started, clock = now(), time.monotonic()
        trial_id = 'reset-' + uuid.uuid4().hex
        active = state / 'active-campaign.json'
        original_command = ops.command
        def command(argv, *args, **kwargs):
            return original_command(reset_command(argv), *args, **kwargs)
        ops.command = command
        environments = {}
        seed_receipts = {}
        try:
            # Validate both environments/artifacts before the first deployment.
            prepared = []
            for env in ENVIRONMENTS:
                args = SimpleNamespace(approach='bdi', environment=env, release_sha=frozen['releases']['v1']['application_sha'],
                    execution_id=trial_id + '-' + env, trial_id=trial_id, state=str(state),
                    evidence=str(directory / env), operation='deploy')
                ops.setup(args)
                owned(ops, args)
                ops.preflight(args)
                v1 = frozen['releases']['v1']
                saved = operator.read(state / 'bdi/images' / (v1['application_sha'] + '.json'))
                if any(saved.get(k) != v1[k] for k in ('application_sha', 'tree', 'version')):
                    raise ValueError('Retained image receipt differs from frozen qualification')
                meta = json.loads(ops.command(['docker', 'image', 'inspect', saved['image_id']], args.evidence, 'retained-image'))[0]
                images_identity.verify_image(v1, meta)
                if saved.get('frozen_oci_digest') != images_identity.frozen_digest(v1) or saved.get('runtime_image_id') != meta['Id'] or saved['image_id'] != meta['Id']:
                    raise ValueError('Retained runtime identity differs from proof')
                for image in ops.images(args).values():
                    ops.command(['docker', 'image', 'inspect', image], args.evidence, 'retained-sidecar')
                prepared.append(args)
            save(directory / 'qualification.json', reference)
            save(active, {'directory': str(directory), 'trial_id': trial_id, 'control_sha': config['control_sha'],
                          'kind': 'infrastructure-reset', 'recovery': 'Inspect partial reset; never finalize as a candidate campaign'})
            for args in prepared:
                boundary = time.monotonic()
                ops.deploy(args)
                if not ops.monitor(args):
                    raise RuntimeError('Reset telemetry verification failed')
                seed_receipts[args.environment] = controlled_seed.restore_verified(ops,args,seed,frozen['releases']['v1'],original_command)
                receipt = operator.read(args.evidence / 'verified-deployment.json')
                if not images_identity.matches(frozen['releases']['v1'], receipt['image_id']):
                    raise ValueError('Verified image differs from qualification')
                environments[args.environment] = receipt
                save(directory / (args.environment + '-timing.json'), {'seconds': time.monotonic() - boundary, 'role': 'infrastructure-reset'})
            save(directory / 'reset-receipt.json', {'schema_version': 1, 'kind': 'infrastructure-reset',
                'timestamp': now(), 'approach': 'bdi', 'control_sha': config['control_sha'],
                'qualification': reference, 'environments': environments,
                'data_semantics': 'shared-controlled-seed', 'controlled_seed': seed_receipts, 'treatment_cost': False})
            save(directory / 'reset-timing.json', {'started_at': started, 'completed_at': now(),
                'seconds': time.monotonic() - clock, 'role': 'infrastructure-reset',
                'controller_dispatched': False, 'passive_candidate_followup_seconds': 0})
            seal(directory)
            active.unlink()
        except BaseException as exc:
            # A seal/terminal-write failure must not leave a usable success receipt.
            receipt_path = directory / 'reset-receipt.json'
            if receipt_path.exists():
                receipt_path.rename(directory / 'incomplete-reset-receipt.json')
            save(directory / 'reset-failure.json', {'timestamp': now(), 'error_type': type(exc).__name__,
                'seconds': time.monotonic() - clock, 'role': 'infrastructure-reset',
                'requires_inspection': active.exists()})
            raise
        finally:
            ops.command = original_command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    manifest, frozen = operator.selection('bdi')
    spec = manifest['bdi']
    config = operator.read(args.config)
    target = args.runtime.resolve()
    if (operator.git(target, 'rev-parse', 'HEAD') != spec['control_sha'] or not operator.clean(target)
            or any(config[k] != spec[k] for k in ('control_sha', 'control_ref', 'repository'))):
        raise ValueError('Reset requires clean selected control/configuration')
    operator.published(spec, 'bdi')
    directory = args.directory.resolve()
    directory.relative_to(target / 'experiment/results')
    execute(target, config, directory, frozen)


if __name__ == '__main__':
    main()
