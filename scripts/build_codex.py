#!/usr/bin/env python3
"""Generate Codex agent definitions (.toml) from the Claude Code agent sources (.md).

The .md files in agents/ are the single source of truth. Codex cannot read them,
so this script renders each one into codex/<stem>.toml, which ~/.codex/agents
links to. The codex/ directory is fully generated: never edit it by hand.

Usage:
    python3 scripts/build_codex.py [--source agents] [--output codex]
"""

from __future__ import annotations

import sys

if sys.version_info < (3, 11):
    # tomllib (used to verify the generated files) ships with Python 3.11+.
    sys.exit(f"build_codex.py requires Python 3.11+, found {sys.version.split()[0]}")

import argparse
import json
import logging
import textwrap
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DIR = REPO_ROOT / "agents"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "codex"

# Claude-specific references rewritten for Codex, applied in order to both the
# description and the instructions. Explicit pairs instead of a blanket
# "Claude" -> "Codex" replace, which previously corrupted paths (~/.Codex/...).
CODEX_SUBSTITUTIONS: tuple[tuple[str, str], ...] = (
    ("CLAUDE.md", "AGENTS.md"),
    ("(Claude Code)", "(Codex)"),
)

FRONTMATTER_DELIMITER = "---"

logger = logging.getLogger("build_codex")


class AgentParseError(ValueError):
    """Raised when an agent .md file does not match the supported frontmatter subset."""


@dataclass(frozen=True)
class AgentDefinition:
    """One agent, independent of the tool that will consume it."""

    stem: str
    name: str
    description: str
    body: str


class AgentFileParser:
    """Parses Claude Code agent files: YAML frontmatter + Markdown body.

    Only the YAML subset used by the agents is supported (plain scalars,
    double-quoted scalars and `|` literal blocks); anything else fails fast
    instead of being silently misread, since adding a YAML library is not
    worth a dependency for seven files.
    """

    REQUIRED_KEYS = ("name", "description")

    def parse(self, text: str, stem: str) -> AgentDefinition:
        """Parse the content of one agent file.

        @param text: full content of the .md file
        @param stem: file name without extension, used in error messages and output names
        @return: the parsed agent definition
        @throws AgentParseError: if the frontmatter is missing, malformed or incomplete
        """
        lines = text.splitlines()
        if not lines or lines[0].strip() != FRONTMATTER_DELIMITER:
            raise AgentParseError(f"{stem}: file must start with '{FRONTMATTER_DELIMITER}'")
        try:
            end = next(
                i for i, line in enumerate(lines[1:], start=1) if line.strip() == FRONTMATTER_DELIMITER
            )
        except StopIteration:
            raise AgentParseError(f"{stem}: frontmatter is not closed") from None

        fields = self._parse_fields(lines[1:end], stem)
        missing = [key for key in self.REQUIRED_KEYS if not fields.get(key)]
        if missing:
            raise AgentParseError(f"{stem}: missing required field(s): {', '.join(missing)}")

        return AgentDefinition(
            stem=stem,
            name=fields["name"],
            description=fields["description"],
            body="\n".join(lines[end + 1 :]).strip(),
        )

    def _parse_fields(self, lines: list[str], stem: str) -> dict[str, str]:
        fields: dict[str, str] = {}
        i = 0
        while i < len(lines):
            line = lines[i]
            if not line.strip():
                i += 1
                continue
            key, sep, raw = line.partition(":")
            if not sep or line[0].isspace():
                raise AgentParseError(f"{stem}: unexpected frontmatter line: {line!r}")
            key, raw = key.strip(), raw.strip()
            i += 1
            if raw == "|":
                block_end = i
                while block_end < len(lines) and (not lines[block_end].strip() or lines[block_end][0].isspace()):
                    block_end += 1
                fields[key] = textwrap.dedent("\n".join(lines[i:block_end])).strip()
                i = block_end
            else:
                fields[key] = self._parse_scalar(raw, key, stem)
        return fields

    @staticmethod
    def _parse_scalar(raw: str, key: str, stem: str) -> str:
        if raw.startswith('"'):
            # JSON string escapes are a subset of YAML double-quoted escapes;
            # anything outside that subset raises instead of being misdecoded.
            try:
                return json.loads(raw)
            except json.JSONDecodeError as error:
                raise AgentParseError(f"{stem}: cannot decode quoted '{key}': {error}") from error
        if raw[:1] in ("'", ">", "[", "{", "&", "*", "!"):
            raise AgentParseError(f"{stem}: unsupported YAML style for '{key}': {raw[:20]!r}")
        return raw


class CodexRenderer:
    """Renders an AgentDefinition as a Codex agent .toml file."""

    def __init__(self, substitutions: tuple[tuple[str, str], ...] = CODEX_SUBSTITUTIONS) -> None:
        self._substitutions = substitutions

    def render(self, agent: AgentDefinition) -> str:
        """Render one agent for Codex.

        @param agent: the parsed agent
        @return: TOML document with name, description and developer_instructions
        @throws AgentParseError: if the rendered TOML does not decode back to the same values
        """
        values = {
            "name": agent.name,
            "description": self._adapt(agent.description),
            "developer_instructions": self._adapt(agent.body),
        }
        document = (
            f"# GENERATED by scripts/build_codex.py from agents/{agent.stem}.md — do not edit.\n"
            f"name = {json.dumps(values['name'], ensure_ascii=False)}\n"
            f"description = {self._multiline(values['description'])}\n"
            f"developer_instructions = {self._multiline(values['developer_instructions'])}\n"
        )
        # Hand-rolled escaping is checked against the real parser so a bad
        # escape breaks the build instead of shipping a broken agent to Codex.
        if tomllib.loads(document) != values:
            raise AgentParseError(f"{agent.stem}: rendered TOML does not round-trip")
        return document

    def _adapt(self, text: str) -> str:
        for old, new in self._substitutions:
            text = text.replace(old, new)
        return text

    @staticmethod
    def _multiline(text: str) -> str:
        escaped = text.replace("\\", "\\\\").replace('"""', '""\\"')
        if escaped.endswith('"'):
            # A quote right before the closing delimiter would merge with it.
            escaped = escaped[:-1] + '\\"'
        return f'"""\n{escaped}"""'


class CodexBuilder:
    """Regenerates the whole codex/ directory from the agents/ directory."""

    SOURCE_GLOB = "*.md"
    OUTPUT_SUFFIX = ".toml"

    def __init__(self, parser: AgentFileParser, renderer: CodexRenderer) -> None:
        self._parser = parser
        self._renderer = renderer

    def build(self, source_dir: Path, output_dir: Path) -> list[Path]:
        """Render every agent and delete outputs whose source no longer exists.

        @param source_dir: directory with the agent .md files
        @param output_dir: directory that receives the generated .toml files
        @return: paths of the files written
        @throws FileNotFoundError: if source_dir does not exist
        @throws AgentParseError: if any agent cannot be parsed or rendered
        """
        if not source_dir.is_dir():
            raise FileNotFoundError(f"Agent source directory not found: {source_dir}")

        # Render everything before writing anything, so one bad agent leaves
        # the previous generated set untouched.
        rendered = {
            output_dir / f"{path.stem}{self.OUTPUT_SUFFIX}": self._renderer.render(
                self._parser.parse(path.read_text(encoding="utf-8"), path.stem)
            )
            for path in sorted(source_dir.glob(self.SOURCE_GLOB))
        }

        output_dir.mkdir(parents=True, exist_ok=True)
        for stale in output_dir.glob(f"*{self.OUTPUT_SUFFIX}"):
            if stale not in rendered:
                stale.unlink()
                logger.info("removed stale %s", stale.name)
        for path, document in rendered.items():
            path.write_text(document, encoding="utf-8")
            logger.info("wrote %s", path.name)
        return list(rendered)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    @param argv: command-line arguments (defaults to sys.argv)
    @return: process exit code
    """
    arg_parser = argparse.ArgumentParser(description="Generate Codex agent .toml files from agents/*.md.")
    arg_parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE_DIR)
    arg_parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = arg_parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        written = CodexBuilder(AgentFileParser(), CodexRenderer()).build(args.source, args.output)
    except (AgentParseError, FileNotFoundError) as error:
        logger.error("%s", error)
        return 1
    logger.info("generated %d Codex agent(s) in %s", len(written), args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
