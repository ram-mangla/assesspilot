"""Unit tests for cross-platform browser detection, profiles, CDP, and Playwright verification."""
import os
import unittest
from pathlib import Path
from unittest import mock

from quizagent.browser_launcher import (
    check_playwright_installed,
    find_chrome_executable,
    get_default_chrome_user_data_dir,
    get_platform,
    is_profile_locked,
    list_chrome_profiles,
    probe_cdp_endpoint,
)


class TestBrowserLauncher(unittest.TestCase):
    def test_get_platform(self):
        plat = get_platform()
        self.assertIn(plat, ("windows", "macos", "linux"))

    def test_find_chrome_executable_or_none(self):
        exe = find_chrome_executable()
        if exe is not None:
            self.assertTrue(os.path.isfile(exe), f"Path does not exist: {exe}")

    def test_check_playwright_installed(self):
        res = check_playwright_installed()
        self.assertTrue(res["playwright_installed"])
        self.assertTrue(res["chromium_available"])
        self.assertIsNotNone(res["chromium_path"])

    def test_probe_cdp_endpoint_non_existent(self):
        res = probe_cdp_endpoint("http://127.0.0.1:59999", timeout=0.5)
        self.assertFalse(res["available"])
        self.assertIn("error", res)

    def test_list_chrome_profiles_missing_dir(self):
        profiles = list_chrome_profiles(Path("/path/that/does/not/exist"))
        self.assertEqual(profiles, [])

    def test_is_profile_locked_missing_dir(self):
        self.assertFalse(is_profile_locked("/path/that/does/not/exist"))


if __name__ == "__main__":
    unittest.main()
