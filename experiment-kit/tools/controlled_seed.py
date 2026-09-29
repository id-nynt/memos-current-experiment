"""Private controlled seed import and reset-only restore. Never used by rollback."""
import image_identity as images_identity
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import time

BACKUP = 'tar -czf /backup/data.tar.gz -C /data .; tar -tzf /backup/data.tar.gz >/dev/null'
RESTORE = 'find /data -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +; tar -xzf /seed/data.tar.gz -C /data'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate(directory, v1):
    directory=Path(directory).resolve()
    manifest=json.loads((directory/'manifest.json').read_text())
    if manifest['owner']!='memos-current-experiment' or manifest['application_sha']!=v1['application_sha']:
        raise ValueError('Seed owner/release mismatch')
    if digest(directory/'data.tar.gz')!=manifest['archive_sha256']:
        raise ValueError('Controlled seed checksum mismatch')
    with tarfile.open(directory/'data.tar.gz') as archive:
        members=archive.getmembers()
        for item in members:
            p=PurePosixPath(item.name)
            if p.is_absolute() or '..' in p.parts or not (item.isfile() or item.isdir()):
                raise ValueError('Unsafe seed archive entry')
        if not members:raise ValueError('Empty seed')
    credential=json.loads((directory/'credential.json').read_text())
    seal=json.loads((directory/'seed-seal.json').read_text())
    if seal!={name:digest(directory/name) for name in ('data.tar.gz','manifest.json','credential.json')}:
        raise ValueError('Controlled seed seal mismatch')
    if not all(credential.get(k) for k in ('token','sentinel_name','sentinel_content')):
        raise ValueError('Missing seed credentials')
    return dict(directory=directory,manifest=manifest,credential=credential,seal=seal)


def import_seed(source_state, destination, v1):
    """Explicit local operator preparation. Credentials remain outside evidence."""
    source=Path(source_state).resolve();destination=Path(destination).resolve()
    if destination.exists():raise ValueError('Seed import is one-time; do not overwrite provenance')
    destination.mkdir(mode=0o700,parents=True)
    for name in ('data.tar.gz','manifest.json'):
        shutil.copyfile(source/'seed'/name,destination/name)
    shutil.copyfile(source/'credentials/staging/credential.json',destination/'credential.json')
    for p in destination.iterdir():p.chmod(0o600)
    (destination/'seed-seal.json').write_text(json.dumps({name:digest(destination/name) for name in ('data.tar.gz','manifest.json','credential.json')}))
    return validate(destination,v1)


def helper_command(image, volume, directory, operation):
    if operation not in ('backup','restore') or not volume.startswith('memos-experiment-bdi-') or not volume.endswith('_data'):
        raise ValueError('Invalid controlled volume operation')
    if volume not in ('memos-experiment-bdi-staging_data','memos-experiment-bdi-production_data'):
        raise ValueError('Foreign data volume')
    directory=Path(directory).resolve()
    if ',' in str(directory):raise ValueError('Invalid Docker mount path')
    destination='backup' if operation=='backup' else 'seed'
    return ['docker','run','--rm','--pull','never','--network','none','--user','0','--entrypoint','/bin/sh',
            '--mount','type=volume,source='+volume+',target=/data'+(',readonly' if operation=='backup' else ''),
            '--mount','type=bind,source='+str(directory)+',target=/'+destination+(',readonly' if operation=='restore' else ''),
            image,'-ec',BACKUP if operation=='backup' else RESTORE]


def restore_verified(ops,args,seed,v1,command):
    from common import save, now, http, identity
    # Caller holds study/campaign/operation locks and has checked both volumes.
    runtime_image = images_identity.runtime_id(v1, lambda value: json.loads(command(['docker','image','inspect',value],args.evidence,'seed-image'))[0])
    cmd,env=ops.compose(args,runtime_image,Path(ops.current(args)['evidence_directory']),args.execution_id)
    command(cmd+['stop','traffic','proxy','memos'],args.evidence,'seed-stop',env=env)
    backup=args.state/'private-reset-backups'/args.trial_id/args.environment
    backup.mkdir(parents=True,exist_ok=False,mode=0o700)
    shutil.copyfile(args.environment_state/'credential.json',backup/'credential.json')
    (backup/'credential.json').chmod(0o600)
    command(helper_command(runtime_image,args.project+'_data',backup,'backup'),args.evidence,'seed-backup')
    command(helper_command(runtime_image,args.project+'_data',seed['directory'],'restore'),args.evidence,'seed-restore')
    cred=args.environment_state/'credential.json'
    save(cred,seed['credential']);cred.chmod(0o600)
    command(cmd+['up','-d','--no-deps','--no-build','--pull','never','memos','proxy'],args.evidence,'seed-start',env=env)
    expected=json.loads((args.environment_state/'current.json').read_text())
    deadline=time.monotonic()+60
    while True:
        try:identity(args.base,expected);break
        except Exception:
            if time.monotonic()>=deadline:raise
            time.sleep(2)
    warmup=time.monotonic()+ops.POLICY['warmup_seconds']
    while True:
        status,body=http(args.base+'/api/v1/'+seed['credential']['sentinel_name'],token=seed['credential']['token'])
        if status!=200 or json.loads(body).get('content')!=seed['credential']['sentinel_content']:
            raise ValueError('Controlled seed sentinel failed')
        if time.monotonic()>=warmup:break
        time.sleep(1)
    for i in range(ops.POLICY['consecutive_healthy']):
        if not ops.observe(args):raise ValueError('Restored seed telemetry verification failed')
        if i+1<ops.POLICY['consecutive_healthy']:time.sleep(ops.POLICY['interval_seconds'])
    expected.update(verified=True,verified_at=now(),controlled_seed_sha256=seed['manifest']['archive_sha256'])
    save(args.evidence/'verified-deployment.json',expected)
    save(args.environment_state/'known-good.json',expected)
    return dict(archive_sha256=seed['manifest']['archive_sha256'],private_backup_sha256=digest(backup/'data.tar.gz'),
                data_semantics='shared-controlled-seed',traffic='CRUD stopped until candidate deployment',
                sentinel_verified=True,telemetry_verified=True)
