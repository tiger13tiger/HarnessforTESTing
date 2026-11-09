"""Only tests the parts that don't need a real API call: missing-key handling.
suggest_fix() for AnthropicLLMClient/DeepSeekLLMClient is exercised for real
by running harness/evolve_cli.py by hand, not by the automated suite."""
import pytest

from harness.llm_client import AnthropicLLMClient, DeepSeekLLMClient, _build_prompt


def test_anthropic_client_requires_an_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        AnthropicLLMClient()


def test_deepseek_client_requires_an_api_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        DeepSeekLLMClient()


def test_deepseek_client_picks_up_the_key_from_the_environment(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    client = DeepSeekLLMClient()
    assert client.api_key == "sk-test"
    assert client.model == "deepseek-chat"


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
