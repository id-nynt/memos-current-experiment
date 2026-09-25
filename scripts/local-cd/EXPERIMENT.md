# Conventional experiment execution

Use the repository-owned [experiment harness](../../experiment/README.md) for setup,
seed/reset, v1/v2 execution and evidence. It has no parent-repository dependencies.

`frozen-releases.json`, `compose.yaml` and `deploy.ps1` remain the native release
manifest and conventional deployment implementation. The opt-in `-Experiment`
configuration uses `memos-current-experiment-*`, ports 5541/5542 and private
`%LOCALAPPDATA%/memos-current-experiment` state. Historical frozen-mode defaults and
ordinary local CD remain separate; do not reuse their state as this experiment's reset.
