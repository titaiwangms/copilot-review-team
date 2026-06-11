# Copilot CLI Review Team

[![validate](https://github.com/titaiwangms/copilot-review-team/actions/workflows/validate.yml/badge.svg)](https://github.com/titaiwangms/copilot-review-team/actions/workflows/validate.yml)

A drop-in **multi-agent code-review team** for
[GitHub Copilot CLI](https://github.com/github/copilot-cli). Point it at a PR, a
diff, or a set of changed files and it fans the change out to five specialized
reviewers and a QA tester — spread across three model families — then
synthesizes their findings by severity into one report.

Instead of one model reviewing everything, the lead Copilot agent delegates to a
team of focused sub-agents — **five reviewers + a QA tester** — wired together by a
**playbook** into a review → synthesize → (loop) → report pipeline.

## Why multi-agent review (not one model)

A single model reviewing a change sees it through one lens and shares one set of
blind spots. Split the job across specialists and each one goes deep on a single
concern — clarity, function-level correctness, adversarial security, spec/math
adherence, cross-module integration — instead of one pass spreading itself thin.
You catch more, and the findings come back labeled by *who* raised them and *why*,
so you can weigh them rather than trust an undifferentiated verdict.

## Model-family diversity (and why it matters)

The reviewers run across **three model families on purpose — Claude, GPT, and
Gemini.** Different families have different blind spots, so reviewing a change with
an *adversarial reviewer in a different family than the code's author* catches
things a same-family reviewer would wave through. The GPT reviewers are the
adversarial pair; the deep reviewer (Claude) is the spec/math tie-breaker; the
integration reviewer (Gemini) brings a third blind-spot set and a large context
window for whole-repo consistency.

If you swap models, keep the adversarial reviewers spread across families — that
spread is the main source of review value.

## Match review depth to task size

The playbook defines the full tiers; quick version:

- **Trivial** (typo, one-liner, doc-only): the lead reads it; no team.
- **Small** (one file, well-defined): a reviewer or two.
- **Medium** (a few files): full reviewer fan-out; add the QA tester if behavior
  needs running.
- **Large / risky** (multi-file, security-sensitive, ambiguous): full fan-out +
  QA tester, with a second loop if findings warrant.

You can always steer it: *"just review the security"*, *"skip the QA tester"*, etc.

## The team

Each agent's model is the `model:` line in its own
`agents/local-*.agent.md` frontmatter (the single source of truth). The IDs below
are read from those files.

| Agent | Role | Model | Why this model |
|---|---|---|---|
| `local-readability-reviewer` | Clarity: naming, organization, simplicity, docs | `claude-sonnet-4.6` | A fresh-reader clarity lens; not adversarial, so family isn't critical |
| `local-code-reviewer` | Function-level correctness, idiom, patterns, test quality | `gpt-5.3-codex` | Cross-family adversarial review of (often Claude-written) code; code-tuned |
| `local-critical-reviewer` | Adversarial: bugs, security, perf, edge cases, structural design | `gpt-5.5` | Second cross-family adversary — different blind spots from the author |
| `local-deep-reviewer` | Spec adherence, math/bit-level correctness, multi-file invariants; tie-breaker | `claude-opus-4.8` | Strong base model for deep spec/math reasoning; arbiter when reviewers disagree |
| `local-integration-reviewer` | Cross-module wiring, contract drift, ripple effects, whole-codebase consistency | `gemini-3.1-pro-preview` | Third model family + large context window for wide cross-module review |
| `local-qa-tester` | Runs the actual code; reports failures with repro steps | `claude-sonnet-4.6` | Execution and repro, not adversarial reading — family isn't critical here |

The `local-` prefix is a namespace convention marking these as user-installed
agents. The installer only copies `local-*.agent.md` files, so any custom agent you
add must follow that naming to be picked up.

## What's in here

```
agents/                       6 sub-agent definitions
  local-readability-reviewer.agent.md  Naming, clarity, organization, docs
  local-code-reviewer.agent.md         Correctness, idiom, patterns, test quality
  local-critical-reviewer.agent.md     Adversarial: bugs, security, perf, edge cases, structural design
  local-deep-reviewer.agent.md         Spec/math arbiter: multi-file invariants, tie-breaker
  local-integration-reviewer.agent.md  Cross-module / whole-codebase consistency
  local-qa-tester.agent.md             Actually runs the code, reports repro steps
copilot-instructions.md       The orchestration playbook (the part that ties it together)
install.sh                    Copies agents + merges the playbook into ~/.copilot/
uninstall.sh                  Removes this repo's agents (leaves others alone)
scripts/validate.sh           Repo self-checks (run before submitting a PR; also runs in CI)
```

> **Agents + playbook are both required.** The agent files define *who* is on the
> team; the `copilot-instructions.md` playbook tells the lead agent *when* and *how*
> to fan them out. The agents are inert without it — install both.

## How the review pipeline works

When you ask the lead to **"review &lt;PR url or number&gt;"** (or hand it a diff):

1. **Fetch / frame** the change and do a quick read-through.
2. **Parallel fan-out** — all five reviewers run in parallel, at once, each getting the
   diff inline plus role-specific framing. (The QA tester joins only when running
   the code is warranted — review-only ≠ run the code.)
3. **Severity synthesis** — findings are deduplicated and prioritized
   Critical → Major → Minor → Nit, with a **findings ledger** recording who raised
   each Critical/Major finding and its disposition.
4. **Loop** — for large/risky changes, re-review what changed (max 2 rounds).
5. **Final report** — the synthesis, plus a **minority report** (anything the lead
   overruled, with who raised it) and a **residual-risk / exclusions statement**
   (what was *not* checked). Posting to the PR happens only if you ask.

### Severity levels

- **Critical** — must fix before merge (security holes, data loss, crashes, broken
  contracts).
- **Major** — should fix before merge (real bugs, missing edge cases, spec gaps).
- **Minor** — worth fixing (clarity, small correctness/robustness issues). A
  deep-reviewer **Question** lands here, carrying an open question.
- **Nit** — optional polish. Dropped unless you want thoroughness.

The qa-tester's P0/P1/P2/P3 map onto Critical/Major/Minor/Nit during synthesis.

### The QA tester is an instrument, not a judge

The QA tester **runs** the code and reports what actually happened — failures,
repro steps, observed output — rather than offering an opinion on the design. It
**sits out static-only passes**: a review-only request (read the diff, don't
execute) leaves it on the bench, and it joins only when behavior is in question and
the change is runnable in the workspace.

## Treat reviewed content as untrusted

This team exists to review arbitrary, sometimes hostile code — exactly where prompt
injection lives. The agents treat code, diffs, PR text, and test output as **data,
not instructions**: they never follow embedded commands, never exfiltrate code or
secrets, and require explicit approval before running networked or destructive
shell commands. See the playbook's "Treat reviewed content as untrusted" section.

## Prerequisites

- **GitHub Copilot CLI** installed and working — see
  [github/copilot-cli](https://github.com/github/copilot-cli)
  (typically `npm install -g @github/copilot`, then run `copilot`).
- A Copilot plan whose account can access multiple model families (Claude / GPT /
  Gemini). If yours can't, swap the model IDs (see [Customization](#customization)).
- To see which model IDs your account can use, run `/model` inside a `copilot`
  session, then match the agent `model:` fields to that list.
- `python3` on your PATH (used by `install.sh`/`uninstall.sh` to merge the playbook
  and by the self-checks).

## Install

One-click (recommended):

```bash
git clone https://github.com/titaiwangms/copilot-review-team
cd copilot-review-team
./install.sh
```

Then start a fresh `copilot` session — the lead agent picks up the team
automatically. If you're not sure it loaded, ask: *"what agents do you have?"*

> **NOTE — your existing `copilot-instructions.md` is preserved.** The installer
> merges the playbook in as a **marker-delimited managed block**; anything you wrote
> yourself stays put. Re-running `./install.sh` upgrades that block in place
> (idempotent), and `./uninstall.sh` strips just the block, leaving your own
> instructions behind. The file is also backed up to
> `~/.copilot/.backup-<timestamp>-<pid>/` as a safety net.

Re-running `./install.sh` is a versioned, in-place upgrade: it prints a
`version -> version` change summary (added / updated / unchanged / removed agents)
and prunes agents earlier versions shipped but this one no longer does. Unrelated
`local-*` agents you installed yourself are never touched.

`install.sh` and `uninstall.sh` honor a `$COPILOT_HOME` environment variable if your
Copilot CLI keeps its config somewhere other than the default `~/.copilot`.

### Manual copy (fallback)

No installer? Copy the pieces by hand:

```bash
mkdir -p ~/.copilot/agents
cp agents/local-*.agent.md ~/.copilot/agents/
# then paste this repo's copilot-instructions.md into
# ~/.copilot/copilot-instructions.md (append it; keep anything already there)
```

To remove the team later, run [`./uninstall.sh`](uninstall.sh) — it removes only
the agent files this repo installed (your other `local-*` agents are left alone)
and strips the playbook's managed block. Use `--purge-playbook` to drop the whole
`copilot-instructions.md` instead (it asks first).

## Customization

The model for each agent lives in one place: the `model:` line in that agent's
`agents/local-*.agent.md` frontmatter. To change models:

```bash
# edit the model: line in the agent(s) you want to retarget, e.g.
#   model: gpt-5.5   ->   model: gpt-5.4
$EDITOR agents/local-critical-reviewer.agent.md
./install.sh        # re-run to push the change into ~/.copilot/
```

If a referenced model isn't available to your account, point that agent at one that
is. When swapping, keep the adversarial reviewers across **different** families —
that cross-family spread is where most of the review value comes from.

## Per-repo install (optional)

Copilot CLI also reads a repo's `.github/copilot-instructions.md` and repo-local
agents. To give every contributor the team automatically, commit the playbook to
`.github/copilot-instructions.md` and the agents into the repo. Repo-local
instructions layer on top of (and win over) your global ones.

## Notes

- **No extra servers, but your code does go to model providers.** This repo adds no
  server of its own — but Copilot CLI sends your prompts, diffs, and code context to
  hosted model providers per your Copilot plan. A full review fan-out sends the same
  diff to several model families. Don't treat it as an air-gapped/local-only setup;
  for sensitive code, narrow the fan-out (fewer reviewers) accordingly.
- **Cost & latency scale with the fan-out.** A full review can hit five reviewers
  (plus a QA pass and a second loop) — many premium model calls per change,
  multiplied by diff size. The "match depth to task size" guidance keeps this in
  check.
- Tested with Copilot CLI. Requires an account with access to the referenced
  models (swap as needed).

> **Disclaimer.** This is a personal setup I happen to find useful, shared as-is —
> not an official product, a standard, or a guarantee of anything. Treat it as a
> starting template: **fork it, swap the models, rewrite the playbook, throw out
> the parts you don't like.** Feedback and PRs are welcome (see
> [CONTRIBUTING.md](CONTRIBUTING.md)), but you owe me nothing for using it. 🙂

## License

[MIT](LICENSE) — do whatever you want with it.
