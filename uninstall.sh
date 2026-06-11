#!/usr/bin/env bash
#
# uninstall.sh — remove the Copilot CLI Review + Build Team that install.sh placed in
# ~/.copilot/.
#
# Safety: this removes ONLY explicit agent basenames — the union of this repo's
# agents/local-*.agent.md and any recorded in the install manifest. It never
# globs ~/.copilot/agents/, so unrelated local-* agents are left alone.
#
# Usage:
#   ./uninstall.sh [--dry-run] [--purge-playbook] [--restore-playbook] [-h|--help]
#
#   --dry-run            show what would happen; change nothing
#   --restore-playbook   (default) restore copilot-instructions.md from the
#                        newest install backup, if one exists
#   --purge-playbook     remove copilot-instructions.md instead of restoring
#                        (asks for confirmation first)
#   -h, --help           show this help
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
PLAYBOOK_ACTION="restore"

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
    --restore-playbook)
      PLAYBOOK_ACTION="restore"
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

echo "Uninstalling Copilot Review + Build Team from: $COPILOT_DIR"
if [ "$DRY_RUN" -eq 1 ]; then
  echo "(dry-run — no changes will be made)"
fi

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
  target="$AGENTS_DIR/$name"
  if [ -e "$target" ]; then
    run rm -f "$target"
    echo "  remove agent: $name"
    removed=$((removed + 1))
  else
    echo "  skip (not installed): $name"
  fi
done
echo "Agents removed: $removed"

# --- Playbook ---
newest_backup_playbook() {
  # install.sh names backups .backup-YYYYMMDD-HHMMSS-PID, which sort
  # lexically == chronologically. Pick the newest one that has a saved
  # copilot-instructions.md.
  ls -d "$COPILOT_DIR"/.backup-*/copilot-instructions.md 2>/dev/null | sort | tail -1
}

manifest_original_playbook() {
  # Print the original-playbook backup path recorded at first install, if any.
  [ -e "$MANIFEST" ] || return 0
  grep '^ORIGINAL_PLAYBOOK_BACKUP=' "$MANIFEST" 2>/dev/null | head -1 | cut -d= -f2- || true
}

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
  # restore (default). Preference order:
  #   1. the manifest's recorded ORIGINAL playbook backup (the user's true
  #      pre-install file), if present;
  #   2. else the newest install .backup-*/copilot-instructions.md (legacy
  #      behavior — also the only path when no manifest exists);
  #   3. else, if a manifest exists and the installed playbook is byte-identical
  #      to this repo's copy, remove our residue (clean round-trip);
  #   4. else leave it in place and warn.
  orig="$(manifest_original_playbook)"
  backup="$(newest_backup_playbook || true)"
  if [ -n "$orig" ] && [ -e "$orig" ]; then
    echo "  restoring playbook from recorded original: $orig"
    run cp -a "$orig" "$PLAYBOOK"
  elif [ -n "$backup" ]; then
    echo "  restoring playbook from: $backup"
    run cp -a "$backup" "$PLAYBOOK"
  elif [ -e "$MANIFEST" ] && [ -e "$PLAYBOOK" ] && cmp -s "$PLAYBOOK" "$SRC_DIR/copilot-instructions.md"; then
    echo "  removing installed playbook (clean round-trip; no original to restore)"
    run rm -f "$PLAYBOOK"
  else
    echo "  WARNING: no install backup found; leaving copilot-instructions.md in place;"
    echo "           use --purge-playbook to remove it."
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
