"""Tests for scripts/build_codex.py (Claude agent .md -> Codex agent .toml)."""

import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_codex import (  # noqa: E402
    AgentFileParser,
    AgentParseError,
    CodexBuilder,
    CodexRenderer,
)

BLOCK_AGENT = """---
name: implementer
description: |
  Implements features.
  Examples:
    - "Build the queue worker"
tools: Read, Edit
model: sonnet
---

# Implementer

1. **Read CLAUDE.md** for conventions.
"""

QUOTED_AGENT = """---
name: code-architect
description: "Designs systems.\\\\n\\\\nExamples: \\"Design an API\\""
tools: Glob, Grep
memory: user
---
Body.
"""

PLAIN_AGENT = """---
name: error-audit
description: Audits a diff for silent failures.
model: inherit
---
Body.
"""


class AgentFileParserTest(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = AgentFileParser()

    def test_parse_block_description_returns_dedented_text(self) -> None:
        agent = self.parser.parse(BLOCK_AGENT, "implementer")
        self.assertEqual(agent.name, "implementer")
        self.assertEqual(
            agent.description,
            'Implements features.\nExamples:\n  - "Build the queue worker"',
        )

    def test_parse_double_quoted_description_decodes_yaml_escapes(self) -> None:
        agent = self.parser.parse(QUOTED_AGENT, "code-architect")
        # "\\n" in YAML decodes to a literal backslash + n, not a newline.
        self.assertEqual(agent.description, 'Designs systems.\\n\\nExamples: "Design an API"')

    def test_parse_plain_description_returns_value(self) -> None:
        agent = self.parser.parse(PLAIN_AGENT, "error-audit")
        self.assertEqual(agent.description, "Audits a diff for silent failures.")

    def test_parse_body_strips_surrounding_blank_lines(self) -> None:
        agent = self.parser.parse(BLOCK_AGENT, "implementer")
        self.assertEqual(agent.body, "# Implementer\n\n1. **Read CLAUDE.md** for conventions.")

    def test_parse_missing_frontmatter_raises_error(self) -> None:
        with self.assertRaises(AgentParseError):
            self.parser.parse("# No frontmatter\n", "broken")

    def test_parse_unclosed_frontmatter_raises_error(self) -> None:
        with self.assertRaises(AgentParseError):
            self.parser.parse("---\nname: x\ndescription: y\n", "broken")

    def test_parse_missing_description_raises_error(self) -> None:
        with self.assertRaises(AgentParseError):
            self.parser.parse("---\nname: x\n---\nBody\n", "broken")

    def test_parse_unsupported_scalar_style_raises_error(self) -> None:
        with self.assertRaises(AgentParseError):
            self.parser.parse("---\nname: x\ndescription: >\n  folded\n---\nBody\n", "broken")


class CodexRendererTest(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = AgentFileParser()
        self.renderer = CodexRenderer()

    def _render(self, text: str, stem: str) -> dict:
        return tomllib.loads(self.renderer.render(self.parser.parse(text, stem)))

    def test_render_replaces_claude_md_with_agents_md(self) -> None:
        data = self._render(BLOCK_AGENT, "implementer")
        self.assertIn("**Read AGENTS.md**", data["developer_instructions"])
        self.assertNotIn("CLAUDE.md", data["developer_instructions"])

    def test_render_replaces_claude_code_label_with_codex(self) -> None:
        text = PLAIN_AGENT.replace("Body.", "- **Auditor**: security-auditor agent (Claude Code)")
        data = self._render(text, "error-audit")
        self.assertEqual(data["developer_instructions"], "- **Auditor**: security-auditor agent (Codex)")

    def test_render_keeps_only_codex_fields(self) -> None:
        data = self._render(QUOTED_AGENT, "code-architect")
        self.assertEqual(set(data), {"name", "description", "developer_instructions"})

    def test_render_round_trips_backslashes_and_quotes(self) -> None:
        tricky = 'Path C:\\tmp, regex \\d+, triple """ quotes, ends with "quote"'
        text = PLAIN_AGENT.replace("Body.", tricky)
        data = self._render(text, "error-audit")
        self.assertEqual(data["developer_instructions"], tricky)

    def test_render_marks_file_as_generated(self) -> None:
        output = self.renderer.render(self.parser.parse(PLAIN_AGENT, "error-audit"))
        self.assertTrue(output.startswith("# GENERATED"))
        self.assertIn("agents/error-audit.md", output.splitlines()[0])


class CodexBuilderTest(unittest.TestCase):
    def test_build_writes_one_toml_per_agent_and_removes_stale_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "agents"
            output = Path(tmp) / "codex"
            source.mkdir()
            output.mkdir()
            (source / "implementer.md").write_text(BLOCK_AGENT)
            (source / "error-audit.md").write_text(PLAIN_AGENT)
            (output / "removed-agent.toml").write_text('name = "old"\n')

            written = CodexBuilder(AgentFileParser(), CodexRenderer()).build(source, output)

            self.assertEqual(sorted(p.name for p in written), ["error-audit.toml", "implementer.toml"])
            self.assertEqual(
                sorted(p.name for p in output.iterdir()),
                ["error-audit.toml", "implementer.toml"],
            )

    def test_build_missing_source_dir_raises_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                CodexBuilder(AgentFileParser(), CodexRenderer()).build(
                    Path(tmp) / "missing", Path(tmp) / "codex"
                )


if __name__ == "__main__":
    unittest.main()
