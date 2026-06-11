#!/usr/bin/env python3
"""C6: least-privilege tool grants in agent frontmatter.

Reads each agents/local-*.agent.md frontmatter `tools:` list (via the shared
parser in _lib_parsing) and asserts the team's privilege invariants:

  - every *-reviewer.agent.md has `read` and `search` but NOT `edit`
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

# Per-agent required tools, keyed by agent basename (sans .agent.md). Reviewers
# are handled by the *-reviewer suffix rule below.
REQUIRED = {
    "local-qa-tester": ["shell"],
}
# Rule applied to every agent whose name ends in "-reviewer".
REVIEWER_REQUIRED = ["read", "search"]
REVIEWER_FORBIDDEN = ["edit"]

ok = True
files = sorted(glob.glob(os.path.join(REPO_ROOT, "agents", "local-*.agent.md")))
if not files:
    print("  no agent files found")
    sys.exit(1)

for path in files:
    base = os.path.basename(path)
    name = base[: -len(".agent.md")]
    with open(path, encoding="utf-8") as fh:
        tools = parse_tools(fh.read())
    if tools is None:
        print("  %s: could not parse tools: list" % base)
        ok = False
        continue

    if name.endswith("-reviewer"):
        for t in REVIEWER_REQUIRED:
            if t not in tools:
                print("  %s: reviewer missing required tool '%s'" % (base, t))
                ok = False
        for t in REVIEWER_FORBIDDEN:
            if t in tools:
                print("  %s: reviewer must NOT have tool '%s'" % (base, t))
                ok = False

    for t in REQUIRED.get(name, []):
        if t not in tools:
            print("  %s: missing required tool '%s'" % (base, t))
            ok = False

sys.exit(0 if ok else 1)
