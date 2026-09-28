> Final-matrix execution is gated by [local readiness](../../../docs/LOCAL_BATCH_READINESS.md). This native guide is reference material; use the shared batch runbook after publication and parity verification. Historical examples do not override current contracts.

# Experiment source of truth

Updated 2026-09-25 (Australia/Sydney). This supersedes the initial read-only audit.

**Implementation aligned; conventional healthy deployment PASS; BDI campaign blocked
by GitHub publication approval.** Same frozen releases and common measurement
contract PASS. A BDI build-worker check or bootstrap container is not a successful
BDI-controlled deployment. No fault scenario was executed.

## Frozen application and control identities

Common upstream: `05a2c6db7a3e926c9142a635f42f7af0f078c81d`.
The application releases were not modified or recreated.

| Release | Application commit | Source tree |
| --- | --- | --- |
| v1 | `2b5a8be2c2f9cf81599393a227890fb2424a5f03` | `65d334d6e9e67c0b7262096a7e1c4abcb368daa5` |
| v2 | `db695ea0d54cfce6925f07a4715cb42eb6fd8f20` | `edcac42ea04e37749c5d003c8dbb14c75d174ef6` |

Both repositories resolve tags `memos-20260924-visible-header-v1` and
`memos-20260924-visible-header-v2` to those exact objects. v1 adds only the release
marker to upstream; v2 changes that marker and adds V2 text in `AuthPageLayout.tsx`
and `MemosLogo.tsx`. No backend, schema, dependency or API changes distinguish the
pair. Both approaches select the same corresponding release, independently of
what application files happen to be present at their control HEAD.

| Release | Shared immutable image ID (linux/amd64) |
| --- | --- |
| v1 | `sha256:610a28ab259d8d966851a5318258bdb3dc904a4be1af79c8ec61f3ecd9c281dc` |
| v2 | `sha256:d08139aec853b76733232f768cab6f771d8ae5055ac48d1b9c27619c67f1e701` |

Each image reports `COMMIT=<application SHA>` and `VERSION=local-<application SHA>`.
[Canonical release manifest](protocol/frozen-releases.json) is copied identically
into current's `scripts/local-cd/frozen-releases.json` and BDI's
`experiment/frozen-releases.json`. Both reject mismatched source trees/image IDs.
Packaging is shared preparation: both arms reuse the same preloaded images rather
than rebuild separate candidates. Docker save/load preserves IDs for another daemon.
The retained build logs are in [alignment evidence](results/alignment-20260925).

| Final local control | Commit | Immutable local tag |
| --- | --- | --- |
| Conventional | `7c6312c1950999ce875b3aa88174fdb03f3478c1` | `memos-control-current-aligned-7c6312c19509` |
| BDI | `d664e8b1e3765d366e7f59fa6aad1570f4506e5b` | `memos-control-bdi-aligned-d664e8b1e376` |

[Control/support manifest](protocol/control-revisions/20260925-aligned.json)
records full identities and SHA-256 hashes of shared tools. Neither final tag was
pushed. Conventional deployments ran at `ac5113b2986c902839869651155abf03da219f4e`;
its final commit changes only passive measurement selection mapping, not deployment
or workflow code. Original audit heads were current `05a2c6db...` and BDI `14da02be...`.
Historical `memos-conventional/`, pilot1 configs and results are not this comparison.

## What was implemented

- **Conventional:** `frozen-cd.yml` runs the existing backend/frontend/proto checks
  against the chosen frozen SHA, then upgrade smoke, then fixed staging/production
  deployment. The same image is promoted, production data is backed up, and identity,
  frontend, external URL and seeded sentinel are checked. v2 requires an accepted
  v1 baseline. No BDI monitoring, reconsideration, rollback policy or budgets were
  added. The ordinary main-branch `local-cd.yml` remains separate from this experiment.
- **BDI:** the real worker checks the same frozen application/image inputs; runtime
  bindings and helper paths select isolated aligned environments. Readiness verifies
  compiled SHA/version/external URL. Existing Jason decisions, goals, recovery policy,
  budgets, parser, generator and AgentSpeak agent are unchanged. Runtime bindings
  were regenerated through the existing generator, not edited in generated code.
- **Measurements:** identical collector and contract in each repository's
  `scripts/experiment-measurement/`, with canonical copies in
  [tools/measure_trial.py](tools/measure_trial.py) and
  [protocol/measurement-contract.json](protocol/measurement-contract.json).
  Native event hooks record deployment/verification boundaries. BDI collection retains
  all correlated GitHub run/job attempts and detects missing/expired artifacts.

## Isolation and initial data

| Approach | Staging / production ports | Projects | Private state |
| --- | --- | --- | --- |
| Conventional | 5441 / 5442 | `memos-aligned-current-{staging,production}` | Windows `~/.memos-aligned-current` |
| BDI | 5421 / 5420 | `memos-aligned-bdi-{staging,production}` | Linux `~/memos-aligned-state` |

Each project has its own `_data` volume/network. Both use SQLite, internal port 5230,
`/var/opt/memos`, and an instance URL equal to that environment's external localhost
endpoint. BDI Prometheus ports are 9421/9420. Previous deployments/volumes remain intact.

[Preparation tool](tools/prepare_aligned_state.py) created one fresh v1 account/PAT/
private sentinel, stopped the seed, and cloned its database to four independent
volumes. [Initial-state receipt](results/alignment-20260925/initial-state.json)
records the identical initial database SHA-256:
`1fb2a21c65a9c46a8c702541819177e12c0cb419876a4d0bdf16a7064556ca03`.
Credentials remain outside Git/evidence. The tool refuses to overwrite existing
setup. This establishes initial seed equality; runtime/controller traffic naturally
changes the copies afterwards. A later measured study requires fresh, verified
baseline/reset receipts and must not assume used volumes are still byte-identical.

## Common raw measurement definitions

The linked JSON contract is authoritative. Required fields include approach,
scenario, trial ID, application SHA, immutable image identity, pipeline start/end,
production deployment start/end, first fault/unhealthy and recovered/healthy times,
final health/release, candidate delivered, retry/reobservation counts, recovery
selected/executed, GitHub workflow/job counts and run IDs, and human interventions.

The same passive production sampler checks running image, health, compiled identity,
external URL and an authenticated sentinel read. It waits two seconds between
completed samples; short outages may be missed. Samples never drive controller
choices. Deployment boundaries bracket the application `compose up` operation;
backup/observer work is retained separately in native logs. Pipeline boundaries
cover the launched operator/controller, including its completion and final sample.

Unknown evidence stays null. A selected recovery is distinct from execution and
successful delivery. Reobservations count native controller rounds beyond the first,
not passive samples or operator final verification. Direct BDI recovery selection
and reconsideration selection both count. `[]` interventions requires explicit
attestation. `execution_mode=local` has zero GitHub runs; remote evidence requires
all acknowledged run IDs. Local deployment duration must not be compared with full
GitHub pipeline duration as if they were the same execution scope.

## Validation and outstanding work

| Check | Result / evidence |
| --- | --- |
| Same v1/v2 objects, trees, image IDs, architecture | PASS; release manifests and source/build-worker receipts |
| Identical application dependencies | PASS; original Go/pnpm/Buf manifests and locks unchanged |
| Conventional actual v1 deployment | PASS; [raw measurement](results/alignment-20260925/current-v1/common-measurement.json) |
| Conventional actual v1 to v2 deployment | PASS; [raw measurement](results/alignment-20260925/current-v2/common-measurement.json), backup and sentinel preserved |
| BDI build worker accepts both frozen releases | PASS; clean source checkouts, verified image IDs; not a deployment claim |
| BDI generated model/agent consistency | PASS; validate-only; decision architecture/policy unchanged |
| Shared measurement tests | PASS: six tests, including cross-arm definitions, missing evidence and direct recovery selection |
| BDI worker/preparation tests | PASS: five support tests and six preparation tests; no live faults |
| Workflow lint / PowerShell syntax / whitespace | PASS; [actionlint log](results/alignment-20260925/actionlint.log), AST parsing and Git diff checks |
| Full BDI-controlled healthy v1/v2 campaign | BLOCKED; final control tag must be published for real GitHub worker dispatch |
| Full conventional GitHub workflow | Not run; repository currently has no Windows runner. Actual local deployment path passed |

Automatic approval review rejected the BDI tag push because exporting repository
contents to GitHub lacked sufficiently explicit authorization. The existing
`id-nynt/memos-bdi-experiment` repository was verified private with an online Linux
runner, but that does not override the rejection. Approval was requested for the
final tag above; no publication or BDI campaign occurred.

After approval, publish only the final BDI tag, then use
[launch_aligned_bdi_windows.py](tools/launch_aligned_bdi_windows.py) for v1 followed
by v2 with the successful v1 native evidence directory as `--baseline`. This launches
the real Jason controller and preserves the common records. The helper passes the
existing GitHub session privately to WSL; it never writes the token into evidence.
Do not substitute sequential worker calls for a BDI-controlled validation.

## Remaining difference classification

- **Expected controller/infrastructure:** deterministic conventional vs Jason BDI;
  Windows vs Linux runner; BDI proxy/traffic/Prometheus; different native probes,
  observation/recovery policy; conventional backup/manual recovery and restart
  behavior; existing CI timeout/publication differences. These remain disclosed
  experimental treatments, not silently equalized or tuned against outcomes.
- **Harmless configuration:** separate names, ports, paths, Git remotes/branches,
  lint runner labels and CRLF/LF text encodings. Builds use the frozen Linux images.
- **Experiment-threatening application differences:** original asymmetric v2 UI,
  release selection, VERSION and external-URL mismatches are fixed by shared frozen
  artifacts/configuration. Full live equivalence is not yet certified because the
  BDI healthy campaign remains blocked. Do not start measured fault comparisons
  before completing that validation and freezing a comparable execution scope.
