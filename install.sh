#!/usr/bin/env bash
#
# Installs the Copilot CLI review team into ~/.copilot/
#
#   - Copies the local-* agent definitions into ~/.copilot/agents/
#   - Installs the orchestration playbook as ~/.copilot/copilot-instructions.md
#
# Existing files are backed up to ~/.copilot/.backup-<timestamp>-<pid>/ before being
# overwritten, so this is safe to re-run.
#
# A manifest is written to ~/.copilot/.copilot-review-team-manifest recording
# the exact agent basenames installed, the version installed, and the backup
# that holds the user's ORIGINAL pre-install copilot-instructions.md (if any).
# uninstall.sh uses it for a precise, clean removal. The original-playbook
# pointer is set only on first install (or when the live playbook differs from
# this repo's), so re-running install never clobbers the pointer to the user's
# true original.
#
# Re-running install is a versioned, in-place upgrade: it prints a
# version->version change summary (added / updated / unchanged / removed agents)
# and prunes agents that earlier versions shipped but this one no longer does.
# Pruning is driven ONLY by the previous manifest's AGENT= entries (never by
# globbing ~/.copilot/agents/), so unrelated local-* agents are left untouched.

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COPILOT_DIR="${COPILOT_HOME:-$HOME/.copilot}"
AGENTS_DIR="$COPILOT_DIR/agents"
MANIFEST="$COPILOT_DIR/.copilot-review-team-manifest"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
# Include the PID so two runs within the same second can't clobber each other's
# backups (which could otherwise overwrite the user's *original* files).
BACKUP_DIR="$COPILOT_DIR/.backup-$TIMESTAMP-$$"

# Version this install ships. Read robustly so a missing/blank VERSION file
# can't abort the install under `set -e`.
NEW_VERSION="$(tr -d '[:space:]' < "$SRC_DIR/VERSION" 2>/dev/null || true)"
[ -n "$NEW_VERSION" ] || NEW_VERSION="unknown"

# --- Capture PREVIOUS install state BEFORE we overwrite anything ---
# We need the prior version and the prior agent set so we can (a) print a
# version->version change summary and (b) prune agents that older versions
# shipped but this version no longer does (orphans).
PREV_VERSION=""
declare -A PREV_AGENT_SET=()
PREV_AGENTS=()
if [ -e "$MANIFEST" ]; then
  PREV_VERSION="$(grep '^VERSION=' "$MANIFEST" 2>/dev/null | head -1 | cut -d= -f2- || true)"
  # A manifest with no VERSION= line predates this feature.
  [ -n "$PREV_VERSION" ] || PREV_VERSION="pre-1.0"
  while IFS= read -r _prev_name; do
    [ -n "$_prev_name" ] || continue
    if [ -z "${PREV_AGENT_SET[$_prev_name]:-}" ]; then
      PREV_AGENT_SET[$_prev_name]=1
      PREV_AGENTS+=("$_prev_name")
    fi
  done < <(grep '^AGENT=' "$MANIFEST" 2>/dev/null | cut -d= -f2- || true)
fi

echo "Installing Copilot review team into: $COPILOT_DIR"

if ! command -v copilot >/dev/null 2>&1; then
  echo "  WARNING: 'copilot' CLI not found on PATH. Files will still be installed, but"
  echo "           you'll need GitHub Copilot CLI to use them. See:"
  echo "           https://github.com/github/copilot-cli"
fi

mkdir -p "$AGENTS_DIR"

backup() {
  local target="$1"
  if [ -e "$target" ] || [ -L "$target" ]; then
    mkdir -p "$BACKUP_DIR"
    local rel="${target#"$COPILOT_DIR"/}"
    mkdir -p "$BACKUP_DIR/$(dirname "$rel")"
    # cp -a implies -P (--no-dereference), so a symlink target is backed up as
    # the LINK itself, never its (possibly out-of-tree) referent.
    cp -a "$target" "$BACKUP_DIR/$rel"
  fi
}

# Strict basename validation. A shell glob `case` (e.g. `local-*.agent.md`) is
# NOT sufficient to stop path traversal: glob `*` matches `/`, so a tampered
# manifest entry like `local-/../../../victim.agent.md` would PASS such a guard
# and then resolve OUTSIDE $AGENTS_DIR. We require a pure, safe agent basename:
# `local-<safe chars>.agent.md`, with no `/`, no `..`, and no whitespace/control
# characters. Returns 0 (true) only for names that are safe to use in a path.
is_safe_agent_name() {
  local name="$1"
  case "$name" in
    */*|*..*) return 1 ;;  # reject any path separator or parent-dir component
  esac
  [[ "$name" =~ ^local-[A-Za-z0-9._-]+\.agent\.md$ ]]
}

# Write $1 (a source file) to $2 (target inside $AGENTS_DIR) safely. If $target
# is a symlink we must NOT follow it: `cp` would dereference and clobber the
# referent (which could live OUTSIDE $AGENTS_DIR). We write to a temp file in the
# same directory and `mv -T` it into place — atomic, and it replaces the link
# itself rather than writing through it. Behavior for a regular-file target is
# identical to a plain copy.
install_file() {
  local src="$1" target="$2"
  local tmp
  tmp="$(mktemp "$(dirname "$target")/.tmp-agent.XXXXXX")"
  cp "$src" "$tmp"
  # mktemp creates the temp file 0600; preserve the source file's mode instead
  # so installed agents aren't silently more restrictive than a plain copy.
  chmod --reference="$src" "$tmp"
  mv -T "$tmp" "$target"
}

# --- Agents ---
# Classify each agent this version ships by its on-disk effect, then copy it.
# We also record the NEW agent set (for the manifest and orphan computation).
declare -A NEW_AGENT_SET=()
ADDED=()
UPDATED=()
UNCHANGED=()
for f in "$SRC_DIR"/agents/local-*.agent.md; do
  name="$(basename "$f")"
  NEW_AGENT_SET[$name]=1
  target="$AGENTS_DIR/$name"
  if [ -L "$target" ]; then
    # Symlink in the agents dir: do NOT follow it (cp would clobber the
    # referent, possibly outside $AGENTS_DIR). Back up the link, then replace
    # it with a regular file holding the shipped content.
    backup "$target"
    rm -f "$target"
    install_file "$f" "$target"
    UPDATED+=("$name")
  elif [ ! -e "$target" ]; then
    install_file "$f" "$target"
    ADDED+=("$name")
  elif ! cmp -s "$f" "$target"; then
    backup "$target"
    install_file "$f" "$target"
    UPDATED+=("$name")
  else
    # Identical — nothing to do (skip backup; it's a no-op copy).
    UNCHANGED+=("$name")
  fi
done

# --- Orphan cleanup ---
# Orphans = agents the PREVIOUS manifest recorded that this version no longer
# ships. We remove ONLY such basenames, and only if they match the expected
# `local-*.agent.md` shape (defense-in-depth against a tampered manifest). We
# NEVER glob ~/.copilot/agents/ to decide deletions, so unrelated local-* agents
# (e.g. a separate "thinking team") are always left untouched.
REMOVED=()
if [ "${#PREV_AGENTS[@]}" -gt 0 ]; then
  for name in "${PREV_AGENTS[@]}"; do
    # (a) recorded in previous manifest — guaranteed by iterating PREV_AGENTS.
    # (b) not in the new agent set:
    [ -z "${NEW_AGENT_SET[$name]:-}" ] || continue
    # (c) must be a strict, safe agent basename. A glob `case` is NOT enough
    # here: glob `*` matches `/`, so a tampered manifest entry such as
    # `local-/../../../victim.agent.md` would pass `local-*.agent.md` and then
    # resolve OUTSIDE $AGENTS_DIR — a path-traversal delete. Validate strictly.
    is_safe_agent_name "$name" || continue
    target="$AGENTS_DIR/$name"
    # A symlink orphan: `rm -f` removes the LINK, never its referent, and
    # backup() (cp -a / --no-dereference) backs up the link itself. Both safe.
    if [ -e "$target" ] || [ -L "$target" ]; then
      backup "$target"
      rm -f "$target"
      REMOVED+=("$name")
    fi
    # If it doesn't exist on disk, it's already absent — nothing to do.
  done
fi

# --- Playbook ---
# If you already have a copilot-instructions.md, we DON'T clobber it silently:
# it is backed up first, then replaced. Merge by hand afterward if needed.
PLAYBOOK="$COPILOT_DIR/copilot-instructions.md"

# Decide which backup holds the user's ORIGINAL (pre-install) playbook. This is
# computed BEFORE we back up / overwrite the live file.
#   - If a manifest already exists, preserve whatever it recorded (never point
#     it at this repo's own playbook on a re-install).
#   - Otherwise (first install): the original is the live playbook only if it
#     exists and is NOT byte-identical to this repo's copy; else there is no
#     real original to preserve (empty pointer).
if [ -e "$MANIFEST" ]; then
  ORIG_PLAYBOOK_BACKUP="$(grep '^ORIGINAL_PLAYBOOK_BACKUP=' "$MANIFEST" 2>/dev/null | head -1 | cut -d= -f2- || true)"
elif [ -e "$PLAYBOOK" ] && ! cmp -s "$PLAYBOOK" "$SRC_DIR/copilot-instructions.md"; then
  ORIG_PLAYBOOK_BACKUP="$BACKUP_DIR/copilot-instructions.md"
else
  ORIG_PLAYBOOK_BACKUP=""
fi

if [ -e "$PLAYBOOK" ]; then
  echo "  NOTE:    existing copilot-instructions.md found — backing it up."
fi
backup "$PLAYBOOK"
cp "$SRC_DIR/copilot-instructions.md" "$PLAYBOOK"
echo "  playbook: copilot-instructions.md"

# --- Manifest ---
# Record exactly what we installed so uninstall.sh can clean up precisely.
{
  echo "# Manifest written by install.sh; read by uninstall.sh. Do not edit by hand."
  echo "VERSION=$NEW_VERSION"
  echo "INSTALLED_AT=$TIMESTAMP"
  echo "ORIGINAL_PLAYBOOK_BACKUP=$ORIG_PLAYBOOK_BACKUP"
  for f in "$SRC_DIR"/agents/local-*.agent.md; do
    echo "AGENT=$(basename "$f")"
  done
} > "$MANIFEST"
echo "  manifest: $(basename "$MANIFEST")"

if [ -d "$BACKUP_DIR" ]; then
  echo "Backed up replaced files to: $BACKUP_DIR"
fi

# --- Change summary ---
# Always print a readable, grep-friendly summary of what this run did.
echo ""
echo "== Summary =="
if [ -n "$PREV_VERSION" ]; then
  echo "Version: $PREV_VERSION -> $NEW_VERSION"
else
  echo "Version: $NEW_VERSION (fresh install)"
fi
echo "Agent changes:"
if [ "${#ADDED[@]}" -gt 0 ]; then
  echo "  + added:     ${ADDED[*]}"
fi
if [ "${#UPDATED[@]}" -gt 0 ]; then
  echo "  ~ updated:   ${UPDATED[*]}"
fi
if [ "${#REMOVED[@]}" -gt 0 ]; then
  echo "  - removed:   ${REMOVED[*]}  (orphaned from previous version)"
fi
echo "  = unchanged: ${#UNCHANGED[@]}"

echo ""
echo "Verify anytime with: ls ~/.copilot/agents/local-*.agent.md"
echo "Done. Start a new 'copilot' session for the team to take effect."
