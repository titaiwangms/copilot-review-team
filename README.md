# Copilot CLI Review + Build Team

[![validate](https://github.com/titaiwangms/copilot-review-team/actions/workflows/validate.yml/badge.svg)](https://github.com/titaiwangms/copilot-review-team/actions/workflows/validate.yml)

A drop-in **multi-agent SDLC team** for [GitHub Copilot CLI](https://github.com/github/copilot-cli):
it **designs, builds, reviews, and fixes** code, end to end.

Instead of one model doing everything, this setup gives the lead Copilot agent a
team of specialized sub-agents — an architect, a developer, and a tech writer that
**build** (design, implement, and document), plus five reviewers (spread across three
model families — Claude, GPT, and Gemini) and a QA tester that **review** — wired
together by a **playbook** into a design → build → review → fix pipeline.

The result: code changes get designed up front, implemented, then reviewed in
parallel for correctness, security, edge cases, spec adherence, cross-module
integration, and readability — and looped back for fixes — before they ever reach you.

Want just a review pass? Ask it to **"review &lt;PR&gt;"** and it runs the reviewers only,
without touching code (the QA tester, which *executes* code, sits out). **Build and review
are two first-class halves of one team** — use the whole pipeline or either half on its own.

> **Disclaimer.** This is a personal setup I happen to find useful, shared as-is —
> not an official product, a standard, or a guarantee of anything. Treat it as a
> starting template: **fork it, swap the models, rewrite the playbook, throw out
> the parts you don't like.** Feedback and PRs are welcome (see
> [CONTRIBUTING.md](CONTRIBUTING.md)), but you owe me nothing for using it. 🙂

## What's in here

```
agents/                       9 sub-agent definitions
  local-architect.agent.md          Designs the approach (short design doc)
  local-developer.agent.md          Implements code + tests from the design
  local-readability-reviewer.agent.md  Naming, clarity, organization, docs
  local-code-reviewer.agent.md      Correctness, idiom, patterns, test quality
  local-critical-reviewer.agent.md  Adversarial: security, perf, failure modes, structural design
  local-deep-reviewer.agent.md      Spec/math arbiter: multi-file invariants, tie-breaker when reviewers disagree
  local-integration-reviewer.agent.md  Cross-module / whole-codebase consistency
  local-qa-tester.agent.md          Actually runs the code, reports repro steps
  local-tech-writer.agent.md        Docs, examples, READMEs, changelogs
copilot-instructions.md       The orchestration playbook (the part that ties it together)
models.conf                   Agent → model mapping (the knob you edit to swap models)
set-models.sh                 Applies models.conf to the agents + playbook table
install.sh                    Copies everything into ~/.copilot/
uninstall.sh                  Removes this repo's agents from ~/.copilot/ (leaves others alone)
scripts/validate.sh           Repo self-checks (run before submitting a PR; also runs in CI)
examples/                     Illustrative design-doc + review-synthesis samples
```

> **One install, two jobs.** This team is two first-class halves of a single
> design → build → review → fix loop — a **build** side (architect → developer → tech
> writer) and a **review** side (five reviewers + QA tester) — not a review tool with
> build bolted on. Use the whole pipeline, or just the review half (see
> ["How it behaves"](#how-it-behaves)).
>
> **Agents + playbook ship together.** The agent files define *who* is on the team; the
> `copilot-instructions.md` playbook tells the lead agent *when* and *how* to fan them
> out. Install both for the full workflow.

The `local-` prefix is just a namespace convention to mark these as user-installed
agents. The installer only copies `local-*.agent.md` files, so any custom agent you
add must follow that naming to be picked up.

## Prerequisites

- **GitHub Copilot CLI** installed and working — see
  [github/copilot-cli](https://github.com/github/copilot-cli) for install instructions
  (typically `npm install -g @github/copilot`, then run `copilot`).
- A Copilot plan whose account can access multiple model families (Claude / GPT /
  Gemini). If yours can't, you'll swap the model IDs — see
  [Model diversity](#model-diversity--why-it-matters-and-what-breaks-if-you-change-it).
- To see which model IDs your account can use, run `/model` inside a `copilot` session
  (or check your Copilot settings), then match the agent `model:` fields to that list.

## Install

```bash
git clone https://github.com/titaiwangms/copilot-review-team
cd copilot-review-team
./install.sh
```

Then start a fresh `copilot` session. The lead agent will pick up the team
automatically.

`install.sh` backs up any existing `~/.copilot/copilot-instructions.md` and
matching agent files to `~/.copilot/.backup-<timestamp>-<pid>/` before overwriting, so
it's safe to re-run.

Re-running `./install.sh` upgrades in place: it stamps the installed version,
prints a `version -> version` change summary (added / updated / unchanged /
removed per agent), and prunes any agents that were removed or renamed in a
newer version. Unrelated `local-*` agents you installed yourself are never
touched — only agents recorded in this repo's install manifest are pruned.

`install.sh` and `uninstall.sh` honor a `$COPILOT_HOME` environment variable if your
Copilot CLI keeps its config somewhere other than the default `~/.copilot`.

## Try this first

After installing, open a `copilot` session in any git repo and ask for something small:

> "Add input validation to function `foo` in `src/…` and write a test for it."

You should see the lead agent classify the task, delegate to `local-developer`, then
fan out a reviewer or two plus `local-qa-tester`, and summarize what it found. For a
bigger ask ("refactor module X to support Y") it runs the full pipeline, starting with
an architect design doc it shows you for approval. If you're not sure it loaded, ask:
*"what agents do you have?"*

For a sense of what the team's artifacts look like before you run it, see
[`examples/`](examples/) — a sample architect design doc and the matching review
synthesis for one small change (illustrative, not actual run output).

### Already have a `copilot-instructions.md`?

The installer replaces it (after backing it up). To keep your own instructions, open the
backup at `~/.copilot/.backup-<timestamp>-<pid>/copilot-instructions.md`, copy everything
from the `# Multi-agent team playbook` heading to the end of this repo's
`copilot-instructions.md`, and paste it into your file (top or bottom — the lead reads
the whole file; order matters only if sections directly conflict).

## Model diversity — why it matters and what breaks if you change it

The reviewers are spread across **three model families on purpose**:

| Role | Model family | Why |
|---|---|---|
| Architect, Developer | Claude | Cooperative design → build handoff |
| Code + Critical reviewers | GPT | Cross-family adversarial review of Claude-written code |
| Deep reviewer | Claude (Opus) | Spec/math tie-breaker |
| Integration reviewer | Gemini | Third blind-spot set, large context for whole-repo review |
| Readability reviewer | Claude | Fresh-reader clarity lens |

Different model families have different blind spots. Reviewing Claude-written code
with GPT and Gemini catches things a same-family reviewer misses. If you swap
models, keep developer and the adversarial reviewers in **different** families.

The exact model IDs live in each `agents/local-*.agent.md` and in the table in
`copilot-instructions.md`. Adjust them to whatever your Copilot CLI account has
access to — if a referenced model isn't available to you, point that agent at one
that is.

### Customizing models

Don't hand-edit the model IDs in nine agent files and the playbook table
separately — they have to stay in sync. Instead, edit the single mapping in
[`models.conf`](models.conf) and let the tooling apply it everywhere:

```bash
$EDITOR models.conf        # change the model IDs you want
./set-models.sh --dry-run  # preview the exact edits (writes nothing)
./set-models.sh            # apply to agent frontmatter + the playbook table
./install.sh               # copy the updated files into ~/.copilot/
```

`./set-models.sh --check` verifies the agent frontmatter and the playbook table
agree (this is what CI runs); it exits nonzero on drift. The prettified family
names in the prose (e.g. "Claude Opus 4.8") are a manual concern — the tool only
touches the machine-readable model IDs.

To remove the team later, run [`./uninstall.sh`](uninstall.sh) — it removes only
the agent files this repo installed (your other `local-*` agents are left alone)
and restores your previous `copilot-instructions.md` from the install backup.

## How it behaves

The playbook matches effort to task size:

- **Trivial** (typo, one-liner): the lead just does it, no team.
- **Small**: developer + one reviewer + QA.
- **Non-trivial / multi-file**: full pipeline — architect, developer, parallel
  review fan-out, synthesize findings, loop back to the developer (max 2 rounds),
  then docs.

You can always override: say *"just do it"*, *"skip the team"*, or
*"have the QA tester run the tests"* to short-circuit it.

For PR reviews, ask the lead to **"review &lt;PR url&gt;"** and it runs a review-only
pipeline (five reviewers in parallel, synthesized by severity) without touching code.
The QA tester is deliberately excluded from this pass — it verifies behavior by *running*
your code, which a review-only pass (static review, no execution) does not do.

## Per-repo install (optional)

Copilot CLI also reads a repo's `.github/copilot-instructions.md` and repo-local
agents. To give every contributor the team automatically, commit the playbook to
`.github/copilot-instructions.md` and the agents into the repo. Repo-local
instructions layer on top of (and win over) your global ones.

## Notes

- **No extra servers, but your code does go to model providers.** This repo adds no
  server or external service of its own — but the workflow is built on Copilot CLI, which
  sends your prompts, diffs, and code context to hosted model providers per your Copilot
  plan. A full review fan-out sends the same diff to several model families. Don't treat
  it as an air-gapped/local-only setup; for sensitive code, narrow the pipeline (e.g.
  fewer reviewers) accordingly.
- **Cost & latency scale with the pipeline.** A non-trivial task can fan out to architect
  + developer + 5 reviewers + QA, possibly a second loop, then docs — i.e. many premium
  model calls per change, multiplied by diff size. The "match depth to task size" guidance
  in the playbook keeps this in check; lean on *"just do it"* / *"skip the team"* for small
  work.
- Tested with Copilot CLI. Requires an account with access to the referenced
  models (swap as needed).

## Known limitations

Documented, accepted trade-offs for the single-user install this tool targets — not open
action items. See the linked issues for detail.

- **`install.sh` backup→remove is not atomic (a TOCTOU-style race).**
  ([#4](https://github.com/titaiwangms/copilot-review-team/issues/4)) When replacing a
  symlink or pruning an orphaned agent, the installer backs the file up and then removes
  it as two separate steps. A process racing in between could leave the removed bytes
  differing from the backed-up bytes. The window is theoretical under the intended
  single-user use — the installer isn't meant to run concurrently with itself — and is
  empirically safe in testing. A `flock` lockfile under `$COPILOT_DIR` would close it if
  multi-user installs ever become a use case.
- **Install manifest is trusted by name.**
  ([#5](https://github.com/titaiwangms/copilot-review-team/issues/5)) Upgrades prune
  agents recorded in `~/.copilot/.copilot-review-team-manifest`. Path-traversal names are
  already rejected, but a *validly-named* foreign agent hand-injected into the manifest
  would be pruned on the next upgrade. This requires the user to tamper with their own
  manifest, so the practical risk is near-zero. The prune is also reversible: agents are
  `backup()`'d to `~/.copilot/.backup-<timestamp>-<pid>/` before removal, so an erroneous
  prune can be restored rather than lost. Recording per-agent ownership (a content hash
  and/or installer marker) and only pruning entries this installer actually wrote would
  harden it further.

## License

[MIT](LICENSE) — do whatever you want with it.
