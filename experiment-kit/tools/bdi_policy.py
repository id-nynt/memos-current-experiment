"""Resolve pinned BDI policy without dispatch or regeneration (Issue 2B.1)."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

F = 'bdi-cicd-framework/'
INPUTS = {'pipeline': F+'models/01_pipeline.yaml', 'goal': F+'models/02_goal.yaml',
          'policy': F+'config/controller_policy.yaml', 'bindings': F+'config/runtime_bindings.yaml',
          'workflow': F+'models/03_workflow_model.yaml', 'agent': F+'bdi/controller_agent.asl',
          'generation': F+'models/generation-manifest.json', 'protocol': 'experiment/protocol.json',
          'paired': 'experiment/scripts/rq1-s4r-s5r.json',
          'measurement': 'experiment/measurement/contract.json', 'prometheus': 'experiment/prometheus.yml',
          'runtime': 'experiment/runtime.json'}


def digest(text):
    return hashlib.sha256(text.replace('\r\n', '\n').encode('utf-8')).hexdigest()


def resolve_values(data, fixed, scenario, environ):
    """Compare only declared mirrors; independent safety/measurement budgets stay separate."""
    policy, bindings, protocol = data['policy'], data['bindings']['telemetry'], data['protocol']
    execution, shared = policy['execution'], protocol['policy']
    checks = []

    def agree(name, values):
        if any(value != values[0] for value in values[1:]):
            raise ValueError('BDI policy disagreement: '+name+' = '+repr(values))
        checks.append(name)
        return values[0]

    health = {
        'max_error_fraction': agree('error threshold: agent / worker / record / opportunity',
            [policy['telemetry_constraints']['error_rate_high_gt'], shared['max_error_fraction'],
             fixed['analysis_error_fraction']]),
        'max_p95_ms': agree('latency threshold: agent / worker / record',
            [policy['telemetry_constraints']['latency_p95_ms_high_gt'], shared['max_p95_ms'], fixed['analysis_p95_ms']]),
        'max_age_seconds': agree('source freshness: agent / worker', [bindings['max_age_seconds'], shared['max_age_seconds']]),
    }
    windows = []
    for name in ('error_rate_query', 'latency_p95_ms_query'):
        matches = re.findall(r'\[(\d+)s\]', bindings['metrics'][name])
        if not matches:
            raise ValueError('Unreviewed metric window syntax: '+name)
        windows.extend(map(int, matches))
    health['metric_window_seconds'] = agree('metric window: bindings / protocol / worker query',
        [shared['window_seconds'], fixed['worker_metric_window_seconds'], *windows])
    normalize = lambda queries: {k: re.sub(r'\s+', '', v) for k,v in queries.items()}
    agree('metric definitions: agent bindings / reviewed worker expressions',
          [normalize(bindings['metrics']), normalize(fixed['worker_metric_queries'])])
    for environment in ('staging', 'production'):
        port = data['runtime']['bdi_production_port'] + (environment == 'staging')
        agree(environment+' observation targets: bindings / worker runtime',
              [bindings['environments'][environment], {'ready_url':f'http://127.0.0.1:{port}/ready',
                                                       'prometheus_url':f'http://127.0.0.1:{port+4000}'}])
    agree('protocol retry mirror', [data['pipeline']['execution']['max_retries'], shared['job_retries']])
    agree('protocol reconsideration mirror', [policy['rollback_reconsideration']['production']['window_seconds'], shared['reconsideration_seconds']])
    agree('traffic cadence mirror', [shared['cycle_interval_seconds'], fixed['traffic_cycle_seconds']])
    agree('passive sample interval: native / contract / paired',
          [protocol['observation']['interval_seconds'], data['measurement']['sampling']['interval_seconds'], data['paired']['sample_interval_seconds']])
    agree('endpoint window: observer / paired contract', [fixed['endpoint_window_seconds'], data['paired']['endpoint_window_seconds']])
    agree('endpoint coverage: observer / paired contract', [fixed['endpoint_coverage_seconds'], data['paired']['endpoint_coverage_seconds']])
    agree('passive HTTP timeout: implementation / measurement contract',
          [fixed['measurement']['http_timeout_seconds'], data['measurement']['sampling']['http_timeout_seconds']])
    agree('passive Docker timeout: implementation / measurement contract',
          [fixed['measurement']['docker_timeout_seconds'], data['measurement']['sampling']['docker_inspect_timeout_seconds']])
    # These are compiler projections, not independent execution policy.
    agree('generated execution projection', [data['workflow']['execution'], {**data['pipeline']['execution'], **execution}])
    agree('generated goal projection', [data['workflow']['goals'], data['goal']['goal']])
    agree('generated threshold projection', [data['workflow']['bindings']['thresholds'], policy['telemetry_constraints']])
    agree('generated telemetry projection',
          [{k: data['workflow']['bindings'][k] for k in bindings}, bindings])
    agree('generated observation projection', [data['workflow']['observation_schema']['before'], policy['observation']['before']])
    agree('generated post-observation projection', [data['workflow']['observation_schema']['after'], policy['observation']['after']])
    agree('generated recovery projection', [data['workflow']['recovery_policy'], policy['recovery_policy']])
    agree('generated reconsideration projection', [data['workflow']['rollback_reconsideration'], policy['rollback_reconsideration']])
    def env_number(name, default):
        value = environ.get(name, str(default)) or str(default)
        if not re.fullmatch(r'[1-9][0-9]*', value):
            raise ValueError(name+' must be a positive integer without whitespace')
        try:
            result = int(value)
        except ValueError as exc:
            raise ValueError(name+' must be a positive integer') from exc
        if result <= 0:
            raise ValueError(name+' must be a positive integer')
        return result
    revised = scenario in ('S4R', 'S5R')
    return {
        'agreement_checks': checks, 'shared_health_definition': health,
        'resolved_limits': {
            'retry_budget_per_job': data['pipeline']['execution']['max_retries'],
            'retry_interval_seconds': execution['retry_interval_seconds'],
            'observation_attempts': execution['observation_attempts'],
            'observation_interval_seconds': execution['observation_interval_seconds'],
            'observation_timeout_seconds': execution['observation_timeout_seconds'],
            'reconsideration': policy['rollback_reconsideration'],
            'reconciliation_attempts': execution['reconciliation_attempts'],
            'reconciliation_interval_seconds': execution['reconciliation_interval_seconds'],
            'job_wait_minutes': env_number('BDI_JOB_TIMEOUT_MINUTES', 20),
            'worker_operation_timeout_minutes': fixed['safety']['operation_timeout_minutes'],
            'other_worker_job_timeout_minutes': None,
            'other_worker_timeout_note': 'Job/reusable CI jobs declare no explicit timeout-minutes; no platform-default value is asserted here.',
            'goal_constraints': data['goal']['goal'],
            'overall_campaign_deadline_seconds': None,
            'overall_batch_deadline_seconds': None,
            'note': 'Per-action/sequence limits; blocking calls and remote workers may outlive controller waits. No hard aggregate wall-clock guarantee.'},
        'framework_decision_policy': {'execution': data['workflow']['execution'], 'goals': data['workflow']['goals'],
            'observation': policy['observation'], 'recovery': policy['recovery_policy'],
            'reconsideration': policy['rollback_reconsideration'], 'telemetry_bindings': bindings},
        'adapter_worker_safety': {'monitor_seconds': shared['deadline_seconds'],
            'monitor_interval_seconds': shared['interval_seconds'], 'healthy_samples': shared['consecutive_healthy'],
            'warmup_seconds': shared['warmup_seconds'], 'fixed_checks': fixed['safety'],
            'github_poll_seconds': env_number('BDI_POLL_SECONDS', 5),
            'job_wait_minutes': env_number('BDI_JOB_TIMEOUT_MINUTES', 20)},
        'experiment_measurement': {'sample_interval_seconds': protocol['observation']['interval_seconds'],
            'followup_seconds': protocol['observation']['followup_seconds'],
            'endpoint_seconds': data['paired']['endpoint_seconds'] if revised else protocol['observation']['followup_seconds'],
            'fixed_checks': fixed['measurement'], 'prometheus': data['prometheus']['global'],
            'contract_sampling': data['measurement']['sampling'],
            'paired_horizon_contract': {k:data['paired'][k] for k in ('endpoint_seconds','endpoint_window_seconds','endpoint_coverage_seconds','sample_interval_seconds')}},
        'horizons': {
            'controller': 'controller_started through controller_finished in native controller journal; missing/ambiguous bounds = unknown',
            'bdi_observation': 'Only native percepts/decisions inside controller bounds; configured per-sequence limits, optional pre-rollback window; no post-terminal monitoring',
            'worker': 'Each correlated GitHub job/operation start through completion; may outlive an uncertain controller; completion is not controller acceptance',
            'passive': ('Endpoint at fault activation + paired endpoint_seconds; sampling ends at max(controller return, endpoint, fault expiry)'
                        if revised else 'S3-S5 endpoint max(controller return, fault activation + followup); other scenarios controller return + followup'),
            'overall_campaign_deadline': None},
        'analysis_limitations': ['Native record.json mixes layers and is not BDI-attribution authority.',
            'Use horizon-attribution.json for native decision counts; endpoint.json remains separately labelled experimental outcome.',
            'No observed restoration alone proves agent-caused recovery. Missing terminal evidence never extends agent lifetime.'],
    }


def report(workspace, spec, scenario='S0', environ=None):
    # PyYAML is already a BDI prerequisite; conventional commands never import it.
    import yaml
    workspace = Path(workspace)
    contract_name = spec.get('policy_contract', 'protocol/bdi-policy-contract.json')
    if contract_name not in ('protocol/bdi-policy-contract.json', 'protocol/bdi-policy-final-source.json'):
        raise ValueError('Unreviewed policy contract selection')
    contract_path = workspace/contract_name
    contract = json.loads(contract_path.read_text(encoding='utf-8'))
    if contract['schema_version'] != 1:
        raise ValueError('Unsupported BDI policy contract')
    repo = workspace/spec['checkout']
    texts = {}
    for path in sorted(set(INPUTS.values()) | set(contract['reviewed_code_sha256'])):
        texts[path] = subprocess.check_output(['git', '-C', str(repo), 'show', spec['control_sha']+':'+path]).decode('utf-8').replace('\r\n', '\n')
    for path, expected in contract['reviewed_code_sha256'].items():
        if digest(texts[path]) != expected:
            raise ValueError('Unreviewed fixed-policy consumer: '+path+'; review ownership contract before execution')
    data = {name: yaml.safe_load(texts[path]) for name, path in INPUTS.items() if name not in ('agent', 'generation')}
    result = resolve_values(data, contract['fixed_semantics'], scenario, os.environ if environ is None else environ)
    generation = json.loads(texts[INPUTS['generation']])
    for name in ('pipeline', 'goal', 'policy', 'bindings'):
        if digest(texts[INPUTS[name]]) != generation['inputs'][name]['sha256']:
            raise ValueError('Stale generated BDI policy input: '+name)
    for name, key in [('workflow','workflow_sha256'), ('agent','generated_agent_sha256')]:
        if digest(texts[INPUTS[name]]) != generation[key]:
            raise ValueError('Stale generated BDI policy artifact: '+name)
    result.update(schema_version=1, control_sha=spec['control_sha'], scenario=scenario,
                  status='consistent', contract_sha256=hashlib.sha256(contract_path.read_bytes()).hexdigest(),
                  source_sha256={path: digest(text) for path,text in texts.items()},
                  scope='Pinned BDI operator path only; read-only resolution, not runtime health verification')
    if contract.get('timing_contract') == 'memos-final-phase6-v1':
        if data['protocol']['observation']['followup_seconds'] != 300:
            raise ValueError('Final policy selection has historical observation timing')
        result['horizons']['passive'] = 'Declared runtime activation (otherwise native terminal) + 300 seconds; collection never extends the endpoint'
    return result
