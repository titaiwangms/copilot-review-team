#!/usr/bin/env bash
#
# set-models.sh — apply the agent→model mapping in models.conf to both
# machine-readable locations that must stay in sync:
#   (a) the `model:` line in each agents/local-*.agent.md frontmatter
#   (b) the model column of the team table in copilot-instructions.md
#
# Frontmatter is the canonical source of truth; this tool keeps the table
# (and, when you run apply, the frontmatter) matching models.conf. Prose
# (e.g. "Claude Opus 4.8") is a manual concern and is never touched here.
#
# Usage:
#   ./set-models.sh [--from FILE] [--dry-run] [--check] [-h|--help]
#
#   --from FILE   mapping file to read (default: ./models.conf)
#   --dry-run     print a unified diff of every change, write nothing, exit 0
#   --check       verify frontmatter == table for all agents, write nothing;
#                 exit 0 if in sync, 1 if drift (this is what CI runs)
#   -h, --help    show this help
#
# Dependencies: bash + python3 only (no PyYAML).
#
# --- end usage ---

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MAPPING_FILE="$SRC_DIR/models.conf"
MODE="apply"

usage() {
  # Print the leading comment block (after the shebang) up to the
  # `# --- end usage ---` sentinel, stripping the `# ` comment prefix.
  # Content-anchored to the sentinel so it never depends on line numbers.
  awk '
    NR == 1 { next }
    /^# --- end usage ---$/ { exit }
    /^#/ { sub(/^# ?/, ""); print; next }
    { exit }
  ' "${BASH_SOURCE[0]}"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --from)
      [ $# -ge 2 ] || { echo "error: --from requires a FILE argument" >&2; exit 1; }
      MAPPING_FILE="$2"
      shift 2
      ;;
    --from=*)
      MAPPING_FILE="${1#--from=}"
      shift
      ;;
    --dry-run)
      MODE="dry-run"
      shift
      ;;
    --check)
      MODE="check"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "error: unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if ! command -v python3 >/dev/null 2>&1; then
  echo "error: python3 is required but was not found on PATH" >&2
  exit 1
fi

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$SRC_DIR/.backup-models-$TIMESTAMP-$$"

MODE="$MODE" SRC_DIR="$SRC_DIR" MAPPING_FILE="$MAPPING_FILE" BACKUP_DIR="$BACKUP_DIR" \
python3 - <<'PY'
import os
import re
import sys
import glob
import shutil
import difflib
import tempfile

MODE = os.environ["MODE"]
SRC_DIR = os.environ["SRC_DIR"]
MAPPING_FILE = os.environ["MAPPING_FILE"]
BACKUP_DIR = os.environ["BACKUP_DIR"]

PLAYBOOK = os.path.join(SRC_DIR, "copilot-instructions.md")
AGENT_GLOB = os.path.join(SRC_DIR, "agents", "local-*.agent.md")


def fail(msg):
    sys.stderr.write("error: " + msg + "\n")
    sys.exit(1)


def agent_files():
    return sorted(glob.glob(AGENT_GLOB))


def agent_name(path):
    return os.path.basename(path)[: -len(".agent.md")]


def parse_frontmatter(text):
    """Hand-rolled frontmatter parser: split on the first two '---' fences,
    read simple 'key: value' lines. No PyYAML."""
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
    fm = {}
    for line in lines[1:end]:
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if m:
            fm[m.group(1)] = m.group(2).strip()
    return fm, end


def frontmatter_model(path):
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    fm, _ = parse_frontmatter(text)
    if fm is None:
        fail("malformed frontmatter in %s" % path)
    if "model" not in fm:
        fail("no model: in frontmatter of %s" % path)
    return fm["model"]


# Match a table row like:  | `local-architect` | claude-opus-4.8 | role text |
ROW_RE = re.compile(r"^(\|\s*`(local-[a-z-]+)`\s*\|)([^|]*)(\|.*)$")
# A markdown table separator row like | --- | :---: | --- |
SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")


def find_team_table_bounds(lines):
    """Locate the team table robustly: the first markdown table whose header
    row contains a 'Model' column, immediately followed by a separator row.
    Returns (data_start, data_end) — the half-open range of data-row line
    indices — or None if not found. Scoping to this table prevents us from
    matching any stray `| `local-*` |` row elsewhere in the playbook."""
    n = len(lines)
    for i in range(n):
        line = lines[i]
        if not line.lstrip().startswith("|") or "model" not in line.lower():
            continue
        cells = [c.strip().lower() for c in line.strip().strip("|").split("|")]
        if "model" not in cells or i + 1 >= n:
            continue
        sep = lines[i + 1]
        if not SEP_RE.match(sep) or "-" not in sep:
            continue
        start = i + 2
        end = start
        while end < n and lines[end].lstrip().startswith("|"):
            end += 1
        return start, end
    return None


def parse_table(text):
    """Return dict agent -> (line_index, current_model), scoped to the team
    table only. Fails if an agent appears more than once in that table."""
    lines = text.splitlines()
    bounds = find_team_table_bounds(lines)
    if bounds is None:
        fail("could not locate the team table (markdown table with a 'Model' "
             "column) in copilot-instructions.md")
    start, end = bounds
    rows = {}
    for idx in range(start, end):
        m = ROW_RE.match(lines[idx])
        if m:
            agent = m.group(2)
            if agent in rows:
                fail("agent %s appears more than once in the team table" % agent)
            rows[agent] = (idx, m.group(3).strip())
    return rows


def set_frontmatter_model(text, model):
    """Rewrite the single '^model: .*$' line inside the first --- block only."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        fail("malformed frontmatter")
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        fail("malformed frontmatter")
    changed = False
    for i in range(1, end):
        if re.match(r"^model:\s*.*$", lines[i]):
            newline = "model: %s" % model
            if lines[i].endswith("\n"):
                newline += "\n"
            lines[i] = newline
            changed = True
            break
    if not changed:
        fail("no model: line found in frontmatter block")
    return "".join(lines)


def set_table_model(text, agent, model):
    """Replace only the 2nd cell of the matching agent row within the team
    table; preserve the rest. Scoped so we never edit a stray row elsewhere."""
    lines = text.splitlines(keepends=True)
    stripped = [ln.rstrip("\n") for ln in lines]
    bounds = find_team_table_bounds(stripped)
    if bounds is None:
        fail("could not locate the team table in copilot-instructions.md")
    start, end = bounds
    found = False
    for i in range(start, end):
        m = ROW_RE.match(stripped[i])
        if m and m.group(2) == agent:
            rebuilt = "%s %s %s" % (m.group(1), model, m.group(4))
            if lines[i].endswith("\n"):
                rebuilt += "\n"
            lines[i] = rebuilt
            found = True
            break
    if not found:
        fail("no table row found for agent %s" % agent)
    return "".join(lines)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def load_mapping(path):
    if not os.path.exists(path):
        fail("mapping file not found: %s" % path)
    # Validate tokens strictly so a malicious/typo'd value can never break the
    # YAML frontmatter or a markdown table cell (e.g. an embedded '|' or
    # backtick). These patterns reject such characters by construction.
    agent_re = re.compile(r"^local-[A-Za-z0-9-]+$")
    model_re = re.compile(r"^[A-Za-z0-9._:-]+$")
    mapping = {}
    with open(path, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            # split on whitespace and/or a single '='
            tokens = [t for t in re.split(r"[\s=]+", line) if t]
            if len(tokens) != 2:
                fail("malformed mapping line %d in %s: %r" % (lineno, path, raw.rstrip()))
            agent, model = tokens
            if not agent_re.match(agent):
                fail("invalid agent name %r on line %d of %s "
                     "(must match ^local-[A-Za-z0-9-]+$)" % (agent, lineno, path))
            if not model_re.match(model):
                fail("invalid model id %r on line %d of %s "
                     "(allowed: letters, digits and . _ : -)" % (model, lineno, path))
            if agent in mapping:
                fail("duplicate agent %s in %s" % (agent, path))
            mapping[agent] = model
    return mapping


def do_check():
    files = agent_files()
    if not files:
        fail("no agent files found under %s" % AGENT_GLOB)
    table = parse_table(read(PLAYBOOK))
    drift = 0
    for path in files:
        agent = agent_name(path)
        fm_model = frontmatter_model(path)
        if agent not in table:
            print("DRIFT: %s missing from table" % agent)
            drift += 1
            continue
        tbl_model = table[agent][1]
        if fm_model != tbl_model:
            print("DRIFT: %s frontmatter=%s table=%s" % (agent, fm_model, tbl_model))
            drift += 1
    # rows in table with no agent file
    agent_set = {agent_name(p) for p in files}
    for agent in table:
        if agent not in agent_set:
            print("DRIFT: %s in table but no agent file" % agent)
            drift += 1
    if drift:
        sys.exit(1)
    print("OK: frontmatter and table are in sync (%d agents)" % len(files))
    sys.exit(0)


def do_apply(dry_run):
    files = agent_files()
    if not files:
        fail("no agent files found under %s" % AGENT_GLOB)
    mapping = load_mapping(MAPPING_FILE)
    agent_set = {agent_name(p) for p in files}

    # VALIDATE before writing: bijection between mapping and agent files.
    missing = sorted(agent_set - set(mapping))
    if missing:
        fail("agent file(s) with no mapping entry: %s" % ", ".join(missing))
    extra = sorted(set(mapping) - agent_set)
    if extra:
        fail("mapping entry(ies) with no agent file: %s" % ", ".join(extra))

    playbook_text = read(PLAYBOOK)
    table = parse_table(playbook_text)
    for agent in agent_set:
        if agent not in table:
            fail("no table row for agent %s in copilot-instructions.md" % agent)

    # Compute changes.
    changes = []  # (path, old_text, new_text)

    # Frontmatter changes.
    for path in files:
        agent = agent_name(path)
        old = read(path)
        new = set_frontmatter_model(old, mapping[agent])
        if old != new:
            changes.append((path, old, new))

    # Table changes (single file, applied cumulatively).
    new_playbook = playbook_text
    for agent in sorted(agent_set):
        new_playbook = set_table_model(new_playbook, agent, mapping[agent])
    if new_playbook != playbook_text:
        changes.append((PLAYBOOK, playbook_text, new_playbook))

    if not changes:
        print("No changes: all frontmatter and the table already match %s" %
              os.path.relpath(MAPPING_FILE, SRC_DIR))
        sys.exit(0)

    if dry_run:
        for path, old, new in changes:
            rel = os.path.relpath(path, SRC_DIR)
            diff = difflib.unified_diff(
                old.splitlines(keepends=True),
                new.splitlines(keepends=True),
                fromfile="a/" + rel,
                tofile="b/" + rel,
            )
            sys.stdout.writelines(diff)
        print("\n(dry-run) %d file(s) would change; nothing was written." % len(changes))
        sys.exit(0)

    # Apply: backup each touched file before first edit, then write atomically.
    os.makedirs(BACKUP_DIR, exist_ok=True)
    for path, _old, new in changes:
        rel = os.path.relpath(path, SRC_DIR)
        dest = os.path.join(BACKUP_DIR, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy2(path, dest)
        # Write to a temp file in the same directory then os.replace() it, so an
        # interrupted/failed run never leaves a partially-written file behind.
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path),
                                   prefix=".tmp-set-models-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(new)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    print("Updated %d file(s):" % len(changes))
    for path, _old, _new in changes:
        print("  " + os.path.relpath(path, SRC_DIR))
    print("Backed up originals to: %s" % os.path.relpath(BACKUP_DIR, SRC_DIR))
    print("Next: run ./install.sh to copy the updated files into ~/.copilot/.")
    sys.exit(0)


if MODE == "check":
    do_check()
elif MODE == "dry-run":
    do_apply(dry_run=True)
else:
    do_apply(dry_run=False)
PY
