#!/usr/bin/env bash
# Symlink every agent in this repo into the directory each tool reads from:
#   agents/*.md   -> ~/.claude/agents, ~/.junie/agents
#   codex/*.toml  -> ~/.codex/agents   (generated: run scripts/build_codex.py first)
# Idempotent: re-run after adding, renaming or deleting an agent.
# Every directory can be overridden through the environment variables below.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENTS_SOURCE_DIR="${AGENTS_SOURCE_DIR:-$REPO_ROOT/agents}"
CODEX_SOURCE_DIR="${CODEX_SOURCE_DIR:-$REPO_ROOT/codex}"
CLAUDE_AGENTS_DIR="${CLAUDE_AGENTS_DIR:-$HOME/.claude/agents}"
JUNIE_AGENTS_DIR="${JUNIE_AGENTS_DIR:-$HOME/.junie/agents}"
CODEX_AGENTS_DIR="${CODEX_AGENTS_DIR:-$HOME/.codex/agents}"

conflicts=0

# link_dir SOURCE_DIR GLOB TARGET_DIR
link_dir() {
  local source_dir="$1" glob="$2" target_dir="$3" source target link_dest

  if [ ! -d "$source_dir" ]; then
    echo "error    source directory not found: $source_dir" >&2
    exit 1
  fi
  mkdir -p "$target_dir"

  # Remove links to agents deleted from this repo. Links pointing elsewhere
  # are agents managed outside the repo and must be left alone.
  for target in "$target_dir"/*; do
    [ -L "$target" ] || continue
    link_dest="$(readlink "$target")"
    case "$link_dest" in
      "$source_dir"/*)
        if [ ! -e "$link_dest" ]; then
          rm "$target"
          echo "removed  $target"
        fi
        ;;
    esac
  done

  for source in "$source_dir"/$glob; do
    [ -e "$source" ] || continue
    target="$target_dir/$(basename "$source")"
    # A regular file may hold edits not yet moved into the repo: never overwrite it.
    if [ -e "$target" ] && [ ! -L "$target" ]; then
      echo "conflict $target is a regular file; move it into the repo or away, then re-run" >&2
      conflicts=$((conflicts + 1))
      continue
    fi
    ln -sfn "$source" "$target"
    echo "linked   $target -> $source"
  done
}

link_dir "$AGENTS_SOURCE_DIR" "*.md" "$CLAUDE_AGENTS_DIR"
link_dir "$AGENTS_SOURCE_DIR" "*.md" "$JUNIE_AGENTS_DIR"
link_dir "$CODEX_SOURCE_DIR" "*.toml" "$CODEX_AGENTS_DIR"

if [ "$conflicts" -gt 0 ]; then
  echo "error    $conflicts conflict(s), see above" >&2
  exit 1
fi
