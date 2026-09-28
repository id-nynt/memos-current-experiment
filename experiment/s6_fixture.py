"""S6 one-request HTTP dependency outage; identical in both treatments.

Only loopback is used. Consuming the first request clears the fault, regardless
of any subsequent controller decision. A diagnostic request proves clearance
but never changes the result of the original test request.
"""
import datetime
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import re
import threading
import urllib.error
import urllib.request


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def write_new(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def run_fixture(state, evidence, identity):
    """Return measured outcome; refuse replay, foreign state and missing attempt 1."""
    required = {'scenario', 'campaign_id', 'release_sha', 'entity', 'attempt',
                'execution_id', 'github_run_id', 'github_run_attempt', 'control_sha'}
    if set(identity) != required or identity['scenario'] not in ('S6', 'CI01') or identity['entity'] != 'test':
        raise ValueError('Invalid S6 identity')
    if identity['attempt'] not in (1, 2) or identity['github_run_attempt'] != 1:
        raise ValueError('Only native attempts 1/2; GitHub manual reruns are invalid')
    for key in ('campaign_id', 'execution_id', 'github_run_id'):
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,120}', str(identity[key])):
            raise ValueError('Invalid identity: ' + key)
    for key in ('release_sha', 'control_sha'):
        if not re.fullmatch(r'[0-9a-f]{40}', identity[key]):
            raise ValueError('Expected immutable SHA: ' + key)
    state, evidence = Path(state), Path(evidence)
    state.mkdir(parents=True, exist_ok=True)
    evidence.mkdir(parents=True, exist_ok=True)
    # An interrupted fixture leaves this guard: never manufacture a fresh outage.
    lock = state / 'fixture.lock'
    with lock.open('x', encoding='utf-8') as stream:
        stream.write(identity['execution_id'])
    complete = False
    try:
        consumed = state / 'consumed.json'
        previous = None
        if identity['attempt'] == 1:
            if consumed.exists():
                raise ValueError('First request already consumed; no replay')
        else:
            previous = json.loads((state / 'attempt-1.json').read_text())
            first = previous['identity']
            if any(first[k] != identity[k] for k in ('scenario', 'campaign_id', 'release_sha', 'entity', 'control_sha')):
                raise ValueError('Previous attempt belongs to another trial/release/control')
            if (previous['primary_status'] != 503 or previous['clearance_status'] != 200
                    or not consumed.exists() or first['execution_id'] == identity['execution_id']
                    or first['github_run_id'] == identity['github_run_id']):
                raise ValueError('Missing genuine first failure/clearance or new execution')
            if json.loads(consumed.read_text())['identity'] != first:
                raise ValueError('Consumed state identity mismatch')
        claim = state / ('attempt-' + str(identity['attempt']) + '.claim')
        write_new(claim, identity)
        events = []
        failures = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                try:
                    if self.path != '/dependency':
                        self.send_error(404)
                        return
                    status = 200
                    if not consumed.exists():
                        status = 503
                        write_new(consumed, {'identity': identity, 'cleared_at': now(),
                                            'cause': 'first dependency request consumed'})
                    events.append({'timestamp': now(), 'event': 'dependency_response',
                                   'status': status, 'request_number': len(events) + 1})
                    body = json.dumps({'available': status == 200}).encode()
                    self.send_response(status)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except Exception as error:
                    failures.append(type(error).__name__)
                    self.close_connection = True

        def probe(url):
            # Ignore host proxy configuration; fixture traffic must stay local.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            try:
                response = opener.open(url, timeout=5)
            except urllib.error.HTTPError as response_error:
                response = response_error
            with response:
                status, body = response.code, json.load(response)
            if status not in (200, 503) or body != {'available': status == 200}:
                raise ValueError('Unexpected dependency response')
            return status

        with HTTPServer(('127.0.0.1', 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                url = 'http://127.0.0.1:' + str(server.server_port) + '/dependency'
                primary = probe(url)
                clearance = probe(url)  # evidence only; not a test retry
            finally:
                server.shutdown()
                thread.join(timeout=5)
        if failures or primary != (503 if identity['attempt'] == 1 else 200) or clearance != 200:
            raise ValueError('Fixture failed its exposure/clearance contract')
        record = {'schema_version': 1, 'identity': identity, 'primary_status': primary,
                  'clearance_status': clearance, 'responses': events,
                  'consumed': json.loads(consumed.read_text()),
                  'previous_receipt_sha256': hashlib.sha256((state / 'attempt-1.json').read_bytes()).hexdigest()
                      if previous else None,
                  'result': 'transient_failure' if primary == 503 else 'success'}
        write_new(state / ('attempt-' + str(identity['attempt']) + '.json'), record)
        write_new(evidence / 's6-receipt.json', record)
        with (evidence / 'fault-events.jsonl').open('a', encoding='utf-8') as stream:
            for event in (
                {'event': 'transient_dependency_failure' if primary == 503 else 'transient_dependency_passed',
                 'http_status': primary},
                {'event': 'transient_condition_cleared', 'http_status': clearance}):
                stream.write(json.dumps({'timestamp': now(), **identity, **event}) + '\n')
        complete = True
        return record
    finally:
        if complete:
            lock.unlink()


def publish_output(record, output):
    """Called only after a fully verified local receipt has been written."""
    with Path(output).open('a', encoding='utf-8') as stream:
        stream.write('result=' + record['result'] + '\n')


def conventional_main():
    import os
    identity = dict(scenario=os.environ.get('SCENARIO', 'S6'), campaign_id=os.environ['TRIAL_ID'], entity='test', attempt=1,
                    execution_id='conventional-' + os.environ['GITHUB_RUN_ID'],
                    github_run_id=os.environ['GITHUB_RUN_ID'],
                    github_run_attempt=int(os.environ['GITHUB_RUN_ATTEMPT']),
                    release_sha=os.environ['RELEASE_SHA'], control_sha=os.environ['GITHUB_SHA'])
    record = run_fixture(Path(os.environ['RUNNER_TEMP']) / ('s6-' + identity['campaign_id']),
                         Path('s6-evidence'), identity)
    publish_output(record, os.environ['GITHUB_OUTPUT'])


if __name__ == '__main__':
    conventional_main()
