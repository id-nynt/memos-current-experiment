"""Focused offline policy/horizon tests; no runner, network or deployment."""
import copy
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
import yaml
import bdi_policy as p
import bdi_attribution as a
import experiment as e

ROOT = Path(__file__).resolve().parents[1]


class PolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = json.loads((ROOT/'protocol/operator-revisions.json').read_text())['bdi']
        cls.contract = json.loads((ROOT/'protocol/bdi-policy-final-source.json').read_text())
        cls.data = {name: yaml.safe_load((ROOT/'memos-bdi'/path).read_text()) for name,path in p.INPUTS.items() if name not in ('generation','agent')}

    def resolve(self, data):
        return p.resolve_values(data, self.contract['fixed_semantics'], 'S0', {})

    def test_prepared_source_report_matches_authority(self):
        # Publication pins remain unchanged until the user creates new commits.
        def working_source(cmd, **kwargs):
            return (ROOT/'memos-bdi'/cmd[-1].split(':',1)[1]).read_bytes()
        with patch.object(p.subprocess, 'check_output', side_effect=working_source):
            report = p.report(ROOT, self.spec, environ={})
        self.assertEqual(report['control_sha'], self.spec['control_sha'])
        self.assertEqual(report['status'], 'consistent')
        self.assertEqual(report['shared_health_definition']['max_error_fraction'], .05)
        self.assertEqual(report['resolved_limits']['retry_budget_per_job'], 1)
        self.assertEqual(report['resolved_limits']['retry_interval_seconds'], 5)
        self.assertEqual(report['resolved_limits']['observation_timeout_seconds'], 150)
        self.assertIsNone(report['resolved_limits']['overall_campaign_deadline_seconds'])

    def test_shared_conflicts_fail(self):
        mutations = [lambda d: d['protocol']['policy'].update(max_error_fraction=.1),
                     lambda d: d['protocol']['policy'].update(max_p95_ms=900),
                     lambda d: d['protocol']['policy'].update(max_age_seconds=40),
                     lambda d: d['protocol']['policy'].update(window_seconds=60),
                     lambda d: d['bindings']['telemetry']['metrics'].update(error_rate_query='sum(other_errors[30s])'),
                     lambda d: d['paired'].update(sample_interval_seconds=3),
                     lambda d: d['runtime'].update(bdi_production_port=9999),
                     lambda d: d['workflow']['execution'].update(observation_attempts=5)]
        for mutate in mutations:
            data = copy.deepcopy(self.data)
            mutate(data)
            with self.subTest(mutation=mutate), self.assertRaisesRegex(ValueError, 'disagreement'):
                self.resolve(data)

    def test_coordinated_threshold_change_still_detects_fixed_analysis_copy(self):
        data = copy.deepcopy(self.data)
        data['policy']['telemetry_constraints']['error_rate_high_gt'] = .01
        data['protocol']['policy']['max_error_fraction'] = .01
        data['workflow']['bindings']['thresholds']['error_rate_high_gt'] = .01
        with self.assertRaisesRegex(ValueError, 'record / opportunity'):
            self.resolve(data)

    def test_independent_worker_budget_is_not_forced_to_equal_agent(self):
        data = copy.deepcopy(self.data)
        data['protocol']['policy']['deadline_seconds'] = 90
        data['protocol']['policy']['interval_seconds'] = 3
        report = self.resolve(data)
        self.assertEqual(report['adapter_worker_safety']['monitor_seconds'], 90)
        self.assertEqual(report['framework_decision_policy']['execution']['observation_timeout_seconds'], 150)

    def test_unreviewed_code_is_rejected(self):
        def changed(cmd, **kwargs):
            result = (ROOT/'memos-bdi'/cmd[-1].split(':',1)[1]).read_bytes()
            return result+b'\n# changed\n' if cmd[-1].endswith(':experiment/scripts/record.py') else result
        with patch.object(p.subprocess, 'check_output', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'Unreviewed fixed-policy'):
                p.report(ROOT, self.spec)

    def test_conflict_blocks_before_network_runtime_or_receipt_consumption(self):
        manifest = json.loads(e.MANIFEST.read_text())
        with patch.object(e,'selection',return_value=(manifest, {})), \
             patch.object(e,'policy_report',side_effect=ValueError('BDI policy disagreement')), \
             patch.object(e,'published') as network, patch.object(e,'runtime') as runtime, \
             patch.object(e.subprocess,'call') as dispatch, \
             patch.object(e.sys,'argv',['experiment.py','reset','bdi']):
            with self.assertRaisesRegex(ValueError,'disagreement'):
                e.main()
            network.assert_not_called()
            runtime.assert_not_called()
            dispatch.assert_not_called()

    def test_read_only_policy_cli_does_not_prepare_or_dispatch(self):
        manifest = json.loads(e.MANIFEST.read_text())
        with patch.object(e,'selection',return_value=(manifest, {})), \
             patch.object(e,'policy_report',return_value={'status':'consistent'}), \
             patch.object(e,'published') as network, patch.object(e,'runtime') as runtime, \
             patch.object(e.subprocess,'call') as dispatch, \
             patch.object(e.sys,'argv',['experiment.py','policy','bdi','--scenario','S5R']):
            self.assertEqual(e.main(),0)
            network.assert_not_called(); runtime.assert_not_called(); dispatch.assert_not_called()


class AttributionTests(unittest.TestCase):
    def event(self, name, seconds):
        return {'event': name, 'timestamp': f'2026-09-28T10:00:{seconds:02d}+00:00'}

    def test_post_terminal_native_and_all_passive_samples_are_not_bdi(self):
        journal = [self.event('controller_started',0), self.event('telemetry_measurement',2),
                   self.event('controller_finished',3), self.event('telemetry_measurement',4),
                   self.event('rollback_selected',5)]
        passive = [self.event('telemetry_measurement',1),self.event('rollback_selected',6)]
        result = a.classify(journal,passive)
        self.assertEqual(result['native_in_horizon_event_counts']['telemetry_measurement'],1)
        self.assertNotIn('rollback_selected',result['native_in_horizon_event_counts'])
        self.assertEqual(len(result['excluded_native_events']),2)
        self.assertFalse(result['passive_measurement']['attributed_to_bdi'])
        self.assertEqual(result['passive_measurement']['post_controller_samples'],1)

    def test_missing_duplicate_or_invalid_bounds_remain_unknown(self):
        for journal in ([self.event('controller_started',0)],
                        [self.event('controller_started',0),self.event('controller_finished',2),self.event('controller_finished',3)],
                        [self.event('controller_started',4),self.event('controller_finished',2)],
                        [self.event('controller_started',0),{'event':'controller_finished','timestamp':'bad'}],
                        [self.event('controller_started',0),{'event':'controller_finished','timestamp':None}]):
            with self.subTest(journal=journal):
                result = a.classify(journal,[self.event('sample',5)])
                self.assertIsNone(result['native_in_horizon_event_counts'])
                self.assertFalse(result['controller_horizon_complete'])

    def test_nanosecond_event_after_terminal_is_excluded(self):
        result = a.classify([self.event('controller_started',0),
            {'event':'controller_finished','timestamp':'2026-09-28T10:00:01.123456100Z'},
            {'event':'telemetry_measurement','timestamp':'2026-09-28T10:00:01.123456101Z'}], [])
        self.assertNotIn('telemetry_measurement', result['native_in_horizon_event_counts'])
        self.assertEqual(len(result['excluded_native_events']),1)


if __name__ == '__main__':
    unittest.main()
