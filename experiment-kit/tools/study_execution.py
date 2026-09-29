"""Simple operator commands; every candidate uses batch_runner.run unchanged."""
import argparse
import copy
import json
from pathlib import Path
import sys
import subprocess
import time
import batch_runner as batch
import phase8_matrix as matrix
import server_execution as server
import study_batches

ROOT=batch.ROOT
SETUP=ROOT/'results/setup'


def reference(path):return dict(path=str(path.resolve()),sha256=batch.digest(path))


def configure_validation(parity):
    path=SETUP/'validation.json'
    if path.exists():
        batch.readiness(batch.read(path),batch.read(matrix.MANIFEST),live=True)
        return
    config=server.draft_config('validation','server-smoke')
    report=SETUP/'readiness.json'
    verified=batch.read(report)
    if not verified['target_checks'] or any(r['status'] in ('BLOCKER','REQUIRES TARGET-SERVER VALIDATION') for r in verified['checks']):raise ValueError('Target evidence failed')
    retained=SETUP/'readiness-for-validation.json';batch.save(retained,verified,new=True)
    if not batch.read(parity)['equal']:raise ValueError('Parity failed')
    import image_identity
    config.update(server_evidence=reference(retained),controlled_seed_sha256=batch.read(parity)['archive_sha256'],
                  image_session=image_identity.session(),study_batches_sha256=batch.digest(study_batches.PATH),
                  kit_commit=subprocess.check_output(['git','-C',str(ROOT.parent),'rev-parse','HEAD'],text=True).strip(),
                  parity_evidence=reference(parity),execution_authorized=True,environment_parity_verified=True,
                  clock_alignment_verified=True,exclusive_environment_verified=True,unresolved_blockers=[])
    batch.readiness(config,batch.read(matrix.MANIFEST),live=True)
    batch.save(path,config,new=True)


def checked(directory,ids):
    result=server.inspect_results(directory,batch.read(matrix.MANIFEST),ids,derive=True)
    if result['active_lock'] or not result['all_selected_valid']:raise ValueError('Invalid/incomplete or locked results: '+str(directory))
    batch.save(directory/'validation.json',result)
    return result


def execute(directory,ids,config):
    if (directory/'STOP').exists():raise ValueError('STOP is present; remove it only when ready to resume')
    batch.readiness(config,batch.read(matrix.MANIFEST),live=True)
    complete=False
    if (directory/'batch.json').exists():
        if batch.read(directory/'batch.json')['configuration']!=config:raise ValueError('Recorded run configuration differs')
        previous=server.inspect_results(directory,batch.read(matrix.MANIFEST),ids,derive=True)
        complete=previous['all_selected_valid'] and not previous['active_lock']
    # Existing valid arms are checked and skipped by the same native lifecycle.
    # Invalid/interrupted arms and unresolved locks remain blocked, never replayed.
    if not complete:batch.run(batch.read(matrix.MANIFEST),config,directory,ids)
    result=checked(directory,ids)
    n=len(ids);counts=result['counts']
    print(f"{counts['valid']}/{n} pairs completed\n{counts['valid']} valid\n{counts['invalid']} invalid\n{counts['incomplete']+counts['pending']} incomplete")
    return result


def healthy(directory):
    for arm in ('conventional','bdi'):
        metric=batch.read(directory/'M001'/arm/'metrics.json')['reliability']
        if (metric['requests_failed']!=0 or metric['requests_total']<=0 or metric['endpoint_health'] is not True
                or metric['candidate_delivered'] is not True or metric['native_outcome'] not in ('success','achieved')):
            raise ValueError('M001 healthy reference failed: '+arm)


def calibration(config):
    source=ROOT/'results/smoke/M001/M001/conventional/evidence/native-events.jsonl'
    events=[json.loads(s) for s in source.read_text(encoding='utf-8-sig').splitlines() if s.strip()]
    ceiling=batch.read(ROOT/'memos-current/experiment/config.json')['startup_timeout_seconds']
    metrics=batch.read(source.parent.parent/'metrics.json')
    # Native trial attribution was already verified by the metric normalizer.
    trial=metrics['identity']['trial_id'] if 'trial_id' in metrics['identity'] else None
    durations={}
    for environment in ('staging','production'):
        start=[e for e in events if e.get('event')=='startup_start' and e.get('environment')==environment]
        end=[e for e in events if e.get('event')=='startup_ready' and e.get('environment')==environment]
        if len(start)!=1 or len(end)!=1 or start[0]['trial_id']!=end[0]['trial_id'] or (trial and start[0]['trial_id']!=trial):raise ValueError('Missing/ambiguous healthy startup bounds')
        elapsed=batch.metrics.duration(start[0]['timestamp'],end[0]['timestamp'])
        if elapsed is None or elapsed>=ceiling or start[0]['timeout_seconds']!=ceiling:raise ValueError('Startup ceiling failed; do not widen it to pass')
        durations[environment]=elapsed
    value=dict(approved=True,source_hashes=config['source_hashes'],operator_manifest_sha256=config['operator_manifest_sha256'],
               conventional_startup_timeout_seconds=ceiling,healthy_startup_evidence=[reference(source)],observed_seconds=durations,
               finite_ceiling_justification='Automated check: both healthy M001 startup intervals completed below the unchanged, predeclared ceiling. This is a readiness check, not a statistical upper bound.')
    path=SETUP/'startup-calibration.json'
    if path.exists():
        if batch.read(path)!=value:raise ValueError('Existing calibration differs')
    else:batch.save(path,value,new=True)
    return reference(path)


def smoke(first=False):
    config=batch.read(SETUP/'validation.json')
    cases=['M001'] if first else list(server.SMOKE_CASES)
    reports=[]
    for case in cases:
        directory=ROOT/'results/smoke'/case
        execute(directory,[case],config)
        if case=='M001':
            healthy(directory)
            approval=SETUP/'fault-approval'
            if not approval.exists():
                if server.approve_faults(directory,approval,config):raise ValueError('Fault approval failed')
        reports.append(reference(directory/'validation.json'))
    if first:
        print('PASS: first healthy trial; export-results.sh M001 to review locally')
        return
    study=copy.deepcopy(config);study.update(execution_mode='study',smoke_evidence=reports,representative_smoke_verified=True)
    study.pop('validation_campaign',None)
    study['startup_calibration_evidence']=calibration(study)
    batch.readiness(study,batch.read(matrix.MANIFEST),live=True)
    target=SETUP/'study.json'
    if target.exists():
        if batch.read(target)!=study:raise ValueError('Existing study configuration differs')
    else:batch.save(target,study,new=True)
    print('READY: representative smoke passed; study batches enabled')


def ids_for(name):
    entries=[b for b in study_batches.load()['batches'] if b['batch_id']==name]
    if len(entries)!=1:raise ValueError('Choose batch-1 through batch-5')
    return [r['case_id'] for r in entries[0]['cases']]


def study(name):
    config=batch.read(SETUP/'study.json')
    if config['execution_mode']!='study':raise ValueError('Study configuration required')
    execute(ROOT/'results/study'/name,ids_for(name),config)
    print('READY FOR NEXT BATCH')


def aggregate():
    configurations=[];rows=[]
    for number in range(1,6):
        name=f'batch-{number}';directory=ROOT/'results/study'/name
        report=checked(directory,ids_for(name))
        if report['execution_mode']!='study':raise ValueError('Validation evidence is not study data')
        configurations.append(batch.read(directory/'batch.json')['configuration'])
        rows.extend(batch.read(directory/case/arm/'metrics.json') for case in ids_for(name) for arm in ('conventional','bdi'))
    if any(c!=configurations[0] for c in configurations):raise ValueError('Batch configuration/provenance differs')
    if len(rows)!=200:raise ValueError('Exactly 200 treatment metric records required')
    if configurations[0].get('study_batches_sha256')!=batch.digest(study_batches.PATH):raise ValueError('Allocation provenance differs')
    result=dict(status='PASS',pairs=100,treatment_records=len(rows),allocation_sha256=batch.digest(study_batches.PATH),aggregate=batch.metrics.aggregate(rows))
    batch.save(ROOT/'results/study/aggregate-validation.json',result)
    print('PASS: all five batches; 100/100 pairs; 200 validated treatment records')
    return result


def export(name):
    from export_results import export as bundle,verify
    names=[f'batch-{i}' for i in range(1,6)] if name=='all' else [name]
    if name=='all':aggregate()
    for name in names:
        directory=ROOT/'results/smoke/M001' if name=='M001' else ROOT/'results/study'/name
        ids=['M001'] if name=='M001' else ids_for(name)
        checked(directory,ids)
        if name=='M001':healthy(directory)
        target=ROOT/'results/bundles'/(name+'.tar.gz')
        if target.exists():
            manifest=verify(target)
            if manifest['files']!=batch.hashes(directory):raise ValueError('Existing bundle differs; preserve it and choose a new export via export_results.py')
        else:bundle(directory,target)
    print('PASS: bundles and checksums in results/bundles/')


def main(argv=None):
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='action',required=True)
    s=sub.add_parser('smoke');s.add_argument('selection',nargs='?',choices=['first','all'],default='all')
    for name in ('study','validate','export'):
        s=sub.add_parser(name);s.add_argument('selection',choices=['M001','all',*[f'batch-{n}' for n in range(1,6)]] if name!='study' else [f'batch-{n}' for n in range(1,6)])
    a=p.parse_args(argv)
    if a.action=='smoke':smoke(a.selection=='first')
    elif a.action=='study':study(a.selection)
    elif a.action=='export':export(a.selection)
    elif a.selection=='all':aggregate()
    else:
        directory=ROOT/'results/smoke/M001' if a.selection=='M001' else ROOT/'results/study'/a.selection
        report=checked(directory,['M001'] if a.selection=='M001' else ids_for(a.selection))
        print('PASS: '+str(report['completed_pairs'])+' valid pairs')
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:print('FAIL: '+str(exc),file=sys.stderr);raise SystemExit(1)
