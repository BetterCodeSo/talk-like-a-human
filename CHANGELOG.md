# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow [semantic versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-09-21 <!-- ai-style: ignore, Keep a Changelog date format -->

First public release.

### Added

- `prose_lint.py`, a dependency-free linter with 51 checks over French and English prose: 46 regex rules and 5 document-level measures, split between blocking errors and warnings that print without failing.
- Text extraction for Markdown, HTML, reStructuredText, AsciiDoc, LaTeX, plain text and `.docx`. Fenced blocks, inline code, URLs and HTML comments are masked so code samples are never linted.
- Five modes: file arguments, `--stdin`, `--hook` for the Claude Code `PostToolUse` event, `--commit-msg` and `--git-staged`.
- Suppression through `ai-style: ignore` on a line, or an `ai-style: off` and `ai-style: on` pair around a block. `AI_STYLE_STRICT=1` promotes warnings to errors.
- `writing-rules.md`, imported by `~/.claude/CLAUDE.md` so the rules reach every project, and `claude-app-instructions.md` for the chat surfaces that have no config file.
- `install.sh`, which copies the files to `~/.config/ai-style/`, adds the import, registers the `PostToolUse` hook through `jq` and keeps a backup of `settings.json`. The `--git` flag also installs the git hooks globally.
- Global `pre-commit` and `commit-msg` hooks. Both warn by default, block when `AI_STYLE_GIT_BLOCK=1`, and chain to the repository's own hooks.
- Unit tests covering each rule family, the masking and suppression paths, every mode and the severity model.
- GitHub Actions running the tests on Python 3.9 to 3.13, the linter on this repository's own prose, and shellcheck on the shell scripts.

[Unreleased]: https://github.com/BetterCodeSo/talk-like-a-human/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/BetterCodeSo/talk-like-a-human/releases/tag/v0.1.0
