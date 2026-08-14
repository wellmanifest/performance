# Ticket 002: Define Performance v1 contracts and reference profiles

- **ID**: ticket-002
- **Owner**: unresolved:human
- **Status**: BACKLOG
- **Workflow state**: PLAN
- **Created**: 2026-08-14

## Goal and scope

Define the language-neutral Performance v1 contract: evidence, workload,
baseline, metrics, budgets, decision outcomes, refactoring strategies,
compatibility, security invariants, rollout, rollback and verification. Publish
the normative prose, closed JSON Schema, request-only GBNF and the required
architecture diagrams. This ticket describes work and never authorizes it.

## Acceptance criteria

- [ ] AC-01: The standard covers no-change, configuration, packaging,
      same-language, algorithm, concurrency, protocol, runtime, selective Rust
      extraction and bounded replacement outcomes.
- [ ] AC-02: A plan is invalid without a comparable baseline, workload,
      measurement method, acceptance threshold and rollback.
- [ ] AC-03: Functional, security, resource and authority invariants are
      preserved independently of performance gains.
- [ ] AC-04: The closed schema and GBNF reject unknown fields and executable
      shell strings.
- [ ] AC-05: POA and DSL remain immutable external bindings; no standard
      document grants execution or deployment authority.

## Risks

- Optimizing a synthetic benchmark could regress the production workload.
- A rewrite could improve throughput while breaking compatibility or security.
- Rust could be selected as fashion rather than a measured boundary decision.

## Participants

- Human participant: unresolved; no user-* file was created by this script.
- Agent participant: [ai-codex.md](ai-codex.md)
