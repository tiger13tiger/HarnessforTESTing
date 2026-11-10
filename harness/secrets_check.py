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

import requests

from harness.connector import SynapseConnector


def check_synapse(env_var: str) -> tuple[bool, str]:
    try:
        connector = SynapseConnector(env_var=env_var)
    except RuntimeError as exc:
        return False, str(exc)
    try:
        connector.query("SELECT 1 AS ok")
    except Exception as exc:  # noqa: BLE001 - any failure here is a finding to report, not a crash
        return False, f"{type(exc).__name__}: {exc}"
    return True, "connected and queried successfully"


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
