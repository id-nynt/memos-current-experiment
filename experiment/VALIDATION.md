# Validation record

## External fixture setup — 2026-09-25 (no trials executed)

- 27 unit tests passed: frozen controller hashes, existing ownership protections,
  route/release scope, exact schedule boundaries, mocked HTTP 503 and v1 forwarding,
  credential-safe receipts, Docker adapter passthrough/failure and stale observer,
  duplicate trial/path protection. These tests do not activate live scenarios.
- Python compilation, actionlint, PowerShell AST, read-only Compose expansion and
  Windows PowerShell → Docker adapter → real `docker version` passed. The adapter
  receipt is `results/fixture-setup-validation-20260925/adapter-readonly.json`.
- Docker Linux/amd64, Compose 2.39.2, exact frozen v1/v2 images and online/idle
  dedicated runner verified without deployment/reset. The override changes only
  the production host port to 5543; instance URL remains public port 5542.
- Deployment policy/config and upstream CI match validated S0 revision
  `67c4731e67ee1ff0a8cc8d3cbfd7459a23ffe667`; frozen checks enforce this identity.
- Protected S0 `S0-github-validation-20260925-002`: all 175 inventory hashes verified;
  its directory was not changed. No S1–S5 or new S0 execution occurred.
- Before execution, commit/publish the harness and configure `MEMOS_EXPERIMENT_ROOT`
  as described in [EXPERIMENT_GUIDE.md](EXPERIMENT_GUIDE.md). Static readiness is not
  a claim that fault trials have passed end to end.

## Historical validation records

Validated on Windows/Docker Desktop, 2026-09-25:

- 11 ownership, identity, disabled-scenario and policy-regression tests passed.
- PowerShell AST parsing, Python compilation, actionlint and `git diff --check` passed.
- Exact source trees and immutable linux/amd64 images for v1/v2 passed verification.
  Owned image bundles were exported with checksum receipts under private `images/`.
- Runner `memos-current-windows` was reconfigured to the repository-owned Python
  environment and verified online. No parent virtual environment remains required.
- Fresh conventional-only initialization passed on ports 5541/5542. Both environments
  use the same stopped v1 seed and sentinel credentials, with separate data volumes.
- Healthy v2 rehearsal `standalone-S0-validation-001` passed at control
  `a37062400f82f9091ac1e9ab2a341c14b50b2bf4`: candidate delivered, final health true,
  native retry count 0, reobservations 1, no recovery selection/execution. Measured
  pipeline duration was approximately 20.9 seconds. These are technical validation
  results, not comparative experiment findings.
- Raw observations, workload, native events/receipts and common measurements were
  saved under `experiment/results/standalone-S0-validation-001/`. The file-hash
  inventory passed; private PAT values were absent from the evidence.
- Explicit reset archived both prior data volumes, restored the original seed,
  deployed v1 and verified both environments. Final state: healthy v1 on both ports.
- Upstream backend/frontend/proto/upgrade workflows and ordinary `local-cd.yml` have
  no diff from the prior control. The complete native readiness routine is unchanged.

Later evidence-only corrections distinguish GitHub native completion from collection
completion and require final-window coverage before assigning endpoint health. They
do not change native deployment decisions. Each subsequent run records its actual
control SHA and file hashes; the old control tag was not moved.

Not claimed: real upstream CI execution, a complete GitHub-backed trial, or runtime
fault exposure. S1/S2 activation awaits explicit approval; S3-S5 require a separately
approved route injector/readiness hook. Disabled scenarios fail before Docker use.
The protocol's proposal status is not silently converted into fault approval.

Modified existing files: local-CD `deploy.ps1` (opt-in namespace and S2 fixture),
`frozen-cd.yml` (explicit scenario input and fixture gate), local execution guides,
and upstream `.gitignore` (ignore measurement Python bytecode only). No application,
upstream CI, retry/health/recovery policy or other implementation was modified.

## Single GitHub S0 validation: 2026-09-25

- Published and tested control: `e13dfcc4314dff72f24ac1dad8e1337b72e2371f`.
- Exactly one S0 dispatch: [36115658970](https://github.com/id-nynt/memos-current-experiment/actions/runs/36115658970),
  trial `S0-github-validation-20260925-001`, candidate frozen v2. No rerun or fault scenario.
- **End-to-end result: FAIL before deployment.** All backend/frontend/proto checks
  passed, as did SQLite/MySQL/PostgreSQL upgrade tests and entrypoint tests. The
  release-image smoke job built a candidate Docker image, then failed with
  `No supported previous release found`. Deployment was skipped. There were 14
  successful jobs, one failed job and one skipped job (15 executed jobs).
- Cause: the new remote has experiment tags but lacks the upstream `v0.31.0` tag
  at `2b2192d4e153bd04f1d325b60fd880cf00d68b01`. The unchanged smoke script resolves
  its previous stable image from ancestral Git tags. Publishing that historical
  tag requires care: its old Release workflow triggers on `v*.*.*`. This historical
  tag proposal was later superseded by the explicitly approved image override below.
- Real self-hosted deployment remains **unvalidated** by this run. The Windows
  runner was brought online before dispatch but its deployment job was ineligible.
- Evidence retained under `experiment/results/S0-github-validation-20260925-001/`:
  exact run/job identities, all job-attempt metadata, artifact, complete raw GitHub
  log ZIP and 144 extracted files, health/workload samples and hash inventory.
  The CLI combined log omitted reusable-workflow logs; the full API archive was
  collected separately and archive collection is now automated in the harness.
- Fixed 600-second post-terminal follow-up completed. Final and endpoint health
  were true for **v1**, candidate delivery false, deployment timestamps null. Native
  deployment counters remain null and contract-v1 `evidence_complete` is false
  because deployment never started; these are not presented as a complete delivery.
- Reset after follow-up passed: both conventional volumes were backed up, the
  original seed was restored, and both environments verified on v1 at 5541/5542.
- Publishing the original harness briefly queued five push-triggered setup runs;
  four were cancelled before deployment and proto finished successfully. These
  predate S0 and are separately retained in `setup-push-runs.json`, not counted as
  trial runs. No second S0 was dispatched.
- Evidence-only archive correction passed 13 tests, including traversal rejection
  and nested-job log extraction. Native verification/recovery policy is unchanged.

## Approved minimal fix and one new S0: PASS

- Fix/tested control: `67c4731e67ee1ff0a8cc8d3cbfd7459a23ffe667`. Only the experiment
  supplies `previous_image: neosmemo/memos:0.31.0` to the reusable upgrade workflow;
  its existing smoke command receives `MEMOS_SMOKE_PREVIOUS_IMAGE`. The default
  remains empty for normal stable-tag discovery. No upstream test was removed.
- Exactly one newly authorized run:
  [36118890913](https://github.com/id-nynt/memos-current-experiment/actions/runs/36118890913),
  trial `S0-github-validation-20260925-002`, **all 16 jobs successful**. The previous
  failed attempt is preserved separately; no rerun or fault scenario was launched.
- CI, frontend/candidate smoke build, all upgrade checks and self-hosted deployment
  succeeded. The release smoke log confirms the requested previous image and test
  success. Deployment job `108021587169` ran on `memos-current-windows`.
- Staging and production both verified application
  `db695ea0d54cfce6925f07a4715cb42eb6fd8f20`, VERSION `local-<that full SHA>`, and image
  `sha256:d08139aec853b76733232f768cab6f771d8ae5055ac48d1b9c27619c67f1e701`.
  The smoke job builds its own test image; deployment promotes the preloaded frozen
  experiment image unchanged. The production backup checksum was independently verified.
- Common measurements: candidate delivered true; terminal and endpoint health true;
  evidence complete true; one workflow, 16 executed jobs; native retries and
  reobservations both zero; no recovery/rollback selected or executed; no human rescue.
  Pipeline time (including collection overhead) was 537.821794 seconds. These are
  technical validation measurements, not comparative performance conclusions.
- Follow-up retained its full 600 seconds. Evidence contains 518 health samples,
  1,129 workload requests, 153 raw log entries, native receipts/events and all job
  attempts. All 175 files in the collector's hash inventory verified. Private PAT
  values were absent. One unhealthy sample occurred during the planned stopped
  production backup; first subsequent healthy sample was about 4.29 seconds later.
- Raw evidence: `experiment/results/S0-github-validation-20260925-002/`. Additional
  live-state and reset verification is kept separately in the `-postvalidation/`
  sibling, preserving the collector's sealed inventory. Data/credential backups
  stay in private state, outside Git and GitHub artifacts.
- Reset after follow-up passed: both prior data sets were archived, the original
  stopped seed restored, and staging/production verified on frozen v1 at 5541/5542.
- Workflow lint, whitespace checks and all 13 harness tests passed before dispatch.
  No pipeline implementation defect beyond the approved previous-image wiring
  needed correction. No historical tag or Release workflow setting was changed.
