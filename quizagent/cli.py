"""QuizAgent CLI: Reliable browser test harness and user-assisted practice CLI.

Supports interactive wizards, direct CLI execution, configuration profiles (YAML/JSON),
diagnostics ('doctor'), automated discovery, and local control dashboard.
"""
from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
import random
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import __version__, behavior as B
from .agent import Agent
from .cache import Cache
from .config import init_config, load_config
from .doctor import Doctor
from .strategies import Chain, KeyStrategy
from .wizard import run_interactive_wizard

logger = logging.getLogger("quizagent.cli")


def _resolve_password(user: str, password_arg: Optional[str], pass_file: Optional[str], pass_env: str) -> str:
    """Safely resolve password without leaking into logs or traces."""
    if password_arg:
        # User explicitly passed on CLI
        return password_arg

    if pass_file and os.path.isfile(pass_file):
        try:
            return Path(pass_file).read_text(encoding="utf-8").strip()
        except Exception as e:
            logger.warning("Could not read password file %s: %s", pass_file, e)

    env_val = os.environ.get(pass_env)
    if env_val:
        return env_val

    if sys.stdin.isatty():
        try:
            return getpass.getpass(f"Enter password for {user} (input masked): ")
        except (KeyboardInterrupt, EOFError):
            print("\nOperation cancelled.")
            sys.exit(1)

    return ""


def build_agent_from_params(params: Dict[str, Any]) -> Agent:
    """Construct an Agent instance from normalized parameters."""
    rng = random.Random(params.get("seed", 0))
    cache_dir = None if params.get("no_cache") else params.get("cache_dir", ".quizagent_cache")
    cache = Cache(cache_dir)

    key_path = params.get("key")
    key = KeyStrategy(key_path) if key_path and os.path.exists(key_path) else None

    # AI Strategy initialization
    ai_strategy = None
    ai_provider = params.get("ai_provider")
    mock_ai = params.get("mock_ai", False) or (ai_provider == "mock")

    if ai_provider or mock_ai:
        try:
            from .ai_strategy import AIStrategy
            ai_strategy = AIStrategy(
                provider=ai_provider or "nvidia",
                model=params.get("ai_model"),
                review_mode=bool(params.get("ai_review", True)),
                confidence_threshold=float(params.get("ai_confidence", 0.6)),
                mock=mock_ai,
            )
        except Exception as e:
            logger.warning("Could not initialize AI strategy: %s", e)

    fallback_mode = params.get("fallback", "skip")
    text_default = params.get("text_default", "test")
    use_cache = not params.get("fresh", False)
    chain = Chain(key, fallback_mode, rng, cache, use_cache=use_cache, text_default=text_default, ai_strategy=ai_strategy)

    cfg = None
    config_path = params.get("config")
    if config_path and os.path.exists(config_path):
        try:
            cfg = json.load(open(config_path, encoding="utf-8"))
        except Exception:
            pass

    creds = None
    user = params.get("user")
    if user:
        pw = _resolve_password(
            user,
            params.get("password"),
            params.get("pass_file"),
            params.get("pass_env", "QA_PASS"),
        )
        creds = (user, pw)

    behavior_name = params.get("behavior", "instant")
    speed = float(params.get("speed", 1.0))
    beh = B.load(behavior_name, speed)

    from .learner import SelfLearningEngine
    learner = SelfLearningEngine(cache_dir)

    return Agent(
        strategy=chain,
        behavior=beh,
        cache=cache,
        seed=params.get("seed", 0),
        out_dir=params.get("out", "runs"),
        max_steps=params.get("max_steps", 150),
        headed=bool(params.get("headed", False)),
        creds=creds,
        adapter=params.get("adapter", "auto"),
        config=cfg,
        trace=bool(params.get("trace", False)),
        use_state=not bool(params.get("no_state", False)),
        chrome_path=params.get("chrome_path"),
        cdp=params.get("cdp"),
        profile=params.get("profile"),
        storage_state=params.get("storage_state"),
        confirm_submit=bool(params.get("confirm_submit", False)),
        learner=learner,
    )


def build_parser() -> argparse.ArgumentParser:
    """Create the primary argument parser with all subcommands."""
    prog_name = "quizpilot"
    if sys.argv and sys.argv[0]:
        stem = Path(sys.argv[0]).stem
        if "quizagent" in stem:
            prog_name = "quizagent"

    ap = argparse.ArgumentParser(
        prog=prog_name,
        description="QuizPilot: Self-learning browser automation harness and AI copilot CLI for web assessments.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")

    sub = ap.add_subparsers(dest="cmd", help="Available subcommands")

    # ---- doctor
    doc = sub.add_parser("doctor", help="Run system diagnostics (Playwright, Chrome, API keys, cache)")
    doc.add_argument("--cache-dir", default=".quizagent_cache", help="Cache directory to check")
    doc.add_argument("--cdp", default="http://127.0.0.1:9222", help="CDP endpoint to probe")

    # ---- config
    cfg_p = sub.add_parser("config", help="Manage configuration profiles")
    cfg_sub = cfg_p.add_subparsers(dest="config_cmd", required=True)
    cfg_init = cfg_sub.add_parser("init", help="Generate a starter configuration file")
    cfg_init.add_argument("-o", "--output", default="quizpilot.yaml", help="Destination path (e.g. quizpilot.yaml or quizpilot.json)")
    cfg_init.add_argument("-f", "--format", choices=["yaml", "json"], default="yaml", help="Format to generate")

    # ---- run, probe, auto
    for name in ("run", "probe", "auto"):
        s = sub.add_parser(name, help=f"{name.capitalize()} workflow")
        # In 'run', URL is optional to allow interactive wizard or config file usage
        if name == "run":
            s.add_argument("url", nargs="?", default=None, help="Target assessment or practice URL")
            s.add_argument("--url", dest="url_opt", help="Target assessment URL (flag alternative)")
        else:
            s.add_argument("url", help="Target URL")

        s.add_argument("-c", "--config", help="Path to YAML or JSON configuration profile or custom site profile")
        s.add_argument("-k", "--key", help="Answer key JSON file")
        s.add_argument("--fallback", default="skip", choices=["skip", "fail", "first", "last", "random"],
                       help="Strategy for questions not covered by answer key")
        s.add_argument("--text-default", default="test", help="Default fill-in text for short/long answers")
        s.add_argument("-b", "--behavior", default="instant", help="Pacing profile: instant | student | careful | erratic | path.json")
        s.add_argument("--speed", type=float, default=1.0, help="Pacing time multiplier (e.g. 2.0 = twice as fast)")
        s.add_argument("--seed", type=int, default=0, help="Random seed for reproducibility")
        s.add_argument("--adapter", default="auto", choices=["auto", "generic", "moodle"], help="DOM detection adapter")

        # AI assistance
        s.add_argument("--ai-provider", choices=["nvidia", "openrouter", "mock"], help="AI provider for practice assistance")
        s.add_argument("--ai-model", help="AI model identifier or slug (e.g. nemotron_ultra, nemotron_lightning)")
        s.add_argument("--ai-review", action="store_true", default=None, help="Enable interactive user review of AI answers")
        s.add_argument("--no-review", action="store_true", help="Disable interactive review of AI answers")
        s.add_argument("--ai-confidence", type=float, default=0.6, help="Minimum confidence threshold for AI answers")
        s.add_argument("--mock-ai", action="store_true", help="Use deterministic mock AI provider (offline testing)")

        # Auth & Browser
        s.add_argument("-u", "--user", help="Username for platforms requiring login")
        s.add_argument("--password", help="Password (plain text; prefer prompt, env, or --pass-file)")
        s.add_argument("--pass-file", help="File containing password")
        s.add_argument("--pass-env", default="QA_PASS", help="Environment variable holding password (default: QA_PASS)")
        s.add_argument("--session", "--storage-state", dest="storage_state", help="Path to saved Playwright storage state JSON")
        s.add_argument("--cache-dir", default=".quizagent_cache", help="Directory for learned profiles and cache state")
        s.add_argument("--no-cache", action="store_true", help="Disable persistent cache")
        s.add_argument("--no-state", action="store_true", help="Do not reuse cached login storage states")
        s.add_argument("--fresh", action="store_true", help="Ignore memoized answers")
        s.add_argument("-o", "--out", default="runs", help="Output directory for execution reports")
        s.add_argument("--max-steps", type=int, default=150, help="Maximum navigation steps before halting")
        s.add_argument("--headed", action="store_true", default=True, help="Run browser in visible (headed) mode (default)")
        s.add_argument("--headless", action="store_false", dest="headed", help="Run browser in headless background mode")
        s.add_argument("--cdp", metavar="URL", help="Attach to running Chrome via Chrome DevTools Protocol (e.g. http://127.0.0.1:9222)")
        s.add_argument("--profile", metavar="DIR", help="Persistent Chrome user profile directory")
        s.add_argument("--trace", action="store_true", help="Capture screenshot for every navigation step")
        s.add_argument("--confirm-submit", action="store_true", help="Require user confirmation before clicking final submit")

        if name == "auto":
            s.add_argument("--pick", help="Regex pattern matching quiz title/URL to select which assessment to take")
            s.add_argument("--all", action="store_true", help="Attempt all discovered quizzes")
            s.add_argument("--list", action="store_true", help="Discover and list quizzes without attempting them")
            s.add_argument("--again", action="store_true", help="Re-attempt quizzes already marked completed in cache")
            s.add_argument("--budget", type=int, default=25, help="Maximum page crawl budget")

    # ---- serve
    sv = sub.add_parser("serve", help="Start local web dashboard (token-gated, binds 127.0.0.1)")
    sv.add_argument("--port", type=int, default=8765, help="HTTP dashboard port")
    sv.add_argument("--cache-dir", default=".quizagent_cache", help="Cache directory")
    sv.add_argument("-o", "--out", default="runs", help="Output directory")

    # ---- chrome
    ch = sub.add_parser("chrome", help="Launch Chrome with remote debugging port enabled for CDP attachment")
    ch.add_argument("--port", type=int, default=9222, help="Remote debugging port")
    ch.add_argument("--profile", default=os.path.expanduser("~/.quizagent/chrome-profile"), help="Dedicated profile directory")

    # ---- cache
    c = sub.add_parser("cache", help="Inspect or clear cache")
    c.add_argument("action", choices=["show", "clear"], help="Cache operation")
    c.add_argument("--cache-dir", default=".quizagent_cache", help="Cache directory")

    return ap


def _load_and_merge_config(args: argparse.Namespace) -> Dict[str, Any]:
    """Merge CLI arguments on top of optional configuration file."""
    config_file = getattr(args, "config", None)
    params: Dict[str, Any] = {}

    if config_file and (config_file.endswith(".yaml") or config_file.endswith(".yml") or (
            config_file.endswith(".json") and not os.path.basename(config_file).startswith("spa_"))):
        try:
            cfg_data = load_config(config_file)
            params["url"] = cfg_data["target"].get("url")
            params["adapter"] = cfg_data["target"].get("adapter", "auto")
            params["headed"] = not cfg_data["browser"].get("headless", False)
            params["cdp"] = cfg_data["browser"].get("cdp_url")
            params["profile"] = cfg_data["browser"].get("profile_dir")
            params["storage_state"] = cfg_data["auth"].get("storage_state")
            params["user"] = cfg_data["auth"].get("username")
            params["pass_env"] = cfg_data["auth"].get("password_env", "QA_PASS")
            params["key"] = cfg_data["strategy"].get("key_file")
            params["fallback"] = cfg_data["strategy"].get("fallback", "skip")
            params["text_default"] = cfg_data["strategy"].get("text_default", "test")
            params["ai_provider"] = cfg_data["ai"].get("provider") if cfg_data["ai"].get("enabled") else None
            params["ai_model"] = cfg_data["ai"].get("model")
            params["ai_review"] = cfg_data["ai"].get("review_mode", True)
            params["ai_confidence"] = cfg_data["ai"].get("confidence_threshold", 0.6)
            params["behavior"] = cfg_data["execution"].get("behavior", "student")
            params["speed"] = cfg_data["execution"].get("speed", 1.0)
            params["seed"] = cfg_data["execution"].get("seed", 0)
            params["max_steps"] = cfg_data["execution"].get("max_steps", 150)
            params["trace"] = cfg_data["execution"].get("trace", False)
            params["confirm_submit"] = cfg_data["execution"].get("confirm_submit", True)
            params["out"] = cfg_data["execution"].get("output_dir", "runs")
            params["cache_dir"] = cfg_data["execution"].get("cache_dir", ".quizagent_cache")
        except Exception as e:
            logger.warning("Could not parse config file %s: %s", config_file, e)

    # Override with explicit CLI arguments
    for k, v in vars(args).items():
        if v is not None:
            if k == "url_opt" and v:
                params["url"] = v
            elif k == "url" and v:
                params["url"] = v
            elif k == "no_review" and v:
                params["ai_review"] = False
            elif k == "ai_review" and v:
                params["ai_review"] = True
            else:
                params[k] = v

    return params


def main(argv: Optional[List[str]] = None) -> int:
    ap = build_parser()
    if argv is None:
        argv = sys.argv[1:]

    # Default invocation without arguments: show help if not interactive, else doctor or guide
    if not argv:
        ap.print_help()
        return 0

    a = ap.parse_args(argv)

    if a.cmd == "doctor":
        return Doctor(cache_dir=a.cache_dir, cdp_url=a.cdp).render_cli()

    if a.cmd == "config":
        if a.config_cmd == "init":
            path = init_config(a.output, format=a.format)
            print(f"[OK] Configuration initialized at: {path.resolve()}")
            print(f"Edit this file, then execute: quizagent run --config {a.output}")
            return 0
        return 0

    if a.cmd == "serve":
        from .server import serve
        serve(a.port, a.cache_dir, a.out)
        return 0

    if a.cmd == "chrome":
        import subprocess
        from .browser_launcher import find_chrome_executable
        exe = find_chrome_executable()
        if not exe:
            print("Google Chrome executable not found in standard paths.")
            print("Please start Chrome manually with: --remote-debugging-port=" + str(a.port))
            return 1
        os.makedirs(a.profile, exist_ok=True)
        subprocess.Popen([exe, f"--remote-debugging-port={a.port}", f"--user-data-dir={a.profile}", "--no-first-run"])
        print(f"Chrome launched on debugging port {a.port} with profile {a.profile}.")
        print(f"Log into your site in that browser window, then run:")
        print(f"  quizagent run <URL> --cdp http://127.0.0.1:{a.port}")
        return 0

    if a.cmd == "cache":
        ch = Cache(a.cache_dir)
        from .learner import SelfLearningEngine
        learner = SelfLearningEngine(a.cache_dir)
        try:
            if a.action == "clear":
                ch.clear()
                learner.clear()
                print("[OK] Cache and self-learning models cleared.")
            combined = {
                "cache": ch.stats(),
                "self_learning": learner.stats(),
            }
            print(json.dumps(combined, indent=2))
        finally:
            ch.close()
            learner.close()
        return 0

    # Commands 'run', 'probe', 'auto'
    params = _load_and_merge_config(a)

    if a.cmd == "run":
        target_url = params.get("url")
        if not target_url:
            if sys.stdin.isatty():
                params = run_interactive_wizard()
                target_url = params.get("url")
            else:
                print("Error: Target URL or --config must be provided when running in non-interactive mode.")
                print("Usage: quizagent run <URL>  OR  quizagent run --config <config.yaml>")
                return 1

        agent = build_agent_from_params(params)
        rep = agent.run(target_url)

        summary_data = {
            "status": rep.get("status"),
            "adapter": rep.get("adapter"),
            "report_path": rep.get("report_path"),
            "summary": rep.get("summary"),
        }
        print(json.dumps(summary_data, indent=2))
        return 0 if rep.get("status") == "completed" else 1

    if a.cmd == "probe":
        agent = build_agent_from_params(params)
        result = agent.probe(params["url"])
        print(json.dumps(result, indent=2))
        return 0

    if a.cmd == "auto":
        agent = build_agent_from_params(params)
        res = agent.auto(
            params["url"],
            pick=a.pick,
            run_all=a.all,
            list_only=a.list,
            budget=a.budget,
            again=a.again,
        )
        print(json.dumps(res, indent=2))
        success = (res.get("runs") and all(r["status"] == "completed" for r in res["runs"])) or (a.list and res.get("found"))
        return 0 if success else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
