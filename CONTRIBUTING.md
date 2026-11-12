# Contributing to AssessPilot

Thank you for your interest in contributing to AssessPilot! We welcome contributions, bug reports, feature requests, and documentation improvements.

## Code of Conduct

By participating in this project, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

## Development Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/ram-mangla/assesspilot.git
   cd assesspilot
   ```

2. **Create and activate a virtual environment:**
   - **Linux / macOS:**
     ```bash
     python3 -m venv .venv
     source .venv/bin/activate
     ```
   - **Windows:**
     ```powershell
     python -m venv .venv
     .venv\Scripts\Activate.ps1
     ```

3. **Install dependencies and editable package:**
   ```bash
   pip install --upgrade pip
   pip install -e ".[dev]"
   python -m playwright install chromium
   ```

4. **Verify your environment:**
   ```bash
   assesspilot doctor
   ```

## Running Tests

Run the unit and integration test suite:
```bash
python -m pytest tests -v
```

## Pull Request Guidelines

1. Create a descriptive feature branch (`git checkout -b feature/amazing-feature`).
2. Adhere to Python style conventions (PEP 8, type hints where practical).
3. Ensure all tests pass (`python -m pytest tests`).
4. Include unit tests for any new features or bug fixes.
5. Update documentation and docstrings where relevant.
6. Submit a pull request to `main` using our pull request template.
