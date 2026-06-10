# `dist/` — generated zero-tooling bundle

This directory holds **generated artifacts**. Do not edit them by hand.

## `copilot-review-team-bundle.md`

A single, paste-able Markdown file containing **every agent definition plus the
orchestration playbook**. It lets someone adopt the review+build team with
**zero tooling** — no git clone, no `install.sh`, no shell access required.

### Why it exists

The installer (`install.sh`) is a convenience, not a requirement: the unit of
value is the Markdown itself. The bundle packages all of it into one file you
can paste into a chat, drop into a gist, or split into the target paths by hand.

### How a user consumes it

Two options, both tooling-free (full instructions are in the bundle header):

1. **Let an AI assistant place the files.** Paste the whole bundle into a Copilot
   CLI / chat session and ask it to create each file at its marked path.
2. **Place the files by hand.** Each embedded file is wrapped in explicit
   sentinels that begin at column 0:

   ```
   ===== BEGIN FILE: .copilot/agents/local-architect.agent.md =====
   ...verbatim contents...
   ===== END FILE: .copilot/agents/local-architect.agent.md =====
   ```

   Create each file at its `<path>` relative to your home directory
   (`.copilot/...` → `~/.copilot/...`). Both the agents **and** the playbook
   (`~/.copilot/copilot-instructions.md`) are required — the agents are inert
   without it.

We use textual sentinels rather than Markdown code fences because the agent
files and playbook contain their own ```` ``` ```` fences; nested fencing would
break. The sentinels are guarded against collision by the generator.

### How it stays in sync

The bundle is produced by [`scripts/build-bundle.sh`](../scripts/build-bundle.sh)
directly from `agents/local-*.agent.md` and `copilot-instructions.md`, so it
never drifts from the real sources.

```bash
scripts/build-bundle.sh            # (re)write this bundle
scripts/build-bundle.sh --check    # verify the committed bundle is up to date
scripts/build-bundle.sh --stdout   # print without writing a file
```

Generation is deterministic (sorted inputs, no timestamps). CI enforces sync via
check **C9** in [`scripts/validate.sh`](../scripts/validate.sh): if you change an
agent or the playbook, regenerate the bundle in the same commit or the check
fails.
