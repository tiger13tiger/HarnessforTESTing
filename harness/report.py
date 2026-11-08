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
