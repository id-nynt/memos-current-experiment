"""Offline synthetic records only: no controller, Docker, HTTP, or fault execution."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error

import measurement_records as records
import phase5_metrics as m


def at(second):
    return m.iso(m.stamp('2026-09-28T00:00:00Z') + second)


class Metrics(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=m.ROOT)
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.releases = json.loads((m.ROOT/'protocol/frozen-releases.json').read_text())['releases']

    def write(self, root, name, value, lines=False):
        p=root/name; p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text('\n'.join(json.dumps(v) for v in value) if lines else json.dumps(value))

    def fixture(self, arm='bdi', failed=False):
        root=self.root/arm; root.mkdir(exist_ok=True)
        w=lambda n,v,l=False:self.write(root,n,v,l)
        v2=self.releases['v2']
        events=[dict(event='controller_started',timestamp=at(0)),
                dict(event='entity_execution_started',timestamp=at(1),entity='production',attempt=1),
                dict(event='dispatch_intent',timestamp=at(1)),
                dict(event='dispatch_acknowledged',timestamp=at(2),github_run_id=7),
                dict(event='controller_finished',timestamp=at(10),outcome='achieved')]
        run=dict(databaseId=7,status='completed',conclusion='success',headSha='control',startedAt=at(0),
                 jobs=[dict(databaseId=70,startedAt=at(1),conclusion='success'),dict(databaseId=71,startedAt=None,conclusion='skipped')])
        if arm=='bdi':
            w('trial.json',dict(mode='candidate',trial_id='trial',application_sha=v2['application_sha'],control_sha='control',started_at=at(0)))
            w('controller/generation-manifest.json',dict(campaign_id='campaign'))
            w('controller/controller-result.json',dict(campaign_id='campaign',outcome='achieved'))
            w('controller/controller-journal.jsonl',events,True)
            w('github-x/run.json',run)
        else:
            w('manifest.json',dict(config=dict(approach='conventional',application_sha=v2['application_sha'],control_sha='control',trial_id='trial')))
            w('launch.json',dict(pipeline_start=at(0),native_terminal=at(10),pipeline_end=at(50)))
            w('dispatch.json',dict(github_run_id=7))
            w('github/run.json',run)
            w('native-events.jsonl',[dict(event='deployment_start',timestamp=at(1),trial_id='trial',environment='production')],True)
        w('measurement-boundaries.json',dict(role='candidate',candidate_launch_at=at(0)))
        w('human-interventions.json',[])
        workload=[]; samples=[]
        for second in range(31):
            good=not failed or second<5
            workload.append(dict(timestamp=at(second),measurement_version=2,request_started_at=at(second),request_completed_at=at(second),duration_seconds=0,
                                 status=200 if good else 503,response_valid=True if good else None,content_matches=True if good else None,
                                 failure_category=None if good else 'http_5xx'))
            samples.append(dict(timestamp=at(second),healthy=good,measurement_version=2,measurement_error=False,
                                release_sha=v2['application_sha'],image_id=v2['image_id']))
        w('workload.jsonl',workload,True); w('common-observations.jsonl',samples,True)
        return dict(role='candidate',treatment=arm,case_id='case',scenario_family='S0',parameters={},evidence_directory=str(root),declaration='prospective',declared_at=at(0),
                    window=dict(start=at(0),end=at(30),anchor='launch',pair_key='pair'),
                    coverage=dict(maximum_gap_seconds=3,minimum_fraction=.95),
                    endpoint=dict(window_seconds=5,minimum_samples=3,edge_tolerance_seconds=1),
                    stability=dict(minimum_samples=3,minimum_span_seconds=10,maximum_gap_seconds=15),cross_clock_verified=True)

    def fault(self,spec):
        self.write(Path(spec['evidence_directory']),'fault-events.jsonl',[dict(event='fault_started',timestamp=at(5))],True)
        spec['fault']=dict(kind='production',source='fault-events.jsonl',match=dict(event='fault_started'),entity='production',native_error_threshold=.05)

    def test_equivalent_traces(self):
        a,b=m.normalize(self.fixture('conventional',True)),m.normalize(self.fixture('bdi',True))
        self.assertEqual(a['reliability'],{**b['reliability'],'native_outcome':'success'})
        self.assertEqual(a['cost']['candidate_seconds'],b['cost']['candidate_seconds'])
        self.assertEqual(a['reliability']['requests_total'],30)
        self.assertEqual(a['reliability']['error_rate'],25/30)

    def test_false_acceptance_does_not_rewrite_native_outcome(self):
        r=m.normalize(self.fixture('conventional',True))
        self.assertEqual(r['reliability']['native_outcome'],'success')
        self.assertTrue(r['reliability']['false_acceptance'])

    def test_cost_excludes_followup_and_collection(self):
        r=m.normalize(self.fixture('conventional'))
        self.assertEqual(r['cost']['candidate_seconds'],10)
        self.assertEqual(r['boundaries']['observation_end'],at(30))

    def test_reset_and_qualification_rejected(self):
        for role in ('reset','qualification','setup','baseline'):
            s=self.fixture(); s['role']=role
            with self.assertRaises(ValueError):m.normalize(s)
        s=self.fixture(); self.write(Path(s['evidence_directory']),'trial.json',dict(mode='baseline'))
        with self.assertRaises(ValueError):m.normalize(s)

    def test_reset_stream_cannot_add_cost(self):
        s=self.fixture(); root=Path(s['evidence_directory'])
        self.write(root,'reset/controller-journal.jsonl',[dict(event='entity_execution_started',timestamp=at(4),entity='rollback')],True)
        r=m.normalize(s); self.assertEqual(r['cost']['rollbacks_started'],0)

    def test_post_terminal_events_excluded(self):
        s=self.fixture(); root=Path(s['evidence_directory']); p=root/'controller/controller-journal.jsonl'
        with p.open('a') as f:f.write('\n'+json.dumps(dict(event='entity_execution_started',timestamp=at(20),entity='rollback')))
        r=m.normalize(s); self.assertEqual(r['cost']['rollbacks_started'],0); self.assertEqual(r['validity']['excluded_native_events'],1)

    def test_foreign_campaign_rejected(self):
        s=self.fixture(); self.write(Path(s['evidence_directory']),'controller/controller-result.json',dict(campaign_id='foreign'))
        with self.assertRaises(ValueError):m.normalize(s)

    def test_foreign_conventional_event_rejected(self):
        s=self.fixture('conventional'); self.write(Path(s['evidence_directory']),'native-events.jsonl',[dict(trial_id='other',timestamp=at(1))],True)
        with self.assertRaises(ValueError):m.normalize(s)

    def test_missing_terminal_is_not_zero_cost(self):
        s=self.fixture(); (Path(s['evidence_directory'])/'controller/controller-result.json').unlink()
        r=m.normalize(s); self.assertIsNone(r['cost']['rollbacks_started']); self.assertFalse(r['validity']['evidence_complete']); self.assertIsNone(r['cost']['candidate_seconds'])

    def test_missing_workload_is_not_zero_error(self):
        s=self.fixture(); (Path(s['evidence_directory'])/'workload.jsonl').unlink()
        r=m.normalize(s); self.assertIsNone(r['reliability']['error_rate'])

    def test_boundary_crossing_request_assigned_by_start(self):
        s=self.fixture(); root=Path(s['evidence_directory']); rows=[json.loads(x) for x in (root/'workload.jsonl').read_text().splitlines()]
        rows[29]['request_completed_at']=at(32); rows.pop()
        self.write(root,'workload.jsonl',rows,True)
        self.assertEqual(m.normalize(s)['reliability']['requests_total'],30)

    def test_historical_unknown_transport_preserved(self):
        for arm in ('bdi','conventional'):
            row=m.request(dict(timestamp=at(1),status=None,error_type='URLError',duration_seconds=1),arm)
            self.assertEqual(row['failure_category'],'unknown')

    def test_new_categories(self):
        cases=[(503,None,None,None,'http_5xx'),(401,None,None,None,'http_4xx'),(302,None,None,None,'unexpected_http_status'),
               (200,False,None,None,'invalid_response'),(200,True,False,None,'content_mismatch'),
               (None,None,None,urllib.error.URLError(TimeoutError()),'timeout'),
               (None,None,None,ConnectionRefusedError(),'transport_failure'),(None,None,None,ValueError(),'unknown')]
        for status,valid,match,error,expected in cases:
            self.assertEqual(records.failure_category(status,valid,match,error),expected)
        self.assertIsNone(records.failure_category(200,True,True))

    def test_observer_error_is_unknown_availability(self):
        rows=[dict(timestamp=at(0),healthy=False,measurement_version=2,measurement_error=True),dict(timestamp=at(10),healthy=True)]
        r=m.availability(rows,m.stamp(at(0)),m.stamp(at(10)),15,.9)
        self.assertEqual(r['unknown_seconds'],10); self.assertIsNone(r['availability_estimate'])

    def test_gap_not_carried_as_healthy(self):
        rows=[dict(timestamp=at(0),healthy=True),dict(timestamp=at(30),healthy=True)]
        r=m.availability(rows,m.stamp(at(0)),m.stamp(at(30)),15,.9)
        self.assertEqual(r['unknown_seconds'],30)

    def test_passive_failure_is_not_native_detection(self):
        s=self.fixture(failed=True); self.fault(s); r=m.normalize(s)
        self.assertFalse(r['resilience']['detected']); self.assertTrue(r['resilience']['censored'])

    def test_native_detection(self):
        s=self.fixture(failed=True); self.fault(s); p=Path(s['evidence_directory'])/'controller/controller-journal.jsonl'
        rows=[json.loads(x) for x in p.read_text().splitlines()]
        rows.insert(-1,dict(timestamp=at(6),event='telemetry_measurement',entity='production',data_status='fresh',readiness='ready',error_rate=.5))
        self.write(p.parent,'controller-journal.jsonl',rows,True)
        r=m.normalize(s); self.assertEqual(r['resilience']['detection_seconds'],1)

    def test_unknown_cross_clock_latency(self):
        s=self.fixture(failed=True); self.fault(s); s['cross_clock_verified']=False
        self.assertIsNone(m.normalize(s)['resilience']['detection_seconds'])

    def test_stability_and_relapse(self):
        rows=[dict(timestamp=at(i),healthy=i not in (5,25)) for i in range(31)]
        onset,confirmed,relapse=m.stable_recovery(rows,m.stamp(at(5)),m.stamp(at(30)),dict(minimum_samples=3,minimum_span_seconds=10,maximum_gap_seconds=15))
        self.assertEqual(onset,at(6)); self.assertEqual(confirmed,at(16)); self.assertTrue(relapse)

    def test_clearance_is_not_autonomous_recovery(self):
        s=self.fixture(failed=True); self.fault(s); root=Path(s['evidence_directory'])
        rows=[json.loads(x) for x in (root/'common-observations.jsonl').read_text().splitlines()]
        for row in rows:
            if m.stamp(row['timestamp'])>=m.stamp(at(15)):row['healthy']=True
        self.write(root,'common-observations.jsonl',rows,True)
        self.write(root,'clearance.jsonl',[dict(event='expired',timestamp=at(15))],True)
        s['fault']['clearance']=dict(source='clearance.jsonl',match=dict(event='expired'))
        r=m.normalize(s); self.assertTrue(r['resilience']['recovery_observed']); self.assertEqual(r['resilience']['recovery_cause'],'scheduled_clearance_or_coincident_action')

    def test_jobs_deduplicated_and_skipped_excluded(self):
        s=self.fixture(); root=Path(s['evidence_directory']); self.write(root,'github-x/duplicate.json',json.loads((root/'github-x/run.json').read_text()))
        self.assertEqual(m.normalize(s)['cost']['started_jobs'],1)

    def test_nanosecond_ordering(self):
        self.assertGreater(m.stamp('2026-09-28T00:00:00.000000002Z'),m.stamp('2026-09-28T00:00:00.000000001Z'))
        with self.assertRaises(ValueError):m.stamp('2026-09-28T00:00:00')

    def test_no_evidence_mutation(self):
        s=self.fixture(); root=Path(s['evidence_directory'])
        before={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
        m.normalize(s)
        self.assertEqual(before,{p:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()})

    def test_paired_aggregate_and_denominators(self):
        rows=[m.normalize(self.fixture(a)) for a in ('bdi','conventional')]
        r=m.aggregate(rows); self.assertEqual(r['complete_pair_n'],1); self.assertEqual(r['paired_comparisons'][0]['bdi_minus_conventional']['error_rate'],0)
        self.assertEqual(r['groups'][0]['frequencies']['restoration']['applicable_n'],0)
        with self.assertRaises(ValueError):m.aggregate(rows+rows)

    def test_mismatched_pair_window_rejected(self):
        rows=[m.normalize(self.fixture(a)) for a in ('bdi','conventional')]; rows[0]['boundaries']['window']['anchor']='fault'
        with self.assertRaises(ValueError):m.aggregate(rows)

    def test_historical_not_primary_aggregate(self):
        s=self.fixture(); s['declaration']='retrospective'; r=m.aggregate([m.normalize(s)])
        self.assertEqual(r['groups'][0]['valid_n'],0)

    def test_common_helper_copies(self):
        original=(m.ROOT/'tools/measurement_records.py').read_bytes()
        for p in ('memos-current/scripts/experiment-measurement/measurement_records.py','memos-bdi/experiment/scripts/measurement_records.py'):
            self.assertEqual(original,(m.ROOT/p).read_bytes())

    def test_prospective_declaration_after_launch_rejected(self):
        s=self.fixture(); s['declared_at']=at(1)
        with self.assertRaises(ValueError):m.normalize(s)

    def test_measurement_failure_preserves_native_success(self):
        s=self.fixture(); self.write(Path(s['evidence_directory']),'measurement-errors.jsonl',[dict(timestamp=at(3),error_type='OSError')],True)
        r=m.normalize(s); self.assertIsNone(r['reliability']['error_rate']); self.assertEqual(r['reliability']['native_outcome'],'achieved')

    def test_foreign_fault_campaign_rejected(self):
        s=self.fixture(); self.fault(s); self.write(Path(s['evidence_directory']),'fault-events.jsonl',[dict(event='fault_started',timestamp=at(5),campaign_id='foreign')],True)
        with self.assertRaises(ValueError):m.normalize(s)

    def test_ci_retry_does_not_invent_service_restoration(self):
        s=self.fixture(); self.fault(s); s['fault'].update(kind='ci',entity='test')
        p=Path(s['evidence_directory'])/'controller/controller-journal.jsonl'; rows=[json.loads(x) for x in p.read_text().splitlines()]
        rows[-1:-1]=[dict(timestamp=at(6),event='entity_execution_finished',entity='test',attempt=1,status='transient_failure'),
                     dict(timestamp=at(7),event='entity_execution_started',entity='test',attempt=2),
                     dict(timestamp=at(8),event='entity_execution_finished',entity='test',attempt=2,status='success')]
        self.write(p.parent,p.name,rows,True); r=m.normalize(s)
        self.assertTrue(r['resilience']['ci_retry_recovered']); self.assertTrue(r['resilience']['detected'])
        self.assertIsNone(r['resilience']['recovery_observed']); self.assertFalse(r['resilience']['service_recovery_applicable'])

    def test_failed_rollback_is_not_success(self):
        s=self.fixture(); p=Path(s['evidence_directory'])/'controller/controller-journal.jsonl'; rows=[json.loads(x) for x in p.read_text().splitlines()]
        rows[-1:-1]=[dict(timestamp=at(7),event='entity_execution_started',entity='rollback',attempt=1),
                     dict(timestamp=at(8),event='entity_execution_finished',entity='rollback',attempt=1,status='failure')]
        self.write(p.parent,p.name,rows,True); r=m.normalize(s)
        self.assertFalse(r['resilience']['rollback_success']); self.assertEqual(r['cost']['rollbacks_started'],1)

    def test_historical_http_error_is_service_failure(self):
        self.assertFalse(m.health(dict(healthy=False,error_type='HTTPError')))
        self.assertIsNone(m.health(dict(healthy=False,error_type='CalledProcessError')))

    def test_conventional_all_attempt_retries(self):
        s=self.fixture('conventional'); root=Path(s['evidence_directory'])
        jobs=[dict(id=1,run_id=7,name='test',run_attempt=1,started_at=at(1),conclusion='failure'),
              dict(id=2,run_id=7,name='test',run_attempt=2,started_at=at(2),conclusion='success')]
        self.write(root,'github/jobs-all-attempts.json',jobs)
        self.assertEqual(m.normalize(s)['cost']['retries'],1)


if __name__=='__main__':unittest.main()
