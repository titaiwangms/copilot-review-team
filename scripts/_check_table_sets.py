#!/usr/bin/env python3
"""C3 (supplement): the set of agent names in the copilot-instructions.md
table equals the set of agent files. set-models.sh --check already compares
the per-agent model values; this asserts there are no extra or missing rows.
"""
import os
import re
import sys
import glob

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAYBOOK = os.path.join(REPO_ROOT, "copilot-instructions.md")
ROW_RE = re.compile(r"^\|\s*`(local-[a-z-]+)`\s*\|")

agent_files = {
    os.path.basename(p)[: -len(".agent.md")]
    for p in glob.glob(os.path.join(REPO_ROOT, "agents", "local-*.agent.md"))
}

table_agents = set()
with open(PLAYBOOK, encoding="utf-8") as fh:
    for line in fh:
        m = ROW_RE.match(line.rstrip("\n"))
        if m:
            table_agents.add(m.group(1))

ok = True
missing = sorted(agent_files - table_agents)
extra = sorted(table_agents - agent_files)
if missing:
    print("  agents missing from table: %s" % ", ".join(missing))
    ok = False
if extra:
    print("  table rows with no agent file: %s" % ", ".join(extra))
    ok = False

sys.exit(0 if ok else 1)
