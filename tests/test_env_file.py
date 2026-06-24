"""Tests for the .env auto-loader (jarvis.config.env_file)."""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from jarvis.config.env_file import _parse, load_env_files


class ParseTest(unittest.TestCase):
    def _write(self, tmp: str, body: str) -> Path:
        path = Path(tmp) / ".env"
        path.write_text(body, encoding="utf-8")
        return path

    def test_parses_pairs_comments_blanks_export_and_quotes(self):
        with TemporaryDirectory() as tmp:
            path = self._write(tmp, "\n".join([
                "# a comment",
                "",
                "OPENROUTER_API_KEY=abc123",
                "export JARVIS_TIME_MCP_URL=http://localhost:8080/mcp",
                'QUOTED="spaced value"',
                "  SPACED  =  trimmed  ",
                "no_equals_line_ignored",
            ]))
            pairs = dict(_parse(path))
        self.assertEqual(pairs["OPENROUTER_API_KEY"], "abc123")
        self.assertEqual(pairs["JARVIS_TIME_MCP_URL"], "http://localhost:8080/mcp")
        self.assertEqual(pairs["QUOTED"], "spaced value")
        self.assertEqual(pairs["SPACED"], "trimmed")
        self.assertNotIn("no_equals_line_ignored", pairs)

    def test_missing_file_is_empty(self):
        self.assertEqual(_parse(Path("/no/such/.env")), [])


class LoadPrecedenceTest(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in
                       ("ENVTEST_A", "ENVTEST_B", "ENVTEST_C")}
        for k in self._saved:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_real_env_wins_local_beats_global(self):
        with TemporaryDirectory() as gdir, TemporaryDirectory() as ldir:
            global_ = Path(gdir) / ".env"
            local = Path(ldir) / ".env"
            global_.write_text("ENVTEST_A=from_global\nENVTEST_B=from_global\n")
            local.write_text("ENVTEST_B=from_local\nENVTEST_C=from_local\n")
            os.environ["ENVTEST_A"] = "from_real_env"  # already set → must win

            applied = load_env_files(local=local, global_=global_)

            self.assertEqual(os.environ["ENVTEST_A"], "from_real_env")  # real env wins
            self.assertEqual(os.environ["ENVTEST_B"], "from_local")     # local > global
            self.assertEqual(os.environ["ENVTEST_C"], "from_local")     # only in local
            self.assertEqual(applied, [str(local), str(global_)])


if __name__ == "__main__":
    unittest.main()
