# Frozen-release conventional execution

Use `frozen-cd.yml` for this experiment. It deterministically runs the existing
backend/frontend/proto checks against the selected application SHA, then upgrade
smoke, then `deploy.ps1` for staging and production. No BDI policy is imported.
The ordinary `local-cd.yml` remains a separate main-branch development pipeline.

`frozen-releases.json` pins the application trees, compiled `local-<SHA>` version
and immutable images. Both images must be preloaded on the runner (Docker save/load
preserves image IDs). Source tags must be available in the repository. Packaging is
shared preparation; both approaches verify and reuse these same images rather than
rebuild them per arm. Missing or mismatched source/image identity fails closed.

Frozen mode uses projects `memos-aligned-current-{staging,production}`, independent
`_data` volumes, ports 5441/5442, and private state `~/.memos-aligned-current`.
Seed both volumes through the shared `tools/prepare_aligned_state.py` preparation.
The normal data volumes and ports are not used. Credentials reside in the state
directory at `credentials/<environment>/credential.json`, outside Git and evidence.
v2 requires an accepted v1 receipt in this state directory.

Local healthy validation (actual deployment, not a claim of GitHub CI completion):

```powershell
./scripts/local-cd/deploy.ps1 -Commit 2b5a8be2c2f9cf81599393a227890fb2424a5f03 -FrozenRelease v1 -TrialId unique-v1
./scripts/local-cd/deploy.ps1 -Commit db695ea0d54cfce6925f07a4715cb42eb6fd8f20 -FrozenRelease v2 -TrialId unique-v2
```

Wrap executions with `scripts/experiment-measurement/measure_trial.py` using an
explicit measurement JSON config. The identical collector/contract ships with BDI.
It records passive production samples and native events without deciding retries
or recovery. Pipeline timestamps cover the launched command; use `execution_mode`
to distinguish local deployment validation from a full GitHub pipeline. Failed
runs remain separate evidence directories. No fault scenario is authorized by
these healthy validation instructions.
