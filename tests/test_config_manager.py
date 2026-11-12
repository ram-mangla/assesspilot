"""Unit tests for configuration manager, YAML/JSON parsing, and CLI overrides."""
import json
import os
import tempfile
import unittest

from quizagent.config import (
    DEFAULT_CONFIG_JSON,
    init_config,
    load_config,
    validate_and_merge,
)


class TestConfigManager(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_init_config_yaml(self):
        dest = os.path.join(self.tmp.name, "quizagent.yaml")
        init_config(dest, format="yaml")
        self.assertTrue(os.path.isfile(dest))

        data = load_config(dest)
        self.assertEqual(data["version"], "1.0")
        self.assertIn("target", data)
        self.assertIn("browser", data)
        self.assertIn("strategy", data)
        self.assertIn("ai", data)

    def test_init_config_json(self):
        dest = os.path.join(self.tmp.name, "quizagent.json")
        init_config(dest, format="json")
        self.assertTrue(os.path.isfile(dest))

        data = load_config(dest)
        self.assertEqual(data["version"], "1.0")
        self.assertEqual(data["target"]["adapter"], "auto")

    def test_load_custom_yaml(self):
        dest = os.path.join(self.tmp.name, "custom.yaml")
        with open(dest, "w", encoding="utf-8") as f:
            f.write("""
target:
  url: "https://myquiz.org/test"
  adapter: "moodle"
browser:
  headless: true
ai:
  enabled: true
  model: "nemotron_lightning"
""")
        data = load_config(dest)
        self.assertEqual(data["target"]["url"], "https://myquiz.org/test")
        self.assertEqual(data["target"]["adapter"], "moodle")
        self.assertTrue(data["browser"]["headless"])
        self.assertEqual(data["ai"]["model"], "nemotron_lightning")
        # Defaults preserved
        self.assertEqual(data["execution"]["behavior"], "student")

    def test_load_nonexistent_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            load_config(os.path.join(self.tmp.name, "missing.yaml"))

    def test_invalid_adapter_falls_back_to_auto(self):
        data = validate_and_merge({"target": {"adapter": "unsupported_adapter"}})
        self.assertEqual(data["target"]["adapter"], "auto")


if __name__ == "__main__":
    unittest.main()
