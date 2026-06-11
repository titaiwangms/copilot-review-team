#!/usr/bin/env python3
"""C2: each agents/local-*.agent.md has a well-formed frontmatter block.

- starts with '---' and has a closing '---'
- block contains keys: name, description, model, tools
- name value == filename minus '.agent.md'
- model value is a well-formed model id (matches MODEL_RE) — a malformed pin
  such as `model: [gpt-5.5]`, a block scalar, or an empty value is rejected,
  not just a missing key

Exit 0 if all pass, 1 otherwise.
"""
import os
import sys
import glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _lib_parsing import parse_frontmatter, MODEL_RE

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIRED = ("name", "description", "model", "tools")


def check_frontmatter(text, expected_name):
    """Return a list of error strings for one agent file's content.

    An empty list means the frontmatter is well-formed. `expected_name` is the
    agent name derived from the filename (the `name:` value must equal it).
    """
    errors = []
    fm, _ = parse_frontmatter(text)
    if fm is None:
        return ["missing or malformed '---' frontmatter block"]
    for key in REQUIRED:
        if key not in fm:
            errors.append("frontmatter missing key '%s'" % key)
    if fm.get("name") != expected_name:
        errors.append("name=%r but expected %r" % (fm.get("name"), expected_name))
    if "model" in fm and not MODEL_RE.match(fm["model"]):
        errors.append(
            "model value %r is malformed (allowed: letters, digits and . _ : -)"
            % fm["model"]
        )
    return errors


def main():
    ok = True
    files = sorted(glob.glob(os.path.join(REPO_ROOT, "agents", "local-*.agent.md")))
    if not files:
        print("  no agent files found")
        return 1
    for path in files:
        base = os.path.basename(path)
        expected_name = base[: -len(".agent.md")]
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        for error in check_frontmatter(text, expected_name):
            print("  %s: %s" % (base, error))
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
