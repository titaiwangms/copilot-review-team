#!/usr/bin/env python3
"""C2: each agents/local-*.agent.md has a well-formed frontmatter block.

- starts with '---' and has a closing '---'
- block contains keys: name, description, model, tools
- name value == filename minus '.agent.md'

Exit 0 if all pass, 1 otherwise.
"""
import os
import sys
import glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib_parsing import parse_frontmatter

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
        fm, _ = parse_frontmatter(fh.read())
    if fm is None:
        print("  %s: missing or malformed '---' frontmatter block" % base)
        ok = False
        continue
    for key in REQUIRED:
        if key not in fm:
            print("  %s: frontmatter missing key '%s'" % (base, key))
            ok = False
    if fm.get("name") != expected_name:
        print("  %s: name=%r but expected %r" % (base, fm.get("name"), expected_name))
        ok = False

sys.exit(0 if ok else 1)
