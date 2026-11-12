"""Unit tests for QuizAgent CLI commands, options, version, and doctor diagnostics."""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

from quizagent import __version__
from quizagent.cli import build_parser, main
from quizagent.doctor import Doctor


class TestCliCommands(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        import gc
        gc.collect()
        try:
            self.tmp.cleanup()
        except Exception:
            pass

    def test_version_flag(self):
        buf = io.StringIO()
        with redirect_stdout(buf), self.assertRaises(SystemExit) as cm:
            main(["--version"])
        self.assertEqual(cm.exception.code, 0)
        self.assertIn(__version__, buf.getvalue())

    def test_help_flag(self):
        buf = io.StringIO()
        with redirect_stdout(buf), self.assertRaises(SystemExit) as cm:
            main(["--help"])
        self.assertEqual(cm.exception.code, 0)
        out = buf.getvalue()
        self.assertIn("doctor", out)
        self.assertIn("config", out)
        self.assertIn("run", out)
        self.assertIn("serve", out)

    def test_doctor_command(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["doctor", "--cache-dir", os.path.join(self.tmp.name, "cache")])
        out = buf.getvalue()
        self.assertIn("Doctor", out)
        self.assertIn("Python Environment", out)
        self.assertIn("Playwright", out)
        self.assertEqual(code, 0)

    def test_config_init_yaml(self):
        dest = os.path.join(self.tmp.name, "quizagent.yaml")
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["config", "init", "-o", dest, "-f", "yaml"])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.isfile(dest))
        self.assertIn("[OK] Configuration initialized", buf.getvalue())

    def test_config_init_json(self):
        dest = os.path.join(self.tmp.name, "quizagent.json")
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["config", "init", "-o", dest, "-f", "json"])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.isfile(dest))
        self.assertIn("[OK] Configuration initialized", buf.getvalue())

    def test_cache_clear_and_show(self):
        cdir = os.path.join(self.tmp.name, "cache")
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["cache", "clear", "--cache-dir", cdir])
        self.assertEqual(code, 0)
        self.assertIn("profiles", buf.getvalue())

    def test_run_non_interactive_without_url_fails_gracefully(self):
        with mock.patch("sys.stdin.isatty", return_value=False):
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = main(["run"])
            self.assertEqual(code, 1)
            self.assertIn("Target URL or --config must be provided", buf.getvalue())

    def test_parser_options(self):
        parser = build_parser()
        args = parser.parse_args(["run", "http://127.0.0.1:5055/single", "--headless", "--fallback", "first", "--ai-provider", "mock"])
        self.assertEqual(args.url, "http://127.0.0.1:5055/single")
        self.assertFalse(args.headed)
        self.assertEqual(args.fallback, "first")
        self.assertEqual(args.ai_provider, "mock")


if __name__ == "__main__":
    unittest.main()
