"""Interactive setup wizard for guided CLI execution of QuizAgent.

Prompts users for target URL, browser mode, authentication, profile selection,
AI provider, model routing, and review preferences with sensible defaults.
"""
from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .browser_launcher import (
    find_chrome_executable,
    get_default_chrome_user_data_dir,
    list_chrome_profiles,
    probe_cdp_endpoint,
)
from .llm import MODELS


def _prompt_choice(prompt: str, choices: List[str], default_idx: int = 0) -> str:
    """Prompt user to choose from a list of options."""
    print(f"\n{prompt}")
    for idx, c in enumerate(choices, 1):
        marker = " (Default)" if idx - 1 == default_idx else ""
        print(f"  [{idx}] {c}{marker}")

    while True:
        try:
            val = input(f"Select option [1-{len(choices)}] (default {default_idx + 1}): ").strip()
            if not val:
                return choices[default_idx]
            if val.isdigit() and 1 <= int(val) <= len(choices):
                return choices[int(val) - 1]
            print(f"Invalid input. Please enter a number between 1 and {len(choices)}.")
        except (KeyboardInterrupt, EOFError):
            print("\nSetup cancelled.")
            sys.exit(0)


def _prompt_string(prompt: str, default: Optional[str] = None, required: bool = True) -> str:
    """Prompt user for a text input."""
    def_hint = f" [{default}]" if default is not None else ""
    while True:
        try:
            val = input(f"{prompt}{def_hint}: ").strip()
            if not val and default is not None:
                return default
            if val or not required:
                return val
            print("This field is required. Please enter a value.")
        except (KeyboardInterrupt, EOFError):
            print("\nSetup cancelled.")
            sys.exit(0)


def run_interactive_wizard() -> Dict[str, Any]:
    """Run the interactive guided setup experience and return parsed configuration options."""
    print("\n" + "=" * 70)
    print(" QuizAgent Interactive Assessment Setup")
    print("=" * 70)
    print("Welcome! Let's configure your assessment practice run step-by-step.")

    # 1. Assessment URL
    url = _prompt_string(
        "\nStep 1: Enter Assessment or Practice URL",
        default="http://127.0.0.1:5055/single",
    )

    # 2. Browser Mode
    browser_choices = [
        "Headed (Visible Chromium browser window)",
        "Headless (Silent background browser)",
        "Attach to Running Chrome via CDP (Remote Debugging Port)",
        "Persistent Chrome Profile (Keep your logins and cookies)",
    ]
    b_choice = _prompt_choice("Step 2: Select Browser Mode", browser_choices, default_idx=0)

    cdp_url = None
    profile_dir = None
    headless = "Headless" in b_choice

    if "CDP" in b_choice:
        cdp_default = "http://127.0.0.1:9222"
        cdp_status = probe_cdp_endpoint(cdp_default)
        hint = " (Active Chrome Detected!)" if cdp_status.get("available") else ""
        cdp_url = _prompt_string(f"Enter Chrome DevTools Protocol (CDP) URL{hint}", default=cdp_default)
    elif "Profile" in b_choice:
        detected = get_default_chrome_user_data_dir()
        profiles = list_chrome_profiles(detected) if detected else []
        if profiles:
            p_choices = [f"{p['name']} ({p['path']})" for p in profiles] + ["Custom profile directory..."]
            p_sel = _prompt_choice("Select an existing Chrome profile", p_choices, default_idx=0)
            if "Custom" in p_sel:
                profile_dir = _prompt_string("Enter directory path for browser profile", default=".quizagent_profile")
            else:
                idx = p_choices.index(p_sel)
                profile_dir = profiles[idx]["path"]
        else:
            profile_dir = _prompt_string("Enter directory path for browser profile", default=".quizagent_profile")

    # 3. Authentication Mode
    auth_choices = [
        "None (Public or already authenticated in profile/CDP)",
        "Username & Password (Forms-based login)",
        "Saved Session File (Playwright storage_state.json)",
    ]
    a_choice = _prompt_choice("Step 3: Select Authentication Mode", auth_choices, default_idx=0)

    user = None
    password = None
    storage_state = None

    if "Username" in a_choice:
        user = _prompt_string("Enter username")
        if sys.stdin.isatty():
            password = getpass.getpass(f"Enter password for {user} (input hidden): ")
        else:
            password = _prompt_string("Enter password")
    elif "Session File" in a_choice:
        storage_state = _prompt_string("Path to storage state JSON file", default=".quizagent_cache/state/session.json")

    # 4. Answering Strategy & AI Provider
    strategy_choices = [
        "AI-Assisted Practice (NVIDIA NIM / OpenRouter)",
        "Answer Key File (key.json)",
        "Deterministic Fallback Only (Random / First / Last)",
    ]
    s_choice = _prompt_choice("Step 4: Select Answering Strategy", strategy_choices, default_idx=0)

    ai_provider = None
    ai_model = None
    ai_review = True
    key_file = None
    fallback_mode = "skip"

    if "AI-Assisted" in s_choice:
        prov_choices = [
            "NVIDIA NIM (Free developer API with Nemotron models)",
            "OpenRouter (Free open-source & reasoning models)",
            "Mock AI Provider (Simulated responses for offline testing)",
        ]
        p_sel = _prompt_choice("Select AI Provider", prov_choices, default_idx=0)

        if "NVIDIA" in p_sel:
            ai_provider = "nvidia"
            models_list = ["nemotron_ultra", "nemotron_lightning", "nemotron_super_vl"]
            ai_model = _prompt_choice("Select NVIDIA Model", models_list, default_idx=0)
        elif "OpenRouter" in p_sel:
            ai_provider = "openrouter"
            models_list = ["nemotron_ultra_or", "nemotron_lightning_or", "north_mini_code", "gemma_4", "nemotron_nano_omni"]
            ai_model = _prompt_choice("Select OpenRouter Model", models_list, default_idx=0)
        else:
            ai_provider = "mock"
            ai_model = "mock_model"

        review_ans = _prompt_choice(
            "Enable Human Review Mode? (Review suggestions before applying)",
            ["Yes (Recommended for learning & safety)", "No (Automated assistance)"],
            default_idx=0,
        )
        ai_review = "Yes" in review_ans
    elif "Answer Key" in s_choice:
        key_file = _prompt_string("Path to Answer Key JSON file", default="key.json")

    fallback_choices = ["skip", "fail", "first", "last", "random"]
    fallback_mode = _prompt_choice("Fallback for uncovered questions", fallback_choices, default_idx=0)

    # 5. Execution Behavior & Pacing
    beh_choices = [
        "student (Natural reading pauses, thinking time, answer jitter)",
        "instant (Fastest execution, no artificial pauses)",
        "careful (Extended think times, careful review pause)",
        "erratic (Simulated hesitant behavior, back-and-forth review)",
    ]
    beh_sel = _prompt_choice("Step 5: Select Behavioral Pacing", beh_choices, default_idx=0)
    behavior = beh_sel.split()[0]

    # 6. Report and Safety
    out_dir = _prompt_string("Step 6: Output / Reports Directory", default="runs")
    confirm_sub = _prompt_choice(
        "Require explicit confirmation before final assessment submission?",
        ["Yes (Safe practice guardrail)", "No (Auto-submit on completion)"],
        default_idx=0,
    )
    confirm_submit = "Yes" in confirm_sub

    config_dict = {
        "url": url,
        "headed": not headless,
        "cdp": cdp_url,
        "profile": profile_dir,
        "user": user,
        "password": password,
        "storage_state": storage_state,
        "key": key_file,
        "fallback": fallback_mode,
        "ai_provider": ai_provider,
        "ai_model": ai_model,
        "ai_review": ai_review,
        "behavior": behavior,
        "out": out_dir,
        "confirm_submit": confirm_submit,
        "speed": 1.0,
        "seed": 0,
        "max_steps": 150,
        "trace": False,
        "adapter": "auto",
        "cache_dir": ".quizagent_cache",
        "no_cache": False,
        "no_state": False,
        "fresh": False,
        "text_default": "test",
        "pass_file": None,
        "pass_env": "QA_PASS",
        "config": None,
    }

    print("\n" + "=" * 70)
    print(" Configuration Summary")
    print(f"  Target URL:       {url}")
    print(f"  Browser Mode:     {'Headed' if not headless else 'Headless'}" + (f" (CDP: {cdp_url})" if cdp_url else ""))
    print(f"  Auth:             {a_choice.split('(')[0].strip()}")
    print(f"  Strategy:         {s_choice.split('(')[0].strip()}" + (f" ({ai_provider}:{ai_model})" if ai_provider else ""))
    print(f"  Behavior Profile: {behavior}")
    print(f"  Report Output:    {out_dir}")
    print("=" * 70 + "\n")

    return config_dict
