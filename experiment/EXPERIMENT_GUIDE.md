# Conventional experiment: operator guide

This is the operational source of truth for this repository. Run PowerShell commands
from its root. **S0–S3 completed validation; S4–S5 have not been executed.**
The two earlier invalid S3 attempts remain preserved. READY below means setup-ready,
not an observed experimental result. S3 live validation used published harness
`b7db614d3d1ed2d425e9275b422760f062b177b4`.
Do not launch a trial until its harness revision is committed and published.

## Frozen inputs

| Input | Exact identity |
| --- | --- |
| Controller validated by healthy S0 | `67c4731e67ee1ff0a8cc8d3cbfd7459a23ffe667` |
| Earlier decision-policy baseline | `7c6312c1950999ce875b3aa88174fdb03f3478c1` |
| v1 application | `2b5a8be2c2f9cf81599393a227890fb2424a5f03` |
| v2 application | `db695ea0d54cfce6925f07a4715cb42eb6fd8f20` |
| v1 image | `sha256:610a28ab259d8d966851a5318258bdb3dc904a4be1af79c8ec61f3ecd9c281dc` |
| v2 image | `sha256:d08139aec853b76733232f768cab6f771d8ae5055ac48d1b9c27619c67f1e701` |

VERSION=`local-<full application SHA>`, COMMIT=that SHA. v2 changes the release
marker/visible V2 header, not schema or backend behavior. Source tree pins are in
`scripts/local-cd/frozen-releases.json`. Frozen tags are
`memos-20260924-visible-header-v1` and `memos-20260924-visible-header-v2`.
`frozen-control.json` enforces the original deploy script, Compose configuration,
release/config pins and CI files (SHA-256, normalizing only CRLF to LF).
The new fixture/harness revision is distinct: every trial records its exact Git
HEAD and file hashes. Remote `main` must match that HEAD. No application rebuild
or tag repointing is permitted to replace the pinned images.

The controller still uses its existing jobs, 180-second verification deadline,
3-second rechecks, 5-second HTTP timeouts, stopped production backup and manual
recovery. There is no new automatic rollback, reconsideration or retry policy.

## Prerequisites and one-time setup

- Windows FullLanguage PowerShell; Python 3.11+, Git, tar and authenticated `gh`.
- Docker Desktop running Linux/amd64; Compose **2.24.4+**, Buildx; both frozen images
  available locally. Import an existing exact bundle with
  `./experiment/run.ps1 images import C:/frozen-images` if necessary.
- Dedicated `memos-current-windows` runner, labels `self-hosted,Windows,memos-local`,
  registered to **id-nynt/memos-current-experiment**. Runner and operator must use
  the same Windows account, Docker engine and local filesystem. Keep signed in;
  prevent sleep during trials. No concurrent experiments or competing deployments.
- Existing private seed/credentials in `%LOCALAPPDATA%/memos-current-experiment`.
  On a genuinely new host only, `./experiment/run.ps1 init` creates these and v1;
  it refuses to adopt existing data. Never publish private state.

```powershell
./experiment/setup.ps1 -InstallRunner    # only when provisioning the runner
./experiment/run.ps1 check
# Store the path of THIS operator checkout, not the runner's disposable _work checkout:
gh variable set MEMOS_EXPERIMENT_ROOT --repo id-nynt/memos-current-experiment --body "$((Get-Location).Path)"
# After reviewing, committing and publishing the harness to this repository's main:
./experiment/trial.ps1 check --scenario S3
```

`check` does not dispatch or deploy. It verifies frozen files/images, clean tracked
files, exact published HEAD, idle runner, no pending deployments and runtime Compose
port mapping. Setup registers the hidden sign-in task `MemosCurrentActionsRunner`;
GitHub must allow this repository's Actions and the runner must be online.
The existing upgrade smoke uses `neosmemo/memos:0.31.0`; do not push historical tags
or alter the upstream Release workflow.

## Run one case

Each command below automates: fresh seed reset/verified v1 → arm → dispatch **one**
v2 workflow → wait/collect → passive follow-up → record final state → reset/verify v1.
The workflow remains release selection → real backend/frontend/proto jobs → CI
fixture → existing upgrade/build smoke → frozen-image staging/verification → stopped
production backup → same-image production/verification → accepted receipt.
Frozen-image preparation is outside measured time; shared immutable images are reused.

Use a **new trial ID for each authorized new trial**. After interruption, reconcile
and recollect the original run first; do not dispatch a replacement for missing
evidence. The commands below are templates, not authorization to repeat a scenario.

| Scenario | Fault | Trigger/timing | Command | Evidence | Ready? |
| --- | --- | --- | --- | --- | --- |
| S0 | None | Normal pipeline; 600s post-terminal follow-up | `./experiment/trial.ps1 run --scenario S0 --trial S0-001 --no-interventions` | Native/GitHub/health | YES; prior S0 validated |
| S1 | Deterministic extra CI gate exits 42 | After genuine backend/frontend/proto pass; before upgrade/deploy | `./experiment/trial.ps1 run --scenario S1 --trial S1-001 --no-interventions` | CI fixture artifact + skipped downstream jobs | Validated; expected pipeline failure |
| S2 | Existing staging adapter throws | Before first staging Docker mutation, after upgrade smoke | `./experiment/trial.ps1 run --scenario S2 --trial S2-001 --no-interventions` | Native deterministic_failure + unchanged v1 | Validated; expected pipeline failure |
| S3 | Production v2 memo HTTP 503 | `[0,60)` seconds from t0 | `./experiment/trial.ps1 run --scenario S3 --trial S3-001 --no-interventions` | Fault receipts, HTTP workload, native probes | Validated; pipeline success, healthy v2 retained |
| S4 | Persistent production v2 memo HTTP 503 | `[0,900)`; measurement endpoint t0+600 | `./experiment/trial.ps1 run --scenario S4 --trial S4-001 --no-interventions` | Endpoint before independent 900s expiry | YES; not executed |
| S5 | Degradation, recovery, recurrence, recovery | 503 `[0,60)` and `[120,240)`; healthy otherwise | `./experiment/trial.ps1 run --scenario S5 --trial S5-001 --no-interventions` | Every clock boundary and post-terminal health | YES; not executed |

S5 retains the local protocol's predeclared changing-evidence schedule. It is not
cleared in response to a controller decision. No expected winner is encoded.
S1/S2 test the already-present explicit fixtures, not deliberately broken application
sources. If an earlier CI gate fails, the prescribed fault was **not reached**.

For S3–S5, an external adapter changes only the candidate production host binding
to private `127.0.0.1:5543`. A loopback proxy serves the usual `5542`, preserving
instance URL `http://127.0.0.1:5542`. Staging stays on `5541`. Docker image, volume,
container/network names, restart settings and real inspect output remain unchanged.
The proxy returns 503 for **every method** on `/api/v1/memos` and subpaths only when
the backend reports v2; v1, health/profile/frontend and staging are unaffected.
The native controller and external clients use the same public URL. Runtime
faults pass the native controller its ordinary S0 input; the outer manifest and
fault receipts retain the actual S3/S4/S5 label.

The neutral t0 boundary is the first successful production candidate identity,
health and authenticated-sentinel sample, after container start and before the
adapter returns `compose up` to the unchanged controller. Initial fixture readiness
has a 180s setup cap; after readiness, synchronization must finish within **2s** or
the fixture is invalid. Its checks and latency are recorded separately from native
probes. Fault transitions use elapsed monotonic time, never controller outcomes.
This setup interval is instrumentation overhead included in measured deployment
time; it must also be disclosed in any later comparison.

Observation is passive: sentinel GET every 1s without overlap (3s timeout), health
samples 2s after prior completion. S0–S2 observe 600s after resolved pipeline
termination; runtime endpoint is t0+600, retaining later terminal evidence. S4 also
waits for its fixed 900s expiry before cleanup. Pipeline observation cap is 120min;
unresolved work is not silently cancelled. Proxy framing covers these HTTP tests,
not streaming/WebSocket application use. Proxy transport errors are retained;
`fixture-error.json` or an invalid synchronization receipt invalidates the fixture.

## Evidence and completion

`experiment/results/<trial>/` holds manifest/harness hashes, `dispatch.json`,
`github/run.json`, all-attempt job timestamps, full raw log ZIP/extracted logs,
artifacts, native deployment events, `common-observations.jsonl`, `workload.jsonl`,
fault arm/start/boundary/end/hook receipts, `common-measurement.json`, endpoint
`evaluation.json`, **`raw-result.json`**, and `hashes.json`.
`<trial>-lifecycle/lifecycle.json` records preparation, final pre-reset observations
and verified reset separately from measured behavior. Fixture state and generated
Docker adapter are inside that trial directory. Private credentials, seed and
database backups remain in the existing account-private state directory.

Read `raw-result.json` for application/controller/harness/image identities, native
and operator timestamps, GitHub IDs/jobs/outcomes/counts, delivery, endpoint retention
versus health, deployment events, actual fault boundaries, native probe counts,
retries/reobservations, recovery/rollback and interventions. Actual request counts
are in workload JSONL. No cross-approach score/evaluator is implemented. Common
contract terminal definitions stay unchanged; endpoint facts are separate. `null`
means unknown: for S1, native deployment never starts, so common-contract native
completeness/counters can be unknown; skipped jobs and the fixture receipt are the
direct evidence. Planned backup downtime is distinct from injected-fault onset.

A completed trial requires terminal correlated GitHub work, collected logs/artifacts,
adequate endpoint observation coverage, fault exposure (except S0), valid runtime
hook/timing, and verified v1 reset. Lifecycle `status=completed` means orchestration
finished; check `collection_complete`, `fault_exposure_recorded`, `fixture_valid`
and command exit status too. Exit 0 means those experiment checks passed, **not**
that the deployment succeeded. Exit 2 means incomplete evidence/fixture validation.
Pipeline failure and a healthy v1 final state can be legitimate measured outcomes.
Never count post-trial v1 reset as native rollback or recovery.

Use `--no-interventions` only if you will not manually rescue the measured trial.
Otherwise omit it (unknown until recorded). During an active trial, record any
manual action in another shell before taking it:

```powershell
./experiment/trial.ps1 note --trial S3-001 --action "Manual workflow cancellation requested"
```

Completed, hashed evidence cannot receive notes. Preserve post-trial corrections
as separate records, never edit sealed raw data. In particular, do not edit
`experiment/results/S0-github-validation-20260925-002/` (175 inventoried files).

## Reset and interrupted trials

```powershell
./experiment/trial.ps1 reset
./experiment/run.ps1 verify
```

Reset refuses queued/running deployments, checks ownership and seed checksum,
locks its own state, archives both data volumes, restores the seed and verifies
v1. It never prunes Docker or touches another repository. A normal completed trial
already performs this reset; the commands above are explicit operator recovery.

If interrupted, **do not rerun the same ID**. Keep evidence and backups. The helper
records the interruption and does not automatically reset. Exit the interrupted
operator process so its proxy releases 5542; a dead operator cannot resume a valid
runtime trial. Check the exact run ID in `dispatch.json` using
`gh run view <run-id> --repo id-nynt/memos-current-experiment`.
Wait for termination; if safety requires cancellation, record it with `note` first,
then use `gh run cancel <run-id> --repo id-nynt/memos-current-experiment` and wait.
If dispatch was not correlated, inspect the exact `conventional-<trial>` run title
and HEAD in GitHub before any reset. Do not infer that dispatch failed.

After the run is terminal, recover its logs without dispatching again:

```powershell
./experiment/trial.ps1 collect --trial S3-001
./experiment/trial.ps1 reset
./experiment/run.ps1 verify
```

Recollection creates a new `<trial>-recollection-<id>/`, never fills observation gaps
with invented data. If `dispatch.json` is missing, manual run correlation is required;
`collect` intentionally refuses guessing. If reset reports a busy port, inspect
`Get-NetTCPConnection -LocalPort 5542,5543` and the recorded fixture PID; do not kill
unrelated processes or delete locks/volumes. A failed reset retains its backups;
resolve the reported ownership/seed/Docker problem and run explicit reset again.

## Validation and change record

2026-09-25: added external S3–S5 transport/schedules, enabled existing S1/S2 hooks,
operator lifecycle/recollection/intervention commands, frozen-file guard and raw
result inventory. Only the experiment wrapper workflow is adapted; deployment
policy, upstream CI and successful S0 evidence are unchanged.

Local validation: 27 unit tests passed, Python compilation, actionlint, PowerShell
parse, read-only Compose expansion, and a real read-only PowerShell → adapter →
Docker version call passed. Runner was online/idle and both frozen images verified.
Those checks were setup validation, not live fault validation. Re-run unit checks with:

```powershell
./experiment/.venv/Scripts/python.exe -m unittest discover -s experiment -p 'test_*.py' -v
```

### S3 adapter correction (2026-09-25)

Harness `0da3d2fd0f4b2363254f8b5ef02b029c7822e265` was published and the root-path
variable configured before trials S0-20260925-202920, S1-20260925-205029,
S2-20260925-210717 and S3-20260925-212647. S0–S2 passed lifecycle validation.
S3 run [36129487476](https://github.com/id-nynt/memos-current-experiment/actions/runs/36129487476)
failed at production startup: the frozen controller passed `up --detach --no-build
--pull never memos`, but the external adapter accepted only `-d`. Its rejection
occurred after the production backup stop and before Docker production startup.
Consequently no `fixture-up.json`, t0, synchronization hook or injected responses
were produced. Runtime endpoint coverage could not be established. The verified
v1 reset passed; the invalid trial remains preserved and S4/S5 were not dispatched.

The adapter now accepts both detach spellings and preserves the original arguments.
The regression test extracts the production command from the frozen controller
and checks override insertion and successful hook receipt with mocked Docker.
All 28 unit tests pass, including frozen-file and schedule checks. This is local
validation only; it does not establish live S3 recovery or valid fault timing.

Before another authorized runtime trial, commit and publish the corrected harness,
verify remote `main` equals local HEAD, and run both documented read-only prerequisite
checks. Use a fresh timestamped trial ID. Preserve the invalid S3 evidence as-is;
neither recollection nor this correction can supply its missing runtime observations.
The same adapter serves S4/S5. Controller, application images, schedules, thresholds,
retry budgets and recovery behavior remain frozen.

### S3 runner interruption and live validation (2026-09-25)

Trial `S3-20260925-221852`, run
[36134278423](https://github.com/id-nynt/memos-current-experiment/actions/runs/36134278423),
was invalid: the runner received `UserCancelled` at `2026-09-25T12:30:23Z`, before
the production fault hook. The scheduled task exited with `0xC000013A`, consistent
with console interruption. The operator reported likely closing PowerShell; the
logs do not identify the initiating process. No sleep or reboot event was found
around that time. The task already had unlimited execution time and battery-stop
disabled. Its diagnostic logs were preserved under
`experiment/results/runner-recovery-20260925-225725/` before restarting the existing
hidden `MemosCurrentActionsRunner` task. No controller or runner configuration
change was required.

Keep the runner and trial processes running until evidence collection and reset
finish. Do not close their PowerShell hosts or press Ctrl+C. Before restarting an
offline runner, reconcile any dispatched run and preserve diagnostic logs; never
restart a busy runner. Use the existing scheduled task and verify online/idle
status with the documented prerequisite checks. Do not enable automatic trial
retries to compensate for interruption.

The separately authorized fresh trial `S3-20260925-225819`, run
[36138116562](https://github.com/id-nynt/memos-current-experiment/actions/runs/36138116562),
passed on published harness `b7db614d3d1ed2d425e9275b422760f062b177b4`:
all 16 jobs succeeded, fixture/evidence validation passed, and v2 was delivered
and retained healthy at the 600-second endpoint. Synchronization took 0.056354s;
101 injected responses fell within `[0,60)`, with the expiry receipt at 60.0284425s.
The final pre-cleanup state was healthy v2 in both environments; reset verified
healthy v1 in both. The pre-trial runner restart was disclosed using `trial.ps1 note`;
no manual rescue occurred during measurement. All 185 trial evidence hashes and
the lifecycle hash verified. Earlier evidence remains unchanged. This guide update
is subsequent documentation, not part of that trial's frozen harness identity.
