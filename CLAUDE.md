# Working in this repo

## Keep docs/architecture.html in sync

`docs/architecture.html` is the maintained architecture diagram for this
project: the dev -> uat -> main pipeline (Fig. 1) and the evolve() fix loop
internals (Fig. 2), plus the check-types table and module map.

**Whenever a change affects what either figure shows, update the diagram in
the same piece of work** -- don't let it drift into a stale picture of a
pipeline that no longer exists. Concretely, touch it when:

- A workflow's trigger, steps, or gate logic changes (`.github/workflows/*.yml`)
- The branch model changes (adding/removing/renaming dev/uat/main, or how
  promotion between them works)
- `harness/evolve.py` or `harness/promote.py`'s control flow changes (new
  stage, different retry/rollback behavior, different transaction scope)
- A check type is added, removed, or changes what it catches
  (`harness/checks/*.py` -- update the Fig. 2-adjacent reference table)
- Module layout changes enough that the "Where things live" tree is wrong

Small wording fixes elsewhere in the repo don't need a diagram update --
this is about the diagram staying an accurate picture of the mechanism, not
about touching it on every commit.

To edit: `docs/architecture.html` is a single self-contained HTML file
(inline SVG, no build step). Follow the same dev -> uat -> main flow as any
other change -- it doesn't trigger either GitHub Actions workflow (its path
doesn't match `procs/**.sql` or `tests/**.yaml`), so there's no CI signal to
wait on, but it should still go through a reviewed `uat -> main` PR rather
than a direct push to `main`, per `PROCESS.md`.

See `PROCESS.md` for what a healthy pipeline state looks like more broadly.
