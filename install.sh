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
# the exact agent basenames installed and the backup that holds the user's
# ORIGINAL pre-install copilot-instructions.md (if any). uninstall.sh uses it
# for a precise, clean removal. The original-playbook pointer is set only on
# first install (or when the live playbook differs from this repo's), so
# re-running install never clobbers the pointer to the user's true original.

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COPILOT_DIR="${COPILOT_HOME:-$HOME/.copilot}"
AGENTS_DIR="$COPILOT_DIR/agents"
MANIFEST="$COPILOT_DIR/.copilot-review-team-manifest"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
# Include the PID so two runs within the same second can't clobber each other's
# backups (which could otherwise overwrite the user's *original* files).
BACKUP_DIR="$COPILOT_DIR/.backup-$TIMESTAMP-$$"

echo "Installing Copilot review team into: $COPILOT_DIR"

if ! command -v copilot >/dev/null 2>&1; then
  echo "  WARNING: 'copilot' CLI not found on PATH. Files will still be installed, but"
  echo "           you'll need GitHub Copilot CLI to use them. See:"
  echo "           https://github.com/github/copilot-cli"
fi

mkdir -p "$AGENTS_DIR"

backup() {
  local target="$1"
  if [ -e "$target" ]; then
    mkdir -p "$BACKUP_DIR"
    local rel="${target#"$COPILOT_DIR"/}"
    mkdir -p "$BACKUP_DIR/$(dirname "$rel")"
    cp -a "$target" "$BACKUP_DIR/$rel"
  fi
}

# --- Agents ---
for f in "$SRC_DIR"/agents/local-*.agent.md; do
  name="$(basename "$f")"
  backup "$AGENTS_DIR/$name"
  cp "$f" "$AGENTS_DIR/$name"
  echo "  agent:   $name"
done

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
  echo "ORIGINAL_PLAYBOOK_BACKUP=$ORIG_PLAYBOOK_BACKUP"
  for f in "$SRC_DIR"/agents/local-*.agent.md; do
    echo "AGENT=$(basename "$f")"
  done
} > "$MANIFEST"
echo "  manifest: $(basename "$MANIFEST")"

if [ -d "$BACKUP_DIR" ]; then
  echo "Backed up replaced files to: $BACKUP_DIR"
fi

echo "Installed agents:"
ls "$AGENTS_DIR"/local-*.agent.md 2>/dev/null | sed 's#.*/#  #'
echo "Verify anytime with: ls ~/.copilot/agents/local-*.agent.md"
echo "Done. Start a new 'copilot' session for the team to take effect."
