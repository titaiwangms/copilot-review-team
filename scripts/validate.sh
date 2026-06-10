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

SCRIPTS="install.sh uninstall.sh set-models.sh scripts/validate.sh"

# --- prerequisite: python3 ---
echo "== prerequisites =="
if command -v python3 >/dev/null 2>&1; then
  pass "python3 available"
else
  fail "python3 not found on PATH — required by set-models.sh and these checks"
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

# --- C3: model drift (single source of truth: set-models.sh --check) ---
echo "== C3: model drift =="
if ./set-models.sh --check; then
  pass "frontmatter == table (set-models.sh --check)"
else
  fail "model drift detected (set-models.sh --check)"
fi
if python3 scripts/_check_table_sets.py; then
  pass "table agent set == agent file set"
else
  fail "table agent set != agent file set"
fi

# --- C4: models.conf consistency ---
echo "== C4: models.conf =="
if python3 scripts/_check_models_conf.py; then
  pass "models.conf matches frontmatter"
else
  fail "models.conf inconsistent with frontmatter"
fi

# --- C5: reviewer-count phrasing (fork-friendly) ---
# Derive the reviewer count N from the actual files rather than hard-coding 5,
# so a fork that adds/removes a reviewer still passes as long as it is
# internally consistent. We then assert every reviewer body and every count
# phrasing in the docs agrees with N.
echo "== C5: reviewer count phrasing =="
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

# --- C6: shellcheck (opt-in) ---
echo "== C6: shellcheck (optional) =="
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

# --- C7: tool privileges (least privilege) ---
echo "== C7: tool privileges =="
if python3 scripts/_check_tools.py; then
  pass "agent tool grants satisfy least-privilege rules"
else
  fail "tool privilege check (scripts/_check_tools.py)"
fi

# --- C8: VERSION file present and well-formed ---
echo "== C8: VERSION file =="
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

echo ""
if [ "$FAILURES" -eq 0 ]; then
  echo "All checks passed."
  exit 0
else
  echo "$FAILURES check(s) failed."
  exit 1
fi
