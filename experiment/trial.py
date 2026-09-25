"""One conventional trial: preparation, external fixture, collection, then reset.

No trial is executed by installation or tests. A failed pipeline can be a complete
experiment; an unresolved run or missing fixture/evidence is an incomplete trial.
"""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import manage as m
import runtime_fixture as rf


def ready(scenario):
    rf.frozen_check()
    m.validate(scenario)
    if m.command('git', 'status', '--porcelain', '--untracked-files=no'):
        raise RuntimeError('Commit tracked harness changes before a trial')
    sha = m.command('git', 'rev-parse', 'HEAD')
    if m.command('gh', 'api', f"repos/{m.CFG['repository']}/commits/main", '--jq', '.sha') != sha:
        raise RuntimeError('Publish the exact harness revision to origin/main first')
    m.preflight()
    m.no_remote_work()
    if scenario in rf.SCHEDULES:
        value = m.command('gh', 'variable', 'get', 'MEMOS_EXPERIMENT_ROOT', '--repo', m.CFG['repository'])
        if Path(value).resolve() != m.ROOT.resolve():
            raise RuntimeError('MEMOS_EXPERIMENT_ROOT must identify this operator checkout')
        # Read-only config expansion also tests !override compatibility.
        import os
        text = m.command('docker', 'compose', '-f', m.ROOT / 'scripts/local-cd/compose.yaml',
                         '-f', rf.HERE / 'runtime-port.yaml', '-p', rf.PROJECT, 'config', '--format', 'json',
                         env=dict(os.environ, MEMOS_IMAGE=m.RELEASES['v2']['image_id'],
                                  MEMOS_HOST_PORT='5542', MEMOS_DATA_VOLUME=rf.PROJECT + '_data'))
        service = json.loads(text)['services']['memos']
        if len(service['ports']) != 1 or str(service['ports'][0]['published']) != '5543':
            raise RuntimeError('Fixture Compose port replacement failed')
    runners = json.loads(m.command('gh', 'api', f"repos/{m.CFG['repository']}/actions/runners"))['runners']
    if not any(r['name'] == m.CFG['runner_name'] and r['status'] == 'online' and not r['busy'] for r in runners):
        raise RuntimeError('Dedicated conventional runner must be online and idle')


def run(args):
    directory = rf.trial_directory(m.ROOT, args.trial)
    lifecycle = rf.trial_directory(m.ROOT, args.trial + '-lifecycle')
    if directory.exists() or lifecycle.exists():
        raise RuntimeError('Trial ID already exists; nothing reset or overwritten')
    ready(args.scenario)
    lifecycle.mkdir(parents=True)
    receipt = dict(trial_id=args.trial, scenario=args.scenario, started_at=m.now(), status='preparing',
                   controller=rf.frozen_check(), harness=m.identity(), automatic_reset='outside measured trial')
    m.save(lifecycle / 'lifecycle.json', receipt)
    try:
        m.reset()
        receipt['baseline'] = m.read(m.STATE / 'baseline.json')
        receipt['status'] = 'running'
        m.save(lifecycle / 'lifecycle.json', receipt)
        code = m.run(SimpleNamespace(scenario=args.scenario, release='v2', mode='github',
                                     trial=args.trial, no_interventions=args.no_interventions))
        receipt['pipeline_exit_code'] = code
        result = m.read(directory / 'raw-result.json')
        launch = m.read(directory / 'launch.json')
        if launch.get('exit_code') is None:
            raise RuntimeError('Remote work unresolved; reconcile before cleanup/reset')
        # Final facts before reset, even if health is false. Do not require a
        # controller outcome to match a hypothesis in order to collect evidence.
        final_state = directory / 'final-state-before-cleanup.json'
        receipt['pre_reset_observations'] = (m.read(final_state) if final_state.exists() else
            {env: m.sample(m.measurement(env)) for env in ('staging', 'production')})
        receipt['collection_complete'] = ((directory / 'github/raw-logs.zip').exists()
            and not (directory / 'github/collection-warning.json').exists()
            and (directory / 'github/jobs-all-attempts.json').exists()
            and (args.scenario == 'S1' or ((directory / 'native-events.jsonl').exists()
                 and (directory / 'release.json').exists()
                 and 'pipeline_end' in (directory / 'native-events.jsonl').read_text(encoding='utf-8-sig')))
            and bool(result['github_run_ids']) and result['endpoint']['observation_coverage'])
        receipt['fault_exposure_recorded'] = not result['endpoint']['fault_not_reached']
        receipt['fixture_valid'] = result['fixture_valid']
        receipt['status'] = 'resetting'
        m.save(lifecycle / 'lifecycle.json', receipt)
        m.reset()
        receipt['reset'] = m.read(m.STATE / 'baseline.json')
        receipt.update(status='completed', completed_at=m.now())
        m.save(lifecycle / 'lifecycle.json', receipt)
        m.save(lifecycle / 'hashes.json', {p.name: m.digest(p) for p in lifecycle.iterdir() if p.is_file()})
        print('Trial and reset complete: ' + str(lifecycle))
        valid = receipt['collection_complete'] and (args.scenario == 'S0' or receipt['fault_exposure_recorded'])
        if args.scenario in rf.SCHEDULES:
            valid = valid and receipt['fixture_valid']
        return 0 if valid else 2
    except BaseException as exc:
        receipt.update(status='interrupted_or_incomplete', error_type=type(exc).__name__,
                       error=str(exc), stopped_at=m.now())
        m.save(lifecycle / 'lifecycle.json', receipt)
        print('Evidence retained. No automatic recovery/reset after interruption; see the guide.')
        raise


def collect(args):
    source = rf.trial_directory(m.ROOT, args.trial)
    dispatch = m.read(source / 'dispatch.json')
    run_id = dispatch['github_run_id']
    run = json.loads(m.command('gh', 'run', 'view', str(run_id), '--repo', m.CFG['repository'],
                    '--json', 'headSha,displayTitle,status'))
    if run['headSha'] != dispatch['control_sha'] or run['displayTitle'] != 'conventional-' + args.trial:
        raise RuntimeError('Run identity mismatch')
    if run['status'] != 'completed':
        raise RuntimeError('Run is not terminal. Wait, or explicitly cancel and record intervention.')
    output = rf.trial_directory(m.ROOT, args.trial + '-recollection-' + m.secrets.token_hex(4))
    output.mkdir()
    finished = {}
    m.collect_run(run_id, output, finished)
    m.save(output / 'recollection.json', dict(source=str(source), timestamp=m.now(), **finished,
           note='Log recollection only; missing observation periods remain unknown.'))
    print(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('run', 'check'):
        p = sub.add_parser(name)
        p.add_argument('--scenario', choices=['S0', 'S1', 'S2', 'S3', 'S4', 'S5'], required=True)
        if name == 'run':
            p.add_argument('--trial', required=True)
            p.add_argument('--no-interventions', action='store_true')
    p = sub.add_parser('collect')
    p.add_argument('--trial', required=True)
    p = sub.add_parser('note')
    p.add_argument('--trial', required=True)
    p.add_argument('--action', required=True)
    sub.add_parser('reset')
    args = parser.parse_args()
    if args.command == 'note':
        directory = rf.trial_directory(m.ROOT, args.trial)
        if not (directory / 'manifest.json').exists() or (directory / 'hashes.json').exists():
            raise RuntimeError('Notes require an active, unsealed trial; completed evidence is immutable')
        notes = directory / 'interventions'
        notes.mkdir(exist_ok=True)
        rf.atomic(notes / (m.secrets.token_hex(12) + '.json'), dict(timestamp=m.now(), action=args.action))
        return 0
    with m.lock():
        if args.command == 'run':
            return run(args)
        if args.command == 'check':
            ready(args.scenario)
        elif args.command == 'collect':
            collect(args)
        else:
            m.reset()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
