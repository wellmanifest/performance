# Ticket 002: Define Performance v1 contracts and reference profiles

- **ID**: ticket-002
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: VALIDATION
- **Created**: 2026-08-14

## Goal and scope

Define the language-neutral Performance v1 contract: evidence, workload,
baseline, metrics, budgets, decision outcomes, refactoring strategies,
compatibility, security invariants, rollout, rollback and verification. Publish
the normative prose, closed JSON Schema, request-only GBNF and the required
architecture diagrams. This ticket describes work and never authorizes it.

The 2026-08-30 execution slice also standardizes the measured Subactor
findings: generated-tree exclusion, background CPU/I/O containment, bounded
JSONL tail reads, shared refresh caches, and health-check cadence. These are
portable requirements; host-specific values remain adopter configuration.

A follow-up live audit adds machine-readable control records, detection tiers,
aggregate health-probe fan-out and bounded static-audit requirements after
observing 18 services sharing a three-second interpreter-based probe cadence.

## Acceptance criteria

- [x] AC-01: The standard covers no-change, configuration, packaging,
      same-language, algorithm, concurrency, protocol, runtime, selective Rust
      extraction and bounded replacement outcomes.
- [x] AC-02: A plan is invalid without a comparable baseline, workload,
      measurement method, acceptance threshold and rollback.
- [x] AC-03: Functional, security, resource and authority invariants are
      preserved independently of performance gains.
- [x] AC-04: The closed schema and GBNF reject unknown fields and executable
      shell strings.
- [x] AC-05: POA and DSL remain immutable external bindings; no standard
      document grants execution or deployment authority.

## Risks

- Optimizing a synthetic benchmark could regress the production workload.
- A rewrite could improve throughput while breaking compatibility or security.
- Rust could be selected as fashion rather than a measured boundary decision.

## Participants

- Human participant: unresolved; no user-* file was created by this script.
- Agent participant: [ai-codex.md](ai-codex.md)

## Validation evidence

- JSON Schema parsed and passed Draft 2020-12 meta-schema validation.
- `./project/governance-check.sh --actor agent`: `GOV-PASS`.
- `git diff --check`: passed.
- No runtime dependency, network effect, deployment or embedded grant was added.
- Expanded schema passes Draft 2020-12 meta-validation and governance after
  adding closed control records and bounded static-audit semantics.
