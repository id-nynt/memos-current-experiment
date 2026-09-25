"""External, clock-driven HTTP fixture; never consumes controller decisions.

The operator owns the proxy. A runner-only Docker CLI adapter changes production
port plumbing and synchronizes initial readiness before returning `compose up`.
All other Docker commands and all deployment policy remain untouched.
"""
import argparse
import datetime as dt
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PROJECT = 'memos-current-experiment-production'
PUBLIC_PORT = 5542
BACKEND_PORT = 5543
SCHEDULES = {'S3': [(0, 60)], 'S4': [(0, 900)], 'S5': [(0, 60), (120, 240)]}
HOP = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
       'te', 'trailer', 'transfer-encoding', 'upgrade', 'content-length'}


def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def atomic(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    # Windows readers can briefly hold a file without delete sharing. This is
    # fixture IPC only; these bounded retries never retry deployment operations.
    for attempt in range(3):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 2:
                raise
            time.sleep(.01)


def trial_directory(root, trial):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', trial):
        raise ValueError('Unsafe trial ID')
    base = (Path(root) / 'experiment/results').resolve()
    directory = (base / trial).resolve()
    if directory.parent != base:
        raise ValueError('Trial escapes results')
    return directory


def fault_active(scenario, elapsed, path, candidate):
    route = urlsplit(path).path
    return (candidate and (route == '/api/v1/memos' or route.startswith('/api/v1/memos/'))
            and any(start <= elapsed < end for start, end in SCHEDULES[scenario]))


def frozen_check(root=ROOT):
    import hashlib
    spec = read(Path(root) / 'experiment/frozen-control.json')
    for name, expected in spec['files'].items():
        actual = hashlib.sha256((Path(root) / name).read_bytes().replace(b'\r\n', b'\n')).hexdigest()
        if actual != expected:
            raise RuntimeError('Frozen controller changed: ' + name)
    return spec


class Fixture:
    def __init__(self, directory, scenario, config, sampler):
        self.directory = Path(directory)
        self.scenario = scenario
        self.config = config
        self.sampler = sampler
        self.started = None
        self.t0 = None
        self.error = None
        self.server = None
        self.stop = threading.Event()
        self.mutex = threading.Lock()
        self.thread = None

    def event(self, event, **fields):
        with self.mutex:
            with (self.directory / 'fault-events.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(dict(timestamp=stamp(), event=event, scenario=self.scenario, **fields)) + '\n')

    def arm(self):
        # Reserve only the alternate backend port; production is still v1 here.
        with socket.socket() as test:
            test.bind(('127.0.0.1', BACKEND_PORT))
        atomic(self.directory / 'fixture-arm.json', dict(scenario=self.scenario, trial_id=self.directory.name,
               control_sha=self.config['control_sha'], pid=os.getpid(), created_at=stamp(),
               public_port=PUBLIC_PORT, backend_port=BACKEND_PORT, schedule=SCHEDULES[self.scenario]))
        self.event('fixture_armed')
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        try:
            while not self.stop.wait(.05):
                atomic(self.directory / 'fixture-heartbeat.json', {'timestamp': stamp()})
                if (self.directory / 'fixture-up.json').exists():
                    break
            if self.stop.is_set():
                return
            fixture = self

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *_):
                    pass  # Never log Authorization, request bodies, or private memo IDs.

                def proxy(self):
                    status = 502
                    body = b'Fixture upstream unavailable'
                    headers = []
                    connection = None
                    try:
                        # Identity on each memo request keeps the rule release-scoped,
                        # including restarts. Never infer identity from controller events.
                        candidate = False
                        route = urlsplit(self.path).path
                        memo = route == '/api/v1/memos' or route.startswith('/api/v1/memos/')
                        if memo and fixture.started is not None:
                            identity = http.client.HTTPConnection('127.0.0.1', BACKEND_PORT, timeout=1)
                            try:
                                identity.request('GET', '/api/v1/instance/profile')
                                profile = json.loads(identity.getresponse().read())
                                candidate = profile.get('commit') == fixture.config['application_sha']
                            finally:
                                identity.close()
                        elapsed = time.monotonic() - fixture.started if fixture.started is not None else -1
                        if fault_active(fixture.scenario, elapsed, self.path, candidate):
                            status, body = 503, b'External experiment fixture'
                            fixture.event('injected_response', method=self.command, route='memo', elapsed_seconds=elapsed)
                        else:
                            length = int(self.headers.get('Content-Length', '0'))
                            if self.headers.get('Transfer-Encoding') or length > 16 * 1024 * 1024:
                                raise ValueError('Unsupported fixture request framing')
                            data = self.rfile.read(length) if length else None
                            forward = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
                            # Let the caller's original 3s/5s timeout win. The
                            # transport must not shorten a native probe budget.
                            connection = http.client.HTTPConnection('127.0.0.1', BACKEND_PORT, timeout=6)
                            connection.request(self.command, self.path, data, forward)
                            response = connection.getresponse()
                            status, body = response.status, response.read()
                            headers = [(k, v) for k, v in response.getheaders() if k.lower() not in HOP]
                    except Exception as exc:
                        fixture.event('proxy_error', error_type=type(exc).__name__)
                    finally:
                        if connection:
                            connection.close()
                    try:
                        self.send_response(status)
                        for name, value in headers:
                            self.send_header(name, value)
                        self.send_header('Content-Length', str(len(body)))
                        self.end_headers()
                        if self.command != 'HEAD':
                            self.wfile.write(body)
                    except (BrokenPipeError, ConnectionResetError):
                        pass

                do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = proxy

                def __getattr__(self, name):
                    if name.startswith('do_'):
                        return self.proxy
                    raise AttributeError(name)

            self.server = ThreadingHTTPServer(('127.0.0.1', PUBLIC_PORT), Handler)
            serving = threading.Thread(target=self.server.serve_forever, daemon=True)
            serving.start()
            # A fixture setup cap, not an additional controller retry policy. No
            # production acceptance code runs until this external boundary returns.
            deadline = time.monotonic() + 180
            while not self.stop.is_set() and time.monotonic() < deadline:
                atomic(self.directory / 'fixture-heartbeat.json', {'timestamp': stamp()})
                observation = self.sampler(self.config)
                if observation['healthy'] and observation['application_sha'] == self.config['application_sha']:
                    ready = stamp()
                    self.started = time.monotonic()
                    self.t0 = stamp()
                    self.event('fault_started', t0=self.t0, readiness=observation)
                    atomic(self.directory / 'fixture-start.json', dict(t0=self.t0, ready_at=ready,
                           monotonic_start=self.started, scenario=self.scenario))
                    break
                self.event('fixture_readiness', observation=observation)
                self.stop.wait(.1)
            if self.started is None:
                raise RuntimeError('Fixture initial candidate readiness not reached')
            boundaries = sorted({x for interval in SCHEDULES[self.scenario] for x in interval if x})
            while not self.stop.wait(.05):
                elapsed = time.monotonic() - self.started
                atomic(self.directory / 'fixture-heartbeat.json', {'timestamp': stamp()})
                while boundaries and elapsed >= boundaries[0]:
                    boundary = boundaries.pop(0)
                    self.event('fault_boundary', scheduled_seconds=boundary, elapsed_seconds=elapsed,
                               active=any(a <= elapsed < b for a, b in SCHEDULES[self.scenario]))
                if elapsed >= SCHEDULES[self.scenario][-1][1] and not (self.directory / 'fixture-expired.json').exists():
                    self.event('fault_ended', reason='fixed_schedule_expired')
                    atomic(self.directory / 'fixture-expired.json', {'timestamp': stamp()})
        except Exception as exc:
            self.error = str(exc)
            self.event('fixture_error', error_type=type(exc).__name__, message=str(exc))
            atomic(self.directory / 'fixture-error.json', {'timestamp': stamp(), 'error': str(exc)})

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=15)
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        self.event('fixture_closed', scheduled_expiry_reached=(self.directory / 'fixture-expired.json').exists())


def adapted_arguments(arguments, override):
    """Only alter the exact production up command; inspect output stays real."""
    target = (len(arguments) > 4 and arguments[0] == 'compose'
              and '--project-name' in arguments
              and arguments[arguments.index('--project-name') + 1] == PROJECT
              and 'up' in arguments)
    if target:
        if arguments[-6:] != ['up', '-d', '--no-build', '--pull', 'never', 'memos']:
            raise RuntimeError('Unexpected production up command; fixture refuses adaptation')
        arguments = [arguments[0], '--file', arguments[arguments.index('--file') + 1],
                     '--file', str(override)] + arguments[arguments.index('--project-name'):]
    return arguments, target


def docker_adapter(arguments):
    directory = Path(os.environ['MEMOS_FIXTURE_DIRECTORY'])
    arguments, target = adapted_arguments(arguments, HERE / 'runtime-port.yaml')
    code = subprocess.run([os.environ['MEMOS_REAL_DOCKER'], *arguments]).returncode
    if code or not target:
        return code
    atomic(directory / 'fixture-up.json', {'timestamp': stamp()})
    deadline = time.monotonic() + 185
    while time.monotonic() < deadline:
        if (directory / 'fixture-error.json').exists():
            raise RuntimeError('External fixture failed; trial is invalid')
        if (directory / 'fixture-start.json').exists():
            start = read(directory / 'fixture-start.json')
            released = stamp()
            latency = (dt.datetime.fromisoformat(released) - dt.datetime.fromisoformat(start['ready_at'])).total_seconds()
            atomic(directory / 'fixture-hook.json', {'released_at': released, 'synchronization_seconds': latency})
            if not 0 <= latency <= 2:
                raise RuntimeError('Fixture synchronization exceeded two seconds')
            return 0
        heartbeat = read(directory / 'fixture-heartbeat.json')
        if (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(heartbeat['timestamp'])).total_seconds() > 15:
            raise RuntimeError('External fixture observer disconnected')
        time.sleep(.05)
    raise RuntimeError('External fixture hook timed out')


def runner():
    frozen_check()
    scenario = os.environ['SCENARIO']
    environment = dict(os.environ)
    native_scenario = scenario
    if scenario in SCHEDULES:
        if os.environ['RELEASE'] != 'v2':
            raise RuntimeError('Runtime faults require v2')
        home = Path(os.environ['MEMOS_EXPERIMENT_ROOT']).resolve()
        directory = trial_directory(home, os.environ['TRIAL_ID'])
        arm = read(directory / 'fixture-arm.json')
        sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        if arm['scenario'] != scenario or arm['control_sha'] != sha or arm['trial_id'] != directory.name:
            raise RuntimeError('Fixture lease does not match workflow identity')
        heartbeat = read(directory / 'fixture-heartbeat.json')
        if (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(heartbeat['timestamp'])).total_seconds() > 15:
            raise RuntimeError('Fixture lease is stale')
        docker = shutil.which('docker.exe')
        if not docker:
            raise RuntimeError('Real Docker executable missing')
        shim = directory / 'docker-adapter'
        shim.mkdir(exist_ok=False)
        # Explicit quoted local paths; never interpolate workflow inputs in shell code.
        for value in (sys.executable, str(Path(__file__).resolve())):
            if any(c in value for c in '%!\r\n"'):
                raise ValueError('Unsupported adapter path')
        (shim / 'docker.cmd').write_text(f'@echo off\n"{sys.executable}" "{Path(__file__).resolve()}" docker %*\nexit /b %errorlevel%\n')
        environment.update(MEMOS_REAL_DOCKER=docker, MEMOS_FIXTURE_DIRECTORY=str(directory),
                           PATH=str(shim) + os.pathsep + environment['PATH'])
        native_scenario = 'S0'  # Controller is unaware of the external runtime fault.
    return subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
        str(ROOT / 'scripts/local-cd/deploy.ps1'), '-Experiment', '-Commit', os.environ['RELEASE_SHA'],
        '-FrozenRelease', os.environ['RELEASE'], '-TrialId', os.environ['TRIAL_ID'],
        '-Scenario', native_scenario], cwd=ROOT, env=environment).returncode


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'docker':
        raise SystemExit(docker_adapter(sys.argv[2:]))
    argparse.ArgumentParser(description=__doc__).parse_args()
    raise SystemExit(runner())
