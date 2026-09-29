"""Allowlisted shared-source handoff; excludes private state and historical results."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
import batch_runner as batch

ROOT=batch.ROOT
MODULES=('experiment','batch_runner','pinned_conventional','bdi_reset','controlled_seed',
         'verify_controlled_seed','bdi_policy','bdi_attribution','phase5_metrics','phase8_matrix',
         'scenario_runtime','measurement_records','final_timing','exact_measurements','ci_controls',
         'workflow_audit','server_execution','server_readiness','server_migration','frozen_artifacts','image_identity',
         'linux_prepare','export_results','scenario_files','pull_results','job_events','study_batches')


def files():
    names=[f'tools/{name}.py' for name in MODULES]
    names += ['tools/'+n for n in ('scenario-catalogue.json','matrix-scenarios.json','phase6-timing.json','frozen-runtime-identities.json')]
    names += ['protocol/'+n for n in ('operator-revisions.json','frozen-releases.json','frozen-runtime-identities.json','bdi-policy-contract.json',
        'bdi-policy-final-source.json','measurement-contract-v2.json','measurement-contract.json','phase6-timing.json',
        'phase7-measurement.json','exact-count-contract.json','final-coverage-policy.json','scenario-catalogue.json',
        'matrix-scenarios.json','phase8-case-matrix.json','batch-readiness.template.json','rq1-s4r-s5r.json','server-preparation.json')]
    names += ['docs/'+n for n in ('LINUX_EXPERIMENT_GUIDE.md','SERVER_EXECUTION_GUIDE.md','SERVER_EXECUTION_GUIDE_SIMPLE_END_TO_END.md','PORTABLE_IMAGE_MIGRATION.md','SERVER_PREPARATION_CHECKPOINT.md','LOCAL_BATCH_READINESS.md',
        'EXPERIMENT_SOURCE_OF_TRUTH.md','PHASE5_MEASUREMENT.md','PHASE6_TIMING.md','PHASE7_SCENARIO_CATALOGUE.md',
        'PHASE8_CASE_MATRIX.md','BATCH_RUNBOOK.md','WORKFLOW_RUNNER_AUDIT.md','EXACT_COUNT_MEASUREMENT.md')]
    return names


def export(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=False)
    hashes={}
    with tarfile.open(directory/'shared-source.tar','x') as archive:
        for name in files():
            source=ROOT/name
            if not source.is_file() or source.is_symlink():raise ValueError('Missing/unsafe allowlisted source: '+name)
            hashes[name]=batch.digest(source)
            info=archive.gettarinfo(str(source),arcname=name)
            info.uid=info.gid=0;info.uname=info.gname='';info.mode=0o644
            with source.open('rb') as stream:archive.addfile(info,stream)
    batch.save(directory/'handoff.json',dict(schema_version=1,files=hashes,
        archive_sha256=batch.digest(directory/'shared-source.tar'),
        selected_controls=batch.read(ROOT/'protocol/operator-revisions.json'),
        native_repositories_included=False,private_state_included=False,historical_results_included=False,
        execution_authorized=False),new=True)


def verify(directory):
    directory=Path(directory);manifest=batch.read(directory/'handoff.json')
    if batch.digest(directory/'shared-source.tar')!=manifest['archive_sha256']:raise ValueError('Archive checksum mismatch')
    seen=set()
    with tarfile.open(directory/'shared-source.tar') as archive:
        for entry in archive:
            path=PurePosixPath(entry.name)
            if not entry.isfile() or path.is_absolute() or '..' in path.parts or entry.name not in files() or entry.name in seen:
                raise ValueError('Non-allowlisted archive member')
            seen.add(entry.name)
            if hashlib.sha256(archive.extractfile(entry).read()).hexdigest()!=manifest['files'].get(entry.name):
                raise ValueError('Source hash mismatch')
    if seen!=set(manifest['files']) or seen!=set(files()):raise ValueError('Incomplete handoff')
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['export','verify'])
    parser.add_argument('directory',type=Path)
    args=parser.parse_args()
    if args.action=='export':export(args.directory)
    verify(args.directory)
    print('Allowlisted shared-source checksums verified; no private state, native repository, or historical evidence included.')


if __name__=='__main__':main()
