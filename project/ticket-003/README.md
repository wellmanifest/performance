# Ticket 003: Implement deterministic Performance conformance

- **ID**: ticket-003
- **Owner**: unresolved:human
- **Status**: BACKLOG
- **Workflow state**: PLAN
- **Created**: 2026-08-14

## Goal and scope

Implement a dependency-free, offline validator for Performance v1. The CLI
must use strict JSON parsing, stable `PERF-*` findings, deterministic ordering
and fail-safe exit codes. Tests must cover valid plans and adversarial cases
including missing baselines, incomparable workloads, one-dimensional wins,
unbounded Rust rewrites, security regression and embedded execution authority.

## Acceptance criteria

- [ ] AC-01: Strict parsing rejects duplicate keys, malformed UTF-8 and unknown
      document fields.
- [ ] AC-02: Semantic checks enforce comparable evidence, budgets, invariants,
      rollback and authority separation.
- [ ] AC-03: Findings are stable, bounded, value-free and deterministically
      ordered.
- [ ] AC-04: CLI exits `0` for conforming plans, `1` for findings and `2` for
      internal failure.
- [ ] AC-05: Tests exercise every refactoring outcome and fail-closed boundary.

## Risks

- A hand-written validator could drift from the published schema.
- Diagnostics could accidentally echo secrets or untrusted benchmark payloads.
- Filesystem checks could escape the repository or introduce network behavior.

## Participants

- Human participant: unresolved; no user-* file was created by this script.
- Agent participant: [ai-codex.md](ai-codex.md)
