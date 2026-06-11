#!/usr/bin/env bash
#
# scripts/validate.sh — repo self-checks. Run this before submitting a PR.
# Runs every check, accumulates failures, prints a summary, and exits
# nonzero if anything failed.
#
# Dependencies: bash + python3. shellcheck is used if present (optional).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

FAILURES=0
pass() { echo "  PASS: $*"; }
fail() { echo "  FAIL: $*"; FAILURES=$((FAILURES + 1)); }

SCRIPTS="install.sh uninstall.sh scripts/validate.sh scripts/build-bundle.sh"

# --- prerequisite: python3 ---
echo "== prerequisites =="
if command -v python3 >/dev/null 2>&1; then
  pass "python3 available"
else
  fail "python3 not found on PATH — required by these checks"
  echo ""
  echo "Cannot continue without python3."
  exit 1
fi

# --- C1: bash syntax ---
echo "== C1: bash syntax =="
for s in $SCRIPTS; do
  if bash -n "$s" 2>/dev/null; then
    pass "bash -n $s"
  else
    fail "bash -n $s"
  fi
done

# --- C2: frontmatter well-formed ---
echo "== C2: agent frontmatter =="
if python3 scripts/_check_frontmatter.py; then
  pass "all agent frontmatter well-formed"
else
  fail "agent frontmatter check"
fi
# Run the frontmatter checker's own unit tests so CI exercises the validation
# logic (malformed / empty / list / block-scalar model values), not just the
# happy path. Capture output so a PASS stays quiet but a FAILURE shows which
# cases broke.
if frontmatter_test_output="$(python3 scripts/_test_check_frontmatter.py 2>&1)"; then
  pass "frontmatter checker unit tests (scripts/_test_check_frontmatter.py)"
else
  fail "frontmatter checker unit tests"
  printf '%s\n' "$frontmatter_test_output"
fi

# --- C3: team table roster matches agent files ---
# Model IDs are single-source in each agent's frontmatter; there is no model
# sync to police. We still assert the playbook team table lists exactly the
# agents that exist on disk (no stale or missing rows).
echo "== C3: team table roster =="
if python3 scripts/_check_table_sets.py; then
  pass "table agent set == agent file set"
else
  fail "table agent set != agent file set"
fi

# --- C4: reviewer-count phrasing (fork-friendly) ---
# Derive the reviewer count N from the actual files rather than hard-coding 5,
# so a fork that adds/removes a reviewer still passes as long as it is
# internally consistent. We then assert every reviewer body and every count
# phrasing in the docs agrees with N.
echo "== C4: reviewer count phrasing =="
reviewer_count="$(find agents -name 'local-*-reviewer.agent.md' | wc -l | tr -d ' ')"
if [ "$reviewer_count" -ge 1 ]; then
  pass "found $reviewer_count reviewer agent file(s)"
else
  fail "expected at least 1 reviewer agent file, found $reviewer_count"
fi

# English number word for small counts (enough for any realistic team size).
num2word() {
  case "$1" in
    1) echo one ;; 2) echo two ;; 3) echo three ;; 4) echo four ;;
    5) echo five ;; 6) echo six ;; 7) echo seven ;; 8) echo eight ;;
    9) echo nine ;; 10) echo ten ;; 11) echo eleven ;; 12) echo twelve ;;
    *) echo "" ;;
  esac
}
n_word="$(num2word "$reviewer_count")"

# Accept either the digit or the word form of N in "one of N reviewers".
count_alt="$reviewer_count"
[ -n "$n_word" ] && count_alt="$reviewer_count|$n_word"

for r in agents/local-*-reviewer.agent.md; do
  if grep -qE "one of ($count_alt) reviewers" "$r"; then
    pass "$(basename "$r") agrees with reviewer count ($reviewer_count)"
  else
    fail "$(basename "$r") does not say 'one of $reviewer_count reviewers'"
  fi
done

# Stale-count scan: flag any "<number> reviewers" phrasing (word or digit) that
# disagrees with the derived count, across the playbook, README, and examples.
stale_scan_files="copilot-instructions.md README.md"
for ex in examples/*.md; do
  [ -e "$ex" ] && stale_scan_files="$stale_scan_files $ex"
done
number_re='\b(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|[0-9]+) reviewers'
for f in $stale_scan_files; do
  [ -e "$f" ] || continue
  bad=""
  while IFS= read -r found; do
    [ -z "$found" ] && continue
    [ "$found" = "$reviewer_count" ] && continue
    [ -n "$n_word" ] && [ "$found" = "$n_word" ] && continue
    bad="$bad $found"
  done < <(grep -ioE "$number_re" "$f" | awk '{print tolower($1)}' | sort -u)
  if [ -n "$bad" ]; then
    fail "stale reviewer count(s) in $f:$bad (team has $reviewer_count)"
  else
    pass "no stale reviewer count in $f"
  fi
done

# --- C5: shellcheck (opt-in) ---
echo "== C5: shellcheck (optional) =="
if command -v shellcheck >/dev/null 2>&1; then
  # shellcheck disable=SC2086
  if shellcheck $SCRIPTS; then
    pass "shellcheck clean"
  else
    fail "shellcheck reported issues"
  fi
else
  echo "  SKIP: shellcheck not installed"
fi

# --- C6: tool privileges (least privilege) ---
echo "== C6: tool privileges =="
if python3 scripts/_check_tools.py; then
  pass "agent tool grants satisfy least-privilege rules"
else
  fail "tool privilege check (scripts/_check_tools.py)"
fi

# --- C7: VERSION file present and well-formed ---
echo "== C7: VERSION file =="
if [ -s VERSION ]; then
  version_str="$(tr -d '[:space:]' < VERSION)"
  if printf '%s' "$version_str" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
    pass "VERSION is non-empty and looks like a version ($version_str)"
  else
    fail "VERSION does not look like a version (got: '$version_str')"
  fi
else
  fail "VERSION file missing or empty"
fi

# --- C8: zero-tooling bundle in sync ---
# The committed paste-able bundle (dist/copilot-review-team-bundle.md) is a
# generated artifact. It must be regenerated whenever an agent definition, the
# playbook, or the VERSION file changes (the bundle embeds VERSION), or
# zero-tooling adopters get stale content. Enforce that the committed bundle
# matches a fresh generation from the current sources.
echo "== C8: zero-tooling bundle drift =="
# Capture output so a PASS stays quiet but a FAILURE shows WHAT drifted (the
# generator prints a unified diff of committed-vs-fresh on stderr). Using
# `if ! out=$(...)` keeps this safe under `set -e`.
if bundle_check_output="$(./scripts/build-bundle.sh --check 2>&1)"; then
  pass "dist bundle matches sources (scripts/build-bundle.sh --check)"
else
  fail "bundle is stale — regenerate with scripts/build-bundle.sh"
  printf '%s\n' "$bundle_check_output"
fi

echo ""
if [ "$FAILURES" -eq 0 ]; then
  echo "All checks passed."
  exit 0
else
  echo "$FAILURES check(s) failed."
  exit 1
fi
