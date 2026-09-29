"""Offline exact-count, honest accounting and balanced final-study contracts."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import scenario_runtime as s
import phase8_matrix as matrix
import ci_controls
import exact_measurements as accounting
import phase5_metrics as metrics
from test_phase5_metrics import at

ROOT=Path(__file__).resolve().parents[1]


class ExactCount(unittest.TestCase):
    def engine(self,k=6,seed=123,episodes=None):
        spec=copy.deepcopy(s.resolve('P12'));spec['seed']=seed
        spec['episodes']=episodes or [dict(matrix.episode(0,300,k),id='e1')]
        identity=dict(trial_id='trial',project='owned',release='v2',release_sha='b'*40,image_id='sha256:'+'c'*64,environment='production')
        rows=[]
        return s.Engine(s.lease(spec,identity,0,0),identity,emit=rows.append,clock=lambda:1),rows

    def run_requests(self,engine,n,stream='independent',elapsed=1):
        values=[]
        for i in range(n):
            d=engine.decision('/api/v1/memos/x','GET',stream,elapsed,request_id=stream+'-'+str(i))
            engine.record(d,503 if d['injected_error'] else 200,1,True);values.append(d)
        return values

    def test_each_complete_block_has_exact_selected_count(self):
        for k in (0,4,5,6,10,30,60,100):
            e,rows=self.engine(k);values=self.run_requests(e,200)
            for begin in (0,100):self.assertEqual(sum(v['injected_error'] for v in values[begin:begin+100]),k)
            blocks=s.block_summary(rows,e.value['spec'])
            actual=[b for b in blocks if b['stream']=='independent']
            self.assertEqual([b['exact_realized_rate'] for b in actual],[k/100,k/100])

    def test_seed_reproduces_positions_across_engines(self):
        a,_=self.engine();b,_=self.engine()
        self.assertEqual([v['injected_error'] for v in self.run_requests(a,250)],
                         [v['injected_error'] for v in self.run_requests(b,250)])
        self.assertNotEqual(s.failure_positions(123,'e1','independent',1,100,6),
                            s.failure_positions(124,'e1','independent',1,100,6))

    def test_native_methods_share_block_but_never_consume_independent(self):
        a,_=self.engine();b,_=self.engine()
        for i in range(100):
            d=a.decision('/api/v1/memos/x','POST' if i%2 else 'GET')
            self.assertEqual(d['ordinal'],i+1)
        self.assertEqual([v['injected_error'] for v in self.run_requests(a,100)],
                         [v['injected_error'] for v in self.run_requests(b,100)])

    def test_partial_block_has_no_exact_rate(self):
        e,rows=self.engine();self.run_requests(e,36)
        b=next(b for b in s.block_summary(rows,e.value['spec']) if b['stream']=='independent')
        self.assertEqual(b['actual_eligible_requests'],36);self.assertTrue(b['partial_block'])
        self.assertIsNone(b['exact_realized_rate']);self.assertEqual(len(b['selected_failure_positions']),6)

    def test_zero_exposure_explicit(self):
        e,rows=self.engine();blocks=s.block_summary(rows,e.value['spec'])
        self.assertEqual(len(blocks),2);self.assertTrue(all(b['status']=='not_started' for b in blocks))

    def test_episode_restart_and_clearance(self):
        episodes=[dict(matrix.episode(0,10,6),id='e1'),dict(matrix.episode(20,40,6),id='e2')]
        e,rows=self.engine(episodes=episodes);self.run_requests(e,4)
        self.assertIsNone(e.decision('/api/v1/memos/x','GET',elapsed=10))
        d=e.decision('/api/v1/memos/x','GET','independent',elapsed=20)
        self.assertEqual((d['ordinal'],d['block_index']),(1,1))

    def test_missing_completion_and_delivery_are_not_claimed_exact(self):
        e,rows=self.engine(100)
        for i in range(100):
            d=e.decision('/api/v1/memos/x','GET','independent')
            if i<99:e.record(d,503,1,False)
        b=next(b for b in s.block_summary(rows,e.value['spec']) if b['stream']=='independent')
        self.assertEqual((b['selected_failures'],b['injected_failures'],b['delivered_failures']),(100,99,0))
        self.assertFalse(b['completion_evidence_complete']);self.assertIsNone(b['exact_realized_rate'])

    def test_missing_arrival_rejected(self):
        e,rows=self.engine();self.run_requests(e,2)
        with self.assertRaises(ValueError):s.block_summary(rows[1:],e.value['spec'])

    def test_restart_rejected(self):
        a,ra=self.engine();b,rb=self.engine();self.run_requests(a,2);self.run_requests(b,2)
        with self.assertRaises(ValueError):s.block_summary(ra+rb,a.value['spec'])

    def test_invalid_count_or_percentage_rejected(self):
        for field,value in [('failure_count',6.5),('failure_count',101),('error_percent',5.1),('block_size',0)]:
            e,_=self.engine();spec=copy.deepcopy(e.value['spec']);spec['episodes'][0][field]=value
            with self.assertRaises(ValueError):s.validate(spec)

    def test_historical_probability_formula_preserved(self):
        import hashlib
        e,_=self.engine();ep=e.value['spec']['episodes'][0]
        for k in ('error_model','block_size','failure_count'):ep.pop(k)
        for n in range(1,101):
            d=e.decision('/api/v1/memos/x','GET','independent')
            payload=json.dumps([123,'e1','independent','GET',n],separators=(',',':'))
            self.assertEqual(d['injected_error'],int.from_bytes(hashlib.sha256(payload.encode()).digest()[:8],'big')/2**64<.06)

    def test_delay_applies_to_both_streams_not_selected_errors(self):
        for stream in ('independent','native'):
            e,_=self.engine(0);e.value['spec']['episodes'][0]['delay_ms']=550
            with patch.object(e,'sleep') as sleep:
                e.delay(e.decision('/api/v1/memos/x','GET',stream));sleep.assert_called_once_with(.55)
            e,_=self.engine(100);e.value['spec']['episodes'][0]['delay_ms']=550
            with patch.object(e,'sleep') as sleep:
                e.delay(e.decision('/api/v1/memos/x','GET',stream));sleep.assert_not_called()

    def test_client_injection_timeout_and_native_latency_are_separate(self):
        e,proxy_rows=self.engine();starts=[];rows=[];timeout_used=False
        for i in range(100):
            rid='production-'+str(i)
            d=e.decision('/api/v1/memos/x','GET','independent',request_id=rid)
            status=503 if d['injected_error'] else 200
            is_timeout=not d['injected_error'] and not timeout_used
            timeout_used|=is_timeout
            e.record(d,status,600,not is_timeout)
            starts.append(dict(request_id=rid,request_started_at=at(i)))
            rows.append(dict(request_id=rid,request_started_at=at(i),request_completed_at=at(i+3 if is_timeout else i),
                measurement_version=2,duration_seconds=3 if is_timeout else .6,
                status=None if is_timeout else status,response_valid=status==200,content_matches=status==200,
                failure_category='timeout' if is_timeout else 'http_5xx' if status==503 else None))
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            for name,value in [('workload-starts',starts),('workload',rows)]:
                (p/(name+'.jsonl')).write_text(''.join(json.dumps(r)+'\n' for r in value))
            (p/'scenario-schedule.json').write_text(json.dumps(e.value))
            (p/'fault-summary.json').write_text(json.dumps(dict(exact_requests=proxy_rows,
                evidence_complete=True,blocks=s.block_summary(proxy_rows,e.value['spec']))))
            native=dict(events=[dict(timestamp=at(5),entity='production',event='telemetry_measurement',latency_p95_ms=650,error_rate=.09)])
            value=accounting.derive(metrics.Evidence(p),dict(treatment='bdi'),native,metrics.stamp(at(0)),metrics.stamp(at(300)),metrics.stamp,metrics.request)
            out=value['workload']['production']
            self.assertEqual((out['requests_started'],out['requests_completed'],out['successes']),(100,100,93))
            self.assertEqual((out['injected_failures_received'],out['other_failures'],out['timeouts']),(6,1,1))
            self.assertTrue(out['bdi_native_latency_threshold_crossed'])
            self.assertEqual(out['bdi_native_rolling_telemetry'][0]['error_rate'],.09)
            self.assertEqual(value['blocks'][0]['exact_realized_rate'],.06)


class ControlsAndMatrix(unittest.TestCase):
    def test_permanent_controls_are_required_correct_workflow_boundaries(self):
        import yaml
        conventional=yaml.safe_load((ROOT/'memos-current/.github/workflows/frozen-cd.yml').read_text())
        steps=conventional['jobs']['deploy']['steps']
        control=next(x for x in steps if x.get('name')=='Explicit permanent build control')
        self.assertIn('--boundary build',control['run']);self.assertNotIn('continue-on-error',control)
        self.assertLess(steps.index(control),next(i for i,x in enumerate(steps) if x.get('name')=='Deliver frozen image through conventional stages'))
        worker=yaml.safe_load((ROOT/'memos-bdi/.github/workflows/experiment-operation.yml').read_text())
        control=next(x for x in worker['jobs']['operation']['steps'] if x.get('name')=='Explicit permanent build control')
        self.assertEqual(control['if'],"inputs.operation == 'build'")
        self.assertEqual(control['env']['FIXTURE_BOUNDARY'],'build');self.assertNotIn('continue-on-error',control)
    def test_permanent_build_and_test_fail_each_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            for sid,boundary in [('CI02','build'),('CI03','test')]:
                for attempt in (1,2):
                    path=Path(tmp)/sid/str(attempt)
                    with self.assertRaises(RuntimeError):ci_controls.run_control(sid,boundary,dict(campaign_id='x',control_sha='b'*40,release_sha='c'*40),path)
                    self.assertTrue(json.loads((path/'ci-control.json').read_text())['permanent'])
            self.assertFalse(ci_controls.run_control('CI02','test',{},tmp))
            self.assertFalse(ci_controls.run_control('CI03','build',{},tmp))
            self.assertFalse(ci_controls.run_control('CI01','test',{},tmp))

    def test_matrix_balance_repeats_controls_and_no_reserves(self):
        from collections import Counter
        value=matrix.build();matrix.validate(value)
        a=[c for c in value['cases'] if c['test_set']=='A'];b=[c for c in value['cases'] if c['test_set']=='B']
        self.assertEqual(len(a),50);self.assertEqual(len(b),50)
        self.assertEqual(Counter(c['family'] for c in a),Counter(c['family'] for c in b))
        self.assertEqual([c['scenario'] for c in a if c['family']=='deterministic_control'],['CI02'])
        self.assertEqual([c['scenario'] for c in b if c['family']=='deterministic_control'],['CI03'])
        self.assertFalse(any(c['baseline'] in ('P24','P25','P28') for c in value['cases']))
        for family in ('reference','persistent','transient','relapse','latency'):
            self.assertTrue(any(c['family']==family and c['repeat_rationale'] for c in a))
        self.assertEqual(len({c['parameters']['seed'] for c in value['cases']}),100)

    def test_client_duration_distribution_includes_timeout_censoring(self):
        self.assertEqual(accounting.distribution([450,500,550,3000])['p95_ms'],3000)

    def test_major_severity_onset_and_duration_categories_balanced(self):
        from collections import Counter
        def categories(c):
            episodes=c['parameters']['episodes']
            if not episodes:return ('control',)*3
            maximum=max(e['failure_count'] for e in episodes)
            onset=episodes[0]['start'];active=sum(e['end']-e['start'] for e in episodes)
            return (('zero' if maximum==0 else 'threshold' if maximum<=6 else 'moderate' if maximum<=30 else 'severe'),
                    ('immediate' if onset==0 else 'early' if onset<=60 else 'late' if onset<=150 else 'post_budget'),
                    ('short' if active<=45 else 'medium' if active<=150 else 'long'))
        groups={name:[categories(c) for c in matrix.build()['cases'] if c['test_set']==name] for name in ('A','B')}
        for column in range(3):
            counts={name:Counter(row[column] for row in rows) for name,rows in groups.items()}
            for key in set(counts['A'])|set(counts['B']):self.assertLessEqual(abs(counts['A'][key]-counts['B'][key]),2)

    def test_missing_launch_completion_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            (p/'workload-starts.jsonl').write_text(json.dumps(dict(request_id='production-1',request_started_at=at(0)))+'\n')
            (p/'workload.jsonl').write_text('')
            with self.assertRaises(ValueError):accounting.derive(metrics.Evidence(p),dict(treatment='bdi'),dict(events=[]),metrics.stamp(at(0)),metrics.stamp(at(300)),metrics.stamp,metrics.request)


if __name__=='__main__':unittest.main()
