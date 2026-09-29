"""Download exported experiment bundles, verify and extract, then review locally.

Read-only on the server. Never dispatches, resets, exports, or approves a study.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import sys

from export_results import verify
import phase8_matrix as matrix

GROUPS = ('identity', 'boundaries', 'reliability', 'resilience', 'cost', 'validity',
          'exact_count_measurement', 'staging', 'episodes')


def read(path):
    def reject(value):
        raise ValueError('Non-finite JSON number: ' + value)
    return json.loads(Path(path).read_text(encoding='utf-8-sig'), parse_constant=reject)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')


def safe_member(name):
    path = PurePosixPath(name)
    if (path.is_absolute() or str(path) != name or '\\' in name or ':' in name
            or any(p in ('.', '..') or p.endswith((' ', '.')) for p in path.parts)
            or any(p.split('.')[0].upper() in {'CON','PRN','AUX','NUL',
                *('COM'+str(n) for n in range(1,10)), *('LPT'+str(n) for n in range(1,10))} for p in path.parts)):
        raise ValueError('Unsafe/nonportable archive path: ' + name)
    return path


def extract_verified(bundle, destination):
    manifest = verify(bundle)
    with tarfile.open(bundle) as archive:
        names = set()
        members = archive.getmembers()
        for member in members:
            safe_member(member.name)
            if not member.isfile() or member.name.casefold() in names:
                raise ValueError('Non-file or duplicate archive member')
            names.add(member.name.casefold())
        if sum(m.size for m in members) > shutil.disk_usage(destination.parent).free:
            raise ValueError('Not enough local disk space for extraction')
        destination.mkdir()
        for member in members:
            target = destination.joinpath(*PurePosixPath(member.name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                shutil.copyfileobj(archive.extractfile(member), stream)
    # Check extracted bytes too. Do not change paths inside provenance documents.
    for name, expected in manifest['files'].items():
        if digest(destination/'results'/name) != expected:
            raise ValueError('Extracted file checksum mismatch: ' + name)
    return manifest


def remote_sources(server, remotes):
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*(?:@[A-Za-z0-9][A-Za-z0-9_.-]*)?', server or ''):
        raise ValueError('--server must be USER@HOST or an SSH alias (no shell syntax)')
    for remote in remotes:
        if not re.fullmatch(r'(?:~/|/)[A-Za-z0-9_./-]+\.tar\.gz', remote):
            raise ValueError('Use an absolute or ~/ Linux .tar.gz path without spaces or shell syntax')
        if '..' in PurePosixPath(remote).parts:
            raise ValueError('Remote path must not contain ..')
    return [server+':'+remote for remote in remotes]


def flatten(value, prefix='', result=None):
    result = {} if result is None else result
    if isinstance(value, dict):
        for key, item in value.items():
            flatten(item, prefix+'.'+key if prefix else key, result)
    else:
        result[prefix] = json.dumps(value, ensure_ascii=False) if isinstance(value, list) else value
    return result


def check_bundle(root, bundle_manifest, cases, expected_mode):
    errors, warnings, rows = [], [], []
    def require(ok, message):
        if not ok: errors.append(message)
    batch = read(root/'results/batch.json')
    report = bundle_manifest['validation']
    session=batch['configuration'].get('image_session')
    if session:
        body={k:v for k,v in session.items() if k!='sha256'}
        require(hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':')).encode()).hexdigest()==session.get('sha256'),'Image session checksum mismatch')
    ids = batch['identity']['selection']
    require(len(ids)==len(set(ids)), 'Duplicate cases in batch selection')
    require(batch['identity']['matrix_sha256']==matrix.sha(matrix_document()), 'Scenario matrix differs from the local protocol')
    require(batch['identity'].get('execution_mode')==expected_mode, 'Wrong execution mode: expected '+expected_mode)
    require(report.get('execution_mode')==expected_mode, 'Server validation mode mismatch')
    require(report.get('all_selected_valid') is True, 'Server validation did not pass every selected case')
    require(report.get('completed_pairs')==len(ids), 'Server validated pair count mismatch')
    require({r['case_id'] for r in report.get('cases',[])}==set(ids), 'Server validation selection mismatch')
    for case_id in ids:
        if case_id not in cases:
            errors.append('Unexpected case: '+str(case_id)); continue
        case = cases[case_id]
        report_row = next((r for r in report.get('cases',[]) if r['case_id']==case_id), {})
        require(report_row.get('status')=='valid', case_id+': server case not valid')
        require({a.get('treatment') for a in report_row.get('arms',[])}=={'conventional','bdi'}, case_id+': server treatment pair missing')
        for arm in ('conventional','bdi'):
            label=case_id+'/'+arm; folder=root/'results'/case_id/arm
            try:
                state=read(folder/'status.json'); metrics=read(folder/'metrics.json')
                spec=read(folder/'metric-spec.json'); declaration=read(folder/'declaration.json')
                require(state.get('status')=='valid', label+': execution not valid')
                require(state.get('case_id')==case_id and state.get('treatment')==arm, label+': status identity mismatch')
                require(state.get('spec_sha256')==case['spec_sha256'], label+': scenario fingerprint mismatch')
                require(declaration.get('case')==case, label+': scenario/seed declaration mismatch')
                require(digest(folder/'metrics.json')==state['result']['metrics_sha256'], label+': metrics seal mismatch')
                require(digest(folder/'metric-spec.json')==state['result']['metric_spec_sha256'], label+': specification seal mismatch')
                require(spec.get('case_id')==case_id and spec.get('treatment')==arm, label+': metric specification identity mismatch')
                seal=read(folder/'evidence-seal.json')
                actual={p.relative_to(folder/'evidence').as_posix():digest(p) for p in (folder/'evidence').rglob('*') if p.is_file()}
                require(bool(actual) and seal==actual, label+': evidence seal incomplete/changed')
                for subdir, key in (('reset_before','baseline'),('reset_after','final_reset')):
                    reset=state.get(key,{})
                    require(reset.get('verified') is True, label+': '+subdir+' not verified')
                    require(reset.get('seed_sha256')==batch['configuration'].get('controlled_seed_sha256'), label+': reset seed mismatch')
                    receipt=folder/subdir/'baseline-receipt.json'
                    if receipt.exists():
                        require(digest(receipt)==reset.get('receipt_sha256'), label+': reset receipt hash mismatch')
                    else:
                        warnings.append(label+': portable '+subdir+' receipt absent; check original server receipt')
                for group in GROUPS[:7]:
                    require(isinstance(metrics.get(group),dict), label+': missing metric group '+group)
                identity=metrics['identity']; reliability=metrics['reliability']; cost=metrics['cost']; validity=metrics['validity']
                if session:
                    release=session['frozen_releases']['releases']['v2']
                    require(identity.get('application_sha')==release['application_sha'] and identity.get('frozen_oci_digest')==release['image_id'],label+': candidate differs from shared server image freeze')
                require(identity.get('case_id')==case_id and identity.get('treatment')==arm, label+': metric identity mismatch')
                require(metrics.get('execution_mode')==expected_mode, label+': metric execution mode mismatch')
                require(validity.get('status')=='valid' and validity.get('observation_complete') is True and validity.get('evidence_complete') is True, label+': metric completeness/validity failed')
                total=reliability.get('requests_total'); failed=reliability.get('requests_failed'); successful=reliability.get('requests_successful')
                counts=all(type(x) is int and x>=0 for x in (total,failed,successful)) and total>0
                require(counts and total==failed+successful, label+': request counts do not reconcile')
                rate=reliability.get('error_rate')
                require(counts and isinstance(rate,(int,float)) and math.isfinite(rate) and math.isclose(rate,failed/total), label+': request error rate mismatch/missing')
                require(isinstance(cost.get('candidate_seconds'),(int,float)) and cost['candidate_seconds']>=0, label+': candidate duration missing/invalid')
                for metric in ('availability_estimate','coverage'):
                    number=reliability.get(metric)
                    require(isinstance(number,(int,float)) and 0<=number<=1, label+': '+metric+' missing/invalid')
                workload=metrics['exact_count_measurement']['workload']
                for env in ('production','staging') if case['parameters']['stage']=='staging' else ('production',):
                    account=workload[env]
                    require(account.get('requests_started',0)>0 and account.get('requests_started')==account.get('requests_completed') and account.get('pending_or_missing_completions')==0, label+': '+env+' request accounting incomplete')
                    require(isinstance(account.get('request_duration_ms'),dict), label+': '+env+' latency distribution missing')
                if case['parameters']['stage']=='staging':
                    require(isinstance(metrics.get('staging'),dict), label+': staging metrics missing')
                if expected_mode=='validation' and not case['parameters']['episodes'] and case['analysis_stratum']=='service':
                    require(failed==0, label+': healthy reference has request errors')
                    require(reliability.get('endpoint_health') is True and reliability.get('candidate_delivered') is True, label+': healthy reference did not finish healthy v2')
                    require(reliability.get('native_outcome') in ('success','achieved'), label+': healthy reference native outcome was not successful')
                rows.append(dict(bundle=root.name, case_id=case_id, treatment=arm,
                    metrics_file=str((folder/'metrics.json').relative_to(root.parent.parent)),
                    metrics={key:metrics[key] for key in GROUPS if key in metrics}))
            except (KeyError, TypeError, ValueError, OSError) as exc:
                errors.append(label+': missing/malformed evidence: '+str(exc))
    return dict(selection=ids, configuration=batch['configuration'], errors=errors, warnings=warnings, rows=rows)


def matrix_document():
    value=read(matrix.MANIFEST); matrix.validate(value)
    return value


def review(extracted, expected_cases, expected_sets, output, expected_batches=None):
    design=matrix_document(); cases={c['case_id']:c for c in design['cases']}
    mode='study' if expected_sets or expected_batches else 'validation'
    expected={c['case_id'] for c in design['cases'] if c['test_set'] in expected_sets} if expected_sets else set(expected_cases)
    if expected_batches:
        import study_batches
        allocation=study_batches.load()
        expected={r['case_id'] for b in allocation['batches'] if b['batch_id'] in expected_batches for r in b['cases']}
    if not expected or expected-set(cases): raise ValueError('Unknown/empty expected case selection')
    checks=[check_bundle(root, manifest, cases, mode) for root,manifest in extracted]
    errors=[e for c in checks for e in c['errors']]; warnings=[e for c in checks for e in c['warnings']]
    selection=[case for c in checks for case in c['selection']]
    if len(selection)!=len(set(selection)): errors.append('Duplicate case across bundles')
    if set(selection)!=expected: errors.append('Expected case selection differs: missing='+str(sorted(expected-set(selection)))+' extra='+str(sorted(set(selection)-expected)))
    for check in checks[1:]:
        for key in ('source_hashes','matrix_sha256','operator_manifest_sha256','controlled_seed_sha256','measurement_policy','image_session','study_batches_sha256','kit_commit'):
            if check['configuration'].get(key)!=checks[0]['configuration'].get(key): errors.append('Bundles differ in '+key)
    if expected_batches:
        for check in checks:
            if check['configuration'].get('study_batches_sha256')!=digest(study_batches.PATH):errors.append('Allocation fingerprint missing/different')
            if not check['configuration'].get('image_session'):errors.append('Shared server image freeze missing')
            if not re.fullmatch(r'[0-9a-f]{40}',check['configuration'].get('kit_commit','')):errors.append('Published kit commit missing/invalid')
            valid_selections=[[r['case_id'] for r in b['cases']] for b in allocation['batches'] if b['batch_id'] in expected_batches]
            if check['selection'] not in valid_selections:errors.append('Bundle differs from declared batch order/selection')
    rows=[row for c in checks for row in c['rows']]
    if len(rows)!=2*len(expected): errors.append('Expected '+str(2*len(expected))+' complete treatment metric records; found '+str(len(rows)))
    report=dict(status='CHECKS_PASSED' if not errors else 'NEEDS_ATTENTION', execution_mode=mode,
                expected_pairs=len(expected), metric_records=len(rows), errors=errors, warnings=warnings,
                human_review_required=True, study_approved=False,
                limitation='Checks downloaded integrity, selections, seals, metric fields and consistency. Raw metric derivation remains the server validator; null/not-applicable recovery is not failure.',
                records=rows)
    save(output/'review.json',report)
    flat=[dict(bundle=r['bundle'], **flatten(r['metrics'])) for r in rows]
    columns=sorted({key for r in flat for key in r})
    with (output/'metrics.csv').open('x',newline='',encoding='utf-8-sig') as stream:
        writer=csv.DictWriter(stream,fieldnames=columns);writer.writeheader();writer.writerows(flat)
    lines=['# Local experiment result review','',report['status'],'',
           f"Expected pairs: {len(expected)}. Treatment metric records: {len(rows)}. Mode: {mode}.",'',
           'No study approval was changed. Review these measurements before continuing.','',
           '| Case | Treatment | Requests | Failed | Error rate | Availability estimate | Candidate seconds | Final measured state | Native outcome |',
           '|---|---|---:|---:|---:|---:|---:|---|---|']
    for row in rows:
        r=row['metrics']['reliability']; c=row['metrics']['cost']
        values=[row['case_id'],row['treatment'],r.get('requests_total'),r.get('requests_failed'),r.get('error_rate'),r.get('availability_estimate'),c.get('candidate_seconds'),r.get('endpoint_release'),r.get('native_outcome')]
        lines.append('| '+' | '.join(str(v).replace('|','\\|').replace('\n',' ') for v in values)+' |')
    lines+=['','## Issues','']+(['- '+e for e in errors] or ['None found by these checks.'])
    lines+=['','## Items to inspect','']+['- '+w for w in warnings]
    lines+=['- Check source/image identity and the declared scenario/seed.',
            '- Check production request counts, errors, availability/coverage and latency distributions.',
            '- Check detection, retry/recovery/rollback, recovery time/censoring and measured final state.',
            '- Check candidate cost, workflow/job/retry/deployment counts and overhead definitions.',
            '- Check staging metrics separately and both verified v1 resets.',
            '- Healthy cases can have null recovery/detection times: no fault occurred. Do not replace null with zero.',
            '- Fault-case native failures can be valid results. A successful transfer does not imply a successful deployment.',
            '', 'Every recorded metric group is in review.json and metrics.csv. Original metrics and raw evidence remain in unpacked/.',
            '', report['limitation'], '', '## Original metric files','']
    lines+=['- ['+r['case_id']+' '+r['treatment']+']('+Path(r['metrics_file']).as_posix()+')' for r in rows]
    (output/'review.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(report['status']+': '+str(output/'review.md'))
    return 0 if not errors else 2


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--remote',nargs='+',help='One or more already exported .tar.gz paths on the Linux server')
    source.add_argument('--bundles',nargs='+',type=Path,help='Review already downloaded bundles without SSH')
    parser.add_argument('--server',help='USER@HOST or SSH alias; required with --remote')
    parser.add_argument('--port',type=int,default=22)
    parser.add_argument('--output',type=Path,required=True,help='New local directory; existing evidence is never overwritten')
    expected=parser.add_mutually_exclusive_group(required=True)
    expected.add_argument('--expect-case',nargs='+',help='Expected validation case IDs, e.g. M001')
    expected.add_argument('--expect-sets',nargs='+',choices=['A','B'],help='Expected completed study sets, e.g. A B')
    expected.add_argument('--expect-batches',nargs='+',choices=[f'batch-{n}' for n in range(1,6)],help='Expected independently completed 20-case batches')
    args=parser.parse_args(argv)
    if not 1<=args.port<=65535:parser.error('Invalid SSH port')
    sources=remote_sources(args.server,args.remote) if args.remote else args.bundles
    names=[PurePosixPath(p).name if isinstance(p,str) else p.name for p in (args.remote or args.bundles)]
    if len(set(n.casefold() for n in names))!=len(names):parser.error('Bundle filenames must be distinct')
    if any(not name.endswith('.tar.gz') for name in names):parser.error('Expected .tar.gz bundles')
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    (output/'archives').mkdir();(output/'unpacked').mkdir()
    try:
        extracted=[]
        for source,name in zip(sources,names):
            bundle=output/'archives'/name
            for suffix in ('','.sha256'):
                target=Path(str(bundle)+suffix)
                if args.remote:
                    subprocess.run(['scp','-P',str(args.port),'--',str(source)+suffix,str(target)],check=True)
                else:
                    shutil.copyfile(Path(str(source)+suffix),target)
            root=output/'unpacked'/name.removesuffix('.tar.gz')
            manifest=extract_verified(bundle,root)
            extracted.append((root,manifest))
        return review(extracted,args.expect_case or [],args.expect_sets or [],output,args.expect_batches)
    except (OSError,ValueError,KeyError,TypeError,tarfile.TarError,subprocess.CalledProcessError) as exc:
        save(output/'download-error.json',dict(status='FAILED',error=str(exc),server_modified=False))
        print('FAILED: '+str(exc)+'; partial files preserved in '+str(output),file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
