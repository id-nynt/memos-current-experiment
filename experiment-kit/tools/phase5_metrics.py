"""Read-only Phase 5 normalizer. Explicit case/window specification; JSON to stdout.

No experiment imports, network, subprocesses, mutation, or inferred timing policy.
Usage: python -B tools/phase5_metrics.py case SPEC.json
       python -B tools/phase5_metrics.py aggregate RESULT.json ...
"""
import image_identity as images_identity
from job_events import normalize as normalize_job
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import statistics

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / 'protocol/measurement-contract-v2.json'


def stamp(value):
    """Preserve Java/PowerShell sub-microsecond ordering; reject naive clocks."""
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Timezone required')
    fraction = re.search(r'T\d\d:\d\d:\d\d(?:\.(\d+))?', value)
    if not fraction:
        raise ValueError('ISO timestamp required')
    return Decimal(int(parsed.replace(microsecond=0).timestamp())) + Decimal('0.' + (fraction[1] or '0'))


def iso(seconds):
    return datetime.fromtimestamp(float(seconds), timezone.utc).isoformat()


def duration(start, end):
    if start is None or end is None:
        return None
    result = stamp(end) - stamp(start)
    return float(result) if result >= 0 else None


class Evidence:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.hashes = {}
        self.missing = []

    def read(self, name, lines=False, required=False):
        path = (self.root / name).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError('Evidence path escapes candidate directory')
        if not path.is_file():
            if required:
                self.missing.append(name)
            return [] if lines else None
        raw = path.read_bytes()
        self.hashes[name] = hashlib.sha256(raw).hexdigest()
        text = raw.decode('utf-8-sig')
        return [json.loads(line) for line in text.splitlines() if line.strip()] if lines else json.loads(text)


def request(row, arm):
    """Normalize historical vocabulary conservatively; never guess transport subtype."""
    status = row.get('status')
    valid = row.get('response_valid')
    matches = row.get('content_matches')
    if row.get('measurement_version') == 2:
        success = status == 200 and valid is True and matches is True
        category = row.get('failure_category') if not success else None
        if not success and not category:
            category = 'unknown'
    else:
        success = status == 200 and (matches is True if arm == 'conventional' else row.get('success') is True)
        if success:
            category = None
        elif status is not None and status != 200:
            category = 'http_5xx' if 500 <= status < 600 else 'http_4xx' if 400 <= status < 500 else 'unexpected_http_status'
        elif row.get('error_type') == 'JSONDecodeError':
            category = 'invalid_response'
        elif status == 200 and (matches is False or row.get('success') is False):
            category = 'content_mismatch'
        else:
            category = 'unknown'
    seconds = row.get('duration_seconds', row.get('latency_ms', 0) / 1000)
    if seconds < 0:
        raise ValueError('Negative request duration')
    start = row.get('request_started_at')
    end = row.get('request_completed_at')
    quality = 'explicit'
    if start is None:
        quality = 'historical_start' if arm == 'conventional' else 'estimated_from_completion'
        value = stamp(row['timestamp'])
        start = iso(value if arm == 'conventional' else value - Decimal(str(seconds)))
        end = iso(value + Decimal(str(seconds)) if arm == 'conventional' else value)
    if end is None or duration(start, end) is None:
        raise ValueError('Incomplete or reversed request')
    return dict(start=start, end=end, seconds=seconds, status=status, success=success,
                failure_category=category, timestamp_quality=quality)


def health(row):
    if row.get('measurement_error') is True:
        return None
    # Old catches combine Docker, credential and network failures: cannot disambiguate.
    if (row.get('measurement_version') != 2 and row.get('error_type') and
            row['error_type'] not in ('HTTPError', 'URLError', 'JSONDecodeError', 'TimeoutError', 'ConnectionRefusedError', 'ConnectionResetError')):
        return None
    return row.get('healthy') if isinstance(row.get('healthy'), bool) else None


def service_state(row, releases):
    good = health(row)
    sha = row.get('application_sha', row.get('release_sha'))
    release = next((name for name, value in releases.items()
                    if value['application_sha'] == sha and images_identity.matches(value, row.get('image_id'))), None)
    return ('healthy_' + release) if good is True and release else 'unhealthy' if good is False else 'unknown'


def availability(samples, start, end, maximum_gap, minimum_coverage):
    totals = {True: 0., False: 0., None: 0.}
    covered = 0.
    for left, right in zip(samples, samples[1:]):
        a, b = stamp(left['timestamp']), stamp(right['timestamp'])
        seconds = float(max(Decimal(0), min(end, b) - max(start, a)))
        if 0 < b-a <= Decimal(str(maximum_gap)):
            state = health(left)
            totals[state] += seconds
            if state is not None:
                covered += seconds
    total = float(end-start)
    coverage = covered/total
    return dict(healthy_seconds_estimate=totals[True], unhealthy_seconds_estimate=totals[False],
                unknown_seconds=max(0., total-covered), coverage=coverage,
                availability_estimate=totals[True]/total if coverage >= minimum_coverage else None,
                downtime_ratio_estimate=totals[False]/total if coverage >= minimum_coverage else None)


def stable_recovery(samples, after, end, rule):
    sequence = []
    onset = confirmation = None
    relapse = False
    for row in samples:
        t = stamp(row['timestamp'])
        if not after <= t <= end:
            continue
        if health(row) is not True:
            if confirmation and health(row) is False:
                relapse = True
            sequence = []
            continue
        if sequence and t-stamp(sequence[-1]['timestamp']) > Decimal(str(rule['maximum_gap_seconds'])):
            sequence = []
        sequence.append(row)
        if (onset is None and len(sequence) >= rule['minimum_samples']
                and t-stamp(sequence[0]['timestamp']) >= Decimal(str(rule['minimum_span_seconds']))):
            onset, confirmation = sequence[0]['timestamp'], row['timestamp']
    return onset, confirmation, relapse


def native_case(evidence, arm, releases):
    boundaries = evidence.read('measurement-boundaries.json') or {}
    if boundaries and boundaries.get('role') != 'candidate':
        raise ValueError('Non-candidate measurement boundaries')
    if arm == 'bdi':
        trial = evidence.read('trial.json', required=True)
        if not trial or trial.get('mode') != 'candidate' or trial.get('application_sha') != releases['v2']['application_sha']:
            raise ValueError('Expected genuine v2 candidate, not qualification/reset/setup')
        manifest = evidence.read('controller/generation-manifest.json', required=True) or {}
        result = evidence.read('controller/controller-result.json', required=True) or {}
        if result and result.get('campaign_id') != manifest.get('campaign_id'):
            raise ValueError('Controller campaign mismatch')
        if result.get('release_sha') and result['release_sha'] != releases['v2']['application_sha']:
            raise ValueError('Controller candidate release mismatch')
        events = [normalize_job(e) for e in evidence.read('controller/controller-journal.jsonl', lines=True, required=True)]
        starts = [e for e in events if e.get('event') == 'controller_started']
        ends = [e for e in events if e.get('event') == 'controller_finished']
        complete = len(starts) == len(ends) == 1 and bool(result)
        first = starts[0]['timestamp'] if len(starts) == 1 else None
        last = ends[0]['timestamp'] if len(ends) == 1 else None
        if complete and (duration(first, last) is None or result.get('outcome') != ends[0].get('outcome')):
            raise ValueError('Inconsistent native terminal evidence')
        launch = boundaries.get('candidate_launch_at') or trial.get('started_at')
        quality = 'explicit_host_utc' if boundaries else 'historical_trial_start_proxy'
        outcome = result.get('outcome')
        ids = {int(e['github_run_id']) for e in events if e.get('event') == 'dispatch_acknowledged' and e.get('github_run_id')}
        runs = []
        for path in sorted(evidence.root.glob('github-*/*.json')):
            value = evidence.read(path.relative_to(evidence.root).as_posix())
            if isinstance(value, dict) and value.get('databaseId') in ids:
                runs.append(value)
        control, trial_id = trial.get('control_sha'), trial['trial_id']
    else:
        manifest = evidence.read('manifest.json', required=True) or {}
        config = manifest.get('config', {})
        if config.get('application_sha') != releases['v2']['application_sha'] or config.get('approach') != 'conventional':
            raise ValueError('Expected conventional v2 candidate manifest')
        meta = evidence.read('launch.json', required=True) or {}
        run = evidence.read('github/run.json', required=True) or {}
        dispatch = evidence.read('dispatch.json', required=True) or {}
        if run and (run.get('databaseId') != dispatch.get('github_run_id') or run.get('headSha') != config.get('control_sha')):
            raise ValueError('Uncorrelated conventional workflow')
        events = evidence.read('native-events.jsonl', lines=True)
        trial_id, control = config.get('trial_id'), config.get('control_sha')
        if any(e.get('trial_id') != trial_id for e in events):
            raise ValueError('Foreign native event')
        launch = boundaries.get('candidate_launch_at') or meta.get('pipeline_start')
        last = meta.get('native_terminal') if run.get('status') == 'completed' else None
        # Never substitute the deployment-script start for complete CI/CD execution.
        first = run.get('startedAt')
        complete = bool(last and run.get('conclusion'))
        outcome = run.get('conclusion')
        quality = 'explicit_launch_cross_clock_terminal_proxy' if boundaries else 'historical_launch_cross_clock_terminal_proxy'
        runs = [run] if run else []
        ids = {run['databaseId']} if run else set()
    if launch and last and duration(launch, last) is None:
        raise ValueError('Negative candidate duration')
    # Native events outside the terminal boundary never become action cost/detection.
    accepted = [e for e in events if complete and launch and stamp(launch) <= stamp(e['timestamp']) <= stamp(last)]
    if arm == 'bdi':
        ids = {int(e['github_run_id']) for e in accepted if e.get('event') == 'dispatch_acknowledged' and e.get('github_run_id')}
        runs = [r for r in runs if r['databaseId'] in ids]
    if any(r.get('headSha') and r['headSha'] != control for r in runs):
        raise ValueError('Workflow control SHA mismatch')
    all_jobs = evidence.read('github/jobs-all-attempts.json') if arm == 'conventional' else None
    if all_jobs is not None and any(j.get('run_id') not in ids for j in all_jobs):
        raise ValueError('Foreign all-attempt job evidence')
    return dict(trial_id=trial_id, control_sha=control, outcome=outcome, complete=complete,
                launch=launch, terminal=last, native_start=first, duration_quality=quality,
                campaign_id=manifest.get('campaign_id') if arm == 'bdi' else trial_id,
                reset_reference=trial.get('reset_receipt') if arm == 'bdi' else 'manifest.json#baseline',
                all_attempt_jobs=all_jobs,
                events=accepted, runs=runs, run_ids=ids, excluded_events=len(events)-len(accepted))


def action_counts(native, arm):
    if not native['complete']:
        return {k: None for k in ('retries', 'deployment_attempts', 'rollbacks_started', 'native_check_cycles',
                                  'reobservations', 'dispatch_attempts', 'workflow_runs', 'started_jobs')}
    events = [normalize_job(e) for e in native['events']]
    starts = [e for e in events if e.get('event') == 'job_execution_started']
    runs = {r['databaseId']: r for r in native['runs']}
    remote_complete = bool(native['run_ids']) and set(runs) == native['run_ids'] and all(r.get('status') == 'completed' for r in runs.values())
    jobs = {}
    jobs_complete = remote_complete
    for run in runs.values():
        if 'jobs' not in run:
            jobs_complete = False
        for job in run.get('jobs', []):
            key = job.get('databaseId', job.get('id'))
            if key is None:
                jobs_complete = False
            elif job.get('startedAt', job.get('started_at')) and job.get('conclusion') != 'skipped':
                jobs[(run['databaseId'], key)] = job
    cycles = [e for e in events if e.get('event') in ('health_observation', 'telemetry_measurement')]
    # Conventional job retry absence cannot be inferred from deployment events.
    conventional_retries = None
    if remote_complete and native.get('all_attempt_jobs') is not None:
        started = {j['id']:j for j in native['all_attempt_jobs'] if j.get('started_at') and j.get('conclusion') != 'skipped'}
        rounds = Counter((j['run_id'],j.get('name'),j.get('run_attempt')) for j in started.values())
        if all(j.get('name') and j.get('run_attempt') for j in started.values()) and all(n==1 for n in rounds.values()):
            per_job = Counter((j['run_id'],j['name']) for j in started.values())
            conventional_retries = sum(n-1 for n in per_job.values())
    return dict(retries=sum(e.get('attempt', 1) > 1 for e in starts) if arm == 'bdi' else
                conventional_retries,
                deployment_attempts=sum(e.get('job') in ('staging', 'production', 'rollback') for e in starts) if arm == 'bdi' else
                sum(e.get('event') == 'deployment_start' for e in events),
                rollbacks_started=sum(e.get('job') == 'rollback' for e in starts) if arm == 'bdi' else 0,
                native_check_cycles=len(cycles), reobservations=sum(e.get('round', 1) > 1 for e in cycles),
                dispatch_attempts=sum(e.get('event') == 'dispatch_intent' for e in events) if arm == 'bdi' else None,
                workflow_runs=len(runs) if remote_complete else None, started_jobs=len(jobs) if jobs_complete else None)


def native_detection(event, fault):
    event = normalize_job(event)
    if event.get('event') == 'job_execution_finished':
        return event.get('status') in ('failure','failed','transient_failure','permanent_failure')
    if event.get('event') == 'health_observation':
        return event.get('healthy') is False
    if event.get('event') != 'telemetry_measurement':
        return False
    if fault.get('signal') == 'telemetry':
        return event.get('data_status') in ('unavailable','stale','missing')
    if event.get('data_status') != 'fresh':
        return False
    return (event.get('readiness') == 'not_ready' or
            (event.get('error_rate') or 0) > fault.get('native_error_threshold',.05) or
            (event.get('latency_p95_ms') or 0) > fault.get('native_latency_threshold_ms',500) or
            event.get('availability',1) < 1)


def episode_metrics(schedule, samples, native, end, rule):
    """One record per predetermined exposure; clearance is never controller recovery."""
    rows=[]
    episodes=schedule['spec']['episodes']
    for i,e in enumerate(episodes):
        onset=Decimal(str(schedule['start_epoch']))+Decimal(str(e['start']))
        limit=min(end,Decimal(str(schedule['start_epoch']))+Decimal(str(episodes[i+1]['start']))) if i+1<len(episodes) else end
        subset=[s for s in samples if onset <= stamp(s['timestamp']) < limit]
        bad=next((s for s in subset if health(s) is False),None)
        signal='telemetry' if e.get('mode')=='telemetry_missing' else 'service'
        detections=[x for x in native['events'] if onset<=stamp(x['timestamp'])<limit
                    and x.get('job',x.get('environment'))==schedule['target']['environment']
                    and native_detection(x,{'signal':signal})]
        restore=confirm=None
        if bad and signal=='service':
            restore,confirm,_=stable_recovery(subset,stamp(bad['timestamp']),limit,rule)
        fresh=next((x['timestamp'] for x in native['events'] if detections and stamp(detections[0]['timestamp'])<stamp(x['timestamp'])<limit
                    and x.get('event')=='telemetry_measurement' and x.get('job')==schedule['target']['environment']
                    and x.get('data_status')=='fresh'),None) if signal=='telemetry' else None
        rows.append(dict(episode_id=e['id'],environment=schedule['target']['environment'],signal=signal,
            impairment_at=iso(onset),scheduled_end_at=iso(Decimal(str(schedule['start_epoch']))+Decimal(str(e['end']))),
            scheduled_clearance_at=None if i+1<len(episodes) and episodes[i+1]['start']==e['end'] else iso(Decimal(str(schedule['start_epoch']))+Decimal(str(e['end']))),
            detection_at=detections[0]['timestamp'] if detections else None,
            independently_unhealthy_at=bad['timestamp'] if bad else None,
            recovery_onset=restore,recovery_confirmation=confirm,observability_restored_at=fresh,
            service_recovery_applicable=signal=='service',censored=bool(bad and not confirm and signal=='service'),
            censor_at=iso(limit),recovery_cause='unassigned; compare executed response with scheduled clearance'))
    return rows


def normalize(spec):
    if spec.get('role') != 'candidate' or spec.get('treatment') not in ('conventional', 'bdi'):
        raise ValueError('Only explicit candidate operations are eligible')
    arm = spec['treatment']
    window = spec['window']
    if not window.get('anchor') or not window.get('pair_key'):
        raise ValueError('Declared scenario window anchor/pair key required')
    start, end = stamp(window['start']), stamp(window['end'])
    if end <= start:
        raise ValueError('Positive window required')
    coverage = spec['coverage']
    if not 0 < coverage['minimum_fraction'] <= 1 or coverage['maximum_gap_seconds'] <= 0:
        raise ValueError('Explicit valid coverage policy required')
    for key in ('minimum_samples', 'minimum_span_seconds', 'maximum_gap_seconds'):
        if spec['stability'][key] <= 0:
            raise ValueError('Invalid stability policy')
    evidence = Evidence(spec['evidence_directory'])
    releases = json.loads((ROOT / 'protocol/frozen-releases.json').read_text())['releases']
    native = native_case(evidence, arm, releases)
    if spec.get('declaration') == 'prospective':
        if not spec.get('declared_at') or not native['launch'] or stamp(spec['declared_at']) > stamp(native['launch']):
            raise ValueError('Prospective window must be declared before candidate launch')
    requests = [request(row, arm) for row in evidence.read('workload.jsonl', lines=True, required=True)]
    if any(stamp(b['start']) < stamp(a['start']) for a, b in zip(requests, requests[1:])):
        raise ValueError('Request clock went backwards')
    selected = [r for r in requests if start <= stamp(r['start']) < end]
    samples = evidence.read('common-observations.jsonl', lines=True, required=True)
    measurement_errors = evidence.read('measurement-errors.jsonl', lines=True) if arm == 'bdi' else []
    error_record = evidence.read('measurement-errors.json') if arm == 'conventional' else None
    if error_record:
        measurement_errors.append(error_record)
    if any(stamp(b['timestamp']) <= stamp(a['timestamp']) for a, b in zip(samples, samples[1:])):
        raise ValueError('Duplicate or reversed health timestamps')
    statistics_health = availability(samples, start, end, coverage['maximum_gap_seconds'], coverage['minimum_fraction'])
    max_gap = Decimal(str(coverage['maximum_gap_seconds']))
    request_coverage = bool(selected and stamp(selected[0]['start'])-start <= max_gap and
                            end-stamp(selected[-1]['end']) <= max_gap and
                            all(stamp(b['start'])-stamp(a['end']) <= max_gap for a, b in zip(selected, selected[1:])))
    if measurement_errors:
        request_coverage = False
    counts = Counter(r['failure_category'] for r in selected if not r['success'])
    failed = sum(counts.values())
    endpoint_policy = spec['endpoint']
    endpoint_start = end-Decimal(str(endpoint_policy['window_seconds']))
    endpoint_samples = [s for s in samples if endpoint_start <= stamp(s['timestamp']) <= end]
    endpoint_ok = bool(len(endpoint_samples) >= endpoint_policy['minimum_samples'] and
                       stamp(endpoint_samples[0]['timestamp'])-endpoint_start <= Decimal(str(endpoint_policy['edge_tolerance_seconds'])) and
                       end-stamp(endpoint_samples[-1]['timestamp']) <= Decimal(str(endpoint_policy['edge_tolerance_seconds'])) and
                       all(stamp(b['timestamp'])-stamp(a['timestamp']) <= max_gap for a,b in zip(endpoint_samples, endpoint_samples[1:])))
    states = [service_state(s, releases) for s in endpoint_samples]
    endpoint_health = (all(s.startswith('healthy_') for s in states) if endpoint_ok and 'unknown' not in states else None)
    final_state = states[-1] if endpoint_ok and states else 'unknown'
    delivered = all(s == 'healthy_v2' for s in states) if endpoint_health is not None else None
    fault = spec.get('fault')
    detected = detection_time = recovery_onset = confirmation = recovery_time = cause = first_bad = None
    relapse = False
    fault_evidence = None
    if fault:
        # Explicit event selector binds claimed activation to retained evidence.
        stream = evidence.read(fault['source'], lines=True, required=True)
        matches = [e for e in stream if all(e.get(k) == v for k,v in fault['match'].items())]
        if len(matches) != 1:
            raise ValueError('Fault activation selector must resolve exactly once')
        fault_evidence = matches[0]
        if fault_evidence.get('campaign_id') and fault_evidence['campaign_id'] != native['campaign_id']:
            raise ValueError('Foreign fault campaign')
        if fault_evidence.get('release_sha') and fault_evidence['release_sha'] != releases['v2']['application_sha']:
            raise ValueError('Foreign fault release')
        fault_start = fault_evidence[fault.get('timestamp_field', 'timestamp')]
        if isinstance(fault_start, (float, int)):
            fault_start = iso(fault_start)
        t0 = stamp(fault_start)
        if not native['launch'] or not stamp(native['launch']) <= t0 < end:
            raise ValueError('Fault episode outside candidate/observation boundaries')
        entity = fault['entity']
        # These are delivered native observations, never the independent samples.
        detections = [e for e in native['events'] if stamp(e['timestamp']) >= t0 and
                      e.get('job', e.get('environment')) == entity and
                      native_detection(e, fault)]
        detection_time = detections[0]['timestamp'] if detections else None
        if arm == 'conventional' and fault.get('native_job_match'):
            jobs = evidence.read('github/jobs-all-attempts.json', required=True) or []
            failed_jobs = [j for j in jobs if j.get('run_id') in native['run_ids'] and
                           all(j.get(k) == v for k,v in fault['native_job_match'].items()) and
                           j.get('conclusion') == 'failure' and j.get('completed_at') and
                           t0 <= stamp(j['completed_at']) <= stamp(native['terminal'])]
            detection_time = min((j['completed_at'] for j in failed_jobs),key=stamp,default=detection_time)
        # Missing result-valued conventional checks do not prove absence of detection.
        detected = True if detection_time else False if native['complete'] and arm == 'bdi' else None
        recovery_onset, confirmation, relapse = stable_recovery(samples, t0, end, spec['stability']) if fault['kind'] == 'production' and fault.get('signal') != 'telemetry' else (None, None, False)
        # Require independently observed impairment; healthy v1 during CI failure is not restoration.
        bad = [s for s in samples if t0 <= stamp(s['timestamp']) <= end and health(s) is False]
        first_bad = bad[0]['timestamp'] if bad else None
        if not bad:
            recovery_onset = confirmation = None
        elif recovery_onset and stamp(recovery_onset) <= stamp(bad[0]['timestamp']):
            recovery_onset, confirmation, relapse = stable_recovery(samples, stamp(bad[0]['timestamp']), end, spec['stability'])
        if recovery_onset:
            recovery_time = duration(fault_start, recovery_onset)
            # No automatic causal credit: reviewers must inspect independent expiry/action evidence.
            cause = 'unknown'
    else:
        fault_start = None
    actions = [e for e in native['events'] if e.get('event') in ('bdi_recovery_decision', 'rollback_selected', 'rollback_cancelled') or
               e.get('event') == 'bdi_decision' and e.get('decision') in ('retry','rollback_committed','reconsider') or
               e.get('event') == 'job_execution_started' and (e.get('job') == 'rollback' or e.get('attempt', 1) > 1)]
    executed = [e for e in actions if e.get('event') == 'job_execution_started']
    selected_actions = [e for e in actions if e.get('event') in ('bdi_recovery_decision', 'rollback_selected') or
                        e.get('event') == 'bdi_decision' and e.get('decision') in ('retry','rollback_committed')]
    rollback_starts = [e for e in executed if e.get('job') == 'rollback']
    rollback_ends = [e for e in native['events'] if e.get('event') == 'job_execution_finished' and e.get('job') == 'rollback']
    rollback_success = None
    rollback_confirmed = None
    if rollback_starts:
        v1_samples = [dict(s, healthy=service_state(s,releases)=='healthy_v1') if health(s) is not None else s for s in samples]
        _, rollback_confirmed, _ = stable_recovery(v1_samples, stamp(rollback_starts[-1]['timestamp']), end, spec['stability'])
        if native['complete'] and rollback_ends:
            if rollback_ends[-1].get('status') in ('failure','failed','permanent_failure','transient_failure'):
                rollback_success = False
            elif rollback_ends[-1].get('status') == 'success' and rollback_confirmed:
                rollback_success = True
    recovery_applicable = bool(fault and fault['kind'] == 'production' and fault.get('signal') != 'telemetry')
    ci_recovered = None
    if fault and fault['kind'] == 'ci':
        retried = [e for e in native['events'] if e.get('event') == 'job_execution_finished' and
                   e.get('job') == fault['entity'] and e.get('attempt', 1) > 1 and
                   stamp(e['timestamp']) >= stamp(fault_start)]
        ci_recovered = any(e.get('status') == 'success' for e in retried) if native['complete'] and arm == 'bdi' else None
    # Fault owners may publish expiry: compare evidence, never infer recovery from reset.
    clearance = None
    if fault and fault.get('clearance'):
        selector = fault['clearance']
        records = evidence.read(selector['source'], lines=True, required=True)
        matched = [e for e in records if all(e.get(k) == v for k,v in selector['match'].items())]
        if len(matched) == 1:
            clearance = matched[0][selector.get('timestamp_field','timestamp')]
        elif len(matched) > 1:
            raise ValueError('Ambiguous fault clearance')
    if recovery_onset and clearance and stamp(clearance) <= stamp(recovery_onset):
        cause = 'scheduled_clearance_or_coincident_action'
    elif rollback_success and clearance and stamp(confirmation) < stamp(clearance):
        cause = 'verified_rollback_before_scheduled_clearance'
    costs = action_counts(native, arm)
    reasons = []
    if measurement_errors:
        reasons.append('independent_measurement_error')
    if evidence.missing:
        reasons.append('missing_evidence')
    if not native['complete']:
        reasons.append('native_terminal_incomplete')
    if costs['workflow_runs'] is None or costs['started_jobs'] is None:
        reasons.append('remote_execution_evidence_incomplete')
    if not request_coverage:
        reasons.append('request_coverage_incomplete')
    if not endpoint_ok:
        reasons.append('endpoint_coverage_incomplete')
    if spec.get('declaration') != 'prospective':
        reasons.append('historical_window_not_prospectively_declared')
    if native['duration_quality'].startswith('historical'):
        reasons.append('historical_launch_boundary_proxy')
    interventions = evidence.read('human-interventions.json')
    if interventions is None or isinstance(interventions, dict) and not interventions.get('attested_complete'):
        reasons.append('intervention_attestation_missing')
    policy_hash = hashlib.sha256(json.dumps({k: spec[k] for k in ('coverage','endpoint','stability')},sort_keys=True).encode()).hexdigest()
    phase7 = {}
    if spec.get('scenario_contract') == 'memos-phase7-v1':
        phase7['scenario_contract']='memos-phase7-v1'
        reset_state=evidence.read('reset-state.json',required=True)
        if (not reset_state or reset_state.get('data_semantics')!='shared-controlled-seed' or reset_state.get('verified') is not True
                or reset_state.get('application_sha')!=releases['v1']['application_sha'] or not images_identity.matches(releases['v1'],reset_state.get('image_id'))
                or not re.fullmatch('[a-f0-9]{64}',reset_state.get('archive_sha256',''))):
            raise ValueError('Phase 7 requires verified controlled seed evidence')
        phase7['controlled_seed_sha256']=reset_state['archive_sha256']
        schedule=evidence.read('scenario-schedule.json',required=True)
        if not schedule or schedule.get('version')!='memos-phase7-v1' or end-start!=300:
            raise ValueError('Phase 7 requires a sealed schedule and fixed 300-second window')
        if abs(start-Decimal(str(schedule['start_epoch'])))>Decimal('.000001'):
            raise ValueError('Measurement window must start at declared schedule activation')
        target=schedule['target']
        if target['release_sha']!=releases['v2']['application_sha'] or not images_identity.matches(releases['v2'],target['image_id']) or target['trial_id']!=native['trial_id'] and target['trial_id']!=native['campaign_id']:
            raise ValueError('Foreign scenario target')
        stage=target['environment']
        if stage not in ('staging','production'):raise ValueError('Foreign scenario environment')
        environment_samples=evidence.read('staging-observations.jsonl',lines=True,required=True) if stage=='staging' else samples
        phase7['episodes']=episode_metrics(schedule,environment_samples,native,end,spec['stability'])
        if stage=='staging':
            stage_requests=[request(row,arm) for row in evidence.read('staging-workload.jsonl',lines=True,required=True)]
            stage_requests=[r for r in stage_requests if start<=stamp(r['start'])<end]
            stage_coverage=bool(stage_requests and stamp(stage_requests[0]['start'])-start<=max_gap and end-stamp(stage_requests[-1]['start'])<=max_gap
                and all(stamp(b['start'])-stamp(a['start'])<=max_gap for a,b in zip(stage_requests,stage_requests[1:])))
            promotions=[e for e in native['events'] if e.get('job',e.get('environment'))=='production' and e.get('event') in ('job_execution_started','deployment_start')]
            phase7['staging']=dict(requests=len(stage_requests),failed=sum(not r['success'] for r in stage_requests),
                error_rate=sum(not r['success'] for r in stage_requests)/len(stage_requests) if stage_coverage else None,
                request_coverage_sufficient=stage_coverage,
                **availability(environment_samples,start,end,coverage['maximum_gap_seconds'],coverage['minimum_fraction']),
                production_reliability_unchanged=True,
                production_started=bool(promotions),
                production_started_during_fault=any(Decimal(str(schedule['start_epoch']))+Decimal(str(ep['start']))<=stamp(e['timestamp'])<Decimal(str(schedule['start_epoch']))+Decimal(str(ep['end'])) for e in promotions for ep in schedule['spec']['episodes']))
    if spec.get('measurement_extension') == 'memos-exact-count-v1':
        from exact_measurements import derive
        phase7['exact_count_measurement']=derive(evidence,spec,native,start,end,stamp,request)
    return {
        **phase7,
        'schema_version': 2,
        'identity': dict(case_id=spec['case_id'], scenario_family=spec['scenario_family'], parameters=spec.get('parameters', {}),
                         treatment=arm, trial_id=native['trial_id'], control_sha=native['control_sha'],
                         application_sha=releases['v2']['application_sha'], image_id=images_identity.frozen_digest(releases['v2']), frozen_oci_digest=images_identity.frozen_digest(releases['v2']),
                         pair_key=window['pair_key'], contract_sha256=hashlib.sha256(CONTRACT.read_bytes()).hexdigest()),
        'boundaries': dict(candidate_start=native['launch'], treatment_end=native['terminal'], window=window,
                           observation_start=requests[0]['start'] if requests else None,
                           observation_end=requests[-1]['end'] if requests else None,
                           duration_quality=native['duration_quality'], cross_clock_verified=spec.get('cross_clock_verified', False)),
        'reliability': dict(requests_total=len(selected), requests_successful=len(selected)-failed, requests_failed=failed,
                            failures_by_category=dict(counts), error_rate=failed/len(selected) if selected and request_coverage else None,
                            **statistics_health, endpoint_health=endpoint_health, endpoint_release=final_state,
                            endpoint_identity={k: endpoint_samples[-1].get(k) for k in ('application_sha','release_sha','image_id','frozen_oci_digest','runtime_image_id')} if endpoint_samples else None,
                            candidate_delivered=delivered, native_outcome=native['outcome'],
                            false_acceptance=(not endpoint_health) if native['outcome'] in ('success','achieved') and endpoint_health is not None else None),
        'resilience': dict(applicable=bool(fault), fault_start=fault_start, fault_exposed=bool(fault_evidence),
                           service_recovery_applicable=recovery_applicable, ci_retry_recovered=ci_recovered,
                           detected=detected, detection_at=detection_time,
                           detection_seconds=duration(fault_start, detection_time) if spec.get('cross_clock_verified') else None,
                           actions=actions, selected_responses=selected_actions, executed_responses=executed,
                           recovery_attempted=bool(executed) if native['complete'] else None,
                           recovery_started_at=executed[0]['timestamp'] if executed else None,
                           rollback_success=rollback_success, scheduled_clearance_at=clearance,
                           rollback_independent_confirmation=rollback_confirmed,
                           recovery_onset=recovery_onset, recovery_confirmation=confirmation,
                           first_independent_unhealthy_at=first_bad,
                           sampled_restoration_seconds=duration(first_bad, recovery_onset),
                           recovery_observed=True if confirmation else False if recovery_applicable and statistics_health['coverage'] >= coverage['minimum_fraction'] else None,
                           recovery_seconds=recovery_time if spec.get('cross_clock_verified') else None,
                           recovery_cause=cause, relapse_observed=relapse,
                           censored=bool(recovery_applicable and not confirmation),
                           censor_at=window['end'] if fault and not confirmation and fault.get('signal')!='telemetry' else None, final_service_state=final_state),
        'cost': dict(candidate_seconds=duration(native['launch'], native['terminal']) if native['complete'] else None,
                     native_controller_seconds=duration(native['native_start'], native['terminal']) if arm=='bdi' else None,
                     **costs, deployment_count_basis='native job invocation' if arm=='bdi' else 'Docker replacement start'),
        'validity': dict(status='valid' if not reasons else 'incomplete', reasons=reasons,
                         observation_complete=request_coverage and endpoint_ok,
                         evidence_complete=not evidence.missing and native['complete'] and costs['workflow_runs'] is not None and costs['started_jobs'] is not None,
                         reset_excluded=True, excluded_native_events=native['excluded_events'],
                         metric_validity={'error_rate': request_coverage, 'availability': statistics_health['availability_estimate'] is not None,
                                          'candidate_duration': native['complete'] and duration(native['launch'], native['terminal']) is not None},
                         intervention_attestation=interventions),
        'provenance': dict(evidence_directory=str(evidence.root), source_sha256=evidence.hashes, missing=evidence.missing,
                           reset_reference=native['reset_reference'],
                           specification_sha256=hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest(),
                           measurement_policy_sha256=policy_hash,
                           reset_data_policy=('controlled_seed_receipt_required' if spec.get('scenario_contract')=='memos-phase7-v1' else 'reseed' if arm=='conventional' else 'preserve_existing_data_and_sentinels'),
                           reset_isolation_decision=('shared seed; verify per-case reset receipt' if spec.get('scenario_contract')=='memos-phase7-v1' else 'UNRESOLVED before scenario/batch freeze')),
        'normalized_requests': selected,
    }


def aggregate(results):
    if any(r.get('execution_mode') == 'validation' or r.get('primary_study_eligible') is False for r in results):
        raise ValueError('Validation campaigns are excluded from primary study aggregates')
    groups = defaultdict(list)
    seen = set()
    for row in results:
        identity = row['identity']
        key = (identity['case_id'], identity['treatment'])
        if key in seen:
            raise ValueError('Duplicate case/treatment')
        seen.add(key)
        w=row['boundaries']['window']
        group = (identity['scenario_family'], json.dumps(identity['parameters'], sort_keys=True),
                identity['treatment'], identity['contract_sha256'], row['provenance']['measurement_policy_sha256'],
                w['anchor'], duration(w['start'],w['end']))
        if row.get('controlled_seed_sha256'):
            group += (row['controlled_seed_sha256'],)
        groups[group].append(row)
    output = []
    for key, rows in sorted(groups.items()):
        valid = [r for r in rows if r['validity']['status']=='valid']
        metrics = {}
        for section, name in [('reliability','error_rate'),('reliability','availability_estimate'),
                              ('cost','candidate_seconds'),('cost','retries'),('cost','deployment_attempts'),
                              ('cost','workflow_runs'),('cost','started_jobs'),('resilience','detection_seconds'),('resilience','recovery_seconds')]:
            eligible = [r for r in valid if section!='resilience' or r['resilience']['applicable']]
            values = [r[section][name] for r in eligible if r[section].get(name) is not None]
            metrics[name] = dict(applicable_n=len(eligible), observed_n=len(values), missing_n=len(eligible)-len(values),
                                 distribution=values, mean=statistics.mean(values) if values else None,
                                 median=statistics.median(values) if values else None)
        counts = {}
        for name, eligible, section, field in [
            ('false_acceptance', [r for r in valid if r['reliability']['native_outcome'] in ('success','achieved')], 'reliability','false_acceptance'),
            ('restoration', [r for r in valid if r['resilience']['service_recovery_applicable']], 'resilience','recovery_observed'),
            ('candidate_delivery', valid, 'reliability','candidate_delivered')]:
            values=[r[section][field] for r in eligible if r[section][field] is not None]
            counts[name]=dict(applicable_n=len(eligible), observed_n=len(values), unknown_n=len(eligible)-len(values),
                              success_n=sum(values), fraction=sum(values)/len(values) if values else None)
        counts['final_service_states']=dict(Counter(r['resilience']['final_service_state'] for r in valid))
        total = sum(r['reliability']['requests_total'] for r in valid if r['reliability']['error_rate'] is not None)
        failed = sum(r['reliability']['requests_failed'] for r in valid if r['reliability']['error_rate'] is not None)
        output.append(dict(group=key, attempted_n=len(rows), valid_n=len(valid),
                           invalid_n=sum(r['validity']['status']=='invalid' for r in rows),
                           incomplete_n=sum(r['validity']['status'] not in ('valid','invalid') for r in rows),
                           metrics=metrics, frequencies=counts, recovery_censored_n=sum(r['resilience']['censored'] for r in valid),
                           pooled_request_error_rate=failed/total if total else None, pooled_request_denominator=total))
    pairs=defaultdict(dict)
    for r in results:
        i=r['identity']; pairs[(i['scenario_family'],json.dumps(i['parameters'],sort_keys=True),i['pair_key'],i['contract_sha256'])][i['treatment']]=r
    comparisons=[]
    for key,pair in sorted(pairs.items()):
        complete=set(pair)=={'conventional','bdi'} and all(r['validity']['status']=='valid' for r in pair.values())
        if set(pair)=={'conventional','bdi'}:
            a,b=pair.values()
            if a.get('controlled_seed_sha256') != b.get('controlled_seed_sha256'):
                raise ValueError('Paired controlled seed state differs')
            wa,wb=a['boundaries']['window'],b['boundaries']['window']
            if (wa['anchor'] != wb['anchor'] or duration(wa['start'],wa['end']) != duration(wb['start'],wb['end']) or
                    a['provenance']['measurement_policy_sha256'] != b['provenance']['measurement_policy_sha256']):
                raise ValueError('Paired measurement policies/windows differ')
        differences={}
        for section,name in [('reliability','error_rate'),('cost','candidate_seconds')]:
            values=[pair[a][section][name] for a in ('bdi','conventional')] if complete else [None,None]
            differences[name]=values[0]-values[1] if all(v is not None for v in values) else None
        comparisons.append(dict(pair=key,complete=complete,bdi_minus_conventional=differences))
    return dict(schema_version=2,groups=output,paired_comparisons=comparisons,
                complete_pair_n=sum(p['complete'] for p in comparisons),missing_pair_n=sum(not p['complete'] for p in comparisons),
                note='No cross-family weighting or composite score. Historical/incomplete cases excluded from primary aggregates.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['case','aggregate'])
    parser.add_argument('inputs',nargs='+',type=Path)
    args=parser.parse_args()
    values=[json.loads(p.read_text(encoding='utf-8-sig')) for p in args.inputs]
    if args.operation=='case' and len(values)!=1:
        parser.error('case requires one explicit specification')
    print(json.dumps(normalize(values[0]) if args.operation=='case' else aggregate(values),indent=2,allow_nan=False))


if __name__=='__main__':
    main()
