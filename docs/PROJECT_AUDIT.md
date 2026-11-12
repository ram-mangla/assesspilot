# QuizAgent Project Audit & Architectural Analysis

**Date:** November 2026  
**Auditor:** Principal Software Architect & QA Lead  
**Repository:** QuizAgent Open-Source CLI Product  
**Operating System:** Windows 11 (Targeting Cross-Platform: Windows, Linux, macOS)  
**Runtime:** Python 3.10+ (Verified on Python 3.14)

---

## 1. Executive Summary

QuizAgent is a browser-automation and test-harness application designed for automated and user-assisted verification of quiz and assessment web applications. It leverages Playwright for deterministic browser control, features advanced DOM heuristics for question/control detection, supports multiple interaction styles (behavior profiles), and includes an OpenAI-compatible LLM gateway supporting NVIDIA NIM and OpenRouter models for AI-assisted practice.

While the core mechanics are sophisticated, the project is currently in an intermediate transition state between two architectural layers:
1. An initial CLI-driven test harness (`agent.py`, `cli.py`, `scanjs.py`, `adapters.py`) focused on answer keys, deterministic fallbacks, and behavioral simulation.
2. A newer threaded session architecture (`session.py`, `browser_ctrl.py`, `quiz_session.py`, `server.py`, `llm/`) with state-machine tracking, sqlite attempt metrics, and multi-model LLM routing.

To ship as a world-class, production-ready, open-source CLI product, QuizAgent requires unified CLI orchestration, complete cross-platform hardening, robust packaging (`pyproject.toml`), full interactive and non-interactive workflows, security safeguards, a local practice demo, automated test coverage, and documentation.

---

## 2. Codebase Structure & Inventory

```
quizagent/
├── .continue/             # Local developer environment keys (SECURITY SENSITIVE)
├── examples/              # Example custom configuration profiles (e.g., spa_div.json)
├── llmenv/                # Dev shell scripts for LLM environment exploration
├── moodle_seed/           # Seed data and test questions for Moodle integration
├── quizagent/             # Core application package
│   ├── llm/               # Model registry, routing gateway, and task classifiers
│   │   ├── __init__.py    # ModelSpec definitions, capability registry, task map
│   │   ├── gateway.py     # Resilient HTTP transport, retries, exponential backoff, error normalization
│   │   ├── suggest.py     # Prompt formatting, JSON schema validation, answer coercion
│   │   └── task_classifier.py # Rule-based task router (vision, code, reasoning, general)
│   ├── adapters.py        # Site-specific adapters (MoodleAdapter, GenericAdapter, ConfigAdapter)
│   ├── agent.py           # Original phase-machine CLI runner
│   ├── answer_applier.py  # [DEFECT] Malformed escaped-string stub (unlinked)
│   ├── behavior.py        # Pacing and interaction profiles (instant, student, careful, erratic)
│   ├── browser_ctrl.py    # Synchronous Playwright controller running on worker thread
│   ├── cache.py           # SQLite cache for learned site adapters, memoized fallback answers, runs
│   ├── cli.py             # Existing CLI entry point (subcommands: run, probe, auto, serve, chrome, cache)
│   ├── discover.py        # Best-first crawler for assessment discovery
│   ├── metrics.py         # Verified-only success rate calculation
│   ├── model.py           # Core dataclasses: Opt, Q, Nav, Choice, Obs
│   ├── normalize.py       # Prompt and option normalization, question fingerprinting
│   ├── page_inspect.js    # In-page JavaScript evaluating DOM state, controls, questions, timers
│   ├── question_navigator.py # High-level navigator, answer applier, and save manager
│   ├── quiz_session.py    # State-machine orchestration across browser thread and LLM gateway
│   ├── report.py          # Summary extraction, score parsing, Markdown/JSON reports
│   ├── save_manager.py    # [DEFECT] Malformed escaped-string stub (unlinked)
│   ├── scanjs.py          # DOM scanner for native, ARIA, and custom elements
│   ├── server.py          # Flask HTTP API and live web control dashboard
│   ├── server_test.py     # [DEFECT] 1-line dummy file
│   ├── session.py         # Threaded worker managing synchronous Playwright Chromium lifecycle
│   ├── session_state.py   # State machine constants and transition validators
│   ├── store.py           # SQLite persistence for attempt facts, question state, and metrics
│   └── strategies.py      # Answer selection strategies (KeyStrategy, SimpleStrategy, Chain)
├── tests/                 # Automated test suite
│   ├── e2e.py             # End-to-end matrix against local Flask fixture
│   ├── fakes.py           # In-memory fake browser, controller, and gateway for testing
│   ├── probe_all.py       # Batch probe runner
│   ├── test_ai.py         # Unit tests for model registry, routing, and error classification
│   ├── test_metrics.py    # Unit tests for verified success rate metrics
│   ├── test_quiz_session.py # Unit tests for quiz session state transitions
│   └── test_server.py     # Unit tests for Flask API endpoints
├── testsite/              # Mock assessment web application
│   └── app.py             # 10 diverse assessment formats with server-side grading
├── DEV_MODELS.md          # Development documentation for external LLM testing
├── README.md              # Initial documentation
├── requirements.txt       # Minimal package requirements
├── setup.bat              # Windows setup helper
├── setup.sh               # Unix setup helper
└── SUPERBRAIN.md          # Internal architecture guidelines and conventions
```

---

## 3. Detailed Component Audit

### 3.1 Browser Management & Playwright Implementation
* **Worker Thread Architecture:** `session.py` encapsulates Playwright operations within a single dedicated worker thread (`_Worker`). This prevents thread-safety violations with Playwright's sync API.
* **Persistent Context vs. Standard Launch:** Both persistent contexts (`launch_persistent_context`) and ephemeral contexts (`launch`) are supported.
* **OS Hardcoding Defect:** `agent.py` contains `chrome_path="/usr/bin/google-chrome"`. On Windows or macOS systems, this path is invalid. The system must detect Chrome across standard operating system locations:
  - Windows: `C:\Program Files\Google\Chrome\Application\chrome.exe`, `C:\Program Files (x86)\Google\Chrome\Application\chrome.exe`, `%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe`.
  - macOS: `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`.
  - Linux: `/usr/bin/google-chrome`, `/usr/bin/google-chrome-stable`, `/usr/bin/chromium-browser`, `/usr/bin/chromium`.
* **Chrome Profile Integration:** Existing Chrome profiles in user data directories can be locked by active browser instances (`SingletonLock`). The CLI must detect running instances, provide clear guidance, or support non-conflicting profile copies and CDP attachment.
* **Remote Debugging (CDP):** Supported via `quizagent chrome` and `--cdp http://127.0.0.1:9222`. The CLI attaches to a designated tab or opens a new tab without closing user sessions.

### 3.2 Authentication & Session Persistence
* **Credential Handling:** Credentials can be provided via prompt (`getpass`), file (`--pass-file`), or environment variable (`QA_PASS`). Command-line `--password` is supported but logged as a security risk.
* **Storage State:** Playwright's `storage_state` and cookie snapshots are saved in `.quizagent_cache/state/` and `<profile>/qa_cookies.json`.
* **Security Gap:** Session files lack explicit file permission restrictions on creation, and without a `.gitignore`, session cookies or credentials risk accidental commits.

### 3.3 Question Extraction & Page Detection
* **DOM Scanners:** `scanjs.py` and `page_inspect.js` provide sophisticated scanning of native `<input>`, `<select>`, `<textarea>`, ARIA widgets (`role="radio"`, `role="checkbox"`), open Shadow DOM trees, and iframes.
* **Adapters:**
  - `MoodleAdapter`: Detects Moodle via `window.M.cfg.wwwroot`, handles deferred feedback, `.que` containers, multi-part questions, and review pages.
  - `GenericAdapter`: Fallback heuristic parser for arbitrary pages.
  - `ConfigAdapter`: Profile-driven parsing matching custom CSS selectors from JSON configurations.

### 3.4 AI Provider Integration
* **Provider Registry (`quizagent/llm/__init__.py`):**
  - NVIDIA NIM (`https://integrate.api.nvidia.com/v1`)
  - OpenRouter (`https://openrouter.ai/api/v1`)
* **Task Routing:** Intelligently routes tasks based on question type:
  - `reasoning`: `nemotron_ultra` -> `nemotron_ultra_or` -> `nemotron_lightning` -> `nemotron_lightning_or`
  - `vision` / `multimodal`: `nemotron_super_vl` -> `nemotron_super_vl_or` -> `gemma_4` -> `nemotron_nano_omni`
  - `code`: `north_mini_code` -> `nemotron_ultra` -> `nemotron_ultra_or`
  - `general`: `nemotron_lightning` -> `nemotron_lightning_or` -> `nemotron_nano_omni` -> `gemma_4`
* **Resilience:** `Gateway` implements exponential backoff, jitter, rate-limit pauses (HTTP 429), error classification, and automatic failover to fallback models in the chain.
* **Test Isolation:** Mock transports ensure unit tests never make live network calls to AI APIs.

### 3.5 Identified Bugs, Code Debt & Anomalies
1. **Missing Packaging:** No `pyproject.toml` exists. Users cannot install `quizagent` as a command-line binary via `pip install .` or `pipx`.
2. **Missing Git Ignore:** No `.gitignore` file is present in the repository, exposing `.continue/.env` (containing sensitive API keys), cache databases, and session cookies.
3. **Escaped Code Files:** `quizagent/answer_applier.py` and `quizagent/save_manager.py` contain literal escaped strings (`\"\"\"...\\n...\"\"\"`) with unintegrated async code. Real logic is cleanly implemented in `quizagent/question_navigator.py`.
4. **Stale Stub:** `quizagent/server_test.py` contains only `print('ok')`.
5. **Cross-Platform Temp Directory in E2E:** `tests/e2e.py` hardcoded `TMP = "/tmp/qa_e2e"`, which causes path errors or root `C:\tmp` pollution on Windows.
6. **CLI Feature Gaps:**
   - Missing subcommands: `quizagent --version`, `quizagent doctor`, `quizagent config init`.
   - Missing interactive wizard when `quizagent run` is executed without arguments.
   - Missing YAML configuration file parser (`pyyaml`).
   - Lack of unified CLI option for selecting AI provider/model with human-in-the-loop review.

---

## 4. Preservation & Target Architecture

### 4.1 Functionality to Preserve Intact
- All DOM scanning and extraction algorithms (`scanjs.py`, `page_inspect.js`).
- All existing adapters (`MoodleAdapter`, `GenericAdapter`, `ConfigAdapter`).
- All behavioral profiles (`instant`, `student`, `careful`, `erratic`).
- Complete model routing chains and identifiers in `quizagent/llm/`.
- Verified-only metric calculation (`metrics.py`).
- Full compatibility with existing answer key JSON formats and site configuration profiles.
- Flask server and live dashboard functionality (`quizagent serve`).

### 4.2 Architecture Additions to Implement
1. **Packaging & Entrypoints:** Standard `pyproject.toml` with `[project.scripts]` mapping `quizagent = "quizagent.cli:main"`.
2. **Comprehensive CLI Engine:**
   - `quizagent --help` and `quizagent --version`.
   - `quizagent doctor`: Comprehensive system diagnosis (Python, Playwright, Chrome, API keys, cache, permissions).
   - `quizagent config init`: Interactive & templated configuration file generator (YAML/JSON).
   - `quizagent run`: Dual-mode (interactive wizard or direct CLI flags).
   - `quizagent chrome`: Launch Chrome with remote debugging.
   - `quizagent probe`: Inspect assessment page structure without answering.
   - `quizagent auto`: Crawl and attempt discovered assessments.
   - `quizagent serve`: Web control dashboard.
   - `quizagent cache`: Show and clear session/run caches.
3. **AI Strategy & Human Review Mode:** Bridge the LLM `Gateway` into the CLI answering flow, offering human review, confidence thresholds, and mock provider modes.
4. **Cross-Platform Browser Detection:** Centralized OS-aware detection for Chrome binaries and user profiles across Windows, macOS, and Linux.
5. **Security & Session Hardening:** Strict `.gitignore`, credential masking, file permission validation, and prevention of automated submission on live graded tests.
6. **Local Demo & Documentation:** Self-contained mock assessment demo, genuine screenshots, full GitHub documentation suite, and CI workflows.
