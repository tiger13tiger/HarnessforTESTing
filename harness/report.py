"""Writes report.md (human-readable), results.csv (full detail) and summary.json
(for a CI step or a chat notification), and computes the pass/fail gate."""
import csv
import json
from pathlib import Path


def gate_failed(results) -> bool:
    return any(r.status == "error" for r in results) or any(
        r.status == "fail" and r.severity == "blocker" for r in results
    )


def write_reports(results, suite_name: str, suite_version: str, output_dir) -> dict:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    total = len(results)
    passed = [r for r in results if r.status == "pass"]
    failed = [r for r in results if r.status == "fail"]
    errored = [r for r in results if r.status == "error"]
    gate_fail = gate_failed(results)

    lines = [
        f"# UAT Test Report — {suite_name} ({suite_version})",
        "",
        f"- Total checks: {total}",
        f"- Passed: {len(passed)}",
        f"- Failed: {len(failed)}",
        f"- Errored: {len(errored)}",
        f"- Gate: {'FAIL' if gate_fail else 'PASS'}",
        "",
        "| id | category | severity | status | message | duration(ms) |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(f"| {r.id} | {r.category} | {r.severity} | {r.status} | {r.message} | {r.duration_ms:.0f} |")

    if failed or errored:
        lines += ["", "## Failures / Errors", ""]
        for r in failed + errored:
            lines.append(f"### {r.id} ({r.status})")
            lines.append(f"- category: {r.category}")
            lines.append(f"- severity: {r.severity}")
            lines.append(f"- message: {r.message}")
            if r.details:
                lines.append(f"- details: `{r.details}`")
            lines.append("")

    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")

    with (output_dir / "results.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "category", "severity", "status", "message", "duration_ms", "details"])
        for r in results:
            writer.writerow([r.id, r.category, r.severity, r.status, r.message, f"{r.duration_ms:.1f}", r.details])

    summary = {
        "suite": suite_name,
        "version": suite_version,
        "total": total,
        "passed": len(passed),
        "failed": len(failed),
        "errored": len(errored),
        "gate": "fail" if gate_fail else "pass",
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

    return summary


def _closest_iteration(history):
    """The validate-stage attempt with the fewest non-pass checks, as a consolation
    pointer when every attempt failed -- "closest" by check count, not a guarantee
    it was semantically closer to correct."""
    candidates = [it for it in history if it.stage == "validate" and it.results]
    if not candidates:
        return None
    return min(candidates, key=lambda it: sum(1 for r in it.results if r.status != "pass"))


def _final_fix_rationale(success: bool, history) -> str | None:
    """The LLM's own explanation for the candidate that actually passed -- that
    rationale lives on the iteration BEFORE the last one (evolve() attaches it to
    the failing attempt that prompted the fix, not to the fix itself). None if the
    loop failed outright, or if the very first attempt already passed (no fix was
    ever requested). Surfaced in the commit message an auto-fix push makes, so a
    human reviewing the eventual uat -> main PR sees why an LLM changed what it
    changed, not just the final diff."""
    if not success or len(history) < 2:
        return None
    return history[-2].rationale


def write_evolve_report(success: bool, history, output_dir) -> dict:
    """Writes evolve_report.md / evolve_summary.json for the auto-fix loop in harness/evolve.py."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    lines = [
        "# Stored Procedure Auto-Fix Report",
        "",
        f"- Result: {'PASS' if success else 'FAIL (exhausted iterations without a human reviewing them)'}",
        f"- Iterations: {len(history)}",
        "",
    ]
    for it in history:
        lines.append(f"## Attempt {it.attempt} (stage: {it.stage})")
        if it.stage in ("guardrail", "connect", "deploy", "exec", "llm"):
            label = {
                "guardrail": "blocked by guardrail (never deployed)",
                "connect": "could not open a connection after retries",
                "deploy": "deploy failed, rolled back",
                "exec": "EXEC failed, rolled back",
                "llm": "could not get a fix from the LLM",
            }[it.stage]
            lines.append(f"- **{label}:** {it.error}")
            lines.append("")
            continue
        lines.append(f"- gate: {'FAIL' if it.gate_failed else 'PASS'}")
        lines.append(f"- {'rolled back (candidate discarded)' if it.gate_failed else 'committed'}")
        for r in it.results:
            lines.append(f"  - `{r.id}` ({r.category}, {r.severity}): **{r.status}** — {r.message}")
        if it.rationale:
            lines += ["", "<details><summary>LLM rationale for the next candidate</summary>", "", it.rationale, "", "</details>"]
        lines.append("")

    closest = _closest_iteration(history) if not success else None
    if closest is not None:
        failing_count = sum(1 for r in closest.results if r.status != "pass")
        lines += [
            "## Closest attempt",
            "",
            f"Attempt {closest.attempt} had the fewest failing checks ({failing_count}/{len(closest.results)}). "
            "Not a guarantee it was semantically closest to correct -- just the smallest failure count.",
            "",
        ]

    (output_dir / "evolve_report.md").write_text("\n".join(lines), encoding="utf-8")

    summary = {
        "success": success,
        "iterations": len(history),
        "closest_attempt": closest.attempt if closest is not None else None,
        "rationale": _final_fix_rationale(success, history),
    }
    (output_dir / "evolve_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary
