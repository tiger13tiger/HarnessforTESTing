"""Runs every attack in infra/guardrail_attacks.yaml and asserts the harness
actually catches it -- this project's equivalent of bank-data-agent-eval's
injection_set.jsonl + eval_safety(), sized to this harness's own attack
surface (a stored-procedure auto-fix loop, not a conversational agent).

Before this file existed, 128 tests checked "does the correctness logic
work" and zero checked "can a malicious or confused LLM response defeat our
guardrails" -- this is the structural gap that closes."""
from pathlib import Path

import pytest
import yaml

from harness.guardrails import GuardrailViolation, check_candidate_sql, contains_likely_leak

ATTACKS = yaml.safe_load(Path("infra/guardrail_attacks.yaml").read_text(encoding="utf-8"))["attacks"]
SQL_ATTACKS = [a for a in ATTACKS if a["kind"] == "sql"]
LEAK_ATTACKS = [a for a in ATTACKS if a["kind"] == "rationale_leak"]


def test_the_catalog_itself_is_well_formed():
    # A typo in the catalog (a missing "kind", a duplicate id) would
    # otherwise silently drop an attack from parametrization instead of
    # failing loudly -- this catches that before it hides a real gap.
    ids = [a["id"] for a in ATTACKS]
    assert len(ids) == len(set(ids)), "duplicate attack id in infra/guardrail_attacks.yaml"
    assert len(SQL_ATTACKS) + len(LEAK_ATTACKS) == len(ATTACKS), "every attack must be kind: sql or kind: rationale_leak"
    assert len(ATTACKS) >= 10


@pytest.mark.parametrize("attack", SQL_ATTACKS, ids=[a["id"] for a in SQL_ATTACKS])
def test_sql_attack_is_blocked(attack, tmp_path):
    blocked_tables_path = "infra/blocked_tables.yaml"
    if attack.get("blocked_tables"):
        blocked_tables_path = str(tmp_path / "blocked_tables.yaml")
        Path(blocked_tables_path).write_text(
            yaml.safe_dump({"tables": attack["blocked_tables"]}), encoding="utf-8",
        )

    with pytest.raises(GuardrailViolation, match=".+"):  # must raise with a real, non-empty reason
        check_candidate_sql(attack["payload"], allowed_schema=attack["allowed_schema"], blocked_tables_path=blocked_tables_path)


@pytest.mark.parametrize("attack", LEAK_ATTACKS, ids=[a["id"] for a in LEAK_ATTACKS])
def test_rationale_leak_attack_is_caught(attack):
    assert contains_likely_leak(attack["payload"]) is not None
