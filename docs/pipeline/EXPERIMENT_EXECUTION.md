# Conventional experiment execution

Current setup, run, reset, scenario status, evidence and ownership instructions are
maintained in [experiment/EXPERIMENT_GUIDE.md](../../experiment/EXPERIMENT_GUIDE.md).

Repository: `id-nynt/memos-current-experiment`. Execution is independent of the master
repository. This replaces the historical guide's parent-script, shared virtual
environment and master-remote instructions. The protocol/source of truth beside
this document are historical definitions, not executable dependencies or fault approval.

Application v1 remains `2b5a8be2c2f9cf81599393a227890fb2424a5f03`; v2 remains
`db695ea0d54cfce6925f07a4715cb42eb6fd8f20`. v2 changes the release marker and visible
V2 header text, with no backend/schema/dependency changes. Each run records the actual
conventional control revision and harness hashes separately.

## Execution ledger

| Scenario | Trial | GitHub run | Outcome | Evidence |
| --- | --- | --- | --- | --- |
| S0 | `S0-20260925-202920` | Recorded in trial evidence | Completed validation | `experiment/results/S0-20260925-202920/` |
| S1 | `S1-20260925-205029` | Recorded in trial evidence | Valid expected pipeline failure | `experiment/results/S1-20260925-205029/` |
| S2 | `S2-20260925-210717` | Recorded in trial evidence | Valid expected pipeline failure | `experiment/results/S2-20260925-210717/` |
| S3 | `S3-20260925-225819` | [36138116562](https://github.com/id-nynt/memos-current-experiment/actions/runs/36138116562) | Completed validation; v2 delivered and retained | `experiment/results/S3-20260925-225819/` |
| S4 | Pending | Pending | Not dispatched | Pending |
| S5 | Pending | Pending | Not dispatched | Pending |

Earlier S3 attempts remain preserved as invalid/interrupted evidence:
`S3-20260925-212647` had no valid runtime fixture after the adapter rejected the
controller's `up --detach` form, and `S3-20260925-221852` was interrupted by a local
runner cancellation before the production fault hook. Neither is replaced or edited.

## Next authorized steps

S4 and S5 must run sequentially with fresh timestamped trial IDs using
`experiment/trial.ps1`, preserving the frozen controller, application images,
schedules, thresholds, retry budgets and reset behavior. Continue only if each
trial completes evidence collection and reset verification.

Before dispatching S4, the repository must again satisfy the guide prerequisites:
tracked files clean, local `HEAD` published to `origin/main`, `MEMOS_EXPERIMENT_ROOT`
pointing at this checkout, runner online and idle, Docker/frozen images/seed verified,
and the documented read-only checks passing. The current S3 documentation update is
subsequent to the validated S3 harness identity and must be reviewed, committed and
published before another trial can be launched under the guide's exact-HEAD rule.
