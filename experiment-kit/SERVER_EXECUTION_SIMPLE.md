# Run the experiment on Ubuntu

Use **LOCAL** for Windows PowerShell and **SERVER** for Ubuntu Bash.

```text
LOCAL: validate → commit controls → package → commit kit → push
SERVER: clone → prepare → M001 → smoke → five 20-case batches
        → validate → export → download
```

## 1. Finish and publish on LOCAL

| Value | Use |
|---|---|
| Workspace | `C:\NHI\2026_IT-Project\260037_memos-exp` |
| Conventional repository | `id-nynt/memos-current-experiment` |
| BDI repository | `id-nynt/memos-bdi-experiment` |
| Branch | `main` in both repositories; merge your reviewed work first |

The refactor and experiment changes must be committed before packaging. The
package command selects those commits automatically. It copies the shared tools,
protocol, scenarios and scripts into Conventional's tracked `experiment-kit/`.

```powershell
Set-Location C:\NHI\2026_IT-Project\260037_memos-exp
.\.venv\Scripts\python.exe -B tools/local_prepare.py validate

git -C memos-bdi add .github bdi-cicd-framework experiment docs
git -C memos-bdi commit -m "Complete Job controls and shared Linux image preparation"
git -C memos-current add .github scripts experiment .gitattributes
git -C memos-current commit -m "Use shared server image freeze for experiment controls"

.\.venv\Scripts\python.exe -B tools/local_prepare.py package
git -C memos-current add experiment-kit
git -C memos-current commit -m "Package reproducible experiment runner and five study batches"
.\.venv\Scripts\python.exe -B tools/local_prepare.py publish
```

Explanation:

- `Set-Location` opens the local workspace; `validate` checks contracts, batch allocation and offline tests.
- The first two `git add` / `git commit` pairs save the BDI and Conventional changes.
- `package` selects those commits and creates the reproducible experiment kit.
- The final `git add` / `git commit` saves the kit; `publish` pushes both repositories and required tags to GitHub.

If native changes are already committed, skip that repository's commit command.
`validate` runs offline tests. `package` requires a matching successful validation
receipt and refuses uncommitted native changes.
`publish` pushes both controls and the kit, with automatic immutable control/source
tags. **Do not publish the supplied preview package without running `package`.**

## 2. Set up SERVER once

Ask the administrator for Ubuntu **amd64**, Python **3.11+** with `venv`, Git,
GitHub CLI (`gh`), Docker with Compose/Buildx, PowerShell **7**, JDK **21+**,
`curl`, `unzip`, `jq`, and `tar`. Your non-root account must use Docker without
sudo, have a synchronized clock, and reach GitHub and package registries.

Use a dedicated server/account. Keep experiment ports local. Detailed dependency,
port and runner notes: [Preparation internals](docs/SERVER_PREPARATION_INTERNALS.md).

| Value | Example |
|---|---|
| SSH destination | `USER@SERVER` — replace with your university login |
| Server checkout | `~/memos-current` |

Connect through your university VPN, then SSH. **SERVER:**

```bash
gh auth login
gh auth setup-git
git clone https://github.com/id-nynt/memos-current-experiment.git ~/memos-current
cd ~/memos-current/experiment-kit
./scripts/server-prepare.sh
```

Explanation:

- `gh auth login` signs in to GitHub; `gh auth setup-git` enables Git to use that login.
- `git clone` downloads the Conventional repository; `cd` opens its experiment kit.
- `server-prepare.sh` prepares both approaches, retained images, runners and controlled starting state, then checks readiness.

**Expected: `READY`.** Preparation clones BDI, verifies controls, creates the Python
environment, registers/starts two runners, builds and verifies v1/v2 once, prepares
private state, qualifies BDI, resets both treatments and checks database parity.
No SHA editing, source-file transfer or server-side Git publication is needed.

Keep this checkout and private state for the whole study. Re-running preparation
reuses completed stages and the retained images. It stops on partial/uncertain state.

## 3. Run M001, then smoke

**SERVER**, from `~/memos-current/experiment-kit`:

```bash
./scripts/run-smoke.sh first
./scripts/export-results.sh M001
```

Explanation:

- `run-smoke.sh first` runs and validates the healthy M001 case with both approaches.
- `export-results.sh M001` creates its result bundle and checksum for downloading.

**Expected:** one valid healthy pair. Download it using Section 6 and review the
metrics. Then run the remaining smoke coverage:

```bash
./scripts/run-smoke.sh
```

Explanation:

- Runs the smoke cases through the shared runner, reuses valid completed results and checks readiness for the study.

M001 is checked and skipped if already valid. Fault scenarios run only after its
healthy checks pass. **Expected: `READY`** before starting the study.

## 4. Run five independent batches

| Value | Choices | Size |
|---|---|---|
| Batch | `batch-1` … `batch-5` | 20 paired cases / 40 treatment executions |
| Final validation/export | `all` | All 100 pairs / 200 treatment executions |

Run each line when ready. Each command validates its results and resets between
treatments. You can stop work between batches and download each batch immediately.

```bash
./scripts/run-study.sh batch-1
./scripts/export-results.sh batch-1
./scripts/run-study.sh batch-2
./scripts/run-study.sh batch-3
./scripts/run-study.sh batch-4
./scripts/run-study.sh batch-5
./scripts/validate-results.sh all
./scripts/export-results.sh all
```

Explanation:

- Each `run-study.sh batch-N` runs and validates that batch of 20 paired cases.
- `export-results.sh batch-1` packages the first batch so you can download it immediately.
- `validate-results.sh all` checks all five batches together.
- `export-results.sh all` creates or verifies the five downloadable batch bundles.

**Expected after each batch:** `20/20 pairs completed`, `20 valid`, `0 invalid`,
`0 incomplete`, `READY FOR NEXT BATCH`.

To recheck one batch:

```bash
./scripts/validate-results.sh batch-1
```

Explanation:

- Checks the saved evidence and validity of batch 1 without running its cases again.

The [batch design](docs/STUDY_BATCH_DESIGN.md) lists all case IDs and balance checks.

## 4a. Run selected cases only

After preparation and the full smoke check pass, you can run a custom selection.
See the [case tracking list by Test Sets 1-5](docs/PHASE8_CASE_MATRIX.md) to choose IDs.

| Value | Example |
|---|---|
| Cases | `M005 M006 M007 M008 M009 M010` (six paired cases / 12 treatment executions) |
| Configuration | `results/setup/study.json`, created after smoke passes |
| Results | `results/selected/M005-M010` (use a separate directory for each selection) |

**SERVER**, from `~/memos-current/experiment-kit`:

```bash
.venv/bin/python -B tools/batch_runner.py execute \
  --config results/setup/study.json \
  --cases M005 M006 M007 M008 M009 M010 \
  --directory results/selected/M005-M010
```

Explanation:

- Runs only the listed cases, with both treatments and each case's predefined order, seed and fault settings.
- Uses the same execution, evidence collection and reset process as the study batches.
- Saves the results separately; these runs do not replace cases in the official five-batch study.

List each ID after `--cases`; range notation such as `M005-M010` is not supported.
For one case, use `--cases M005`. For any other selection, list its IDs in the desired order.
Repeat the same command and directory only for a safe resume: valid treatments are skipped;
invalid/interrupted evidence or unresolved locks require diagnosis. Use a new directory for a new trial.

## 5. Monitor or resume

| Value | Example |
|---|---|
| Result directory | `results/study/batch-1` |

```bash
.venv/bin/python -B tools/experiment.py status --directory results/study/batch-1
touch results/study/batch-1/STOP
```

Explanation:

- `status` displays the batch progress.
- `touch .../STOP` requests a safe stop after the active treatment and reset; use it only when you want to pause.

`STOP` finishes the active treatment and reset, then prevents the next treatment.
After the command exits, resume with:

```bash
rm results/study/batch-1/STOP
./scripts/run-study.sh batch-1
```

Explanation:

- `rm .../STOP` removes the pause request.
- `run-study.sh batch-1` resumes the same batch, skipping valid completed treatments.

Valid treatments are skipped. Invalid/interrupted treatments and uncertain remote
workers are never replayed automatically. A forced interruption needs reconciliation;
keep the locks and evidence. See [troubleshooting](docs/SERVER_PREPARATION_INTERNALS.md#when-a-command-fails).

## 6. Download and inspect on LOCAL

| Value | First trial | One study batch |
|---|---|---|
| `$Name` | `M001` | `batch-1` … `batch-5` |
| Expected selection | `--expect-case M001` | `--expect-batches batch-1` |
| Output | A **new** local directory | A **new** local directory |

**LOCAL — first trial:**

```powershell
$Server = "USER@SERVER"
$Name = "M001"
$Remote = "~/memos-current/experiment-kit/results/bundles/$Name.tar.gz"
.\.venv\Scripts\python.exe -B tools/pull_results.py --server $Server --remote $Remote --expect-case M001 --output results/download/M001-001
Invoke-Item results/download/M001-001/review.md
```

Explanation:

- Sets your server address and the M001 bundle path.
- `pull_results.py` downloads and verifies the first trial, then writes a local review.
- `Invoke-Item` opens that review.

**LOCAL — one completed batch:**

```powershell
$Name = "batch-1"
$Remote = "~/memos-current/experiment-kit/results/bundles/$Name.tar.gz"
.\.venv\Scripts\python.exe -B tools/pull_results.py --server $Server --remote $Remote --expect-batches $Name --output "results/download/$Name-001"
```

Explanation:

- Selects one completed batch and its remote bundle, using the `$Server` value set above.
- Downloads and verifies that batch into a new local directory, including its review and metrics.

**LOCAL — all five completed batches:**

```powershell
$Batches = 1..5 | ForEach-Object { "batch-$_" }
$Remote = $Batches | ForEach-Object { "~/memos-current/experiment-kit/results/bundles/$_.tar.gz" }
.\.venv\Scripts\python.exe -B tools/pull_results.py --server $Server --remote $Remote --expect-batches $Batches --output results/download/final-001
Invoke-Item results/download/final-001/review.md
```

Explanation:

- Builds the names and remote paths for all five batches, using the `$Server` value set above.
- Downloads and checks the complete result set together.
- `Invoke-Item` opens the final local review.

**Expected: `CHECKS_PASSED`.** Read `review.md` and `metrics.csv`; original evidence
is in `unpacked/`. The helper checks checksums, cases, metrics, evidence and reset
receipts. It does not decide which treatment should win or approve your conclusions.
Keep null/not-applicable recovery values; do not replace them with zero.
