"""Configuration management for QuizAgent.

Supports loading and validation from YAML and JSON files, merging with CLI overrides,
and generating well-commented initial configurations for users.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


DEFAULT_CONFIG_YAML = """# ==============================================================================
# QuizAgent Configuration Profile
# Practice test harness & user-reviewed AI assistance configuration
# ==============================================================================

version: "1.0"

# Target assessment / practice URL
target:
  url: "http://127.0.0.1:5055/single"
  adapter: "auto"              # auto | generic | moodle
  custom_profile: null         # Optional path to site selector JSON

# Browser runtime configuration
browser:
  headless: false              # Run visible browser window
  cdp_url: null                # Attach to existing Chrome (e.g. "http://127.0.0.1:9222")
  profile_dir: null            # Path to persistent Chrome user profile directory
  timeout: 30000               # Navigation timeout in milliseconds

# Authentication settings (consequential credentials excluded from version control)
auth:
  mode: "none"                 # none | credentials | saved_session | cdp
  username: null
  password_env: "QA_PASS"      # Read password from this environment variable
  storage_state: null          # Path to Playwright storage_state.json

# Answer strategy
strategy:
  mode: "ai"                   # ai | key | fallback
  key_file: null               # Path to key.json
  fallback: "skip"             # skip | fail | first | last | random
  text_default: "test"

# AI Provider & Model routing (NVIDIA NIM or OpenRouter)
ai:
  enabled: true
  provider: "nvidia"           # nvidia | openrouter | mock
  model: "nemotron_ultra"      # nemotron_ultra | nemotron_lightning | nemotron_super_vl | north_mini_code | gemma_4
  review_mode: true            # Ask user for confirmation before selecting answer
  confidence_threshold: 0.6    # Minimum model confidence
  timeout: 45.0

# Execution pacing & safety guardrails
execution:
  behavior: "student"          # instant | student | careful | erratic
  speed: 1.0                   # Pacing multiplier
  seed: 0
  max_steps: 150
  trace: false                 # Save screenshots of every step
  confirm_submit: true         # Require explicit confirmation before final submission
  output_dir: "runs"
  cache_dir: ".quizagent_cache"
"""

DEFAULT_CONFIG_JSON = {
    "version": "1.0",
    "target": {
        "url": "http://127.0.0.1:5055/single",
        "adapter": "auto",
        "custom_profile": None,
    },
    "browser": {
        "headless": False,
        "cdp_url": None,
        "profile_dir": None,
        "timeout": 30000,
    },
    "auth": {
        "mode": "none",
        "username": None,
        "password_env": "QA_PASS",
        "storage_state": None,
    },
    "strategy": {
        "mode": "ai",
        "key_file": None,
        "fallback": "skip",
        "text_default": "test",
    },
    "ai": {
        "enabled": True,
        "provider": "nvidia",
        "model": "nemotron_ultra",
        "review_mode": True,
        "confidence_threshold": 0.6,
        "timeout": 45.0,
    },
    "execution": {
        "behavior": "student",
        "speed": 1.0,
        "seed": 0,
        "max_steps": 150,
        "trace": False,
        "confirm_submit": True,
        "output_dir": "runs",
        "cache_dir": ".quizagent_cache",
    },
}


def load_config(path: str | Path) -> Dict[str, Any]:
    """Load configuration from a YAML or JSON file."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    ext = p.suffix.lower()
    raw_text = p.read_text(encoding="utf-8")

    if ext in (".yaml", ".yml"):
        if not HAS_YAML:
            raise RuntimeError("PyYAML is required to read YAML configuration files (pip install pyyaml).")
        data = yaml.safe_load(raw_text) or {}
    elif ext == ".json":
        data = json.loads(raw_text)
    else:
        # Try YAML first if available, then JSON
        if HAS_YAML:
            try:
                data = yaml.safe_load(raw_text)
                if isinstance(data, dict):
                    return validate_and_merge(data)
            except Exception:
                pass
        data = json.loads(raw_text)

    if not isinstance(data, dict):
        raise ValueError(f"Configuration root in {path} must be a dictionary/object.")

    return validate_and_merge(data)


def validate_and_merge(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate configuration fields and merge with sane defaults."""
    merged = json.loads(json.dumps(DEFAULT_CONFIG_JSON))

    # Deep merge nested sections
    for section in ("target", "browser", "auth", "strategy", "ai", "execution"):
        if section in data and isinstance(data[section], dict):
            merged[section].update(data[section])

    # Validate specific values
    adapter = merged["target"].get("adapter")
    if adapter not in ("auto", "generic", "moodle"):
        merged["target"]["adapter"] = "auto"

    fallback = merged["strategy"].get("fallback")
    if fallback not in ("skip", "fail", "first", "last", "random"):
        merged["strategy"]["fallback"] = "skip"

    behavior = merged["execution"].get("behavior")
    if behavior not in ("instant", "student", "careful", "erratic") and not (behavior and Path(behavior).is_file()):
        merged["execution"]["behavior"] = "student"

    return merged


def init_config(output_path: str | Path, format: str = "yaml") -> Path:
    """Generate a starter configuration file."""
    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)

    fmt = format.lower()
    if fmt in ("yaml", "yml"):
        p.write_text(DEFAULT_CONFIG_YAML, encoding="utf-8")
    else:
        p.write_text(json.dumps(DEFAULT_CONFIG_JSON, indent=2), encoding="utf-8")

    return p
