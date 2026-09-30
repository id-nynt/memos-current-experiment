"""The representative SQLite workload, shared verbatim by rehearsal and CI.

Run only against a disposable exact frozen application checkout. This performs
application validation, not deployment, fault injection or experiment measurement.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def documents(base=None):
    base = Path(base or __file__).resolve().parent
    if (base / 'ci-workload.json').exists():
        contract = base / 'ci-workload.json'
        releases = base / 'frozen-releases.json'
        if not releases.exists():
            releases = base.parent / 'scripts/local-cd/frozen-releases.json'
    else:
        contract = base.parent / 'protocol/ci-workload.json'
        releases = base.parent / 'protocol/frozen-releases.json'
    return (json.loads(contract.read_text(encoding='utf-8')),
            json.loads(releases.read_text(encoding='utf-8')))


def plan(contract):
    return ([(name, '.', argv) for name, argv in contract['backend'].items()]
            + [('frontend-' + str(i), 'web', argv) for i, argv in enumerate(contract['frontend'])])


def verify_go_results(output, expected):
    events = [json.loads(line) for line in output.splitlines() if line.strip()]
    passed = {e['Test'] for e in events if e.get('Action') == 'pass' and 'Test' in e}
    if not set(expected).issubset(passed):
        raise ValueError('Required tests did not pass (missing/skipped): ' + str(sorted(set(expected) - passed)))
    if any(e.get('Action') == 'fail' for e in events):
        raise ValueError('Go test emitted failure')


def run_go(argv, cwd, env):
    """Stream raw events immediately so interrupted Actions runs retain progress."""
    lines = []
    with subprocess.Popen(argv, cwd=cwd, env=env, text=True,
                          stdout=subprocess.PIPE) as process:
        for line in process.stdout:
            print(line, end='', flush=True)
            lines.append(line)
        if process.wait():
            raise subprocess.CalledProcessError(process.returncode, argv)
    return ''.join(lines)


def execute(source, release_sha, contract, releases):
    if sys.platform != 'linux':
        raise ValueError('Use a disposable Linux checkout with the pinned CI toolchain')
    source = Path(source).resolve()
    def git(*args):
        return subprocess.check_output(['git', '-C', str(source), *args], text=True).strip()
    selected = [r for r in releases['releases'].values() if r['application_sha'] == release_sha]
    if len(selected) != 1 or git('rev-parse', 'HEAD') != release_sha:
        raise ValueError('Source must be an exact frozen application revision')
    if git('rev-parse', 'HEAD^{tree}') != selected[0]['tree'] or git('status', '--porcelain'):
        raise ValueError('Source tree differs or checkout is not clean')
    if contract['driver'] != 'sqlite' or os.environ.get('DRIVER', 'sqlite') != 'sqlite':
        raise ValueError('Only SQLite is in this experimental scope')
    for name in ('GOFLAGS', 'SKIP_CONTAINER_TESTS'):
        if os.environ.get(name):
            raise ValueError('Unset ' + name + '; do not silently change the workload')
    for argv, expected in [(['go', 'version'], 'go' + contract['go_version'] + ' '),
                           (['node', '--version'], 'v' + contract['node_version'] + '.'),
                           (['pnpm', '--version'], contract['pnpm_version'])]:
        if expected not in subprocess.check_output(argv, text=True):
            raise ValueError('Wrong toolchain: ' + argv[0])
    env = dict(os.environ, DRIVER='sqlite')
    for name, cwd, argv in plan(contract):
        print('RUN ' + name + ': ' + json.dumps(argv), flush=True)
        if name in contract['backend']:
            output = run_go(argv, source/cwd, env)
            verify_go_results(output, contract['required_tests'][name])
        else:
            subprocess.run(argv, cwd=source/cwd, env=env, check=True)
    if git('diff', '--name-only'):
        raise ValueError('Validation modified tracked application source')
    print('CANDIDATE_VALIDATION_PASS: ' + contract['id'] + '; ' + release_sha)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--release-sha', required=True)
    args = parser.parse_args()
    execute(args.source, args.release_sha, *documents())


if __name__ == '__main__':
    main()
