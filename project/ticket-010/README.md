# Ticket 010: Modularize performance validator and harden schema parity and symlink safety

- **ID**: ticket-010
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-11

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: User authorized continuous autonomous auditing, fixing, optimization, modularization, testing, and protected Validator delivery across `wellmanifest/*` repositories:
- AC-01: Decompose `src/performance.py` (954 lines) into focused `< 500`-line modules (`src/performance.py`, `src/performance_plan.py`, `src/performance_ast.py`) while preserving CLI entrypoint and `spec_from_file_location` compatibility.
- AC-02: Fix `TypeError` crashes on unhashable list/dict elements in `profiles`, `budgets`, `controls`, `invariants`, and `strategy`, and enforce full parity with `docs/performance-plan.schema.v1.json` (`subject.component`, `workload` strings/bounds, `metric` name regex, `invariants` `id`/`verification` & uniqueness, `strategy` `rationale`/`compatibility`/`changedPaths`, `rollout`/`rollback` string bounds).
- AC-03: Harden `load_plan`, `parse_inventory`, `local_adoption`, `audit_repository`, and `atomic_write` against symlink traversal/overwrite and add `fsync` durability.
- AC-04: Add regression tests in `tests/test_performance_hardening.py` and pass `ruff`, unit tests, `./project/governance-check.sh`, and `wellman check`.

## Acceptance criteria

- [x] AC-01: Decompose `src/performance.py` into `< 500`-line modules (`src/performance.py`, `src/performance_plan.py`, `src/performance_ast.py`).
- [x] AC-02: Fix unhashable input `TypeError` crashes and enforce `performance-plan.schema.v1.json` parity in `validate_plan`.
- [x] AC-03: Harden symlink handling and `atomic_write` durability across plan loading, repository audit, and local adoption.
- [x] AC-04: Pass `ruff`, unit tests, `./project/governance-check.sh`, and `wellman check` with 0 errors.

## Participants

- Human participant: user via chat authorization.
- Agent participant: Antigravity
