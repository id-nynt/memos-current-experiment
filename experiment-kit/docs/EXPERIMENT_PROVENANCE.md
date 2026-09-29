# Provenance without manual hash work

The comparison keeps the application, images, seed, workload and measurement rules
the same. Only the native Conventional versus BDI control approach differs.

## Three fixed inputs

1. **Application source:** `protocol/frozen-releases.json` selects the exact v1/v2
   commits and trees. Preparation verifies both repositories contain those objects.
2. **Control source:** Windows packaging selects committed native controls, creates
   immutable dispatch tags and includes their SHAs in `operator-revisions.json`.
3. **Study design:** the unchanged case matrix contains seeds, faults and treatment
   order. `study-batches.json` adds only grouping and execution order.

The kit-only Conventional commit follows its selected control commit. This avoids
a circular manifest containing its own commit hash. The package manifest separately
seals the kit files. Publication rejects intervening native control changes.

## Server image freeze

Preparation builds v1 and v2 once on Ubuntu amd64, verifies compiled commit/version
and health, and retains OCI archives, hashes, labels, layer/config/index proofs and
runtime Docker identities. Both treatments use the same shared session at
`~/.memos-experiment-images/session.json` through identical `image_identity.py` copies.

The committed release file still contains historical image selectors for backward
compatibility. In an active server session these are **source selectors**, not claims
that the historical image is running. The session explicitly maps each selected
source/release to the freshly built artifact. `frozen_oci_digest` records the actual
server artifact; `runtime_image_id` records Docker's runtime identity. The session
checksum, build-tool identities, preparation health receipts and full source/artifact
proofs are retained in run configuration/evidence.
No historical result file is rewritten.

A different source, altered session, wrong labels/layers/platform, or different
image between treatments fails verification. Configuration locks the whole session
across smoke and every study batch. Re-running preparation verifies or reloads the
retained archives; scenario execution never builds application images.

## Evidence and validation

Each treatment preserves declaration/seed, source and image identities, baseline,
native dispatch/outcome, actual fault schedule, production observations, staging
observations when applicable, retries/recovery/rollback, endpoint, cost and final
reset. Native journals remain raw. Historical Entity event names are translated
only in memory when reading old evidence; conflicting Entity/Job values are rejected.

Server validation checks evidence seals and rederives metrics. Every 20-case batch
can be validated and exported independently. Aggregate validation requires all five
exact selections, 200 valid treatment records and identical execution configuration.
Exports exclude images/private state and preserve file hashes. Local download checks
archive/file integrity, case coverage, order, seals, metrics and reset receipts; it
does not rederive server-path-dependent raw metrics or approve scientific conclusions.

No live Ubuntu preparation or experiment is claimed by local/static tests.
