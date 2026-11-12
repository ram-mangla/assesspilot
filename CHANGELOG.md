# Changelog

All notable changes to the QuizPilot project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-11-12

### Added
- **Unified CLI Product Interface (`quizpilot` and `quizagent`):**
  - `quizpilot --help` with comprehensive command and flag documentation.
  - `quizpilot --version` printing application version.
  - `quizpilot doctor` diagnosing Python environment, Playwright installation, Chrome detection, API key configuration, and cache health.
  - `quizpilot config init` with interactive and templated configuration generation (YAML and JSON formats).
  - `quizpilot run` supporting both an intuitive, guided interactive CLI experience and full direct command-line arguments.
- **Adaptive Self-Learning & DOM Evolution Engine:**
  - Automated DOM pattern discovery, fingerprint clustering, and high-priority `LearnedAdapter` synthesis.
  - Markov state transition graph learning navigation flows, buttons, and phase completions.
  - Confidence reinforcement scoring with automated self-healing against evolving DOM trees.
- **Cross-Platform Browser Detection & Profile Management:**
  - Automated detection of Google Chrome and Chromium across Windows, macOS, and Linux.
  - Dedicated detection of user profile directories (`Default`, `Profile 1`, etc.).
  - Chrome lock (`SingletonLock`) detection and safe profile separation to prevent session corruption.
  - Full Chrome DevTools Protocol (`--cdp`) attachment support for pre-authenticated browser instances.
- **Enhanced AI Integration & Review Workflow:**
  - Seamless integration of NVIDIA NIM and OpenRouter models directly into the CLI.
  - Human-in-the-loop answer review mode (`--ai-review`) ensuring no automatic actions on consequential assessments.
  - Preserved multi-model routing (`nemotron_ultra`, `nemotron_lightning`, `nemotron_super_vl`, `north_mini_code`, `gemma_4`, `nemotron_nano_omni`).
  - Built-in Mock AI provider for offline testing and deterministic CI runs.
- **Packaging & Distribution:**
  - Modern `pyproject.toml` specification for installation via `pip`, `pipx`, or `uv`.
  - Dual console entrypoints: `quizpilot = "quizagent.cli:main"` and `quizagent = "quizagent.cli:main"`.
- **Automated Testing & QA:**
  - Cross-platform test suite supporting Windows, Linux, and macOS (87 automated tests passing).
  - Multi-OS GitHub Actions workflow.
  - Local mock assessment application (`testsite/app.py`) covering 10 distinct quiz formats.
- **Security & Privacy:**
  - Comprehensive `.gitignore` to prevent credential and session leakages.
  - Masked password prompts (`getpass`) and redacted environment variable logs.
  - Explicit confirmation requirement for final submission.
