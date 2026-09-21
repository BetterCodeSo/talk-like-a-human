#!/usr/bin/env bash
# Installs the writing rules and the prose linter for every Claude surface that reads ~/.claude.
# Usage: ./install.sh [--git]     (--git also installs global, warn-only git hooks)
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.config/ai-style"
WITH_GIT=0
[[ "${1:-}" == "--git" ]] && WITH_GIT=1

mkdir -p "$DEST" "$HOME/.claude"
cp "$SRC/writing-rules.md" "$SRC/prose_lint.py" "$SRC/claude-app-instructions.md" "$DEST/"
chmod +x "$DEST/prose_lint.py"

# 1. Instructions: import the rules into the user-level CLAUDE.md (all projects).
CLAUDE_MD="$HOME/.claude/CLAUDE.md"
IMPORT_LINE="@~/.config/ai-style/writing-rules.md"
touch "$CLAUDE_MD"
if ! grep -qF "$IMPORT_LINE" "$CLAUDE_MD"; then
  printf '\n# Writing style for all generated prose\n%s\n' "$IMPORT_LINE" >> "$CLAUDE_MD"
  echo "[ok] import added to $CLAUDE_MD"
else
  echo "[ok] import already present in $CLAUDE_MD"
fi

# 2. Enforcement: PostToolUse hook in user settings (all projects).
SETTINGS="$HOME/.claude/settings.json"
# $HOME stays literal: Claude Code expands it when it runs the hook.
# shellcheck disable=SC2016
HOOK_CMD='python3 "$HOME/.config/ai-style/prose_lint.py" --hook'
if command -v jq >/dev/null 2>&1; then
  [[ -s "$SETTINGS" ]] || echo '{}' > "$SETTINGS"
  cp "$SETTINGS" "$SETTINGS.bak.$(date +%Y%m%d%H%M%S)"
  tmp="$(mktemp)"
  jq --arg cmd "$HOOK_CMD" '
    .hooks = (.hooks // {})
    | .hooks.PostToolUse = (.hooks.PostToolUse // [])
    | if any(.hooks.PostToolUse[]?.hooks[]?; .command == $cmd) then .
      else .hooks.PostToolUse += [{"matcher": "Write|Edit|MultiEdit",
                                   "hooks": [{"type": "command", "command": $cmd}]}]
      end' "$SETTINGS" > "$tmp" && mv "$tmp" "$SETTINGS"
  echo "[ok] PostToolUse hook registered in $SETTINGS (backup kept next to it)"
else
  cat <<MSG
[todo] jq not found. Add this under "hooks" in $SETTINGS:
  "PostToolUse": [{"matcher": "Write|Edit|MultiEdit",
                   "hooks": [{"type": "command", "command": "python3 \\"\$HOME/.config/ai-style/prose_lint.py\\" --hook"}]}]
MSG
fi

# 3. Optional: global git hooks (catch commits made by any tool, Claude or not).
if [[ $WITH_GIT == 1 ]]; then
  mkdir -p "$DEST/git-hooks"
  cp "$SRC/git-hooks/pre-commit" "$SRC/git-hooks/commit-msg" "$DEST/git-hooks/"
  chmod +x "$DEST/git-hooks/"*
  current="$(git config --global --get core.hooksPath || true)"
  if [[ -n "$current" && "$current" != "$DEST/git-hooks" ]]; then
    echo "[skip] core.hooksPath already set to $current; merge $DEST/git-hooks into it manually."
  else
    git config --global core.hooksPath "$DEST/git-hooks"
    echo "[ok] global core.hooksPath -> $DEST/git-hooks (chains to each repo's .git/hooks)"
  fi
fi

cat <<MSG

Manual steps (no file-based config exists for these surfaces):
  claude.ai / Desktop chat / mobile : Settings > General > Instructions for Claude
  Cowork                            : Settings > Cowork > Global instructions
  Paste the content of $DEST/claude-app-instructions.md into both.

Check in Claude Code: run /memory (the import is listed) and /hooks (the hook is listed).
The first session may ask you to approve the external import.
MSG
