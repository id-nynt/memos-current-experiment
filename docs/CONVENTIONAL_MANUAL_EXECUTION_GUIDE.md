> Final-matrix execution is gated by [local readiness](../../docs/LOCAL_BATCH_READINESS.md). This native guide is reference material; use the shared batch runbook after publication and parity verification. Historical examples do not override current contracts.

# Conventional Memos: manual experiment guide

Run this guide from the **memos-current repository root**, in Windows PowerShell.
It uses only this repository, GitHub Actions, Docker and the local Python harness.
No BDI checkout, runtime, controller or parent-repository script is required.

These are **new standalone demonstrations**, separate from frozen RQ1 results.
Use `manual-` trial IDs. Do not append them to a study ledger, reuse old IDs or
change historical evidence. This guide describes scenarios, not previous results.
The [operational guide](../experiment/EXPERIMENT_GUIDE.md) remains the experiment
reference; current commands and schedules are defined in the source linked below.

Lifecycle: **prepare -> ONE scenario -> inspect/save evidence -> reset v1 -> next scenario**.
The supported `trial.ps1 run` command saves endpoint and final-state evidence,
then resets automatically. Inspect live in D and inspect saved evidence in E.
There is no pause-before-reset option. Do not interrupt the helper to create one.

Keep an **Operator PowerShell** for execution and an **Observation PowerShell**
for read-only monitoring. Keep Docker, the runner and Operator PowerShell alive
until collection and reset finish. Do not press Ctrl+C in the Operator window.
Run complete code blocks; stop when a command fails. The C sections are alternatives.

## A. One-time setup

### A1. Tools and GitHub

Required: Windows FullLanguage PowerShell, Python 3.11+, Git, tar, GitHub CLI,
Docker Desktop using Linux/amd64, Docker Compose 2.24.4+ and Buildx.
Go, Node, pnpm and buf for the quality jobs are provisioned by GitHub workflows.
The local harness uses Python's standard library.

```powershell
$ErrorActionPreference = 'Stop'
$repo = (Get-Content experiment/config.json -Raw | ConvertFrom-Json).repository
$ExecutionContext.SessionState.LanguageMode
Get-Command git, gh, docker, tar, powershell
py -3 --version
docker version --format '{{.Server.Os}}/{{.Server.Arch}}'
docker compose version
docker buildx version
gh auth status
```

Expect `FullLanguage`, Python 3.11 or later and `linux/amd64`. Install missing
tools through their normal installers. If authentication is missing, run
`gh auth login`. The account needs repository access, Actions dispatch/read/log
download access, and runner administration access during registration. Setting
the repository variable requires variable write access. Do not print tokens.
Enable repository Actions and ensure hosted-job quota and artifact storage exist.

### A2. Runner, frozen images and private seed

Use the dedicated runner `memos-current-windows`, registered to
`id-nynt/memos-current-experiment`, with `self-hosted, Windows, memos-local` labels.
Runner and operator must share the Windows account, Docker engine and filesystem.
Keep that account signed in and prevent sleep.

On a new installation only:

```powershell
./experiment/setup.ps1 -InstallRunner
```

This creates `experiment/.venv`, installs/registers the official runner if needed,
and starts the hidden sign-in task `MemosCurrentActionsRunner`. Its final check can
report missing images. Import an **existing exact frozen bundle**, then check again:

```powershell
$imageBundle = Read-Host 'Full path to the frozen image bundle directory'
./experiment/run.ps1 images import $imageBundle
if ($LASTEXITCODE -ne 0) { throw 'Frozen image import failed' }
./experiment/run.ps1 check
if ($LASTEXITCODE -ne 0) { throw 'Prerequisites failed' }
```

Skip import if both pinned images are already present. To create a transfer bundle
on a machine that has them, use `./experiment/run.ps1 images export <new-directory>`.
Do not rebuild or retag a different image as a substitute. Missing source objects
require fetching the frozen source tags from this project's remote.

Set the path to this **operator checkout**, not the runner's disposable `_work` checkout:

```powershell
gh variable set MEMOS_EXPERIMENT_ROOT --repo $repo --body "$((Get-Location).Path)"
if ($LASTEXITCODE -ne 0) { throw 'Repository variable update failed' }
gh variable get MEMOS_EXPERIMENT_ROOT --repo $repo
```

Only on a genuinely new host with no seed, credentials or experiment volumes:

```powershell
./experiment/run.ps1 init
if ($LASTEXITCODE -ne 0) { throw 'Initialization failed; preserve partial state' }
```

Initialization creates a Memos account, PAT and private sentinel memo, makes a
stopped v1 database seed, then verifies v1 in both environments. Existing hosts
use reset in B, not `init`. Never delete existing state to make initialization pass.
Credentials, seed and database backups stay under
`$env:LOCALAPPDATA/memos-current-experiment`; do not publish that directory.

### A3. Control and application identities

```powershell
git rev-parse HEAD
git status --short
gh api "repos/$repo/commits/main" --jq .sha
Get-Content experiment/frozen-control.json
Get-Content scripts/local-cd/frozen-releases.json
```

Local HEAD and published `main` must match, and tracked files must be clean.
Have any intended harness changes reviewed, committed and published before a run;
this guide does not publish them. Wait for any resulting Local CD run to finish.

| Identity | Source / required value |
| --- | --- |
| Harness / workflow revision | Exact published local HEAD; recorded per trial |
| Frozen controller | `67c4731e67ee1ff0a8cc8d3cbfd7459a23ffe667`; guarded file hashes in `experiment/frozen-control.json` |
| v1 application | `2b5a8be2c2f9cf81599393a227890fb2424a5f03` |
| v2 application | `db695ea0d54cfce6925f07a4715cb42eb6fd8f20` |
| Image / VERSION / source tree | Exact entries in `scripts/local-cd/frozen-releases.json`; VERSION is `local-<full application SHA>` |
| Workflow | `.github/workflows/frozen-cd.yml`, named `Frozen Memos experiment CD` |
| Staging / production | `http://127.0.0.1:5541` / `http://127.0.0.1:5542` |

The app pair includes a visible release header change; it does not change database
schema or backend behavior. Ordinary `local-cd.yml` builds from main and normally
uses 5231/5232. `demo-deploy.yml` triggers Render. Neither is this experiment entry point.

## B. Prepare each experiment

### B1. Select one scenario and check readiness

In Operator PowerShell, select **one** name from C. Use S4 for the persistent-fault
demonstration. S4R/S5R are implemented but marked prepared in their contract;
they require a separately approved live demonstration and a published matching
harness. Their names do not make this run a frozen RQ1 trial.

```powershell
$ErrorActionPreference = 'Stop'
$scenario = 'S4'
$repo = (Get-Content experiment/config.json -Raw | ConvertFrom-Json).repository
$state = Join-Path $env:LOCALAPPDATA 'memos-current-experiment'
$releases = (Get-Content scripts/local-cd/frozen-releases.json -Raw | ConvertFrom-Json).releases
./experiment/run.ps1 check
if ($LASTEXITCODE -ne 0) { throw 'Prerequisites failed' }
./experiment/trial.ps1 check --scenario $scenario
if ($LASTEXITCODE -ne 0) { throw 'Trial readiness failed' }
```

These checks do not dispatch or deploy. They check frozen files/images/source,
published HEAD, clean tracked files, no pending conventional deployment and an
online idle runner. Runtime scenarios also check `MEMOS_EXPERIMENT_ROOT` and
Compose's 5543 override. They do not establish seed integrity or live v1 health;
do B2 as well. Do not run these locked helper checks during an active trial.

### B2. Restore and verify healthy v1

No other experiment or deployment may be active. Reset archives the current
experiment data, restores the private seed and verifies both environments.

```powershell
./experiment/trial.ps1 reset
if ($LASTEXITCODE -ne 0) { throw 'Reset failed; stop here' }
$verifiedText = & ./experiment/run.ps1 verify
if ($LASTEXITCODE -ne 0) { throw 'Live verification failed' }
$verified = ($verifiedText -join "`n") | ConvertFrom-Json
foreach ($environment in @('staging', 'production')) {
    $observation = $verified.$environment
    if (-not $observation.healthy -or
        $observation.application_sha -ne $releases.v1.application_sha -or
        $observation.image_id -ne $releases.v1.image_id) {
        throw "Healthy pinned v1 required in $environment"
    }
}
$seed = Get-Content (Join-Path $state 'seed/manifest.json') -Raw | ConvertFrom-Json
$seedHash = (Get-FileHash (Join-Path $state 'seed/data.tar.gz') -Algorithm SHA256).Hash
if ($seed.owner -ne 'memos-current-experiment' -or $seedHash -ne $seed.archive_sha256) {
    throw 'Seed identity/checksum failed'
}
$verified | ConvertTo-Json -Depth 10
```

`verify` tests the live image, release identity, instance URL, health and
authenticated sentinel in staging and production. By itself it accepts either
pinned healthy release; the extra comparisons above require v1. A stale accepted
receipt or a green `/healthz` alone is insufficient.

### B3. Create a new ID and operator folder

```powershell
$trial = 'manual-' + $scenario + '-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8)
$evidence = Join-Path (Get-Location).Path "experiment/results/$trial"
$lifecycle = "$evidence-lifecycle"
$operator = "$evidence-operator"
foreach ($path in @($evidence, $lifecycle, $operator)) {
    if (Test-Path -LiteralPath $path) { throw 'ID collision; generate a new ID' }
}
New-Item -ItemType Directory -Path $operator | Out-Null
@{
    scope = 'standalone manual demonstration; excluded from frozen RQ1 results'
    trial_id = $trial
    scenario = $scenario
    evidence = $evidence
    lifecycle = $lifecycle
    prepared_at = [DateTime]::UtcNow.ToString('o')
    preparation = 'Explicit seed reset and healthy v1 verification in B2'
    baseline = (Get-Content (Join-Path $state 'baseline.json') -Raw | ConvertFrom-Json)
} | ConvertTo-Json -Depth 20 | Set-Content (Join-Path $operator 'selection.json') -Encoding UTF8
Write-Host "Trial: $trial"
Write-Host "Operator folder: $operator"
```

The helper creates the trial and lifecycle folders in C. Do not pre-create them:
existing folders are rejected to protect evidence. Keep the printed operator path
for D/E. Record any additional preparation actions in a new file there.

## C. Run ONE scenario

After B, run this block **once**, with the selected `$scenario`:

```powershell
./experiment/trial.ps1 run --scenario $scenario --trial $trial --no-interventions
$trialExit = $LASTEXITCODE
Write-Host "Trial helper exit: $trialExit"
```

This is the exact common execution command for every row below. It prepares v1
again under its lifecycle record, arms the selected fixture, dispatches one v2
workflow, observes, collects and resets. Do not also click **Run workflow** or
dispatch with `gh workflow run`: runtime faults need the active local helper.
`--no-interventions` declares no manual rescue; omit it if rescue is planned.
Always record an actual intervention with D4, even if it was unexpected.

| Choice in B1 | Purpose and injection | Application effect / pipeline observation | Expected workflow behavior | Fault ends |
| --- | --- | --- | --- | --- |
| `$scenario = 'S0'` | Healthy control; no fault | v2 passes identity, health, sentinel and frontend checks | Quality gates, staging and production succeed if prerequisites hold | No fault |
| `$scenario = 'S1'` | CI rejection; fixture exits 42 after real backend/frontend/proto jobs pass | No candidate deployment; both environments stay v1 | Fixture job fails; upgrade and deploy are skipped | One CI gate invocation; no runtime fault |
| `$scenario = 'S2'` | Deployment adapter failure after upgrade smoke, just before the first staging Docker mutation | Native `deterministic_failure`; both environments stay v1 | Deploy job fails before staging replacement | One thrown exception; no runtime fault |
| `$scenario = 'S3'` | Temporary production fault; memo HTTP 503 during `[0,60)` seconds | Production sentinel fails, then succeeds; staging unaffected | Existing verification rechecks can accept v2 after 60s | At t0+60, by clock |
| `$scenario = 'S4'` | **Persistent production fault**; memo HTTP 503 during `[0,900)` | Sentinel remains bad beyond the native deadline and at the 600s endpoint | Production verification fails; no automatic rollback; v2 may remain running but unusable for memos | At t0+900, independently of workflow outcome |
| `$scenario = 'S5'` | Changing health; 503 during `[0,60)` and `[120,240)` | First recovery can let verification finish; later memo requests fail again | Can succeed before recurrence; there is no native monitoring/reconsideration after termination | First interval ends at 60s; recurrence ends at 240s |
| `$scenario = 'S4R'` | Revised persistent case; same `[0,900)` fault | Same memo failure as S4; adds revised evidence/coverage rules | Same conventional deadline and lack of automatic rollback | At t0+900 |
| `$scenario = 'S5R'` | Revised recurrence; 503 during `[0,60)` and `[70,190)` | Only a 10s healthy gap; native verification may finish before recurrence or still encounter it | Outcome depends on actual probe timing; do not claim reconsideration from external samples | First interval ends at 60s; recurrence ends at 190s |

These are expectations, not acceptance criteria for a desired winner. An earlier
unrelated CI failure means the intended later fault was not reached. S1 is an extra
deterministic gate, not a broken application test or a transient automatic retry.

### Runtime fault timing: S3, S4, S5, S4R and S5R

The operator injects the fault by selecting the scenario and launching the helper.
There is no separate supported manual on/off command. Do not pause containers,
edit schedules or clear a fault early to imitate another controller's behavior.

The adapter moves only the candidate production host binding to `127.0.0.1:5543`.
A proxy keeps the public production URL on 5542. Staging remains on 5541.
It returns 503 for every method on `/api/v1/memos` and its subpaths only when the
backend identifies as v2. Profile, `/healthz`, frontend and v1 are unaffected by
the injected rule. Users may see the V2 header while memo operations fail.

**t0** is the first independent successful candidate identity, health and
authenticated-sentinel observation after production starts, before the adapter
returns to native verification. Setup has a 180s cap; the recorded release of the
native hook must be within 2s of readiness. Missing/late synchronization invalidates
the fixture. Timing uses a monotonic clock, never a controller decision.

The conventional controller receives its ordinary S0 input for runtime faults;
the outer manifest records the real scenario. Its sequence remains: real quality
jobs -> CI fixture -> upgrade/build smoke -> frozen-image staging verification ->
stopped production backup -> same-image production verification -> accepted receipt.
Backup downtime before t0 is separate from injected memo failures.

Verification has a 180s deadline per environment, a 3s delay between failed rounds
and 5s HTTP timeouts. One successful full round returns immediately. These are
bounded verification rechecks, not a job/deployment retry or adaptive recovery.
Failure leaves diagnostics and backup information; there is no automatic rollback.

Runtime observation covers t0+600 and remote termination. S4/S4R also wait for
900s expiry before cleanup. S0-S2 observe for 600s after resolved workflow completion.
Allow CI time **plus** this follow-up; a green/red Actions run is not helper completion.
S4R/S5R use only local `experiment/paired_rq1.py` and `rq1-s4r-s5r.json`; they add no
BDI dependency or longer controller lifetime.

## D. Live observation

### D1. Load this trial in Observation PowerShell

Run from the same repository root. Enter the operator path printed in B3.

```powershell
$operator = (Read-Host 'Full operator folder path from B3').Trim().Trim('"')
$selection = Get-Content (Join-Path $operator 'selection.json') -Raw | ConvertFrom-Json
$trial = $selection.trial_id
$evidence = $selection.evidence
$lifecycle = $selection.lifecycle
$repo = (Get-Content experiment/config.json -Raw | ConvertFrom-Json).repository
```

After `dispatch.json` appears, correlate the exact run and open its jobs:

```powershell
$dispatch = Get-Content (Join-Path $evidence 'dispatch.json') -Raw | ConvertFrom-Json
$runId = $dispatch.github_run_id
gh run view $runId --repo $repo --json databaseId,displayTitle,headSha,status,conclusion,jobs,url
gh run view $runId --repo $repo --web
```

Confirm title `conventional-<trial ID>` and `headSha == dispatch.control_sha`.
In the browser, expand the deploy job's **Deliver frozen image through conventional
stages** step. For a terminal view, use `gh run watch $runId --repo $repo --interval 5`.
Watch the selected ID, never the latest run. If dispatch metadata is missing, use H.

### D2. Deployment, identity and health

Repeat these read-only snapshots as needed:

```powershell
docker ps --filter 'label=com.docker.compose.project=memos-current-experiment-staging'
docker ps --filter 'label=com.docker.compose.project=memos-current-experiment-production'
docker inspect memos-current-experiment-production-memos-1 --format '{{.Image}} {{.State.Status}} {{.RestartCount}}'
foreach ($port in @(5541, 5542)) {
    try {
        Invoke-RestMethod "http://127.0.0.1:$port/api/v1/instance/profile" -TimeoutSec 5
        Invoke-RestMethod "http://127.0.0.1:$port/healthz" -TimeoutSec 5
    } catch { Write-Host "Port $port unavailable: $($_.Exception.Message)" }
}
Get-Content (Join-Path $evidence 'common-observations.jsonl') -Tail 5
Get-Content (Join-Path $evidence 'workload.jsonl') -Tail 5
```

Open staging/production in a browser to see the app. Do not write test memos during
the measured run. The harness already sends authenticated sentinel reads every
1s without overlap (3s timeout), and health samples 2s after each prior completion.
`healthy` includes sentinel access. A 200 from `/healthz` alone does not mean the
memo path works. External observations never drive conventional decisions.

For native progress after the deploy job starts, find its exact private release
record. Repeat this block if the record has not appeared yet:

```powershell
$releaseRoot = Join-Path $env:LOCALAPPDATA 'memos-current-experiment/releases'
$nativeMatches = @(foreach ($folder in Get-ChildItem -LiteralPath $releaseRoot -Directory) {
    $recordPath = Join-Path $folder.FullName 'release.json'
    if (Test-Path -LiteralPath $recordPath) {
        $record = Get-Content -LiteralPath $recordPath -Raw | ConvertFrom-Json
        if ($record.trial_id -eq $trial -and $record.workflowRun -eq "$runId") {
            $folder.FullName
        }
    }
})
if ($nativeMatches.Count -gt 1) { throw 'Multiple native attempts; inspect each separately' }
if ($nativeMatches.Count -eq 1) {
    $native = $nativeMatches[0]
    Get-Content (Join-Path $native 'native-events.jsonl') -Tail 15
    Get-Content (Join-Path $native 'release.json')
}
```

`health_observation` records native probe rounds; `deployment_start/end` records
container deployment boundaries, not acceptance. No matching record exists before
deploy or for S1. Later, collected copies appear in the trial folder. A native
probe event marks a round starting; correlate logs/workload before claiming it
received a particular fault response.

### D3. Injected fault and recurrence

For runtime cases, inspect files as they appear:

```powershell
Get-ChildItem -LiteralPath $evidence -Filter 'fixture-*.json'
Get-Content (Join-Path $evidence 'fault-events.jsonl') -Tail 12
foreach ($name in @('fixture-start.json', 'fixture-hook.json', 'fixture-expired.json', 'fixture-error.json')) {
    $path = Join-Path $evidence $name
    if (Test-Path -LiteralPath $path) { Get-Content -LiteralPath $path }
}
```

`fixture-arm` means waiting, not injected exposure. Look for `fault_started`,
`injected_response`, timed `fault_boundary` events and `fault_ended`.
Use `workload.jsonl` to see received HTTP statuses. S4R/S5R also record
`response_delivered`; this alone does not identify the native verifier as the client.
Any `fixture-error.json` needs investigation. For S1, inspect the fixture job and
its artifact; for S2, inspect native `deterministic_failure`.

### D4. Record manual interventions

Before cancellation, restart, manual repair or another state-changing intervention:

```powershell
$action = Read-Host 'Describe the manual action and reason'
./experiment/trial.ps1 note --trial $trial --action $action
if ($LASTEXITCODE -ne 0) { throw 'Note was not recorded; inspect trial state' }
```

Notes require an existing manifest and unsealed evidence. Record preparation or
post-seal actions in a new timestamped operator-side file instead; never edit hashed
evidence. Read-only observation needs no rescue note. Routine harness preparation,
fault timing and reset are recorded automatically.

## E. Evidence

### E1. Files saved by the helper

Paths below are relative to `experiment/results/<trial>/` unless stated otherwise.

| Fact | Saved evidence |
| --- | --- |
| Experiment ID and standalone scope | `manifest.json`; sibling `<trial>-operator/selection.json` |
| Harness, controller, application and image identities | `manifest.json`, `raw-result.json`, `release.json` when deploy starts |
| Scenario and fault schedule | Manifest; runtime `fixture-arm.json`, `fixture-start.json`, `fixture-hook.json`; revised `paired-contract.json` |
| GitHub run/job IDs and outcomes | `dispatch.json`, `github/run.json`, `github/jobs-all-attempts.json` |
| Full logs and artifacts | `github/raw-logs.zip`, `github/raw-logs/`, `github/logs.txt`, `github/artifacts/` |
| Runtime health and request results | `common-observations.jsonl`, `workload.jsonl` |
| Fault events | Runtime `fault-events.jsonl`; S1 artifact under `github/artifacts/fixture-<trial>/`; S2 `native-events.jsonl` |
| Deployment/verification result | `native-events.jsonl`, `release.json`, `launch.json`, `common-measurement.json`, `raw-result.json` |
| Endpoint state | `evaluation.json`, `raw-result.json` endpoint fields; revised `active-opportunity.json` |
| Final state before fixture cleanup | Runtime `final-state-before-cleanup.json`; lifecycle `pre_reset_observations` |
| Interventions | `interventions/*.json`, `human-interventions.json`; separate operator notes outside sealed evidence |
| Preparation and verified reset | Sibling `<trial>-lifecycle/lifecycle.json`; private `resets/` backups/receipts |
| Evidence integrity | `hashes.json` in trial and lifecycle folders |

S1 has no native deployment record because deploy is skipped. Missing native
counters can therefore be null. Null means unknown, not zero. The endpoint is
t0+600 for runtime cases. Terminal health, endpoint health and the later pre-cleanup
state are different facts: S4 can be unhealthy at the endpoint and healthy after
900s expiry. That later recovery is caused by scheduled fault removal.

`candidate_retained` means the endpoint identity still matches v2; it does not
mean healthy or accepted. `candidate_delivered` uses common terminal semantics;
also inspect `endpoint.candidate_delivered_at_endpoint`. The final v1 reset is
operator cleanup, never native recovery.

### E2. Inspect after the helper returns

Load D1 first if using a new terminal. This inspection does not launch anything:

```powershell
$raw = Get-Content (Join-Path $evidence 'raw-result.json') -Raw | ConvertFrom-Json
$life = Get-Content (Join-Path $lifecycle 'lifecycle.json') -Raw | ConvertFrom-Json
$run = Get-Content (Join-Path $evidence 'github/run.json') -Raw | ConvertFrom-Json
$raw | Select-Object scenario, trial_id, frozen_controller, evidence_complete, fixture_valid,
    candidate_delivered, candidate_retained, final_health, retry_count, reobservation_count
$raw.endpoint | Format-List
$life | Select-Object status, collection_complete, fault_exposure_recorded, fixture_valid
$life.pre_reset_observations | ConvertTo-Json -Depth 10
$life.reset | ConvertTo-Json -Depth 10
$run | Select-Object databaseId, headSha, status, conclusion, url
Get-Content (Join-Path $evidence 'github/jobs-all-attempts.json') -Raw |
    ConvertFrom-Json | Select-Object id, name, status, conclusion, started_at, completed_at
```

Before another scenario, confirm:

1. Exact title/SHA/run and application/image identities match the manifest and pins.
2. GitHub is terminal; raw log ZIP, extracted logs and expected artifacts exist;
   there is no `github/collection-warning.json`.
3. Intended fault was reached (except S0), timing/endpoint coverage are valid,
   and runtime `fixture_valid` is true. It is null for non-runtime fixtures.
4. `raw-result.json` and lifecycle fields are consistent. Investigate false or
   unexplained null completeness fields; S1's absent native deployment is expected.
5. Pre-cleanup facts were saved and lifecycle reset verifies pinned healthy v1
   in both environments. `status=completed` alone is insufficient.

Verify both inventories, without updating them:

```powershell
foreach ($folder in @($evidence, $lifecycle)) {
    $inventory = Get-Content (Join-Path $folder 'hashes.json') -Raw | ConvertFrom-Json
    foreach ($entry in $inventory.PSObject.Properties) {
        $file = Join-Path $folder $entry.Name
        if (-not (Test-Path -LiteralPath $file)) { throw "Missing evidence: $file" }
        $actual = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash
        if ($actual -ne $entry.Value) { throw "Evidence hash mismatch: $file" }
    }
    Write-Host "Hashes verified: $folder"
}
```

Helper exit 0 means its lifecycle checks passed, even for an expected failed
pipeline. Exit 2 means incomplete evidence/fixture validation. Other errors or
interruptions need H. Do not automatically rerun a failed or incomplete scenario.

Keep all three sibling directories together. They are Git-ignored, so Git is not
a backup. Optional: archive them to a new path without changing their contents:

```powershell
$archive = Join-Path (Split-Path $evidence -Parent) "$trial-evidence.zip"
if (Test-Path -LiteralPath $archive) { throw 'Archive already exists' }
Compress-Archive -LiteralPath @($evidence, $lifecycle, $operator) -DestinationPath $archive
Get-FileHash -LiteralPath $archive -Algorithm SHA256
```

Review logs before sharing. Never bundle the private credentials, seed or databases.
Preserve all historical results, including `S0-github-validation-20260925-002`.

## F. Reset

A normally completed helper already saved measured evidence and reset both
environments to healthy v1. Read its reset receipt and run B2's live verification
checks without the first reset command; no duplicate reset is needed.

If cleanup did not complete, first reconcile remote work and save/recollect its
evidence using H. Only after it is terminal and the old operator/fixture is stopped:

```powershell
./experiment/trial.ps1 reset
if ($LASTEXITCODE -ne 0) { throw 'Reset failed; do not run another scenario' }
./experiment/run.ps1 verify
if ($LASTEXITCODE -ne 0) { throw 'Post-reset verification failed' }
```

Check the exact v1 SHA/image as in B2. Reset verifies seed checksum and ownership,
locks its state, archives both data volumes, restores the seed, then deploys and
verifies v1. It refuses outstanding remote deployments. Failed resets retain backups.
Never prune Docker, delete locks or remove volumes to bypass a failure.
For the next scenario, return to B and generate a fresh ID.

## G. Professor demonstration

Use **S4** for the main demonstration. It shows the same class of persistent
production request failure as the archived manual, now on Memos memo requests.
This is not a payment-service demonstration or a claim of equivalent measurements.

1. Complete A once, then B with `$scenario = 'S4'`. Show healthy v1 in both environments.
2. Run C once. Show real quality jobs, staging v2 and same-image production promotion.
3. In D, show production's v2 identity and green `/healthz`, alongside repeated memo
   503s and `healthy=false`. The visible header alone does not prove delivery.
4. Show native probe rounds and the failed verification job after its fixed budget.
   Explain: "The pipeline rechecks its declared conditions, then fails. It does
   not select a repair or automatically roll back."
5. Keep the helper running. At t0+600 show the unhealthy endpoint; at 900s the
   fixture expires by schedule. This is not conventional recovery. The helper
   then saves the final state and restores v1 outside the measured pipeline.
6. Use E to show run URL, identities, fault receipts, raw logs, outcome and verified reset.

For a later comparison using the **same Memos pair and fault**, use the independently
prepared counterpart's evidence. Explain its actual recorded control decisions;
this guide neither runs nor assumes a BDI recovery. Do not infer comparative scores.
Optionally demonstrate S3 or S5R in a separate new lifecycle to show bounded
rechecks or recurrence. S5R's `active-opportunity.json` distinguishes termination
before recurrence from retained native probes; passive monitoring alone does not
prove the controller observed or reconsidered changed health.

## H. Troubleshooting

| Problem | Action |
| --- | --- |
| Runner offline | Inspect `Get-ScheduledTaskInfo -TaskName MemosCurrentActionsRunner` and `%USERPROFILE%/actions-runner-memos-current/_diag/`. Preserve diagnostics. Reconcile existing work first; then start the existing task with `Start-ScheduledTask -TaskName MemosCurrentActionsRunner`. Never restart a busy runner. |
| Runner stopped after closing PowerShell | A closed host/Ctrl+C can stop the runner or local fixture. Preserve logs and follow reconciliation below. Use the hidden task; keep the operator alive until reset finishes. |
| Docker unavailable / wrong engine | Start Docker Desktop in Linux mode for the shared account. Check `docker version`. If exact frozen images are missing, use A2's bundle import. |
| gh 401/403 or PAT/sentinel errors | Check `gh auth status` and repository permissions. GitHub credentials and the private Memos PAT are separate. Preserve private state; do not print credentials or replace the seed during a trial. |
| Hosted quota / billing / artifact limit | Inspect the exact run's failure and repository Actions/billing settings. Restore capacity before a new authorized run. Do not weaken quality gates or treat quota failure as prescribed fault exposure. |
| Published HEAD / frozen hash mismatch | Review local changes and the configured remote. Publish only reviewed intended changes through the normal process. Do not edit frozen hashes to bypass a guard. |
| Readiness reports pending work | Inspect both `frozen-cd.yml` and `local-cd.yml`. A main push can queue Local CD. Wait/reconcile the exact run; do not launch another trial. |
| Port 5542/5543 busy, stale lease or lock | Inspect `Get-NetTCPConnection -LocalPort 5542,5543` and `fixture-arm.json`'s PID. Identify the owner before stopping anything. Never kill an unrelated process or delete a lock file to force entry. |
| v2 already deployed / baseline consumed | Finish evidence collection and reset to verified v1 before a new scenario. Do not edit `baseline.json` or `accepted.json`. |
| Fault not reached / fixture invalid | Check earlier jobs, `fixture-up/start/hook/error` receipts and timing. Preserve the attempt; missing exposure is not a valid fault result. |
| Reset failed | Preserve private `resets/` receipts/backups. Resolve the reported ownership, seed, port or Docker cause; then perform explicit F reset and verify v1. |
| Incomplete logs or observations | Recollect the original terminal run below. Recollection cannot reconstruct lost runtime samples. Keep the original invalid/incomplete status and evidence. |

### Reconcile an interruption or uncertain remote job

Do not repeat C or reuse its ID. Closing the operator does not prove GitHub stopped.
Load D1, then read the original dispatch and status:

```powershell
$dispatch = Get-Content (Join-Path $evidence 'dispatch.json') -Raw | ConvertFrom-Json
$runId = $dispatch.github_run_id
gh run view $runId --repo $repo --json databaseId,displayTitle,headSha,status,conclusion,jobs,url
```

If `dispatch.json` is absent, find the exact title and manifest's harness SHA:

```powershell
$manifest = Get-Content (Join-Path $evidence 'manifest.json') -Raw | ConvertFrom-Json
$runs = gh run list --repo $repo --workflow frozen-cd.yml --event workflow_dispatch --limit 100 --json databaseId,displayTitle,headSha,status,conclusion,url | ConvertFrom-Json
$runs | Where-Object { $_.displayTitle -eq "conventional-$trial" -and $_.headSha -eq $manifest.identity.control_sha }
```

If no unique match appears, inspect older runs in GitHub; absence from this limited
list does not prove dispatch failed. Do not fabricate `dispatch.json`. Missing
dispatch metadata needs manual correlation and separate evidence retention; the
collect helper deliberately refuses to guess.

Wait for the exact run to terminate. If cancellation is necessary, record D4
first (or a separate operator note if evidence is sealed), then:

```powershell
gh run cancel $runId --repo $repo
gh run watch $runId --repo $repo --interval 5
```

After terminal status, and once the original operator process has ended:

```powershell
./experiment/trial.ps1 collect --trial $trial
if ($LASTEXITCODE -ne 0) { throw 'Recollection failed; preserve evidence and diagnose' }
```

This writes a new `<trial>-recollection-<id>/` with original-run logs/artifacts.
It does not redispatch, resume the clock, replace hashes or fill observation gaps.
Then follow F. A dead runtime fixture cannot resume a valid trial. Any later fresh
trial needs a new ID and its own authorization; it never replaces the old evidence.

### Source map and verification scope

Commands and behavior were checked against these repository files:

- [Workflow](../.github/workflows/frozen-cd.yml) and its backend/frontend/proto/upgrade reusable workflows.
- [Native deployment](../scripts/local-cd/deploy.ps1), [Compose](../scripts/local-cd/compose.yaml) and [release pins](../scripts/local-cd/frozen-releases.json).
- [Setup](../experiment/setup.ps1), [lifecycle CLI](../experiment/trial.py) and [execution/collection CLI](../experiment/manage.py).
- [CI fixture](../experiment/fixture.py), [runtime fixture](../experiment/runtime_fixture.py), [scenario list](../experiment/scenarios.json) and [revised contract](../experiment/rq1-s4r-s5r.json).
- [Passive measurements](../scripts/experiment-measurement/measure_trial.py) and [revised evidence rules](../experiment/paired_rq1.py).

The archived manual was used only for step-by-step presentation style. This guide
does not establish current machine readiness or a successful live trial; run the
readiness checks when preparing an authorized demonstration.
