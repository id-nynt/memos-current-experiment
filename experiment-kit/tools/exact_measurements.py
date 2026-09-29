"""Read-only additive accounting for the final exact-count study.

No sampling, treatment decisions or changed Phase 5 reliability/cost denominator.
"""
import math
from collections import Counter


def distribution(values):
    values=sorted(values)
    if not values:return dict(n=0,min_ms=None,mean_ms=None,p50_ms=None,p95_ms=None,max_ms=None)
    return dict(n=len(values),min_ms=values[0],mean_ms=sum(values)/len(values),
                p50_ms=values[math.ceil(.5*len(values))-1],p95_ms=values[math.ceil(.95*len(values))-1],max_ms=values[-1])


def derive(evidence, spec, native, start, end, stamp, normalize_request):
    from scenario_runtime import block_summary
    arm=spec['treatment'];schedule=evidence.read('scenario-schedule.json')
    report=evidence.read('fault-summary.json',required=bool(schedule))
    exact=report.get('exact_requests',[]) if report else []
    if schedule:
        if report is None or report.get('evidence_complete') is not True:
            raise ValueError('Missing/incomplete exact-count proxy accounting')
        blocks=block_summary(exact,schedule['spec'])
        if report.get('blocks')!=blocks:raise ValueError('Exact-count block summary does not reconcile')
        target=schedule['target']
        if any(row.get('trial_id')!=target['trial_id'] or row.get('project')!=target['project'] for row in exact):
            raise ValueError('Foreign exact-count request accounting')
    else:
        blocks=[]
    environments=['production']+(['staging'] if schedule and schedule['target']['environment']=='staging' else [])
    accounting={}
    for environment in environments:
        prefix='' if environment=='production' else 'staging-'
        starts=evidence.read(prefix+'workload-starts.jsonl',lines=True,required=True)
        rows=evidence.read(prefix+'workload.jsonl',lines=True,required=True)
        arrivals={r['request_id']:r for r in starts if start<=stamp(r['request_started_at'])<end}
        if len({r['request_id'] for r in starts})!=len(starts):raise ValueError('Duplicate independent launch ID')
        completed={r['request_id']:r for r in rows if r.get('request_id') in arrivals}
        if len({r.get('request_id') for r in rows})!=len(rows):raise ValueError('Missing/duplicate independent completion ID')
        if any(start<=stamp(r['request_started_at'])<end and r.get('request_id') not in arrivals for r in rows):
            raise ValueError('Independent completion has no recorded launch')
        assigned={r['request_id']:r for r in exact if r['event']=='fault_eligible' and r['stream']=='independent'
                  and r['environment']==environment}
        if len(assigned)!=sum(r['event']=='fault_eligible' and r['stream']=='independent' and r['environment']==environment for r in exact):
            raise ValueError('Duplicate/missing independent injector correlation')
        observed=[];injected=delivered=other=timeouts=0
        for request_id,row in completed.items():
            r=normalize_request(row,arm)
            if r['start']!=arrivals[request_id]['request_started_at']:raise ValueError('Independent launch/completion clock mismatch')
            fault=assigned.get(request_id);selected=bool(fault and fault['injected_error'])
            injected+=selected
            received=bool(selected and row.get('status')==fault['injected_status'])
            delivered+=received
            other+=not r['success'] and not received
            timeouts+=r['failure_category']=='timeout'
            observed.append(r)
        relevant=[e for e in native['events'] if e.get('job',e.get('entity',e.get('environment')))==environment]
        telemetry=[dict(timestamp=e['timestamp'],error_rate=e.get('error_rate'),latency_p95_ms=e.get('latency_p95_ms'),
                        event=e.get('event')) for e in relevant if e.get('error_rate') is not None or e.get('latency_p95_ms') is not None]
        latencies=[t['latency_p95_ms'] for t in telemetry if t['latency_p95_ms'] is not None]
        accounting[environment]=dict(requests_started=len(arrivals),requests_completed=len(completed),
            requests_completed_by_endpoint=sum(stamp(r['end'])<=end for r in observed),
            pending_or_missing_completions=len(arrivals)-len(completed),successes=sum(r['success'] for r in observed),
            injected_failure_assignments=sum(bool(assigned.get(k,{}).get('injected_error')) for k in arrivals),
            injected_failures_completed=injected,injected_failures_received=delivered,other_failures=other,timeouts=timeouts,
            http_outcomes=dict(Counter(str(r['status']) if r['status'] is not None else 'no_http_response' for r in observed)),
            request_duration_ms=distribution([1000*r['seconds'] for r in observed]),
            http_200_duration_ms=distribution([1000*r['seconds'] for r in observed if r['status']==200]),
            duration_definition='client-observed duration; timeout durations censored, not service latency',
            completion_coverage=len(completed)/len(arrivals) if arrivals else None,
            bdi_native_rolling_telemetry=telemetry if arm=='bdi' else [],
            bdi_native_latency_threshold_crossed=any(x>500 for x in latencies) if arm=='bdi' and latencies else None,
            configured_additive_delays_ms=[e['delay_ms'] for e in schedule['spec']['episodes']] if schedule and schedule['target']['environment']==environment else [])
        if not arrivals or len(completed)!=len(arrivals):raise ValueError('Incomplete independent launch/completion accounting')
    return dict(contract='memos-exact-count-v1',blocks=blocks,workload=accounting,
                rate_population_note='Injected K/100 per stream/episode block is not the BDI rolling telemetry population/window')
