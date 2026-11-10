"""The LLM side of the auto-fix loop: given a failing stored procedure and the
checks it failed, ask a model for a corrected version. Real calls go through
Anthropic's API or DeepSeek's (pick with evolve_cli.py's --provider); tests
use MockLLMClient so the loop logic can be proven without burning API calls
or needing a key.
"""
import os
import re
from dataclasses import dataclass


@dataclass
class FixSuggestion:
    sql: str
    rationale: str
    usage: dict | None = None  # {"input_tokens": int, "output_tokens": int} when a real client set it


class LLMClient:
    def suggest_fix(self, original_sql: str, failing_checks: list[dict], context: str, stage: str = "validate") -> FixSuggestion:
        raise NotImplementedError


class MockLLMClient(LLMClient):
    """Returns pre-scripted fixes in order, for unit-testing the evolve loop."""

    def __init__(self, responses: list[FixSuggestion], model: str = "mock"):
        self._responses = list(responses)
        self.calls: list[dict] = []
        self.model = model  # evolve() reads this to tag each Iteration, same as a real client

    def suggest_fix(self, original_sql, failing_checks, context, stage="validate"):
        self.calls.append({"original_sql": original_sql, "failing_checks": failing_checks, "context": context, "stage": stage})
        if not self._responses:
            raise RuntimeError("MockLLMClient exhausted its scripted responses")
        return self._responses.pop(0)


class AnthropicLLMClient(LLMClient):
    def __init__(self, model: str = "claude-opus-5-5", api_key: str | None = None):
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")

    def suggest_fix(self, original_sql, failing_checks, context, stage="validate"):
        import anthropic  # imported lazily: not needed unless a real fix is requested

        client = anthropic.Anthropic(api_key=self.api_key)
        prompt = _build_prompt(original_sql, failing_checks, context, stage)
        response = client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text
        match = re.search(r"```sql\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
        sql = match.group(1).strip() if match else text.strip()
        usage = {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
        return FixSuggestion(sql=sql, rationale=text, usage=usage)


class DeepSeekLLMClient(LLMClient):
    """Same contract as AnthropicLLMClient, against DeepSeek's OpenAI-compatible API."""

    def __init__(self, model: str = "deepseek-chat", api_key: str | None = None, base_url: str = "https://api.deepseek.com"):
        self.model = model
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY not set")
        self.base_url = base_url.rstrip("/")

    def suggest_fix(self, original_sql, failing_checks, context, stage="validate"):
        import requests  # imported lazily, same reasoning as anthropic/pyodbc above

        prompt = _build_prompt(original_sql, failing_checks, context, stage)
        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 4096,
            },
            timeout=120,
        )
        response.raise_for_status()
        payload = response.json()
        text = payload["choices"][0]["message"]["content"]
        match = re.search(r"```sql\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
        sql = match.group(1).strip() if match else text.strip()
        raw_usage = payload.get("usage") or {}
        usage = {
            "input_tokens": raw_usage.get("prompt_tokens", 0),
            "output_tokens": raw_usage.get("completion_tokens", 0),
        }
        return FixSuggestion(sql=sql, rationale=text, usage=usage)


# Typed repair routing (SIRIUS-SQL's term for this): a deploy-time syntax error, a
# runtime EXEC error, and a wrong-data validation failure are different problems and
# get different guidance, instead of one generic "something failed" prompt.
STAGE_GUIDANCE = {
    "deploy": (
        "The CREATE OR ALTER PROCEDURE statement itself failed to deploy -- this is a "
        "T-SQL syntax or object-definition error, not a business-logic problem. Focus "
        "only on making it valid T-SQL: missing commas/semicolons, unmatched BEGIN/END, "
        "misspelled keywords, or a reference to a column/table that doesn't exist. Do "
        "not change the procedure's logic beyond what's needed to make it compile."
    ),
    "exec": (
        "The procedure deployed successfully but threw a runtime error when executed. "
        "Common causes: a referenced table/column that doesn't exist at runtime, a type "
        "conversion failure, a divide-by-zero, or a constraint violation (e.g. a "
        "duplicate key insert against a unique index). Focus on the specific statement "
        "that would raise this error, not on the final output shape."
    ),
    "validate": (
        "The procedure deployed and ran without error, but its output doesn't match the "
        "verified business figures -- this is a logic bug, not a syntax error. Common "
        "causes: a fan-out join inflating counts/sums, a missing or wrong WHERE filter, "
        "UNION vs UNION ALL double-counting or dropping rows, or GROUP BY at the wrong "
        "granularity. Check join conditions and grouping columns against what the gold "
        "figures imply."
    ),
}


def _build_prompt(original_sql: str, failing_checks: list[dict], context: str, stage: str = "validate") -> str:
    guidance = STAGE_GUIDANCE.get(stage, STAGE_GUIDANCE["validate"])
    checks_desc = "\n".join(
        f"- {c['id']}: {c['message']} (details: {c['details']})" for c in failing_checks
    )
    return f"""You are fixing a SQL Server / Azure Synapse stored procedure so its output \
matches verified business figures.

Context:
{context}

What went wrong (failed at the '{stage}' stage):
{guidance}

Current stored procedure:
```sql
{original_sql}
```

Specific error/check output:
{checks_desc}

Return ONLY the corrected, complete `CREATE OR ALTER PROCEDURE ...` statement in a \
```sql code block. Do not change the procedure's name or schema. Keep the fix minimal \
and targeted at the failing checks."""
