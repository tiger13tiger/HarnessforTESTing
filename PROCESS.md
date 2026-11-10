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
dev  --(promote-dev-to-uat.yml "promote" job: automatic)-->  uat (merged)
uat (merged)  --(promote-dev-to-uat.yml "validate-after-merge" job)-->  uat (confirmed ready)
                    |                                    |
                    | either job can fail --> auto-fix-dev.yml (reusable):
                    | sends the failure back to an LLM against dev, pushes
                    | a fix, re-triggers promote-dev-to-uat.yml from the
                    | top (max 3 rounds total, shared by both jobs)
                    v
                   dev
uat (confirmed ready)  --(a reviewed pull request, gated by uat-to-prd-gate.yml)-->  main
```

`main` represents "promoted to prd." It should only ever move forward
through a merged `uat -> main` pull request — never a direct push, and
never a PR from `dev` or any other branch.

## What healthy looks like

- `main`'s latest commit is an ancestor of `uat`'s latest commit.
- `uat`'s latest commit is at or behind `dev`'s.
- No open PR has sat for more than ~3 days without action.
- No open PR has a failing check that nobody's addressed.
- `promote-dev-to-uat.yml` (both its `promote` and `validate-after-merge`
  jobs) and `uat-to-prd-gate.yml` aren't failing repeatedly for the same
  unaddressed reason (one expected failure while actively debugging a real
  procedure/connection issue is normal; a pattern of failures or a
  long-silent red run is not).
- A `promote` job passing doesn't by itself mean `uat` is ready — check
  that `validate-after-merge` also passed on the same run before treating
  `uat` as safe to open a PR from.
- `secrets-smoke-test.yml` is passing (run it by hand after touching any
  secret, or trust its daily schedule) — `SYNAPSE_DEV_CONN_STR`,
  `SYNAPSE_UAT_CONN_STR`, `DEEPSEEK_API_KEY`, and `GH_PAT` all actually
  authenticate, not just exist.
- Every procedure in `procs/manifest.yaml` is passing `promote` and
  `validate-after-merge` on the same run — a manifest with more than one
  procedure means "uat is ready" requires *all* of them clean, not just
  the one you happen to be watching.
- `python -m harness.metrics_cli` shows a success rate that isn't quietly
  degrading, and a cost that isn't quietly climbing — worth a glance
  periodically, not just when something's already visibly broken.
- `tests.yml` is passing on `dev`/`uat`/`main` — it runs the full unit
  suite on every push with no path filter, unlike `promote-dev-to-uat.yml`
  and `uat-to-prd-gate.yml`'s own pytest steps, which only fire alongside a
  `procs/**.sql`/`tests/**.yaml` change. A `harness/**.py`-only change
  still won't trigger live UAT validation (correct — it doesn't need a
  database round-trip), but it should still show a green `tests.yml` run.

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
- `auto-fix-dev.yml` hitting its 3-round cap (an `::error::` from its
  "Determine round number" step, with no further commits following it) and
  nobody looking at why the LLM couldn't converge — this is the one case in
  the dev -> uat step that's supposed to stop and wait for a human instead
  of resolving itself. The cap is shared: it can be reached from either
  `promote` failing or `validate-after-merge` failing, so check which one
  triggered it.
- A `[auto-fix round N/3]` commit on `dev` that changes nothing at all —
  not even `reports/metrics_log.jsonl` — would indicate the no-op guard in
  that job's push step isn't doing what it's supposed to. (A round where
  the procedure file itself didn't change but the metrics log did is
  normal and expected: that's what a non-convergent attempt looks like.)
- `infra/deepseek_governance_approval.yaml` showing `approved: true` with
  no real sign-off behind it — that file going from `false` to `true`
  should only ever happen as its own reviewed change, with
  `approved_by`/`approved_at` actually filled in, not bundled quietly
  into an unrelated commit.
- `validate-after-merge` failing on a run where `promote` passed — the
  candidate alone was fine, but something about the merge or the UAT
  database's state right after wasn't. Worth a closer look even once the
  auto-fix loop resolves it, since it's not a case the pre-merge check was
  ever designed to catch.
- A `uat -> main` PR opened or merged without that PR's run of
  `uat-to-prd-gate.yml` showing a passing `validate-after-merge` on the
  commit it's built from.
- A `uat -> main` PR merged without reading the 🤖 auto-fix-summary
  comment, when `uat-to-prd-gate.yml` posted one — it means at least one
  commit in that PR was LLM-generated, not human-written, and nobody's
  own eyes have been on its rationale yet.
- `secrets-smoke-test.yml` failing (on its daily schedule or a manual run)
  with nobody looking into which secret broke and why.

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
