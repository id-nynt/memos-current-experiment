"""Fail-closed paired batch orchestration. Default operations are offline only.

No recovery policy lives here. Native operators retain ownership, qualification,
one-use baseline and remote-work guards. Execution requires an explicit reviewed
readiness configuration; the distributed template intentionally cannot execute.
"""
import image_identity as images_identity
import argparse
import copy
import datetime as dt
import hashlib
import json
import math
import os
import platform
import socket
import re
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
import phase8_matrix as matrix
import phase5_metrics as metrics

ROOT=Path(__file__).resolve().parents[1]
STEPS=('prerequisites','reset_before','verify_baseline','candidate','collect_seal',
       'validate_metrics','reset_after','verify_reset')


def now():return dt.datetime.now(dt.timezone.utc).isoformat()
def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path,value,new=False):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if new:
        with path.open('x',encoding='utf-8') as f:json.dump(value,f,indent=2,allow_nan=False)
    else:
        temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
        with temporary.open('x',encoding='utf-8') as f:
            json.dump(value,f,indent=2,allow_nan=False);f.flush();os.fsync(f.fileno())
        temporary.replace(path)


def hashes(directory):
    result={}
    for p in sorted(Path(directory).rglob('*')):
        if p.is_symlink():raise ValueError('Symlink in evidence')
        if p.is_file():result[p.relative_to(directory).as_posix()]=digest(p)
    return result


def selected(manifest,ids=None):
    matrix.validate(manifest)
    requested=set(ids or [c['case_id'] for c in manifest['cases']])
    if not requested or requested-set(c['case_id'] for c in manifest['cases']):
        raise ValueError('Unknown/empty selection')
    by_id={c['case_id']:c for c in manifest['cases']}
    if ids and len(ids)!=len(requested):raise ValueError('Duplicate case selection')
    return [by_id[i] for i in (ids or list(by_id))]


def plan(manifest,ids=None):
    return [dict(case_id=c['case_id'],pair_key=c['pair_key'],treatment=arm,
                 scenario=c['scenario'],spec_sha256=c['spec_sha256'],steps=list(STEPS),
                 entry_workflow='memos-current/.github/workflows/frozen-cd.yml' if arm=='conventional' else 'memos-bdi/.github/workflows/'+read(ROOT/'memos-bdi/experiment/adapter-contract.json')['workflow_file'],
                 reset_entry='memos-current/experiment/manage.py reset' if arm=='conventional' else 'tools/bdi_reset.py',
                 runner_labels=[['self-hosted','linux','memos-bdi-deploy']],
                 horizon_seconds=300,baseline='shared-controlled-seed',native_policy_unchanged=True)
            for c in selected(manifest,ids) for arm in c['treatments']]


def validate_plan(manifest):
    from workflow_audit import reachable
    import scenario_runtime
    matrix.validate(manifest);jobs=reachable()
    enabled=read(ROOT/'memos-current/experiment/scenarios.json')
    generated=read(ROOT/'protocol/matrix-scenarios.json')
    if generated['matrix_sha256']!=matrix.sha(manifest):raise ValueError('Generated matrix provenance mismatch')
    for folder in ('tools','memos-current/experiment','memos-bdi/experiment/scripts'):
        if read(ROOT/folder/'matrix-scenarios.json')!=generated:raise ValueError('Native profile copy mismatch')
    for case in manifest['cases']:
        if not enabled.get(case['scenario'],{}).get('enabled'):raise ValueError('Conventional profile unavailable')
        if case['spec'] and scenario_runtime.resolve(case['scenario'])!=case['spec']:raise ValueError('Native scenario mismatch')
    if not (ROOT/'tools/bdi_reset.py').is_file() or not (ROOT/'memos-current/experiment/manage.py').is_file():
        raise ValueError('Reset implementation missing')
    return dict(cases=len(manifest['cases']),candidate_executions=2*len(manifest['cases']),
                source_workflow_job_definitions=len(jobs),valid=True,live_execution=False,
                scope='source/static; selected historical control publication and live prerequisites remain blocked')


def source_hashes():
    paths=set()
    for base in ('tools','protocol','scripts','memos-current/experiment','memos-current/scripts/local-cd',
                 'memos-current/scripts/experiment-measurement','memos-current/.github/workflows',
                 'memos-bdi/experiment','memos-bdi/.github/workflows',
                 'memos-bdi/bdi-cicd-framework'):
        for folder,dirs,files in os.walk(ROOT/base):
            dirs[:]=[d for d in dirs if d not in ('results','runs','.runtime','__pycache__','node_modules','.git','bin','build','target','dist','.gradle','.venv','venv')]
            for name in files:
                p=Path(folder)/name
                if name=='machine.json':continue
                if p.suffix in ('.py','.json','.yml','.yaml','.ps1','.asl','.sh','.java','.gradle','.properties','.txt','.toml','.xml') or name.endswith('Dockerfile') or name in ('gradlew','gradlew.bat'):
                    paths.add(p)
    return {p.relative_to(ROOT).as_posix():digest(p) for p in sorted(paths)}


def require_source_lock(expected,expected_images=None):
    if source_hashes()!=expected:
        raise ValueError('Execution source/config changed during batch; reconcile before further work')
    if expected_images is not None and images_identity.session()!=expected_images:
        raise ValueError('Server image freeze missing/changed during batch')


def readiness(config,manifest,live=False):
    from workflow_audit import reachable
    reachable()
    failures=[]
    active_images=images_identity.session()
    if (active_images is not None or config.get('image_session') is not None) and config.get('image_session')!=active_images:
        failures.append('server image freeze differs from execution configuration')
    if config.get('study_batches_sha256'):
        from study_batches import PATH,load
        load()
        if config['study_batches_sha256']!=digest(PATH):failures.append('study allocation changed')
    if config.get('schema_version')!=1:failures.append('readiness schema')
    if config.get('matrix_sha256')!=matrix.sha(manifest):failures.append('matrix review identity')
    mode=config.get('execution_mode','study')
    if mode not in ('study','validation'):failures.append('unknown execution mode')
    if mode=='validation' and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',str(config.get('validation_campaign',''))):
        failures.append('explicit validation campaign required')
    for key in ('execution_authorized','measurement_policy_approved','environment_parity_verified',
                'clock_alignment_verified','exclusive_environment_verified') + (() if mode=='validation' else ('representative_smoke_verified',)):
        if config.get(key) is not True:failures.append(key)
    if config.get('source_hashes')!=source_hashes():failures.append('reviewed source snapshot/publication required')
    if config.get('operator_manifest_sha256')!=digest(ROOT/'protocol/operator-revisions.json'):
        failures.append('operator revision identity')
    if config.get('unresolved_blockers'):failures.extend(config['unresolved_blockers'])
    try:
        ref=config['server_evidence'];path=Path(ref['path'])
        if path.is_symlink() or digest(path)!=ref['sha256']:raise ValueError()
        evidence=read(path)
        if live and (platform.system()!='Linux' or evidence.get('host')!=socket.gethostname()):raise ValueError()
        if (evidence.get('target_checks') is not True or evidence.get('source_hashes')!=config.get('source_hashes')
                or evidence.get('matrix_sha256')!=matrix.sha(manifest)
                or evidence.get('operator_manifest_sha256')!=digest(ROOT/'protocol/operator-revisions.json')
                or not evidence.get('checks') or any(r['status'] in ('BLOCKER','REQUIRES TARGET-SERVER VALIDATION') for r in evidence['checks'])):
            raise ValueError()
    except (KeyError,TypeError,ValueError,OSError):failures.append('matching target-server evidence required')
    if mode=='study':
        try:
            from server_execution import inspect_results, SMOKE_CASES
            covered=set()
            for ref in config.get('smoke_evidence',[]):
                report_path=Path(ref['path'])
                if report_path.is_symlink() or digest(report_path)!=ref['sha256']:raise ValueError()
                smoke=read(report_path)
                if smoke.get('execution_mode')!='validation' or smoke.get('all_selected_valid') is not True:raise ValueError()
                directory=Path(smoke['directory'])
                snapshot=read(directory/'batch.json')['configuration']
                if any(snapshot.get(k)!=config.get(k) for k in ('source_hashes','operator_manifest_sha256','controlled_seed_sha256','measurement_policy')):raise ValueError()
                fresh=inspect_results(directory,manifest,derive=True)
                if not fresh['all_selected_valid']:raise ValueError()
                covered.update(row['case_id'] for row in fresh['cases'])
            if not set(SMOKE_CASES)<=covered:raise ValueError()
        except (KeyError,TypeError,ValueError,OSError):failures.append('matching sealed representative validation evidence required')
        try:
            ref=config['startup_calibration_evidence'];path=Path(ref['path'])
            if path.is_symlink() or digest(path)!=ref['sha256']:raise ValueError()
            value=read(path)
            if (value.get('approved') is not True or value.get('source_hashes')!=config.get('source_hashes')
                    or value.get('operator_manifest_sha256')!=config.get('operator_manifest_sha256')
                    or value.get('conventional_startup_timeout_seconds')!=read(ROOT/'memos-current/experiment/config.json')['startup_timeout_seconds']
                    or not value.get('healthy_startup_evidence') or not value.get('finite_ceiling_justification')):raise ValueError()
            for item in value['healthy_startup_evidence']:
                source=Path(item['path'])
                if source.is_symlink() or digest(source)!=item['sha256']:raise ValueError()
        except (KeyError,TypeError,ValueError,OSError):failures.append('reviewed final startup calibration evidence required')
    policy=config.get('measurement_policy',{})
    if policy != read(ROOT/'protocol/final-coverage-policy.json')['policy']:
        failures.append('measurement policy differs from approved final coverage contract')
    if policy.get('stability')!={'minimum_samples':3,'minimum_span_seconds':10,'maximum_gap_seconds':15}:
        failures.append('stable recovery policy changed')
    try:
        coverage,endpoint=policy['coverage'],policy['endpoint']
        numbers=[coverage['maximum_gap_seconds'],coverage['minimum_fraction'],endpoint['window_seconds'],endpoint['minimum_samples'],endpoint['edge_tolerance_seconds']]
        if not all(type(v) in (int,float) and math.isfinite(v) and v>0 for v in numbers):raise ValueError()
        if coverage['minimum_fraction']>1 or endpoint['window_seconds']>300 or endpoint['edge_tolerance_seconds']>endpoint['window_seconds']:raise ValueError()
    except (KeyError,TypeError,ValueError):failures.append('invalid measurement coverage/endpoint configuration')
    if not re.fullmatch('[a-f0-9]{64}',str(config.get('controlled_seed_sha256',''))):
        failures.append('controlled seed hash missing/invalid')
    if any(not isinstance(config.get('drivers',{}).get(a),list) or not config['drivers'][a] or not all(isinstance(x,str) and x for x in config['drivers'][a]) for a in ('conventional','bdi')):
        failures.append('native platform driver argv missing/invalid')
    pins=read(ROOT/'protocol/operator-revisions.json')
    # Every selected source input must actually exist in the immutable control.
    # A review checkbox cannot promote an old pin into a new executable control.
    for arm in ('conventional','bdi'):
        item=pins[arm];repo=ROOT/item['checkout']
        if arm=='bdi' and item.get('policy_contract')!='protocol/bdi-policy-final-source.json':
            failures.append('BDI final policy fingerprint contract not selected')
        relative='experiment/scripts/matrix-scenarios.json' if arm=='bdi' else 'experiment/matrix-scenarios.json'
        proc=subprocess.run(['git','-C',str(repo),'show',item['control_sha']+':'+relative],capture_output=True)
        if proc.returncode or proc.stdout.replace(b'\r\n',b'\n')!=(repo/relative).read_bytes().replace(b'\r\n',b'\n'):
            failures.append(arm+': selected historical control lacks exact matrix')
        if live:
            for rel,h in config.get('source_hashes',{}).items():
                if not rel.startswith(item['checkout']+'/'):continue
                native_rel=rel[len(item['checkout'])+1:]
                result=subprocess.run(['git','-C',str(repo),'show',item['control_sha']+':'+native_rel],capture_output=True)
                if result.returncode or result.stdout.replace(b'\r\n',b'\n')!=(ROOT/rel).read_bytes().replace(b'\r\n',b'\n'):
                    failures.append(arm+': pinned source mismatch '+native_rel)
    if live and failures:raise ValueError('Batch execution blocked: '+'; '.join(failures))
    return failures


def claim_ledger(manifest,config):
    base=ROOT/'results/batch-state'/manifest['study_id']
    if config.get('execution_mode','study')=='validation':
        campaign=config.get('validation_campaign','')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',campaign):
            raise ValueError('Explicit safe validation campaign required')
        return base/'validation'/campaign
    return base


def local_path(value):
    """Map native paths only on the current Windows/WSL shared workspace."""
    value=str(value)
    if os.name=='nt' and value.startswith('/mnt/'):
        value=value[5].upper()+':/'+value[7:]
    elif os.name!='nt' and len(value)>2 and value[1:3] in (':\\',':/'):
        value='/mnt/'+value[0].lower()+'/'+value[3:].replace('\\','/')
    path=Path(value).resolve()
    if not path.is_relative_to(ROOT):raise ValueError('Native evidence outside shared workspace')
    return path


def ci_fault(directory,arm,scenario=None):
    releases=read(ROOT/'protocol/frozen-releases.json')['releases']
    native=metrics.native_case(metrics.Evidence(directory),arm,releases)
    receipts={}
    for p in [*directory.rglob('s6-receipt.json'),*directory.glob('s6-fixture/attempt-1.json')]:
        value=read(p);identity=value.get('identity',{})
        if identity.get('attempt')!=1:continue
        if scenario is not None and identity.get('scenario') != scenario:
            raise ValueError('CI fault receipt scenario mismatch')
        if (identity.get('campaign_id')!=native['campaign_id'] or identity.get('control_sha')!=native['control_sha']
                or identity.get('release_sha')!=releases['v2']['application_sha']):
            raise ValueError('Foreign CI fault receipt')
        receipts[matrix.sha(value)]=value
    if len(receipts)!=1:raise ValueError('Missing/conflicting CI first-attempt exposure')
    value=next(iter(receipts.values()))
    failures=[r for r in value['responses'] if r['status']==503]
    if len(failures)!=1 or value['primary_status']!=503 or value['clearance_status']!=200:
        raise ValueError('CI fault exposure/clearance mismatch')
    with (directory/'batch-derived-ci.jsonl').open('x') as stream:
        stream.write(json.dumps(dict(event='ci_dependency_failure',timestamp=failures[0]['timestamp'],
            campaign_id=native['campaign_id'],release_sha=releases['v2']['application_sha']))+'\n')
    return dict(kind='ci',entity='test',source='batch-derived-ci.jsonl',match={'event':'ci_dependency_failure'},
                **({'native_job_match':{'name':'fixture'}} if arm=='conventional' else {}))


def permanent_ci_fault(directory,arm,scenario):
    releases=read(ROOT/'protocol/frozen-releases.json')['releases']
    native=metrics.native_case(metrics.Evidence(directory),arm,releases)
    expected='build' if scenario=='CI02' else 'test'
    receipts={matrix.sha(read(p)):read(p) for p in directory.rglob('ci-control.json')}
    if not receipts:raise ValueError('Missing permanent CI exposure receipt')
    for r in receipts.values():
        if (r.get('scenario')!=scenario or r.get('boundary')!=expected or r.get('permanent') is not True
                or r.get('campaign_id')!=native['campaign_id'] or r.get('control_sha')!=native['control_sha']
                or r.get('release_sha')!=releases['v2']['application_sha']):
            raise ValueError('Foreign permanent CI fault evidence')
    first=min(receipts.values(),key=lambda r:metrics.stamp(r['timestamp']))
    with (directory/'batch-derived-ci.jsonl').open('x') as stream:stream.write(json.dumps(first)+'\n')
    return dict(kind='ci',entity=expected,source='batch-derived-ci.jsonl',match={'event':'deterministic_failure'},
                **({'native_job_match':{'name':'deploy' if expected=='build' else 'fixture'}} if arm=='conventional' else {}))


class NativeDriver:
    def __init__(self,config):self.config=config

    def operator(self,arm,action,directory,scenario='S0'):
        prefix=self.config['drivers'][arm]
        if not isinstance(prefix,list) or not prefix or any(not isinstance(x,str) for x in prefix):
            raise ValueError('Explicit argv driver required')
        command=prefix+[action,arm]
        if getattr(self,'batch_token',None):command+=['--batch-token',self.batch_token]
        if action=='run':command+=['--scenario',scenario,'--allow-fault-execution']
        save(directory/'command.json',dict(argv=command,started_at=now()),new=True)
        # No new timeout truncates native policy. Interruptions preserve locks and
        # require explicit reconciliation of remote work; never cancel/retry here.
        with (directory/'operator.log').open('x',encoding='utf-8') as log:
            code=subprocess.call(command,stdout=log,stderr=subprocess.STDOUT)
        save(directory/'exit.json',dict(code=code,completed_at=now()),new=True)
        if action=='check':
            if code:raise ValueError('Native prerequisite check failed')
            return None
        lines=(directory/'operator.log').read_text(encoding='utf-8-sig').splitlines()
        records=[]
        for line in lines:
            try:value=json.loads(line)
            except ValueError:continue
            if isinstance(value,dict) and 'native_evidence' in value:records.append(value)
        if len(records)!=1:raise ValueError('Missing/ambiguous operator operation identity')
        op=local_path(records[0]['evidence']);native=local_path(records[0]['native_evidence'])
        selection=read(op/'selection.json');completion=read(op/'completion.json')
        pins=read(ROOT/'protocol/operator-revisions.json')
        if (op.parent!=(ROOT/'results/operator-runs').resolve()
                or local_path(selection['native_directory'])!=native
                or selection['control_sha']!=pins[arm]['control_sha']
                or selection['manifest_sha256']!=digest(ROOT/'protocol/operator-revisions.json')):
            raise ValueError('Foreign/stale operator revision or evidence path')
        if selection['action']!=action or selection['approach']!=arm or completion['exit_code']!=code:
            raise ValueError('Operator completion attribution mismatch')
        if action=='run' and selection['scenario']!=scenario:raise ValueError('Wrong dispatched scenario')
        if action=='reset' and code:raise ValueError('Reset failed')
        # Keep provenance portable; operator paths alone cannot be inspected after download.
        save(directory/'selection.json', selection, new=True)
        save(directory/'completion.json', completion, new=True)
        save(directory/'operation.json',dict(operator=str(op),native=str(native),selection_sha256=digest(op/'selection.json')),new=True)
        return op,native

    def prerequisites(self,case,arm,directory):
        directory.mkdir();self.operator(arm,'check',directory)

    def reset(self,case,arm,directory):
        directory.mkdir();op,native=self.operator(arm,'reset',directory)
        receipt=read(op/'baseline-receipt.json')
        release=read(ROOT/'protocol/frozen-releases.json')['releases']['v1']
        if arm=='bdi':
            if receipt.get('data_semantics')!='shared-controlled-seed':raise ValueError('BDI seed reset missing')
            seeds={x['archive_sha256'] for x in receipt['controlled_seed'].values()}
            if set(receipt['environments'])!={'staging','production'} or not all(x.get('verified') and x['release_sha']==release['application_sha'] and images_identity.matches(release,x['image_id']) for x in receipt['environments'].values()):
                raise ValueError('Unverified reset identity')
        else:
            seeds={receipt['seed_sha256']}
            if receipt.get('used_by') or set(receipt['observations'])!={'staging','production'} or not all(x.get('healthy') and x['application_sha']==release['application_sha'] and images_identity.matches(release,x.get('image_id')) for x in receipt['observations'].values()):
                raise ValueError('Unverified conventional baseline')
        if seeds!={self.config['controlled_seed_sha256']}:raise ValueError('Shared seed identity mismatch')
        shutil.copyfile(op/'baseline-receipt.json', directory/'baseline-receipt.json')
        return dict(seed_sha256=next(iter(seeds)),receipt_sha256=digest(op/'baseline-receipt.json'),verified=True,operation=str(op))

    def candidate(self,case,arm,directory):
        directory.mkdir();return self.operator(arm,'run',directory,case['scenario'])[1]

    def collect(self,case,arm,native,directory,declared_at):
        # Native check verifies no unknown remote work before evidence is copied.
        checkdir=directory.parent/'post_candidate_check';checkdir.mkdir()
        self.operator(arm,'check',checkdir)
        original=hashes(native)
        shutil.copytree(native,directory)
        if original!=hashes(native) or original!=hashes(directory):raise ValueError('Evidence changed during collection')
        horizon=read(directory/'observation-horizon.json')
        if horizon.get('horizon_seconds')!=300 or horizon['endpoint_epoch']-horizon['measurement_start_epoch']!=300:
            raise ValueError('Wrong independent horizon')
        reset=read(directory/'reset-state.json')
        if reset.get('archive_sha256')!=self.config['controlled_seed_sha256'] or reset.get('verified') is not True:
            raise ValueError('Missing candidate controlled-reset attribution')
        spec=dict(role='candidate',treatment=arm,case_id=case['case_id'],scenario_family=case['family'],
                  measurement_extension='memos-exact-count-v1',
                  parameters=case['parameters'],evidence_directory=str(directory),declaration='prospective',declared_at=declared_at,
                  window=dict(start=metrics.iso(horizon['measurement_start_epoch']),end=metrics.iso(horizon['endpoint_epoch']),
                              anchor=case['anchor'],pair_key=case['pair_key']),
                  cross_clock_verified=self.config['clock_alignment_verified'],**self.config['measurement_policy'])
        if case['spec']:
            schedule=read(directory/'scenario-schedule.json')
            if schedule['spec']!=case['spec'] or schedule['start_epoch']!=horizon['measurement_start_epoch']:
                raise ValueError('Wrong scenario parameters or schedule anchor')
            if schedule['target']['environment']!=case['parameters']['stage']:
                raise ValueError('Cross-environment schedule')
            summary=read(directory/'fault-summary.json')
            if summary.get('version')!='memos-phase7-v1':raise ValueError('Missing final fault accounting')
            if (directory/'fixture-error.json').exists():raise ValueError('Fixture infrastructure error')
            events=directory/'fault-events.jsonl'
            if case['spec']['episodes'] and not events.exists():raise ValueError('Missing episode observer evidence')
            if events.exists():
                observed=[json.loads(line) for line in events.read_text().splitlines() if line.strip()]
                for ep in case['spec']['episodes']:
                    if not any(r.get('event')=='episode_started' and r.get('episode_id')==ep['id'] for r in observed):
                        raise ValueError('Missing independent scheduled episode boundary')
            spec['scenario_contract']='memos-phase7-v1'
            if case['spec']['episodes']:
                ep=case['spec']['episodes'][0]
                save(directory/'batch-derived-onset.jsonl',dict(event='declared_first_impairment',
                    timestamp=metrics.iso(schedule['start_epoch']+ep['start'])),new=True)
                # JSONL must be exactly one line; derived data never modifies native evidence.
                (directory/'batch-derived-onset.jsonl').write_text(json.dumps(dict(event='declared_first_impairment',timestamp=metrics.iso(schedule['start_epoch']+ep['start'])))+'\n')
                spec['fault']=dict(kind=case['parameters']['stage'],entity=case['parameters']['stage'],source='batch-derived-onset.jsonl',
                    match={'event':'declared_first_impairment'},native_error_threshold=.05,
                    signal='telemetry' if ep['mode']=='telemetry_missing' else 'service')
        elif case['scenario']=='CI01':
            spec['fault']=ci_fault(directory,arm,case['scenario'])
        elif case['scenario'] in ('CI02','CI03'):
            spec['fault']=permanent_ci_fault(directory,arm,case['scenario'])
        # This attests the exclusive batch-owned lifecycle, not unobservable human activity.
        save(directory/'batch-native-files.json',original,new=True)
        if not (directory/'human-interventions.json').exists():
            save(directory/'human-interventions.json',dict(attested_complete=True,events=[],
                authority='exclusive environment per reviewed readiness configuration; no batch interventions'),new=True)
        save(directory.parent/'metric-spec.json',spec,new=True)
        result=metrics.normalize(spec)
        result['controlled_seed_sha256']=reset['archive_sha256']
        result['provenance']['reset_data_policy']='shared-controlled-seed'
        result['provenance']['reset_isolation_decision']='Resolved; exact seed and v1 receipt checked by batch validator'
        result['analysis_stratum']=case['analysis_stratum']
        result['execution_mode']=self.config.get('execution_mode','study')
        result['primary_study_eligible']=result['execution_mode']=='study'
        save(directory.parent/'metrics.json',result,new=True)
        if result['validity']['status']!='valid':raise ValueError('Invalid/incomplete independent measurement: '+str(result['validity']))
        if case['parameters']['stage']=='staging' and not result.get('staging',{}).get('request_coverage_sufficient'):
            raise ValueError('Incomplete staging exposure measurement')
        if case['parameters']['stage']=='staging' and result['staging'].get('coverage',0)<self.config['measurement_policy']['coverage']['minimum_fraction']:
            raise ValueError('Incomplete staging endpoint observation coverage')
        save(directory.parent/'evidence-seal.json',hashes(directory),new=True)
        return dict(native_outcome=result['reliability']['native_outcome'],validity='valid',metrics_sha256=digest(directory.parent/'metrics.json'),
                    metric_spec_sha256=digest(directory.parent/'metric-spec.json'))


def claim_case(ledger,case,arm,path):
    ledger.mkdir(parents=True,exist_ok=True)
    save(ledger/(case['case_id']+'-'+arm+'.json'),dict(case_id=case['case_id'],treatment=arm,
         directory=str(path.resolve()),claimed_at=now(),spec_sha256=case['spec_sha256']),new=True)


def run(manifest,config,directory,ids=None,driver=None):
    """Driver injection is for offline tests only; the CLI always uses NativeDriver."""
    cases=selected(manifest,ids);directory=Path(directory)
    native_driver=driver is None
    if native_driver:readiness(config,manifest,live=True);driver=NativeDriver(config)
    directory.mkdir(parents=True,exist_ok=True)
    lock=directory/'active.lock'
    lock.mkdir() # No stale-lock override, PID guessing or reboot auto-unlock.
    save(lock/'owner.json',dict(pid=os.getpid(),started_at=now(),host=os.environ.get('COMPUTERNAME',os.environ.get('HOSTNAME','unknown'))),new=True)
    identity=dict(matrix_sha256=matrix.sha(manifest),config_sha256=matrix.sha(config),selection=[c['case_id'] for c in cases],
                  execution_mode=config.get('execution_mode','study'),validation_campaign=config.get('validation_campaign'))
    done=False
    global_lock=None
    try:
        if native_driver:
            global_lock=ROOT/'results/operator-state/batch.lock'
            global_lock.parent.mkdir(parents=True,exist_ok=True)
            global_lock.mkdir()
            driver.batch_token=uuid.uuid4().hex
            save(global_lock/'owner.json',dict(token=driver.batch_token,directory=str(directory.resolve()),started_at=now()),new=True)
        if (directory/'batch.json').exists():
            if read(directory/'batch.json')['identity']!=identity:raise ValueError('Resume identity/selection drift')
        else:save(directory/'batch.json',dict(identity=identity,configuration=config,created_at=now()),new=True)
        for case in cases:
            for arm in case['treatments']:
                if native_driver:require_source_lock(config['source_hashes'],config.get('image_session'))
                path=directory/case['case_id']/arm
                if path.exists():
                    state=read(path/'status.json')
                    if state['status']!='valid':raise ValueError('Prior incomplete/invalid attempt requires reconciliation; never auto-retry')
                    if hashes(path/'evidence')!=read(path/'evidence-seal.json'):raise ValueError('Completed evidence seal changed')
                    if digest(path/'metrics.json')!=state['result']['metrics_sha256']:raise ValueError('Completed metrics changed')
                    if 'metric_spec_sha256' in state['result'] and digest(path/'metric-spec.json')!=state['result']['metric_spec_sha256']:
                        raise ValueError('Completed metric specification changed')
                    continue
                # An operator requests a graceful stop by creating STOP in this
                # batch directory. Finish the active arm including reset first.
                if (directory/'STOP').exists():
                    done=True
                    return
                if native_driver:
                    claim_case(claim_ledger(manifest,config),case,arm,path)
                path.mkdir(parents=True)
                state=dict(case_id=case['case_id'],treatment=arm,status='in_progress',step='prerequisites',started_at=now(),spec_sha256=case['spec_sha256'])
                save(path/'status.json',state,new=True)
                try:
                    driver.prerequisites(case,arm,path/'prerequisites')
                    state['step']='reset_before';save(path/'status.json',state)
                    baseline=driver.reset(case,arm,path/'reset_before')
                    if baseline.get('verified') is not True:raise ValueError('Unverified baseline')
                    state['baseline']=baseline;state['step']='candidate';save(path/'status.json',state)
                    declared_at=now()
                    save(path/'declaration.json',dict(case=case,declared_at=declared_at,measurement_policy=config.get('measurement_policy')),new=True)
                    native=driver.candidate(case,arm,path/'candidate')
                    state['step']='collect_seal';save(path/'status.json',state)
                    result=driver.collect(case,arm,native,path/'evidence',declared_at)
                    if result['validity']!='valid':raise ValueError('Measurement invalid')
                    state['step']='reset_after';state['result']=result;save(path/'status.json',state)
                    final=driver.reset(case,arm,path/'reset_after')
                    if not final.get('verified') or final['seed_sha256']!=baseline['seed_sha256']:
                        raise ValueError('Final reset equivalence failed')
                    state.update(status='valid',step='complete',completed_at=now(),final_reset=final)
                    save(path/'status.json',state)
                except BaseException as exc:
                    state.update(status='interrupted' if isinstance(exc,KeyboardInterrupt) else 'invalid_or_incomplete',
                                 error_type=type(exc).__name__,error=str(exc),stopped_at=now())
                    save(path/'status.json',state);raise
                finally:index(directory)
        done=True
    finally:
        index(directory)
        if done:
            (lock/'owner.json').unlink();lock.rmdir()
            if global_lock:
                (global_lock/'owner.json').unlink();global_lock.rmdir()


def index(directory):
    rows=[read(p) for p in sorted(Path(directory).glob('M*/*/status.json'))]
    save(Path(directory)/'index.json',dict(updated_at=now(),attempted=len(rows),valid=sum(r['status']=='valid' for r in rows),cases=rows))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['validate','dry-run','readiness','execute'])
    p.add_argument('--manifest',type=Path,default=matrix.MANIFEST)
    p.add_argument('--config',type=Path,default=ROOT/'protocol/batch-readiness.template.json')
    p.add_argument('--directory',type=Path)
    selection=p.add_mutually_exclusive_group()
    selection.add_argument('--cases',nargs='+')
    selection.add_argument('--test-set',choices=['A','B'])
    a=p.parse_args();manifest=read(a.manifest);matrix.validate(manifest)
    if a.test_set:
        a.cases=[c['case_id'] for c in manifest['cases'] if c['test_set']==a.test_set]
    if a.action in ('validate','dry-run'):
        value=dict(validation=validate_plan(manifest),operations=plan(manifest,a.cases),execution=False)
        if a.directory:save(a.directory/'dry-run.json',value,new=True)
        print(json.dumps(dict(valid=True,paired_conditions=len(value['operations'])//2,candidates=len(value['operations']),execution=False)))
    elif a.action=='readiness':print(json.dumps(dict(blockers=readiness(read(a.config),manifest)),indent=2))
    else:
        if not a.directory:p.error('Explicit batch evidence directory required')
        run(manifest,read(a.config),a.directory,a.cases)


if __name__=='__main__':main()
