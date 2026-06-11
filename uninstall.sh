#!/usr/bin/env bash
#
# uninstall.sh — remove the Copilot CLI Review Team that install.sh placed in
# ~/.copilot/.
#
# Safety: this removes ONLY explicit agent basenames — the union of this repo's
# agents/local-*.agent.md and any recorded in the install manifest. It never
# globs ~/.copilot/agents/, so unrelated local-* agents are left alone.
#
# Usage:
#   ./uninstall.sh [--dry-run] [--purge-playbook] [-h|--help]
#
#   --dry-run            show what would happen; change nothing
#   --purge-playbook     remove the whole copilot-instructions.md instead of only
#                        stripping our managed block (asks for confirmation first)
#   -h, --help           show this help
#
# Default behavior strips this repo's managed block from copilot-instructions.md,
# preserving any instructions you wrote yourself. If nothing else remains, the
# file is removed.
#
# Backup directories (~/.copilot/.backup-*/) are never deleted.
#
# --- end usage ---

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COPILOT_DIR="${COPILOT_HOME:-$HOME/.copilot}"
AGENTS_DIR="$COPILOT_DIR/agents"
PLAYBOOK="$COPILOT_DIR/copilot-instructions.md"
MANIFEST="$COPILOT_DIR/.copilot-review-team-manifest"

DRY_RUN=0
PLAYBOOK_ACTION="strip"

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
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --purge-playbook)
      PLAYBOOK_ACTION="purge"
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

run() {
  # Echo + execute, or just echo under --dry-run.
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "  would: $*"
  else
    "$@"
  fi
}

echo "Uninstalling Copilot Review Team from: $COPILOT_DIR"
if [ "$DRY_RUN" -eq 1 ]; then
  echo "(dry-run — no changes will be made)"
fi

# python3 is required for the playbook-merge (block removal) step. Check BEFORE
# any destructive work (agent removal) so a missing interpreter can't leave a
# partial uninstall. Skip the check under --dry-run since nothing is removed.
if [ "$DRY_RUN" -eq 0 ]; then
  command -v python3 >/dev/null 2>&1 || { echo "error: python3 is required" >&2; exit 1; }
fi

# Strict basename validation, identical to install.sh. A shell glob `case` is NOT
# sufficient to stop path traversal (glob `*` matches `/`), so a tampered
# manifest entry like `local-/../../../victim.agent.md` could resolve OUTSIDE
# $AGENTS_DIR. We require a pure, safe agent basename: `local-<safe chars>.agent.md`,
# with no `/`, no `..`, and no whitespace/control characters.
is_safe_agent_name() {
  local name="$1"
  case "$name" in
    */*|*..*) return 1 ;;  # reject any path separator or parent-dir component
  esac
  [[ "$name" =~ ^local-[A-Za-z0-9._-]+\.agent\.md$ ]]
}

# --- Agents: remove ONLY explicit basenames this install owns. ---
# The removal set is the UNION of:
#   - the basenames this repo currently ships (agents/local-*.agent.md), and
#   - whatever the manifest recorded as installed (so agents renamed/removed in
#     a later repo update are still cleaned up rather than orphaned).
# We NEVER glob ~/.copilot/agents/, so unrelated local-* agents (e.g. a separate
# "thinking team") are always left untouched.
declare -A in_remove_set=()
remove_list=()
add_agent() {
  local name="$1"
  if [ -n "$name" ] && [ -z "${in_remove_set[$name]:-}" ]; then
    in_remove_set[$name]=1
    remove_list+=("$name")
  fi
}

for f in "$SRC_DIR"/agents/local-*.agent.md; do
  add_agent "$(basename "$f")"
done
if [ -e "$MANIFEST" ]; then
  while IFS= read -r name; do
    add_agent "$name"
  done < <(grep '^AGENT=' "$MANIFEST" 2>/dev/null | cut -d= -f2- || true)
fi

removed=0
for name in "${remove_list[@]}"; do
  # Defense-in-depth against a tampered manifest: only act on strict, safe agent
  # basenames so a crafted entry can't delete outside $AGENTS_DIR.
  if ! is_safe_agent_name "$name"; then
    echo "  skip (unsafe name): $name"
    continue
  fi
  target="$AGENTS_DIR/$name"
  if [ -e "$target" ]; then
    run rm -f "$target"
    if [ "$DRY_RUN" -eq 1 ]; then
      echo "  would remove agent: $name"
    else
      echo "  remove agent: $name"
    fi
    removed=$((removed + 1))
  else
    echo "  skip (not installed): $name"
  fi
done
if [ "$DRY_RUN" -eq 1 ]; then
  echo "Agents that would be removed: $removed"
else
  echo "Agents removed: $removed"
fi

# --- Playbook ---
if [ "$PLAYBOOK_ACTION" = "purge" ]; then
  if [ -e "$PLAYBOOK" ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
      echo "  would: rm $PLAYBOOK"
    else
      printf "Remove %s? [y/N] " "$PLAYBOOK"
      read -r reply
      case "$reply" in
        [yY]|[yY][eE][sS])
          rm -f "$PLAYBOOK"
          echo "  removed playbook: copilot-instructions.md"
          ;;
        *)
          echo "  kept playbook (not confirmed)"
          ;;
      esac
    fi
  else
    echo "  playbook already absent: copilot-instructions.md"
  fi
else
  # Default: strip only our marker-delimited managed block, preserving any
  # instructions the user wrote themselves. If the block was the only content,
  # _merge_playbook.py deletes the now-empty file.
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "  would: remove managed block from copilot-instructions.md"
  else
    python3 "$SRC_DIR/scripts/_merge_playbook.py" remove "$PLAYBOOK"
  fi
fi

# --- Manifest cleanup: the install is gone, so drop our manifest too. ---
if [ -e "$MANIFEST" ]; then
  run rm -f "$MANIFEST"
  echo "  remove manifest: $(basename "$MANIFEST")"
fi

echo "Done."
if [ "$DRY_RUN" -eq 1 ]; then
  echo "(dry-run complete — nothing was changed)"
fi
