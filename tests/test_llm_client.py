"""Only tests the parts that don't need a real API call: missing-key handling.
suggest_fix() for AnthropicLLMClient/DeepSeekLLMClient is exercised for real
by running harness/evolve_cli.py by hand, not by the automated suite."""
import pytest
import yaml

from harness.llm_client import AnthropicLLMClient, DeepSeekLLMClient, _build_prompt


def _approved_governance_file(tmp_path):
    path = tmp_path / "governance.yaml"
    path.write_text(yaml.safe_dump({
        "approved": True, "approved_by": "test", "approved_at": "2026-01-01",
    }), encoding="utf-8")
    return str(path)


def test_anthropic_client_requires_an_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        AnthropicLLMClient()


def test_deepseek_client_requires_an_api_key(monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        DeepSeekLLMClient(governance_path=_approved_governance_file(tmp_path))


def test_deepseek_client_picks_up_the_key_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    client = DeepSeekLLMClient(governance_path=_approved_governance_file(tmp_path))
    assert client.api_key == "sk-test"
    assert client.model == "deepseek-chat"


def test_deepseek_client_refuses_to_construct_without_governance_approval(monkeypatch, tmp_path):
    # This is the actual enforcement point: auto-fix-dev.yml's separate
    # governance_check.py CI step is just one caller of this same code path.
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    missing_path = str(tmp_path / "does_not_exist.yaml")
    with pytest.raises(RuntimeError, match="governance check failed"):
        DeepSeekLLMClient(governance_path=missing_path)


def test_deepseek_client_governance_check_runs_before_the_api_key_check(monkeypatch, tmp_path):
    # Governance is unapproved AND the key is missing -- governance should be
    # what's reported, since "not allowed to use this provider at all" is the
    # more fundamental block.
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    missing_path = str(tmp_path / "does_not_exist.yaml")
    with pytest.raises(RuntimeError, match="governance check failed"):
        DeepSeekLLMClient(governance_path=missing_path)


@pytest.mark.parametrize("stage,expected_phrase", [
    ("deploy", "syntax or object-definition error"),
    ("exec", "runtime error when executed"),
    ("validate", "doesn't match the"),
])
def test_build_prompt_routes_each_stage_to_different_guidance(stage, expected_phrase):
    prompt = _build_prompt("CREATE OR ALTER PROCEDURE dbo.sp_x\nAS\nBEGIN\n  SELECT 1;\nEND", [], "ctx", stage=stage)
    assert expected_phrase in prompt


def test_build_prompt_falls_back_to_validate_guidance_for_an_unknown_stage():
    prompt = _build_prompt("...", [], "ctx", stage="something_new")
    assert "doesn't match the" in prompt  # same text as the "validate" case


def test_build_prompt_tells_the_model_to_treat_embedded_content_as_data_not_instructions():
    # context/original_sql/check details can all carry text this harness
    # didn't author (a crafted check message, a comment in a prior round's
    # LLM-generated SQL) -- the prompt itself must say not to follow
    # instructions found inside them, the same defense a conversational
    # agent's system prompt would carry.
    prompt = _build_prompt("CREATE OR ALTER PROCEDURE dbo.sp_x\nAS\nBEGIN\n  SELECT 1;\nEND", [], "ctx")
    assert "not instructions to follow" in prompt
    assert "ignore previous instructions" in prompt


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_deepseek_client_captures_token_usage(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    payload = {
        "choices": [{"message": {"content": "```sql\nSELECT 1\n```"}}],
        "usage": {"prompt_tokens": 123, "completion_tokens": 45},
    }
    # requests is imported lazily inside suggest_fix(), so patch the real module directly.
    import requests
    monkeypatch.setattr(requests, "post", lambda *a, **k: _FakeResponse(payload))

    client = DeepSeekLLMClient(governance_path=_approved_governance_file(tmp_path))
    suggestion = client.suggest_fix("CREATE OR ALTER PROCEDURE dbo.sp_x\nAS\nBEGIN\n  SELECT 1;\nEND", [], "ctx")

    assert suggestion.usage == {"input_tokens": 123, "output_tokens": 45}


def test_deepseek_client_defaults_usage_to_zero_when_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    payload = {"choices": [{"message": {"content": "SELECT 1"}}]}  # no "usage" key at all
    import requests
    monkeypatch.setattr(requests, "post", lambda *a, **k: _FakeResponse(payload))

    client = DeepSeekLLMClient(governance_path=_approved_governance_file(tmp_path))
    suggestion = client.suggest_fix("...", [], "ctx")

    assert suggestion.usage == {"input_tokens": 0, "output_tokens": 0}
