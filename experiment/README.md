# Conventional experiment

This directory owns execution for `id-nynt/memos-current-experiment`. Run commands
from the repository root on Windows. Only this repository, installed tools, Docker
and this repository's GitHub API are used. No parent-folder tooling is required.

## Setup

Install Python 3.11+, Git, authenticated GitHub CLI, and Docker Desktop with its
Linux/amd64 engine. PowerShell must permit FullLanguage execution. Keep the runner
account signed in and Docker Desktop running.

```powershell
./experiment/setup.ps1 -InstallRunner
./experiment/run.ps1 check
```

Setup creates `experiment/.venv` (standard library only), verifies/installs the
checksum-verified official Windows runner, and registers a hidden sign-in task
`MemosCurrentActionsRunner`, label `memos-local`. It refuses a foreign/busy runner.
No Windows password is stored. Use `-Python C:/path/to/python.exe` if needed.

Frozen source tags and image IDs are pinned in
[frozen-releases.json](../scripts/local-cd/frozen-releases.json). A rebuilt image
with a different ID is not a substitute. Transfer exact images independently:

```powershell
# Once on a machine that has the frozen images:
./experiment/run.ps1 images export "$env:LOCALAPPDATA/memos-current-experiment/images"
# On another machine, supply that bundle as a read-only input:
./experiment/run.ps1 images import C:/frozen-images
```

Archive checksums, image IDs, source trees, platform and release labels are checked.
Keep the application-only image bundle with the experiment; a fresh host needs it.
Setup never publishes credentials or data archives.

## Ownership

| Resource | Conventional owner |
| --- | --- |
| Endpoints | staging `127.0.0.1:5541`, production `127.0.0.1:5542` |
| Compose projects/networks | `memos-current-experiment-staging`, `memos-current-experiment-production` |
| Containers / volumes | project plus `-memos-1` / `_data` |
| Private state | `%LOCALAPPDATA%/memos-current-experiment/` |
| Locks | private `experiment.lock` (harness), `deployment.lock` (deployment/reset) |
| Raw evidence | `experiment/results/<unique-trial>/` (Git-ignored) |
| Runner | `%USERPROFILE%/actions-runner-memos-current/` |

Private state contains credentials, stopped seed, backups, accepted receipts, image
bundles and reset history. Setup restricts its Windows ACL to the account and SYSTEM.
Never publish it. Historical deployments are not adopted. Reset checks resource
ownership and never invokes Docker prune. `config.json` owns the namespace.

## Initialize, run, verify

Use a clean committed control checkout:

```powershell
./experiment/run.ps1 init
./experiment/run.ps1 run --release v2 --scenario S0 --mode rehearsal --trial pilot-001 --no-interventions
./experiment/run.ps1 verify
```

`init` refuses existing volumes/state, creates an account/PAT/private sentinel via
the Memos API, stops v1 for a consistent seed and loads the same seed and credentials
into both environments. It then deploys/verifies v1 and records the baseline.
One candidate attempt consumes the baseline; reset before another attempt.

`rehearsal` measures local deployment only. For actual upstream quality gates,
upgrade smoke and deployment, publish the new control revision to this repo's
`main`, then run:

```powershell
./experiment/run.ps1 reset
./experiment/run.ps1 run --release v2 --scenario S0 --mode github --trial S0-001 --no-interventions
```

Use `--no-interventions` only to attest no manual rescue occurred; otherwise that
field remains unknown. `--release v1` also deploys the frozen baseline. `verify`
checks both live containers, image/SHA/VERSION, URL, health and sentinel; it does
not trust only `accepted.json`. Healthy v1 is not v2 delivery.

GitHub runs correlate exact unique title and control SHA. All job attempts, logs,
artifacts and run IDs are retained. Passive health sampling continues 600 seconds
after completion; a separate client sends one sentinel request per second without
overlap (3-second timeout). Native decisions never consume these observations.
The remote observation cap is 120 minutes; unresolved work is recorded, not silently
cancelled. Rehearsals omit extended follow-up and are not full-pipeline measurements.

## Scenarios and unchanged policy

`scenarios.json` is the fail-closed allowlist. S0 is enabled. Implemented S1/S2
fixtures remain disabled pending approval of the proposed scenarios:

- S1: deterministic extra CI failure after successful upstream backend/frontend/
  proto jobs, before upgrade/deployment eligibility. GitHub mode only.
- S2: deterministic failure immediately before the first staging Docker mutation.
  Production is untouched; every attempt fails at that boundary.
- S3/S4/S5: disabled; their prescribed HTTP 503 injector and neutral production
  readiness boundary are not installed. Container stops/sleeps are not substitutes.

Once explicitly enabled in an approved revision, select `--scenario S1` or `S2`.
A scenario label never fabricates exposure evidence. No runtime-fault trial is
claimed executable. The local protocol still labels these conditions as proposals.

The conventional controller retains 180-second verification, 3-second rechecks,
5-second HTTP timeouts, staging-first ordering, stopped production backup, same-image
promotion and manual recovery. No retry, rollback or reconsideration policy is added.

## Reset and evidence

```powershell
./experiment/run.ps1 reset
```

Reset is explicit preparation, never automatic recovery. It refuses outstanding
remote deployment work, takes local locks, validates seed checksum and volume/
container ownership, stops both environments, archives both current data sets,
restores the seed, deploys v1 and verifies both. Failure retains backups/seed for
inspection. Private `resets/` records preparation; prior evidence is not overwritten.

Results include controller SHA plus harness hashes in `manifest.json`, launch/native
events, observations, workload, common-contract measurements, separate endpoint
evaluation, correlated GitHub metadata/artifacts/logs and `hashes.json`. Explicit
copy allowlists exclude credentials and database archives. Review application logs
before publication. Missing evidence stays null. The repository-owned
[contract](../scripts/experiment-measurement/contract.json) preserves terminal-health
definitions separately from post-terminal endpoint observations.

## Changes and validation

2026-09-25: added owned setup, seed/reset, image transport, evidence and namespace.
Only the local `frozen-cd.yml` orchestration and opt-in `deploy.ps1 -Experiment`
configuration/fixture boundary are adapted. Upstream CI and ordinary local CD are
unchanged. Policy baseline: `7c6312c1950999ce875b3aa88174fdb03f3478c1`; each run
records its actual new control SHA/hashes. Application v1/v2 remain unchanged.

Tests: `experiment/.venv/Scripts/python.exe -m unittest discover -s experiment -p 'test_*.py' -v`.
See [VALIDATION.md](VALIDATION.md) for actual results and remaining limitations.
