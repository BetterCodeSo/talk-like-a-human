# talk-like-a-human

Stops Claude from writing like a language model. Three pieces: a rules file that Claude reads before it writes, a Python linter that checks what came out, and hooks that wire both into Claude Code and git.

Works in French and English. The linter has no dependencies outside the Python 3.9 standard library.

## What the linter catches

51 checks. 46 are regexes over the text; 5 are computed over the whole document.

Punctuation and layout: em dashes, en dashes used as sentence dashes, emoji bullets and status markers, `**Label:** text` bullets, Title Case headings, summary sections that repeat what was already said.

Sentence templates: contrastive reframes in both languages, self-answered questions, setup-and-reveal colons, runs of short fragments for effect, aphoristic closers, false ranges, signposting.

Openers and closers: praise openers, output narration, closing offers, recap endings, empathy formulas.

Vocabulary: the stock phrases (`delve`, `unlock the full potential`, `il convient de souligner`, `tirer pleinement parti`), the French calques (`adresser un problème`, `impactant`), hedge stacks, vague authority, personified abstractions.

Two document-level measures round it out. `RHYTHM_UNIFORM` fires when the coefficient of variation of sentence length drops below 0.35 over at least 15 sentences, which is what uniform LLM pacing looks like. `RHYTHM_TRIADS` fires above 6 groups of three per 1000 words.

Findings come in two severities. An error fails the run; a warning prints and passes, because some flagged words are the right technical term in context. `AI_STYLE_STRICT=1` promotes warnings to errors everywhere.

## Install

```sh
git clone https://github.com/BetterCodeSo/talk-like-a-human.git
cd talk-like-a-human
./install.sh --git
```

The installer copies `writing-rules.md`, `prose_lint.py` and `claude-app-instructions.md` to `~/.config/ai-style/`, adds an `@~/.config/ai-style/writing-rules.md` import to `~/.claude/CLAUDE.md`, and registers a `PostToolUse` hook on `Write|Edit|MultiEdit` in `~/.claude/settings.json`. The settings file is backed up next to itself before it is touched. Registering the hook needs `jq`; without it the installer prints the JSON block for you to paste.

`--git` also installs the two git hooks globally through `core.hooksPath`. If that config already points somewhere else, the installer says so and changes nothing.

Two surfaces have no file-based config. For claude.ai, the desktop chat and mobile, paste `claude-app-instructions.md` into Settings, General, Instructions for Claude. For Cowork, the same text goes into Settings, Cowork, Global instructions.

Verify with `/memory` and `/hooks` in Claude Code. The first session may ask you to approve the external import.

## Usage

```sh
python3 prose_lint.py README.md docs/*.md   # exit 1 on an error
python3 prose_lint.py --strict README.md    # warnings fail too
python3 prose_lint.py --stdin < draft.md
python3 prose_lint.py --commit-msg .git/COMMIT_EDITMSG
python3 prose_lint.py --git-staged          # added lines in staged prose files
python3 prose_lint.py --hook                # Claude Code PostToolUse, JSON on stdin
```

Output is one finding per line:

```
README.md:12:1: error RHET_Q_REVEAL_EN: "The result? Two seconds saved." -> self-answered question: make the statement
```

Prose extensions are `.md`, `.mdx`, `.markdown`, `.txt`, `.rst`, `.adoc`, `.asciidoc`, `.tex`, `.html`, `.htm` and `.docx`. Word files are read straight from the zip, no library needed. Markdown fenced blocks, inline code, URLs and HTML comments are masked before linting, so code samples never trigger a rule.

### Exit codes

`0` clean, `1` an error was found, `2` in hook mode only. Claude Code reads exit code 2 as a blocking failure and feeds the stderr text back to the model, which is what makes it rewrite the sentence instead of moving on.

### Suppression

A line containing `ai-style: ignore` is skipped. Everything between `ai-style: off` and `ai-style: on` is skipped. In Markdown, put the marker in an HTML comment:

```md
<!-- ai-style: off -->
Quoted text that should not be rewritten.
<!-- ai-style: on -->
```

`writing-rules.md` and `claude-app-instructions.md` are exempt by name, along with anything under `~/.config/ai-style/`. They quote the patterns they ban, so linting them would flag every example.

## The git hooks

Both hooks warn and let the commit through by default. `AI_STYLE_GIT_BLOCK=1` makes an error block it. Each one chains to the repository's own hook of the same name afterwards, so a project that already has a `pre-commit` keeps it.

`pre-commit` lints the lines added in staged prose files, not the whole file, so an old document does not block work on a new paragraph. `commit-msg` lints the message with comment lines and the diff below the scissors line removed.

## Repository layout

```
prose_lint.py               the linter
writing-rules.md            imported by ~/.claude/CLAUDE.md
claude-app-instructions.md  condensed version for chat surfaces
install.sh                  installer
git-hooks/                  pre-commit and commit-msg
tests/                      unit tests
```

## Development

```sh
make test        # unit tests
make lint-docs   # run the linter on this repo's prose
make check       # both, plus shellcheck if it is installed
```

## Uninstall

```sh
rm -rf ~/.config/ai-style
git config --global --unset core.hooksPath
```

Then remove the import line from `~/.claude/CLAUDE.md` and the `PostToolUse` entry from `~/.claude/settings.json`.

## Licence

MIT. See [LICENSE](LICENSE).
