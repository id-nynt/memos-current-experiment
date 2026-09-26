"""Pure paired-harness rules. No deployment, network, or controller actions."""
import hashlib
import json
import time
from pathlib import Path
from datetime import datetime


def contract():
    return json.loads(Path(__file__).with_name('rq1-s4r-s5r.json').read_text())


def digest():
    return hashlib.sha256(Path(__file__).with_name('rq1-s4r-s5r.json').read_bytes()).hexdigest()


def revised(scenario):
    return scenario in contract()['scenarios']


def elapsed(schedule):
    # Host and Linux containers share CLOCK_MONOTONIC. A reboot is invalid,
    # never permission to restart a measured schedule.
    if schedule.get('boot_id') != boot_id():
        raise ValueError('Schedule host rebooted; preserve and reconcile')
    value = time.monotonic() - schedule['start_monotonic']
    if value < 0:
        raise ValueError('Schedule clock invalid; preserve and reconcile')
    return value


def boot_id():
    path = Path('/proc/sys/kernel/random/boot_id')
    return path.read_text().strip() if path.exists() else 'offline-non-linux'


def create(scenario, expected, trial_id, start_epoch, start_monotonic):
    c = contract()
    if expected['environment'] != 'production' or expected['release_sha'] != c['v2'] or expected['image_id'] != c['v2_image']:
        raise ValueError('Paired target must be frozen production v2')
    spec = c['scenarios'][scenario]
    return dict(scenario=scenario, contract_sha256=digest(), owner='operator-harness',
                trial_id=trial_id, campaign_id=expected['trial_id'],
                deployment_id=expected['deploymentRunId'], project=expected['project'],
                release_sha=c['v2'], image_id=c['v2_image'], start_epoch=start_epoch,
                start_monotonic=start_monotonic, boot_id=boot_id(), end_epoch=start_epoch+spec['expiry_seconds'],
                duration_seconds=spec['expiry_seconds'],
                fault_intervals_seconds=spec['fault_intervals_seconds'])


def matches(schedule, identity):
    return (schedule['contract_sha256'] == digest()
            and identity['environment'] == 'production'
            and identity['trial_id'] == schedule['campaign_id']
            and identity['project'] == schedule['project']
            and identity['release_sha'] == schedule['release_sha']
            and identity['image_id'] == schedule['image_id'])


def active(schedule, identity, seconds=None):
    t = elapsed(schedule) if seconds is None else seconds
    return matches(schedule, identity) and any(a <= t < b for a, b in schedule['fault_intervals_seconds'])


def clearance_allowed(schedule, seconds=None):
    t = elapsed(schedule) if seconds is None else seconds
    return t >= schedule['duration_seconds']


def worker_guard(schedule, previous, requested_sha, campaign_id):
    """Workers may validate ownership, never remove or reset schedule state."""
    c = contract()
    if (schedule['contract_sha256'] != digest() or previous['project'] != schedule['project']
            or previous['trial_id'] != schedule['campaign_id'] or campaign_id != schedule['campaign_id']):
        raise ValueError('Foreign paired schedule')
    if requested_sha not in (c['v1'], c['v2']):
        raise ValueError('Unexpected requested release')


def opportunity(t0, terminal, native_samples, scenario):
    """Classify delivered native samples, not passive observations or GUI life."""
    if scenario != 'S5R':
        return {'classification': 'not_applicable'}
    if t0 is None or terminal is None:
        return {'classification': 'unknown', 'reason': 'missing activation or native terminal timestamp'}
    def seconds(value):
        return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    end = seconds(terminal)
    samples = [s for s in native_samples if t0+70 <= seconds(s['timestamp']) < min(t0+190, end)]
    delivered = [s for s in samples if s.get('event') == 'telemetry_measurement']
    prior = [s for s in native_samples if t0+60 <= seconds(s['timestamp']) < t0+70
             and s.get('event') == 'telemetry_measurement' and s.get('data_status') == 'fresh'
             and s.get('error_rate') is not None and s['error_rate'] <= .05]
    changed = [s for s in delivered if s.get('data_status') == 'fresh'
               and s.get('error_rate') is not None and s['error_rate'] > .05]
    return {'classification': 'native_telemetry_delivered_during_relapse' if delivered else
            ('native_probe_started_during_relapse' if samples else
            ('terminated_before_relapse' if end <= t0+70 else 'no_retained_native_observation_during_relapse')),
            'relapse_epoch': t0+70, 'terminal_epoch': end, 'native_samples': samples,
            'changed_evidence_received': True if prior and changed else None,
            'changed_evidence_note': 'Inspect retained values; probe-start alone does not prove receipt. No reconsideration inferred.',
            'note': 'A sample is an opportunity, not proof of reconsideration; inspect its values and decision trace.'}
