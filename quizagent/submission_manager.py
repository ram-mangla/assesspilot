"\"\"\"Submission management module for quiz attempts\\nHandles start attempt, submission, and results tracking.\"\"\"\nfrom dataclasses import dataclass, field\nfrom typing import Dict, Any, List, Optional\nfrom enum import Enum

class SubmissionStatus(Enum):
    IDLE = "idle"
    START_PENDING = "start_pending"
    START_ACTIVE = "start_active"
    PAUSED = "paused"
    STOPPED = "stopped"
    SUBMISSION_PENDING = "submission_pending"
    SUBMITTING = "submitting"
    SUBMITTED = "submitted"
    RESULTS_AVAILABLE = "results_available"

@dataclass
class SubmissionResult:
    """Result of submission operation."""
    success: bool = False
    submitted: bool = False
    score: Optional[dict] = None  # {earned, total, pct}
    attempt_id: Optional[str] = None
    error: str = ""
    phase: SubmissionStatus = SubmissionStatus.IDLE

@dataclass
class SubmissionManager:
    """Manages quiz attempt start, submission, and results."""
    
    def __init__(self, page, attempt_id: Optional[str] = None):
        self.page = page
        self.attempt_id = attempt_id
        self.submission_preview: Dict[str, Any] = {
            'total_questions': 0,
            'answered': 0,
            'unanswered': 0,
            'flagged': 0,
            'unsaved': 0
        }
    
    async def start_attempt(self) -> SubmissionResult:
        """Start a quiz attempt."""
        result = SubmissionResult(phase=SubmissionStatus.START_PENDING)
        
        try:
            # Look for Start Attempt or Begin Quiz button
            start_btn = await self.page.locator('button:has-text(\"Start Attempt\"), button:has-text(\"Begin Quiz\"), button:has-text(\"Take Quiz\")').first
            
            if await start_btn.count() and await start_btn.is_visible() and await start_btn.is_enabled():
                # Show quiz title and details
                title = await self.page.title()
                result.attempt_id = f"attempt_{int(time.time())}"
                result.attempt_id = f"attempt_{int(time.time())}"
                
                # Record attempt start
                await start_btn.click(timeout=3000)
                
                # Wait for page to process
                await self.page.wait_for_load_state('networkidle', timeout=15000)
                
                result.success = True
                result.phase = SubmissionStatus.START_ACTIVE
            else:
                # Try other start controls
                navs = await self.page.locator('nav button, .nav button, .nav a').all()
                for nav in navs:
                    nav_text = await nav.text_content()
                    if nav_text and any(kw in (nav_text or '').lower() for kw in ['start', 'begin', 'take']):
                        await nav.click(timeout=3000)
                        result.success = True
                        result.phase = SubmissionStatus.START_ACTIVE
                        break
        except Exception as e:
            result.error = str(e)
        
        return result
    
    async def pause_attempt(self) -> SubmissionResult:
        """Pause the current attempt."""
        result = SubmissionResult(phase=SubmissionStatus.PAUSED)
        
        try:
            pause_btn = await self.page.locator('button:has-text(\"Pause\"), button:has-text(\"Pause attempt\")').first
            if await pause_btn.count() and await pause_btn.is_visible() and await pause_btn.is_enabled():
                await pause_btn.click(timeout=3000)
                result.success = True
        except Exception as e:
            result.error = str(e)
        
        return result
    
    async def resume_attempt(self) -> SubmissionResult:
        """Resume a paused attempt."""
        result = SubmissionResult(phase=SubmissionStatus.START_ACTIVE)
        
        try:
            resume_btn = await self.page.locator('button:has-text(\"Resume\"), button:has-text(\"Continue\")').first
            if await resume_btn.count() and await resume_btn.is_visible() and await resume_btn.is_enabled():
                await resume_btn.click(timeout=3000)
                result.success = True
        except Exception as e:
            result.error = str(e)
        
        return result
    
    async def stop_attempt(self) -> SubmissionResult:
        """Stop the current attempt without submitting."""
        result = SubmissionResult(phase=SubmissionStatus.STOPPED)
        
        try:
            # Look for a way to stop without submitting
            # This might be closing a modal or clicking cancel
            stop_options = [
                'button:has-text(\"Cancel\")',
                'button:has-text(\"Close\")',
                'a:has-text(\"Back to quiz\")'
            ]
            
            for pattern in stop_options:
                btn = await self.page.locator(pattern).first
                if await btn.count() and await btn.is_visible() and await btn.is_enabled():
                    await btn.click(timeout=3000)
                    result.success = True
                    break
            
            if not result.success:
                # Try ESC key
                await self.page.keyboard.press('Escape')
                result.success = True
        except Exception as e:
            result.error = str(e)
        
        return result
    
    async def submit_attempt(self, confirm: bool = True) -> SubmissionResult:
        """Submit the quiz attempt."""
        result = SubmissionResult(phase=SubmissionStatus.SUBMISSION_PENDING)
        
        if confirm:
            # Show submission preview first
            preview_result = await self._show_submission_preview()
            if not preview_result:
                result.error = \"User cancelled submission preview\"
                result.phase = SubmissionStatus.IDLE
                return result
        
        try:
            # Look for submit controls
            submit_btn = await self.page.locator('button:has-text(\"Submit all and finish\"), button:has-text(\"Submit Quiz\"), button:has-text(\"Finish attempt\")').first
            
            if await submit_btn.count() and await submit_btn.is_visible() and await submit_btn.is_enabled():
                # Confirm final submission
                if confirm:
                    confirmed = await self.page.evaluate(\"() => confirm('Are you sure you want to submit the quiz?')\")
                    if not confirmed:
                        result.error = \"User cancelled final submission\"
                        result.phase = SubmissionStatus.SUBMISSION_PENDING
                        return result
                
                await submit_btn.click(timeout=5000)
                
                # Wait for submission to process
                await self.page.wait_for_load_state('networkidle', timeout=15000)
                
                result.success = True
                result.submitted = True
                result.phase = SubmissionStatus.SUBMITTED
                
                # Try to capture results
                try:
                    # Look for score display
                    score_elem = await self.page.locator('.score, .grade, [data-score]').first
                    if await score_elem.count() and await score_elem.is_visible():
                        score_text = await score_elem.text_content()
                        result.score = self._parse_score(score_text)
                except Exception:
                    pass
            else:
                # Try other submit patterns
                submit_options = [
                    'input[type=\"submit\"].submit',
                    'button[type=\"submit\"',
                    'a:has-text(\"Submit\")'
                ]
                
                for pattern in submit_options:
                    btn = await self.page.locator(pattern).first
                    if await btn.count() and await btn.is_visible() and await btn.is_enabled():
                        await btn.click(timeout=3000)
                        result.success = True
                        result.submitted = True
                        result.phase = SubmissionStatus.SUBMITTED
                        break
        except Exception as e:
            result.error = str(e)
        
        return result
    
    async def _show_submission_preview(self) -> bool:
        """Show submission preview and get user confirmation."""
        result = True  # Default to showing preview
        
        # Count answered/unanswered questions
        try:
            # Get all questions
            questions = await self.page.locator('.question, .q, .quiz-question').all()
            total = len(questions) if questions else self.submission_preview['total_questions']
            
            if total > 0:
                answered = 0
                unanswered = 0
                flagged = 0
                
                for i in range(total):
                    # Check if question i has an answer
                    q_elem = questions[i] if questions else None
                    if q_elem:
                        # Look for selected answers
                        selected = await q_elem.locator('input:checked, .selected').count()
                        if selected > 0:
                            answered += 1
                        else:
                            unanswered += 1
                
                self.submission_preview = {
                    'total_questions': total,
                    'answered': answered,
                    'unanswered': unanswered,
                    'flagged': flagged,
                    'unsaved': 0  # Will be calculated separately
                }
        except Exception:
            pass
        
        return result  # In automated mode, always show preview
    
    def _parse_score(self, score_text: str) -> Optional[dict]:
        """Parse score from display text."""
        import re
        
        # Pattern: X out of Y
        m = re.search(r'(\d+)\s*(?:out|/)\s*(\d+)', score_text or '')
        if m:
            return {
                'earned': int(m.group(1)),
                'total': int(m.group(2)),
                'pct': round(100 * int(m.group(1)) / int(m.group(2)), 1)
            }
        
        # Pattern: X%
        m = re.search(r'(\d+)\s*%', score_text or '')
        if m and int(m.group(1)) <= 100:
            return {
                'earned': None,
                'total': None,
                'pct': int(m.group(1))
            }
        
        return None
""""