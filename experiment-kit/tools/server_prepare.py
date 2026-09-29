"""Idempotent server preparation using the versioned kit and native operators."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import batch_runner as batch

ROOT=batch.ROOT
SETUP=ROOT/'results/setup'


def run(argv,**kwargs):
    subprocess.run([str(x) for x in argv],check=True,**kwargs)


def python(relative,*args):run([sys.executable,'-B',ROOT/relative,*args])


def api(path):return json.loads(subprocess.check_output(['gh','api',path],text=True))


def step(name,action):
    folder=SETUP/name
    if (folder/'complete.json').exists():return
    if folder.exists():raise ValueError('Incomplete preparation stage retained: '+str(folder)+'; diagnose before retrying')
    folder.mkdir(parents=True)
    batch.save(folder/'started.json',dict(time=batch.now()),new=True)
    action()
    batch.save(folder/'complete.json',dict(time=batch.now()),new=True)
    print('PASS: '+name,flush=True)


def checkout():
    dirty=subprocess.check_output(['git','-C',str(ROOT.parent),'status','--porcelain','--untracked-files=normal','--','experiment-kit'],text=True).strip()
    if dirty:raise ValueError('The cloned experiment kit has local changes; configure and publish on Windows instead')
    package=batch.read(ROOT/'package.json')
    if package['preview_only']:raise ValueError('Preview kit cannot execute; package after native commits')
    for name,digest in package['files'].items():
        if batch.digest(ROOT/name)!=digest:raise ValueError('Published kit changed: '+name)
    actual={p.relative_to(ROOT).as_posix() for base in ('tools','protocol','scenarios','scripts','docs')
            for p in (ROOT/base).rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    expected={n for n in package['files'] if n.split('/')[0] in ('tools','protocol','scenarios','scripts','docs')}
    if actual!=expected:raise ValueError('Unexpected or missing files in the published kit')
    pins=package['controls']
    for arm in ('conventional','bdi'):
        spec=pins[arm];repo=ROOT/spec['checkout']
        if not repo.exists():
            if arm=='conventional':repo.symlink_to(ROOT.parent,target_is_directory=True)
            else:run(['git','clone','https://github.com/'+spec['repository']+'.git',repo])
        run(['git','-C',repo,'fetch','origin','--tags'])
        if arm=='bdi':
            if subprocess.check_output(['git','-C',repo,'status','--porcelain']).strip():raise ValueError('BDI checkout changed')
            run(['git','-C',repo,'checkout','--detach',spec['control_sha']])
    from experiment import selection,published
    selection('bdi')
    for arm in ('conventional','bdi'):published(pins[arm],arm)
    return pins


def images():
    from linux_prepare import prepare
    directory=ROOT/'results/frozen-images'
    prepare(directory,publication_required=False)
    body=dict(schema_version=1,source_releases=batch.read(ROOT/'protocol/frozen-releases.json'),
              frozen_releases=batch.read(directory/'frozen-releases.json'),proofs=batch.read(directory/'frozen-runtime-identities.json'),
              build_tools=batch.read(directory/'build-tools.json'),health=batch.read(directory/'COMPLETE.json')['health'])
    body['sha256']=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    destination=Path.home()/'.memos-experiment-images/session.json'
    if destination.exists():
        if batch.read(destination)!=body:raise ValueError('Another image session already exists; never replace an active study freeze')
    else:batch.save(destination,body,new=True);destination.chmod(0o600)
    batch.save(SETUP/'image-session.json',body)
    import image_identity
    for release in body['source_releases']['releases'].values():image_identity.resolve(release)


def runners(pins):
    """Register official, digest-verified runner distributions under this user."""
    for arm in ('conventional','bdi'):
        spec=pins[arm];name='memos-current-linux' if arm=='conventional' else 'memos-bdi-experiment'
        folder=Path.home()/('actions-runner-'+arm)
        folder.mkdir(exist_ok=True)
        if not (folder/'config.sh').exists():
            release=api('repos/actions/runner/releases/latest')
            assets=[a for a in release['assets'] if a['name'].startswith('actions-runner-linux-x64-') and a['name'].endswith('.tar.gz')]
            if len(assets)!=1 or not assets[0].get('digest','').startswith('sha256:'):raise ValueError('Official runner asset must have a published SHA256 digest')
            asset=assets[0];archive=folder/'runner.tar.gz'
            urllib.request.urlretrieve(asset['browser_download_url'],archive)
            if 'sha256:'+batch.digest(archive)!=asset['digest']:raise ValueError('Runner download checksum mismatch')
            with tarfile.open(archive) as tar:tar.extractall(folder,filter='data')
            batch.save(folder/'distribution.json',dict(version=release['tag_name'],sha256=asset['digest']))
        if not (folder/'.runner').exists():
            token=api_post('repos/'+spec['repository']+'/actions/runners/registration-token')['token']
            # Never print argv: registration token is transient and not evidence.
            registered=subprocess.run(['bash',str(folder/'config.sh'),'--unattended','--url','https://github.com/'+spec['repository'],
                 '--token',token,'--name',name,'--labels','memos-bdi-deploy','--work','_work'],cwd=folder)
            if registered.returncode:raise RuntimeError('Runner registration failed; token omitted from diagnostics')
        config=batch.read(folder/'.runner')
        if config['agentName']!=name or config['gitHubUrl'].rstrip('/')!='https://github.com/'+spec['repository']:
            raise ValueError('Existing runner belongs to another repository/name')
        (folder/'.path').write_text(str(Path(sys.executable).parent)+os.pathsep+os.environ['PATH'])
        remote=api('repos/'+spec['repository']+'/actions/runners/'+str(config['agentId']))
        if remote['status']!='online':
            with (folder/'listener.log').open('ab') as log:
                subprocess.Popen(['bash',str(folder/'run.sh')],cwd=folder,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            for _ in range(30):
                time.sleep(2)
                remote=api('repos/'+spec['repository']+'/actions/runners/'+str(config['agentId']))
                if remote['status']=='online':break
        if remote['status']!='online' or remote['busy']:raise ValueError('Runner not online and idle: '+name)
        inventory=api('repos/'+spec['repository']+'/actions/runners?per_page=100')
        eligible=[r['id'] for r in inventory['runners'] if {'self-hosted','linux','memos-bdi-deploy'}<={v['name'].lower() for v in r['labels']}]
        if inventory['total_count']>100 or eligible!=[config['agentId']]:raise ValueError('Another eligible runner could execute on a different host; isolate the experiment runner labels')
        batch.save(SETUP/(arm+'-runner.json'),dict(id=config['agentId'],name=name,host=platform.node(),uid=os.getuid(),directory=str(folder),repository=spec['repository']))


def api_post(path):return json.loads(subprocess.check_output(['gh','api','--method','POST',path],text=True))


def fixture_root(pins):
    # The kit-only publication commit is newer than the selected Conventional
    # control. Point the workflow at its actual detached runtime, not the clone.
    from experiment import runtime
    directory=runtime(pins['conventional'],'conventional').resolve()
    repository=pins['conventional']['repository']
    run(['gh','variable','set','MEMOS_EXPERIMENT_ROOT','--repo',repository,'--body',directory])
    actual=subprocess.check_output(['gh','variable','get','MEMOS_EXPERIMENT_ROOT','--repo',repository],text=True).strip()
    if actual!=str(directory):raise ValueError('Conventional fixture root was not configured correctly')
    batch.save(SETUP/'conventional-fixture-root.json',dict(path=str(directory),control_sha=pins['conventional']['control_sha']))


def private_state(pins):
    python('memos-bdi/experiment/scripts/prepare.py','images')
    v1=batch.read(ROOT/'protocol/frozen-releases.json')['releases']['v1']
    python('memos-bdi/experiment/scripts/operate.py','prepare-adapter','--approach','bdi','--release-sha',v1['application_sha'],
           '--execution-id','server-adapter','--trial-id','server-adapter','--evidence',SETUP/'adapter')
    python('memos-current/experiment/manage.py','init')
    python('memos-bdi/experiment/scripts/prepare.py','accounts','--repository',pins['bdi']['repository'])
    from controlled_seed import import_seed
    import_seed(Path(os.environ.get('LOCALAPPDATA',Path.home()))/'memos-current-experiment',Path.home()/'memos-bdi-state/phase7-seed',v1)


def readiness():
    from server_readiness import report
    value=report(True)
    batch.save(SETUP/'readiness.json',value)
    blockers=[r for r in value['checks'] if r['status'] in ('BLOCKER','REQUIRES TARGET-SERVER VALIDATION')]
    if blockers:raise ValueError('Readiness failed: '+json.dumps(blockers))
    return value


def main():
    if platform.system()!='Linux' or os.geteuid()==0:raise ValueError('Run as the non-root Ubuntu experiment user')
    os.umask(0o077)
    missing=[n for n in ('git','docker','gh','pwsh','java','javac','curl','unzip','jq','tar') if not shutil.which(n)]
    if missing:raise ValueError('Install required software first: '+', '.join(missing))
    if platform.machine() not in ('amd64','x86_64'):raise ValueError('The frozen build protocol requires Ubuntu amd64')
    java=subprocess.check_output(['javac','-version'],text=True).strip().split()[-1]
    if int(java.split('.')[0])<21:raise ValueError('JDK 21+ required')
    powershell=subprocess.check_output(['pwsh','-NoProfile','-Command','$PSVersionTable.PSVersion.Major'],text=True).strip()
    if not powershell.isdigit() or int(powershell)<7:raise ValueError('PowerShell 7 required')
    run(['docker','info'],stdout=subprocess.DEVNULL);run(['docker','compose','version']);run(['docker','buildx','version'])
    run(['gh','auth','status'])
    if subprocess.check_output(['timedatectl','show','-p','NTPSynchronized','--value'],text=True).strip()!='yes':raise ValueError('Clock is not synchronized')
    SETUP.mkdir(parents=True,exist_ok=True)
    if any((ROOT/'results/operator-state'/name).exists() for name in ('batch.lock','bdi.lock','conventional.lock')):
        raise ValueError('An active/unresolved operator lock blocks preparation')
    pins=checkout()
    # Both local runner identities and the shared Docker socket are checked each invocation.
    runners(pins)
    fixture_root(pins)
    step('images',images)
    import image_identity
    if image_identity.session()!=batch.read(SETUP/'image-session.json'):raise ValueError('Image session drift')
    for label,release in batch.read(ROOT/'protocol/frozen-releases.json')['releases'].items():
        try:image_identity.resolve(release)
        except ValueError:
            from frozen_artifacts import verify_bundle
            frozen=ROOT/'results/frozen-images'
            verify_bundle(frozen,batch.read(frozen/'frozen-releases.json'))
            run(['docker','load','-i',frozen/(label+'.tar')])
            image_identity.resolve(release)
    step('private-state',lambda:private_state(pins))
    step('qualification',lambda:python('tools/experiment.py','qualify','bdi'))
    for arm in ('conventional','bdi'):python('tools/experiment.py','reset-v1',arm)
    parity=SETUP/('database-equivalence-'+str(time.time_ns())+'.json')
    python('tools/verify_controlled_seed.py','--output',parity)
    if not batch.read(parity)['equal']:raise ValueError('Database parity failed')
    readiness()
    from study_execution import configure_validation
    configure_validation(parity)
    print('READY: same v1/v2 images, shared seed, two verified runners; run-smoke next')


if __name__=='__main__':
    try:main()
    except Exception as exc:print('FAIL: '+str(exc),file=sys.stderr);raise SystemExit(1)
