"""Tests for scripts/link_agents.sh (symlinks from the tool directories to this repo)."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "link_agents.sh"


class LinkAgentsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.agents_src = root / "repo" / "agents"
        self.codex_src = root / "repo" / "codex"
        self.claude_dir = root / "home" / ".claude" / "agents"
        self.junie_dir = root / "home" / ".junie" / "agents"
        self.codex_dir = root / "home" / ".codex" / "agents"
        self.agents_src.mkdir(parents=True)
        self.codex_src.mkdir(parents=True)
        (self.agents_src / "implementer.md").write_text("---\nname: implementer\n---\n")
        (self.codex_src / "implementer.toml").write_text('name = "implementer"\n')

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self) -> subprocess.CompletedProcess:
        env = {
            **os.environ,
            "AGENTS_SOURCE_DIR": str(self.agents_src),
            "CODEX_SOURCE_DIR": str(self.codex_src),
            "CLAUDE_AGENTS_DIR": str(self.claude_dir),
            "JUNIE_AGENTS_DIR": str(self.junie_dir),
            "CODEX_AGENTS_DIR": str(self.codex_dir),
        }
        return subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)

    def test_link_creates_symlinks_in_all_targets(self) -> None:
        result = self._run()

        self.assertEqual(result.returncode, 0, result.stderr)
        for link, source in (
            (self.claude_dir / "implementer.md", self.agents_src / "implementer.md"),
            (self.junie_dir / "implementer.md", self.agents_src / "implementer.md"),
            (self.codex_dir / "implementer.toml", self.codex_src / "implementer.toml"),
        ):
            self.assertTrue(link.is_symlink(), link)
            self.assertEqual(Path(os.readlink(link)), source)

    def test_link_twice_succeeds(self) -> None:
        self.assertEqual(self._run().returncode, 0)
        result = self._run()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.claude_dir / "implementer.md").is_symlink())

    def test_link_refuses_to_overwrite_regular_file(self) -> None:
        self.claude_dir.mkdir(parents=True)
        local_copy = self.claude_dir / "implementer.md"
        local_copy.write_text("local edits")

        result = self._run()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(local_copy), result.stderr)
        self.assertFalse(local_copy.is_symlink())
        self.assertEqual(local_copy.read_text(), "local edits")

    def test_link_removes_dangling_symlinks_into_source_only(self) -> None:
        self.assertEqual(self._run().returncode, 0)
        (self.agents_src / "implementer.md").unlink()
        unrelated = self.claude_dir / "other.md"
        unrelated.symlink_to(Path(self._tmp.name) / "elsewhere" / "other.md")

        result = self._run()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.claude_dir / "implementer.md").is_symlink())
        self.assertFalse((self.junie_dir / "implementer.md").is_symlink())
        self.assertTrue(unrelated.is_symlink())


if __name__ == "__main__":
    unittest.main()
