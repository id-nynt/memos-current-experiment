"""Pinned single-trial operator: explicit reset -> run, with existing native guards.

Run conventional on Windows or Linux with PowerShell 7; BDI on Linux. No checkout,
tag, private configuration, controller policy or historical evidence is rewritten.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'protocol/operator-revisions.json'
from scenario_runtime import catalogue
SCENARIOS = ('S0', 'S1', 'S2', 'S3', 'S4R', 'S5R', 'S6', 'CI01', 'CI02', 'CI03') + tuple(k for k,v in catalogue().items() if v['status']=='implemented')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save_new(path, value):
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def output(command, cwd=None):
    return subprocess.check_output([str(x) for x in command], cwd=cwd, text=True,
                                   encoding='utf-8', errors='replace').strip()


def git(repo, *args):
    return output(['git', '-C', repo, *args])


def selection(approach):
    manifest = read(MANIFEST)
    if manifest['schema_version'] != 1:
        raise ValueError('Unsupported operator manifest schema')
    frozen = read(ROOT / manifest['release_manifest'])
    if set(frozen['releases']) != {'v1', 'v2'}:
        raise ValueError('Exactly baseline v1 and candidate v2 are required')
    # Check BOTH selected controls against the same authoritative application pair.
    for arm in ('conventional', 'bdi'):
        spec = manifest[arm]
        repo = ROOT / spec['checkout']
        sha = spec['control_sha']
        if not re.fullmatch(r'[0-9a-f]{40}', sha):
            raise ValueError('Expected full control SHA in operator manifest')
        if not re.fullmatch(r'memos-control-[A-Za-z0-9_.-]+', spec['control_ref']):
            raise ValueError('Expected immutable control tag in operator manifest')
        if git(repo, 'rev-parse', 'refs/tags/' + spec['control_ref'] + '^{commit}') != sha:
            raise ValueError(arm + ': control tag/SHA mismatch; no execution permitted')
        selected = json.loads(git(repo, 'show', sha + ':' + spec['release_manifest']))
        if selected != frozen:
            raise ValueError(arm + ': pinned release manifest differs from authoritative manifest')
        for release in frozen['releases'].values():
            if git(repo, 'rev-parse', release['application_sha'] + '^{tree}') != release['tree']:
                raise ValueError(arm + ': frozen application tree mismatch')
        if arm == 'bdi':
            pair = json.loads(git(repo, 'show', sha + ':experiment/protocol.json'))['pair']
            if pair != {k: v['application_sha'] for k, v in frozen['releases'].items()}:
                raise ValueError('BDI protocol/application pair mismatch')
    return manifest, frozen


def clean(repo):
    # Documentation edits are irrelevant; untracked execution code is not.
    return (not git(repo, 'status', '--porcelain', '--untracked-files=no')
            and not git(repo, 'ls-files', '--others', '--exclude-standard', '--',
                        'experiment', 'scripts', '.github/workflows', 'bdi-cicd-framework'))


def runtime(spec, approach):
    source = ROOT / spec['checkout']
    sha = spec['control_sha']
    if approach == 'conventional' and git(source, 'rev-parse', 'HEAD') == sha and clean(source):
        return source
    target = source / 'experiment/results/control-runtime' / sha
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['git', '-C', str(source), 'worktree', 'add', '--detach', str(target), sha], check=True)
    if git(target, 'rev-parse', 'HEAD') != sha or not clean(target):
        raise ValueError('Pinned runtime changed; preserve and inspect: ' + str(target))
    return target


def published(spec, approach):
    for ref in (spec['control_ref'],):
        actual = output(['gh', 'api', 'repos/' + spec['repository'] + '/commits/' + ref, '--jq', '.sha'])
        if actual != spec['control_sha']:
            raise ValueError(approach + ': published ' + ref + ' differs from operator pin; stop for a reviewed manifest update')


def policy_report(spec, scenario):
    from bdi_policy import report
    return report(ROOT, spec, scenario)


def plan(approach, action, scenario, target, spec, operation, prior=None):
    name = operation.name
    if approach == 'conventional':
        command = [sys.executable, '-B', str(target / 'experiment/manage.py'), action]
        if action == 'run':
            command = [sys.executable, '-B', str(ROOT / 'tools/pinned_conventional.py'),
                       '--runtime', str(target), '--selection', str(operation / 'selection.json'),
                       'run', '--release', 'v2', '--scenario', scenario, '--mode', 'github', '--trial', name]
        # Reset's native receipt is copied here; its private backup path is inside
        # that receipt. Unlike a candidate, reset has no native trial directory.
        return command, operation if action == 'reset' else target / 'experiment/results' / name, None
    destination = target / 'experiment/results' / name
    config = {'approach': 'bdi', 'repository': spec['repository'],
              'control_sha': spec['control_sha'], 'control_ref': spec['control_ref'],
              'state': str(Path(read(target / 'experiment/runtime.json')['state']).expanduser())}
    if action == 'run':
        from bdi_reset import candidate_reference
        config['bdi_known_good'] = candidate_reference(
            Path(prior['native_directory']) / 'reset-receipt.json', config,
            read(ROOT / read(MANIFEST)['release_manifest']))
    if action == 'reset':
        command = [sys.executable, '-B', str(ROOT / 'tools/bdi_reset.py'),
                   '--runtime', str(target), '--config', str(operation / 'operator.json'),
                   '--directory', str(destination)]
        return command, destination, config
    command = [sys.executable, '-B', str(target / 'experiment/scripts/trial.py'),
               'baseline' if action == 'qualify' else 'candidate',
               '--config', str(operation / 'operator.json'), '--directory', str(destination)]
    if action == 'run':
        command += ['--scenario', scenario, '--reset-receipt', str(Path(prior['native_directory']) / 'reset-receipt.json')]
        if scenario != 'S0':
            command.append('--allow-fault-execution')
    return command, destination, config


def main():
    if len(sys.argv)>1 and sys.argv[1] in ('run-batch','validate-study'):
        from study_execution import main as study_main
        return study_main(['study' if sys.argv[1]=='run-batch' else 'validate',*sys.argv[2:]])
    if len(sys.argv) > 1 and sys.argv[1] in ('prepare', 'stage-freeze', 'export-results', 'scenarios'):
        action = sys.argv[1]
        module = 'linux_prepare' if action in ('prepare', 'stage-freeze') else 'export_results' if action == 'export-results' else 'scenario_files'
        argv = [sys.executable, '-B', str(ROOT/'tools'/(module+'.py'))]
        return subprocess.call(argv + ([action] if module == 'linux_prepare' else []) + sys.argv[2:])
    if len(sys.argv) > 1 and sys.argv[1] == 'reset-v1':
        sys.argv[1] = 'reset'
    if len(sys.argv) > 1 and sys.argv[1] in ('server-check', 'run-case', 'run-set', 'resume-set', 'status', 'validate-results', 'artifacts', 'prepare-config', 'approve-faults'):
        from server_execution import main as server_main
        return server_main(sys.argv[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['check', 'policy', 'qualify', 'reset', 'run'])
    parser.add_argument('approach', choices=['conventional', 'bdi'])
    parser.add_argument('--scenario', choices=SCENARIOS, default='S0')
    parser.add_argument('--case', help='BDI run only: validated fault parameter JSON')
    parser.add_argument('--allow-fault-execution', action='store_true')
    parser.add_argument('--offline', action='store_true', help='check only: validate local pins without GitHub/Docker')
    parser.add_argument('--batch-token', help=argparse.SUPPRESS)
    args = parser.parse_args()
    batch_owner = ROOT / 'results/operator-state/batch.lock/owner.json'
    if batch_owner.parent.exists():
        if not batch_owner.exists() or read(batch_owner).get('token') != args.batch_token:
            raise ValueError('Exclusive batch owns this workspace; reconcile its lock before independent execution')
    elif args.batch_token:
        raise ValueError('Batch ownership token has no active lease')
    operation_started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    operation_clock = time.monotonic()
    if args.action == 'qualify' and args.approach != 'bdi':
        parser.error('qualify is the explicit full BDI baseline campaign')
    if args.case and (args.approach != 'bdi' or args.action != 'run'):
        parser.error('--case is only valid for BDI run')
    if args.offline and args.action not in ('check', 'policy'):
        parser.error('--offline is only valid for check/policy; it never simulates a successful trial')
    if args.action not in ('run', 'policy') and (args.scenario != 'S0' or args.allow_fault_execution):
        parser.error('Only run accepts a fault scenario')
    if args.action == 'policy' and (args.approach != 'bdi' or args.allow_fault_execution):
        parser.error('policy is a read-only BDI report; no fault execution flag is accepted')
    if args.action == 'run' and args.scenario != 'S0' and not args.allow_fault_execution:
        parser.error('Fault execution requires --allow-fault-execution; existing native approvals still apply')
    manifest, frozen = selection(args.approach)
    fingerprint = hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
    spec = manifest[args.approach]
    resolved = policy_report(spec, args.scenario) if args.approach == 'bdi' and (args.action == 'policy' or not args.offline) else None
    if args.action == 'policy':
        print(json.dumps(resolved, indent=2))
        return 0
    if args.offline:
        print(json.dumps({'check': 'local revision contract verified; no live validation',
                          'manifest_sha256': fingerprint, 'selected_control': spec,
                          'releases': frozen['releases'],
                          **({'resolved_policy': resolved} if resolved else {})}, indent=2))
        return 0
    if args.approach == 'bdi' and os.name == 'nt':
        raise ValueError('BDI requires Linux as the runner account')
    published(spec, args.approach)
    target = runtime(spec, args.approach)
    if args.scenario.startswith('P'):
        catalogue_path = target / ('experiment/scripts/scenario-catalogue.json' if args.approach == 'bdi' else 'experiment/scenario-catalogue.json')
        if not catalogue_path.exists():
            raise ValueError('Selected historical control cannot execute Phase 7; reviewed immutable publication required')
    if args.approach == 'conventional':
        from pinned_conventional import check
        check(target, spec, args.scenario)
    else:
        subprocess.run([sys.executable, '-B', str(target / 'bdi-cicd-framework/run_controller.py'),
                        '--validate-only'], cwd=target, check=True)
    resolved_case = None
    if args.case:
        validator = target / 'experiment/scripts/cases.py'
        if not validator.exists():
            raise ValueError('Selected immutable control does not support parameterised cases; reviewed publication required')
        resolved_case = json.loads(output([sys.executable, '-B', validator, '--scenario', args.scenario,
                                          '--case', str(Path(args.case).resolve())]))
    if args.action == 'check':
        print('Pins and native prerequisites checked. No reset or candidate executed.')
        return 0
    state = ROOT / 'results/operator-state'
    state.mkdir(parents=True, exist_ok=True)
    lock = state / (args.approach + '.lock')
    try:
        lock.mkdir()
    except FileExistsError:
        raise ValueError('Operator execution unresolved: ' + str(lock) + '; reconcile before another command')
    interrupted = False
    try:
        pointer = state / (args.approach + '-baseline.json')
        prior = read(pointer) if pointer.exists() else None
        if args.action == 'run':
            if not prior or prior['manifest_sha256'] != fingerprint or prior.get('consumed'):
                raise ValueError('Run reset for this approach first; matching unused baseline required')
        name = 'operator-' + args.approach + '-' + args.action + '-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
        operation = ROOT / 'results/operator-runs' / name
        operation.mkdir(parents=True, exist_ok=False)
        command, native, config = plan(args.approach, args.action, args.scenario, target, spec, operation, prior)
        if resolved_case:
            save_new(operation / 'case.json', resolved_case['case'])
            save_new(operation / 'resolved-case.json', resolved_case)
            command += ['--case', str(operation / 'case.json')]
        record = {'manifest_sha256': fingerprint, 'manifest': manifest, 'release_manifest': frozen,
                  'wrapper_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  'dispatch_adapter_sha256': hashlib.sha256((ROOT / 'tools/pinned_conventional.py').read_bytes()).hexdigest(),
                  'reset_adapter_sha256': hashlib.sha256((ROOT / 'tools/bdi_reset.py').read_bytes()).hexdigest(),
                  'action': args.action, 'approach': args.approach, 'scenario': args.scenario,
                  'control_sha': spec['control_sha'], 'native_directory': str(native),
                  'command': command, 'cwd': str(target), 'previous_reset': prior}
        save_new(operation / 'selection.json', record)
        if resolved:
            save_new(operation / 'resolved-policy.json', resolved)
            for filename in ('bdi_policy.py', 'bdi_attribution.py'):
                with (operation / filename).open('xb') as snapshot:
                    snapshot.write((ROOT / 'tools' / filename).read_bytes())
            with (operation / 'bdi-policy-contract.json').open('xb') as snapshot:
                snapshot.write((ROOT / spec.get('policy_contract', 'protocol/bdi-policy-contract.json')).read_bytes())
        for filename in ('experiment.py', 'pinned_conventional.py', 'bdi_reset.py'):
            with (operation / filename).open('xb') as snapshot:
                snapshot.write((ROOT / 'tools' / filename).read_bytes())
        if config:
            save_new(operation / 'operator.json', config)  # Only allowlisted non-secret fields.
        # Invalidate any older receipt BEFORE attempting a reset or candidate.
        # Failed/interrupted work cannot fall back to a stale baseline.
        if pointer.exists():
            pointer.unlink()
        print(json.dumps({'evidence': str(operation), 'native_evidence': str(native), 'command': command}), flush=True)
        with (operation / 'execution.log').open('x', encoding='utf-8') as log:
            code = subprocess.call(command, cwd=target, stdout=log, stderr=subprocess.STDOUT)
        if args.approach == 'bdi' and args.action != 'reset':
            from bdi_attribution import report
            save_new(operation / 'horizon-attribution.json', report(native))
        elif args.approach == 'bdi':
            save_new(operation / 'horizon-attribution.json', {
                'role': 'infrastructure-reset', 'treatment_cost': False,
                'note': 'No controller campaign or candidate observation horizon exists for this operation.'})
        save_new(operation / 'completion.json', {'exit_code': code, 'completed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            **({'reset_wrapper_started_at': operation_started_at,
                'reset_wrapper_seconds': time.monotonic() - operation_clock,
                'role': 'infrastructure-reset', 'treatment_cost': False} if args.action == 'reset' else {})})
        if code == 0 and args.action in ('reset', 'qualify'):
            if args.approach == 'bdi':
                receipt = read(native / 'reset-receipt.json')
                if receipt['control_sha'] != spec['control_sha'] or receipt.get('approach') != 'bdi' or set(receipt['environments']) != {'staging', 'production'} or not all(
                    v.get('verified') and v['release_sha'] == frozen['releases']['v1']['application_sha']
                    for v in receipt['environments'].values()):
                    raise ValueError('Reset receipt does not verify pinned v1')
            else:
                private = Path(os.environ.get('LOCALAPPDATA', Path.home())) / read(target / 'experiment/config.json')['owner']
                receipt = read(private / 'baseline.json')
                if receipt.get('used_by') or set(receipt['observations']) != {'staging', 'production'} or not all(v['healthy'] and v['application_sha'] == frozen['releases']['v1']['application_sha'] for v in receipt['observations'].values()):
                    raise ValueError('Conventional baseline does not verify pinned v1')
            save_new(operation / 'baseline-receipt.json', receipt)
            save_new(pointer, {'manifest_sha256': fingerprint, 'native_directory': str(native),
                               'operation': str(operation), 'consumed': False})
        print('Exit ' + str(code) + '; retained evidence: ' + str(operation), flush=True)
        return code
    except KeyboardInterrupt:
        interrupted = True
        print('Interrupted: preserve lock/evidence and reconcile native remote work before reset.', file=sys.stderr)
        raise
    finally:
        if not interrupted:
            lock.rmdir()


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
