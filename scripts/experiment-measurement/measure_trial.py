"""Passive, common evidence collector. Never selects, retries or repairs deployments."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import urllib.request


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def sample(config):
    result = {'timestamp': now(), 'healthy': False, 'application_sha': None, 'image_id': None}
    try:
        credential = read(config['credential_file'])
        def get(path, authorized=False):
            request = urllib.request.Request(config['production_url'] + path)
            if authorized:
                request.add_header('Authorization', 'Bearer ' + credential['token'])
            with urllib.request.urlopen(request, timeout=3) as response:
                return response.read()
        container = json.loads(subprocess.check_output(['docker', 'inspect', config['production_container']], timeout=5))[0]
        result['image_id'] = container['Image']
        profile = json.loads(get('/api/v1/instance/profile'))
        result.update(application_sha=profile.get('commit'), version=profile.get('version'), instance_url=profile.get('instanceUrl'))
        health = get('/healthz').decode().strip()
        sentinel = json.loads(get('/api/v1/' + credential['sentinel_name'], True))
        release = next((r for r in config['releases'].values() if r['application_sha'] == profile.get('commit')), None)
        result.update(application_sha=profile.get('commit'), image_id=container['Image'], version=profile.get('version'), instance_url=profile.get('instanceUrl'))
        result['healthy'] = bool(health == 'Service ready.' and container['State']['Running'] and release
                                 and release['image_id'] == container['Image'] and profile.get('version') == release['version']
                                 and profile.get('instanceUrl') == config['production_url']
                                 and sentinel.get('content') == credential['sentinel_content'])
    except Exception as exc:
        result['error_type'] = type(exc).__name__
    return result


def instant(value):
    return dt.datetime.fromisoformat(value.replace('Z', '+00:00'))


def events(directory, start):
    seen = set()
    for path in directory.rglob('*.jsonl'):
        if path.name == 'common-observations.jsonl':
            continue
        for line in path.read_text(encoding='utf-8-sig', errors='replace').splitlines():
            try: item = json.loads(line)
            except ValueError: continue
            stamp = item.get('timestamp')
            if not stamp: continue
            try:
                if instant(stamp) < instant(start): continue
            except ValueError: continue
            key = json.dumps(item, sort_keys=True)
            if key not in seen:
                seen.add(key)
                yield item


def summarize(config, directory, meta, samples):
    native = list(events(directory, meta['pipeline_start']))
    deployments = [e for e in native if e.get('environment') == 'production' and e.get('event') in ('deployment_start', 'deployment_end')]
    first_bad = next((s['timestamp'] for s in samples if not s['healthy']), None)
    faults = [e['timestamp'] for e in native if e.get('event') in ('injected_response', 'deterministic_failure')]
    if faults: first_bad = min(([first_bad] if first_bad else []) + faults, key=instant)
    recovered = next((s['timestamp'] for s in samples if s['healthy'] and (not first_bad or instant(s['timestamp']) > instant(first_bad))), None)
    final = samples[-1] if samples else {}
    runs = {}
    for path in directory.rglob('*.json'):
        try: item = read(path)
        except (ValueError, OSError): continue
        if isinstance(item, dict) and 'databaseId' in item and 'jobs' in item:
            runs[item['databaseId']] = item
    # A local operator execution really has zero GitHub runs; missing remote evidence is unknown.
    acknowledged = {int(e['github_run_id']) for e in native if e.get('event') == 'dispatch_acknowledged' and e.get('github_run_id')}
    acknowledged.update(config.get('github_run_ids', []))
    remote_complete = config['execution_mode'] == 'local' or (bool(acknowledged) and acknowledged == set(runs)
                         and all(r.get('status') == 'completed' for r in runs.values()))
    names = {e.get('event') for e in native}
    native_complete = ({'pipeline_start', 'pipeline_end'} <= names if config['approach'] == 'conventional'
                       else {'controller_started', 'controller_finished'} <= names)
    retries = sum(e.get('event') == 'entity_execution_started' and int(e.get('attempt', 1)) > 1 for e in native)
    reobservations = sum(e.get('event') in ('telemetry_measurement', 'health_observation') and e.get('round', 1) > 1 for e in native)
    executed = 'rollback_executed' in names or any(e.get('event') == 'entity_execution_started' and e.get('entity') == 'rollback' for e in native)
    interventions = read(directory / 'human-interventions.json') if (directory / 'human-interventions.json').exists() else None
    return {
        'contract_version': 1, 'approach': config['approach'], 'scenario': config['scenario'], 'trial_id': config['trial_id'],
        'control_sha': config['control_sha'], 'application_sha': config['application_sha'], 'image_identity': config['image_identity'],
        'pipeline_start': meta['pipeline_start'], 'pipeline_end': meta['pipeline_end'],
        'deployment_start': min((e['timestamp'] for e in deployments if e['event'] == 'deployment_start'), key=instant, default=None),
        'deployment_end': max((e['timestamp'] for e in deployments if e['event'] == 'deployment_end'), key=instant, default=None),
        'first_fault_unhealthy_time': first_bad, 'first_recovered_healthy_time': recovered,
        'final_health': final.get('healthy'),
        'final_deployed_release': {'application_sha': final.get('application_sha'), 'image_identity': final.get('image_id')},
        'candidate_delivered': (bool(final.get('healthy') and final.get('application_sha') == config['application_sha']
                                    and final.get('image_id') == config['image_identity']) if samples else None),
        'retry_count': retries if native_complete else None, 'reobservation_count': reobservations if native_complete else None,
        'recovery_rollback_selected': True if 'rollback_selected' in names else (False if native_complete else None),
        'recovery_rollback_executed': True if executed else (False if native_complete else None),
        'github_workflow_count': len(runs) if remote_complete else None,
        'github_job_count': sum(bool(j.get('startedAt')) and j.get('conclusion') != 'skipped' for r in runs.values() for j in r['jobs']) if remote_complete else None,
        'human_intervention': interventions, 'github_run_ids': sorted(runs),
        'execution_mode': config['execution_mode'], 'controller_exit_code': meta['exit_code'],
        'evidence_complete': remote_complete and native_complete and interventions is not None and bool(samples),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--no-interventions', action='store_true', help='Operator attests no post-start manual action; launch/preparation are excluded')
    args = parser.parse_args()
    config = read(args.config)
    if config['approach'] not in ('conventional', 'bdi') or config['execution_mode'] not in ('local', 'github'):
        raise ValueError('Explicit approach and execution mode required')
    directory = Path(args.output).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    pointer = directory/'runtime-pointer.txt'
    env = dict(os.environ, LOCAL_CD_EVIDENCE_POINTER=str(pointer))
    meta = {'pipeline_start': now(), 'pipeline_end': None, 'exit_code': None}
    save(directory/'launch.json', {'config': config, **meta})
    samples = []
    with (directory/'controller.log').open('w') as log, (directory/'common-observations.jsonl').open('w') as stream:
        process = subprocess.Popen(config['command'], cwd=config.get('cwd'), env=env, stdout=log, stderr=subprocess.STDOUT)
        while True:
            observation = sample(config)
            samples.append(observation)
            stream.write(json.dumps(observation)+'\n'); stream.flush()
            if process.poll() is not None: break
            time.sleep(2)
        meta.update(pipeline_end=now(), exit_code=process.returncode)
    if pointer.exists():
        source = Path(pointer.read_text(encoding='utf-8-sig').strip())
        for name in ('native-events.jsonl', 'release.json'):
            shutil.copyfile(source/name, directory/name)
    if config.get('native_directory'):
        # Copy evidence only. Never copy private state or credentials into results.
        if Path(config['native_directory']).exists():
            shutil.copytree(config['native_directory'], directory/'native')
    if args.no_interventions: save(directory/'human-interventions.json', [])
    save(directory/'launch.json', {'config': config, **meta})
    result = summarize(config, directory, meta, samples)
    save(directory/'common-measurement.json', result)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['candidate_delivered'] and result['evidence_complete'] and meta['exit_code'] == 0 else 1)


if __name__ == '__main__': main()
