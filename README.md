# Copilot CLI Review Team

[![validate](https://github.com/titaiwangms/copilot-review-team/actions/workflows/validate.yml/badge.svg)](https://github.com/titaiwangms/copilot-review-team/actions/workflows/validate.yml)

A drop-in **multi-agent code-review system** for
[GitHub Copilot CLI](https://github.com/github/copilot-cli). Point it at a PR, a
diff, or a set of changed files and it defaults to a fast two-agent lightweight
review. Risky or escalated changes fan out to five specialized reviewers and a
QA tester spread across three model families.

The playbook provides two deliberately separate paths:

- **Lightweight team:** MAI-Code-1.1-Flash checks implementation correctness while
  Claude Sonnet 5 checks semantic and adversarial risk.
- **Full team:** five deep specialists plus an optional QA tester handle risky,
  wide, or escalated changes.

## Why two review depths

Routine coding feedback should be fast enough to run after development without
turning every change into a premium-model tax. The lightweight pair uses bounded
context, reports at most three concrete findings each, and escalates instead of
expanding into a repository audit.

High-risk changes still need specialist depth. The full team covers clarity,
function-level correctness, adversarial security and architecture, spec/math
adherence, and cross-module integration.

## Why multi-agent review (not one model)

A single model reviewing a change sees it through one lens and shares one set of
blind spots. Split the job across specialists and each one goes deep on a single
concern — clarity, function-level correctness, adversarial security, spec/math
adherence, cross-module integration — instead of one pass spreading itself thin.
You catch more, and the findings come back labeled by *who* raised them and *why*,
so you can weigh them rather than trust an undifferentiated verdict.

## Model-family diversity (and why it matters)

The lightweight pair uses **MAI + Claude**, providing two distinct model-family
perspectives without paying for a full fan-out. The full team runs across
**Claude, GPT, and Grok**: GPT supplies the adversarial pair, Claude handles
clarity and deep spec/math reasoning, and Grok is reserved for whole-repository
integration tracing.

If you swap models, keep the adversarial reviewers spread across families — that
spread is the main source of review value.

## Match review depth to task size

The playbook defines the full tiers; quick version:

- **Trivial** (typo, one-liner, doc-only): the lead reads it; no team.
- **Routine** (bounded scope, no escalation trigger): lightweight pair.
- **Risky or wide**: full reviewer fan-out; add the QA tester only when runtime
  evidence is needed.

You can always steer it: *"just review the security"*, *"skip the QA tester"*, etc.

## The teams

Each agent's model is the `model:` line in its own
`agents/local-*.agent.md` frontmatter (the single source of truth). The IDs below
are read from those files.

| Agent | Role | Model | Why this model |
|---|---|---|---|
| `local-lightweight-code-review` | Fast implementation correctness, tests, and direct callers | `mai-code-1.1-flash` | Low-latency coding specialist for routine real-time review |
| `local-lightweight-risk-review` | Fast semantic intent, failure modes, and local contracts | `claude-sonnet-5` | Strong reasoning and a different family from a GPT developer |
| `local-readability-reviewer` | Clarity: naming, organization, simplicity, docs | `claude-sonnet-5` | A fresh-reader clarity lens; not adversarial, so family isn't critical |
| `local-code-reviewer` | Function-level correctness, idiom, patterns, test quality | `gpt-5.3-codex` | Cross-family adversarial review of (often Claude-written) code; code-tuned |
| `local-critical-reviewer` | Adversarial: bugs, security, perf, edge cases, structural design | `gpt-5.6-sol` | Second cross-family adversary — different blind spots from the author (now the GPT-5.6 flagship, Sol tier) |
| `local-deep-reviewer` | Spec adherence, math/bit-level correctness, multi-file invariants; tie-breaker | `claude-opus-5` | Strong base model for deep spec/math reasoning; arbiter when reviewers disagree |
| `local-integration-reviewer` | Cross-module wiring, contract drift, ripple effects, whole-codebase consistency | `grok-4.6` | Third model family + large context window for wide cross-module review |
| `local-qa-tester` | Runs the actual code; reports failures with repro steps | `gpt-5.6-sol` | Authoring repros, cold-env build bring-up, and driving sanitizers/benchmarks is agentic-reasoning-heavy — not mere log reading — so it gets a strong agentic tool-use model |

The `local-` prefix is a namespace convention marking these as user-installed
agents. The installer only copies `local-*.agent.md` files, so any custom agent you
add must follow that naming to be picked up.

## What's in here

```
agents/                       8 sub-agent definitions
  local-lightweight-code-review.agent.md  Fast implementation review
  local-lightweight-risk-review.agent.md  Fast semantic/adversarial review
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

After code is written, or when you ask the lead to
**"review &lt;PR url or number&gt;"**:

1. **Fetch / frame** the change and do a quick read-through.
2. **Route** — routine changes run MAI + Sonnet lightweight review in parallel.
   Changes already matching an escalation trigger skip directly to the full team.
3. **Handle the verdict**:
   - Combine parallel results using `ESCALATE > FINDINGS > PASS`.
   - `PASS`: run the smallest relevant validation and finish.
   - `FINDINGS`: for implementation work, fix and re-run only the lightweight
     agent whose finding was affected. For review-only requests, report the
     finding and wait for a revised diff.
   - `ESCALATE`: preserve both reports' trigger, reason, evidence, findings, and
     exclusions, then run the full five-reviewer team. Lightweight escalation is
     a routing handoff inside the current round, not an additional completed round.
4. **Full fan-out when needed** — all five full reviewers run in parallel. The QA
   tester joins only when runtime evidence is warranted.
5. **Severity synthesis** — findings are deduplicated and prioritized
   Critical → Major → Minor → Nit, with a **findings ledger** recording who raised
   each Critical/Major full-team finding and its disposition.
6. **Loop** — re-review only affected areas, with a global maximum of two
   completed review rounds. If a lightweight pass escalates, the full-team pass
   completes that same round; escalation does not reset the count. If round one
   reached the full team, round two is a targeted full-team re-review. The cap
   applies per diff revision.
7. **Final report** — lightweight review includes any one-line minority note
   for an overruled Major. Full review also includes the findings ledger, full
   **minority report**, and a **residual-risk / exclusions statement**. Posting
   to the PR happens only if you ask.

For review-only requests, the lead never edits code. The author supplies a
revised diff before another review cycle begins.

### Escalation triggers

Use the full team immediately, or escalate from lightweight review, for:

- authentication, authorization, secrets, cryptography, or untrusted input
- destructive persistence, migrations, or data-format compatibility
- public APIs, schemas, wire/event formats, ABI, or serialization
- concurrency, locking, or resource lifecycles
- external specifications, numerical proofs, or bit-level invariants
- changes requiring transitive tracing beyond direct consumers
- runtime behavior that cannot be settled by reading
- a possible Critical issue, or scope/intent that cannot be bounded confidently

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
- A Copilot plan whose account can access the configured model families (MAI /
  Claude / GPT / Grok). If yours can't, swap the model IDs (see
  [Customization](#customization)).
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
#   model: claude-sonnet-5   ->   model: claude-opus-5
$EDITOR agents/local-readability-reviewer.agent.md
./install.sh        # re-run to push the change into ~/.copilot/
```

If a referenced model isn't available to your account, point that agent at one that
is. When swapping, keep the adversarial reviewers across **different** families —
that cross-family spread is where most of the review value comes from.

### Tracking agent changes

There's no changelog to maintain — git history *is* the per-agent evolution log.
Each agent is a single self-contained file, so its full history is one command away:

```bash
# how one agent's prompt evolved, line by line, over time
git log --follow -p agents/local-critical-reviewer.agent.md

# just the commits that touched any agent
git log --oneline -- agents/
```

On GitHub, the **History** button on any `agents/local-*.agent.md` file shows the
same thing in the browser, and **Blame** shows which commit last changed each line.

## Per-repo install (optional)

Copilot CLI also reads a repo's `.github/copilot-instructions.md` and repo-local
agents. To give every contributor the team automatically, commit the playbook to
`.github/copilot-instructions.md` and the agents into the repo. Repo-local
instructions layer on top of (and win over) your global ones.

## Notes

- **No extra servers, but your code does go to model providers.** This repo adds no
  server of its own — but Copilot CLI sends your prompts, diffs, and code context to
  hosted model providers per your Copilot plan. Lightweight review sends bounded
  context to two providers; a full review sends the diff to several model families.
  Don't treat it as an air-gapped/local-only setup.
- **Cost & latency scale with the fan-out.** Routine work defaults to two bounded
  review calls. Full review can still hit five reviewers plus QA, but only after
  objective risk routing or escalation.
- Tested with Copilot CLI. Requires an account with access to the referenced
  models (swap as needed).

> **Disclaimer.** This is a personal setup I happen to find useful, shared as-is —
> not an official product, a standard, or a guarantee of anything. Treat it as a
> starting template: **fork it, swap the models, rewrite the playbook, throw out
> the parts you don't like.** Feedback and PRs are welcome (see
> [CONTRIBUTING.md](CONTRIBUTING.md)), but you owe me nothing for using it. 🙂

## License

[MIT](LICENSE) — do whatever you want with it.
