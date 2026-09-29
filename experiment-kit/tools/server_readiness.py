"""Read-only server inventory. Never installs, dispatches, pulls, or prints secrets."""
import image_identity as images_identity
import datetime as dt
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import sys
import urllib.request
import batch_runner as batch
import phase8_matrix as matrix
from workflow_audit import reachable

ROOT = batch.ROOT
DEFERRED = 'REQUIRES TARGET-SERVER VALIDATION'
PROJECTS = ('memos-current-experiment-staging', 'memos-current-experiment-production',
            'memos-experiment-bdi-staging', 'memos-experiment-bdi-production')
PORTS = (5541, 5542, 5543, 5544, 5420, 5421, 9420, 9421)


def probe(argv):
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=25)
        return proc.returncode == 0, proc.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return False, ''


def report(target=False, config=None):
    checks = []
    def add(name, status, detail):checks.append(dict(check=name, status=status, detail=detail))
    def boolean(name, ok, detail):add(name, 'PASS' if ok else 'BLOCKER', detail)
    manifest = batch.read(matrix.MANIFEST)
    batch.validate_plan(manifest)
    sources = batch.source_hashes()
    jobs = reachable()
    add('matrix/workflows', 'PASS', f"100 pairs; {len(jobs)} reachable self-hosted Linux job definitions; no dispatch")
    boolean('Python/PyYAML', sys.version_info >= (3,11) and importlib.util.find_spec('yaml') is not None,
            'Python 3.11+ and PyYAML required in operator and runner environments')
    from experiment import selection
    try:
        selection('bdi')
        add('local frozen identities', 'PASS', 'Both selected tags, application Git trees and frozen release manifests agree')
    except (ValueError, OSError, subprocess.CalledProcessError):
        add('local frozen identities', 'BLOCKER', 'Missing or inconsistent local Git control/application objects')
    pins = batch.read(ROOT / 'protocol/operator-revisions.json')
    for arm in ('conventional','bdi'):
        spec = pins[arm];repo=ROOT/spec['checkout']
        relative = 'experiment/scripts/matrix-scenarios.json' if arm=='bdi' else 'experiment/matrix-scenarios.json'
        ok, raw = probe(['git','-C',str(repo),'show',spec['control_sha']+':'+relative])
        boolean(arm+' published-source selection', ok and raw.replace('\r\n','\n')==(repo/relative).read_text().strip(),
                'Selected control must contain the exact final matrix; historical pins are blocked')
        ok, raw = probe(['git','-C',str(repo),'status','--porcelain','--untracked-files=normal','--','experiment','scripts','.github/workflows','bdi-cicd-framework'])
        boolean(arm+' clean execution checkout', ok and not raw,
                'Commit reviewed execution sources before publication; preserve existing edits')
    boolean('final BDI policy selected', pins['bdi'].get('policy_contract')=='protocol/bdi-policy-final-source.json',
            'Historical BDI fingerprint contract cannot execute the final matrix')
    shell_paths = []
    for name in sources:
        p = ROOT/name
        if p.suffix=='.sh' or p.name=='gradlew':shell_paths.append(p)
    bad_lf=[p.relative_to(ROOT).as_posix() for p in shell_paths if b'\r' in p.read_bytes()]
    add('Linux shell line endings', 'BLOCKER' if target and bad_lf else 'WARNING' if bad_lf else 'PASS',
        bad_lf or 'Selected shell source has LF line endings')
    if not target:
        for name in ('Linux architecture/CPU/RAM/disk', 'clock synchronization', 'Docker/Compose/access/images',
                     'Java/Jason/PowerShell/Node/Go', 'ports/container/network/volume ownership',
                     'private seed/credential presence', 'GitHub access/runner placement/dependency connectivity',
                     'qualification/reset/healthy startup/interruption rehearsal'):
            add(name, DEFERRED, 'Local source inspection cannot establish target-server readiness')
    elif platform.system()!='Linux':
        add('target platform', 'BLOCKER', '--target must run on the university Linux server')
    else:
        boolean('Linux amd64', platform.machine() in ('x86_64','amd64'), 'Frozen artifacts require linux/amd64')
        memory = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemTotal:')))*1024
        free = shutil.disk_usage(ROOT).free
        add('capacity', 'PASS' if (os.cpu_count() or 0)>=4 and memory>=8*1024**3 and free>=50*1024**3 else 'WARNING',
            dict(cpus=os.cpu_count(),ram_gib=round(memory/1024**3,1),free_gib=round(free/1024**3,1),
                 note='Planning floor: 4 CPU/8 GiB/50 GiB free; prove capacity with smoke, monitor evidence/backup growth'))
        for name in ('git','docker','gh','pwsh','java','javac','tar','bash','curl','unzip','jq'):
            boolean('executable '+name, shutil.which(name) is not None, 'Required on the operator/runner PATH')
        for name in ('node','npm','go','pnpm'):
            add('executable '+name, 'PASS' if shutil.which(name) else 'WARNING',
                'Workflow setup actions provide pinned versions; verify downloads/cache and service PATH')
        ok, raw=probe(['java','-version']) # Java version goes to stderr; javac has a stable stdout version.
        ok, raw=probe(['javac','-version'])
        boolean('JDK 21+',ok and raw.startswith('javac ') and raw.split()[1].split('.')[0].isdigit() and int(raw.split()[1].split('.')[0])>=21,'Controller compiles for Java 21; Jason 3.3.0 resolves through Gradle')
        ok, raw=probe(['pwsh','-NoProfile','-Command','$PSVersionTable.PSVersion.Major'])
        boolean('PowerShell 7',ok and raw.isdigit() and int(raw)>=7,'Same Conventional deployment script runs under pwsh')
        ok, raw=probe(['timedatectl','show','-p','NTPSynchronized','--value'])
        boolean('host clock synchronized',ok and raw=='yes','Also retain clock evidence for every runner host; local NTP alone cannot attest cross-host alignment')
        ok, raw=probe(['docker','version','--format','{{.Server.Os}}/{{.Server.Arch}}'])
        boolean('Docker daemon and permissions',ok and raw=='linux/amd64','Current non-root runner/operator user must access the same daemon')
        for args in (['docker','compose','version'],['docker','buildx','version']):
            ok,_=probe(args);boolean(' '.join(args),ok,'Required by existing deployment/quality paths')
        # Actual Compose parser test, including the !override syntax used by the fixture.
        env=dict(os.environ,MEMOS_IMAGE='sha256:'+'0'*64,MEMOS_HOST_PORT='5542',MEMOS_DATA_VOLUME=PROJECTS[1]+'_data')
        try:
            proc=subprocess.run(['docker','compose','-f',str(ROOT/'memos-current/scripts/local-cd/compose.yaml'),
                '-f',str(ROOT/'memos-current/experiment/runtime-port.yaml'),'config','--format','json'],env=env,capture_output=True,text=True,timeout=25)
            boolean('Compose fixture override',proc.returncode==0 and str(json.loads(proc.stdout)['services']['memos']['ports'][0]['published'])=='5543','Production backend override must replace, not append, port bindings')
        except (OSError,ValueError,KeyError,subprocess.TimeoutExpired):boolean('Compose fixture override',False,'Compose must support !override')
        for name, release in batch.read(ROOT/'protocol/frozen-releases.json')['releases'].items():
            try:
                def inspect(value):
                    ok, raw = probe(['docker','image','inspect',value])
                    if not ok: raise subprocess.CalledProcessError(1, 'docker image inspect')
                    return json.loads(raw)[0]
                images_identity.resolve(release, inspect)
                good=True
            except (ValueError,KeyError,IndexError,TypeError,subprocess.CalledProcessError):good=False
            boolean('frozen image '+name,good,'Exact retained ID/platform/application-SHA label; never rebuilt by candidates')
        for name, image in batch.read(ROOT/'memos-bdi/experiment/sidecar-images.json').items():
            ok,_=probe(['docker','image','inspect',image]);boolean('retained sidecar '+name,ok,'Digest-pinned sidecar must be provisioned before qualification')
        ok,raw=probe(['docker','ps','-q'])
        owners={}
        if ok:
            for cid in raw.splitlines():
                good,details=probe(['docker','inspect',cid])
                if not good:continue
                obj=json.loads(details)[0];project=obj['Config'].get('Labels',{}).get('com.docker.compose.project')
                for bindings in (obj.get('NetworkSettings',{}).get('Ports') or {}).values():
                    for binding in bindings or []:owners[int(binding['HostPort'])]=project
        for port in PORTS:
            with socket.socket() as sock:
                try:sock.bind(('127.0.0.1',port));free_port=True
                except OSError:free_port=False
            expected=PROJECTS[0] if port in (5541,5544) else PROJECTS[1] if port in (5542,5543) else PROJECTS[2] if port in (5421,9421) else PROJECTS[3]
            # Public fixture ports are Python-owned only during a candidate; idle readiness must reject them.
            boolean('port '+str(port),free_port or owners.get(port)==expected,'Free or bound by the expected experiment Compose project')
        for project in PROJECTS:
            for kind,name in (('volume',project+'_data'),('network',project+'_default')):
                ok,raw=probe(['docker',kind,'inspect',name])
                if not ok:add(kind+' '+name,'WARNING','Absent; first-time setup must provision and verify ownership')
                else:
                    obj=json.loads(raw)[0]
                    boolean(kind+' '+name,(obj.get('Labels') or {}).get('com.docker.compose.project')==project,'Foreign ownership blocks execution')
        state=Path.home()/'memos-bdi-state'
        conventional=Path(os.environ.get('LOCALAPPDATA',Path.home()))/'memos-current-experiment'
        try:
            import controlled_seed
            v1=batch.read(ROOT/'protocol/frozen-releases.json')['releases']['v1']
            seed=controlled_seed.validate(state/'phase7-seed',v1)
            boolean('shared private seed integrity',batch.digest(conventional/'seed/data.tar.gz')==seed['manifest']['archive_sha256'],
                    'Sealed seed and Conventional archive hashes match; credentials not emitted')
        except (OSError,ValueError,KeyError):boolean('shared private seed integrity',False,'Provision a matching sealed private controlled seed')
        try:
            spec=pins['bdi'];receipt=batch.read(state/'adapters'/(spec['control_sha']+'.json'))
            native=ROOT/spec['checkout']/'experiment';sidecars=batch.read(native/'sidecar-images.json')
            digest=hashlib.sha256()
            for p in sorted((native/'scripts').glob('*.py')):digest.update(p.read_bytes())
            for name in ('adapter.Dockerfile','scripts/rq1-s4r-s5r.json','scripts/scenario-catalogue.json','scripts/matrix-scenarios.json'):digest.update((native/name).read_bytes())
            digest.update(sidecars['python'].encode())
            ok,raw=probe(['docker','image','inspect',receipt['image_id']])
            meta=json.loads(raw)[0]
            boolean('prepared BDI adapter',ok and receipt['control_sha']==spec['control_sha'] and receipt['source_hash']==digest.hexdigest()
                    and receipt['base_images']==sidecars and meta['Id']==receipt['image_id'] and meta['Os']=='linux' and meta['Architecture']=='amd64',
                    'Existing exact adapter receipt/image/source checked; checker never builds')
        except (OSError,ValueError,KeyError,IndexError):boolean('prepared BDI adapter',False,'Prepare support adapter explicitly for selected immutable control')
        try:
            from bdi_reset import qualified_reference
            spec=pins['bdi']
            qualified_reference(dict(repository=spec['repository'],control_sha=spec['control_sha'],control_ref=spec['control_ref'],state=str(state)),
                                batch.read(ROOT/'protocol/frozen-releases.json'))
            add('genuine v1 qualification','PASS','Matching sealed achieved qualification and correlated terminal workers verified')
        except (OSError,ValueError,KeyError,IndexError):boolean('genuine v1 qualification',False,'Run genuine qualification for the selected control; old receipts cannot qualify new source')
        for path in (conventional/'seed/data.tar.gz',conventional/'seed/manifest.json',
                     *(conventional/'credentials'/e/'credential.json' for e in ('staging','production')),
                     state/'phase7-seed/data.tar.gz',state/'phase7-seed/seed-seal.json',
                     *(state/'bdi'/e/'credential.json' for e in ('staging','production'))):
            boolean('private file '+str(path.relative_to(path.anchor)),path.is_file() and not path.is_symlink() and not path.stat().st_mode&0o077,
                    'Presence and private permissions only; values are never printed')
        for p in shell_paths:
            if p.name=='gradlew':boolean('executable '+p.relative_to(ROOT).as_posix(),os.access(p,os.X_OK),'Preserve Git executable modes on Linux')
        for arm in ('conventional','bdi'):
            spec=pins[arm];repo=spec['repository']
            ok,raw=probe(['gh','api','repos/'+repo+'/commits/'+spec['control_ref'],'--jq','.sha'])
            boolean(arm+' GitHub published tag',ok and raw==spec['control_sha'],'Authenticated read access; immutable published SHA must match selection')
            ok,raw=probe(['gh','api','--paginate','--slurp','repos/'+repo+'/actions/runners?per_page=100'])
            try:
                runners=[r for page in json.loads(raw) for r in page['runners']]
                eligible=[r for r in runners if r['status']=='online' and not r['busy'] and {'self-hosted','linux','memos-bdi-deploy'}<={v['name'].lower() for v in r['labels']}]
                if arm=='conventional':eligible=[r for r in eligible if r['name']==batch.read(ROOT/'memos-current/experiment/config.json')['runner_name']]
            except (ValueError,KeyError,TypeError):eligible=[]
            boolean(arm+' online idle runner',ok and bool(eligible),'Repository-scoped labels verified; operator must attest same host/user/daemon')
        for host in ('github.com','api.github.com','objects.githubusercontent.com','raw.githubusercontent.com',
                     'results-receiver.actions.githubusercontent.com','registry.npmjs.org','proxy.golang.org',
                     'sum.golang.org','repo.maven.apache.org','services.gradle.org','registry-1.docker.io','ghcr.io'):
            try:
                socket.getaddrinfo(host,443)
                import ssl
                with socket.create_connection((host,443),timeout=5) as conn:
                    with ssl.create_default_context().wrap_socket(conn,server_hostname=host):pass
                add('TLS '+host,'PASS','DNS/TLS connection only; package/action/artifact authorization still requires target smoke')
            except OSError:add('TLS '+host,'BLOCKER','Dependency endpoint DNS/TLS unavailable')
        add('runner service context / package downloads / qualification / calibration / interruption','WARNING',
            'Verify as the actual service user and retain live qualification, healthy startup, artifacts and remote-work reconciliation evidence')
    return dict(schema_version=1,created_at=batch.now(),target_checks=target and platform.system()=='Linux',
                host=socket.gethostname(),user=os.environ.get('USER',os.environ.get('USERNAME')),
                matrix_sha256=matrix.sha(manifest),operator_manifest_sha256=batch.digest(ROOT/'protocol/operator-revisions.json'),
                source_hashes=sources,checks=checks,
                execution_gate_blockers=batch.readiness(config,manifest) if config is not None else ['No execution configuration supplied'],
                launch_authorized=False,phases_13_to_15_verified=False)
