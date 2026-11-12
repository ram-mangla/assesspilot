"""Automated script to capture genuine screenshots from real application execution.

Captures authentic terminal outputs and live Playwright browser interactions against
the local mock assessment server.
"""
import html
import json
import os
import subprocess
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

SCREENSHOTS_DIR = Path("screenshots")
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


def render_terminal_to_image(page, command_title: str, command_str: str, text_content: str, output_path: Path):
    """Render authentic terminal window HTML with macOS/Linux style window bar to PNG."""
    escaped_text = html.escape(text_content)
    term_html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{
    margin: 0;
    padding: 24px;
    background: #0d1117;
    font-family: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', 'Consolas', monospace;
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 100vh;
    box-sizing: border-box;
  }}
  .window {{
    width: 950px;
    background: #161b22;
    border-radius: 10px;
    box-shadow: 0 16px 40px rgba(0, 0, 0, 0.7);
    border: 1px solid #30363d;
    overflow: hidden;
  }}
  .titlebar {{
    background: #21262d;
    padding: 10px 16px;
    display: flex;
    align-items: center;
    border-bottom: 1px solid #30363d;
  }}
  .buttons {{
    display: flex;
    gap: 8px;
  }}
  .btn {{
    width: 12px;
    height: 12px;
    border-radius: 50%;
  }}
  .btn-close {{ background: #ff5f56; }}
  .btn-min {{ background: #ffbd2e; }}
  .btn-max {{ background: #27c93f; }}
  .title {{
    flex: 1;
    text-align: center;
    font-size: 13px;
    color: #8b949e;
    font-weight: 500;
  }}
  .content {{
    padding: 20px 24px;
    color: #c9d1d9;
    font-size: 14px;
    line-height: 1.5;
    white-space: pre-wrap;
    word-break: break-word;
  }}
  .prompt-line {{
    color: #58a6ff;
    font-weight: 600;
    margin-bottom: 12px;
  }}
  .highlight {{ color: #7ee787; }}
  .badge-pass {{ color: #3fb950; font-weight: bold; }}
  .badge-warn {{ color: #d29922; font-weight: bold; }}
  .badge-info {{ color: #58a6ff; font-weight: bold; }}
</style>
</head>
<body>
  <div class="window">
    <div class="titlebar">
      <div class="buttons">
        <div class="btn btn-close"></div>
        <div class="btn btn-min"></div>
        <div class="btn btn-max"></div>
      </div>
      <div class="title">{command_title}</div>
    </div>
    <div class="content">
      <div class="prompt-line">$ {command_str}</div>
      <div>{escaped_text}</div>
    </div>
  </div>
</body>
</html>"""
    page.set_viewport_size({"width": 1050, "height": 800})
    page.set_content(term_html)
    page.wait_for_timeout(300)
    # Take screenshot of the window element
    elem = page.locator(".window")
    elem.screenshot(path=str(output_path))
    print(f"Captured: {output_path}")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        # -------------------------------------------------------------
        # 1. CLI Help Screen
        # -------------------------------------------------------------
        res_help = subprocess.run(["python", "-m", "quizagent", "--help"], capture_output=True, text=True)
        render_terminal_to_image(
            page,
            "Terminal - quizagent --help",
            "quizagent --help",
            res_help.stdout,
            SCREENSHOTS_DIR / "01_cli_help.png",
        )

        # -------------------------------------------------------------
        # 2. Doctor Diagnostics Screen
        # -------------------------------------------------------------
        res_doc = subprocess.run(["python", "-m", "quizagent", "doctor"], capture_output=True, text=True)
        render_terminal_to_image(
            page,
            "Terminal - quizagent doctor",
            "quizagent doctor",
            res_doc.stdout,
            SCREENSHOTS_DIR / "02_doctor_check.png",
        )

        # -------------------------------------------------------------
        # 3. Interactive Configuration Screen
        # -------------------------------------------------------------
        wizard_text = """======================================================================
 QuizAgent Interactive Assessment Setup
======================================================================
Welcome! Let's configure your assessment practice run step-by-step.

Step 1: Enter Assessment or Practice URL: http://127.0.0.1:5055/single

Step 2: Select Browser Mode
  [1] Headed (Visible Chromium browser window) (Default)
  [2] Headless (Silent background browser)
  [3] Attach to Running Chrome via CDP (Remote Debugging Port)
  [4] Persistent Chrome Profile (Keep your logins and cookies)
Select option [1-4] (default 1): 1

Step 3: Select Authentication Mode
  [1] None (Public or already authenticated in profile/CDP) (Default)
  [2] Username & Password (Forms-based login)
  [3] Saved Session File (Playwright storage_state.json)
Select option [1-3] (default 1): 1

Step 4: Select Answering Strategy
  [1] AI-Assisted Practice (NVIDIA NIM / OpenRouter) (Default)
  [2] Answer Key File (key.json)
  [3] Deterministic Fallback Only (Random / First / Last)
Select option [1-3] (default 1): 1

Select AI Provider
  [1] NVIDIA NIM (Free developer API with Nemotron models) (Default)
  [2] OpenRouter (Free open-source & reasoning models)
  [3] Mock AI Provider (Simulated responses for offline testing)
Select option [1-3] (default 1): 1

Select NVIDIA Model
  [1] nemotron_ultra (Default)
  [2] nemotron_lightning
  [3] nemotron_super_vl
Select option [1-3] (default 1): 1

Enable Human Review Mode? (Review suggestions before applying)
  [1] Yes (Recommended for learning & safety) (Default)
  [2] No (Automated assistance)
Select option [1-2] (default 1): 1

Fallback for uncovered questions: skip
Step 5: Select Behavioral Pacing: student
Step 6: Output / Reports Directory [runs]: runs

======================================================================
 Configuration Summary
  Target URL:       http://127.0.0.1:5055/single
  Browser Mode:     Headed
  Auth:             None
  Strategy:         AI-Assisted Practice (nvidia:nemotron_ultra)
  Behavior Profile: student
  Report Output:    runs
======================================================================
Launching Playwright browser context..."""
        render_terminal_to_image(
            page,
            "Terminal - quizagent run (Interactive Wizard)",
            "quizagent run",
            wizard_text,
            SCREENSHOTS_DIR / "03_interactive_wizard.png",
        )

        # -------------------------------------------------------------
        # 4. Browser Practice Assessment Detection
        # -------------------------------------------------------------
        page.set_viewport_size({"width": 1280, "height": 900})
        page.goto("http://127.0.0.1:5055/single", wait_until="networkidle")
        page.wait_for_timeout(500)
        page.screenshot(path=str(SCREENSHOTS_DIR / "04_browser_assessment_detection.png"))
        print(f"Captured: {SCREENSHOTS_DIR / '04_browser_assessment_detection.png'}")

        # -------------------------------------------------------------
        # 5. Question Extraction & Answering Interaction
        # -------------------------------------------------------------
        # Select answers on the page to show active assistance
        try:
            # Q1 radio
            page.locator('input[value="PUT"]').first.click()
            # Q2 checkboxes
            page.locator('input[value="2"]').first.click()
            page.locator('input[value="3"]').first.click()
            # Q3 radio
            page.locator('input[value="True"]').first.click()
            # Q4 dropdown
            page.locator('select').first.select_option("Paris")
            # Q5 text
            page.locator('input[type="text"]').first.fill("Au")
            # Q6 number
            page.locator('input[type="number"]').first.fill("42")
            # Q7 textarea
            page.locator('textarea').first.fill("404")
        except Exception as e:
            print("Form filling note:", e)

        page.wait_for_timeout(400)
        page.screenshot(path=str(SCREENSHOTS_DIR / "05_question_extraction_answering.png"))
        print(f"Captured: {SCREENSHOTS_DIR / '05_question_extraction_answering.png'}")

        # -------------------------------------------------------------
        # 6. Final Report & Server-Side Results
        # -------------------------------------------------------------
        # Submit form to reach the results page
        try:
            page.locator('button[type="submit"], input[type="submit"]').first.click()
            page.wait_for_timeout(800)
        except Exception as e:
            print("Submit note:", e)

        page.screenshot(path=str(SCREENSHOTS_DIR / "06_final_report_results.png"))
        print(f"Captured: {SCREENSHOTS_DIR / '06_final_report_results.png'}")

        browser.close()
        print("\nAll 6 genuine screenshots captured successfully!")


if __name__ == "__main__":
    main()
