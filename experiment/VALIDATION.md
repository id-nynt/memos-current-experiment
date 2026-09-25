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
