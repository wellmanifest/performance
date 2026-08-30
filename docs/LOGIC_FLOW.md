# Performance v1 logic flow and adoption

## Adoption

1. Pin an immutable `wellmanifest/performance` revision.
2. Start in audit mode and classify repository/runtime profiles.
3. Capture a representative baseline before changing code or configuration.
4. Create a `performance.plan/v1` document and run offline conformance.
5. Obtain the adopter's normal execution authority, then apply only the plan's
   bounded change.
6. Measure with the same workload and accept, reject or roll back.
7. Store a digest-bound receipt and enable enforcement only after the local
   check is stable.

## Subactor-derived reference mapping

| Observation | Portable control | Verification |
| --- | --- | --- |
| IDE indexes generated worktrees and dependency trees | layered narrow exclusions with preserved canonical children | index size, scan time, missing-input test |
| recurring diagnostics compete with interactive work | non-overlap plus CPU/IO weights and a bounded quota | CPU pressure and task completion time |
| a JSONL observer rereads hundreds of MB per poll | backward EOF reader or durable offset, shared TTL cache | bytes read per request and result equivalence |
| many containers run interpreter-based probes every few seconds | smallest native probe and evidence-based cadence | detection time and aggregate probe CPU |
| concurrent refreshes repeat the same full scan | promise coalescing, bounded cache and backpressure | refresh count, queue bound and freshness |

These mappings are examples, not universal numeric defaults. Canonical
`.planfile` configuration and sprint definitions remain visible; only generated
events, indexes and evidence may be excluded when the adopter confirms they are
reconstructable.

## Fail-closed decisions

- Missing, incomparable or mutable evidence: reject.
- Any correctness, security or authority regression: reject.
- Budget win with another undeclared resource regression: reject.
- Unknown plan field or executable shell string: reject.
- Native extraction without a measured boundary and compatibility test: reject.
- Successful candidate with no bounded rollout or rollback: reject.

