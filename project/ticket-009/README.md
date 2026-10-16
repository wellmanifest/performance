# Ticket 009: Add AST performance and resource-leak detectors to audit-repository

- **ID**: ticket-009
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-16

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: On 2026-10-16 user requested extending static bug and performance anti-pattern detectors in `wellmanifest/performance`:
- AC-01: Extend `audit_repository` in `src/performance.py` with AST and source detectors for `PERF-AUDIT-SQLITE-001`, `PERF-AUDIT-SQLITE-002`, `PERF-AUDIT-SQLITE-003`, `PERF-AUDIT-SUBPROC-001`, `PERF-AUDIT-SLEEP-001`, `PERF-AUDIT-PARSE-001`, and `PERF-AUDIT-KWARG-001`.
- AC-02: Add unit tests in `tests/test_performance.py` covering all 7 new detectors and their safe counterparts.
- AC-03: Pass `pytest -q` and `./project/governance-check.sh` with 0 errors.

## Acceptance criteria

- [x] AC-01: Extend `audit_repository` in `src/performance.py`.
- [x] AC-02: Add unit tests in `tests/test_performance.py`.
- [x] AC-03: Pass `pytest -q` and `./project/governance-check.sh`.

## Participants

- Human participant: user via chat authorization.
- Agent participant: Antigravity
