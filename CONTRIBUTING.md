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

- **Preserve the cross-family model split.** The main value of the review phase is
  that reviewers run on *different model families* than the developer. If you
  change models, keep the developer and the adversarial reviewers in different
  families (see the model table in the README / playbook).
- **Keep agents self-contained.** Each `local-*.agent.md` is a fresh context — don't
  assume it can see conversation state.
- **Test the installer** before submitting:

  ```bash
  COPILOT_HOME=$(mktemp -d) ./install.sh
  ```

- **Don't commit anything private.** No internal repo names, secrets, tokens, or
  org-specific conventions in the shared files.

That's it. Be kind, have fun, fork freely.
