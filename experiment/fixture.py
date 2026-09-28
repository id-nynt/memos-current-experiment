"""Explicit, deterministic fault fixture. Never changes controller decisions."""
import argparse
import datetime
import json
import os
from pathlib import Path


def validate(scenario):
    spec = json.loads(Path(__file__).with_name('scenarios.json').read_text())
    if scenario not in spec or not spec[scenario].get('enabled'):
        raise ValueError(f'Scenario {scenario} is not enabled; no execution allowed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', required=True)
    parser.add_argument('--boundary', choices=['ci', 'build', 'staging'], required=True)
    parser.add_argument('--receipt', required=True)
    args = parser.parse_args()
    validate(args.scenario)
    from ci_controls import run_control
    run_control(args.scenario, 'test' if args.boundary=='ci' else args.boundary,
                dict(campaign_id=os.environ.get('TRIAL_ID'),control_sha=os.environ.get('GITHUB_SHA'),
                     release_sha=os.environ.get('RELEASE_SHA')),Path(args.receipt).parent)
    fail = (args.scenario, args.boundary) in {('S1', 'ci'), ('S2', 'staging')}
    record = dict(timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  event='deterministic_failure' if fail else 'fixture_passed',
                  scenario=args.scenario, boundary=args.boundary)
    Path(args.receipt).write_text(json.dumps(record) + '\n', encoding='utf-8')
    print(json.dumps(record))
    return 42 if fail else 0


if __name__ == '__main__':
    raise SystemExit(main())
