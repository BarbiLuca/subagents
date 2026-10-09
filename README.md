# Subagents

Single source for my custom agents, shared by Claude Code, Junie and Codex
through symlinks.

| Path | Content | Read by |
|---|---|---|
| `agents/*.md` | Agent sources (Claude Code format: YAML frontmatter + Markdown) | `~/.claude/agents`, `~/.junie/agents` |
| `codex/*.toml` | **Generated** from `agents/` — never edit by hand | `~/.codex/agents` |

## Workflow

Edit or add an agent in `agents/`, then:

```sh
python3.14 scripts/build_codex.py   # regenerate codex/*.toml (needs Python 3.11+)
scripts/link_agents.sh              # create/refresh symlinks in the three tool dirs
```

`link_agents.sh` is idempotent: it adds links for new agents, removes links to
deleted ones, and refuses to overwrite a regular file in a tool directory.
Target directories can be overridden with `CLAUDE_AGENTS_DIR`,
`JUNIE_AGENTS_DIR` and `CODEX_AGENTS_DIR`.

## Codex conversion

`build_codex.py` keeps only `name`, `description` and the body
(`developer_instructions`); Claude-only fields (`tools`, `model`, `color`,
`memory`) are dropped. Claude-specific references are rewritten through the
explicit list `CODEX_SUBSTITUTIONS` (e.g. `CLAUDE.md` → `AGENTS.md`).
Frontmatter parsing supports only plain, double-quoted and `|` block scalars and
fails on anything else.

## Tests

```sh
python3.14 -m unittest discover -s tests
```
