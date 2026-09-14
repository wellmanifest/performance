# Ticket 003: Implement deterministic Performance conformance

- **ID**: ticket-003
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-08-14

## Goal and scope

Implement a dependency-free, offline validator for Performance v1. The CLI
must use strict JSON parsing, stable `PERF-*` findings, deterministic ordering
and fail-safe exit codes. Tests must cover valid plans and adversarial cases
including missing baselines, incomparable workloads, one-dimensional wins,
unbounded Rust rewrites, security regression and embedded execution authority.

The CLI also owns a reversible local-adoption operation for the canonical
Wellmanifest workspace inventory. It installs a digest-marked block in each
checkout's local Git exclude file and emits a bounded receipt. It never edits
tracked adopter files, worktrees, deployments, missing repositories or remotes.

The follow-up audit adds a bounded static repository scan for fast healthcheck
cadence, interpreter-per-probe commands, probable whole-file event reads and
mapped concurrency without a visible local bound. Findings are advisory input
to a measured plan and contain paths/lines, never source values.

## Acceptance criteria

- [x] AC-01: Strict parsing rejects duplicate keys, malformed UTF-8 and unknown
      document fields.
- [x] AC-02: Semantic checks enforce comparable evidence, budgets, invariants,
      rollback and authority separation.
- [x] AC-03: Findings are stable, bounded, value-free and deterministically
      ordered.
- [x] AC-04: CLI exits `0` for conforming plans, `1` for findings and `2` for
      internal failure.
- [x] AC-05: Tests exercise every refactoring outcome and fail-closed boundary.
- [x] AC-06: Local adoption preserves existing excludes, canonical `.planfile`
      inputs and dirty worktrees while covering every checked-out manifest repo.
- [x] AC-07: Static audit is bounded, skips generated/vendor/test and secret
      trees by default, emits no source values, and reports stable path/line
      findings for health, growing-file I/O and concurrency hazards.

## Risks

- A hand-written validator could drift from the published schema.
- Diagnostics could accidentally echo secrets or untrusted benchmark payloads.
- Filesystem checks could escape the repository or introduce network behavior.

## Participants

- Human participant: unresolved; no user-* file was created by this script.
- Agent participant: [ai-codex.md](ai-codex.md)

## Validation evidence

- Dependency-free unit/adversarial suite: 11 tests passed.
- Governance gate and diff check passed.
- Local adopter updated 45/45 declared checkouts; read-only follow-up reported
  45 `current`, zero missing, malformed or unsafe repositories.
- Receipt: `~/.local/state/wellmanifest-performance/adoption-20260830.json`,
  pattern digest `sha256:ab1e767798cb6f5140bb32df3ab53281e2c38ae3a80c893bb57e8964cfbecc69`.
- Static fleet audit receipt:
  `~/.local/state/wellmanifest-performance/audit-20260830.json`; 45 repositories
  scanned with generated/vendor/test trees excluded by default.

## Continued audit optimization

- [x] AC-07: Exact diagnostic parity on all selected Wellmanifest repositories and a mixed adversarial fixture; same workload performance budgets pass.

## Numeric validation continuation — 2026-09-14

This new local slice resumes the existing validator scope after the integrated
audit optimization; prior publication observations above are historical.
No adopter deployment or local-exclude update is part of this continuation.

- [x] AC-08: NaN, infinities, overflowing integers and booleans are rejected at
      baseline, candidate, threshold and control boundaries with stable codes.
- [x] AC-09: JSON exponent overflow returns input failure without echoing the
      value; finite exponent notation and a zero control remain accepted.
- [x] AC-10: All 15 dependency-free tests and the scoped governance gate pass.

The standard's grammar/prose changes are separately owned by ticket-002.
Local validation is not trusted review, publication or production verification.
