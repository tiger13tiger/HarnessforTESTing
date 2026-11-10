"""Smoke-tests the four secrets promote-dev-to-uat.yml and auto-fix-dev.yml
depend on -- SYNAPSE_DEV_CONN_STR, SYNAPSE_UAT_CONN_STR, DEEPSEEK_API_KEY,
GH_PAT -- so a broken, stale, or misnamed secret shows up here as a clear
one-line result instead of surfacing mid-pipeline, confusingly, hours or days
later (exactly what happened with a stale password after a credential
rotation, and with GH_PAT silently missing).

Run it manually right after touching any of these in GitHub Settings ->
Secrets, or let .github/workflows/secrets-smoke-test.yml's schedule catch
drift on its own. Each check only reads (a trivial SELECT, a GET request) --
nothing here deploys, pushes, or spends a real LLM call.
"""
import os
import sys
import time

import requests

from harness.connector import SynapseConnector, TransientError

# A serverless Azure SQL database that's been idle overnight routinely needs
# a few seconds to resume on first contact -- harness/connector.py already
# retries this exact error class (TRANSIENT_AZURE_ERROR_NUMBERS, e.g. 40613)
# around transaction() for the real pipeline. This check used to call
# query() once with no retry at all, so the nightly schedule reported a
# healthy secret as "FAIL" every time it happened to catch the database
# mid-resume -- indistinguishable, in the log, from an actually-stale
# connection string.
SYNAPSE_QUERY_RETRIES = 3
SYNAPSE_QUERY_MAX_BACKOFF = 10


def check_synapse(env_var: str) -> tuple[bool, str]:
    try:
        connector = SynapseConnector(env_var=env_var)
    except RuntimeError as exc:
        return False, str(exc)
    last_exc: TransientError | None = None
    for attempt in range(SYNAPSE_QUERY_RETRIES + 1):
        try:
            connector.query("SELECT 1 AS ok")
            return True, "connected and queried successfully"
        except TransientError as exc:
            last_exc = exc
            if attempt < SYNAPSE_QUERY_RETRIES:
                time.sleep(min(2 ** (attempt + 1), SYNAPSE_QUERY_MAX_BACKOFF))
        except Exception as exc:  # noqa: BLE001 - a non-transient failure is a real finding, not a crash
            return False, f"{type(exc).__name__}: {exc}"
    return False, f"TransientError (gave up after {SYNAPSE_QUERY_RETRIES} retries): {last_exc}"


def check_deepseek() -> tuple[bool, str]:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        return False, "DEEPSEEK_API_KEY not set"
    try:
        # GET /models is DeepSeek's standard OpenAI-compatible auth check -- it
        # lists available models and doesn't spend a chat-completion call.
        response = requests.get(
            "https://api.deepseek.com/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=20,
        )
    except requests.RequestException as exc:
        return False, f"request failed: {exc}"
    if response.status_code == 200:
        return True, "key authenticates (GET /models)"
    return False, f"HTTP {response.status_code}: {response.text[:200]}"


def check_gh_pat() -> tuple[bool, str]:
    token = os.environ.get("GH_PAT")
    if not token:
        return False, "GH_PAT not set"
    try:
        response = requests.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {token}"},
            timeout=20,
        )
    except requests.RequestException as exc:
        return False, f"request failed: {exc}"
    if response.status_code != 200:
        return False, f"HTTP {response.status_code}: does not authenticate"
    login = response.json().get("login", "?")
    scopes = response.headers.get("X-OAuth-Scopes", "")
    # Fine-grained PATs don't report this header, so an empty value isn't itself
    # a failure -- only an explicit scope list missing 'repo' is.
    if scopes and "repo" not in scopes:
        return False, f"authenticates as {login} but missing 'repo' scope (has: {scopes})"
    detail = f" (scopes: {scopes})" if scopes else " (fine-grained token; scopes not reported by this header)"
    return True, f"authenticates as {login}{detail}"


def main() -> int:
    checks = [
        ("SYNAPSE_DEV_CONN_STR", lambda: check_synapse("SYNAPSE_DEV_CONN_STR")),
        ("SYNAPSE_UAT_CONN_STR", lambda: check_synapse("SYNAPSE_UAT_CONN_STR")),
        ("DEEPSEEK_API_KEY", check_deepseek),
        ("GH_PAT", check_gh_pat),
    ]
    print("Secrets smoke test -- confirms each secret actually authenticates, not just that it's set\n")
    all_ok = True
    for name, check in checks:
        ok, message = check()
        all_ok = all_ok and ok
        print(f"[{'OK  ' if ok else 'FAIL'}] {name}: {message}")
    print()
    if all_ok:
        print("All secrets check out.")
        return 0
    print("One or more secrets failed -- see above. Nothing was deployed or pushed by this check.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
