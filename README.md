# Copilot CLI Review Team

A drop-in **multi-agent review team** for [GitHub Copilot CLI](https://github.com/github/copilot-cli).

Instead of one model doing everything, this setup gives the lead Copilot agent a
team of specialized sub-agents — an architect, a developer, five reviewers (each on
a deliberately different model family), a QA tester, and a tech writer — and a
**playbook** that wires them into a design → build → review → fix pipeline.

The result: code changes get designed up front, implemented, then reviewed in
parallel for correctness, security, edge cases, spec adherence, cross-module
integration, and readability — before they ever reach you.

## What's in here

```
agents/                       9 sub-agent definitions
  local-architect.agent.md          Designs the approach (short design doc)
  local-developer.agent.md          Implements code + tests from the design
  local-readability-reviewer.agent.md  Naming, clarity, organization, docs
  local-code-reviewer.agent.md      Correctness, idiom, patterns, test quality
  local-critical-reviewer.agent.md  Adversarial: bugs, security, perf, edge cases
  local-deep-reviewer.agent.md      Spec adherence, math, multi-file invariants
  local-integration-reviewer.agent.md  Cross-module / whole-codebase consistency
  local-qa-tester.agent.md          Actually runs the code, reports repro steps
  local-tech-writer.agent.md        Docs, examples, READMEs, changelogs
copilot-instructions.md       The orchestration playbook (the part that ties it together)
install.sh                    Copies everything into ~/.copilot/
```

> **Both pieces are required.** The agents are inert without the playbook —
> `copilot-instructions.md` is what tells the lead agent *when* and *how* to fan
> them out. Installing only the agents won't reproduce the workflow.

## Install

```bash
git clone <this-repo-url> copilot-review-team
cd copilot-review-team
./install.sh
```

Then start a fresh `copilot` session. The lead agent will pick up the team
automatically.

`install.sh` backs up any existing `~/.copilot/copilot-instructions.md` and
matching agent files to `~/.copilot/.backup-<timestamp>/` before overwriting, so
it's safe to re-run.

### Already have a `copilot-instructions.md`?

The installer replaces it (after backing it up). If you have your own global
instructions you want to keep, open the backup and **merge** the
"Multi-agent team playbook" section into your file by hand rather than letting it
be replaced wholesale.

## Model diversity (the secret sauce — change carefully)

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

## Per-repo install (optional)

Copilot CLI also reads a repo's `.github/copilot-instructions.md` and repo-local
agents. To give every contributor the team automatically, commit the playbook to
`.github/copilot-instructions.md` and the agents into the repo. Repo-local
instructions layer on top of (and win over) your global ones.

## Notes

- These are plain Copilot CLI custom agents — no servers, no external services.
- Tested with Copilot CLI. Requires an account with access to the referenced
  models (swap as needed).
