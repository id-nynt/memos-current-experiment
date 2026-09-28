> Final-matrix execution is gated by [local readiness](../../../docs/LOCAL_BATCH_READINESS.md). This native guide is reference material; use the shared batch runbook after publication and parity verification. Historical examples do not override current contracts.

# Conventional vs BDI CI/CD comparison protocol

Design revision: 2026-09-25. **Proposal only: no implementation or experiment execution is authorized by this document.**

## 1. Question, scope and interpretation

Compare how the two existing CI/CD implementations deliver the same Memos candidate,
protect a working production baseline, and respond to equivalent failures. Evaluate
**reliability, resilience and execution cost separately**. Neither a successful
workflow nor a successful rollback alone proves successful candidate delivery.

The treatments are the complete conventional and BDI implementations, including
their existing checks, sequencing, observation policies and available recovery
actions. Conventional remains a deterministic pipeline with fixed verification,
backup and manual recovery. BDI retains Jason-controlled sequencing, observation
and rollback/reconsideration. Do not add BDI decisions to conventional or remove
capabilities from BDI to manufacture policy equality.

This is consequently a **comparison of these two systems**, not a causal test of
BDI reasoning alone. Runner OS, native telemetry workload, verification rules,
restart behavior and CI timeout differences must be reported as treatment
differences. They cannot be dismissed as harmless when interpreting results.
“Conventional CI/CD cannot recover” is not a conclusion supported by this study.

## 2. Sources, frozen inputs and readiness gates

Use [EXPERIMENT_SOURCE_OF_TRUTH.md](EXPERIMENT_SOURCE_OF_TRUTH.md),
[release manifest](protocol/frozen-releases.json),
[control manifest](protocol/control-revisions/20260925-aligned.json), and
[existing raw measurement contract](protocol/measurement-contract.json).

| Input | Frozen identity at design time |
| --- | --- |
| Upstream Memos | `05a2c6db7a3e926c9142a635f42f7af0f078c81d` |
| Known-good v1 | `2b5a8be2c2f9cf81599393a227890fb2424a5f03` |
| Candidate v2 | `db695ea0d54cfce6925f07a4715cb42eb6fd8f20` |
| Conventional control | `7c6312c1950999ce875b3aa88174fdb03f3478c1` |
| BDI control | `d664e8b1e3765d366e7f59fa6aad1570f4506e5b` |

Each arm uses the same corresponding source tree and immutable linux/amd64 image
from the release manifest. VERSION is `local-<application SHA>`; COMMIT is the
application SHA, never the controller revision. Shared image preparation is outside
the measured trial. Tests still run against the selected candidate. This experiment
does not measure independent per-arm image compilation performance.

**The current implementations are not yet ready for this entire protocol:**

| Gate / gap | Required before measured trials; no change made here |
| --- | --- |
| Healthy validation | Complete the real BDI-controlled v1/v2 campaign after publication approval. Conventional local deployment passed, but its full GitHub workflow has not been validated and lacks the required Windows runner. |
| Comparable execution scope | Use full GitHub-backed pipelines for both arms, including their actual quality gates. Do not compare conventional local deployment timing or zero GitHub jobs against a full BDI campaign. Local rehearsals remain separately labelled. |
| Symmetric fault delivery | Current has no equivalent S1/S2 fixture or runtime fault path. A reviewed external injection layer and neutral trigger hooks are prerequisites, not present capabilities. They must not implement recovery decisions. |
| BDI fault-hook defect | `experiment/scripts/scenarios.py:activate` still validates a legacy `memos-<approach>-production` name, whereas the aligned runtime uses `memos-aligned-bdi-production`. Resolve and verify target correlation before any runtime-fault trial. |
| Biased legacy S5 | Existing S5 clears five seconds after `rollback_selected`. Conventional has no corresponding selection event. Do not use that trigger for this comparison. |
| Observation horizon | The current common collector ends after the launched process exits. A separate passive observer must continue to the common evaluation endpoint defined below, including after early pipeline success/failure. |
| Evidence completeness | Demonstrate full conventional dispatch-to-terminal run/job collection, all BDI child runs, clock alignment, fault receipts and operator intervention records. GitHub artifact upload alone is insufficient. |

If these prerequisites require instrumentation changes, retain the old revisions,
assign new control/harness/contract identities, verify that decision policy is
unchanged, repeat technical validation, and freeze the final manifest before
measured runs. This document does not approve a push, deployment or fault execution.

## 3. Controls and permitted differences

The following must match for every paired comparison:

- v1/v2 source, images, platform, dependencies, schema, release identity and data
  compatibility; no controller-specific application patch or faulty candidate build.
- SQLite driver, data path, equivalent external instance URL semantics, independent
  staging/production volumes and networks, credentials with equivalent permissions,
  and the same seeded account/sentinel/data contents.
- A fresh matched v1 preparation before **each** candidate trial. Verify seed
  provenance and live baseline/sentinel in both environments; record native baseline
  receipts. A previous successful run or used volume is not a reset. Preparation and
  manual reset happen outside measured time and are logged separately.
- Host CPU/memory/storage class, Docker version/resources and resource reservations
  as closely as possible. Run arms sequentially on shared hardware; no concurrent
  competing trial. Record OS, quotas, load, dependency caches and runner image.
  Freeze the same warm/cold-cache preparation procedure, without tuning per arm.
- Offered external workload: one authenticated sentinel GET per second, no overlap
  within that client, three-second timeout, same payload/credential semantics and
  schedule. Record actual sends, responses and durations. This is **in addition to**
  the common health sampler. Native controller probes/BDI traffic remain unchanged,
  are identified separately and count as treatment overhead, not matched user load.
- Common health sampler: existing endpoint/identity/sentinel semantics, two seconds
  between completed samples, existing HTTP/Docker timeouts; retain actual timestamps
  and errors. It is passive with respect to control decisions, not load-free.
- Same fault specification, semantic trigger, affected routes/methods/releases,
  duration schedule, evaluation horizon and evidence rules. No approach-name branch
  that changes severity, duration, cleanup or expected outcome.

Separate ports, names and directories are necessary isolation, not different
application configurations. Native polling/retry/recovery budgets, quality-gate
scheduling, backups and decision rules remain frozen treatment properties. Record
them; do not equalize them after observing which arm succeeds. Equalize offered
conditions and measurement definitions, not the number of decisions taken.

## 4. Common timing, health and fault rules

### Timing and observation

`pipeline_start` is immediately before launching the entry workflow/controller;
queueing, checks and child workflows are included. `pipeline_end` uses the existing
contract: the launched operator/controller has terminated and its final common
sample has completed. Also retain native terminal time, collection overhead and the
terminal times of all correlated remote work. A returned launcher with unresolved
child jobs is not a completed pipeline.

The total predeclared pipeline observation cap is **120 minutes**. If unresolved,
record timeout/censoring and pending work; do not invent an end timestamp or delete
the run. Safety cancellation is an intervention and must be recorded separately.

For runtime scenarios, `t0` is the neutral production fault-start boundary below;
the evaluation endpoint is **t0 + 600 seconds**. Observe until the later of that
endpoint and resolved pipeline termination, subject to the pipeline cap. If a
controller acts after the endpoint, retain the action as late evidence but do not
retroactively change the endpoint outcome. For S0/S1/S2, continue common observation
for 600 seconds after resolved pipeline termination. Unresolved trials remain
unknown at end-of-follow-up rather than being assigned an artificial endpoint.

The 600-second horizon is a proposed external service-restoration objective, not
either controller's deadline. It must be accepted and frozen before execution;
longer native budgets remain visible in late-action evidence. These design values
must not be shortened or lengthened after seeing which arm benefits.

Keep pipeline-terminal health and endpoint health as separate fields. A pipeline
that finishes quickly does not receive a shorter fault exposure or follow-up.

An endpoint is **healthy** only when the frozen image/release identity, running
container, `/healthz`, compiled SHA/VERSION, external URL and authenticated sentinel
pass in every sample in the final 30-second window, with at least three samples, no
failed samples, no sample gap over 15 seconds and a last sample within five seconds
of the endpoint. A failed check means unhealthy; inadequate/missing observation
means unknown. Preserve health vs identity vs persistence failures separately.
This measures the tested service contract, not every possible Memos operation.

### Controller-independent runtime trigger and exposure

S3–S5 use the same proposed neutral hook: v2 is running in production and a common
initial identity/readiness/sentinel check has passed, **before native production
release verification/acceptance can complete**. Switch the prescribed fault on and
release the hook immediately. Bound hook synchronization to two seconds, retain its
timestamps, and count its elapsed time. Do not wait for rollback selection, a BDI
belief, a conventional timeout or a desired decision. Existing native warmup and
verification behavior then proceeds unchanged. If this boundary cannot be provided
symmetrically, those scenarios are not eligible for comparative execution.

The fault returns HTTP 503 for **all methods on `/api/v1/memos` and its subpaths**
for the targeted production v2 release; health/profile/frontend endpoints and
production v1 remain unaffected. Staging is unaffected. The external workload,
common sampler and native requests to those routes must encounter the same rule.
Placement must allow BDI's normal telemetry to observe the failed requests; a shim
that bypasses its measurement path is not equivalent exposure. Validate observable
request failures and route coverage, not merely a written switch file.

The schedule remains tied to the trial's production v2 release, including a v2
container recreation. Replacing v2 with verified v1 removes that release from scope
without clearing the schedule for v2. Infrastructure cleanup must not masquerade
as controller recovery. Record injection request, activation, first affected request,
all transitions, removal, target identities, and actual exposure. An armed switch
without affected requests is not proof of a delivered fault.

## 5. Scenario matrix

S0–S4 form the primary comparison. S5 is an optional changing-evidence analysis.
The durations below are fixed design exposures, not fitted to either controller's
deadlines. No winner or required internal action is preassigned.

| Scenario | Identical condition and trigger | Expected observable evidence | Common success / failure criteria | What must not differ |
| --- | --- | --- | --- | --- |
| **S0 Healthy** | Start verified v1; request frozen v2; no injected fault. | Exact-SHA CI results; staging then production receipts; same promoted image; native terminal result; common service/identity/sentinel samples. Normal update downtime is recorded, not called injected failure. | Delivery succeeds if v2 is healthy at the common endpoint with data intact and remote work resolved. Healthy v1 is safe non-delivery, not delivery success. Wrong release, unhealthy service or lost data fails the corresponding outcome; missing evidence is unknown. | Release pair, initial data, offered workload, resources, observation coverage and measured execution scope. Do not skip CI only for one arm. |
| **S1 Deterministic CI failure** | The unchanged backend/frontend checks complete successfully; an additional identical deterministic fixture always fails as the final test-gate result, before staging is eligible. Do not modify frozen application tests/source. | Fixture identity/output/nonzero exit and gate failure; any attempts; absence of staging/production candidate mutations; continued v1 service. Independently scheduled CI jobs may finish and count toward cost. | Correct containment: candidate not delivered, no deployment past the failed test gate, production remains healthy v1 with sentinel. This is successful rejection but failed delivery. Proceeding past the gate is a control failure even if production later looks healthy. Service recovery is not applicable if service never failed. | Same fixture and failing stage, prerequisite checks, exit semantics, repeat behavior on any permitted retry, and verification of production preservation. |
| **S2 Deployment failure** | After required CI passes, the staging deployment adapter deterministically returns a nonzero failure immediately before its first v2 Docker mutation. Every attempt at that operation in the trial sees the same failure. | Stage-entry/fault/error receipt; zero staging Docker mutation attributable to the failed operation; production deployment absence; live v1 state and persistence. | Correct containment: stop candidate promotion and retain healthy production v1. Candidate delivery is false, safety can be true. Promoting to production despite the failed staging gate is failure. This tests adapter failure, not a partially migrated database or production outage. | Same staging boundary, pre-mutation semantics, error type, repeated-attempt exposure and baseline state; no disk destruction or different partial deployment effects. |
| **S3 Transient degradation** | At common production t0, apply the runtime 503 rule for **60 seconds**, then remove it by the harness clock regardless of decisions. | Failed memo requests while health/profile can remain up; native observations; fault removal; first successful and sustained service samples; any action/decision and final release. | Report both axes: healthy v2 at endpoint = delivery and safe service; healthy v1 = safe restoration but no candidate delivery; unhealthy/unknown endpoint is not successful recovery. Controller failure followed by spontaneous service recovery remains controller failure plus service recovery, not an automatic controller rescue. | Fault routes, 60-second schedule, neutral trigger, user load, follow-up and rule that clearing is independent of controller exit/selection. |
| **S4 Persistent degradation** | At common t0, apply the same v2-scoped runtime rule for **900 seconds**; evaluate at +600 while it is still active for v2. The later expiry is only a safety cleanup. | Continued v2 errors; native detection and action selection/execution/cancellation; image changes; verification of any restored v1; sentinel persistence; intervention/timeout records. | Primary resilience success is healthy service with preserved data by the endpoint; healthy v1 counts as restoration, not candidate delivery. Unhealthy v2 at endpoint is unsafe failure regardless of workflow exit. A claimed healthy v2 while an all-request v2 fault is verifiably active demands exposure/measurement investigation, not an automatic win. Conventional's lack of automatic rollback is a measured capability limitation. | Rule remains active through endpoint, including v2 restarts; v1 exemption applies to both; no early clearing for one arm; no unrecorded manual repair. |
| **S5 Changing evidence (optional)** | Fixed schedule at common t0: 503 for **[0,60)** seconds; healthy **[60,120)**; 503 **[120,240)**; healthy thereafter through +600. No transition depends on any action or event. | Each timed request-status transition; which fresh observations reached each controller before termination; decisions/actions over time; accepted/failed/returned outcomes and post-termination outages. | Use the same delivery, health and persistence outcomes as S3. Separately report whether a controller revised, retained or could not revise a decision while active. No requirement to cancel rollback, keep v2, or remain running to earn an invented “adaptivity” score. If changing evidence never reaches an active decision opportunity, decision revision is **not assessable**, not a failed BDI test or evidence of conventional reconsideration. | Same complete timeline, including after an early exit or rollback; no clearance five seconds after rollback selection, no timing adjustment to catch one controller in its preferred window. |

S5 is supported conceptually by BDI's reconsideration capability, not by conventional's
policy. It can compare complete systems under changing conditions once symmetric
injection and extended observation exist. A direct **matched reconsideration-mechanism**
comparison is unsupported by these implementations and must not be claimed. Preserve
all S5 traces; do not select only the runs in which BDI happened to reconsider.

## 6. Objective metrics and derivation

Preserve all existing common-contract fields with their current definitions. In
particular, its `final_health` and `candidate_delivered` describe the collector's last
sample around process completion; they do **not** currently prove health at the
longer evaluation endpoint. This protocol proposes additional derived endpoint and
episode fields under a separately frozen evaluator version. Do not silently relabel
old records or use the collector's exit code as the scenario score: expected S1/S2
rejection can correctly return a nonzero exit.

| Dimension / metric | Definition and required distinction |
| --- | --- |
| **Reliability: candidate delivery** | `candidate_delivered_at_endpoint`: exact v2 image/SHA and healthy endpoint window with sentinel intact, mandatory CI/staging prerequisites satisfied, and no unresolved execution. True/false/unknown. Native production acceptance is reported separately: a failed pipeline can leave a healthy v2 after spontaneous recovery. Also retain pipeline exit and the existing terminal-sample delivery field. |
| **Reliability: final health and safety** | `health_at_endpoint`: healthy/unhealthy/unknown using the common checks. `safe_final_deployment`: verified healthy allowlisted v1 or v2, persistence intact and no unresolved deployment mutation at endpoint; otherwise unsafe or unknown. Healthy rollback is safe failed delivery. Safety here is operational, not a security guarantee. |
| **Reliability: containment** | Did a failed test/staging gate prevent prohibited promotion? Record actual deployment attempts even if final state was later repaired. Native success while common evidence is unhealthy is an acceptance mismatch; an outage starting after a genuinely healthy acceptance is a post-acceptance outage, not retroactive falsification of that timestamp. |
| **Resilience: recovery action** | Record ordered action type (none/reobserve/retry/restart/rollback/manual/other), target, selection, execution start/end, result and actor. Separate Docker automatic restarts and harness expiry from controller actions. Preserve the common selected/executed booleans and native decision traces. No action is not missing data when logs are complete. |
| **Resilience: recovery success** | Following an observed service-unhealthy episode, a stable healthy window is achieved by the endpoint with sentinel preserved. Label candidate repair (v2), baseline restoration (v1), spontaneous recovery after fault removal, or human-assisted recovery. Outcomes without sufficient evidence stay unknown; healthy rejection without outage is not applicable. |
| **Resilience: recovery time** | For each service-outage episode, first common service-unhealthy sample to the **start** of a subsequently confirmed stable window: at least three healthy samples spanning ten seconds, no failures, gaps <=15 seconds. Store confirmation time too. Report a separate fault-onset-to-restoration interval from the first affected request. Do not use the legacy mixed CI-fault/service-unhealthy field as the sole recovery-time origin. |
| **Resilience: unrecovered / repeated outages** | If no stable recovery is observed by endpoint, mark right-censored and report observed duration, not zero or an invented recovery time. For S5 preserve every episode, relapse count and final sustained recovery; first recovery alone is insufficient. Distinguish injection outage from ordinary deployment downtime. |
| **Resilience: continuation** | Record whether execution progressed past the failed operation after recovery and whether that continuation was permitted by the frozen gates. Correct stopping on deterministic failure is not inability-to-continue failure. Report candidate continuation and safe stopping separately. |
| **Execution cost: total pipeline time** | `pipeline_end - pipeline_start`, including queueing and actual quality gates. Retain native controller duration and collection overhead separately. Unresolved remote work is censored, not a fast finish. Observer follow-up time is separate and is not added to native pipeline time. |
| **Execution cost: deployment time** | Report each environment's application `compose up` start/end and result, including unsuccessful calls and recovery. Existing summary boundaries do not cover all stop/backup/proxy time; also report production-unavailability intervals and preparation/backup overhead from raw logs. |
| **Execution cost: workflows/jobs** | Distinct correlated actual GitHub run IDs; started non-skipped job executions across **all** attempts, deduplicated by job ID. Reusable workflow jobs are jobs within the caller's run, not invented extra workflow runs. Include failed/cancelled/quality-gate/collection jobs if started. Queue time and summed job duration are separate; parallel job durations are not wall time. |
| **Execution cost: retries** | Count native logical-operation attempts after the first; distinguish GitHub job/workflow reruns, HTTP-request retries and Docker restarts as separate counters. A rollback entity is a recovery action, not a retry of deployment. Missing attempt history is null. |
| **Execution cost: reobservations** | Existing contract: native health rounds beyond round one within each observation sequence. Separate native decision sequences from passive samples and operator final checks. Report initial observations and total passive requests separately so a count of zero does not mean no monitoring. |
| **Rollback** | Separate selected, cancelled, execution attempted, container actually replaced, v1 verified and persistence verified. Selection is not execution; execution is not success; successful restoration is not delivery of v2. |
| **Human intervention** | Timestamp, actor, reason, action, start/end and affected run. Count unplanned reruns, cancellation, restart, data restore, altered configuration and manual fault removal inside follow-up. Report count and active operator duration; unknown effort stays unknown. Initial launch/preparation and scheduled harness injection are separately logged, not human rescue. |

Recovery is sampled, not observed continuously: retain the preceding healthy and
following healthy samples to show uncertainty in onset/recovery timing. Use UTC
timestamps with clock-offset measurements and monotonic local durations where
available. Cross-host timing claims below measured clock uncertainty are unsupported;
offset >1 second makes precise cross-host timing ineligible, while verified outcome
evidence may remain usable. Observer errors are not automatically application faults:
record error provenance and classify unresolved causes as unknown.

## 7. Recording independently run approaches

Each arm runs separately. Assign a common `pair_id` plus a unique per-arm `trial_id`;
also map BDI native campaign/execution IDs and GitHub run/job IDs. Never correlate
by “latest run”, timestamp proximity alone, or an identical scenario name.

Proposed evidence layout (not created by this design):

```text
results/<study>/<scenario>/<pair_id>/<approach>/<trial_id>/
  manifest.json                # treatment, source/image/control/harness/contract IDs
  baseline-receipt.json        # seed, isolated volumes, v1 health and sentinel
  launch.json                  # requested release, execution scope, launch timing
  native/                     # decisions, deployment receipts, logs, controller result
  github/                     # all correlated runs, jobs/attempts, logs/artifact inventory
  fault-events.jsonl          # requested and actual exposure/transitions/cleanup
  workload.jsonl              # common offered traffic; no tokens or memo secrets
  common-observations.jsonl   # pipeline and post-terminal samples with timestamps
  human-interventions.json
  common-measurement.json     # existing contract, unchanged meanings
  evaluation.json            # endpoint/episodes/validity/censoring + evaluator hash
```

The manifest additionally records scenario parameters and timeline hash, seed
digest, URLs/resource allocation, native policy/config hashes, runner/cache state,
image provenance, time synchronization, observation endpoint and limits. A separate
pair index joins the two immutable records; it never overwrites them with a winner.

Before launch, start and validate observation, ensure healthy v1 and no stale fault,
then launch the normal controller once. Capture events automatically through the
endpoint even if the controller exits. After terminal and endpoint evidence is
sealed, evaluate both arms using the **same offline evaluator**, then perform/log
cleanup and next-trial preparation. The evaluator must not direct either pipeline.
If remote execution is unresolved, reconcile before reset; do not race new trials.

Record missing fields as null with a reason. Zero requires evidence of no occurrences;
`human_interventions=[]` requires an explicit attestation. Keep failed launches,
partial logs, intervention-assisted runs and superseded attempts. Each rerun gets
a new trial ID. Preserve a content-hash manifest before artifact retention expires;
keep credentials/data backups outside publishable evidence.

## 8. Trial order, validity and reporting

First conduct separately labelled technical pilots, after explicit execution
approval, solely to verify targeting, evidence and isolation. Freeze all parameters
above and the final instrumented revisions before measured runs. Pilot outcomes
must not determine fault duration or selection timing. A correction that changes
measurement/exposure creates a new protocol revision; retain earlier evidence.

For a small descriptive study, use **six paired repetitions per eligible primary
scenario**; three pairs conventional-first and three BDI-first, with scenario and
pair order randomized using recorded seed `20260925`. Freeze the resulting schedule
before execution. If S5 is enabled, predeclare it and use six additional pairs;
do not add or remove it after seeing primary outcomes. No concurrency, no early
stopping after favorable results, and no additional repetitions only for one arm.
This sample supports descriptive evidence, not broad statistical superiority claims.

Publish three views, with denominators explicit:

1. **All scheduled/attempted trials:** launch failures, gates not reached, timeouts,
   unavailable infrastructure, missing evidence and manual rescues remain visible.
2. **Exposure-valid paired trials:** same verified condition/trigger/timeline and
   sufficient common observation. Show attrition and causes by arm. If one arm never
   reaches the fault boundary, record non-delivery and `fault_not_reached`; do not
   pretend it recovered or silently rerun only that arm. Early safe rollback is a
   legitimate response, not invalid exposure merely because v1 becomes exempt.
3. **Mechanism traces:** native decisions and action sequences, including unsupported
   or unobserved decision opportunities. These explain outcomes without changing
   the common scoring rules.

Report per scenario: delivery counts/rates, safe/unsafe/unknown endpoints,
containment violations, recovery categories/by-endpoint recovery fraction,
censored recovery times, pipeline times, job/run counts, retries/reobservations,
rollback stages and intervention counts/durations. Show every paired difference
and median/range for eligible timing/count metrics. Do not average unrecovered
trials as zero, compare recovery-time means only among survivors as the sole result,
pool unlike scenarios into an unweighted win score, or treat missing data as success.

Manual rescue after an unsafe endpoint may be operationally necessary. Preserve
the autonomous result first and report the assisted outcome separately. The study
ends with evidence-supported statements about delivery, protection, recovery and
cost under the specified conditions, including cases where neither implementation
demonstrates the desired behavior.
