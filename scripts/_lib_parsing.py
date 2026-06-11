"""Shared parsing helpers for the Copilot review-team tooling.

This module is the single home for the small amount of frontmatter parsing the
repo's checkers need, so they don't each hand-roll their own copy (which
previously drifted). No third-party deps (no PyYAML): agent frontmatter is a
constrained, machine-written subset, so a tiny purpose-built parser is clearer
and dependency-free.

Public API:
    parse_frontmatter(text) -> (dict | None, end_index | None)
    parse_tools(text)       -> list[str] | None
"""
import re

# A model id is a constrained token (letters, digits and . _ : -). The
# frontmatter checker validates `model:` values against this so a malformed or
# malicious value can't slip through.
MODEL_RE = re.compile(r"^[A-Za-z0-9._:-]+$")


def _frontmatter_bounds(lines):
    """Return the line index of the closing '---' of a leading frontmatter block.

    Returns None if `lines` does not open with '---' or has no closing '---'.
    Works with lines from either splitlines() or splitlines(keepends=True),
    since the comparison strips trailing whitespace/newlines.
    """
    if not lines or lines[0].strip() != "---":
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return i
    return None


def parse_frontmatter(text):
    """Parse a leading YAML-style '---' frontmatter block.

    Returns (frontmatter_dict, end_index) where end_index is the line index of
    the closing '---'. Only simple scalar 'key: value' lines are captured
    (list/block values like `tools:` are ignored here — use parse_tools for
    those). Returns (None, None) if there is no well-formed frontmatter block.
    """
    lines = text.splitlines()
    end = _frontmatter_bounds(lines)
    if end is None:
        return None, None
    frontmatter = {}
    for line in lines[1:end]:
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if match:
            frontmatter[match.group(1)] = match.group(2).strip()
    return frontmatter, end


def parse_tools(text):
    """Return the list of tool names from the frontmatter `tools:` block.

    The block looks like:
        tools:
          - read
          - search
    Parsing stops at the closing '---' or the next top-level key. Returns None
    if there is no well-formed frontmatter or no `tools:` key.
    """
    lines = text.splitlines()
    end = _frontmatter_bounds(lines)
    if end is None:
        return None
    for i in range(1, end):
        if re.match(r"^tools:\s*$", lines[i]):
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
            return tools
    return None
