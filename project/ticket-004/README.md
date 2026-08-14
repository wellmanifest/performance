# Ticket 004: Publish Performance conformance CI

- **ID**: ticket-004
- **Owner**: unresolved:human
- **Status**: BACKLOG
- **Workflow state**: PLAN
- **Created**: 2026-08-14

## Goal and scope

Publish a minimal hosted conformance workflow that runs governance, strict
syntax checks, the dependency-free validator tests and repository diff checks
on Linux. The workflow must use pinned action revisions and must not become a
trusted merge-approval source.

## Acceptance criteria

- [ ] AC-01: Hosted CI runs governance and all Performance conformance tests.
- [ ] AC-02: Actions are pinned to immutable revisions and permissions are
      read-only unless a narrower permission is explicitly required.
- [ ] AC-03: CI never writes approval evidence or claims merge authority.
- [ ] AC-04: The workflow has no secrets, deployments or external mutations.

## Risks

- A repository-authored workflow could be mistaken for independent approval.
- Floating action tags could make validation non-reproducible.

## Participants

- Human participant: unresolved; no user-* file was created by this script.
- Agent participant: [ai-codex.md](ai-codex.md)
