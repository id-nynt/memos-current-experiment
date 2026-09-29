"""Server-facing commands delegating to the existing paired batch lifecycle."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import batch_runner as batch
import phase8_matrix as matrix

ROOT = batch.ROOT
SMOKE_CASES = ('M001', 'M002', 'M003', 'M006', 'M011', 'M022', 'M044', 'M036', 'M052')


def selection(manifest, case=None, test_set=None):
    return batch.selected(manifest, [case] if case else
                          [c['case_id'] for c in manifest['cases'] if c['test_set'] == test_set] if test_set else None)


def inspect_results(directory, manifest, ids=None, derive=False):
    """Read-only verification. Never create/reset/dispatch a candidate or rewrite evidence."""
    directory = Path(directory).resolve()
    record = batch.read(directory / 'batch.json') if (directory / 'batch.json').exists() else None
    if record and record['identity']['matrix_sha256'] != matrix.sha(manifest):
        raise ValueError('Batch belongs to another matrix')
    if record and ids and record['identity']['selection'] != [c['case_id'] for c in batch.selected(manifest, ids)]:
        raise ValueError('Requested selection differs from recorded batch')
    cases = batch.selected(manifest, ids or (record['identity']['selection'] if record else None))
    mode = record['identity'].get('execution_mode', 'study') if record else None
    rows, derived = [], []
    for case in cases:
        arms = []
        for arm in case['treatments']:
            path = directory / case['case_id'] / arm
            state_path = path / 'status.json'
            row = dict(treatment=arm, status='pending', native_outcome=None)
            if path.exists():
                row['status'] = 'incomplete'
                try:
                    state = batch.read(state_path)
                    row['native_outcome'] = state.get('result', {}).get('native_outcome')
                    if state.get('case_id') != case['case_id'] or state.get('treatment') != arm or state.get('spec_sha256') != case['spec_sha256']:
                        raise ValueError('Status identity mismatch')
                    if state['status'] == 'valid':
                        if batch.hashes(path / 'evidence') != batch.read(path / 'evidence-seal.json'):
                            raise ValueError('Evidence seal changed')
                        if batch.digest(path / 'metrics.json') != state['result']['metrics_sha256']:
                            raise ValueError('Metrics hash changed')
                        if batch.digest(path / 'metric-spec.json') != state['result'].get('metric_spec_sha256'):
                            raise ValueError('Metric specification hash missing/changed')
                        saved = batch.read(path / 'metrics.json')
                        if saved.get('execution_mode', 'study') != mode:
                            raise ValueError('Validation/study attribution mismatch')
                        if not state.get('final_reset', {}).get('verified'):
                            raise ValueError('Final reset not verified')
                        for folder, key in (('reset_before', 'baseline'), ('reset_after', 'final_reset')):
                            receipt = path / folder / 'baseline-receipt.json'
                            if receipt.exists() and batch.digest(receipt) != state.get(key, {}).get('receipt_sha256'):
                                raise ValueError('Portable reset receipt changed')
                        if derive:
                            spec = batch.read(path / 'metric-spec.json')
                            if Path(spec['evidence_directory']).resolve() != path / 'evidence':
                                raise ValueError('Metric input relocated; preserve original paths')
                            fresh = batch.metrics.normalize(spec)
                            for key in ('identity', 'boundaries', 'reliability', 'resilience', 'cost', 'validity', 'normalized_requests', 'staging', 'exact_count_measurement'):
                                if fresh.get(key) != saved.get(key):
                                    raise ValueError('Re-derived metric differs: ' + key)
                            derived.append(saved)
                        row['status'] = 'valid'
                    elif state['status'] == 'invalid_or_incomplete':
                        row['native_status'] = state['status']
                        row['reason'] = state.get('error', 'Unresolved attempt; inspect retained evidence')
                        if (path / 'metrics.json').exists():
                            validity = batch.read(path / 'metrics.json').get('validity', {})
                            if isinstance(validity, dict) and validity.get('status') == 'invalid':
                                row['status'] = 'invalid'
                    row['step'] = state.get('step')
                except OSError as exc:
                    row.update(status='incomplete', reason=str(exc))
                except (ValueError, KeyError) as exc:
                    row.update(status='invalid', reason=str(exc))
            arms.append(row)
        statuses = {r['status'] for r in arms}
        status = 'valid' if statuses == {'valid'} else 'pending' if statuses == {'pending'} else 'invalid' if 'invalid' in statuses else 'incomplete'
        rows.append(dict(case_id=case['case_id'], status=status, arms=arms))
    counts = {name: sum(r['status'] == name for r in rows) for name in ('valid', 'invalid', 'incomplete', 'pending')}
    value = dict(directory=str(directory), execution_mode=mode, counts=counts, cases=rows,
                 completed_pairs=counts['valid'], active_lock=(directory / 'active.lock').exists(),
                 stop_requested=(directory / 'STOP').exists(), candidate_execution=False)
    if derive:
        # Validation rows are deliberately refused by the primary aggregator.
        value['aggregate'] = batch.metrics.aggregate(derived) if mode == 'study' else None
        value['validation_metrics_checked'] = len(derived) if mode == 'validation' else 0
        value['all_selected_valid'] = counts['valid'] == len(rows)
    return value


def artifacts(operation, directory):
    """Reuse native frozen-image export/import and its exact image/SHA checks."""
    from frozen_artifacts import verify_bundle, require_linux_store
    if operation in ('verify', 'import'):
        report = verify_bundle(directory, batch.read(ROOT / 'protocol/frozen-releases.json'))
        print(json.dumps(report, indent=2), flush=True)
        if operation == 'verify':
            return 0
        # Inspect capabilities, not the images: a fresh daemon need not have them yet.
        info = json.loads(subprocess.check_output(['docker', 'info', '--format', '{{json .}}'], text=True))
        require_linux_store(info)
    code = subprocess.call([sys.executable, '-B', str(ROOT / 'memos-current/experiment/manage.py'),
                            'images', operation, str(Path(directory).resolve())])
    if code == 0 and operation == 'export':
        verify_bundle(directory, batch.read(ROOT / 'protocol/frozen-releases.json'))
    return code


def draft_config(mode, campaign=None):
    value=batch.read(ROOT/'protocol/batch-readiness.template.json')
    value.update(execution_mode=mode,matrix_sha256=matrix.sha(batch.read(matrix.MANIFEST)),
                 source_hashes=batch.source_hashes(),operator_manifest_sha256=batch.digest(ROOT/'protocol/operator-revisions.json'),
                 drivers={arm:[sys.executable,'-B',str(ROOT/'tools/experiment.py')] for arm in ('conventional','bdi')})
    if mode=='validation':
        value['validation_campaign']=campaign
        batch.claim_ledger(batch.read(matrix.MANIFEST),value)
    value['server_evidence']=None
    value['smoke_evidence']=[]
    return value


def approve_faults(directory, output, config):
    """Adapt a genuinely verified healthy batch into the existing approval interface."""
    manifest=batch.read(matrix.MANIFEST)
    batch.readiness(config,manifest,live=True)
    result=inspect_results(directory,manifest,derive=True)
    snapshot=batch.read(Path(directory)/'batch.json')['configuration']
    if any(snapshot.get(k)!=config.get(k) for k in ('source_hashes','operator_manifest_sha256','controlled_seed_sha256','measurement_policy')):
        raise ValueError('Healthy validation belongs to a different source/control/seed/policy')
    if result['execution_mode']!='validation' or not result['all_selected_valid']:
        raise ValueError('Verified validation batch required')
    if any(batch.selected(manifest,[r['case_id']])[0]['spec']['episodes'] for r in result['cases']):
        raise ValueError('Only a no-fault reference can establish healthy approval')
    for row in result['cases']:
        metrics=batch.read(Path(directory)/row['case_id']/'bdi/metrics.json')
        if metrics['reliability']['native_outcome']!='achieved' or metrics['reliability']['candidate_delivered'] is not True:
            raise ValueError('Native achieved outcome and independently healthy v2 required')
    pins=batch.read(ROOT/'protocol/operator-revisions.json')['bdi']
    from experiment import runtime
    target=runtime(pins,'bdi')
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    lifecycle=dict(healthy_verified=True,reset_verified=True,control_sha=pins['control_sha'],
                   protocol_sha256=batch.digest(target/'experiment/protocol.json'),
                   authority='Validated sealed paired no-fault batch; no outcome fabricated',batch=str(Path(directory).resolve()))
    batch.save(output/'healthy-lifecycle.json',lifecycle,new=True)
    batch.save(output/'validation.json',result,new=True)
    operator=dict(approach='bdi',repository=pins['repository'],control_sha=pins['control_sha'],control_ref=pins['control_ref'],
                  state=str(Path(batch.read(target/'experiment/runtime.json')['state']).expanduser()))
    batch.save(output/'operator.json',operator,new=True)
    return subprocess.call([sys.executable,'-B',str(target/'experiment/scripts/approve.py'),
        '--config',str((output/'operator.json').resolve()),'--healthy-lifecycle',str((output/'healthy-lifecycle.json').resolve()),'--approve-bdi-faults'])


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='action', required=True)
    check = sub.add_parser('server-check')
    check.add_argument('--target', action='store_true', help='Perform read-only checks on this Linux server')
    check.add_argument('--output', type=Path)
    check.add_argument('--config', type=Path, default=ROOT / 'protocol/batch-readiness.template.json')
    item=sub.add_parser('prepare-config')
    item.add_argument('--mode',choices=['validation','study'],required=True)
    item.add_argument('--campaign')
    item.add_argument('--output',type=Path,required=True)
    item=sub.add_parser('approve-faults')
    item.add_argument('--healthy-batch',type=Path,required=True)
    item.add_argument('--config',type=Path,required=True)
    item.add_argument('--output',type=Path,required=True)
    for action in ('run-case', 'run-set', 'resume-set'):
        item = sub.add_parser(action)
        item.add_argument('selection', choices=['A', 'B'] if action != 'run-case' else None)
        item.add_argument('--config', type=Path, default=ROOT / 'protocol/batch-readiness.template.json')
        item.add_argument('--directory', type=Path, required=True)
        item.add_argument('--dry-run', action='store_true')
    for action in ('status', 'validate-results'):
        item = sub.add_parser(action)
        item.add_argument('--directory', type=Path, required=True)
        item.add_argument('--output', type=Path)
    item = sub.add_parser('artifacts')
    item.add_argument('operation', choices=['export', 'import', 'verify'])
    item.add_argument('directory', type=Path)
    a = p.parse_args(argv)
    if a.action=='prepare-config':
        batch.save(a.output,draft_config(a.mode,a.campaign),new=True)
        print('Non-executable review draft created; attach target evidence and approve only verified gates.')
        return 0
    if a.action=='approve-faults':
        return approve_faults(a.healthy_batch,a.output,batch.read(a.config))
    if a.action == 'artifacts':
        return artifacts(a.operation, a.directory)
    manifest = batch.read(matrix.MANIFEST)
    matrix.validate(manifest)
    if a.action == 'server-check':
        from server_readiness import report
        value = report(a.target, batch.read(a.config))
        code = 1 if any(r['status'] == 'BLOCKER' for r in value['checks']) else 0
    elif a.action in ('status', 'validate-results'):
        value = inspect_results(a.directory, manifest, derive=a.action == 'validate-results')
        code = 1 if a.action == 'validate-results' and not value['all_selected_valid'] else 0
    else:
        cases = selection(manifest, case=a.selection if a.action == 'run-case' else None,
                          test_set=a.selection if a.action != 'run-case' else None)
        ids = [c['case_id'] for c in cases]
        config = batch.read(a.config)
        if a.dry_run:
            value = dict(validation=batch.validate_plan(manifest), operations=batch.plan(manifest, ids),
                         paired_conditions=len(cases), candidate_executions=2*len(cases),
                         execution_mode=config.get('execution_mode', 'study'), execution=False)
            batch.save(a.directory / 'dry-run.json', value, new=True)
            print(json.dumps({k:v for k,v in value.items() if k != 'operations'}, indent=2))
            return 0
        if a.action != 'run-case' and config.get('execution_mode', 'study') != 'study':
            p.error('Set A/B commands require study mode; smoke uses run-case')
        if a.action == 'resume-set':
            if not (a.directory / 'batch.json').exists():p.error('Resume requires an existing batch')
            if (a.directory / 'STOP').exists():p.error('Remove the acknowledged STOP request before resume')
        elif (a.directory / 'batch.json').exists():
            p.error('Existing batch: use resume-set; never replay a claimed smoke case')
        batch.run(manifest, config, a.directory, ids)
        value = inspect_results(a.directory, manifest, ids)
        code = 0
    if getattr(a, 'output', None):batch.save(a.output, value, new=True)
    print(json.dumps({k:v for k,v in value.items() if k!='source_hashes'}, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
