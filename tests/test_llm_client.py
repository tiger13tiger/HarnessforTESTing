"""Only tests the parts that don't need a real API call: missing-key handling.
suggest_fix() for AnthropicLLMClient/DeepSeekLLMClient is exercised for real
by running harness/evolve_cli.py by hand, not by the automated suite."""
import pytest

from harness.llm_client import AnthropicLLMClient, DeepSeekLLMClient


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
