"""Turns the DeepSeek data-governance sign-off from a comment nobody reads
into a real, technically-enforced gate. auto-fix-dev.yml calls this right
before calling DeepSeek; a missing or unapproved
infra/deepseek_governance_approval.yaml fails that step loudly instead of
silently sending a real company's procedure schema/logic to a China-based
provider without anyone actually having cleared that offshore transfer.

This does NOT mean the compliance work itself is done -- only that the
decision has to be made and recorded (via a reviewed PR editing that file)
before it can be bypassed, instead of being optional.
"""
import sys

import yaml


def check_deepseek_approved(path: str = "infra/deepseek_governance_approval.yaml") -> tuple[bool, str]:
    try:
        data = yaml.safe_load(open(path, encoding="utf-8")) or {}
    except FileNotFoundError:
        return False, (
            f"{path} not found. DeepSeek is a China-based provider; sending a real "
            f"procedure's schema/logic to it is an offshore data transfer that needs "
            f"data-governance sign-off first. Create this file (approved: false by "
            f"default) and have governance actually approve it before using --provider deepseek."
        )

    if not data.get("approved"):
        return False, (
            f"{path} says approved: false (or is missing that key). DeepSeek usage is "
            f"blocked until data governance signs off and someone sets approved: true "
            f"there, with approved_by/approved_at filled in, via a reviewed PR."
        )

    missing = [k for k in ("approved_by", "approved_at") if not data.get(k)]
    if missing:
        return False, (
            f"{path} says approved: true but is missing {missing} -- an approval record "
            f"needs who approved it and when, not just the flag flipped."
        )

    return True, f"approved by {data['approved_by']} on {data['approved_at']}"


def main(argv=None) -> int:
    path = argv[0] if argv else "infra/deepseek_governance_approval.yaml"
    approved, message = check_deepseek_approved(path)
    if approved:
        print(f"DeepSeek governance check: {message}")
        return 0
    print(f"::error::DeepSeek governance check failed: {message}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
