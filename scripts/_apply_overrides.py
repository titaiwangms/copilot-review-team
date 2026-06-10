#!/usr/bin/env python3
"""Apply an optional model-override file to a staging copy of the agent files.

Used by install.sh ONLY. Reads the override file at $OVERRIDE_FILE, copies every
agents/local-*.agent.md from $SRC_AGENTS into $STAGE_DIR, and rewrites the
`model:` line of any agent the override targets (an explicit entry, or the '*'
wildcard for "all agents"). The repo's own files are never modified — install.sh
installs from the staging dir, so overrides affect only ~/.copilot copies.

Fails (nonzero) on a malformed override file or an override that names an agent
which does not exist, so a typo can't silently no-op.
"""
import os
import sys
import glob
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib_parsing import (
    ParseError,
    load_overrides,
    resolve_model,
    set_frontmatter_model,
)

override_file = os.environ["OVERRIDE_FILE"]
src_agents = os.environ["SRC_AGENTS"]
stage_dir = os.environ["STAGE_DIR"]


def die(message):
    sys.stderr.write("error: " + message + "\n")
    sys.exit(1)


try:
    overrides = load_overrides(override_file)
except (ParseError, OSError) as exc:
    die(str(exc))

sources = sorted(glob.glob(os.path.join(src_agents, "local-*.agent.md")))
agent_names = {os.path.basename(p)[: -len(".agent.md")] for p in sources}

unknown = sorted(k for k in overrides if k != "*" and k not in agent_names)
if unknown:
    die(
        "model override names unknown agent(s): %s (in %s)"
        % (", ".join(unknown), override_file)
    )

os.makedirs(stage_dir, exist_ok=True)
applied = []
for src in sources:
    base = os.path.basename(src)
    agent = base[: -len(".agent.md")]
    dest = os.path.join(stage_dir, base)
    with open(src, encoding="utf-8") as fh:
        text = fh.read()
    model = resolve_model(overrides, agent)
    if model is not None:
        try:
            new_text = set_frontmatter_model(text, model)
        except ParseError as exc:
            die("%s: %s" % (base, exc))
        if new_text != text:
            text = new_text
            applied.append("%s -> %s" % (agent, model))
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(text)
    shutil.copymode(src, dest)

for line in applied:
    print("    " + line)
sys.exit(0)
