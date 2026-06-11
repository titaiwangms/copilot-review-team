# Contributing

Thanks for taking a look! This is a personal, opinionated setup shared as-is —
so contributions are welcome but entirely optional, and there's no expectation
of polish.

## The easiest way to "contribute": fork it

The best thing you can do is **make it yours**. Swap models to whatever your
Copilot CLI account has access to, rewrite role prompts, add or remove agents,
reshape the pipeline. You don't need permission and you don't need to upstream
anything.

## If you want to contribute back

- **Issues** — bug reports, "this model ID no longer exists", unclear docs,
  ideas for new agents or pipeline tweaks. All fair game. Use the templates under
  `.github/ISSUE_TEMPLATE/`.
- **Pull requests** — keep them small and focused. A PR that changes one agent's
  prompt or fixes the installer is easy to reason about; a PR that rewrites
  everything is hard to merge.

## Guidelines for changes

- **Preserve the cross-family model split.** The main value of the review is
  that reviewers run on *different model families* than the code's author. If you
  change models, keep the adversarial reviewers in different families (see the
  model-diversity notes in the README and playbook). Each agent's model is the
  `model:` line in its own `agents/local-*.agent.md` frontmatter — the single
  source of truth. Edit it there and re-run `./install.sh`.

- **Keep agents self-contained.** Each `local-*.agent.md` is a fresh context — don't
  assume it can see conversation state.

- **Bump the `VERSION` file when shipping changes.** It holds a single semver line
  (e.g. `1.0.0`). `install.sh` reads it to stamp the install and to print a
  `version -> version` change summary on upgrade. The install manifest
  (`~/.copilot/.copilot-review-team-manifest`) also records `VERSION=` and
  `INSTALLED_AT=` alongside the `AGENT=` lines; bumping `VERSION` is what makes the
  next install report an upgrade.

- **Run the self-checks** before submitting:

  ```bash
  ./scripts/validate.sh
  ```

  This validates script syntax, agent frontmatter, that the playbook team table
  lists exactly the agents on disk, least-privilege tool grants, reviewer-count
  phrasing, and the playbook-merge helper's unit tests (and runs `shellcheck` if
  you have it installed). The same script runs in CI on every push and PR. Expect
  one `PASS`/`FAIL`/`SKIP` line per check and a
  final summary; the exit code is nonzero if any check fails.

- **Don't commit anything private.** No internal repo names, secrets, tokens, or
  org-specific conventions in the shared files.

That's it. Be kind, have fun, fork freely.
