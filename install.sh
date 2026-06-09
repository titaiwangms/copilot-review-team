#!/usr/bin/env bash
#
# Installs the Copilot CLI review team into ~/.copilot/
#
#   - Copies the local-* agent definitions into ~/.copilot/agents/
#   - Installs the orchestration playbook as ~/.copilot/copilot-instructions.md
#
# Existing files are backed up to ~/.copilot/.backup-<timestamp>-<pid>/ before being
# overwritten, so this is safe to re-run.

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COPILOT_DIR="${COPILOT_HOME:-$HOME/.copilot}"
AGENTS_DIR="$COPILOT_DIR/agents"
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
if [ -e "$PLAYBOOK" ]; then
  echo "  NOTE:    existing copilot-instructions.md found — backing it up."
fi
backup "$PLAYBOOK"
cp "$SRC_DIR/copilot-instructions.md" "$PLAYBOOK"
echo "  playbook: copilot-instructions.md"

if [ -d "$BACKUP_DIR" ]; then
  echo "Backed up replaced files to: $BACKUP_DIR"
fi

echo "Installed agents:"
ls "$AGENTS_DIR"/local-*.agent.md 2>/dev/null | sed 's#.*/#  #'
echo "Verify anytime with: ls ~/.copilot/agents/local-*.agent.md"
echo "Done. Start a new 'copilot' session for the team to take effect."
