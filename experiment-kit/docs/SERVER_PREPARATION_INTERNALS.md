# Server preparation internals

The operator path is [SERVER_EXECUTION_SIMPLE.md](../SERVER_EXECUTION_SIMPLE.md).
This document explains checks and recovery; it is not a second setup sequence.

## Source layout

`memos-current/experiment-kit/` is the version-controlled distribution of shared
tools, protocol, scenarios, Bash wrappers and operator documentation. Windows
`tools/local_prepare.py package` generates it from the workspace after native
commits. Its manifest records every included file and both immutable controls.
It contains no credentials, results, images, databases or Python environment.

On Ubuntu the kit links `memos-current` to its parent repository and clones
`memos-bdi` at the selected control. These local paths are Git-ignored. The native
operator creates detached control worktrees when needed. The server never edits
models or workflows and never creates a Git commit.

One automatic control tag per repository is retained because GitHub workflow
dispatch takes a branch/tag ref. Tags select code, not the Linux image build.
No new control tag or commit is needed after server preparation.
Preparation also sets and verifies the repository variable `MEMOS_EXPERIMENT_ROOT`
to the selected Conventional runtime worktree. Runtime faults must find that
worktree's live fixture lease; pointing at the newer kit checkout would be wrong.

## Required server permissions and dependencies

- Non-root dedicated account; Docker access for that account.
- Python 3.11+ and `python3-venv`; preparation installs PyYAML 6.0.2 in `.venv`.
- Docker Engine, Compose supporting `!override`, and Buildx with OCI export/load.
- Git, `gh`, PowerShell 7, JDK 21+, Bash, curl, unzip, jq and tar.
- Working DNS/HTTPS to GitHub/Actions/artifacts, Docker registries, npm, Go module
  servers, Maven and Gradle. Workflow setup actions supply Node/Go/pnpm versions.
- Synchronized system clock. Both runners use this host, user and Docker daemon.
- GitHub access to both private repositories, Actions dispatch/read, runner
  registration and repository-variable write permission. Use `gh auth login`;
  never commit tokens. Application accounts and credentials are generated privately.

Preparation checks tools and capabilities; it does not change university package
repositories, install privileged services or grant itself Docker access.

The helper downloads the official Linux x64 Actions runner release, requires its
published SHA256 digest, verifies it and registers repository-scoped runners.
Registration tokens are transient. Existing runner identities must match. A second
runner eligible for the experiment label blocks preparation to prevent cross-host
execution. Listener logs stay in `~/actions-runner-{conventional,bdi}`.

Listeners run detached under the current account and survive an SSH disconnect.
They are not installed as system services. After reboot, rerun preparation to start
them, provided no unresolved experiment is active. For automatic boot startup,
the administrator may install the official runner service under the same account
and `.venv` PATH; do not run a second listener for the same registration.

## What preparation verifies

1. Kit file hashes, selected Git tags/commits, application trees and publication.
2. Required tools, Docker access and clock synchronization.
3. Two local registered, online, idle and exclusively eligible runners.
4. v1/v2 Linux builds from the source commits, OCI proofs and application health.
5. Shared image session, BDI pinned support images and adapter receipt.
6. Native private credentials/accounts and one controlled database seed.
7. Genuine BDI v1 qualification; both native reset paths.
8. Same logical database state and same v1 images in all four environments.
9. Ports, Compose resource ownership, runner labels and dependency connectivity.

Only successful evidence sets validation flags. There is no manual JSON flag
editing. M001 checks both native outcomes, request observations and delivered v2.
Its sealed startup events must show both environments starting within the unchanged
Conventional timeout. This automated calibration is a readiness test, not proof of
a statistical worst-case startup time. Study mode also requires every representative
smoke case. Native failures in fault cases may be valid experimental outcomes.

Loopback ports: Conventional `5541–5544`; BDI `5420–5421`; BDI telemetry `9420–9421`.
Do not expose these publicly or stop unrelated services to free a port.

## Evidence and state

| Location | Contents |
|---|---|
| `results/setup/` | Preparation stages, parity, readiness and generated run configurations |
| `results/frozen-images/` | Retained images and build/health proofs; never result bundles |
| `~/.memos-experiment-images/session.json` | Shared, checksummed server image freeze |
| `~/memos-current-experiment/` | Private Conventional credentials, seed and receipts |
| `~/memos-bdi-state/` | Private BDI accounts, seed, adapter and campaign state |
| `results/smoke/M001/` | First paired trial |
| `results/study/batch-N/` | Independent 20-case paired batch |
| `results/logs/` | Wrapper command logs |
| `results/bundles/` | Export archives and adjacent checksums |

## When a command fails

| Failure | Meaning / diagnosis | Safe next action |
|---|---|---|
| Missing software, clock, permissions or network | Infrastructure; read wrapper log and readiness report | Administrator fixes the prerequisite, then rerun preparation |
| Runner download lacks a digest | Infrastructure; official asset verification unavailable | Install a verified official runner distribution in the named runner folder, then rerun preparation |
| Runner offline/busy or extra eligible runner | Infrastructure; inspect its local `listener.log` and GitHub runner inventory | Restore the intended runner or isolate labels; do not dispatch more work |
| Kit/control/fingerprint mismatch | Configuration drift | Fix and validate on LOCAL, package and publish again; use a fresh study workspace |
| Incomplete preparation stage | Setup may have changed state before failing; `started.json` exists without `complete.json` | Inspect that stage's log/private state; repair it deliberately. Never invent a completion receipt or delete a live database to retry |
| M001 errors, missing metrics or startup bounds | Readiness failure | Inspect its sealed evidence; correct instrumentation/infrastructure before fault runs |
| Native failure with valid fault evidence | Potentially valid experiment result | Keep it; compare metrics and final state rather than forcing success |
| Invalid/incomplete batch or active lock | Evidence incomplete or remote work uncertain | Preserve it; use the native operator reconciliation/finalization path after confirming remote workers are terminal. Never clear locks simply to rerun a claimed case |
| Bundle rejected for a secret/private file | Export safety failure | Inspect the named file securely; do not edit sealed evidence just to bypass the check |
| Download checksum/selection failure | Transfer or evidence mismatch | Preserve partial download; export/download to a new output directory after diagnosis |

Graceful STOP resumes through the same batch command. Forced interruption cannot be
safely automated when dispatch acknowledgement or remote completion is unknown.
No helper reruns a claimed invalid case or overwrites its evidence.
