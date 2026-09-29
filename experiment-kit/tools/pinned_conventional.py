"""Revision-only adapter for the frozen conventional harness.

Uses the native run/reset/measurement implementation. Overrides only GitHub
dispatch selection so a moving main branch cannot change the workflow executed.
No deployment policy, job graph, retries, observations or recovery are changed.
"""
import argparse
import importlib
from pathlib import Path
import json
import os
import sys
import time


def load_native(runtime, control):
    sys.path.insert(0, str(runtime / 'experiment'))
    native = importlib.import_module('manage')
    if native.ROOT.resolve() != runtime or native.CFG['repository'] != control['repository']:
        raise ValueError('Unexpected native module or repository')
    return native


def check(runtime, control, scenario):
    """Native readiness checks with immutable-tag selection replacing HEAD==main."""
    native = load_native(runtime, control)
    native.validate(scenario)
    native.preflight()  # Includes frozen policy hashes and exact image/tree checks.
    native.no_remote_work()
    rf = native.runtime_fixture
    if scenario in rf.SCHEDULES:
        value = native.command('gh', 'variable', 'get', 'MEMOS_EXPERIMENT_ROOT', '--repo', native.CFG['repository'])
        if Path(value).resolve() != runtime:
            raise ValueError('MEMOS_EXPERIMENT_ROOT must identify selected operator checkout: ' + str(runtime))
        data = json.loads(native.command('docker', 'compose', '-f', runtime / 'scripts/local-cd/compose.yaml',
            '-f', rf.HERE / 'runtime-port.yaml', '-p', rf.PROJECT, 'config', '--format', 'json',
            env=dict(os.environ, MEMOS_IMAGE=native.images_identity.runtime_id(native.RELEASES['v2']), MEMOS_HOST_PORT='5542',
                     MEMOS_DATA_VOLUME=rf.PROJECT + '_data')))
        ports = data['services']['memos']['ports']
        if len(ports) != 1 or str(ports[0]['published']) != '5543':
            raise ValueError('Fixture Compose port replacement failed')
    runners = json.loads(native.command('gh', 'api', f"repos/{native.CFG['repository']}/actions/runners"))['runners']
    if not any(r['name'] == native.CFG['runner_name'] and r['status'] == 'online' and not r['busy'] for r in runners):
        raise ValueError('Dedicated conventional runner must be online and idle')


def github_run(native, control, release, trial, scenario, directory, finished):
    repo = native.CFG['repository']
    sha, ref = control['control_sha'], control['control_ref']
    if native.command('git', 'rev-parse', 'HEAD') != sha:
        raise ValueError('Native runtime/control mismatch')
    if native.command('gh', 'api', f'repos/{repo}/commits/{ref}', '--jq', '.sha') != sha:
        raise ValueError('Published immutable control tag changed; no dispatch')
    if hasattr(native, 'candidate_launch'):
        native.candidate_launch(directory, finished, trial, release)
    native.command('gh', 'workflow', 'run', 'frozen-cd.yml', '--repo', repo, '--ref', ref,
                   '-f', 'release=' + release, '-f', 'trial_id=' + trial, '-f', 'scenario=' + scenario)
    # Same exact-title + SHA correlation as manage.github_run; never latest-run.
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        runs = json.loads(native.command('gh', 'run', 'list', '--repo', repo, '--workflow', 'frozen-cd.yml',
                                        '--event', 'workflow_dispatch', '--limit', '100',
                                        '--json', 'databaseId,displayTitle,headSha'))
        matches = [r for r in runs if r['displayTitle'] == 'conventional-' + trial and r['headSha'] == sha]
        if len(matches) > 1:
            raise ValueError('Ambiguous run identity')
        if matches:
            run_id = matches[0]['databaseId']
            finished['run_id'] = run_id
            native.save(directory / 'dispatch.json', {'github_run_id': run_id, 'control_sha': sha,
                        'control_ref': ref, 'timestamp': native.now()})
            native.collect_run(run_id, directory, finished)
            return
        time.sleep(3)
    raise ValueError('Dispatch uncorrelated; reconcile GitHub before reset')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--selection', type=Path, required=True)
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    selection = json.loads(args.selection.read_text())
    control = selection['manifest']['conventional']
    runtime = args.runtime.resolve()
    if str(runtime) != selection['cwd']:
        raise ValueError('Runtime does not match recorded selection')
    native = load_native(runtime, control)
    native.github_run = lambda *a: github_run(native, control, *a)
    sys.argv = [str(runtime / 'experiment/manage.py'), *args.arguments]
    return native.main()


if __name__ == '__main__':
    raise SystemExit(main())
