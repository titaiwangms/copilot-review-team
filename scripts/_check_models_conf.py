#!/usr/bin/env python3
"""C4: models.conf is consistent with the canonical frontmatter.

- every entry in models.conf matches the current frontmatter model for that agent
- the set of agents in models.conf == the set of agent files
"""
import os
import re
import sys
import glob

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONF = os.path.join(REPO_ROOT, "models.conf")


def frontmatter_model(path):
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            break
        m = re.match(r"^model:\s*(.*)$", lines[i])
        if m:
            return m.group(1).strip()
    return None


agents = {}
for p in glob.glob(os.path.join(REPO_ROOT, "agents", "local-*.agent.md")):
    name = os.path.basename(p)[: -len(".agent.md")]
    agents[name] = frontmatter_model(p)

conf = {}
ok = True
with open(CONF, encoding="utf-8") as fh:
    for lineno, raw in enumerate(fh, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        tokens = [t for t in re.split(r"[\s=]+", line) if t]
        if len(tokens) != 2:
            print("  models.conf line %d malformed: %r" % (lineno, raw.rstrip()))
            ok = False
            continue
        agent, model = tokens
        # Reject duplicate agent entries, matching set-models.sh's
        # load_mapping (which fails on duplicates). Without this, a second
        # entry would silently overwrite the first and C4 could pass.
        if agent in conf:
            print("  models.conf line %d: duplicate agent entry %r" % (lineno, agent))
            ok = False
            continue
        conf[agent] = model

missing = sorted(set(agents) - set(conf))
extra = sorted(set(conf) - set(agents))
if missing:
    print("  agents missing from models.conf: %s" % ", ".join(missing))
    ok = False
if extra:
    print("  models.conf entries with no agent file: %s" % ", ".join(extra))
    ok = False

for agent, model in conf.items():
    if agent in agents and agents[agent] != model:
        print("  %s: models.conf=%s frontmatter=%s" % (agent, model, agents[agent]))
        ok = False

sys.exit(0 if ok else 1)
