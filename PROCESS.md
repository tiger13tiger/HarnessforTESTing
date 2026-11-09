# Pipeline health checklist

This is the single source of truth for "is this repo's dev -> uat -> main
pipeline healthy, or has it drifted." The weekly automated check reads this
file and compares reality against it — if the process ever deliberately
changes, update this file first; the check follows it, not the other way
around.

See README.md's "Stage 1/2/3" sections for the full mechanics of each step,
and [`docs/architecture.html`](docs/architecture.html) for the diagrammed
version. This file is the short version, written as a checklist.

## The intended flow

```
dev  --(human or evolve_cli.py's LLM auto-fix loop)-->  dev
dev  --(promote-dev-to-uat.yml: automatic, no human review)-->  uat
uat  --(a reviewed pull request, gated by uat-to-prd-gate.yml)-->  main
```

`main` represents "promoted to prd." It should only ever move forward
through a merged `uat -> main` pull request — never a direct push, and
never a PR from `dev` or any other branch.

## What healthy looks like

- `main`'s latest commit is an ancestor of `uat`'s latest commit.
- `uat`'s latest commit is at or behind `dev`'s.
- No open PR has sat for more than ~3 days without action.
- No open PR has a failing check that nobody's addressed.
- `promote-dev-to-uat.yml` and `uat-to-prd-gate.yml` aren't failing
  repeatedly for the same unaddressed reason (one expected failure while
  actively debugging a real procedure/connection issue is normal; a
  pattern of failures or a long-silent red run is not).

## Red flags — stop and look

- A commit on `main` that isn't reachable from any merged `uat -> main`
  PR — someone pushed directly to `main`, or merged `dev` (or a feature
  branch) straight into `main`, skipping `uat`.
- `uat` and `dev` diverging outside of the auto-merge commits
  `promote-dev-to-uat.yml` itself creates — suggests someone pushed to
  `uat` by hand.
- A stored procedure change (`procs/**.sql`) landing without a matching
  update to its golden suite (`tests/**.yaml`), or vice versa.
- `harness/evolve_cli.py --push` committing to `dev` without anyone having
  looked at the diff before it moved further (fine to land unreviewed on
  `dev` itself — that's the design — but it should get a human look before
  `uat -> main`).

## Last known-good state

Informal, human-readable log — not load-bearing, just "when did someone
last check this and it was fine." Append a line here (or let the weekly
check do it) rather than editing history.

- 2026-11-09: `main`, `uat`, `dev` converged after merging PR #6. Verified
  end-to-end against real Azure SQL (separate dev/uat databases): the
  planted fan-out bug in `sp_refresh_fact_sales.example.sql` was fixed and
  confirmed two independent ways — a manual fix, and separately via
  `harness/evolve_cli.py --provider deepseek` converging on a working fix
  in 2 iterations.
