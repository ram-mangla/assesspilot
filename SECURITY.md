# Security Policy

## Scope & Authorized Usage

QuizPilot is strictly designed and intended for **authorized practice, self-paced training, educational research, and QA testing of assessment systems you own or have explicit authorization to test**.

- **No Bypass of Access Controls:** QuizPilot does not include, and will not accept, features intended to bypass CAPTCHA, biometric proctoring, anti-bot protections, or security access controls.
- **No Autonomous Live Assessment Completion:** QuizPilot incorporates guardrails requiring human confirmation for consequential actions (such as final submission). It is not designed to autonomously complete graded educational or certification exams.
- **Practice & Training Focus:** The tool is engineered to assist learners in reviewing question materials and developers in load/robustness testing web assessment forms.

## Reporting a Vulnerability

If you discover a security vulnerability in QuizPilot, please disclose it responsibly. Do **not** create a public GitHub issue.

Please report security issues privately to the maintainers:
- **Email:** `manglaram69@gmail.com` (or via private GitHub Security Advisory)
- Please provide a detailed description of the issue, reproducible steps, and potential impact.
- Maintainers will acknowledge receipt within 48 hours and provide a timeline for triage and remediation.

## Security Best Practices for Users

1. **Protect API Keys:** Store API keys (`NVIDIA_API_KEY`, `OPENROUTER_API_KEY`) in environment variables or a `.env` file outside version control. Never commit keys to a public repository.
2. **Protect Saved Sessions:** Playwright storage state files contain authentication cookies and tokens. Ensure file permissions restrict access to your user account only.
3. **Avoid Command-Line Passwords:** Do not pass passwords via `--password` in shared multi-user environments, as arguments are visible in process tables (`ps aux`). Use `--pass-file`, environment variables, or interactive masked prompts.
4. **Local Dashboard Security:** The `quizpilot serve` dashboard binds strictly to `127.0.0.1` and requires a per-run random cryptographic token. Do not expose this port to public networks.
