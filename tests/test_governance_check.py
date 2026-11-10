"""Tests harness/governance_check.py -- the real, enforced gate on DeepSeek
usage, not just a comment. No real file in infra/ needed; each test writes
its own fixture."""
import yaml

from harness.governance_check import check_deepseek_approved, main


def _write(tmp_path, data):
    path = tmp_path / "approval.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return str(path)


def test_missing_file_is_not_approved(tmp_path):
    approved, message = check_deepseek_approved(str(tmp_path / "does_not_exist.yaml"))
    assert not approved
    assert "not found" in message


def test_approved_false_is_not_approved(tmp_path):
    path = _write(tmp_path, {"approved": False, "approved_by": "", "approved_at": ""})
    approved, message = check_deepseek_approved(path)
    assert not approved
    assert "approved: false" in message


def test_approved_true_without_approver_fields_is_not_approved(tmp_path):
    path = _write(tmp_path, {"approved": True, "approved_by": "", "approved_at": ""})
    approved, message = check_deepseek_approved(path)
    assert not approved
    assert "approved_by" in message


def test_approved_true_with_both_fields_filled_in_is_approved(tmp_path):
    path = _write(tmp_path, {
        "approved": True, "approved_by": "Jane Doe (Data Governance)", "approved_at": "2026-01-15",
    })
    approved, message = check_deepseek_approved(path)
    assert approved
    assert "Jane Doe" in message
    assert "2026-01-15" in message


def test_main_returns_1_and_prints_error_when_not_approved(tmp_path, capsys):
    path = _write(tmp_path, {"approved": False})
    exit_code = main([path])
    assert exit_code == 1
    assert "::error::" in capsys.readouterr().err


def test_main_returns_0_when_approved(tmp_path, capsys):
    path = _write(tmp_path, {"approved": True, "approved_by": "Jane", "approved_at": "2026-01-15"})
    exit_code = main([path])
    assert exit_code == 0
