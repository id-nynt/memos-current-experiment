# Five balanced study batches

The primary study remains 100 paired cases (200 treatment executions). Original
case IDs, seeds, faults, horizons, A/B labels and treatment order are unchanged.
Only grouping and execution order change. Each batch can run, validate, resume
safely and export independently through the same single-case lifecycle.

## Final allocation

| Batch | Case IDs in execution order |
|---|---|
| batch-1 | M007, M068, M013, M076, M017, M084, M021, M092, M031, M094, M055, M004, M073, M014, M075, M038, M085, M048, M087, M050 |
| batch-2 | M011, M056, M015, M058, M037, M064, M041, M082, M043, M100, M051, M020, M053, M022, M077, M030, M091, M026, M097, M044 |
| batch-3 | M003, M066, M005, M074, M019, M078, M023, M086, M047, M096, M061, M008, M065, M012, M081, M018, M089, M032, M095, M040 |
| batch-4 | M001, M060, M009, M062, M025, M080, M045, M088, M029, M098, M057, M002, M069, M016, M071, M028, M083, M036, M099, M034 |
| batch-5 | M027, M052, M033, M054, M035, M070, M039, M072, M049, M090, M059, M010, M067, M006, M063, M024, M079, M042, M093, M046 |

## Composition

| Family | Total | Batch 1 | Batch 2 | Batch 3 | Batch 4 | Batch 5 |
|---|---:|---:|---:|---:|---:|---:|
| ci_retry | 2 | 0 | 1 | 1 | 0 | 0 |
| delayed | 10 | 2 | 2 | 2 | 2 | 2 |
| deterministic_control | 2 | 0 | 0 | 0 | 1 | 1 |
| intermittent | 6 | 2 | 1 | 1 | 1 | 1 |
| latency | 14 | 3 | 3 | 3 | 2 | 3 |
| long_transient | 6 | 1 | 1 | 2 | 1 | 1 |
| mixed | 4 | 1 | 1 | 0 | 1 | 1 |
| persistent | 10 | 2 | 2 | 2 | 2 | 2 |
| reference | 4 | 1 | 1 | 0 | 1 | 1 |
| relapse | 6 | 1 | 1 | 2 | 1 | 1 |
| staging | 14 | 3 | 3 | 3 | 2 | 3 |
| threshold | 6 | 1 | 1 | 1 | 2 | 1 |
| trajectory | 6 | 1 | 1 | 1 | 2 | 1 |
| transient | 10 | 2 | 2 | 2 | 2 | 2 |

Every batch contains exactly **20 pairs**, **10 A / 10 B**, and **10
Conventional-first / 10 BDI-first**. Execution alternates first-treatment order
and interleaves the original A/B sets, avoiding adjacent identical families where possible.

Allocation starts within original-set × first-treatment strata. Deterministic
swaps (PRNG seed `20260930`) minimize departures from the integer floor/ceiling
of each overall stratum count divided by five. It achieves those bounds for:

- scenario family;
- CI / production / staging;
- healthy / CI / persistent-through-horizon / finite exposure;
- original A/B set and first treatment;
- each identical-exposure repetition group (including different-seed repeats).

Some categories have fewer than five cases. For example, four healthy references
cannot put one in every batch. Integer floor/ceiling balance is the closest possible
proportional distribution; this is coverage balancing, not added statistical power.

The versioned manifest records each seed, repetition membership, scenario, family,
strata and treatment order. It is compiled from the unchanged case matrix.

## Validate or regenerate locally

| Option | Meaning |
|---|---|
| No option | Validate the saved allocation |
| `--write` | Regenerate deterministically after a reviewed design change |

```powershell
.\.venv\Scripts\python.exe -B tools/study_batches.py
```

Validation rejects missing/duplicate cases, wrong batch size, changed metadata,
allocation drift and any floor/ceiling imbalance. The same allocation hash is
locked into smoke/study configuration and checked by server aggregate validation
and `pull_results.py --expect-batches ...`.

Run `./scripts/run-study.sh batch-1` through `batch-5`. Each uses the existing
native reset → candidate → evidence → metrics → reset path. Final validation
requires all five exact selections, common configuration and 200 valid records.
