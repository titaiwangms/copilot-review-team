#!/usr/bin/env python3
"""The set of agent names in the copilot-instructions.md team table equals the
set of agent files — no extra or missing rows. Model IDs live solely in the
agent frontmatter (single source of truth), so this check is purely about the
table's agent roster, not model values.
"""
import os
import re
import sys
import glob

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAYBOOK = os.path.join(REPO_ROOT, "copilot-instructions.md")
ROW_RE = re.compile(r"^\|\s*`(local-[a-z-]+)`\s*\|")

ok = True
for folder, documents in (
    ("agents", [PLAYBOOK]),
    ("extras/agents", glob.glob(os.path.join(REPO_ROOT, "extras", "instructions", "*.md"))),
):
    agent_files = {
        os.path.basename(p)[: -len(".agent.md")]
        for p in glob.glob(os.path.join(REPO_ROOT, folder, "local-*.agent.md"))
    }
    table_agents = set()
    for document in documents:
        with open(document, encoding="utf-8") as fh:
            for line in fh:
                m = ROW_RE.match(line.rstrip("\n"))
                if m:
                    table_agents.add(m.group(1))
    missing = sorted(agent_files - table_agents)
    extra = sorted(table_agents - agent_files)
    if missing:
        print("  %s agents missing from table: %s" % (folder, ", ".join(missing)))
        ok = False
    if extra:
        print("  %s table rows with no agent file: %s" % (folder, ", ".join(extra)))
        ok = False

sys.exit(0 if ok else 1)
