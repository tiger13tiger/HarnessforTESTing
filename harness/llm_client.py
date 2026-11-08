"""The LLM side of the auto-fix loop: given a failing stored procedure and the
checks it failed, ask a model for a corrected version. Real calls go through
Anthropic's API; tests use MockLLMClient so the loop logic can be proven
without burning API calls or needing a key.
"""
import os
import re
from dataclasses import dataclass


@dataclass
class FixSuggestion:
    sql: str
    rationale: str


class LLMClient:
    def suggest_fix(self, original_sql: str, failing_checks: list[dict], context: str) -> FixSuggestion:
        raise NotImplementedError


class MockLLMClient(LLMClient):
    """Returns pre-scripted fixes in order, for unit-testing the evolve loop."""

    def __init__(self, responses: list[FixSuggestion]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def suggest_fix(self, original_sql, failing_checks, context):
        self.calls.append({"original_sql": original_sql, "failing_checks": failing_checks, "context": context})
        if not self._responses:
            raise RuntimeError("MockLLMClient exhausted its scripted responses")
        return self._responses.pop(0)


class AnthropicLLMClient(LLMClient):
    def __init__(self, model: str = "claude-opus-5-5", api_key: str | None = None):
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")

    def suggest_fix(self, original_sql, failing_checks, context):
        import anthropic  # imported lazily: not needed unless a real fix is requested

        client = anthropic.Anthropic(api_key=self.api_key)
        prompt = _build_prompt(original_sql, failing_checks, context)
        response = client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text
        match = re.search(r"```sql\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
        sql = match.group(1).strip() if match else text.strip()
        return FixSuggestion(sql=sql, rationale=text)


def _build_prompt(original_sql: str, failing_checks: list[dict], context: str) -> str:
    checks_desc = "\n".join(
        f"- {c['id']}: {c['message']} (details: {c['details']})" for c in failing_checks
    )
    return f"""You are fixing a SQL Server / Azure Synapse stored procedure so its output \
matches verified business figures.

Context:
{context}

Current stored procedure:
```sql
{original_sql}
```

These validation checks failed after running it:
{checks_desc}

Return ONLY the corrected, complete `CREATE OR ALTER PROCEDURE ...` statement in a \
```sql code block. Do not change the procedure's name or schema. Keep the fix minimal \
and targeted at the failing checks."""
