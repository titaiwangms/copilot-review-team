#!/usr/bin/env python3
"""C7: least-privilege tool grants in agent frontmatter.

Parses each agents/local-*.agent.md frontmatter `tools:` list and asserts the
team's privilege invariants:

  - every *-reviewer.agent.md has `read` and `search` but NOT `edit`
    (reviewers must never be able to modify code)
  - local-developer and local-tech-writer have `edit`
  - local-qa-tester has `shell`

The rules below are intentionally explicit and easy to update if the team's
privilege model changes.

Exit 0 if all pass, 1 otherwise.
"""
import os
import re
import sys
import glob

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Per-agent required / forbidden tools. Keyed by agent basename (sans
# .agent.md). Reviewers are handled by the *-reviewer suffix rule below.
REQUIRED = {
    "local-developer": ["edit"],
    "local-tech-writer": ["edit"],
    "local-qa-tester": ["shell"],
}
# Rule applied to every agent whose name ends in "-reviewer".
REVIEWER_REQUIRED = ["read", "search"]
REVIEWER_FORBIDDEN = ["edit"]


def parse_tools(path):
    """Return the list of tool names from the frontmatter `tools:` block.

    The block looks like:
        tools:
          - read
          - search
    Parsing stops at the closing '---' or the next top-level key.
    """
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return None
    tools = None
    for i in range(1, end):
        line = lines[i]
        if re.match(r"^tools:\s*$", line):
            tools = []
            for j in range(i + 1, end):
                item = re.match(r"^\s+-\s*(\S+)\s*$", lines[j])
                if item:
                    tools.append(item.group(1))
                elif lines[j].strip() == "":
                    continue
                else:
                    # next top-level key ends the list
                    break
            break
    return tools


ok = True
files = sorted(glob.glob(os.path.join(REPO_ROOT, "agents", "local-*.agent.md")))
if not files:
    print("  no agent files found")
    sys.exit(1)

for path in files:
    base = os.path.basename(path)
    name = base[: -len(".agent.md")]
    tools = parse_tools(path)
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
