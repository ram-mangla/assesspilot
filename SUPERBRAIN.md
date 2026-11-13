# SUPERBRAIN.md — AssessPilot (formerly QuizAgent)

Python + Playwright assessment and exam automation harness for pages the user owns or is authorised to test.
Two layers coexist; check which one a change touches before editing.

## Commands (verified)
- Install: `pip install -e .` or `./setup.sh` / `setup.bat` (creates `.venv`)
- Browser binary: `python -m playwright install chromium` (or use installed Chrome; setup scripts handle it)
- Diagnostics: `assesspilot doctor` (verifies Python, Playwright, Chrome profiles, API keys, cache)
- Unit tests: `python -m pytest tests -v` (87 passed, ~12s)
- Single test: `python -m pytest tests/test_ai.py -q`
- Run: `assesspilot run URL` / `assesspilot run URL --key key.json` / `assesspilot probe URL` (dry scan) / `assesspilot serve` (dashboard on 127.0.0.1:8765 with token auth)
- Cache inspection: `assesspilot cache show` / `assesspilot cache clear`

## Layout & Architecture
- `quizagent/` — the core package. Two architectural stacks coexist:
  - **Core CLI & Autonomous Engine:**
    - `agent.py`: Primary phase state machine (`start` -> `questions` -> `summary` -> `confirm` -> `done`, `login` / Google OAuth detection).
    - `learner.py`: Adaptive Self-Learning Engine (DOM pattern clustering, Markov state transition graphs, reinforcement scoring, and auto-healing).
    - `scanjs.py`: Fast in-page JavaScript scanner for native forms, ARIA widgets, Shadow DOM, and iframes.
    - `adapters.py`: Question & page observation adapters (`auto`, `generic`, `moodle`, and dynamically synthesized `LearnedAdapter`).
    - `browser_launcher.py`: Cross-platform Google Chrome binary and user profile detection (Windows, Linux, macOS), CDP reachability, and profile locking checks.
    - `ai_strategy.py`: Multi-model AI question answering strategies with interactive human-in-the-loop review.
    - `doctor.py`: System diagnostic health-check subsystem.
    - `wizard.py`: Guided terminal setup wizard for interactive runs.
    - `config.py`: YAML and JSON configuration profile manager.
    - `cache.py`: SQLite cache (`cache.db`, `learned_flow.db`) for site profiles, learned DOM patterns, memoized answers, and session storage states.
    - `discover.py`: Autopilot crawler discovering and taking assessment links from a portal or dashboard.
    - `behavior.py`: Realistic student pacing models (`instant`, `student`, `careful`, `erratic`).
    - `cli.py`: Primary command-line entrypoint (`assesspilot` and backward-compatible `quizagent`).
  - **Interactive Session & Web Dashboard Layer:**
    - `session.py`: `ManualBrowserSession` with worker thread + synchronous Playwright command queue.
    - `browser_ctrl.py`: Synchronous Playwright controller on the worker thread.
    - `quiz_session.py`: High-level session orchestration and attempt recording.
    - `session_state.py`: Session state representations.
    - `store.py`: SQLite attempt records.
    - `question_navigator.py`: Question navigation controls.
    - `submission_manager.py`: Confirmation-gated submission manager.
    - `server.py`: Local token-gated Flask web dashboard (binds strictly to `127.0.0.1:8765`).
    - `llm/`: Model registry, multi-provider gateway (`NVIDIA NIM` and `OpenRouter`), and fallback chains.
    - `metrics.py` / `report.py`: Verified metrics and Markdown/JSON report generators.
- `tests/`: Pytest suite (`test_ai.py`, `test_ai_strategy.py`, `test_browser_launcher.py`, `test_cli_commands.py`, `test_config_manager.py`, `test_learner.py`, `test_metrics.py`, `test_quiz_session.py`, `test_server.py`), `fakes.py` (mock browser/gateway).
- `examples/`: Configuration profiles and sample answer keys (`quizagent.yaml`, `quizagent.json`, `key_example.json`, `spa_div.json`).
- `screenshots/`: Authentic execution screenshots for README documentation.

## Google Login, Authentication & Profiles
- **Google OAuth / SSO Authentication:**
  - Automated bots are blocked by Google if launched in clean, isolated headless browser instances without credentials.
  - **Recommended execution methods for assessments behind Google Sign-In:**
    1. **CDP Attach to Existing Chrome (`--cdp`):**
       Launch your personal Chrome with remote debugging:
       `assesspilot chrome --port 9222` (or launch Chrome with `--remote-debugging-port=9222`)
       Log into Google / your institution in that window.
       Run: `assesspilot run <URL> --cdp http://127.0.0.1:9222` (or `assesspilot run here --cdp http://127.0.0.1:9222` to drive the active tab).
    2. **Named Chrome Profile (`--profile Mangla` or `--profile "Profile 1"`):**
       AssessPilot automatically resolves named Chrome profiles from `~/AppData/Local/Google/Chrome/User Data`.
       If launched in headed mode and a Google Sign-In / OAuth page is encountered, AssessPilot pauses and waits for you to complete sign-in in the open browser window.
       Once authenticated, session cookies and storage state are saved to `<profile>/qa_cookies.json` and `.quizagent_cache/state/`, persisting across all future runs.

## Conventions & Gotchas
- **Provider API Keys:** Loaded from central `.env` at root (`NVIDIA_API_KEY`, `OPENROUTER_API_KEY`). Keys are never sent to frontend, never printed in logs or traces, and `.env` is strictly git-ignored.
- **Model Slugs:** Defined in `quizagent/llm/__init__.py` (`MODELS`, `_TASK_MAP`). Never silently substitute models.
- **Verified Metrics Only:** `success_rate` is computed only from verified records (`quizagent/metrics.py`). Unverified or skipped answers never count. No verified data returns `None` / "No verified results yet".
- **Human Confirmation Guardrail:** Consequential final submissions require explicit user confirmation (`--confirm-submit`), preventing unintended submissions on live assessments.
- **Thread Boundary:** In `session.py`, Playwright runs on a background worker thread (`_Worker`). Controller calls go through `session.ctrl(op, **kwargs)` with keyword arguments.
- **Modal Confirmations:** `_control(..., allow_modal=True)` in `browser_ctrl.py` prefers in-modal controls for confirmation dialogs.
- **URL Validation:** Strict protocol enforcement (`http://`, `https://`). `javascript:`, `data:`, and `file:` schemes are rejected.
