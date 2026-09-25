# Conventional local pipeline

Baseline: `05a2c6db7a3e926c9142a635f42f7af0f078c81d` (2026-09-25 inspection).
The original supplied checkout used `id-nynt/memos-experiment`; this conventional
repository now uses `id-nynt/memos-current-experiment`. "Upstream" below means the
existing files at that baseline. The original design is retained below, with the
current experiment-specific adaptation documented here.

## Frozen experiment upgrade baseline (2026-09-25)

The first GitHub S0 failed after building the smoke candidate because this dedicated
repository has no ancestral stable-release tags. The upstream smoke script normally
uses those tags to select a previous image. Its applicable upstream baseline is
`v0.31.0` (`2b2192d4e153bd04f1d325b60fd880cf00d68b01`), mapped to
`neosmemo/memos:0.31.0`. Publishing that tag could trigger its historical Release
workflow, so the experiment instead supplies the script's existing environment
override explicitly.

- **UPSTREAM MINIMALLY ADAPTED:** `.github/workflows/upgrade-smoke.yml` adds optional
  reusable-workflow input `previous_image` (default empty), wired only to
  `MEMOS_SMOKE_PREVIOUS_IMAGE` on the existing release-smoke step. All jobs, checks,
  commands, dependencies, timeouts and normal tag-discovery behavior remain intact.
- **NEW LOCAL CD:** `.github/workflows/frozen-cd.yml` supplies
  `previous_image: neosmemo/memos:0.31.0` for the experiment's upgrade call only.
- **UPSTREAM UNCHANGED by this fix:** backend/frontend/proto checks, the smoke and
  release-version scripts, Dockerfile, `release.yml`, and every other upstream job.

An empty override continues to invoke upstream tag discovery. Release, PR, manual
upgrade-smoke and ordinary local-CD callers do not supply the new input. No tag is
created/pushed and no Release workflow setting is changed. This is baseline-input
wiring, not a change to conventional gating, retry, health or recovery policy.
The smoke job still builds/tests its candidate image; deployment still promotes
the separately frozen immutable experiment image through staging and production.

Change log: 2026-09-25 — explicit experiment-only previous-image input replaces the
unavailable tag-discovery input; no smoke test is skipped or weakened. New healthy
S0 validation is authorized once, with S1-S5 remaining disabled.

## Original pipeline and provenance

This table records the original upstream structure; the current minimal adaptation
to `upgrade-smoke.yml` is classified above.

| Workflow | Trigger | Jobs and dependencies |
| --- | --- | --- |
| `backend-tests.yml` | Main pushes; Go-related PRs | Independent `static-checks` and `tests` matrix: store/server/internal/other |
| `frontend-tests.yml` | Main pushes; web PRs | Independent `lint` (also unit tests) and `build` |
| `proto-linter.yml` | Main pushes; proto PRs | `lint`: lint and format |
| `upgrade-smoke.yml` | Relevant PRs, dispatch, reusable call | Independent `migration-upgrade` matrix (SQLite/MySQL/PostgreSQL), `release-smoke`, `entrypoint` |
| `build-canary-image.yml` | Main pushes | `build-frontend` -> `build-push` (amd64/arm64) -> `merge` |
| `release.yml` | Calendar tags; dispatch | `prepare` + reusable `upgrade-smoke` -> `build-frontend`; then `build-binaries` -> `checksums` -> `release`, and `build-push` -> `merge-images` |
| `demo-deploy.yml` | Dispatch | `deploy-demo`: Render hook, no application verification |
| `stale.yml` | Daily; dispatch | `stale`: issue/PR maintenance |

Release jobs also depend on `prepare` for version metadata. Dispatch skips public
release/image publication. Canary publication is independent of the CI workflows;
release publication gates on upgrade smoke, not the backend/frontend/proto trio.
The existing Compose example runs one mutable `stable` image on port 5230.

## Final pipeline

```text
Existing Backend Tests + Frontend Tests + Proto Linter (exact main SHA)
  -> NEW ci-gate: require every workflow and job to succeed
  -> NEW upgrade-smoke caller -> UNCHANGED upstream upgrade-smoke jobs
  -> NEW deploy-local (one Windows self-hosted runner / Docker daemon):
       preflight -> pnpm release -> reject superseded main SHA
       -> build immutable image ID -> staging -> fixed verification
       -> stop production + back up full data volume
       -> production using SAME image ID -> fixed verification
       -> accepted release record / success
```

All original triggers, jobs, checks, and publishing destinations remain unchanged.
The experiment-only input adaptation is documented above. Local CD neither waits for nor
uses the public canary/release publishers, so it needs no Docker Hub credentials.

| New file | Classification / reason |
| --- | --- |
| `.github/workflows/local-cd.yml` | **NEW LOCAL CD**: `ci-gate`, `upgrade-smoke` caller, `deploy-local`; connects exact-SHA checks to local delivery |
| `scripts/local-cd/compose.yaml` | **NEW LOCAL CD**: isolated persistent environments using an immutable local image ID |
| `scripts/local-cd/deploy.ps1` | **NEW LOCAL CD**: preflight, build, deployment, fixed probes, backup, diagnostics, release records |
| `.github/CONVENTIONAL_PIPELINE_DESIGN.md` | **NEW LOCAL CD**: provenance, operating instructions, policy history |

The existing Dockerfile requires frontend release assets before building. The
script archives the exact Git commit into a temporary build context with
command-scoped `core.autocrlf=false` / `core.eol=lf`, preserving LF shell entrypoints
on Windows and excluding untracked files, then adds the
generated SPA assets. The context is removed after the build. Build
arguments set `VERSION=local-<full SHA>` and `COMMIT=<full SHA>`; an OCI revision
label and unique retention tag are also set. Deployment uses the resulting
`sha256:` image ID with pulling/building disabled, not the tag. Both environments
use SQLite, separate Compose project networks/containers, and separate
`<project>_data` named volumes. Defaults:

| Environment | Project | Host URL |
| --- | --- | --- |
| Staging | `memos-local-staging` | `http://127.0.0.1:5231` |
| Production | `memos-local-production` | `http://127.0.0.1:5232` |

No test accounts or memos are created in these persistent environments. Complete
first-user setup through each UI. Upstream smoke tests exercise writes/restarts
and migrations in disposable instances. Staging data is independent of production;
staging verification is not a rehearsal on a copy of production's database.

## Fixed policy

- Main pushes and manual dispatch on `main` only. Manual runs use the dispatch
  SHA, not an arbitrary input ref. Required runs must be same-repository `push`
  runs on `main` for that exact SHA; newest matching runs and latest job attempts
  must all succeed. Skipped/failed/cancelled checks are not accepted.
- CI polls every 20 seconds for at most 30 minutes; gate job timeout is 35 minutes.
  API errors fail the gate. No replacement tests or inferred CI success.
- Upgrade smoke is called from the same commit and retains all upstream timeouts
  and concurrency. Deployment requires that entire reusable workflow to succeed.
- Local job timeout: 60 minutes including frontend build. Before image build,
  check the SHA is still the main tip. A newer push after this check does not
  interrupt the running deployment. Workflow concurrency disables cancellation;
  an exclusive state-directory file lock also prevents concurrent script runs.
- Each environment has a 180-second verification deadline, 3-second retry delay,
  and 5-second HTTP request timeout. An in-flight probe may finish after the
  deadline. Each attempt checks running container and exact image ID, `/healthz`,
  database-backed `/api/v1/instance/profile` with exact commit/version, frontend
  root and same-origin JavaScript asset, and no restart during that attempt.
- Build, Compose operations, and backup run once and fail on errors. Compose
  uses `restart: unless-stopped`; readiness retries do not change deployment policy.
  Production stop grace period is 30 seconds. Updates entail brief downtime.
- Back up the complete existing production volume after stopping its container,
  including SQLite and uploaded files. Verify archive readability and record its
  SHA-256. A fresh deployment without a volume has nothing to back up.
- Production failure remains failed. Preserve backup, previous image, release
  record, and diagnostic logs; no automatic rollback or later reconsideration.
  A backup failure leaves production stopped for manual inspection. A failed
  candidate may remain running; an operator must decide recovery.
- Keep release directories and images until explicitly cleaned up by the operator.
  `accepted.json` changes only after both environments pass. Per-attempt records
  retain the prior accepted identity, actual previous image, backup path/checksum,
  commit/image/version, ports, timestamps, and GitHub run/attempt when available.
  GitHub artifacts retain reports/logs for 14 days, never database backups.

`/healthz` is only an HTTP availability check. The profile endpoint performs
database reads and exposes the compiled identity. Migrations run before HTTP
startup and reject database downgrades. Consequently image-only rollback is unsafe.

## Runner setup and operation

1. Register a dedicated Windows self-hosted runner on this repository with custom
   label `memos-local`. Use a trusted account with FullLanguage Windows PowerShell
   5.1+, Git, Windows `tar`, Docker CLI/Compose v2/Buildx, and access to Docker Desktop's running
   Linux-container engine. The same daemon must remain available across releases.
   Do not route untrusted PR execution to this machine.
2. Enable GitHub Actions and the unchanged upstream checks. Push the committed
   additions to `main`; local CD requires successful push CI for that SHA. Existing
   public publishers still require their original secrets, independently of CD.
3. Optional repository variables: `LOCAL_CD_STATE_DIRECTORY` (absolute directory
   outside the checkout), `LOCAL_CD_STAGING_PORT`, `LOCAL_CD_PRODUCTION_PORT`.
   Default state is `<runner USERPROFILE>/.memos-local-cd`. Give the runner write
   access and Docker access to this directory for backup mounts. Keep it private.
   Use one consistent directory/account for every deployment. Ports must be free
   or already owned by the matching managed environment.
4. The workflow installs Node 24 and pnpm 11.0.1. Internet access is needed for
   Actions, dependencies, base images, and upstream smoke-test images. No paid
   deployment hosting or registry publication is required.

Local preflight (does not build/start/stop anything):

```powershell
$sha = git rev-parse HEAD
./scripts/local-cd/deploy.ps1 -Commit $sha -CheckOnly
```

For a local operator test, build frontend assets with `pnpm install --frozen-lockfile`
and `pnpm release` in `web`, then invoke the script without `-CheckOnly`. This
executes deployment but **does not claim to have passed the GitHub CI gate**. Use
the workflow for CI-gated releases. Do not use `docker compose down --volumes` on
these projects. Probe either instance independently using its `/healthz` and
`/api/v1/instance/profile` URLs.

### Manual recovery

Stop further workflow runs before recovery. Read the failed attempt's local
`release.json`. Verify the backup checksum before using it. Preserve the failed
volume; restore into a new recovery volume, so recovery does not delete data:

```powershell
$record = Get-Content 'C:/path/to/failed-release/release.json' -Raw | ConvertFrom-Json
if (!$record.productionBackup -or !$record.previousImage) { throw 'No complete previous image/data recovery pair' }
if ((Get-FileHash $record.productionBackup.path -Algorithm SHA256).Hash -ne $record.productionBackup.sha256) { throw 'Backup checksum mismatch' }
$compose = 'scripts/local-cd/compose.yaml'
$env:MEMOS_IMAGE = $record.previousImage
$env:MEMOS_HOST_PORT = [string]$record.productionPort
docker compose -f $compose -p memos-local-production stop
if ($LASTEXITCODE) { throw 'Stop failed' }
$recoveryVolume = 'memos-local-recovery-' + (Get-Date -Format yyyyMMddHHmmss)
docker volume create $recoveryVolume
if ($LASTEXITCODE) { throw 'Volume creation failed' }
$backupDirectory = Split-Path $record.productionBackup.path
docker run --rm --network none --user 0 --entrypoint /bin/sh --mount "type=volume,source=$recoveryVolume,target=/restore" --mount "type=bind,source=$backupDirectory,target=/backup,readonly" $record.previousImage -ec 'tar -xzf /backup/data.tar.gz -C /restore'
if ($LASTEXITCODE) { throw 'Restore failed' }
docker run -d --name $recoveryVolume --restart unless-stopped -p "127.0.0.1:$($record.productionPort):5230" --mount "type=volume,source=$recoveryVolume,target=/var/opt/memos" -e MEMOS_DRIVER=sqlite -e "MEMOS_INSTANCE_URL=http://127.0.0.1:$($record.productionPort)" $record.previousImage
if ($LASTEXITCODE) { throw 'Recovery start failed' }
Invoke-RestMethod "http://127.0.0.1:$($record.productionPort)/api/v1/instance/profile"
```

Check health, previous release identity, and application data manually. Recovery
uses a separate container/volume intentionally; local CD will reject its occupied
port until the operator reconciles the recovered data with the managed production
volume. Do not resume CD against the failed migrated volume. Backups represent
predeployment data; restoring one does not retain subsequent writes.

## Old versus new conventional design

The previous experiment-built conventional controller contained adaptive
production monitoring and rollback reconsideration designed to provide capabilities
comparable with BDI (historical context supplied by the user). This clean baseline
is designed independently from upstream Memos and normal local CD requirements.
No BDI repository or controller logic is used. There is no adaptive monitoring,
belief/state reasoning, delayed rollback decision, or background decision service.
Every candidate follows the same ordered pass/fail checks.

## Validation and change log

- 2026-09-25: Initial baseline. Added exact-SHA CI gate, unchanged reusable upgrade
  smoke, one local image, isolated staging/production, fixed verification, stopped
  data backup, and manual recovery. No upstream files modified.
- 2026-09-25: Validation fixes: allow generated frontend placeholder replacement;
  archive source with command-scoped LF settings for Windows; recognize configured
  port reservations while managed containers restart. Persist previous-image
  identity before stopping production. These do not introduce recovery decisions.

Validation completed locally:

- actionlint 1.7.7 passed with `memos-local` declared as a custom runner label in
  a temporary lint configuration. PowerShell AST parsing, both Compose project
  configurations, new-file whitespace checks, and `git diff --check` passed.
- Eleven tests against the workflow's actual gate script passed: success,
  pending-to-success, missing run, wrong SHA/repository, failed/cancelled run,
  skipped/empty jobs, newest-run precedence, and API error. These used mocked
  GitHub responses and an accelerated clock, not claimed upstream CI executions.
- Preflight rejected wrong SHA, equal ports, occupied default port, and backup
  storage inside the checkout. Distinct Compose networks/volumes were verified.
- Docker Desktop Linux/amd64, Compose 2.39.2, Buildx 0.27.0, Windows PowerShell 5.1,
  Node 24.21.0, pnpm 11.0.1, and Windows tar were available. Docker required normal
  host access outside the agent sandbox. Locked install and `pnpm release` passed;
  the unchanged frontend emitted CSS/chunk-size warnings.
- An initial CRLF startup failure reached the fixed staging deadline, wrote
  diagnostics, and did not deploy production. The corrected exact-commit archive
  was separately checked to contain an LF entrypoint.
- A fresh healthy deployment and a repeat deployment passed on **5241 / 5242**
  (default production port 5232 was occupied). HTTP/API/SPA probes passed for both;
  container IDs referenced the same immutable image, with separate data volumes.
  The repeat run stopped production, created/read-checked its backup, verified
  the archive contains `memos_prod.db`, matched its checksum, and accepted the
  replacement. Release history and diagnostic/report files were verified.
- Latest tested image:
  `sha256:749f31960692e1c66d401cdf749c8e26f80da70d13cc1585cd56efbae2963f8f`.
  Record/backup: `<USERPROFILE>/.memos-local-cd/releases/20260925T053035204Z-fad5844e/`.
  The tested application commit is the baseline SHA above; the new CD files were
  uncommitted during this local operator test. Generated tracked HTML was restored.
- GitHub reports **zero registered repository runners**. A complete Actions run
  (including real upstream CI and reusable upgrade smoke) remains pending: commit
  and push these additions, register the runner, set port variables to 5241/5242
  to continue these instances, and use the same persistent state directory.
  No full upstream test suite or destructive production recovery was run locally.
