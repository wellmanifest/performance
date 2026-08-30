# Performance v1

## Status and ownership

This document is the normative contract for `wellmanifest/performance` v1.
The pack HOMEs performance evidence, budgets, profiles, strategy selection and
rollback requirements. An adopting repository records `ADOPT
wellmanifest/performance`; it does not HOME Wellmanifest. Runtime commands,
credentials, deployment and process control stay in the adopting system.

The words MUST, MUST NOT, SHOULD and MAY are normative.

Performance plans describe a requested change. A valid plan is not execution,
merge, deployment, secret-access or production-mutation authority.

## Immutable bindings

- POA: `wellmanifest/poa@18215639f674966754c00d9188efe571e07cb219`
- DSL: `wellmanifest/dsl@8b5ef587a0eda2d16b6f979b991f66c7b3590fbe`

An adopter MAY use a later compatible revision, but MUST record its exact
40-character revision in the adoption evidence.

## Profiles

Every plan selects one or more profiles:

- `repository`: keeps generated, vendored, cache and ephemeral trees out of
  search, IDE indexes and Docker build contexts while preserving canonical
  source, configuration, migrations, sprints and security evidence.
- `developer-workstation`: contains recurring background jobs with scheduler,
  CPU and I/O weights; interactive work keeps priority.
- `runtime-service`: applies resource budgets, bounded health checks, shared
  refresh caches, backpressure and bounded reads.
- `high-throughput-runtime`: adds load, saturation, queue and tail-latency
  evidence before concurrency, protocol, native extraction or replacement.

Profiles compose. A repository with a service normally adopts `repository` and
`runtime-service`.

## Control records

Every plan MUST carry at least one machine-readable `controls` record. A record
binds a control kind and target to one numeric limit, unit, mechanism and
verification method. Supported kinds are repository working set, background
work, append-only read, health probe, refresh cache, concurrency, process
resource and request amplification. Limits MUST be finite and non-negative. An
exception MUST be explicit, bounded and measured; an empty exception means none.

The selected profiles require these minimum controls:

- `repository`: `repository_working_set`;
- `developer-workstation`: `background_work` and `process_resource`;
- `runtime-service`: `process_resource` and `concurrency`;
- `high-throughput-runtime`: `process_resource` and `concurrency` with tail
  latency and saturation budgets.

## Required evidence

A plan MUST define one stable subject, a representative workload, a baseline,
a candidate, budgets, preserved invariants, rollback and verification. Baseline
and candidate MUST use the same workload, units, measurement method, warm-up
policy and sample-count rule. Each sample set MUST contain at least three
samples. Raw evidence MUST be immutable or digest-bound.

At minimum, evidence covers the metric that triggered the change and every
budget that could regress. A throughput gain MUST NOT compensate for a failed
security, correctness, memory, CPU, I/O, latency or availability invariant.

## Portable controls

### Repository working set

Generated paths SHOULD be excluded at the narrowest effective layers:
tool-specific ignore, IDE exclusion, local Git exclude, and Docker ignore.
Tracked `.gitignore` is used only when the path is generated for every adopter.
An exclusion MUST NOT hide canonical inputs. In particular, a `.planfile`
container MAY be excluded selectively, but configuration and sprint definitions
remain visible while event streams, evidence and indexes may be excluded.

Each exclusion records a reason and one of `generated`, `cache`, `vendor`,
`ephemeral`, or `local-secret`. A validator MUST reject a broad root, source,
configuration or evidence exclusion without an explicit preserved child.

### Background work

Recurring non-interactive work MUST have a declared owner, cadence, timeout,
overlap policy and resource class. `batch-background` work SHOULD use reduced
CPU/IO weights and scheduler priority. It MUST NOT start a second run while the
first is active unless parallel execution is measured and bounded.

Host limits are adopter values, not standard constants. A limit MUST include a
measurement window and a rollback threshold. Process priority alone is not a
capacity bound; services SHOULD use cgroup or equivalent CPU, memory and PID
budgets when available.

### JSONL and append-only logs

Consumers requesting the newest records MUST read backward from EOF or use a
durable offset/index. They MUST NOT read an entire growing file for each poll.
Chunk decoders MUST preserve multibyte UTF-8 across boundaries, ignore only
well-defined blank records, cap record count and bytes, and close file handles.
Concurrent consumers SHOULD share one refresh and cache its immutable result
for a bounded TTL. Rotation, truncation and malformed final records MUST have
defined behavior.

### Health checks and polling

Health checks MUST test the smallest useful boundary and MUST have a timeout.
They SHOULD avoid spawning a language runtime solely to open a local socket
when a cheaper native probe exists. Cadence MUST be justified by detection-time
requirements; development defaults SHOULD not poll faster than 15 seconds
unless evidence requires it. Checks MUST have bounded output and SHOULD share
cached state rather than repeat full scans.

Cadence belongs to a declared detection tier: `startup`, `interactive`,
`availability`, or `background`. A three-second probe across many stable local
services is not a free default: its aggregate process-start rate MUST be
measured. When several services share one variable, the plan MUST report the
fan-out (`services / interval`) and the interpreter startup cost. Startup
readiness MAY use a short bounded cadence; steady-state checks SHOULD transition
to a slower availability cadence.

### Concurrency and caches

Concurrent refreshes of the same resource MUST be coalesced or independently
bounded. A cache declares key, TTL, maximum size, invalidation and stale-data
policy. Backpressure MUST bound queues and define reject, defer or shed behavior.
Caching MUST NOT weaken authorization, tenant isolation or freshness invariants.

Every fan-out operation MUST declare maximum in-flight work, queue size,
per-item timeout and failure aggregation. An unbounded `Promise.all`, thread
pool, process spawn, repository walk or recursive file scan over externally
growing input is non-conforming even when current fixtures are small.

### Request amplification

Polling consumers MUST declare requests per observation window, maximum rows
and bytes returned, cache/coalescing behavior and freshness need. Repeated exact
reads of the same immutable revision SHOULD share a cache. Several list queries
that differ only by a filter SHOULD use one bounded snapshot when this preserves
authorization and freshness. A service MUST NOT repeatedly request thousands of
rows merely to compute a small status projection when a summary, cursor,
conditional request or exact endpoint can provide the same evidence.

The adopter MUST inspect the rendered runtime configuration as well as source
Compose files. Overlays and environment expansion can create more active probes
than a static source count reveals.

## Static audit boundary

A repository audit MAY flag probable hazards such as interpreter-based Docker
healthchecks, sub-15-second steady polling, whole-file reads associated with
JSONL/audit/event paths, and unbounded concurrency. Findings are review input,
not proof of a defect and never execution authority. Audits MUST be bounded by
file count and bytes, skip generated/vendor/worktree/deployment trees, avoid
secret files, and emit stable path-and-line diagnostics without source values.

## Strategy outcomes

`strategy.outcome` is one of:

- `no_change`: evidence does not justify a change;
- `configuration`: ignores, cadence, limits, cache or runtime configuration;
- `packaging`: dependency, image or process packaging;
- `same_language`: algorithm, allocation, I/O or concurrency refactor;
- `protocol`: wire or storage representation change;
- `selective_native`: a measured boundary extracted to Rust or another native
  component while compatibility is retained;
- `bounded_replacement`: replacement with explicit migration and rollback.

The smallest strategy meeting every budget SHOULD be selected. Language choice
MUST follow profiling evidence. An unbounded rewrite or a migration without a
compatibility contract is invalid.

## Decision and lifecycle

The lifecycle is `requested -> baselined -> proposed -> measured -> accepted |
rejected -> rolled_back | verified`. `accepted` means the plan met its evidence
contract; it still grants no execution authority. Any invariant failure yields
`rejected`. Missing or incomparable evidence fails closed.

Rollout MUST be bounded by scope, observation window and abort thresholds.
Rollback MUST name a reversible mechanism and verification workload. A change
is `verified` only after the post-change observation window passes every budget
and invariant.
