"""Validate and package the shared experiment kit in the Conventional Git repository."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import batch_runner as batch
import job_audit
import study_batches

ROOT=batch.ROOT
KIT=ROOT/'memos-current/experiment-kit'


def git(repo,*args):
    return subprocess.check_output(['git','-C',str(repo),*args],text=True).strip()


def validate():
    job_audit.audit()
    print(study_batches.validate(study_batches.load(),batch.read(ROOT/'protocol/phase8-case-matrix.json')))
    batch.validate_plan(batch.read(ROOT/'protocol/phase8-case-matrix.json'))
    print('PASS: local contracts, scenarios, workflow closure and 5 x 20 allocation')


def package(preview=False):
    validate()
    pins=batch.read(ROOT/'protocol/operator-revisions.json')
    if not preview:
        tested=ROOT/'results/local-validation.json'
        if not tested.exists() or batch.read(tested).get('source_hashes')!=batch.source_hashes():
            raise ValueError('Run local_prepare.py validate successfully on these exact sources before packaging')
        for arm in ('conventional','bdi'):
            repo=ROOT/pins[arm]['checkout']
            changes=git(repo,'status','--porcelain','--untracked-files=normal','--','.',':(exclude)experiment-kit')
            if changes:raise ValueError('Commit native source changes first: '+str(repo))
            sha=git(repo,'rev-parse','HEAD');tag='memos-control-'+arm+'-'+sha[:12]
            existing=git(repo,'tag','--list',tag)
            if not existing:git(repo,'tag',tag,sha)
            if git(repo,'rev-parse',tag+'^{commit}')!=sha:raise ValueError('Existing tag differs')
            pins[arm].update(control_sha=sha,control_ref=tag)
        batch.save(ROOT/'protocol/operator-revisions.json',pins)
        from experiment import selection
        from bdi_policy import report
        selection('bdi');report(ROOT,pins['bdi'])
    KIT.mkdir(exist_ok=True)
    names=[]
    from server_migration import MODULES
    modules=set(MODULES)|{'local_prepare','job_audit','job_events','study_batches','server_prepare','study_execution','measure_trial','validate_s6_offline'}
    names.extend(Path('tools')/(n+'.py') for n in sorted(modules))
    names.extend(p.relative_to(ROOT) for p in (ROOT/'tools').glob('test_*.py'))
    for folder,patterns in [('tools',('*.json',)),('protocol',('*.json',)),('scenarios',('*.json',)),('scripts',('*.sh',))]:
        for pattern in patterns:
            names.extend(p.relative_to(ROOT) for p in (ROOT/folder).glob(pattern) if p.is_file())
    names += [Path('SERVER_EXECUTION_SIMPLE.md')]
    names += [Path('docs')/n for n in ('SERVER_PREPARATION_INTERNALS.md','EXPERIMENT_PROVENANCE.md','ENTITY_TO_JOB_AUDIT.md','STUDY_BATCH_DESIGN.md','PHASE8_CASE_MATRIX.md')]
    for name in names:
        destination=KIT/name;destination.parent.mkdir(parents=True,exist_ok=True)
        # LF prevents source fingerprints depending on the developer's Git autocrlf.
        destination.write_text((ROOT/name).read_text(encoding='utf-8-sig'),encoding='utf-8',newline='\n')
    (KIT/'.gitignore').write_text('/.venv/\n/results/\n/memos-current\n/memos-bdi/\n__pycache__/\n',encoding='utf-8')
    (KIT/'.gitattributes').write_text('* text eol=lf\n*.sh text eol=lf\n',encoding='utf-8')
    batch.save(KIT/'package.json',dict(schema_version=1,preview_only=preview,controls=pins,
        files={n.as_posix():batch.digest(KIT/n) for n in sorted(names)},
        note='Native control commits are selected before the kit-only publication commit.'))
    if not preview:
        for shell in (KIT/'scripts').glob('*.sh'):
            git(ROOT/'memos-current','add','--',shell.relative_to(ROOT/'memos-current').as_posix())
            git(ROOT/'memos-current','update-index','--chmod=+x','--',shell.relative_to(ROOT/'memos-current').as_posix())
    print(('PREVIEW ONLY' if preview else 'PASS')+': kit staged at '+str(KIT))


def publish():
    manifest=batch.read(KIT/'package.json')
    if manifest['preview_only']:raise ValueError('Run package after native commits')
    for name,digest in manifest['files'].items():
        if batch.digest(KIT/name)!=digest:raise ValueError('Package changed: '+name)
    for arm in ('bdi','conventional'):
        spec=manifest['controls'][arm];repo=ROOT/spec['checkout']
        if git(repo,'status','--porcelain','--untracked-files=normal'):raise ValueError('Commit changes before publish: '+arm)
        # The default branch must contain job-execution.yml for GitHub dispatch.
        if git(repo,'branch','--show-current')!='main':raise ValueError('Publish from main after merging reviewed changes')
        if git(repo,'diff','--name-only',spec['control_sha'],'HEAD','--','.',':(exclude)experiment-kit'):
            raise ValueError('Native source changed after packaging; run package again: '+arm)
        refs=['HEAD:refs/heads/main','refs/tags/'+spec['control_ref']]
        for label,release in batch.read(ROOT/'protocol/frozen-releases.json')['releases'].items():
            tag='memos-app-'+label+'-'+release['application_sha'][:12]
            if not git(repo,'tag','--list',tag):git(repo,'tag',tag,release['application_sha'])
            refs.append('refs/tags/'+tag)
        subprocess.run(['git','-C',str(repo),'push','--atomic','origin',*refs],check=True)
    print('PASS: controls, application objects and experiment kit published')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['validate','package','preview','publish']);a=p.parse_args()
    if a.action=='validate':
        validate()
        for pattern in ('test_study_workflow.py','test_phase5_metrics.py','test_bdi_policy.py','test_image_identity.py','test_local_batch.py','test_pull_results.py',
                        'test_alignment_contract.py','test_exact_count.py','test_server_execution.py','test_bdi_reset.py','test_linux_workflow.py'):
            subprocess.run([sys.executable,'-B','-m','unittest','discover','-s',str(ROOT/'tools'),'-p',pattern],check=True)
        subprocess.run([sys.executable,'-B','-m','unittest','discover','-s',str(ROOT/'memos-bdi/bdi-cicd-framework/parser'),'-p','test_*.py'],check=True)
        subprocess.run([sys.executable,'-B','-m','unittest','discover','-s',str(ROOT/'memos-bdi/experiment/scripts'),'-p','test_*.py'],check=True)
        batch.save(ROOT/'results/local-validation.json',dict(status='PASS',source_hashes=batch.source_hashes(),completed_at=batch.now(),live_execution=False))
        print('PASS: local offline regression suites; target-server smoke remains required')
    elif a.action=='publish':publish()
    else:package(a.action=='preview')
