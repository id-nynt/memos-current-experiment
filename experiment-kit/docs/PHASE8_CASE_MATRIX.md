# Experiment case tracking list

**Five test sets, each containing 20 paired cases (40 treatment executions).**
Total: 100 paired cases / 200 treatment executions, excluding smoke, resets and qualification.
Every case runs both Conventional and BDI.

Test Set 1 means `batch-1`, Test Set 2 means `batch-2`, and so on.
The tables below follow the exact allocation and case execution order in the
[batch manifest](../protocol/study-batches.json). The original A/B labels remain internal
design metadata; they are not additional operator test sets.

See the [operator guide](../SERVER_EXECUTION_SIMPLE.md) for execution and downloads,
the [batch design](STUDY_BATCH_DESIGN.md) for balance checks, and the
[case matrix](../protocol/phase8-case-matrix.json) for full scenario definitions.

## Test set overview

| Test set | Command argument | Paired cases | Treatment executions | Result directory |
|---|---|---:|---:|---|
| Test Set 1 | `batch-1` | 20 | 40 | `results/study/batch-1` |
| Test Set 2 | `batch-2` | 20 | 40 | `results/study/batch-2` |
| Test Set 3 | `batch-3` | 20 | 40 | `results/study/batch-3` |
| Test Set 4 | `batch-4` | 20 | 40 | `results/study/batch-4` |
| Test Set 5 | `batch-5` | 20 | 40 | `results/study/batch-5` |

## How to read and track

- Row number is the execution position within that test set; do not sort by case ID.
- Each episode is `start-end seconds / failures per 100 requests / added delay in ms`.
- Runtime episode times start at target v2 schedule activation; the measurement horizon is 300 seconds.
- CI cases use native terminal + 300 seconds. `CI01` is the retry control; `CI02` is the deterministic failure control.
- Error positions are seeded in blocks of 100; partial blocks need not realize the configured percentage. Added delay is not observed p95.
- `First` identifies which treatment runs first; both use the same scenario and seed.
- Copy this document for personal tracking. Replace `NOT RECORDED` with `VALID`, `INVALID` or `INCOMPLETE` after checking saved evidence.
- Mark a pair `VALID` only when both treatments pass evidence validation. These initial labels do not report actual execution status.
- Each case directory contains `conventional/` and `bdi/` evidence. Saved results remain the authoritative status.
- Selected trials and smoke results do not replace official test set results.

## Family coverage

| Family | Test Set 1 | Test Set 2 | Test Set 3 | Test Set 4 | Test Set 5 | Total |
|---|---:|---:|---:|---:|---:|---:|
| reference | 1 | 1 | 0 | 1 | 1 | 4 |
| deterministic_control | 0 | 0 | 0 | 1 | 1 | 2 |
| ci_retry | 0 | 1 | 1 | 0 | 0 | 2 |
| persistent | 2 | 2 | 2 | 2 | 2 | 10 |
| transient | 2 | 2 | 2 | 2 | 2 | 10 |
| long_transient | 1 | 1 | 2 | 1 | 1 | 6 |
| relapse | 1 | 1 | 2 | 1 | 1 | 6 |
| intermittent | 2 | 1 | 1 | 1 | 1 | 6 |
| delayed | 2 | 2 | 2 | 2 | 2 | 10 |
| threshold | 1 | 1 | 1 | 2 | 1 | 6 |
| trajectory | 1 | 1 | 1 | 2 | 1 | 6 |
| staging | 3 | 3 | 3 | 2 | 3 | 14 |
| latency | 3 | 3 | 3 | 2 | 3 | 14 |
| mixed | 1 | 1 | 0 | 1 | 1 | 4 |

## Test Set 1 (batch-1)

20 paired cases / 40 treatment executions. Rows are in execution order.

```bash
./scripts/run-study.sh batch-1
```

Explanation:

- Runs or safely resumes Test Set 1, validates its results and resets between treatments.

Case result directories: `results/study/batch-1/<ID>/`.

| # | ID | Baseline / scenario | Family | Stage | Seed | Episodes: seconds / failures per 100 / delay ms | First | Pair status |
|---:|---|---|---|---|---|---|---|---|
| 1 | M007 | P02 / P8007 | persistent | production | 820007 | 0-300 / 60/100 / 0 | conventional | NOT RECORDED |
| 2 | M068 | P05 / P8068 | relapse | production | 820068 | 0-30 / 30/100 / 0; 50-150 / 30/100 / 0 | bdi | NOT RECORDED |
| 3 | M013 | P03 / P8013 | transient | production | 820013 | 0-75 / 60/100 / 0 | conventional | NOT RECORDED |
| 4 | M076 | P07 / P8076 | delayed | production | 820076 | 60-300 / 60/100 / 0 | bdi | NOT RECORDED |
| 5 | M017 | P04 / P8017 | long_transient | production | 820017 | 0-175 / 100/100 / 0 | conventional | NOT RECORDED |
| 6 | M084 | P13 / P8084 | trajectory | production | 820084 | 0-30 / 10/100 / 0; 30-65 / 30/100 / 0; 65-180 / 60/100 / 0 | bdi | NOT RECORDED |
| 7 | M021 | P06 / P8021 | intermittent | production | 820021 | 0-10 / 30/100 / 0; 20-30 / 30/100 / 0; 40-50 / 30/100 / 0; 60-70 / 30/100 / 0; 80-90 / 30/100 / 0; 100-110 / 30/100 / 0; 120-130 / 30/100 / 0 | conventional | NOT RECORDED |
| 8 | M092 | P18 / P8092 | latency | production | 820092 | 0-90 / 0/100 / 450 | bdi | NOT RECORDED |
| 9 | M031 | P10 / P8031 | threshold | production | 820031 | 0-180 / 6/100 / 0 | conventional | NOT RECORDED |
| 10 | M094 | P18 / P8094 | latency | production | 820094 | 0-90 / 0/100 / 550 | bdi | NOT RECORDED |
| 11 | M055 | P02 / P8055 | persistent | production | 820055 | 0-300 / 10/100 / 0 | conventional | NOT RECORDED |
| 12 | M004 | P00 / P8004 | reference | production | 820004 | healthy | bdi | NOT RECORDED |
| 13 | M073 | P06 / P8073 | intermittent | production | 820073 | 0-30 / 60/100 / 0; 60-90 / 60/100 / 0; 120-140 / 60/100 / 0 | conventional | NOT RECORDED |
| 14 | M014 | P03 / P8014 | transient | production | 820014 | 0-110 / 30/100 / 0 | bdi | NOT RECORDED |
| 15 | M075 | P08 / P8075 | delayed | production | 820075 | 30-60 / 60/100 / 0 | conventional | NOT RECORDED |
| 16 | M038 | P16 / P8038 | staging | staging | 820038 | 0-45 / 30/100 / 0 | bdi | NOT RECORDED |
| 17 | M085 | P15 / P8085 | staging | staging | 820085 | 0-300 / 4/100 / 0 | conventional | NOT RECORDED |
| 18 | M048 | P20 / P8048 | latency | production | 820048 | 25-150 / 0/100 / 800 | bdi | NOT RECORDED |
| 19 | M087 | P15 / P8087 | staging | staging | 820087 | 0-300 / 100/100 / 0 | conventional | NOT RECORDED |
| 20 | M050 | P23 / P8050 | mixed | production | 820050 | 0-120 / 30/100 / 800 | bdi | NOT RECORDED |

## Test Set 2 (batch-2)

20 paired cases / 40 treatment executions. Rows are in execution order.

```bash
./scripts/run-study.sh batch-2
```

Explanation:

- Runs or safely resumes Test Set 2, validates its results and resets between treatments.

Case result directories: `results/study/batch-2/<ID>/`.

| # | ID | Baseline / scenario | Family | Stage | Seed | Episodes: seconds / failures per 100 / delay ms | First | Pair status |
|---:|---|---|---|---|---|---|---|---|
| 1 | M011 | P03 / P8011 | transient | production | 820011 | 0-30 / 60/100 / 0 | conventional | NOT RECORDED |
| 2 | M056 | P02 / P8056 | persistent | production | 820056 | 0-300 / 30/100 / 0 | bdi | NOT RECORDED |
| 3 | M015 | P04 / P8015 | long_transient | production | 820015 | 0-145 / 30/100 / 0 | conventional | NOT RECORDED |
| 4 | M058 | P02 / P8058 | persistent | production | 820058 | 0-300 / 100/100 / 0 | bdi | NOT RECORDED |
| 5 | M037 | P15 / P8037 | staging | staging | 820037 | 0-300 / 100/100 / 0 | conventional | NOT RECORDED |
| 6 | M064 | P03 / P8064 | transient | production | 820064 | 0-100 / 30/100 / 0 | bdi | NOT RECORDED |
| 7 | M041 | P30 / P8041 | staging | staging | 820041 | 0-90 / 0/100 / 500 | conventional | NOT RECORDED |
| 8 | M082 | P13 / P8082 | trajectory | production | 820082 | 0-30 / 4/100 / 0; 30-65 / 6/100 / 0; 65-180 / 30/100 / 0 | bdi | NOT RECORDED |
| 9 | M043 | P18 / P8043 | latency | production | 820043 | 0-90 / 0/100 / 500 | conventional | NOT RECORDED |
| 10 | M100 | P23 / P8100 | mixed | production | 820100 | 0-120 / 30/100 / 800 | bdi | NOT RECORDED |
| 11 | M051 | P00 / P8051 | reference | production | 820051 | healthy | conventional | NOT RECORDED |
| 12 | M020 | P05 / P8020 | relapse | production | 820020 | 0-30 / 100/100 / 0; 50-150 / 100/100 / 0 | bdi | NOT RECORDED |
| 13 | M053 | P01 / CI01 | ci_retry | ci | 820053 | CI01 | conventional | NOT RECORDED |
| 14 | M022 | P06 / P8022 | intermittent | production | 820022 | 0-20 / 60/100 / 0; 40-60 / 60/100 / 0; 80-100 / 60/100 / 0; 120-140 / 60/100 / 0 | bdi | NOT RECORDED |
| 15 | M077 | P08 / P8077 | delayed | production | 820077 | 110-140 / 60/100 / 0 | conventional | NOT RECORDED |
| 16 | M030 | P10 / P8030 | threshold | production | 820030 | 0-180 / 5/100 / 0 | bdi | NOT RECORDED |
| 17 | M091 | P30 / P8091 | staging | staging | 820091 | 0-90 / 0/100 / 550 | conventional | NOT RECORDED |
| 18 | M026 | P07 / P8026 | delayed | production | 820026 | 50-300 / 60/100 / 0 | bdi | NOT RECORDED |
| 19 | M097 | P18 / P8097 | latency | production | 820097 | 0-90 / 0/100 / 4000 | conventional | NOT RECORDED |
| 20 | M044 | P18 / P8044 | latency | production | 820044 | 0-90 / 0/100 / 550 | bdi | NOT RECORDED |

## Test Set 3 (batch-3)

20 paired cases / 40 treatment executions. Rows are in execution order.

```bash
./scripts/run-study.sh batch-3
```

Explanation:

- Runs or safely resumes Test Set 3, validates its results and resets between treatments.

Case result directories: `results/study/batch-3/<ID>/`.

| # | ID | Baseline / scenario | Family | Stage | Seed | Episodes: seconds / failures per 100 / delay ms | First | Pair status |
|---:|---|---|---|---|---|---|---|---|
| 1 | M003 | P01 / CI01 | ci_retry | ci | 820003 | CI01 | conventional | NOT RECORDED |
| 2 | M066 | P04 / P8066 | long_transient | production | 820066 | 0-175 / 60/100 / 0 | bdi | NOT RECORDED |
| 3 | M005 | P02 / P8005 | persistent | production | 820005 | 0-300 / 10/100 / 0 | conventional | NOT RECORDED |
| 4 | M074 | P07 / P8074 | delayed | production | 820074 | 15-300 / 60/100 / 0 | bdi | NOT RECORDED |
| 5 | M019 | P05 / P8019 | relapse | production | 820019 | 0-30 / 60/100 / 0; 70-150 / 60/100 / 0 | conventional | NOT RECORDED |
| 6 | M078 | P07 / P8078 | delayed | production | 820078 | 180-300 / 60/100 / 0 | bdi | NOT RECORDED |
| 7 | M023 | P06 / P8023 | intermittent | production | 820023 | 0-35 / 60/100 / 0; 70-105 / 60/100 / 0 | conventional | NOT RECORDED |
| 8 | M086 | P15 / P8086 | staging | staging | 820086 | 0-300 / 60/100 / 0 | bdi | NOT RECORDED |
| 9 | M047 | P18 / P8047 | latency | production | 820047 | 0-90 / 0/100 / 4000 | conventional | NOT RECORDED |
| 10 | M096 | P18 / P8096 | latency | production | 820096 | 0-90 / 0/100 / 2000 | bdi | NOT RECORDED |
| 11 | M061 | P03 / P8061 | transient | production | 820061 | 0-40 / 60/100 / 0 | conventional | NOT RECORDED |
| 12 | M008 | P02 / P8008 | persistent | production | 820008 | 0-300 / 100/100 / 0 | bdi | NOT RECORDED |
| 13 | M065 | P04 / P8065 | long_transient | production | 820065 | 0-150 / 30/100 / 0 | conventional | NOT RECORDED |
| 14 | M012 | P03 / P8012 | transient | production | 820012 | 0-45 / 100/100 / 0 | bdi | NOT RECORDED |
| 15 | M081 | P10 / P8081 | threshold | production | 820081 | 0-180 / 6/100 / 0 | conventional | NOT RECORDED |
| 16 | M018 | P05 / P8018 | relapse | production | 820018 | 0-30 / 30/100 / 0; 45-150 / 30/100 / 0 | bdi | NOT RECORDED |
| 17 | M089 | P16 / P8089 | staging | staging | 820089 | 0-90 / 100/100 / 0 | conventional | NOT RECORDED |
| 18 | M032 | P13 / P8032 | trajectory | production | 820032 | 0-25 / 4/100 / 0; 25-60 / 6/100 / 0; 60-180 / 30/100 / 0 | bdi | NOT RECORDED |
| 19 | M095 | P18 / P8095 | latency | production | 820095 | 0-90 / 0/100 / 1000 | conventional | NOT RECORDED |
| 20 | M040 | P17 / P8040 | staging | staging | 820040 | 0-30 / 60/100 / 0; 50-130 / 60/100 / 0 | bdi | NOT RECORDED |

## Test Set 4 (batch-4)

20 paired cases / 40 treatment executions. Rows are in execution order.

```bash
./scripts/run-study.sh batch-4
```

Explanation:

- Runs or safely resumes Test Set 4, validates its results and resets between treatments.

Case result directories: `results/study/batch-4/<ID>/`.

| # | ID | Baseline / scenario | Family | Stage | Seed | Episodes: seconds / failures per 100 / delay ms | First | Pair status |
|---:|---|---|---|---|---|---|---|---|
| 1 | M001 | P00 / P8001 | reference | production | 820001 | healthy | conventional | NOT RECORDED |
| 2 | M060 | P03 / P8060 | transient | production | 820060 | 0-20 / 30/100 / 0 | bdi | NOT RECORDED |
| 3 | M009 | P02 / P8009 | persistent | production | 820009 | 20-300 / 60/100 / 0 | conventional | NOT RECORDED |
| 4 | M062 | P03 / P8062 | transient | production | 820062 | 0-60 / 100/100 / 0 | bdi | NOT RECORDED |
| 5 | M025 | P08 / P8025 | delayed | production | 820025 | 25-55 / 60/100 / 0 | conventional | NOT RECORDED |
| 6 | M080 | P10 / P8080 | threshold | production | 820080 | 0-180 / 5/100 / 0 | bdi | NOT RECORDED |
| 7 | M045 | P18 / P8045 | latency | production | 820045 | 0-90 / 0/100 / 800 | conventional | NOT RECORDED |
| 8 | M088 | P16 / P8088 | staging | staging | 820088 | 0-60 / 30/100 / 0 | bdi | NOT RECORDED |
| 9 | M029 | P10 / P8029 | threshold | production | 820029 | 0-180 / 4/100 / 0 | conventional | NOT RECORDED |
| 10 | M098 | P20 / P8098 | latency | production | 820098 | 30-150 / 0/100 / 800 | bdi | NOT RECORDED |
| 11 | M057 | P02 / P8057 | persistent | production | 820057 | 0-300 / 60/100 / 0 | conventional | NOT RECORDED |
| 12 | M002 | P33 / CI02 | deterministic_control | ci | 820002 | CI02 | bdi | NOT RECORDED |
| 13 | M069 | P05 / P8069 | relapse | production | 820069 | 0-30 / 60/100 / 0; 70-150 / 60/100 / 0 | conventional | NOT RECORDED |
| 14 | M016 | P04 / P8016 | long_transient | production | 820016 | 0-175 / 60/100 / 0 | bdi | NOT RECORDED |
| 15 | M071 | P06 / P8071 | intermittent | production | 820071 | 0-15 / 30/100 / 0; 30-45 / 30/100 / 0; 60-75 / 30/100 / 0; 90-105 / 30/100 / 0; 120-135 / 30/100 / 0 | conventional | NOT RECORDED |
| 16 | M028 | P07 / P8028 | delayed | production | 820028 | 180-300 / 60/100 / 0 | bdi | NOT RECORDED |
| 17 | M083 | P14 / P8083 | trajectory | production | 820083 | 0-25 / 60/100 / 0; 25-60 / 30/100 / 0; 60-180 / 10/100 / 0 | conventional | NOT RECORDED |
| 18 | M036 | P15 / P8036 | staging | staging | 820036 | 0-300 / 30/100 / 0 | bdi | NOT RECORDED |
| 19 | M099 | P23 / P8099 | mixed | production | 820099 | 0-120 / 6/100 / 550 | conventional | NOT RECORDED |
| 20 | M034 | P13 / P8034 | trajectory | production | 820034 | 0-25 / 10/100 / 0; 25-60 / 30/100 / 0; 60-180 / 60/100 / 0 | bdi | NOT RECORDED |

## Test Set 5 (batch-5)

20 paired cases / 40 treatment executions. Rows are in execution order.

```bash
./scripts/run-study.sh batch-5
```

Explanation:

- Runs or safely resumes Test Set 5, validates its results and resets between treatments.

Case result directories: `results/study/batch-5/<ID>/`.

| # | ID | Baseline / scenario | Family | Stage | Seed | Episodes: seconds / failures per 100 / delay ms | First | Pair status |
|---:|---|---|---|---|---|---|---|---|
| 1 | M027 | P08 / P8027 | delayed | production | 820027 | 100-130 / 60/100 / 0 | conventional | NOT RECORDED |
| 2 | M052 | P34 / CI03 | deterministic_control | ci | 820052 | CI03 | bdi | NOT RECORDED |
| 3 | M033 | P14 / P8033 | trajectory | production | 820033 | 0-25 / 60/100 / 0; 25-60 / 30/100 / 0; 60-180 / 10/100 / 0 | conventional | NOT RECORDED |
| 4 | M054 | P00 / P8054 | reference | production | 820054 | healthy | bdi | NOT RECORDED |
| 5 | M035 | P15 / P8035 | staging | staging | 820035 | 0-300 / 6/100 / 0 | conventional | NOT RECORDED |
| 6 | M070 | P05 / P8070 | relapse | production | 820070 | 0-30 / 100/100 / 0; 60-150 / 100/100 / 0 | bdi | NOT RECORDED |
| 7 | M039 | P16 / P8039 | staging | staging | 820039 | 0-90 / 100/100 / 0 | conventional | NOT RECORDED |
| 8 | M072 | P06 / P8072 | intermittent | production | 820072 | 0-20 / 60/100 / 0; 40-60 / 60/100 / 0; 80-100 / 60/100 / 0; 120-140 / 60/100 / 0 | bdi | NOT RECORDED |
| 9 | M049 | P23 / P8049 | mixed | production | 820049 | 0-120 / 6/100 / 500 | conventional | NOT RECORDED |
| 10 | M090 | P17 / P8090 | staging | staging | 820090 | 0-30 / 60/100 / 0; 65-130 / 60/100 / 0 | bdi | NOT RECORDED |
| 11 | M059 | P02 / P8059 | persistent | production | 820059 | 25-300 / 60/100 / 0 | conventional | NOT RECORDED |
| 12 | M010 | P03 / P8010 | transient | production | 820010 | 0-15 / 30/100 / 0 | bdi | NOT RECORDED |
| 13 | M067 | P04 / P8067 | long_transient | production | 820067 | 0-165 / 100/100 / 0 | conventional | NOT RECORDED |
| 14 | M006 | P02 / P8006 | persistent | production | 820006 | 0-300 / 30/100 / 0 | bdi | NOT RECORDED |
| 15 | M063 | P03 / P8063 | transient | production | 820063 | 0-75 / 60/100 / 0 | conventional | NOT RECORDED |
| 16 | M024 | P07 / P8024 | delayed | production | 820024 | 10-300 / 60/100 / 0 | bdi | NOT RECORDED |
| 17 | M079 | P10 / P8079 | threshold | production | 820079 | 0-180 / 4/100 / 0 | conventional | NOT RECORDED |
| 18 | M042 | P18 / P8042 | latency | production | 820042 | 0-90 / 0/100 / 450 | bdi | NOT RECORDED |
| 19 | M093 | P18 / P8093 | latency | production | 820093 | 0-90 / 0/100 / 500 | conventional | NOT RECORDED |
| 20 | M046 | P18 / P8046 | latency | production | 820046 | 0-90 / 0/100 / 1500 | bdi | NOT RECORDED |
