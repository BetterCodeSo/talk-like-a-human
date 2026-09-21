# talk-like-a-human

This repository holds the writing rules, the prose linter and the hooks that wire both into Claude Code and git. The public remote is `BetterCodeSo/talk-like-a-human`.

## Update the repository on every change

Any change to `prose_lint.py`, `writing-rules.md`, `claude-app-instructions.md`, `install.sh` or the git hooks ends with the work pushed to `origin/main`.

1. Make the change, and add or update the tests that cover it.
2. Run `make check`. The unit tests, the linter on this repository's own prose and shellcheck all have to pass before anything is committed.
3. Update `README.md` when the behavior a user sees changed: a new mode, a new flag, a different exit code, a different rule count.
4. Add an entry under `## [Unreleased]` in `CHANGELOG.md`, in the Added, Changed, Fixed or Removed section that fits.
5. Commit with a message that says what changed and why, then `git push origin main`.

Check that the CI run passed afterwards with `gh run list --repo BetterCodeSo/talk-like-a-human --limit 1`. Fix a red run in the same session.

A release adds three steps. Move the `Unreleased` entries under a new `## [x.y.z] - YYYY-MM-DD` heading and update the comparison links at the bottom of the file. Tag with `git tag -a vx.y.z -m "..."`. Then `git push origin vx.y.z` and `gh release create vx.y.z --title "vx.y.z" --notes "..."`.

Versions follow semantic versioning. A new rule or a new mode is a minor bump. A rule that stops firing on text it used to flag, a renamed rule id or a changed exit code is a major bump, because people wire this into hooks that block their commits.

## Pushing as BetterCodeSo

The active `gh` account on this machine is `Sofiane-Kihal`. Anything that goes through `gh` and writes to the repository, a release or a topic edit, needs `gh auth switch --user BetterCodeSo` first and a switch back afterwards.

Plain `git push` needs no switch. A global `url.insteadOf` rewrites `git@github.com:BetterCodeSo/` to the `github.com-bettercodeso` SSH alias, which carries the right key.

## Adding a rule

Rules live in the `RULES` list in `prose_lint.py`, each one a tuple of id, severity, regex and hint. Errors fail a run. Warnings print and pass, so a word that is sometimes the exact technical term belongs at warning level. The five document-level checks sit in `lint_text` instead, since they measure the whole text rather than a span.

Every new rule needs two tests in `tests/test_prose_lint.py`: a sentence that must fire it, and a rewrite of the same idea that must stay clean. The second test is what catches a regex that grew too greedy.

The rule count appears in `README.md` and in `CHANGELOG.md`. Update both when the list changes.

## Keeping the two rule files in sync

`writing-rules.md` is the long version imported by `~/.claude/CLAUDE.md`. `claude-app-instructions.md` is the condensed version pasted into claude.ai, the desktop chat and Cowork. A rule added to one belongs in the other.

Both files are exempt from linting by name, because they quote the patterns they ban. Nothing else here is exempt, so `README.md`, `CHANGELOG.md` and this file have to pass `make lint-docs`.

After editing `writing-rules.md`, `prose_lint.py` or the hooks, run `./install.sh --git` so the live copy under `~/.config/ai-style/` matches the repository. Skip it and Claude keeps reading the old rules on this machine.

## Commands

```sh
make test        # unit tests
make lint-docs   # the linter on README.md, CHANGELOG.md and CLAUDE.md
make check       # both, plus shellcheck when it is installed
./install.sh --git
```
