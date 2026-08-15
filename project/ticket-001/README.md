# Ticket 001: Bootstrap Performance standard and define delivery slices

- **ID**: ticket-001
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
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
      *Regressed by `45bde3b` and restored under AC-06; see below.*
- [x] AC-02: Required root files and the managed ticket index exist without a
      fabricated human participant file.
- [x] AC-03: The user request is recorded as session execution authorization
      for creating the Performance standard.
- [x] AC-04: The project TODO separates normative contracts, deterministic
      validation, references and publication.
- [x] AC-05: The bootstrap contains no performance optimizer, deployment
      mutation or authority grant.
- [x] AC-06: Every file listed in `.governance/manifest.lock.json` hashes to
      its pinned SHA-256 without the lock itself being edited, and
      `./project/governance-check.sh --actor agent` reports `GOV-PASS`.

## Regression and repair

`main@8693521` did not pass its own governance gate. The merge of pull request
1 carried commit `45bde3b` ("Point schema IDs at wellmanifest.com so packs
resolve the live host"), which rewrote five files that the adopted
`wellmanifest/new-project@0.17.0` standard pins by SHA-256 in
`.governance/manifest.lock.json`. The lock was not regenerated, so the gate
reported five `GOV-SYNC-001` errors.

Two things went wrong, both inside this ticket's own delivery:

- `.governance/**` was never in this ticket's `allowedPaths`, so `45bde3b`
  was out of scope when it was written. The gate now also reports
  `GOV-SCOPE-001` for exactly those paths.
- Editing lock-managed files in place invalidates the adoption preflight that
  AC-01 asserts, so AC-01 was silently false from that commit onward.

The repair restores the five files byte-for-byte from the governed baseline
`1d04a9a` and realigns the derived `.governance/manifest.json`, which the
pinned `manifest.schema.json` constrains to the same attestation predicate
constant. `.governance/manifest.lock.json` is not touched.

`GOV-SYNC-001` also offers an explicit standard upgrade with lock
regeneration. Upstream `new-project` is now `0.18.1` and does use the `.com`
host in these five files, so that path is legitimate later — but not here: it
would rewrite the trusted lock as a side effect of a defect fix, which is the
pattern that caused this breakage, and would import unreviewed
`0.17.0 -> 0.18.1` changes into a bootstrap ticket. This repository publishes
no schemas of its own yet, so no artifact depends on the `.com` host.

The identical defect and the identical repair apply to `wellmanifest/code-dsl`,
which was hit by the same sweep. `wellmanifest/merge` took the same commit but
is pinned to `0.18.0`, where the lock already records `.com`, so it is
unaffected.

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

## Validation evidence

- Managed-file digest audit against the untouched lock: 34 checked,
  0 mismatched, lock unedited.
- Governance gate: `GOV-PASS`, zero errors, zero warnings.
- No residual `wellmanifest.com` reference under `.governance/`.
- Non-governance paths versus the accepted base: empty diff.
- Command transcripts: [ai-codex-logs.txt](ai-codex-logs.txt).

## Publication state

The repair is complete and validated locally on
`ticket/001-restore-governance-lock-conformance`, cut from the exact accepted
base `8693521`. Merge, tag and release are not authorized by this ticket and
were not performed.
