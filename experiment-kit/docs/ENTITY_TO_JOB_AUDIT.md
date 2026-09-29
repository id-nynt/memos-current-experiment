# Entity → Job audit

## Result

The active BDI framework uses Job consistently across pipeline, goal, workflow,
runtime bindings, generated Jason agent, Java execution interface, adapter contract
and `job-execution.yml`. Removed Entity execution classes/workflow must be committed
as deletions together with their Job replacements. Do not publish only the new files.

The audit validates the four source inputs, generated workflow/agent and generator
fingerprints; adapter job names/environments/outcomes; and production code vocabulary.
Parser tests deliberately retain legacy-schema rejection examples. Historical runs,
archived protocols and unrelated `identity`/domain concepts remain unchanged.

## Conflicts fixed

- Shared metric normalization still expected `entity_execution_*` and `entity`.
  It now reads Job events and counts retries, deployments, rollback and detections.
  A separate reader translates old records without changing raw evidence.
- The final shared BDI policy fingerprint still named the old workflow and Java
  class. It now identifies Job code and current reviewed consumers.
- The BDI measurement contract had Job wording while the shared/Conventional
  contracts still described Entity executions. Their common definitions now agree.
- Policy reporting still read `BDI_ENTITY_TIMEOUT_MINUTES`; it now reads the
  actual `BDI_JOB_TIMEOUT_MINUTES` and reports Job limits.
- Shared S6 evidence checks and workflow audit defaults still used Entity names.
  Active paths now use Job, with explicit historical evidence compatibility.
- The old workflow bootstrap generator could recreate Entity/hosted workflows.
  It is retired and stops without writing files. The offline Jason/S6 mock driver
  now uses the Job dispatch contract.
- Worker image verification assumed the committed image digest was always the
  runtime freeze. Both controls now resolve the same verified Linux image session.
- Conventional's frozen-source guard is refreshed and audited alongside BDI's
  fingerprints. Server preparation sets the fixture-root repository variable to
  the actual pinned Conventional worktree, including after the kit-only commit.

`tools/job_audit.py` checks current consistency. Its explicit
`--refresh-fingerprints` option is for a developer updating reviewed changes locally,
not a server bypass for arbitrary modifications. Old policy fingerprints remain in
historical contracts; the new runner selects the final Job contract.

## Validation and remaining deployment work

Local validation: 295 Python tests across the selected suites (four intentional
skips), successful Gradle verification with 46 passing Java test results, and a real
Jason/Job-adapter integration against loopback mocks. The integration observes the
actual deterministic fixture failure, correlated adapter-result artifact, retry,
new execution UUID/run ID and achieved goal. It is not live experiment evidence.
Shell scripts, guide examples, package hashes and Python syntax are checked too.

At implementation delivery the native changes are working-tree changes. Commit/package/publish them
with the short guide before a fresh server can select the new controls. Genuine
Linux builds, runner dispatch, qualification, healthy M001 and failure smoke are
target-server checks; they are not replaced by local test success. Windows-only
test assumptions were corrected: mocked POSIX detection no longer changes pathlib,
UID/GID calls are mocked, and POSIX mode-bit assertions remain Linux-only.

## Delivery files

| Area | Created or updated |
|---|---|
| Operator guide | `SERVER_EXECUTION_SIMPLE.md`; README and old Linux-guide redirect |
| Technical notes | `docs/SERVER_PREPARATION_INTERNALS.md`, `EXPERIMENT_PROVENANCE.md`, `ENTITY_TO_JOB_AUDIT.md`, `STUDY_BATCH_DESIGN.md` |
| Distribution | `memos-current/experiment-kit/`; `package.json` lists every included file/hash |
| Entry scripts | `scripts/server-prepare.sh`, `run-smoke.sh`, `run-study.sh`, `validate-results.sh`, `export-results.sh`, `_common.sh` |
| New shared code | `tools/local_prepare.py`, `server_prepare.py`, `study_batches.py`, `study_execution.py`, `job_audit.py`, `job_events.py`, `test_study_workflow.py` |
| Study protocol | `protocol/study-batches.json`; current BDI-policy and measurement contracts |
| Existing shared code | `experiment.py`, `batch_runner.py`, `linux_prepare.py`, `pull_results.py`, `image_identity.py`, `bdi_policy.py`, `bdi_reset.py`, `phase5_metrics.py`, `exact_measurements.py`, `measure_trial.py`, `check_s6_evidence.py`, `validate_s6_offline.py`, `workflow_audit.py`, `server_migration.py`; related tests |
| Retired generator | `tools/create_experiment_workflows.py` now exits without writing obsolete workflows |
| Conventional integration | `experiment/manage.py`, `experiment/frozen-control.json`; measurement image resolver, summary helper and contract |
| BDI integration | `experiment/adapter-contract.json`; both image-resolver copies; `scripts/bootstrap.py`, `operate.py`, `run.py`; Windows-portable adapter/control/preparation tests |

Existing user refactor changes in models, generators, agent, Java classes and
`job-execution.yml` were preserved and audited, not replaced with a second model.
