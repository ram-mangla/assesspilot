#!/usr/bin/env bash
# QuizPilot One-Shot Setup (Linux / macOS)
set -euo pipefail

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
python -m playwright install chromium

echo ""
echo "Setup completed successfully!"
echo "Activate your environment:"
echo "  source .venv/bin/activate"
echo "Then run:"
echo "  quizpilot doctor"
echo "  quizpilot --help"
