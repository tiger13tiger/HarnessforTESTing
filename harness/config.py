"""Loads and validates a test-suite YAML file."""
from pathlib import Path

import yaml

REQUIRED_CHECK_KEYS = {"id", "type", "params"}


def load_suite(path) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))

    if not isinstance(data.get("checks"), list) or not data["checks"]:
        raise ValueError("suite file must have a non-empty top-level 'checks' list")

    for check in data["checks"]:
        missing = REQUIRED_CHECK_KEYS - check.keys()
        if missing:
            raise ValueError(f"check {check.get('id', '?')} missing keys: {missing}")
        check.setdefault("category", "uncategorized")
        check.setdefault("severity", "blocker")
        check.setdefault("description", "")

    data.setdefault("suite", Path(path).stem)
    data.setdefault("version", "v1")
    return data
