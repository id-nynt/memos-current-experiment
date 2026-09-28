# BDI agent experiments: complete manual

This is the single operational guide for BDI setup, baseline, runtime preparation, scenarios, evidence and reset. Use the same root payment app and immutable v1/v2 pair as the conventional approach. BDI/Jason chooses execution and recovery; GitHub Actions executes the selected jobs. Do not additionally click **Run workflow** for a BDI trial.

## Where to start

| Your situation | Read and follow |
|---|---|
| New computer / first experiment | **A1-A4**, then **F1** to establish the pair baseline, then **B1-B3** |
| Tools ready, but you need a new v1/v2 pair after an app change | **A4**, then **F1**, then **B1-B3** |
| Existing pair and baseline, updating the agent/control revision | **A3 validation**, **A4.4** once, then **B1-B3**; app commits remain unchanged |
| Existing pair and successful v1 baseline already saved, control revision unchanged | **B1-B3**; skip A and F1 |
| Both environments just passed B3/E reset in this session | Choose **one** scenario in **C** |
| A scenario just finished | **D** save/inspect evidence, then **E** reset to v1 |
| A terminal was reopened | **B2** reloads settings; **D** can independently reload the saved trial path |
| Interrupted execution / uncertain remote job | **F3** before any new deployment |

The repeatable cycle is **B -> one C scenario -> D -> E -> one C scenario**. The C subsections are alternatives, not successive tasks. Do not run every C section after one another without finalising and resetting.

**Manual fault injection:** use **C3** to choose a controlled job failure, **C4** to start and stop production request errors yourself, or **C5** to keep request errors active until rollback. C4 also offers a manual rollback-reconsideration variant. These sections are alternatives: after one run, complete **D then E**. C1/C2 remain available for scripted timing.

**Keep manual demonstrations separate from the paired study in guide 07.** Complete any active guide-07 trial and its recording/reset first. This guide uses `current-bdi-trial.json`, not `current-compact-study.txt`. Manual fault timing, request rate and operator intervention differ from the seeded paired protocol; do not append these runs to that study or claim they are equivalent repetitions. No manual fault should target a deployment controlled by another active experiment.

**Copy/paste:** copy only an entire code block, without `PS ...>`, `>>`, or error text. Run one block, read its output, then proceed. A `>>` prompt means PowerShell is still accepting a multiline command; if you pasted the wrong block, cancel that incomplete input with Ctrl+C before pasting again. Do not use Ctrl+C in the Controller window while a campaign is running.

**Terminals:** keep Controller PowerShell for BDI commands, Traffic PowerShell only when a scenario requests it, and Observation PowerShell only for manual timing. Keep Docker Desktop and the existing Linux runner open. Commands assume `C:\NHI\2026_IT-Project\260031_payment-repair`. Values that you must choose appear in a separate short **Manual selection** block; run the following execution block unchanged. Paste complete `. { ... }` blocks: they stop on an error and retain variables in the current terminal.

| Local selection file | Meaning |
|---|---|
| `experiments/results/release-pairs/current-pair.txt` | One-line pair JSON path; automatically read and trimmed, no placeholder |
| `experiments/results/current-bdi-trial.json` | Last selected candidate trial and its scenario; survives terminal restarts |
| `experiments/results/current-bdi-reset.txt` | Reset evidence path, separate from candidate results |
| `experiments/results/current-bdi-baseline.txt` | First-baseline evidence path |

These selection files and experiment folders are Git-ignored. Back them up together. Completed run folders are never overwritten. Never run two experiments concurrently against the same deployment environments.

<a id="part-a---setup-and-separate-system-checks"></a>
<a id="appendix-a-one-time-setup"></a>
## A. One-time setup

### A1. Check tools and connect GitHub

**Open:** install Git, GitHub CLI, Python 3.12, JDK 21+, Node 22 and Docker Desktop with WSL integration if missing. Use their normal installers.

**Start:** open Docker Desktop; wait for the engine. Open Controller PowerShell. Keep the existing repository and worktree; do not run `git init` or create another repository.

**Actions:** run:

```powershell
. {
    $ErrorActionPreference = 'Stop'
    Set-Location C:\NHI\2026_IT-Project\260031_payment-repair
    git status --short --branch
    git remote -v
    py -3 --version
    java -version
    node --version
    gh --version
    docker info
    docker compose version
    py -3 -m pip install PyYAML==6.0.3
    npm ci
    Remove-Item Env:GH_TOKEN,Env:GITHUB_TOKEN -ErrorAction SilentlyContinue
    gh auth login --hostname github.com --git-protocol https --web --scopes workflow
    gh auth setup-git
}
```

**Explanation:**

- `Set-Location` selects the repaired checkout.
- `git status` shows the branch and pending edits; `git remote` shows the target repository.
- Version commands check Python, JDK 21+, Node 22+ and GitHub CLI.
- Docker commands check the running engine and Compose.
- `pip install` installs the YAML dependency; `npm ci` installs app/traffic dependencies.
- `Remove-Item` clears token overrides in this window; silent output is normal.
- `gh auth login` opens browser authentication; sign in as an account with repository write access.
- `gh auth setup-git` makes Git use the stored CLI credentials.

**Expected results:**

- Browser confirms device connection; CLI completes login.
- Remote is `https://github.com/id-nynt/260031_cicd_payment_demo.git`.
- All tool checks respond without errors.

**Cleanup:** none. Stored login persists; environment variables do not. Never put a token in a file or screenshot.

**Runner and repository setup (once):** in GitHub, open this repository's **Settings > Actions > Runners > New self-hosted runner**, select Linux, and follow the displayed download/configuration commands in WSL Ubuntu. Use the existing runner if one is already registered; do not register another. Its labels must include `self-hosted`, `linux`, and `payment-deploy`; the runner account must be able to run `docker info` and `docker compose version`. Under **Settings > Environments**, configure `staging` and `production` and record any approval requirements. Publish/register the reviewed workflows on the default branch before manual dispatch. GitHub installation workflows remain in `.github/workflows/`.

### A2. Check the app separately on port 3002

**Start:** open a separate Local-check PowerShell. This is a rehearsal, not the deployed v1/v2 stacks.

**Actions:** run:

```powershell
. {
    $ErrorActionPreference = 'Stop'
    Set-Location C:\NHI\2026_IT-Project\260031_payment-repair
    $env:COMPOSE_PROJECT_NAME = 'payment-local'
    $env:APP_PORT = '3002'
    $env:POSTGRES_PORT = '5434'
    $env:METRICS_PORT = '9466'
    $env:PROMETHEUS_PORT = '9092'
    $env:CI_RUN_ID = 'local'
    $env:EXPERIMENT_MODE = 'normal'
    docker compose up -d --build
    docker compose ps
    Invoke-RestMethod http://localhost:3002/ready
    $env:PAYMENT_BASE_URL = 'http://localhost:3002'
    npm run traffic:experiment -- normal 6
}
```

**Explanation:**

- `Set-Location` selects the app source.
- Each environment assignment selects the isolated rehearsal stack, its ports, identity or normal behavior.
- `compose up` builds and starts it; `compose ps` lists its services.
- `Invoke-RestMethod` checks readiness.
- `PAYMENT_BASE_URL` directs traffic to the rehearsal app; `npm run` sends normal fake payments.

**Expected results:**

- Traffic prints successful HTTP 201 responses.
- Browser: open `http://localhost:3002/checkout`; choose **Demo card simulation**, use `4242424242424242`, expiry `12/30`, CVC `123`, and see a receipt.
- Browser: Prometheus at `http://localhost:9092` shows `payment_service_ready{ci_run_id="local"}` equal to `1` after samples arrive.

**Cleanup:** in this same window run `docker compose stop`, then close it. Keep Docker running. Ports 3000/3001 are separate deployment stacks, started or restored in B3.

### A3. Validate the configuration and rehearse the BDI agent

**Start:** Controller PowerShell. Keep normal staging/production success goals for C. All paths below are inside `bdi-cicd-framework/`.

| Source file | Review or change here |
|---|---|
| `models/01_pipeline.yaml` | Jobs, dependencies, worker job names, environments, recovery relationship, candidate repair capabilities and `max_retries` |
| `models/02_goal.yaml` | Achievement, maintenance and avoidance goals |
| `config/controller_policy.yaml` | Retry-safe entities, observation/reconciliation budgets, restart/verification limits, recovery rules and thresholds |
| `config/runtime_bindings.yaml` | Readiness/Prometheus URLs, correlated queries, freshness and diagnostic Docker project/services |

**Actions 1 - generation, only when needed:** the migration already generated the current artifacts. Skip this block if you have not changed any source or generator and validation below passes; run it for a new configuration revision or after reviewing a stale-artifact error. Do not copy relocated settings back into 01/02, edit generated 03/ASL, or delete the manifest.

```powershell
. {
    $ErrorActionPreference = 'Stop'
    py -3 -B bdi-cicd-framework/generate_project.py
    if ($LASTEXITCODE -ne 0) { throw 'Generation failed; inspect the input error' }
}
```

**Actions 2 - always validate, then rehearse:** run:

```powershell
. {
    $ErrorActionPreference = 'Stop'
    py -3 -B bdi-cicd-framework/run_controller.py --validate-only
    if ($LASTEXITCODE -ne 0) { throw 'Artifact validation failed' }
    py -3 -B bdi-cicd-framework/run_controller.py --gui --scenario healthy
}
```

**Explanation:**

- `generate_project.py` validates all four sources, saves/reloads 03, and generates the agent solely from that saved contract; the manifest records source/generator hashes.
- Each `if` stops the block if the preceding check failed.
- `--validate-only` verifies their consistency without dispatching.
- `--scenario healthy` runs Jason with simulated execution and telemetry.

**Expected results:**

- Validation prints `Project artifacts are consistent`; a missing/stale profile stops startup with an explicit regeneration instruction.
- Persistent outputs: `models/03_workflow_model.yaml`, `models/generation-manifest.json`, `bdi/controller_agent.asl`.
- Normal execution limits remain: one retry for eligible retryable failures, at most 36 observations at five-second intervals within 180 seconds, and two consecutive healthy observations. Candidate repair adds one production restart, a 120-second probe window and a 300-second decision budget starting at diagnosis. These are explicit configuration values.
- MAS Console's `controller_agent` log reaches `BDI_CONTROLLER_RESULT=achieved recovery=not_needed`.
- No real GitHub deployment is dispatched by this simulation.

**Cleanup:** close MAS Console after the final result. Gradle's **75% EXECUTING** while the completed GUI remains open is normal. Regenerate only after changing inputs/generator/policy, not before each campaign. Keep generated files with their matching configuration revision.

<a id="a4-create-or-refresh-the-version-pair"></a>
### A4. Create or refresh the version pair

Skip A4 if your current pair already contains the intended app commits and control revision. `src/release.ts` is the source of the visible `Payment Service v1/v2` heading, browser titles, `/health.appVersion`, `/config.appVersion` and startup log. Changing an environment variable does not relabel a commit. A heading is a visual check; retain the full SHA and deployment receipt as identity evidence.

#### A4.1. Review and publish v1

Review and commit the app changes, tests, current docs and intended control/workflow changes on your review branch. Merge/register the workflows on the default branch through your normal process. Do not tag the old v1 SHA: it does not contain the new banner.

At the reviewed **v1 commit** in a clean checkout, run from the repository root:

```powershell
. {
    $ErrorActionPreference = 'Stop'
    $series = Get-Date -Format yyyyMMdd-HHmmss
    $v1Tag = "experiment-$series-v1"
    $v2Tag = "experiment-$series-v2"
    $workerRef = "comparison-worker-$series"
    $env:GITHUB_REPOSITORY = 'id-nynt/260031_cicd_payment_demo'
    if (git status --porcelain) { throw 'Review and commit intended changes before freezing v1' }
    $v1Sha = (git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve v1 source' }
    $releaseSource = git show "${v1Sha}:src/release.ts"
    if ($LASTEXITCODE -ne 0 -or ($releaseSource -join "`n") -notmatch "APP_VERSION[^=]*= 'v1';") {
      throw 'The selected commit must contain APP_VERSION v1'
    }
    npm run lint
    if ($LASTEXITCODE -ne 0) { throw 'Typecheck failed' }
    npm test
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
    git tag $v1Tag $v1Sha
    if ($LASTEXITCODE -ne 0) { throw 'Use a new tag name; never move an old tag' }
    git push origin "refs/tags/$v1Tag"
    if ($LASTEXITCODE -ne 0) { throw 'Resolve publication before continuing' }
}
```

Keep this PowerShell window open until A4.3 saves the selections. The existing `v1` tag, prior v2 tag and old receipts remain historical records; do not overwrite them.

#### A4.2. Create and publish v2

Create a candidate branch from the new v1 commit:

```powershell
. {
    $ErrorActionPreference = 'Stop'
    git switch -c "experiment/$series-v2" $v1Sha
    if ($LASTEXITCODE -ne 0) { throw 'Choose a fresh candidate branch' }
}
```

In `src/release.ts`, change only this declaration:

```typescript
export const APP_VERSION: 'v1' | 'v2' = 'v2';
```

The banner, browser titles, receipt title, APIs and startup log will now say v2. Payment behavior, database schema, faults and telemetry stay the same for a controlled comparison. Then:

```powershell
. {
    $ErrorActionPreference = 'Stop'
    npm run lint
    if ($LASTEXITCODE -ne 0) { throw 'Typecheck failed' }
    npm test
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
    git add -- src/release.ts
    git diff --cached
}
```

**Manual review:** confirm only the v1-to-v2 declaration is staged. Then publish with this separate block:

```powershell
. {
    $ErrorActionPreference = 'Stop'
    git commit -m "Mark experiment candidate as v2"
    if ($LASTEXITCODE -ne 0) { throw 'Candidate commit failed' }
    $v2Sha = (git rev-parse HEAD).Trim()
    git diff $v1Sha $v2Sha -- src
    git tag $v2Tag $v2Sha
    if ($LASTEXITCODE -ne 0) { throw 'Candidate tag failed' }
    git tag $workerRef $v2Sha
    if ($LASTEXITCODE -ne 0) { throw 'Control tag failed' }
    git push -u origin HEAD
    if ($LASTEXITCODE -ne 0) { throw 'Candidate branch publication failed' }
    git push origin "refs/tags/$v2Tag" "refs/tags/$workerRef"
    if ($LASTEXITCODE -ne 0) { throw 'Tag publication failed' }
}
```

The control tag selects the reviewed workflow code. Both mechanisms use this same tag, while `release_sha` separately selects v1 or v2. The app's source label change does not require BDI agent regeneration. Do not merge further app changes into this pair during the measured series.

#### A4.3. Save the pair selection

```powershell
. {
    $ErrorActionPreference = 'Stop'
    py -3 ci-cd-conventional/sync_workflows.py --check
    if ($LASTEXITCODE -ne 0) { throw 'Workflow copies differ' }
    py -3 ci-cd-conventional/configuration.py --check-bdi-parity
    if ($LASTEXITCODE -ne 0) { throw 'Paired configurations differ' }
    py -3 bdi-cicd-framework/run_controller.py --validate-only
    if ($LASTEXITCODE -ne 0) { throw 'Resolve generated-project consistency' }
    gh auth status
    if ($LASTEXITCODE -ne 0) { throw 'Restore existing GitHub authentication' }
    foreach ($value in @($series,$env:GITHUB_REPOSITORY,$v1Tag,$v1Sha,$v2Tag,$v2Sha,$workerRef)) {
      if ([string]::IsNullOrWhiteSpace($value)) { throw 'Missing pair selection. Restore the values from A4.1-A4.2 before saving; do not create an unnamed .json file.' }
    }
    New-Item -ItemType Directory -Force experiments/results/release-pairs | Out-Null
    $pairFile = [System.IO.Path]::GetFullPath("experiments/results/release-pairs/$series.json")
    if (Test-Path $pairFile) { throw 'Do not overwrite an earlier release pair' }
    $pair = [pscustomobject]@{
      series = $series; repository = $env:GITHUB_REPOSITORY
      v1_tag = $v1Tag; v1_sha = $v1Sha; v2_tag = $v2Tag; v2_sha = $v2Sha
      worker_ref = $workerRef; known_good_receipt = $null
    }
    $pair | ConvertTo-Json | Set-Content -LiteralPath $pairFile -Encoding utf8
    $pairFile | Set-Content -LiteralPath experiments/results/release-pairs/current-pair.txt -Encoding utf8
    Get-Content -LiteralPath experiments/results/release-pairs/current-pair.txt
}
```

`experiments/results/release-pairs/current-pair.txt` now contains the selected JSON path on one line. B2 and F1 read it automatically; do not copy the path into a quoted multiline value. A new series updates this pointer; previous JSON files remain intact. Both this text file and the selection record are local experiment evidence, so they are Git-ignored and need a backup. Start Docker Desktop and your **existing** Linux runner if stopped; verify it is online and can use Docker. Stop old traffic and settle any previous remote execution. If BDI has an unresolved execution, follow F3 before launching anything else.


**Next:** start Docker/runner as in B1, establish the first v1 receipt in F1, then B2-B3. Do not run F1 again between ordinary trials.

#### A4.4. Update only the control revision, retaining an existing app pair

**Use this for the adaptive repair update.** Payment code and v1/v2 labels have not changed. Keep their immutable tags and existing verified v1 receipt. The old worker tag cannot execute the new diagnosis/restart operations; select a new control tag and save a new pair record. Do not overwrite old tags or results.

**Open:** Controller PowerShell at the repository root and your GitHub review/Actions pages. First review and commit the implementation, generated artifacts, conventional snapshots and workflow copies. Publish/register the reviewed workflows through your normal branch/PR process. The following block checks a clean committed checkout, publishes a new tag, and saves the selection; it does not deploy.

```powershell
. {
    $ErrorActionPreference = 'Stop'
    $oldPairFile = (Get-Content experiments/results/release-pairs/current-pair.txt -Raw).Trim()
    $oldPair = Get-Content -LiteralPath $oldPairFile -Raw | ConvertFrom-Json
    if ([string]::IsNullOrWhiteSpace($oldPair.known_good_receipt)) { throw 'Link the existing v1 receipt in F1 first.' }
    if (-not (Test-Path -LiteralPath $oldPair.known_good_receipt)) { throw 'Restore the saved v1 receipt before continuing.' }
    if (git status --porcelain) { throw 'Review and commit the control update first.' }
    git diff --quiet $oldPair.v2_sha HEAD -- src tests package.json package-lock.json Dockerfile docker-compose.yml
    if ($LASTEXITCODE -ne 0) { throw 'Application files differ: review whether A4.1-A4.3 is required instead.' }
    py -3 bdi-cicd-framework/run_controller.py --validate-only
    if ($LASTEXITCODE -ne 0) { throw 'Resolve generated artifact consistency.' }
    py -3 ci-cd-conventional/configuration.py --check-bdi-parity
    if ($LASTEXITCODE -ne 0) { throw 'Resolve configuration parity.' }
    py -3 ci-cd-conventional/sync_workflows.py --check
    if ($LASTEXITCODE -ne 0) { throw 'Resolve workflow copies.' }
    $series = (Get-Date -Format yyyyMMdd-HHmmss) + '-repair'
    $workerRef = "comparison-worker-$series"
    $workerSha = (git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve reviewed control commit.' }
    git tag $workerRef $workerSha
    if ($LASTEXITCODE -ne 0) { throw 'Choose a fresh tag; never move an existing tag.' }
    git push origin "refs/tags/$workerRef"
    if ($LASTEXITCODE -ne 0) { throw 'Resolve tag publication before continuing.' }
    $pairFile = [System.IO.Path]::GetFullPath("experiments/results/release-pairs/$series.json")
    if (Test-Path -LiteralPath $pairFile) { throw 'Do not overwrite a pair record.' }
    [pscustomobject]@{
        series=$series; repository=$oldPair.repository
        v1_tag=$oldPair.v1_tag; v1_sha=$oldPair.v1_sha
        v2_tag=$oldPair.v2_tag; v2_sha=$oldPair.v2_sha
        worker_ref=$workerRef; worker_sha=$workerSha
        known_good_receipt=$oldPair.known_good_receipt; previous_pair=$oldPairFile
    } | ConvertTo-Json | Set-Content -LiteralPath $pairFile -Encoding utf8
    $pairFile | Set-Content experiments/results/release-pairs/current-pair.txt -Encoding utf8
    Get-Content -LiteralPath $pairFile
}
```

**Expected:** a new `*-repair.json` record and control tag, with the original v1/v2 SHAs and receipt retained. If publication fails, the local tag can exist without a new selection; resolve the reported error before proceeding. This creates a new experimental series: do not pool it with the earlier worker/policy revision. **Next: B1-B3**, then C1 `healthy`. Repeat **C1 → D → E** for each chosen case, changing only the separate `$case` selection. F1 is unnecessary when the retained receipt passes B2 validation.

<a id="b1-start-docker-and-the-deployment-runner"></a>
<a id="b2-restore-the-controller-session-completely"></a>
## B. Setup before each runtime

### B1. Open Docker and the existing deployment runner

First stop traffic from the previous completed campaign and close its completed MAS window. If a campaign was interrupted or a GitHub job remains active, use [interruption troubleshooting](#f3-reconcile-an-interrupted-campaign) before starting another deployment.

Check Docker Desktop is running and the existing `payment-deploy` runner is online/idle. If its service is already running, do not start another listener. Otherwise, in your existing WSL runner terminal:

```bash
cd ~/actions-runner-payment
docker info
docker compose version
./run.sh
```

### B2. Load the pair and clear stale settings

**Open:** Controller PowerShell. Run this entire block unchanged. It reads `current-pair.txt`, trims any trailing newline, validates both baseline environments, and captures the GitHub token without printing it. It does not deploy.

```powershell
. {
    $ErrorActionPreference = 'Stop'
    Set-Location C:\NHI\2026_IT-Project\260031_payment-repair
    $pair = $null
    $baseline = $null
    $knownGood = $null
    $v1Sha = $null
    $v2Sha = $null
    $sessionReady = $false
    foreach ($name in @('GH_TOKEN','GITHUB_TOKEN','GITHUB_API_URL','GITHUB_REPOSITORY','BDI_WORKFLOW_REF','BDI_RELEASE_SHA','BDI_EXECUTION_PLAN','BDI_SCENARIO','BDI_READY_URL','BDI_PROMETHEUS_URL','BDI_PAUSE_AFTER_ENTITY','BDI_PAUSE_MILLISECONDS','BDI_POLL_SECONDS','BDI_ENTITY_TIMEOUT_MINUTES')) {
        if (Test-Path "Env:$name") { Remove-Item "Env:$name" }
    }
    $pairFile = (Get-Content -LiteralPath experiments/results/release-pairs/current-pair.txt -Raw).Trim()
    if ([string]::IsNullOrWhiteSpace($pairFile) -or -not (Test-Path -LiteralPath $pairFile -PathType Leaf)) {
        throw 'Invalid current-pair.txt. Fix its one-line path before continuing.'
    }
    $pair = Get-Content -LiteralPath $pairFile -Raw | ConvertFrom-Json
    foreach ($field in @('series','repository','v1_tag','v1_sha','v2_tag','v2_sha','worker_ref','known_good_receipt')) {
        if ([string]::IsNullOrWhiteSpace($pair.$field)) { throw "Pair field $field is missing. Check A4/F1; stop here." }
    }
    $knownGood = $pair.known_good_receipt
    $baseline = Get-Content -LiteralPath $knownGood -Raw | ConvertFrom-Json
    if ($baseline.mode -ne 'github' -or $baseline.outcome -ne 'achieved' -or
        $baseline.repository -ne $pair.repository -or $baseline.release_sha -ne $pair.v1_sha) {
        throw 'Baseline receipt does not verify this pair v1.'
    }
    foreach ($environment in @('staging','production')) {
        $verified = $baseline.verified_releases.$environment
        if ($verified.release_sha -ne $pair.v1_sha -or -not $verified.github_run_id -or -not $verified.execution_id) {
            throw "Missing verified v1 identity for $environment"
        }
    }
    $env:GITHUB_REPOSITORY = $pair.repository
    $env:GITHUB_TOKEN = gh auth token --hostname github.com
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($env:GITHUB_TOKEN)) { throw 'Restore GitHub login before continuing.' }
    $env:BDI_WORKFLOW_REF = $pair.worker_ref
    $v1Tag = $pair.v1_tag
    $v2Tag = $pair.v2_tag
    $v1Sha = $pair.v1_sha
    $v2Sha = $pair.v2_sha
    $env:BDI_RELEASE_SHA = $v2Sha
    py -3 -B bdi-cicd-framework/run_controller.py --validate-only
    if ($LASTEXITCODE -ne 0) { throw 'Resolve artifact consistency before launching.' }
    $sessionReady = $true
    [pscustomobject]@{ Pair=$pairFile; Worker=$env:BDI_WORKFLOW_REF; V1=$v1Sha; V2=$v2Sha; KnownGood=$knownGood } | Format-List
}
```

**Checkpoint:** every displayed field is populated and validation passes. If reading a file fails, do not trust variables left from a previous run. The block explicitly clears those values first. `--validate-only` checks generated artifacts, not whether session variables are correct.

**Only if you intentionally select a different pair:** open `experiments/results/release-pairs/current-pair.txt` in a text editor and replace its contents with that pair JSON's full path on one line, without quotes. Save it, then rerun B2. Normal trials need no manual path editing.

<a id="b3-start-existing-app-containers-and-identify-the-deployed-version"></a>
<a id="b4-restore-both-environments-to-verified-v1-when-needed"></a>
### B3. Restore BOTH environments to v1 and verify the reset

Run this before the first trial in your session. E performs the same reset after each trial, so you can proceed directly to another scenario after E passes. Starting existing containers or seeing a v1 heading alone is not a verified reset.

This deploys the saved v1 source through BDI, with normal settings. It retains database data; `--confirm-compatible-rollback` confirms this pair's v1 remains compatible with that data/schema. Keep the reset run separate from measured v2 results.

**Controller PowerShell: launch the reset.**

```powershell
. {
    $ErrorActionPreference = 'Stop'
    if (-not $sessionReady -or [string]::IsNullOrWhiteSpace($v1Sha) -or [string]::IsNullOrWhiteSpace($knownGood)) { throw 'Complete B2 in this terminal first.' }
    foreach ($name in @('BDI_EXECUTION_PLAN','BDI_SCENARIO','BDI_READY_URL','BDI_PROMETHEUS_URL','BDI_PAUSE_AFTER_ENTITY','BDI_PAUSE_MILLISECONDS','BDI_POLL_SECONDS','BDI_ENTITY_TIMEOUT_MINUTES')) {
        if (Test-Path "Env:$name") { Remove-Item "Env:$name" }
    }
    $env:BDI_RELEASE_SHA = $v1Sha
    $resetDir = [System.IO.Path]::GetFullPath('bdi-cicd-framework/runs/' + (Get-Date -Format yyyyMMdd-HHmmss-fff) + '-restore-v1')
    $resetDir | Set-Content experiments/results/current-bdi-reset.txt -Encoding utf8
    $resetDir
    py -3 -B bdi-cicd-framework/run_controller.py --gui --known-good "$knownGood" --confirm-compatible-rollback --artifacts-dir "$resetDir"
}
```

Wait for the final MAS result. Close the completed MAS window, then run the verification block below. Gradle remaining at 75% while that GUI is open is normal. A launcher exit code alone does not prove deployment success.

```powershell
. {
    $ErrorActionPreference = 'Stop'
    $resetDir = (Get-Content experiments/results/current-bdi-reset.txt -Raw).Trim()
    $reset = Get-Content -LiteralPath (Join-Path $resetDir 'controller-result.json') -Raw | ConvertFrom-Json
    if ($reset.mode -ne 'github' -or $reset.outcome -ne 'achieved' -or $reset.repository -ne $pair.repository -or $reset.release_sha -ne $v1Sha) {
        throw 'Reset did not verify this pair v1. Inspect the reset journal; do not launch v2.'
    }
    foreach ($environment in @('staging','production')) {
        $port = if ($environment -eq 'staging') { 3001 } else { 3000 }
        $verified = $reset.verified_releases.$environment
        $health = Invoke-RestMethod "http://127.0.0.1:$port/health"
        Invoke-RestMethod "http://127.0.0.1:$port/ready"
        if ($verified.release_sha -ne $v1Sha -or -not $verified.github_run_id -or
            $health.appVersion -ne 'v1' -or $health.experimentMode -ne 'normal' -or
            $health.deploymentRunId -ne $verified.execution_id) { throw "Reset identity/health mismatch in $environment" }
        $inventoryPath = Join-Path $resetDir ("container-preflight-$environment-" + (Get-Date -Format yyyyMMdd-HHmmss-fff) + '.json')
        py -3 -B scripts/candidate-repair.py preflight --project "payment-$environment" --app app --dependency postgres --expected $verified.execution_id --output "$inventoryPath"
        if ($LASTEXITCODE -ne 0) { throw 'Container inventory is not clean. Inspect the saved preflight before launching a candidate.' }
    }
    $env:BDI_RELEASE_SHA = $v2Sha
    'Both environments verified at v1. Ready to choose ONE scenario.'
}
```

**If container preflight fails after an achieved reset:** the deployment may have succeeded but an obsolete/ambiguous container is blocking the next trial. Inspect the saved inventory. A stopped stale container does not occupy a port. Remove only a confirmed obsolete container by exact ID without force or volume deletion; then rerun only the B3 verification block if both live identities still match this reset. Do not rerun the deployment merely because that post-check failed. If identities changed, a fresh B3 reset is required.

Keep `$knownGood` as the original pair baseline. Do not replace it with a v2 result. Refresh `http://localhost:3001/checkout` and `http://localhost:3000/checkout`: both should show v1. Continue to C.

## C. Run ONE scenario

| Purpose | Choose |
|---|---|
| Matched BDI versus conventional study, 14 available shared cases | **C1**: automatic traffic/probes, fault timing, console capture and metrics |
| Interactive MAS GUI with healthy/error traffic | **C2**: replaces both old C0 and C0-S |
| Direct manual faults or a different goal | C3-C7 below (optional) |

**Run only the chosen route. After it finishes, go to D, not the next route.** Route C2 healthy is the GUI experiment you have been using; it is not automatically a matched C1 research trial.

<a id="c6-matched-comparison-all-11-scenarios"></a>
### C1. Matched research scenarios with automatic timing and evidence

The launcher verifies the published worker commit against the current agent, generator, adapters, workers, traffic profiles and metric scripts before dispatch. After this refactor/support update, publish a new reviewed control revision through A4.4; retain existing v1/v2 app SHAs. An old tag does not acquire local fixes. `--prepare-only` writes an offline plan; it neither resolves publication nor authorizes reuse of that directory for a live run.


**Open:** Controller PowerShell and the repository GitHub **Actions** page. Docker/runner remain running; no separate Traffic terminal or MAS GUI is required. B3 must have verified v1.

**Manual selection only:** run this short block separately. Change `healthy` to one shared case when you are ready for a different trial.

```powershell
$case = 'healthy'
```

| Case | Automatic injection / timing | Expected result |
|---|---|---|
| `healthy` | Normal production traffic | Deliver and verify v2 |
| `candidate-stopped` | Stop production app after its deployment job has passed; database stays ready | Diagnose matching stopped v2, restart once, probe and verify fresh health; achieve v2 |
| `candidate-restart-fails` | Same stopped candidate; controlled restart is immediately stopped again | One failed repair, then restore and verify v1; v2 goal remains unmet |
| `build-failure` | Build job exits before compilation/deployment | Stop; production remains v1 |
| `test-failure` | Test job exits with persistent failure | Stop; production remains v1 |
| `transient-test-failure` | First test attempt exits as a typed transient failure; second executes tests | Retry once; deliver if checks pass |
| `service-unavailable` | After production Compose deployment, stop only its app container | Readiness check fails; restore verified v1 and verify health |
| `infrastructure-failure` | After staging deployment, stop only its PostgreSQL container | Readiness check fails; block promotion; production remains v1 |
| `deployment-timeout` | Staging job sleeps 90s before deployment, with a 1-minute job deadline; repeat fault on retry | Confirm timeout, retry once, stop before production |
| `staging-temporary` | Stage request-fault mode; 35s mixed errors, then normal traffic | Recheck; promote if health recovers within budget |
| `staging-persistent` | Stage request-fault mode; persistent mixed errors | Exhaust bounded observations; block promotion |
| `production-temporary` | Production request-fault mode; 35s mixed errors, then normal traffic | Recheck; accept v2 if health recovers within budget |
| `production-persistent` | Production request-fault mode; persistent mixed errors | Exhaust initial observations and eligible final recheck; restore and verify v1 |
| `rollback-reconsideration` | Production request faults for 195s, then normal traffic | Select rollback, recheck for up to 60s, cancel before dispatch if two healthy correlated observations arrive; otherwise restore v1 |

**Scope:** build/test failures are controlled job failures, not yet independent commits with compiler/test defects. “Service unavailable” means the deployed payment service; “infrastructure failure” means its staging database, not the entire host/cloud. The timeout is a controlled pre-deployment hang. A host loss, runner loss, deployment API outage and real network partition remain additional experiments; do not report these scoped faults as proving resilience to those broader failures.

**Small initial study:** run `healthy`, `build-failure`, `candidate-stopped`, `production-persistent`, and `candidate-restart-fails` for both approaches, resetting between every trial. These cover normal delivery, deterministic stopping, repair that preserves v2, inapplicable repair, and failed repair with fallback. Add `production-temporary` for recovery without a restart. Predeclare repetitions and alternate approach order; all 13 cases are available, not mandatory.

Traffic profiles use a fixed seed and bounded rates/jitter. Normally each staging/production gate gets continuous normal or selected fault traffic. For the two stopped-candidate cases, production cannot serve traffic before repair: both approaches keep the same 15-second pause, diagnose, and use the shared restart worker's normal payment probes for 120 seconds. Staging traffic remains automatic. The production evidence is the operation receipt/probe count and subsequent health observations, not a missing `-traffic` folder. The failed-restart case intentionally has no successful post-repair production probes. Rollback verifies its own deployment identity.

**Expected repair trace:** `diagnose_candidate` → `restart_candidate` → `verify_repair` → `resume_candidate` → `Master goal achieved`. Diagnosis only authorizes restart for a matching stopped app with a ready database. Persistent request errors in a running app do not justify restart. A known-terminal failure or exhausted verification can select verified rollback; uncertain remote execution ends `unknown / unresolved` and requires F3. Repair is a bounded subgoal inside the existing execution loop; it never changes `master_goal` or turns rollback into v2 success.


**Then run this block unchanged in Controller PowerShell:**

```powershell
. {
    $ErrorActionPreference = 'Stop'
    if (-not $sessionReady) { throw 'Complete B2 first.' }
    $catalog = Get-Content experiments/scenarios.json -Raw | ConvertFrom-Json
    if ($case -notin $catalog.PSObject.Properties.Name) { throw 'Select a case from the shared catalog.' }
    py -3 ci-cd-conventional/configuration.py --check-bdi-parity
    if ($LASTEXITCODE -ne 0) { throw 'Paired configurations differ.' }
    $candidateDir = [System.IO.Path]::GetFullPath('experiments/results/bdi/' + (Get-Date -Format yyyyMMdd-HHmmss-fff) + '-' + $case)
    [pscustomobject]@{ campaign=$candidateDir; route='comparison'; scenario=$case; pair_file=$pairFile; reset=$resetDir } |
        ConvertTo-Json | Set-Content experiments/results/current-bdi-trial.json -Encoding utf8
    $candidateDir
    py -3 -B bdi-cicd-framework/run_experiment.py --mechanism bdi --case $case --release-sha "$v2Sha" --known-good "$knownGood" --confirm-compatible-rollback --seed 42 --artifacts-dir "$candidateDir"
}
```

The wrapper starts BDI and traffic; do not start another traffic client or click GitHub Run workflow. This route uses terminal output, not the keep-open MAS GUI. It automatically stores the console, plan, traffic and metrics. A failure case can correctly end with candidate delivery stopped; inspect the outcome and fault exposure rather than assuming every run should succeed. **Next: D, then E.**

<a id="c0-scenario-driven-traffic-recommended-for-repeatable-timing"></a>
<a id="c0-s-staging-traffic-failures-recover-or-block-promotion"></a>
<a id="3b-gui-with-scripted-traffic"></a>
### C2. GUI scenarios with scripted traffic

**Open:** Controller PowerShell, Traffic PowerShell, GitHub **Actions**, and browser checkout pages on ports 3000/3001. B3 must have verified v1. The launch opens MAS automatically.

All profiles below are implemented. `healthy` sends normal fake payments; `idle` deliberately sends none. Selecting a profile does not start traffic: complete preparation, traffic launch, then controller launch below.

| Profile | Behavior |
|---|---|
| `healthy` | About 3 normal payments/second, no injected errors |
| `fluctuating` | Normal requests at changing rates: 1, 6, 2, then 4/second |
| `burst` | Normal traffic peak; does not guarantee a failure |
| `temporary-errors` | Production: 70% fault-header requests for 35 seconds, then normal traffic |
| `persistent-errors` | Production: sustained 70% fault-header requests |
| `intermittent-errors` | Production: error/normal/error/normal phases |
| `idle` | No payments from this client; insufficient telemetry is not proof of app failure |
| `staging-temporary-errors` | Staging errors for 35 seconds, then normal traffic |
| `staging-persistent-errors` | Sustained staging errors; promotion should stop if health stays bad |

Rates are targets with seeded timing variation and one request in flight. The profiles run for at most 600 seconds of active traffic, and stop earlier at campaign completion/recovery. Temporary faults do not guarantee recovery within the observation budget. For staging profiles the script selects staging/port 3001 automatically; other profiles select production/port 3000.

**C2.1 - Manual selection, Controller PowerShell.** Run separately; change only the profile when choosing a different trial:

```powershell
$trafficScenario = 'healthy'
```

**C2.2 - Prepare, Controller PowerShell.** Run unchanged; it saves the trial path and profile for the other terminal. Do not create the campaign directory yourself.

```powershell
. {
    $ErrorActionPreference = 'Stop'
    if (-not $sessionReady) { throw 'Complete B2 first.' }
    if ($trafficScenario -notin @('healthy','fluctuating','burst','temporary-errors','persistent-errors','intermittent-errors','idle','staging-temporary-errors','staging-persistent-errors')) { throw 'Choose a listed traffic profile.' }
    $entity = if ($trafficScenario.StartsWith('staging-')) { 'staging' } else { 'production' }
    $env:BDI_RELEASE_SHA = $v2Sha
    $candidateDir = [System.IO.Path]::GetFullPath('bdi-cicd-framework/runs/' + (Get-Date -Format yyyyMMdd-HHmmss-fff) + '-' + $trafficScenario)
    if (Test-Path Env:BDI_EXECUTION_PLAN) { Remove-Item Env:BDI_EXECUTION_PLAN }
    if ($trafficScenario -like '*errors') {
        $faultFile = "$candidateDir-faults.properties"
        Set-Content -LiteralPath $faultFile -Value "$entity.experiment_mode=request_faults" -Encoding ascii
        $env:BDI_EXECUTION_PLAN = $faultFile
    }
    [pscustomobject]@{ campaign=$candidateDir; route='gui-traffic'; scenario=$trafficScenario; entity=$entity; pair_file=$pairFile; reset=$resetDir } |
        ConvertTo-Json | Set-Content experiments/results/current-bdi-trial.json -Encoding utf8
    Get-Content experiments/results/current-bdi-trial.json
}
```

For `healthy`, the fault-writing conditional is skipped. That is correct; no fault file is needed.

**C2.3 - Arm traffic, Traffic PowerShell.** This reads the saved selection automatically. No path copying or repeated profile assignment is needed.

```powershell
. {
    $ErrorActionPreference = 'Stop'
    Set-Location C:\NHI\2026_IT-Project\260031_payment-repair
    $trial = Get-Content experiments/results/current-bdi-trial.json -Raw | ConvertFrom-Json
    if ($trial.route -ne 'gui-traffic') { throw 'Prepare route C2 first.' }
    $trial | Format-List
    node scripts/run-traffic-scenario.mjs --campaign "$($trial.campaign)" --scenario "$($trial.scenario)" --seed 42
}
```

Wait for `WAITING` and leave this terminal running. The campaign folder may not exist yet; the traffic client waits for the controller journal and fresh deployment pause.

**C2.4 - Launch BDI, Controller PowerShell.**

```powershell
. {
    $ErrorActionPreference = 'Stop'
    $trial = Get-Content experiments/results/current-bdi-trial.json -Raw | ConvertFrom-Json
    if (-not $sessionReady -or $trial.campaign -ne $candidateDir -or $trial.scenario -ne $trafficScenario) {
        throw 'Controller selection changed. Do not launch; stop the waiting client and prepare a fresh trial.'
    }
    py -3 -B bdi-cicd-framework/run_controller.py --gui --known-good "$knownGood" --confirm-compatible-rollback --pause-after "$($trial.entity)" --pause-ms 15000 --artifacts-dir "$candidateDir"
}
```

The client starts when the chosen environment reaches its 15-second pause and its deployment identity matches. Look for `STARTED`, `PHASE`, `ACTIVE`, and `HTTP201` for successful payments. Error profiles also produce `injected503`. Keep it running until the final result; it stops automatically on completion/recovery. If you stop it early, record that interruption.

**Expected results:** healthy should finish `achieved / not_needed` with normal HTTP201 payments. Error profiles may reobserve, stop promotion, or restore v1 according to the observed health and budget; keep the actual result even if it differs from the hypothesis. The console is saved automatically.

The MAS log reports BDI decisions; the journal records detailed observations and the pause. On production rollback, production returns to v1 but staging may remain v2. Persistent staging faults can stop promotion without production rollback. **Next: D, then E. Do not run another scenario section now.**

### C3. Execution failure or bounded retry

**Open:** Controller PowerShell, GitHub **Actions** and Docker Desktop. Complete B1-B3 first. After this one scenario, follow D then E.

**Start:** v1 running; choose exactly one fault below. These are controlled worker failures, not traffic faults.

| Put this one line in `$faultLine` | Expected behavior |
|---|---|
| `build.failure_mode=force_failure` | Build fails once; no test or deployment; production stays v1 |
| `test.failure_mode=force_failure` | Test fails once; no production deployment |
| `security.failure_mode=force_failure` | Security fails once; no production deployment |
| `staging.failure_mode=force_failure` | Staging job fails before deployment; production stays v1 |
| `test.1.failure_mode=transient_failure` | Test attempt 1 fails, attempt 2 succeeds; v2 can finish successfully |
| `test.failure_mode=transient_failure` | Both test attempts fail; stop, production stays v1 |
| `production.1.failure_mode=transient_failure` | First production attempt fails before deployment; retry can deliver v2 |

**Manual selection:** Controller PowerShell, select one fault from the table; this requests the worker fault in advance, rather than asking you to edit a running GitHub job. Do not change the saved fault file after launching. Run this short block separately:

```powershell
$faultLine = 'test.1.failure_mode=transient_failure'
```

Then run this execution block unchanged:

```powershell
. {
    $ErrorActionPreference = 'Stop'
    if (-not $sessionReady) { throw 'Complete B2-B3 first.' }
    $env:BDI_RELEASE_SHA = $v2Sha
    $candidateDir = 'bdi-cicd-framework/runs/' + (Get-Date -Format yyyyMMdd-HHmmss-fff) + '-execution-fault'
    [pscustomobject]@{ campaign=[System.IO.Path]::GetFullPath($candidateDir); route='manual'; scenario='manual'; pair_file=$pairFile; reset=$resetDir } | ConvertTo-Json | Set-Content experiments/results/current-bdi-trial.json -Encoding utf8
    $faultFile = [System.IO.Path]::GetFullPath("$candidateDir-faults.properties")
    Set-Content -LiteralPath $faultFile -Value $faultLine -Encoding ascii
    $env:BDI_EXECUTION_PLAN = $faultFile
    $candidateDir
    py -3 -B bdi-cicd-framework/run_controller.py --gui --known-good "$knownGood" --confirm-compatible-rollback --artifacts-dir "$candidateDir"
}
```

**Explanation:**

- `$faultLine` selects the condition; `BDI_RELEASE_SHA` selects v2.
- `$candidateDir` names fresh evidence; `$faultFile` gives the fault file an absolute, campaign-specific path next to it.
- `Set-Content` writes the chosen fault; `BDI_EXECUTION_PLAN` tells Java to read it before dispatch.
- The last two commands display the evidence path and start the agent. The file chooses the fault, not the agent's decision.

**Expected results:**

- GitHub's selected job shows the controlled failing step.
- A transient retry prints `BDI_DECISION=retry`; `max_retries: 1` means two total attempts at most.
- Deterministic build/test/security failure normally finishes `stopped / not_attempted`; no blind retry.
- The first-attempt-only fault can finish `achieved / not_needed` after the second attempt succeeds.

**Finish:** D, then `Remove-Item Env:BDI_EXECUTION_PLAN -ErrorAction SilentlyContinue`. Preserve the fault file as evidence. Repeat B before the next case; a failed production attempt may leave staging at v2.

### C4. Temporary production error traffic, then continue v2

**Open:** Controller, Traffic and Observation PowerShell windows, GitHub **Actions** and Docker Desktop. Complete B1-B3 first. After this one scenario, follow D then E.

**Start:** v1 running. Prepare Observation and Traffic PowerShell windows **before launching**. Read all of this step first. Enabling `request_faults` does not itself create errors.

**Why traffic must continue during this release-verification experiment:** this script is the client sending payment requests. Without `--continuous`, it sends six requests and exits; the app itself can remain ready. The 30-second latency query needs recent payment samples. Once requests stop, the histogram rate can become zero and p95 undefined, so the controller cannot confirm healthy telemetry. Stopping errors must therefore be followed immediately by **normal traffic**, not silence.

Use the direct `node` commands below. In the observed Windows invocation, the npm wrapper did not forward `--continuous`. Direct invocation removes that argument-forwarding dependency. Do not change missing metrics to zero or extend the observation budget just to conceal missing traffic.

**Manual selection - choose when YOU will stop errors:** read this separately before launching. No agent or Java configuration change is needed.

| Demonstration | When to switch from error traffic to normal traffic | What it demonstrates |
|---|---|---|
| Temporary degradation (default) | After a fresh bad production measurement and `wait_reconsider` | Reobservation allows delivery after the condition recovers |
| Rollback reconsideration | Keep errors until the journal records `rollback_selected`, then switch immediately | The selected rollback is still pending; two healthy correlated observations can cancel it and resume `master_goal` |

For the second variant, the current policy permits only 60 seconds after rollback selection. The 30-second metric window must clear within it. Recovery is not guaranteed. `bdi_recovery_decision` / `BDI_DECISION=rollback source=...` means rollback was actually committed: switching traffic then cannot resume this candidate. Do not confuse `wait_reconsider` (a normal observation wait) with `rollback_selected`.

The direct error client sends fault headers on every payment, in batches of six with a one-second pause between batches. This differs from the automatic profile's nominal 70% errors at four requests/second. Record actual start/stop times; do not label the manual run a fixed 35-second or 195-second experiment unless its evidence supports that duration.

**Actions 1 - launch:** Controller PowerShell:

```powershell
. {
    $ErrorActionPreference = 'Stop'
    if (-not $sessionReady) { throw 'Complete B2-B3 first.' }
    $env:BDI_RELEASE_SHA = $v2Sha
    $candidateDir = 'bdi-cicd-framework/runs/' + (Get-Date -Format yyyyMMdd-HHmmss-fff) + '-temporary-traffic'
    [pscustomobject]@{ campaign=[System.IO.Path]::GetFullPath($candidateDir); route='manual'; scenario='manual'; pair_file=$pairFile; reset=$resetDir } | ConvertTo-Json | Set-Content experiments/results/current-bdi-trial.json -Encoding utf8
    $faultFile = [System.IO.Path]::GetFullPath("$candidateDir-faults.properties")
    Set-Content -LiteralPath $faultFile -Value 'production.experiment_mode=request_faults' -Encoding ascii
    $env:BDI_EXECUTION_PLAN = $faultFile
    $candidateDir
    py -3 -B bdi-cicd-framework/run_controller.py --gui --known-good "$knownGood" --confirm-compatible-rollback --pause-after production --pause-ms 15000 --artifacts-dir "$candidateDir"
}
```

**Explanation:**

- The release assignment selects v2; the directory assignment identifies this campaign.
- `$faultFile` resolves an absolute file path; `Set-Content` enables header-triggered production errors.
- `BDI_EXECUTION_PLAN` selects that file; the next command prints the campaign directory.
- The launcher pauses for 15 seconds **after the production GitHub job finishes, before the agent receives its result and observes health**. The pause is automatic, not a prompt waiting for you.

**Actions 2 - watch immediately:** Observation PowerShell:

```powershell
. {
    $ErrorActionPreference = 'Stop'
    Set-Location C:\NHI\2026_IT-Project\260031_payment-repair
    $watchDir = (Get-Content experiments/results/current-bdi-trial.json -Raw | ConvertFrom-Json).campaign
    Get-Content "$watchDir/controller-journal.jsonl" -Tail 30 -Wait
}
```

- `Set-Location` resolves the copied relative path; the saved selection supplies this campaign's path in this window.
- `Get-Content` follows the journal; start after the file appears. **The pause is a Java journal event, not a message in the MAS `controller_agent` tab.** Keep this Observation terminal visible.

**Expected start signal in Observation PowerShell** (field order can differ):

```json
{"event":"controller_pause","after_entity":"production","milliseconds":15000}
```

This excerpt identifies a 15-second pause that resumes automatically. It is not a prompt awaiting input. Watch the current campaign's new event, not a pause from a previous journal. If the event is already more than 15 seconds old, inspect the current outcome before proceeding; do not guess from `run entity=production`, which only means dispatch started.

**Actions 3 - at `controller_pause` with `after_entity: production`:** immediately run in Traffic PowerShell:

```powershell
. {
    $ErrorActionPreference = 'Stop'
    Set-Location C:\NHI\2026_IT-Project\260031_payment-repair
    $manualTrial = Get-Content experiments/results/current-bdi-trial.json -Raw | ConvertFrom-Json
    $manualDir = $manualTrial.campaign
    if ($manualTrial.route -ne 'manual' -or -not $manualDir) { throw 'Launch C4 or C5 first.' }
    if (Test-Path (Join-Path $manualDir 'controller-result.json')) { throw 'Campaign already ended; do not inject.' }
    $events = @(Get-Content (Join-Path $manualDir 'controller-journal.jsonl') | ForEach-Object { $_ | ConvertFrom-Json })
    if ($events | Where-Object { $_.event -eq 'bdi_recovery_decision' }) { throw 'Recovery already dispatched; do not inject.' }
    $deployment = $events | Where-Object { $_.event -eq 'execution_configuration' -and $_.entity -eq 'production' } | Select-Object -Last 1
    if (-not $deployment.execution_id) { throw 'No production deployment identity yet; wait for its pause.' }
    $health = Invoke-RestMethod http://localhost:3000/health
    $health
    if ($health.appVersion -ne 'v2' -or $health.experimentMode -ne 'request_faults' -or $health.deploymentRunId -ne $deployment.execution_id) {
        throw 'Wrong production version, mode or deployment identity; do not inject.'
    }
    function Write-ManualEvent([string]$Action) {
        [pscustomobject]@{ timestamp=(Get-Date).ToUniversalTime().ToString('o'); action=$Action; deployment_execution_id=$deployment.execution_id } |
            ConvertTo-Json -Compress | Add-Content (Join-Path $manualDir 'manual-injection.jsonl') -Encoding utf8
    }
    $trafficLog = Join-Path $manualDir ('manual-traffic-' + (Get-Date -Format yyyyMMdd-HHmmss-fff) + '.txt')
    Start-Transcript -Path $trafficLog -NoClobber
    Write-ManualEvent 'error_traffic_start_requested'
    $env:PAYMENT_BASE_URL = 'http://localhost:3000'
    node scripts/generate-experiment-traffic.mjs inject_error 6 --continuous
}
```

- `Set-Location` selects the traffic script's repository.
- The health request and display confirm the new app's mode/identity; the guard rejects a normal-mode app.
- `PAYMENT_BASE_URL` targets production; `node` passes `--continuous` directly to the script and continuously sends fault-header requests.

**Traffic checkpoint before continuing:**

- `/health` must show `request_faults`. If the guard throws or the connection resets, stop here; the app may still be changing. Recheck `/health` before retrying. Do not continue past the error.
- HTTP 503 lines and `Summary` lines must repeat across multiple batches, approximately once a second plus request time.
- The `PS C:\...>` prompt must **not** return until you press Ctrl+C or the script fails.
- Six responses followed by a prompt means the client stopped. The final `Wait 10-20 seconds...` message also means the script exited; it is not running in the background.
- Keep the Traffic terminal visible. If it exits with an error, retain that error and check the app/mode before restarting.

**Actions 4 - stop the fault at your chosen checkpoint:** for the default case, wait for a fresh production `telemetry_measurement` with error rate above `0.05` and `BDI_DECISION=wait_reconsider`. For the reconsideration variant, wait instead for `rollback_selected`. Then **press Ctrl+C only in Traffic PowerShell**, and immediately run this complete block in that same window. Keep the Controller/MAS running:

```powershell
. {
    $ErrorActionPreference = 'Stop'
    Write-ManualEvent 'error_traffic_stopped_by_operator'
    $health = Invoke-RestMethod http://localhost:3000/health
    if ($health.deploymentRunId -ne $deployment.execution_id) { throw 'Candidate identity changed; inspect rollback before sending more traffic.' }
    Write-ManualEvent 'normal_traffic_start_requested'
    node scripts/generate-experiment-traffic.mjs normal 6 --continuous
}
```

- This sends successful requests while the 30-second metric window clears. Do not wait another 30 seconds before starting normal traffic.

**Normal-traffic checkpoint:**

- Repeated HTTP 201 responses and increasing success totals must appear; the PowerShell prompt must not return. Leave this running until the agent's final result.
- In the Observation terminal, production measurements should remain/become `data_status: fresh`; error rate should fall below the configured limit as the old errors leave the window. Latency must also pass.
- `wait_reconsider` alone does not prove a bad error rate: it also appears for missing data or while waiting for the next healthy sample.
- An `unavailable` measurement's numeric zeros are placeholders, not proof of zero errors or zero latency. If normal traffic is repeating but measurements remain unavailable beyond the export/scrape delay, inspect Prometheus rather than assuming success (see F2).
- If the campaign already ended or rollback began, new traffic cannot resume that campaign. Finish recording it, reset with E and start a new C4 run.

**Expected results:**

- Error traffic produces HTTP 503; normal traffic produces HTTP 201.
- The agent actually observes unhealthy production before you remove the cause; otherwise this is not a demonstrated fault-recovery experiment.
- It rechecks rather than redispatching production. If health clears within the count/time budget, two consecutive healthy samples allow `achieved / not_needed`; production stays v2.
- Current `config/controller_policy.yaml` maximum: 36 observations, five seconds apart, within 180 seconds from the first observation. This is a maximum, not a mandatory wait; two healthy observations can finish quickly.
- In the reconsideration variant, require `rollback_selected`, fresh correlated samples, `rollback_cancelled`, final `achieved`, and no rollback execution. If errors clear too late or another metric remains unhealthy, rollback is a valid outcome. Record it rather than claiming temporary recovery succeeded.

**Finish:** after the final result, press Ctrl+C in Traffic PowerShell, then run there:

```powershell
Write-ManualEvent 'traffic_stopped_after_result'
Stop-Transcript
```

Close MAS only after its final message asks you to close. Perform D, then E to reset. If you missed the pause and the campaign already succeeded, it cannot be faulted retrospectively: reset and start a fresh campaign.

### C5. Persistent production error traffic, then rollback

**Open:** Controller, Traffic and Observation PowerShell windows, GitHub **Actions** and Docker Desktop. Complete B1-B3 first. After this one scenario, follow D then E.

**Start:** B1-B3 must have passed for this trial. Prepare the two extra terminals as in C4; do not reuse the previous campaign directory.

**Actions - launch:** Controller PowerShell:

```powershell
. {
    $ErrorActionPreference = 'Stop'
    if (-not $sessionReady) { throw 'Complete B2-B3 first.' }
    $env:BDI_RELEASE_SHA = $v2Sha
    $candidateDir = 'bdi-cicd-framework/runs/' + (Get-Date -Format yyyyMMdd-HHmmss-fff) + '-persistent-traffic'
    [pscustomobject]@{ campaign=[System.IO.Path]::GetFullPath($candidateDir); route='manual'; scenario='manual'; pair_file=$pairFile; reset=$resetDir } | ConvertTo-Json | Set-Content experiments/results/current-bdi-trial.json -Encoding utf8
    $faultFile = [System.IO.Path]::GetFullPath("$candidateDir-faults.properties")
    Set-Content -LiteralPath $faultFile -Value 'production.experiment_mode=request_faults' -Encoding ascii
    $env:BDI_EXECUTION_PLAN = $faultFile
    $candidateDir
    py -3 -B bdi-cicd-framework/run_controller.py --gui --known-good "$knownGood" --confirm-compatible-rollback --pause-after production --pause-ms 15000 --artifacts-dir "$candidateDir"
}
```

**Explanation:**

- Release and directory assignments select published v2 and new evidence.
- `$faultFile` gives this campaign its own file; `Set-Content` enables request faults.
- The plan assignment selects it; printing the directory lets you follow the correct journal.
- The launcher starts the campaign and gives the same 15-second production pause.

Follow **C4 Actions 2 and 3** to watch the journal and start error traffic at the pause. This time **keep errors running throughout initial observations AND the final reconsideration window**. Do not stop at `rollback_selected`: that is still a pending decision. When the journal records `bdi_recovery_decision` or MAS prints `BDI_DECISION=rollback source=...`, press Ctrl+C only in Traffic PowerShell and run:

```powershell
Write-ManualEvent 'error_traffic_stopped_after_rollback_commit'
Stop-Transcript
```

The rollback worker supplies its verification probes. Do not send intentional fault traffic into the restored baseline. If the error client exits on an unexpected response or identity change, preserve its transcript and record that event; do not blindly restart it.

**Expected results:**

- Repeated unhealthy observations and `wait_reconsider`, then `rollback_selected`; persistent errors during the additional 60-second window lead to `rollback_committed` and actual rollback.
- GitHub runs **Rollback entity** using verified v1 source.
- MAS ends `BDI_CONTROLLER_RESULT=stopped recovery=restored` after recovery health is verified.
- A new payment on production shows v1. Staging may still show v2: automatic rollback restores production only.
- Once rollback starts, this campaign will not resume v2 even if traffic stops.

**Finish:** D, then E restores both environments before the next comparison. If recovery is failed/unverified, inspect its job and telemetry before proceeding.

**For staging traffic:** choose `staging-temporary-errors` or `staging-persistent-errors` in C2 for the complete automated timing procedure. Do not adapt production commands during a running trial.

### C6. Production job failure after deployment, then rollback

**Open:** Controller PowerShell, GitHub **Actions** and Docker Desktop. Complete B1-B3 first. After this one scenario, follow D then E.

**Start:** B1-B3 complete. This deterministic case avoids traffic timing and tests recovery after the production worker has changed the app.

**Actions:** Controller PowerShell:

```powershell
. {
    $ErrorActionPreference = 'Stop'
    if (-not $sessionReady) { throw 'Complete B2-B3 first.' }
    $env:BDI_RELEASE_SHA = $v2Sha
    $candidateDir = 'bdi-cicd-framework/runs/' + (Get-Date -Format yyyyMMdd-HHmmss-fff) + '-production-failure'
    [pscustomobject]@{ campaign=[System.IO.Path]::GetFullPath($candidateDir); route='manual'; scenario='manual'; pair_file=$pairFile; reset=$resetDir } | ConvertTo-Json | Set-Content experiments/results/current-bdi-trial.json -Encoding utf8
    $faultFile = [System.IO.Path]::GetFullPath("$candidateDir-faults.properties")
    Set-Content -LiteralPath $faultFile -Value 'production.failure_mode=force_failure' -Encoding ascii
    $env:BDI_EXECUTION_PLAN = $faultFile
    $candidateDir
    py -3 -B bdi-cicd-framework/run_controller.py --gui --known-good "$knownGood" --confirm-compatible-rollback --artifacts-dir "$candidateDir"
}
```

**Explanation:**

- The first two assignments select v2 and a new campaign path.
- `$faultFile` defines an absolute path; `Set-Content` requests a controlled production failure.
- The plan assignment enables the fault; the path display identifies evidence.
- The launch lets Jason select deployment and, on failure, recovery.

**Expected results:**

- Production job fails at **Controlled post-deployment failure**, after its Compose deployment command.
- Jason selects rollback; successful verified restoration ends `stopped / restored`.
- Production returns to v1, staging can remain v2. Restoration is not successful candidate delivery.

**Finish:** D, then use E for the next experiment. Remove the fault environment setting before restoring v1.

<a id="optional-experiment-require-staging-to-fail"></a>
### C7. Request an actual staging failure as the achievement

**Open:** Controller PowerShell, GitHub **Actions** and Docker Desktop. Complete B1-B3 first. After this one scenario, follow D then E.

**Start:** B1-B3 complete. This changes the goal, not just the fault. Use a separate generated project to preserve normal deployment goals.

**Actions:** Controller PowerShell:

```powershell
. {
    $ErrorActionPreference = 'Stop'
    $negativeProject = 'bdi-cicd-framework/projects/staging-failure'
    py -3 -B bdi-cicd-framework/generate_project.py --project-dir "$negativeProject" --pipeline bdi-cicd-framework/models/01_pipeline.yaml --goal bdi-cicd-framework/examples/staging_failure_goal.yaml --policy bdi-cicd-framework/config/controller_policy.yaml --bindings bdi-cicd-framework/config/runtime_bindings.yaml
    if ($LASTEXITCODE -ne 0) { throw 'Negative-goal generation failed' }
    if (-not $sessionReady) { throw 'Complete B2-B3 first.' }
    $env:BDI_RELEASE_SHA = $v2Sha
    $candidateDir = 'bdi-cicd-framework/runs/' + (Get-Date -Format yyyyMMdd-HHmmss-fff) + '-expected-staging-failure'
    [pscustomobject]@{ campaign=[System.IO.Path]::GetFullPath($candidateDir); route='manual'; scenario='manual'; pair_file=$pairFile; reset=$resetDir } | ConvertTo-Json | Set-Content experiments/results/current-bdi-trial.json -Encoding utf8
    $faultFile = [System.IO.Path]::GetFullPath("$candidateDir-faults.properties")
    Set-Content -LiteralPath $faultFile -Value 'staging.failure_mode=force_failure' -Encoding ascii
    $env:BDI_EXECUTION_PLAN = $faultFile
    $candidateDir
    py -3 -B bdi-cicd-framework/run_controller.py --project-dir "$negativeProject" --gui --baseline --artifacts-dir "$candidateDir"
}
```

**Explanation:**

- `$negativeProject` selects a separate artifact folder; generation writes its failure goal and agent. Regenerate this project only when its inputs/generator change.
- The guard stops on generation failure; the release assignment selects v2.
- The campaign/fault path assignments keep evidence separate; `Set-Content` selects a real controlled staging failure.
- The plan assignment enables that fault; the path display identifies the journal.
- `--project-dir` loads the separate agent; `--baseline` means no prior recovery receipt, not a verified healthy release.

**Expected results:**

- Generated agent contains `achievement(staging, failure)`.
- Build/test/security succeed, staging fails, and MAS reports the expected failure and goal achievement.
- Result has `negative_goal_experiment: true` and no verified release receipts; do not use it as `$knownGood`.
- Production is not dispatched. An unknown/rejected dispatch does not satisfy a failure goal.

**Finish:** D, remove the fault setting and omit this `--project-dir` for normal experiments. To test an unmet failure goal, repeat this project's launch with a fresh directory and no fault plan: healthy staging should end with goals unmet rather than deliberately failing itself. Restore v1 afterward if staging changed.


<a id="e1-record-the-outcome-before-the-next-run"></a>
## D. Finalise: save and inspect this experiment

**Open:** Controller PowerShell and the campaign folder printed by C. For a GUI screenshot only, keep the completed MAS window open until captured. No deployment starts in D.

Most evidence is already written automatically. Do not manually copy JSON output from the terminal into replacement files.

| Evidence | Automatic location |
|---|---|
| Every new launcher run: console output, including agent log messages | `<campaign>/controller-console.log` |
| Outcome, verified releases, execution IDs | `<campaign>/controller-result.json` |
| Decisions, observations, recovery history | `<campaign>/controller-journal.jsonl` |
| Exact configuration/agent provenance | Files inside `<campaign>/` |
| C1 wrapper console and experiment plan | `<campaign>-experiment/controller-console.log`, `plan.json` |
| Route C1 derived metrics | `<campaign>/experiment-metrics.json` |
| Downloaded diagnosis/restart receipts, Docker identity and probe counts | `<campaign>/operation-<operation UUID>/receipt.json`; `download.log` reports download problems |
| Scripted traffic settings, requests, summary (C1/C2) | Sibling `<campaign>-traffic*` folders |
| Manually started/stopped traffic (C4/C5) | `<campaign>/manual-traffic-*.txt` and `manual-injection.jsonl` |

**Automatic C1 evidence:** `<candidateDir>-experiment/plan.json` declares `traffic_targets`. Every reached staging/production gate needs matching profile, seed, execution ID, release SHA and successful traffic evidence. Build/test failures before deployment legitimately have no traffic; stopped-candidate production uses repair probes instead. Inspect `traffic_by_entity` in `experiment-metrics.json`. The launcher also saves `launch-status.json` and per-client `traffic-<entity>-console.log` beside the plan. If the result is missing, inspect these files and reconcile before another run; do not label an interrupted launcher as a deployment outcome.

**Manual C3-C7 evidence:** retain the chosen fault file and actual outcome even if it differs from your intention. For C4/C5, action timestamps record operator requests; HTTP 503 output proves responses were produced, and unhealthy agent observations prove the controller saw the disturbance. None substitutes for the others. Manual traffic has no automatic seeded-profile `summary.json`; do not manufacture one or run guide 07's D4 against a manual campaign. Save the following notes after the run (Controller PowerShell, separate from the inspection block):

```powershell
$manualNotes = Read-Host 'Describe the chosen fault, when you removed it, unexpected behaviour and any repair/approval intervention'
```

```powershell
. {
    $ErrorActionPreference = 'Stop'
    $saved = Get-Content experiments/results/current-bdi-trial.json -Raw | ConvertFrom-Json
    if ($saved.route -ne 'manual') { throw 'These notes are for C3-C7 manual runs.' }
    $notePath = Join-Path $saved.campaign ('operator-notes-' + (Get-Date -Format yyyyMMdd-HHmmss-fff) + '.txt')
    $manualNotes | Set-Content -LiteralPath $notePath -Encoding utf8
    $notePath
}
```

Record planned fault injection separately from unplanned intervention to help the candidate recover. Closing the completed MAS window and collecting evidence are not candidate-repair actions. Finalise every run before reset; do not infer a successful manual experiment merely from GitHub job success.

**Reading the agent sequence:** the console records `BDI_STAGE=1` (previous-job post-observations), `2` (next-job pre-observations), `3` (job dispatch) and `4` (goal assessment). Repeated stages are normal when percepts arrive or health is rechecked; count actual execution/retry events for metrics. Diagnosis, restart, fresh verification and rollback remain visible as `BDI_DECISION` events. A job returning success is not proof of healthy delivery; inspect the final result and verified-release evidence below.

**Automatic capture:** the controller launcher now saves its combined stdout/stderr as `<campaign>/controller-console.log` while displaying it live. The GUI logging configuration sends agent messages to the console as well, so you no longer need to copy MAS text for new runs. This also covers baseline and reset runs. C1 additionally retains its wrapper console under `-experiment/`. Existing completed runs are not retroactively given a console log.

**Manual only for visual/context evidence:** if your study needs an agent-mind screenshot, while MAS is open, open its printed inspector URL, select `controller_agent`, and use `Win+Shift+S`; save `agent-mind-final.png` inside the printed campaign folder. Save approval/timing observations as `operator-notes.txt`. For an older run with no saved console, copy the MAS output to `mas-console.txt` (or `mas-console-excerpt.txt`) there before closing it. If already closed, record the missing capture; do not rerun to recreate evidence for that old run.

Close the **completed** MAS window, then run this block in Controller PowerShell. It also works in a reopened terminal because it reads the saved trial selection.

```powershell
. {
    $ErrorActionPreference = 'Stop'
    Set-Location C:\NHI\2026_IT-Project\260031_payment-repair
    $result = $null
    $trial = Get-Content experiments/results/current-bdi-trial.json -Raw | ConvertFrom-Json
    $candidateDir = $trial.campaign
    if ([string]::IsNullOrWhiteSpace($candidateDir)) { throw 'Saved trial has no campaign path.' }
    "Inspecting: $candidateDir"
    $result = Get-Content -LiteralPath (Join-Path $candidateDir 'controller-result.json') -Raw | ConvertFrom-Json
    $result | Select-Object mode,outcome,recovery_outcome,release_sha,known_good_sha,goal_message | Format-List
    $result.executions
    $result.telemetry
    $result.verified_releases
    Get-Content -LiteralPath (Join-Path $candidateDir 'controller-journal.jsonl') |
        Select-String 'bdi_decision|diagnosis_|repair_|telemetry_measurement|rollback_selected|bdi_recovery_decision|controller_finished'
    $parent = Split-Path -Parent $candidateDir
    $leaf = Split-Path -Leaf $candidateDir
    Get-ChildItem -LiteralPath $parent -Directory | Where-Object { $_.Name -like "$leaf-traffic*" } | ForEach-Object {
        $summaryFile = Join-Path $_.FullName 'summary.json'
        if (Test-Path -LiteralPath $summaryFile) {
            "Traffic summary: $summaryFile"
            Get-Content -LiteralPath $summaryFile
        } else { "Traffic summary missing: $($_.FullName). Check whether the client is still running or was interrupted." }
    }
}
```

`achieved / not_needed` means candidate goals were met. `stopped / restored` means candidate delivery failed but verified v1 recovery succeeded. `stopped / not_attempted` commonly means the run stopped before recovery was applicable. Failed/unknown recovery requires investigation. Traffic `stopped` with `campaign_finished` means the client ended; it does not mean the deployment failed.

For repair trials, inspect `candidate_repair_operations` in the result, the receipts above, and `repair_attempts`, `candidate_repaired`, `candidate_repair_seconds` in the metrics. The original production execution ID must match the diagnosis target and post-repair observations. The restart operation has its own GitHub run/operation UUID; it does not replace the production deployment identity. `candidate_repaired=true` requires final candidate delivery and accepted health after an executed restart. A repair action returning `executed` alone is insufficient. All this evidence is automatic; screenshots remain optional.

Preserve campaign, matching `*-faults.properties`, and sibling traffic/experiment folders together, including failed runs. They are Git-ignored, so back them up separately. Use [guide 05](05_EXPERIMENT_RESULTS_GUIDE.md) for metrics and comparison. If the result is missing, inspect the saved path and journal; do not create a fake result or begin another run while remote work remains unresolved.

**Download remote job logs automatically (recommended before GitHub retention expires):** after the inspection block, run this unchanged. It finds all acknowledged GitHub runs in the journal, including retry attempts, and stores logs/metadata in a new subfolder. It only reads GitHub; it does not dispatch anything. A download failure is reported; rerun into another fresh folder rather than treating missing evidence as success.

```powershell
. {
    $ErrorActionPreference = 'Stop'
    if ($result.mode -ne 'github' -or [string]::IsNullOrWhiteSpace($result.repository)) { throw 'Select a live trial result in D first.' }
    $journal = Get-Content -LiteralPath (Join-Path $candidateDir 'controller-journal.jsonl') | ForEach-Object { $_ | ConvertFrom-Json }
    $remoteIds = @($journal | Where-Object { $_.github_run_id } | ForEach-Object { $_.github_run_id } | Sort-Object -Unique)
    if ($remoteIds.Count -eq 0) { throw 'No acknowledged remote runs found. Preserve the journal and inspect any rejected/uncertain dispatch.' }
    $remoteDir = Join-Path $candidateDir ('github-evidence-' + (Get-Date -Format yyyyMMdd-HHmmss-fff))
    New-Item -ItemType Directory -Path $remoteDir | Out-Null
    foreach ($remoteId in $remoteIds) {
        $remoteLog = gh run view $remoteId --repo $result.repository --log
        if ($LASTEXITCODE -ne 0) { throw "Could not download log for $remoteId. Evidence is incomplete: $remoteDir" }
        $remoteLog | Set-Content (Join-Path $remoteDir "$remoteId.log") -Encoding utf8
        $remoteInfo = gh run view $remoteId --repo $result.repository --json databaseId,headSha,conclusion,status,url,jobs
        if ($LASTEXITCODE -ne 0) { throw "Could not download metadata for $remoteId. Evidence is incomplete: $remoteDir" }
        $remoteInfo | Set-Content (Join-Path $remoteDir "$remoteId.json") -Encoding utf8
    }
    "Remote evidence saved: $remoteDir"
}
```

**Expected:** the result and console log exist, the journal shows the final decision, any traffic clients have summary files, and remote log downloads complete or explicitly report their gaps. **Next: E.**

**Inspecting an older run instead of the saved current trial:** select it in a separate manual-input block, then save that selection before running the inspection block above:

```powershell
$selectedCampaign = (Read-Host 'Paste the full existing campaign folder path, without quotes').Trim()
```

```powershell
. {
    $ErrorActionPreference = 'Stop'
    if ([string]::IsNullOrWhiteSpace($selectedCampaign)) { throw 'No campaign selected.' }
    $selectedCampaign = (Resolve-Path -LiteralPath $selectedCampaign).Path
    if (-not (Test-Path -LiteralPath (Join-Path $selectedCampaign 'controller-result.json'))) { throw 'This folder has no controller result.' }
    [pscustomobject]@{ campaign=$selectedCampaign; route='existing'; scenario='recorded-in-evidence' } |
        ConvertTo-Json | Set-Content experiments/results/current-bdi-trial.json -Encoding utf8
}
```

## E. Clean up and reset to v1

After saving evidence, stop any remaining Traffic/Observation clients with Ctrl+C, close the completed MAS window, and confirm the remote GitHub jobs are terminal. Do not clear unresolved execution records. Keep Docker and the runner running.

**The next actions are explicitly:**

1. Run the complete **B2 Controller block** again. It reads the saved pair automatically, clears stale fault/pause/telemetry settings and reloads valid session variables. No placeholder or manual path is required.
2. Run **both B3 blocks**: launch the v1 reset, close the completed reset MAS, then verify both environments. This is the actual redeployment to v1; clearing variables alone does not reset the app.
3. Once verification prints `Both environments verified at v1`, choose your next scenario in **C**. Do not repeat setup, A4/F1, or another reset unless the deployed state changes.

This applies even if production already rolled back: staging may still be v2 or fault-enabled. The original `$knownGood` receipt and completed trial evidence remain unchanged. For the conventional counterpart, after this verified reset, follow its session and trial instructions using the same pair/case/seed; preserve the reset evidence with the comparison.

## F. Baseline and troubleshooting

### F1. Establish or link the first verified v1 baseline

**Open:** Controller PowerShell, Docker Desktop, the existing runner (B1), and GitHub Actions. A4 must already have saved the pair. If a matching successful baseline already exists, use the existing-baseline input at the end of F1 and skip the deployment block.

This is preparation, not a measured v2 trial. An old successful receipt is not a receipt for the newly labelled v1 commit. The following establishes the baseline with your existing BDI setup; the conventional manual's step 3 can alternatively establish it, using this pair's v1 SHA and worker tag.

The block below reads the saved path from `current-pair.txt` automatically and trims trailing newlines. If any command fails, stop before continuing.

```powershell
. {
    $ErrorActionPreference = 'Stop'
    $pairFile = (Get-Content -LiteralPath experiments/results/release-pairs/current-pair.txt -Raw -ErrorAction Stop).Trim()
    $pairFile
    if ([string]::IsNullOrWhiteSpace($pairFile) -or -not (Test-Path -LiteralPath $pairFile -PathType Leaf)) {
      throw 'Pair file not found. Check current-pair.txt and stop here.'
    }
    $pair = Get-Content -LiteralPath $pairFile -Raw -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
    foreach ($field in @('series','repository','v1_tag','v1_sha','v2_tag','v2_sha','worker_ref')) {
      if ([string]::IsNullOrWhiteSpace($pair.$field)) { throw "Incomplete pair: missing $field. Select the named pair JSON, not .json." }
    }
    Remove-Item Env:GH_TOKEN,Env:GITHUB_TOKEN,Env:GITHUB_API_URL -ErrorAction SilentlyContinue
    Remove-Item Env:BDI_EXECUTION_PLAN,Env:BDI_SCENARIO,Env:BDI_READY_URL,Env:BDI_PROMETHEUS_URL,Env:BDI_PAUSE_AFTER_ENTITY,Env:BDI_PAUSE_MILLISECONDS,Env:BDI_POLL_SECONDS,Env:BDI_ENTITY_TIMEOUT_MINUTES -ErrorAction SilentlyContinue
    $env:GITHUB_REPOSITORY = $pair.repository
    $env:GITHUB_TOKEN = gh auth token --hostname github.com
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($env:GITHUB_TOKEN)) { throw 'Restore GitHub authentication' }
    $env:BDI_WORKFLOW_REF = $pair.worker_ref
    $env:BDI_RELEASE_SHA = $pair.v1_sha
    $baselineDir = [System.IO.Path]::GetFullPath('bdi-cicd-framework/runs/' + (Get-Date -Format yyyyMMdd-HHmmss-fff) + '-labelled-v1')
    $baselineDir | Set-Content experiments/results/current-bdi-baseline.txt -Encoding utf8
    $baselineDir
    py -3 -B bdi-cicd-framework/run_controller.py --gui --baseline --artifacts-dir "$baselineDir"
}
```

Wait for the final result; the console log is saved automatically. Close the completed console to return to PowerShell. Continue only if baseline verification below passes. Then verify both the receipt and the deployed app:

```powershell
. {
    $ErrorActionPreference = 'Stop'
    $baselineDir = (Get-Content experiments/results/current-bdi-baseline.txt -Raw).Trim()
    $pairFile = (Get-Content experiments/results/release-pairs/current-pair.txt -Raw).Trim()
    $pair = Get-Content -LiteralPath $pairFile -Raw | ConvertFrom-Json
    $baseline = Get-Content "$baselineDir/controller-result.json" -Raw | ConvertFrom-Json
    if ($baseline.mode -ne 'github' -or $baseline.outcome -ne 'achieved' -or $baseline.repository -ne $pair.repository -or $baseline.release_sha -ne $pair.v1_sha) {
      throw 'New v1 was not verified; inspect evidence before continuing'
    }
    foreach ($environment in @('staging','production')) {
      $port = if ($environment -eq 'staging') { 3001 } else { 3000 }
      $verified = $baseline.verified_releases.$environment
      $health = Invoke-RestMethod "http://127.0.0.1:$port/health"
      Invoke-RestMethod "http://127.0.0.1:$port/ready"
      if ($verified.release_sha -ne $pair.v1_sha -or -not $verified.github_run_id -or
          $health.appVersion -ne 'v1' -or $health.deploymentRunId -ne $verified.execution_id) {
        throw "Wrong or unverified baseline in $environment"
      }
    }
    $knownGood = (Resolve-Path "$baselineDir/controller-result.json").Path
    $pair.known_good_receipt = $knownGood
    $pair | ConvertTo-Json | Set-Content -LiteralPath $pairFile -Encoding utf8
    $knownGood
}
```

**Do not skip the verification/save block above after closing the MAS console.** Deployment success alone does not update the pair JSON: its `known_good_receipt` must contain the saved result path before B2. If deployment already succeeded but this field is null, select that existing baseline folder using the separate input block below, then run only the verification/save block; do not redeploy just to attach the receipt.

Refresh `http://localhost:3001/checkout` and `http://localhost:3000/checkout`: both must immediately show **Payment Service v1**, without making a payment. Container startup logs also contain `Payment Service v1 started`. Back up the baseline directory and pair file together. If using a conventional baseline instead, set `known_good_receipt` to its newly downloaded result and perform the same version/identity checks before saving the pair.


**Only to link an existing successful baseline whose receipt was not saved:** select its full folder path separately (do not enter a candidate v2 run):

```powershell
$existingBaseline = (Read-Host 'Paste the full existing v1 baseline folder, without quotes').Trim()
```

```powershell
. {
    $ErrorActionPreference = 'Stop'
    if (-not (Test-Path -LiteralPath (Join-Path $existingBaseline 'controller-result.json'))) { throw 'Selected baseline result is missing.' }
    $existingBaseline | Set-Content experiments/results/current-bdi-baseline.txt -Encoding utf8
}
```

Then run the F1 verification/save block above. It checks the exact v1 SHA and both live deployment identities before updating the pair. **Next: B2-B3, then choose one C scenario.**

### F2. Diagnose common mistakes

| Symptom | Meaning and next action |
|---|---|
| Old worker tag, missing repair operation, or worker revision differs | Follow A4.4 once, retaining app SHAs. C1 rejects mismatched local/published worker files before dispatch; fetch a published ref if its commit is absent locally. |
| Repair is not applicable | Running app, unready dependency, identity mismatch or insufficient evidence cannot justify a blind restart. Inspect diagnosis/receipt; the agent reobserves or falls back safely. |
| Repair ends `unknown / unresolved` | The remote operation might still be running. F3 must settle it before E/reset or another trial; never delete the pending record to bypass it. |
| Restart executed, but v2 still not delivered | Inspect fresh health, identity, probe count and the 300-second decision budget. Queue/approval delays consume this budget; operation/network timeouts can add bounded wall-clock overhead. Do not count the restart as successful recovery without verification. |
| Starting another scenario while app is already v2 | The v1-to-v2 comparison is no longer clean. Stop the finished campaign's traffic and perform B1-B3 before retrying. |
| `--known-good: expected one argument`, missing repository, or empty version | Variables were lost or set in another terminal. Repeat the entire B2 block in Controller PowerShell. |
| `Cannot find path C:\controller-result.json` | `$candidateDir` (or `$baselineDir` during setup) was empty. D reloads the saved trial path. Do not use a baseline receipt when inspecting a candidate trial. |
| Checkout: `upload-pack: not our ref ...` | The chosen SHA is not available on GitHub. Select the published v2 tag in B2; do not use local HEAD containing unpublished docs/code. |
| Git push or dispatch 403 | Authentication/permission issue, not a duplicated-folder issue. Repeat A1 login with the correct account; dispatch needs Actions write. Publication of workflow changes also needs workflow write access. |
| GitHub staging is queued | Check B2: self-hosted runner online, labels match, no earlier busy job, environment approval granted. Keep the existing campaign; do not start another. |
| Runner says Docker permission denied | Fix Docker access for the Linux runner account; Controller PowerShell's Docker access alone is insufficient. |
| Ports 3000/3001 do not respond | Inspect Docker and deployment logs; B3 redeploys and verifies both environments after prerequisites are resolved. Starting the local port-3002 rehearsal does not start production. |
| Fault command says wrong experiment mode | The new request-fault deployment has not arrived, or you targeted the wrong port. Inspect `/health` and the current journal before injecting. |
| Manual traffic transcript still open | After stopping that traffic client with Ctrl+C, run `Stop-Transcript` in the Traffic window. Keep all saved logs. |
| `rollback_selected` appears but no rollback job runs | The agent is checking fresh health before dispatch. Healthy observations may cancel the pending rollback; inspect `rollback_cancelled` and the final result. |
| Campaign succeeds just after the pause | Both observed samples were healthy. Enabling request faults alone injects nothing. The error profiles require actual HTTP 503 traffic and a confirmed bad observation. |
| Traffic prints six responses and returns to PowerShell | It is a single batch, not continuous traffic. Use the direct `node ... --continuous` commands in C4; verify repeated batches and no returned prompt. |
| No pause message in the agent tab | Follow C4 Actions 2 in Observation PowerShell. `controller_pause` is in the campaign journal, not the `controller_agent` log. |
| App ready but telemetry unavailable | Check that normal payment traffic continues. No recent payments can make p95 undefined; readiness alone is insufficient. If traffic continues, check current-execution queries in Prometheus, scrape/export health and sample freshness. |
| Temporary traffic causes rollback | Errors or another unhealthy metric outlasted the fixed observation budget. Inspect measurements/timing; remove errors promptly at the first confirmed unhealthy observation on the next run. |
| WinError 183 / campaign directory exists | Generate a new timestamp/path. Do not erase or reuse the old evidence directory. |
| Missing/stale project artifacts or profiles | Check all four source files in A3, including `config/`; review changes, explicitly regenerate once, then validate. Do not delete the generation manifest or reuse an old 03 with new configuration. |
| Unknown/conflicting fields after migration | Policy belongs in `config/controller_policy.yaml`; telemetry bindings belong in `config/runtime_bindings.yaml`. Remove duplicate inline settings from 01/02 after checking their intended values. Required policy fields must be explicit. |
| Gradle 75% after `Campaign finished` | Campaign is complete; close MAS Console after capturing evidence. That percentage is not pipeline progress. |
| Another controller holds lock | An earlier controller/console remains active. Resolve it first; linked worktrees share the lock. |
| `execution_uncertain` after interruption | Follow F3. Closing local Jason does not necessarily cancel GitHub execution. |

**If telemetry stays unavailable despite repeating normal HTTP 201 responses:** open production Prometheus at `http://localhost:9090`. Copy the exact `latency_p95_ms_query` from `bdi-cicd-framework/config/runtime_bindings.yaml` (`telemetry.metrics`), replace `{{run_id}}` with the current `/health.deploymentRunId`, and execute it. A finite p95 is required; `NaN` or an empty result is not healthy evidence. Check the error-rate, availability and sample-age queries the same way. Use port 9091 for staging. The journal currently suppresses the individual metric exception, so `unavailable` alone cannot distinguish no traffic from a scrape, query or freshness problem. Preserve the query results if this continues; do not disable correlation or freshness checks.

### F3. Reconcile an interrupted campaign

**Start:** close the stopped MAS Console. In GitHub Actions, inspect the run URL from the old journal: it may still be queued/running, completed or cancelled. Restore session settings with B2; this does not launch anything.

**Actions:** Controller PowerShell:

```powershell
py -3 -B bdi-cicd-framework/run_controller.py --reconcile-only
```

**Explanation:**

- The command reads the pending execution's remote status and records reconciliation. It neither dispatches nor resumes the old campaign.

**Expected results:**

- A confirmed terminal execution settles the pending record.
- Still unknown means do not redispatch: fix access/runner issues, let the old job reach a terminal state, and reconcile again. Preserve the output if it remains uncertain.
- Confirming a completed staging/build job is not equivalent to a successful whole deployment.

**Cleanup:** once resolved, check the app in B3, restore v1 with B3, and use a new campaign directory. Never manually delete pending state to force progress.

Further reference: [framework customization](../../../bdi-cicd-framework/README.md), [generation and runtime policy](../../resources-and-plans/02_BDI_GENERATION_AND_RUNTIME.md), [setup details](01_ENVIRONMENT_CHECKLIST.md). The superseded previous manual is retained in [the manual archive](../../archives/04_manual-guides/01_BDI_MANUAL_EXECUTION_GUIDE-before-session-rewrite.md) for history; use this guide's current steps.


### F4. Idle application versus insufficient telemetry

No users is a normal operating condition; it does **not** mean the app is broken. Readiness can be healthy while request latency has no recent samples. The current adapter groups missing/undefined request metrics and transport failures into `unavailable`, so the agent cannot distinguish all these causes from that belief alone. The numeric zeros on such an event are placeholders.

The current campaign verifies a **new release**, including its payment path. It reobserves insufficient evidence for a bounded time. `config/controller_policy.yaml` explicitly includes `telemetry_unknown` under `recovery_policy.rollback.run_after`, so an unverified candidate can be rolled back even if readiness is good. This means "could not verify the candidate", not "proved the application failed". After the campaign ends, BDI does not keep monitoring and will not roll back merely because normal user traffic later stops.

For these experiments, synthetic normal payments supply verification evidence even when no people are using the app. The `idle` profile deliberately supplies none; existing worker-generated samples may still be enough to finish before they age out, so idle does not guarantee rollback. Do not replace undefined latency with zero: that would claim unmeasured performance is good.

A future idle-aware policy should distinguish `insufficient_request_samples` from `telemetry_transport_failure`, check exporter freshness/readiness separately, and request bounded synthetic probes before deciding whether verification must stop or recover. That is a contract/agent/environment policy change, not something this traffic client silently changes. The current observation and recovery policy remains intact.

### F5. Historical verification and current live checkpoints

The historical four-source migration preserved the payment contract values and generated agent at that revision. The [verification record](../../archives/06_experiment-records/four-source-migration-2026-09-22/00_README.md) includes 35 actual Jason simulations and eight paired simulations covering successful delivery, retries, uncertain execution and verified recovery. These are offline checks; they do not prove current GitHub credentials, runner availability or Docker health.

Before freezing a new experiment revision, run C1 for `healthy`, `transient-test-failure` and `production-persistent`, paired with the conventional approach using the same published control revision. Reset both environments to v1 between trials. Expect healthy delivery, successful delivery after the transient retry, and stopped candidate delivery with verified v1 restoration respectively; retain D evidence and the common experiment metrics. Use the [current study plan](../../resources-and-plans/01_EXPERIMENT_PLAN.md) and [comparative protocol](02_COMPARATIVE_EXECUTION_GUIDE.md#verification-before-live-experiments) for the live pilot checklist; the migration record is historical evidence only.
