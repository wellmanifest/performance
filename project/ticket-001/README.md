# Ticket 001: Bootstrap Performance standard and define delivery slices

- **ID**: ticket-001
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-08-14

## Goal and scope

Bootstrap the standalone `wellmanifest/performance` repository with the
published `wellmanifest/new-project` governance package and define bounded
delivery slices for Performance v1. This ticket owns repository governance and
planning only. It does not define the normative performance contract or an
executable optimizer.

## Acceptance criteria

- [x] AC-01: Governance is pinned to a published immutable `new-project`
      revision and passes its deterministic adoption preflight.
- [x] AC-02: Required root files and the managed ticket index exist without a
      fabricated human participant file.
- [x] AC-03: The user request is recorded as session execution authorization
      for creating the Performance standard.
- [x] AC-04: The project TODO separates normative contracts, deterministic
      validation, references and publication.
- [x] AC-05: The bootstrap contains no performance optimizer, deployment
      mutation or authority grant.

## Risks

- A performance standard could be mistaken for authority to rewrite or deploy
  code. Every later slice must preserve the descriptive, fail-closed boundary.
- A language migration could be approved from intuition rather than evidence.
  Performance v1 must require a compatible baseline, workload and acceptance
  threshold before selecting a refactoring strategy.
- Creating several contracts in one diff would exceed the governed delivery
  budget. Later work is split into independently owned tickets.

## Participants

- Human participant: unresolved; no user-* file was created by this script.
- Agent participant: [ai-codex.md](ai-codex.md)
