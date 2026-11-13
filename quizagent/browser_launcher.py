"""Cross-platform browser detection, profile discovery, CDP connection, and lifecycle utilities.

Supports Windows, macOS, and Linux without hardcoded OS-specific paths.
Handles running Chrome profile locks, CDP discovery, and Playwright browser verification.
"""
from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("quizagent.browser_launcher")


def get_platform() -> str:
    """Return normalized OS name: 'windows', 'macos', or 'linux'."""
    sys_name = platform.system().lower()
    if "windows" in sys_name or sys_name == "win32":
        return "windows"
    if "darwin" in sys_name or "mac" in sys_name:
        return "macos"
    return "linux"


def find_chrome_executable() -> Optional[str]:
    """Locate an installed Google Chrome or Chromium executable on the current system."""
    os_name = get_platform()
    candidates: List[str] = []

    if os_name == "windows":
        local_app = os.environ.get("LOCALAPPDATA", "")
        prog_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        prog_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")

        candidates = [
            os.path.join(prog_files, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(prog_files_x86, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(local_app, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(prog_files, "Chromium", "Application", "chrome.exe"),
            os.path.join(local_app, "Chromium", "Application", "chrome.exe"),
        ]
    elif os_name == "macos":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        ]
    else:  # Linux / BSD
        candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/snap/bin/chromium",
            "/usr/bin/google-chrome-beta",
            "/usr/bin/google-chrome-unstable",
        ]

    # First check explicit absolute paths
    for p in candidates:
        if p and os.path.isfile(p) and os.access(p, os.X_OK if os_name != "windows" else os.R_OK):
            return str(Path(p).resolve())

    # Fall back to PATH search
    cli_names = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"]
    for name in cli_names:
        found = shutil.which(name)
        if found:
            return str(Path(found).resolve())

    return None


def get_default_chrome_user_data_dir() -> Optional[Path]:
    """Return standard user data directory for Google Chrome on this OS."""
    os_name = get_platform()
    if os_name == "windows":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            path = Path(local) / "Google" / "Chrome" / "User Data"
            if path.exists():
                return path
    elif os_name == "macos":
        path = Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
        if path.exists():
            return path
    else:  # Linux
        path = Path.home() / ".config" / "google-chrome"
        if path.exists():
            return path
        alt = Path.home() / ".config" / "chromium"
        if alt.exists():
            return alt
    return None


def list_chrome_profiles(user_data_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """List detected profiles in Chrome user data directory (Default, Profile 1, Profile 2, etc.)."""
    root = user_data_dir or get_default_chrome_user_data_dir()
    if not root or not root.is_dir():
        return []

    profiles: List[Dict[str, Any]] = []

    # Check Default profile
    default_dir = root / "Default"
    if default_dir.is_dir():
        name = "Default"
        pref_file = default_dir / "Preferences"
        if pref_file.is_file():
            try:
                prefs = json.loads(pref_file.read_text(encoding="utf-8", errors="ignore"))
                name = prefs.get("profile", {}).get("name") or "Default"
            except Exception:
                pass
        profiles.append({
            "id": "Default",
            "name": name,
            "path": str(default_dir),
            "is_default": True,
        })

    # Check numbered profiles Profile 1, Profile 2, ...
    for item in sorted(root.iterdir()):
        if item.is_dir() and item.name.startswith("Profile "):
            name = item.name
            pref_file = item / "Preferences"
            if pref_file.is_file():
                try:
                    prefs = json.loads(pref_file.read_text(encoding="utf-8", errors="ignore"))
                    name = prefs.get("profile", {}).get("name") or item.name
                except Exception:
                    pass
            profiles.append({
                "id": item.name,
                "name": name,
                "path": str(item),
                "is_default": False,
            })

    return profiles


def resolve_chrome_profile(profile_arg: Optional[str]) -> Optional[str]:
    """Resolve a profile argument to a concrete profile directory path.

    Supports:
    1. Direct file paths (e.g. 'C:\\my-profile' or '~/.assesspilot/profile')
    2. Named profiles in system Chrome (e.g. 'Mangla', 'Profile 1', 'Default')
    """
    if not profile_arg:
        return None

    # Check if it's already an existing directory or explicit path
    p = Path(profile_arg).expanduser()
    if p.is_dir() or str(profile_arg).startswith((".", "/", "~", "\\")) or ":" in str(profile_arg):
        return str(p.resolve())

    # Try matching against system Chrome profiles by name or ID
    profiles = list_chrome_profiles()
    arg_lower = profile_arg.strip().lower()
    for prof in profiles:
        if prof["name"].lower() == arg_lower or prof["id"].lower() == arg_lower:
            return prof["path"]

    # Fallback to resolving as directory
    return str(p.resolve())


def is_profile_locked(profile_path: str | Path) -> bool:
    """Check if a Chrome profile or user data directory is currently locked by a running Chrome process."""
    p = Path(profile_path)
    if not p.exists():
        return False

    os_name = get_platform()

    # POSIX: SingletonLock symlink or file
    if os_name in ("linux", "macos"):
        lock_file = p / "SingletonLock"
        if lock_file.exists() or lock_file.is_symlink():
            return True

    # Windows: check file lock on lockfile
    lock_candidates = [p / "lockfile", p / "Default" / "lockfile", p / "Web Data"]
    for cand in lock_candidates:
        if cand.is_file():
            try:
                # Try opening for appending/exclusive read
                with open(cand, "r+b"):
                    pass
            except (IOError, PermissionError):
                return True
            except Exception:
                pass

    return False


def probe_cdp_endpoint(cdp_url: str, timeout: float = 2.0) -> Dict[str, Any]:
    """Probe a Chrome DevTools Protocol endpoint (e.g. http://127.0.0.1:9222).

    Returns a status dictionary with availability, browser version, and webSocketDebuggerUrl.
    """
    clean_url = cdp_url.rstrip("/")
    version_url = f"{clean_url}/json/version"
    try:
        req = urllib.request.Request(version_url, headers={"User-Agent": "quizagent"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {
                "available": True,
                "cdp_url": clean_url,
                "browser": data.get("Browser"),
                "protocol_version": data.get("Protocol-Version"),
                "websocket_debugger_url": data.get("webSocketDebuggerUrl"),
            }
    except Exception as e:
        return {
            "available": False,
            "cdp_url": clean_url,
            "error": str(e),
        }


def check_playwright_installed() -> Dict[str, Any]:
    """Verify Playwright package and Playwright browser binaries are present."""
    result: Dict[str, Any] = {
        "playwright_installed": False,
        "playwright_version": None,
        "chromium_available": False,
        "chromium_path": None,
        "error": None,
    }
    try:
        import playwright
        from playwright.sync_api import sync_playwright
        result["playwright_installed"] = True
        result["playwright_version"] = getattr(playwright, "__version__", "unknown")

        with sync_playwright() as p:
            try:
                exe = p.chromium.executable_path
                result["chromium_path"] = exe
                result["chromium_available"] = bool(exe and os.path.exists(exe))
            except Exception as e:
                result["error"] = f"Chromium binary check failed: {e}"
    except ImportError:
        result["error"] = "Playwright python package is not installed."
    except Exception as e:
        result["error"] = f"Playwright check error: {e}"

    return result
