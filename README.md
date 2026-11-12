# QuizPilot

[![CI](https://github.com/ram-mangla/quizpilot/actions/workflows/ci.yml/badge.svg)](https://github.com/ram-mangla/quizpilot/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/ram-mangla/quizpilot?color=blue)](https://github.com/ram-mangla/quizpilot/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Playwright](https://img.shields.io/badge/playwright-1.45+-green.svg)](https://playwright.dev/)

> **A reliable, self-learning browser automation harness and AI copilot CLI for web assessments.**

QuizPilot drives assessment, quiz, and test web applications using a real Chromium browser via Playwright (`discover -> scan -> answer -> navigate -> submit -> verify`). Built strictly for **authorized practice, self-paced learning, and QA/load testing of platforms you own or are explicitly authorized to test**.

*(Note: For backward compatibility, both `quizpilot` and `quizagent` commands are supported identically).*

Answers can originate from an exact **Answer Key file**, an **AI-assisted model chain** (NVIDIA NIM or OpenRouter) with interactive **human-in-the-loop review**, or deterministic **fallback strategies** (first, last, random).

---

## Table of Contents

1. [Features](#features)
2. [Screenshots & Demo](#screenshots--demo)
3. [System Requirements](#system-requirements)
4. [Installation](#installation)
   - [Windows (PowerShell / Command Prompt)](#windows-installation)
   - [Linux (Ubuntu / Debian / Fedora)](#linux-installation)
   - [macOS](#macos-installation)
5. [First-Run Health Check (`doctor`)](#first-run-health-check)
6. [Interactive Guided CLI](#interactive-guided-cli)
7. [Direct CLI Commands](#direct-cli-commands)
8. [Authentication Modes](#authentication-modes)
9. [Chrome Profile & Session Management](#chrome-profile--session-management)
10. [Saved Playwright Sessions](#saved-playwright-sessions)
11. [AI Providers & Model Routing](#ai-providers--model-routing)
12. [Adaptive Self-Learning & DOM Evolution](#adaptive-self-learning--dom-evolution)
13. [Configuration Reference (YAML / JSON)](#configuration-reference)
14. [Local Practice Assessment Demo](#local-practice-assessment-demo)
15. [Security & Responsible Use](#security--responsible-use)
16. [Architecture](#architecture)
17. [Troubleshooting & Diagnostics](#troubleshooting--diagnostics)
18. [Development & Automated Testing](#development--automated-testing)
19. [Contributing](#contributing)
20. [Roadmap](#roadmap)
21. [License](#license)

---

## 1. Features

- **Adaptive Self-Learning Engine:** Learns arbitrary DOM patterns, question container clusters, button selectors, and Markov state transition graphs dynamically as you browse.
- **Robust DOM Heuristics:** Scans native radio buttons, checkboxes, dropdown selects, text fields, textareas, numeric inputs, ARIA widgets (`role="radio"`, `role="checkbox"`), open Shadow DOM, and iframes.
- **Human-in-the-Loop Review:** Interactive review prompt allows learners to accept, modify, or reject AI model suggestions before anything is clicked.
- **Multiple Authentication Methods:** Supports public assessments, credentials via environment variables / masked prompts, persistent Chrome profiles, CDP remote debugging, and saved Playwright storage state files.
- **Dual Execution Engine:**
  - Guided interactive terminal wizard (`quizpilot run`).
  - Direct, scriptable command-line arguments and configuration files.
- **AI Model Routing:** Integrated with OpenAI-compatible APIs (NVIDIA NIM and OpenRouter) with automatic fallback chains (`nemotron_ultra`, `nemotron_lightning`, `nemotron_super_vl`, `north_mini_code`, `gemma_4`).
- **Simulated Pacing Profiles:** Realistic behavior models (`instant`, `student`, `careful`, `erratic`) with reading delays, thinking pauses, answer changes, and revisit probabilities.
- **Verified Metrics Only:** Measures actual DOM facts. Never estimates scores or fabricates success rates.
- **Live Local Control Dashboard:** Built-in token-gated web dashboard (`quizpilot serve`) running strictly on `127.0.0.1`.

---

## 2. Screenshots & Demo

### CLI Command Center & Help Output
![CLI Help Output](screenshots/01_cli_help.png)

### System Diagnostics (`quizpilot doctor`)
![System Diagnostics](screenshots/02_doctor_check.png)

### Guided Interactive Wizard
![Interactive Wizard](screenshots/03_interactive_wizard.png)

### Practice Assessment DOM Detection
![Assessment Detection](screenshots/04_browser_assessment_detection.png)

### User-Reviewed Answer Assistance
![Question Answering](screenshots/05_question_extraction_answering.png)

### Server-Graded Verification Report
![Final Results](screenshots/06_final_report_results.png)

---

## 3. System Requirements

- **Operating System:** Windows 10/11 (x64), Linux (Ubuntu 20.04+, Debian 11+, Fedora 36+), macOS 12+ (Intel & Apple Silicon).
- **Python:** Python 3.10, 3.11, 3.12, 3.13, or 3.14.
- **Browser:** Google Chrome (optional, for persistent profile/CDP) or Playwright bundled Chromium.

---

## 4. Installation

### Windows Installation

```powershell
# 1. Clone the repository
git clone https://github.com/ram-mangla/quizpilot.git
cd quizpilot

# 2. Run the automated setup script
.\setup.bat

# Or install manually:
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
python -m playwright install chromium
```

### Linux Installation

```bash
# 1. Clone the repository
git clone https://github.com/ram-mangla/quizpilot.git
cd quizpilot

# 2. Run the automated setup script
chmod +x setup.sh
./setup.sh

# Or install manually:
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
python -m playwright install chromium
```

### macOS Installation

```bash
# 1. Clone the repository
git clone https://github.com/ram-mangla/quizpilot.git
cd quizpilot

# 2. Run setup script or install via pip
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
python -m playwright install chromium
```

Verify your installation:
```bash
quizpilot --version
quizpilot doctor
```

---

## 5. First-Run Health Check (`doctor`)

Before running your first assessment, run the built-in diagnostic tool to verify all requirements:

```bash
quizpilot doctor
```

`quizpilot doctor` verifies:
- Python version and architecture.
- Playwright installation and Chromium browser binary status.
- System Google Chrome executable detection.
- Chrome profile directories and active instance locks.
- CDP remote debugging port reachability.
- AI provider API keys (`NVIDIA_API_KEY`, `OPENROUTER_API_KEY`) with secret masking.
- Filesystem cache read/write permissions.

---

## 6. Interactive Guided CLI

Launch QuizPilot without arguments to enter the guided setup wizard:

```bash
quizpilot run
```

The wizard prompts you through:
1. Target Assessment URL.
2. Browser mode (Headed, Headless, Attach via CDP, Persistent Profile).
3. Authentication mode (None, Credentials, Saved Session).
4. Strategy (AI-Assisted Practice, Answer Key, Fallback Only).
5. AI provider selection (NVIDIA NIM, OpenRouter, Mock) and model choice.
6. Human review mode (Yes / No).
7. Behavioral pacing (Student, Instant, Careful, Erratic).
8. Report output directory.

---

## 7. Direct CLI Commands

### Direct URL Execution
```bash
quizpilot run "http://127.0.0.1:5055/single" --key examples/key_example.json
```

### AI-Assisted Practice with Human Review
```bash
quizpilot run "http://127.0.0.1:5055/single" \
  --ai-provider nvidia \
  --ai-model nemotron_ultra \
  --ai-review
```

### Offline / Mock AI Practice
```bash
quizpilot run "http://127.0.0.1:5055/single" --mock-ai
```

### Dry Run DOM Inspection (`probe`)
Inspect what QuizPilot's DOM scanner detects without answering or submitting:
```bash
quizpilot probe "http://127.0.0.1:5055/single"
```

### Autopilot Discovery & Crawler (`auto`)
Crawl same-origin links to find and take quizzes:
```bash
quizpilot auto "http://127.0.0.1:5055/hub" --list
quizpilot auto "http://127.0.0.1:5055/hub" --pick "networking" --key examples/key_example.json
```

### Cache Management & Self-Learning Inspection
```bash
quizpilot cache show
quizpilot cache clear
```

---

## 8. Authentication Modes

### A. Public / Unauthenticated
Assessments that do not require credentials:
```bash
quizpilot run "http://127.0.0.1:5055/single"
```

### B. Form-Based Username & Password
Passwords can be provided via environment variables, files, or masked interactive prompts:

```bash
# Recommended: Environment variable
QA_PASS="SecretPassword123" quizpilot run "https://moodle.example.edu/quiz" --user student1

# Password file
quizpilot run "https://moodle.example.edu/quiz" --user student1 --pass-file /path/to/pw.txt

# Interactive prompt (password input is masked and excluded from logs)
quizpilot run "https://moodle.example.edu/quiz" --user student1
```

---

## 9. Chrome Profile & Session Management

### Attach to Running Chrome via CDP (Recommended for SSO/2FA)
Attach to your personal Chrome instance where you are already signed in:

1. Launch Chrome with remote debugging enabled:
   ```bash
   quizpilot chrome --port 9222
   ```
2. Log into your institution or platform in that opened window.
3. Run QuizPilot against the assessment tab:
   ```bash
   quizpilot run "https://site.example.com/quiz" --cdp http://127.0.0.1:9222
   # Or drive the currently active tab:
   quizpilot run here --cdp http://127.0.0.1:9222
   ```

### Persistent Profile Directory
Create an isolated profile that persists cookies across runs:
```bash
quizpilot run "https://site.example.com/quiz" --profile ~/.quizpilot/my-profile --headed --user student1
```

---

## 10. Saved Playwright Sessions

Export and reuse authenticated Playwright storage states:

```bash
quizpilot run "https://site.example.com/quiz" --session ~/.quizagent_cache/state/session.json
```

> **Security Note:** Session files contain authorization cookies and tokens. QuizPilot automatically applies `0600` file permissions to restrict access to the current user. Session files are strictly excluded in `.gitignore`.

---

## 11. AI Providers & Model Routing

QuizPilot supports free and commercial models via NVIDIA NIM and OpenRouter:

### Supported Model Slugs

| Logical Name | Provider | Model ID | Primary Task |
|---|---|---|---|
| `nemotron_ultra` | NVIDIA NIM | `nvidia/nemotron-3-ultra-550b-a55b` | Reasoning & Complex Q&A |
| `nemotron_lightning` | NVIDIA NIM | `nvidia/nemotron-3.5-lightning-30b-a3b` | General & Speed |
| `nemotron_super_vl` | NVIDIA NIM | `nvidia/nemotron-3.5-super-vl-120b-a12b` | Vision & Diagrams |
| `nemotron_ultra_or` | OpenRouter | `nvidia/nemotron-3-ultra-550b-a55b:free` | Reasoning (Free) |
| `nemotron_lightning_or` | OpenRouter | `nvidia/nemotron-3.5-lightning:free` | General (Free) |
| `north_mini_code` | OpenRouter | `cohere/north-mini-code:free` | Programming / Code |
| `gemma_4` | OpenRouter | `google/gemma-4-26b-a4b-it:free` | Vision & Image Questions |
| `nemotron_nano_omni` | OpenRouter | `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` | Multimodal |

### Configuration
QuizPilot automatically loads your central `.env` file from the project root (or user home `~/.quizagent/.env`) without overriding shell variables:

1. Copy the example template to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Open `.env` and paste your actual keys:
   ```bash
   NVIDIA_API_KEY=nvapi-your-actual-key-here
   OPENROUTER_API_KEY=sk-or-your-actual-key-here
   ```
3. Your `.env` file is strictly protected and ignored by `.gitignore`, so it remains local on your machine and is never committed to GitHub. Only `.env.example` is committed.

---

## 12. Adaptive Self-Learning & DOM Evolution

QuizPilot features a production-grade **Self-Learning Engine** (`quizagent/learner.py`) that continuously adapts to arbitrary, evolving assessment systems:

1. **DOM Structure Learning & Fingerprint Mining:**
   - As QuizPilot encounters new quiz formats (custom divs, Web Components, nested shadow DOM, accessible ARIA roles), it analyzes successful element clusters.
   - Discovers and stores specialized CSS selector patterns for question containers, stems, option labels, and active selection markers.
   - When confidence reaches threshold, it automatically synthesizes a high-priority `LearnedAdapter` for that domain.

2. **Flow & Phase State Transition Graph:**
   - Constructs a directed Markov state model (`Landing` -> `Start` -> `Questions` -> `Summary` -> `Confirm` -> `Results`).
   - Learns exactly which button text and selectors successfully advance the page, whether confirmation modals exist, and how completion is signaled.
   - Recovers from stuck or unknown page states by querying the highest-confidence learned actions.

3. **Confidence Reinforcement & Auto-Healing:**
   - Every time an action leads to a verified answer selection or server-graded result, confidence increases (`hits += 1`).
   - If a page's DOM changes, failure decays confidence and triggers exploratory heuristics to re-learn the modified DOM.

Inspect and manage learned models:
```bash
# View cache and self-learning statistics
quizpilot cache show

# Reset learned patterns and transition models
quizpilot cache clear
```

---

## 13. Configuration Reference

Initialize a configuration file:
```bash
quizpilot config init --format yaml -o quizpilot.yaml
# Or JSON format:
quizpilot config init --format json -o quizpilot.json
```

Execute using your configuration file:
```bash
quizpilot run --config quizpilot.yaml
```

### Complete Configuration Schema (`quizpilot.yaml`)
```yaml
version: "1.0"

target:
  url: "http://127.0.0.1:5055/single"
  adapter: "auto"              # auto | generic | moodle
  custom_profile: null         # Optional path to site selector JSON

browser:
  headless: false              # Run visible browser window
  cdp_url: null                # Attach to existing Chrome
  profile_dir: null            # Persistent Chrome profile directory
  timeout: 30000               # Navigation timeout (ms)

auth:
  mode: "none"                 # none | credentials | saved_session | cdp
  username: null
  password_env: "QA_PASS"
  storage_state: null

strategy:
  mode: "ai"                   # ai | key | fallback
  key_file: null               # Path to key.json
  fallback: "skip"             # skip | fail | first | last | random
  text_default: "test"

ai:
  enabled: true
  provider: "nvidia"           # nvidia | openrouter | mock
  model: "nemotron_ultra"
  review_mode: true            # Ask user before selecting answer
  confidence_threshold: 0.6
  timeout: 45.0

execution:
  behavior: "student"          # instant | student | careful | erratic
  speed: 1.0
  seed: 0
  max_steps: 150
  trace: false
  confirm_submit: true         # Require explicit confirmation before submitting
  output_dir: "runs"
  cache_dir: ".quizagent_cache"
```

---

## 14. Local Practice Assessment Demo

QuizPilot bundles a self-contained local practice assessment application with 10 question layouts:

1. **Start the local practice server:**
   ```bash
   python testsite/app.py 5055
   ```
2. **In a second terminal, execute QuizPilot:**
   ```bash
   # Run against single-page quiz with answer key
   quizpilot run "http://127.0.0.1:5055/single" --key examples/key_example.json

   # Run with simulated student behavior
   quizpilot run "http://127.0.0.1:5055/single" --behavior student --speed 2.0

   # Run with AI assistance (mock mode)
   quizpilot run "http://127.0.0.1:5055/single" --mock-ai
   ```

---

## 15. Security & Responsible Use

- **Authorized Practice Only:** QuizPilot is intended for educational practice, self-study, and authorized system testing.
- **No Anti-Bot Bypass:** QuizPilot contains no bypasses for CAPTCHAs, biometric proctoring, or security access controls.
- **No Autonomous Live Submission:** Final submission requires confirmation (`--confirm-submit`), preventing accidental submissions on graded exams.
- **Credential Protection:** Passwords and API keys are strictly excluded from logs, error reports, and traces.

---

## 16. Architecture

QuizPilot uses a clean modular architecture:

```
quizagent/
├── agent.py               # Main CLI execution engine & phase machine
├── ai_strategy.py         # AI provider answering strategy & review workflow
├── browser_ctrl.py        # Synchronous Playwright controller on worker thread
├── browser_launcher.py    # Cross-platform Chrome & profile detection
├── cache.py               # SQLite cache for site profiles & memoized answers
├── cli.py                 # Primary command-line entrypoint & subcommands
├── config.py              # YAML/JSON configuration manager
├── doctor.py              # Environment diagnostic subsystem
├── learner.py             # Adaptive Self-Learning Engine (DOM & Flow evolution)
├── llm/                   # AI gateway, routing chains, and error handling
├── model.py               # Core dataclasses (Q, Opt, Nav, Choice, Obs)
├── normalize.py           # Text normalization & question fingerprinting
├── page_inspect.js        # In-page DOM inspection script
├── quiz_session.py        # State-machine orchestration across browser & AI
├── report.py              # Verified metrics & Markdown report generator
├── scanjs.py              # DOM scanner for native, ARIA, and custom elements
└── wizard.py              # Interactive guided CLI wizard
```

---

## 17. Troubleshooting & Diagnostics

Run `quizpilot doctor` to diagnose configuration problems:

| Issue | Cause | Resolution |
|---|---|---|
| `Chromium binary not found` | Playwright binaries not downloaded | Run `python -m playwright install chromium` |
| `Chrome User Data Directory Locked` | Google Chrome is actively running | Close running Chrome windows, or use `--cdp http://127.0.0.1:9222` |
| `Missing NVIDIA_API_KEY` | Environment variable not exported | Set `export NVIDIA_API_KEY="..."` or add to `.env` |
| `State conflict 409` | Navigation attempted before page is ready | Wait for page load or check `--timeout` settings |

---

## 18. Development & Automated Testing

Run the automated test suite (87 tests covering CLI, adapters, AI mocks, learning, and reports):
```bash
python -m pytest tests -v
```

Run end-to-end tests against the local test site:
```bash
# Terminal 1: Start test server
python testsite/app.py 5055

# Terminal 2: Run E2E test matrix
python tests/e2e.py
```

Build distribution packages:
```bash
python -m build
```

---

## 19. Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) and our [Code of Conduct](CODE_OF_CONDUCT.md).

1. Fork the repo and create a feature branch (`git checkout -b feature/amazing-feature`).
2. Run unit tests (`pytest tests`).
3. Commit changes (`git commit -m "Add amazing feature"`).
4. Push to branch (`git push origin feature/amazing-feature`).
5. Open a Pull Request.

---

## 20. Roadmap

- [x] Cross-platform Chrome detection and profile isolation.
- [x] Unified interactive wizard (`quizpilot run`).
- [x] YAML and JSON configuration file parser.
- [x] Comprehensive diagnostic suite (`quizpilot doctor`).
- [x] Multi-model AI routing with human review mode.
- [x] Adaptive Self-Learning Engine with Markov Flow Graph Evolution.
- [ ] Export reports to HTML and PDF formats.
- [ ] Support for audio and spoken question accessibility parsing.
- [ ] Plugin architecture for community site adapters.

---

## 21. License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
