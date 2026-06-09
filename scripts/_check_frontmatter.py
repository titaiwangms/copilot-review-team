#!/usr/bin/env python3
"""C2: each agents/local-*.agent.md has a well-formed frontmatter block.

- starts with '---' and has a closing '---'
- block contains keys: name, description, model, tools
- name value == filename minus '.agent.md'

Exit 0 if all pass, 1 otherwise.
"""
import os
import re
import sys
import glob

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIRED = ("name", "description", "model", "tools")

ok = True
files = sorted(glob.glob(os.path.join(REPO_ROOT, "agents", "local-*.agent.md")))
if not files:
    print("  no agent files found")
    sys.exit(1)

for path in files:
    base = os.path.basename(path)
    expected_name = base[: -len(".agent.md")]
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    if not lines or lines[0].strip() != "---":
        print("  %s: missing opening '---'" % base)
        ok = False
        continue
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        print("  %s: missing closing '---'" % base)
        ok = False
        continue
    fm = {}
    for line in lines[1:end]:
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if m:
            fm[m.group(1)] = m.group(2).strip()
    for key in REQUIRED:
        if key not in fm:
            print("  %s: frontmatter missing key '%s'" % (base, key))
            ok = False
    if fm.get("name") != expected_name:
        print("  %s: name=%r but expected %r" % (base, fm.get("name"), expected_name))
        ok = False

sys.exit(0 if ok else 1)
