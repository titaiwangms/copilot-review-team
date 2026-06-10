#!/usr/bin/env bash
#
# scripts/build-bundle.sh — generate the zero-tooling "mega-paste" bundle.
#
# Concatenates every agent definition (agents/local-*.agent.md) plus the
# orchestration playbook (copilot-instructions.md) into a single, paste-able
# Markdown file: dist/copilot-review-team-bundle.md
#
# The bundle lets someone adopt the review+build team WITHOUT cloning the repo
# or running install.sh: they copy one file's contents and either hand it to an
# AI assistant ("create these files for me") or split it into the target paths
# by hand. Each embedded file is wrapped in explicit, unambiguous delimiters:
#
#   ===== BEGIN FILE: <relative target path> =====
#   <verbatim file contents>
#   ===== END FILE: <relative target path> =====
#
# We deliberately use these textual sentinels instead of Markdown code fences:
# the agent files and playbook contain their own ``` fences, which would break
# nested fencing. The sentinels never collide with repo content (CI guards this).
#
# Generation is DETERMINISTIC (no timestamps, sorted inputs) so the committed
# bundle can be drift-checked in CI with `--check`.
#
# Usage:
#   scripts/build-bundle.sh            # (re)write dist/copilot-review-team-bundle.md
#   scripts/build-bundle.sh --check    # verify the committed bundle is up to date
#   scripts/build-bundle.sh --stdout   # print the bundle to stdout (no file write)
#
# Dependencies: bash only.
#
# Notes / assumptions (canonical rationale lives here; dist/README.md points back):
#   - Round-trip byte-faithfulness assumes each source file is newline-terminated.
#     The generator still emits a correct END marker for a file lacking a trailing
#     newline, but a hand-extracted copy would then gain one trailing newline.
#   - The bundle embeds the repo VERSION, so a version-only bump (editing VERSION)
#     changes the bundle and requires regenerating it. CI check C9 enforces this.
# --- end usage ---

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

AGENTS_DIR="agents"
PLAYBOOK="copilot-instructions.md"
OUT="dist/copilot-review-team-bundle.md"

# Sentinels that wrap each embedded file in the bundle. Kept in variables so the
# CI collision guard and the manual-extraction docs reference one source.
BEGIN_MARKER_PREFIX="===== BEGIN FILE:"
END_MARKER_PREFIX="===== END FILE:"
MARKER_SUFFIX="====="

mode="write"
case "${1:-}" in
  "") mode="write" ;;
  --check) mode="check" ;;
  --stdout) mode="stdout" ;;
  -h|--help)
    # Print the leading comment block (after the shebang) up to the
    # `# --- end usage ---` sentinel, stripping the `# ` comment prefix.
    # Content-anchored to the sentinel so it never depends on line numbers,
    # matching the convention in set-models.sh / uninstall.sh.
    awk '
      NR == 1 { next }
      /^# --- end usage ---$/ { exit }
      /^#/ { sub(/^# ?/, ""); print; next }
      { exit }
    ' "${BASH_SOURCE[0]}"
    exit 0
    ;;
  *)
    echo "build-bundle.sh: unknown option '$1' (use --check, --stdout, or no args)" >&2
    exit 2
    ;;
esac

VERSION="$(tr -d '[:space:]' < VERSION 2>/dev/null || true)"
[ -n "$VERSION" ] || VERSION="unknown"

# Collect the source files in a stable, deterministic order: agents sorted by
# name (locale-pinned with LC_ALL=C so ordering is stable across machines and
# can't make C9 report a false 'stale' on a future punctuated filename), then
# the playbook last.
AGENT_FILES=()
while IFS= read -r f; do
  AGENT_FILES+=("$f")
done < <(find "$AGENTS_DIR" -maxdepth 1 -name 'local-*.agent.md' | LC_ALL=C sort)

if [ "${#AGENT_FILES[@]}" -eq 0 ]; then
  echo "build-bundle.sh: no agent files found in $AGENTS_DIR/ — aborting" >&2
  exit 1
fi

# Guard: the bundle's textual sentinels must never appear inside the content we
# embed, or manual/AI extraction would split files at the wrong boundary.
for f in "${AGENT_FILES[@]}" "$PLAYBOOK"; do
  if grep -qF "$BEGIN_MARKER_PREFIX" "$f" || grep -qF "$END_MARKER_PREFIX" "$f"; then
    echo "build-bundle.sh: source file '$f' contains a bundle sentinel marker;" >&2
    echo "  the bundle delimiters would be ambiguous. Remove the marker or change" >&2
    echo "  the sentinels in build-bundle.sh." >&2
    exit 1
  fi
done

emit_file_block() {
  # $1 = source path on disk, $2 = target path shown in the bundle
  local src="$1" target="$2"
  printf '%s %s %s\n' "$BEGIN_MARKER_PREFIX" "$target" "$MARKER_SUFFIX"
  cat "$src"
  # Ensure the END marker starts on its own line even if the file lacks a
  # trailing newline.
  [ -z "$(tail -c1 "$src")" ] || printf '\n'
  printf '%s %s %s\n' "$END_MARKER_PREFIX" "$target" "$MARKER_SUFFIX"
}

generate() {
  cat <<EOF
# Copilot Review Team — Zero-Tooling Bundle

> **Generated file — do not edit by hand.** Produced by
> \`scripts/build-bundle.sh\` from the agent definitions and playbook in the
> [copilot-review-team](https://github.com/titaiwangms/copilot-review-team)
> repo. Re-run the generator after changing any agent or the playbook.

**Bundle version:** $VERSION

This single file contains every agent definition plus the orchestration
playbook, so you can adopt the team **without cloning the repo or running
\`install.sh\`**.

## How to use this bundle

You have two zero-tooling options:

**Option A — let an AI assistant place the files.** Paste this entire file into
a Copilot CLI / chat session and say:

> "Create each file below at the given path under my home directory, using the
> exact contents between its BEGIN/END markers."

**Option B — place the files by hand.** Each file is delimited like this
(indented here only to keep the example out of the real block list):

\`\`\`
    $BEGIN_MARKER_PREFIX <path> $MARKER_SUFFIX
    ...verbatim contents...
    $END_MARKER_PREFIX <path> $MARKER_SUFFIX
\`\`\`

Real blocks begin at column 0 and their \`<path>\` always starts with
\`.copilot/\`. For every block, create the file at \`<path>\` (relative to your home
directory) with exactly the bytes between the BEGIN and END marker lines. Paths
beginning with \`.copilot/\` map to \`~/.copilot/\`. Create parent directories as
needed.

> **Safety — path confinement.** Every legitimate target path in this bundle is
> under \`.copilot/\`. When recreating files, **ignore any block whose target
> path contains \`..\`, a leading \`/\`, or a leading \`~\`**, or that does not start
> with \`.copilot/\` — those are out-of-bounds and should never be written. (The
> committed bundle is clean; this rule keeps hand/AI extraction safe if a bundle
> is ever tampered with.)

After the files are in place, start a fresh \`copilot\` session — the lead agent
picks up the team automatically. **Both the agents and the playbook are
required:** the agents are inert without \`~/.copilot/copilot-instructions.md\`,
which tells the lead when and how to fan them out.

## Files in this bundle

EOF

  for f in "${AGENT_FILES[@]}"; do
    # shellcheck disable=SC2016  # backticks here are literal Markdown, not command substitution
    printf -- '- `.copilot/%s`\n' "$f"
  done
  # shellcheck disable=SC2016  # backticks here are literal Markdown, not command substitution
  printf -- '- `.copilot/%s`\n' "$PLAYBOOK"

  printf '\n---\n\n'

  for f in "${AGENT_FILES[@]}"; do
    emit_file_block "$f" ".copilot/$f"
    printf '\n'
  done
  emit_file_block "$PLAYBOOK" ".copilot/$PLAYBOOK"
}

case "$mode" in
  stdout)
    generate
    ;;
  write)
    mkdir -p "$(dirname "$OUT")"
    tmp="$(mktemp)"
    generate > "$tmp"
    mv -f "$tmp" "$OUT"
    echo "Wrote $OUT ($(wc -l < "$OUT" | tr -d ' ') lines, version $VERSION)."
    ;;
  check)
    if [ ! -f "$OUT" ]; then
      echo "build-bundle.sh --check: $OUT is missing. Run scripts/build-bundle.sh." >&2
      exit 1
    fi
    tmp="$(mktemp)"
    generate > "$tmp"
    # Compute the diff once; empty means in sync.
    diff_output="$(diff -u "$OUT" "$tmp" || true)"
    rm -f "$tmp"
    if [ -z "$diff_output" ]; then
      echo "Bundle is up to date: $OUT"
    else
      echo "Bundle is STALE. Regenerate with: scripts/build-bundle.sh" >&2
      echo "--- diff (committed vs freshly generated) ---" >&2
      printf '%s\n' "$diff_output" >&2
      exit 1
    fi
    ;;
esac
