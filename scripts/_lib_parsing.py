"""Shared parsing helpers for the Copilot review-team tooling.

This module is the single home for the small amount of frontmatter / config
parsing the repo needs, so the checkers and the installer don't each hand-roll
their own copy (which previously drifted). No third-party deps (no PyYAML):
agent frontmatter is a constrained, machine-written subset, so a tiny purpose
-built parser is clearer and dependency-free.

Public API:
    parse_frontmatter(text)      -> (dict | None, end_index | None)
    parse_tools(text)            -> list[str] | None
    frontmatter_model(path)      -> str            (raises on malformed input)
    set_frontmatter_model(text, model) -> str
    load_overrides(path)         -> dict           (agent -> model, '*' wildcard)
    resolve_model(overrides, agent) -> str | None
"""
import re

# A model id is a constrained token (letters, digits and . _ : -). Validating
# overrides against this by construction makes it impossible for a typo'd or
# malicious value to inject a newline / YAML break into an agent's frontmatter.
MODEL_RE = re.compile(r"^[A-Za-z0-9._:-]+$")
AGENT_RE = re.compile(r"^local-[A-Za-z0-9-]+$")

# Wildcard keys in an override file that mean "every agent not listed explicitly".
WILDCARD_KEYS = ("*", "default")
WILDCARD = "*"


class ParseError(Exception):
    """Raised for malformed input the caller should report and abort on."""


def parse_frontmatter(text):
    """Parse a leading YAML-style '---' frontmatter block.

    Returns (frontmatter_dict, end_index) where end_index is the line index of
    the closing '---'. Only simple scalar 'key: value' lines are captured
    (list/block values like `tools:` are ignored here — use parse_tools for
    those). Returns (None, None) if there is no well-formed frontmatter block.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, None
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
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
    if not lines or lines[0].strip() != "---":
        return None
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
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


def frontmatter_model(path):
    """Return the `model:` value from a file's frontmatter, or raise ParseError."""
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    frontmatter, _ = parse_frontmatter(text)
    if frontmatter is None:
        raise ParseError("malformed frontmatter in %s" % path)
    if "model" not in frontmatter:
        raise ParseError("no model: in frontmatter of %s" % path)
    return frontmatter["model"]


def set_frontmatter_model(text, model):
    """Rewrite the single '^model: .*$' line inside the first '---' block only.

    Returns the new text. Raises ParseError if there is no frontmatter block or
    no model: line within it.
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ParseError("malformed frontmatter")
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        raise ParseError("malformed frontmatter")
    for i in range(1, end):
        if re.match(r"^model:\s*.*$", lines[i]):
            newline = "model: %s" % model
            if lines[i].endswith("\n"):
                newline += "\n"
            lines[i] = newline
            return "".join(lines)
    raise ParseError("no model: line found in frontmatter block")


def load_overrides(path):
    """Parse an optional model-override file into a mapping.

    Format: one `agent-name  model-id` per line. The separator is whitespace
    and/or a single '=', so both of these are valid:
        local-architect  gpt-5.4
        local-architect = gpt-5.4
    A wildcard line ('*' or 'default') sets the model for every agent not named
    explicitly, e.g. `*  gpt-5.4` pins the whole team to one model. Blank lines
    and '#' comments are ignored. The wildcard is stored under the key '*'.

    Tokens are validated strictly so a bad value can never break an agent's
    frontmatter. Raises ParseError on any malformed line.
    """
    overrides = {}
    with open(path, encoding="utf-8") as handle:
        for lineno, raw in enumerate(handle, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            tokens = [t for t in re.split(r"[\s=]+", line) if t]
            if len(tokens) != 2:
                raise ParseError(
                    "malformed override line %d in %s: %r"
                    % (lineno, path, raw.rstrip())
                )
            agent, model = tokens
            if agent in WILDCARD_KEYS:
                agent = WILDCARD
            elif not AGENT_RE.match(agent):
                raise ParseError(
                    "invalid agent name %r on line %d of %s "
                    "(must match ^local-[A-Za-z0-9-]+$, or '*' for all)"
                    % (agent, lineno, path)
                )
            if not MODEL_RE.match(model):
                raise ParseError(
                    "invalid model id %r on line %d of %s "
                    "(allowed: letters, digits and . _ : -)" % (model, lineno, path)
                )
            if agent in overrides:
                raise ParseError("duplicate entry %r in %s" % (agent, path))
            overrides[agent] = model
    return overrides


def resolve_model(overrides, agent):
    """Return the override model for `agent`: an explicit entry wins over the
    '*' wildcard; returns None if neither applies (keep the frontmatter value)."""
    if agent in overrides:
        return overrides[agent]
    return overrides.get(WILDCARD)
