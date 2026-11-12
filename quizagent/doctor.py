"""System environment diagnostics and health verification for QuizAgent.

Inspects Python, Playwright, Chrome installations, profiles, API keys, cache, and permissions.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from . import __version__
from .browser_launcher import (
    check_playwright_installed,
    find_chrome_executable,
    get_default_chrome_user_data_dir,
    is_profile_locked,
    list_chrome_profiles,
    probe_cdp_endpoint,
)
from .llm import missing_keys


def mask_key(val: Optional[str]) -> str:
    """Mask an API key for safe display (e.g. nvapi-...3a1b)."""
    if not val:
        return "[NOT SET]"
    val = val.strip()
    if len(val) <= 8:
        return "****"
    return f"{val[:6]}...{val[-4:]}"


class Doctor:
    """Runs diagnostics across all subsystems and generates a formatted health report."""

    def __init__(self, cache_dir: str = ".quizagent_cache", cdp_url: str = "http://127.0.0.1:9222"):
        self.cache_dir = Path(cache_dir)
        self.cdp_url = cdp_url
        self.checks: List[Dict[str, Any]] = []

    def _record(self, category: str, name: str, status: str, details: str, remediation: Optional[str] = None):
        # status: OK | WARN | FAIL | INFO
        self.checks.append({
            "category": category,
            "name": name,
            "status": status,
            "details": details,
            "remediation": remediation,
        })

    def run_all(self) -> Dict[str, Any]:
        """Run all diagnostic checks."""
        self.checks.clear()
        self._check_python()
        self._check_playwright()
        self._check_chrome()
        self._check_profiles_and_cdp()
        self._check_ai_keys()
        self._check_filesystem()

        counts = {
            "ok": sum(1 for c in self.checks if c["status"] == "OK"),
            "warn": sum(1 for c in self.checks if c["status"] == "WARN"),
            "fail": sum(1 for c in self.checks if c["status"] == "FAIL"),
            "info": sum(1 for c in self.checks if c["status"] == "INFO"),
        }
        return {"checks": self.checks, "summary": counts, "healthy": counts["fail"] == 0}

    def _check_python(self):
        v = sys.version_info
        v_str = f"{v.major}.{v.minor}.{v.micro}"
        if v.major >= 3 and v.minor >= 10:
            self._record("Python Environment", "Python Version", "OK", f"Python {v_str} ({platform.architecture()[0]})")
        else:
            self._record("Python Environment", "Python Version", "FAIL", f"Python {v_str} (Requires 3.10+)",
                         "Please upgrade to Python 3.10 or higher.")

        self._record("Python Environment", "QuizAgent Version", "OK", f"v{__version__} at {Path(__file__).parent}")

    def _check_playwright(self):
        pw_info = check_playwright_installed()
        if pw_info.get("playwright_installed"):
            self._record("Playwright", "Package Installation", "OK", f"Playwright v{pw_info['playwright_version']}")
        else:
            self._record("Playwright", "Package Installation", "FAIL", pw_info.get("error") or "Not installed",
                         "Run 'pip install playwright'.")

        if pw_info.get("chromium_available"):
            self._record("Playwright", "Chromium Binary", "OK", f"Found at {pw_info['chromium_path']}")
        else:
            self._record("Playwright", "Chromium Binary", "WARN", "Chromium binary not found in standard Playwright path",
                         "Run 'python -m playwright install chromium'.")

    def _check_chrome(self):
        exe = find_chrome_executable()
        if exe:
            version_str = ""
            try:
                out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=3)
                version_str = f" ({out.stdout.strip()})" if out.stdout else ""
            except Exception:
                pass
            self._record("Browser & Chrome", "System Chrome Detection", "OK", f"Found at {exe}{version_str}")
        else:
            self._record("Browser & Chrome", "System Chrome Detection", "INFO",
                         "Google Chrome not found in standard paths; Playwright bundled Chromium will be used.",
                         "Install Google Chrome if you wish to attach to real Chrome profiles or sessions.")

    def _check_profiles_and_cdp(self):
        root = get_default_chrome_user_data_dir()
        if root:
            profiles = list_chrome_profiles(root)
            locked = is_profile_locked(root)
            prof_names = [p["name"] for p in profiles] or ["Default"]
            status = "WARN" if locked else "OK"
            details = f"Path: {root} | Profiles: {', '.join(prof_names)} | Locked: {locked}"
            remed = "Chrome is currently running. Close Chrome before using --profile, or use --cdp to attach to it." if locked else None
            self._record("Browser Profiles", "Chrome User Data Directory", status, details, remed)
        else:
            self._record("Browser Profiles", "Chrome User Data Directory", "INFO", "No default Chrome user data directory detected.")

        cdp_status = probe_cdp_endpoint(self.cdp_url)
        if cdp_status.get("available"):
            self._record("Remote Debugging", "CDP Endpoint", "OK",
                         f"Connected to {self.cdp_url} ({cdp_status.get('browser')})")
        else:
            self._record("Remote Debugging", "CDP Endpoint", "INFO",
                         f"No active Chrome DevTools endpoint at {self.cdp_url} (Optional: start via 'quizagent chrome').")

    def _check_ai_keys(self):
        nv_key = os.environ.get("NVIDIA_API_KEY")
        or_key = os.environ.get("OPENROUTER_API_KEY")

        if nv_key:
            self._record("AI Providers", "NVIDIA NIM API Key", "OK", f"Configured ({mask_key(nv_key)})")
        else:
            self._record("AI Providers", "NVIDIA NIM API Key", "INFO", "NVIDIA_API_KEY is not set",
                         "Set NVIDIA_API_KEY in environment or .env for free NVIDIA models (build.nvidia.com).")

        if or_key:
            self._record("AI Providers", "OpenRouter API Key", "OK", f"Configured ({mask_key(or_key)})")
        else:
            self._record("AI Providers", "OpenRouter API Key", "INFO", "OPENROUTER_API_KEY is not set",
                         "Set OPENROUTER_API_KEY in environment or .env for OpenRouter models (openrouter.ai).")

    def _check_filesystem(self):
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            test_file = self.cache_dir / ".doctor_test"
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink()
            self._record("Filesystem", "Cache Directory Access", "OK", f"Writable ({self.cache_dir.resolve()})")
        except Exception as e:
            self._record("Filesystem", "Cache Directory Access", "FAIL", f"Cannot write to {self.cache_dir}: {e}",
                         "Ensure read and write permissions for the cache directory.")

    def render_cli(self) -> int:
        """Print the report to the console using rich or clean ANSI formatting."""
        res = self.run_all()
        checks = res["checks"]
        counts = res["summary"]

        print("\n" + "=" * 70)
        print(f" AssessPilot Doctor v{__version__} - Environment Diagnostic")
        print("=" * 70 + "\n")

        current_cat = None
        for c in checks:
            if c["category"] != current_cat:
                current_cat = c["category"]
                print(f" [{current_cat}]")

            status = c["status"]
            badge = {
                "OK": " [PASS] ",
                "WARN": " [WARN] ",
                "FAIL": " [FAIL] ",
                "INFO": " [INFO] ",
            }.get(status, f" [{status}] ")

            print(f"   {badge} {c['name']}")
            print(f"          {c['details']}")
            if c.get("remediation") and status in ("WARN", "FAIL"):
                print(f"          -> Tip: {c['remediation']}")
            print()

        print("-" * 70)
        print(f" Result: {counts['ok']} Passed, {counts['warn']} Warnings, {counts['fail']} Failures, {counts['info']} Informational")
        print("=" * 70 + "\n")

        return 1 if counts["fail"] > 0 else 0
