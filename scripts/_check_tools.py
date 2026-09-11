#!/usr/bin/env python3
"""C6: least-privilege tool grants in agent frontmatter.

Reads each agents/local-*.agent.md frontmatter `tools:` list (via the shared
parser in _lib_parsing) and asserts the team's privilege invariants:

  - every full reviewer and lightweight review agent has `read` and `search`
    but NOT `edit`
    (reviewers must never be able to modify code)
  - local-qa-tester has `shell`

The rules below are intentionally explicit and easy to update if the team's
privilege model changes.

Exit 0 if all pass, 1 otherwise.
"""
import os
import sys
import glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib_parsing import parse_tools

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Per-agent required tools, keyed by agent basename (sans .agent.md). Full
# reviewers and lightweight review agents are handled by naming rules below.
REQUIRED = {
    "local-qa-tester": ["shell"],
}
# Rule applied to every full reviewer whose name ends in "-reviewer".
REVIEWER_REQUIRED = ["read", "search"]
REVIEWER_FORBIDDEN = ["edit"]
LIGHTWEIGHT_REVIEW_TOOLS = {"read", "search"}


def tool_policy_errors(name, tools):
    """Return privilege-policy errors for one parsed agent tool list."""
    errors = []
    if name.endswith("-reviewer"):
        for tool in REVIEWER_REQUIRED:
            if tool not in tools:
                errors.append("reviewer missing required tool '%s'" % tool)
        for tool in REVIEWER_FORBIDDEN:
            if tool in tools:
                errors.append("reviewer must NOT have tool '%s'" % tool)

    if name.startswith("local-lightweight-"):
        actual = set(tools)
        if actual != LIGHTWEIGHT_REVIEW_TOOLS:
            errors.append(
                "lightweight review tools must be exactly %s, found %s"
                % (
                    sorted(LIGHTWEIGHT_REVIEW_TOOLS),
                    sorted(actual),
                )
            )

    for tool in REQUIRED.get(name, []):
        if tool not in tools:
            errors.append("missing required tool '%s'" % tool)
    return errors

def main():
    ok = True
    files = sorted(glob.glob(os.path.join(REPO_ROOT, "agents", "local-*.agent.md")))
    if not files:
        print("  no agent files found")
        return 1

    for path in files:
        base = os.path.basename(path)
        name = base[: -len(".agent.md")]
        with open(path, encoding="utf-8") as fh:
            tools = parse_tools(fh.read())
        if tools is None:
            print("  %s: could not parse tools: list" % base)
            ok = False
            continue

        for error in tool_policy_errors(name, tools):
            print("  %s: %s" % (base, error))
            ok = False

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
