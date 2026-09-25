# Validation record

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
  tag requires care: its old Release workflow triggers on `v*.*.*`. Input correction
  is pending explicit approval; no upstream check was bypassed or changed.
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
