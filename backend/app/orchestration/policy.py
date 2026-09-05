"""
Confidence, retry and escalation policy.  OWNER: P1.

ONE place decides whether an agent result is good enough, whether to retry, what
feedback to inject, and when to stop and ask a human.  All three agents obey it,
which is why a fourth agent inherits the behaviour for free.

THE COUNTING RULES, stated once (contracts.py convention 5):

  * `Attempt.n` is per STEP and 1-indexed.  It is bounded by
    MAX_ATTEMPTS[agent]: vision 3, reasoning 3, coding 4.
  * An ITERATION is one dispatched step.  It is bounded by MAX_ITERATIONS = 5.
  * Retrying a step consumes an ATTEMPT, not an ITERATION.  Three vision
    attempts are one iteration.

Coding gets the extra attempt because its failure signal is objective: a
traceback tells the model precisely what to fix, so a retry there has the
highest expected value in the system.  That asymmetry is a decision, not an
accident.

CODING CONFIDENCE IN REAL MODE reflects actual execution status - exit_code 0
gives 1.0 and nothing else does, enforced by the CodingOutput contract itself.
A zero exit code is evidence the program RAN.  It is not proof that the logic is
correct, and no part of the system claims otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..config import MAX_ATTEMPTS, MAX_ITERATIONS, THRESHOLDS
from ..contracts import AgentResult, Attempt


@dataclass(frozen=True)
class RetryDecision:
    retry: bool
    escalate: bool
    reason: str
    feedback: Optional[str] = None


def threshold_for(agent: str) -> float:
    return THRESHOLDS[agent]


def max_attempts_for(agent: str) -> int:
    return MAX_ATTEMPTS[agent]


def passes(agent: str, confidence: float) -> bool:
    return confidence >= THRESHOLDS[agent]


def failure_reason(agent: str, result: AgentResult) -> str:
    """The specific reason, for the feedback that makes a retry worth doing."""
    if result.error is not None:
        return "%s: %s" % (result.error.code, result.error.message)
    if result.attempts and result.attempts[-1].failure_reason:
        return result.attempts[-1].failure_reason  # type: ignore[return-value]
    if agent == "coding":
        payload = result.payload or {}
        stderr = (payload.get("stderr") or "").strip()
        if stderr:
            return "sandbox exit code %s\n%s" % (payload.get("exit_code"), stderr[:1200])
        return "sandbox reported a non-zero exit code"
    return "confidence %.2f is below the %s threshold of %.2f" % (
        result.final_confidence, agent, THRESHOLDS[agent],
    )


def build_feedback(agent: str, result: AgentResult) -> str:
    """A retry that re-asks the same question gets the same wrong answer.

    Every retry prompt carries what went wrong last time; the string returned
    here is recorded verbatim in Attempt.feedback_injected so the UI can show
    "attempt 2/4 - feeding traceback" and mean it.
    """
    reason = failure_reason(agent, result)
    if agent == "coding":
        return (
            "Your previous script failed in the sandbox. Fix the specific error "
            "below; do not resubmit the same code.\n\n" + reason
        )
    if agent == "vision":
        return (
            "Your previous extraction was below the confidence threshold. "
            "Re-examine only the low-confidence region rather than the whole page.\n\n"
            + reason
        )
    return (
        "Your previous answer was below the grounding/confidence threshold. "
        "Retrieve additional context and address the gap below directly.\n\n" + reason
    )


def evaluate(agent: str, result: AgentResult, attempt: int) -> RetryDecision:
    """The escalation sequence from blueprint 2.7, in code.

    attempt >= threshold                 -> done
    below threshold, attempts remain     -> retry WITH feedback
    below threshold, attempts exhausted  -> escalate (needs_human_review)
    """
    limit = max_attempts_for(agent)
    if result.error is not None and result.error.code == "NOT_IMPLEMENTED":
        return RetryDecision(
            retry=False, escalate=True,
            reason=result.error.message,
        )
    if passes(agent, result.final_confidence):
        return RetryDecision(
            retry=False, escalate=False,
            reason="confidence %.2f >= threshold %.2f" % (result.final_confidence, THRESHOLDS[agent]),
        )
    if attempt < limit:
        return RetryDecision(
            retry=True, escalate=False,
            reason="attempt %d/%d below threshold" % (attempt, limit),
            feedback=build_feedback(agent, result),
        )
    return RetryDecision(
        retry=False, escalate=True,
        reason="all %d attempts below the %s threshold of %.2f; flagged for human review"
        % (limit, agent, THRESHOLDS[agent]),
    )


def iteration_budget() -> int:
    return MAX_ITERATIONS


def cap_reached(iterations_used: int) -> bool:
    return iterations_used >= MAX_ITERATIONS


def cap_message(iterations_used: int) -> str:
    """Reaching the cap is NOT success.  The task ends needs_human_review and the
    summary says why - a truncated run reported as `completed` is the single
    easiest way to lose a judge's trust."""
    return (
        "iteration cap reached: %d of %d dispatched steps used without the plan "
        "reporting satisfaction. The task was stopped and flagged for human "
        "review rather than reported as complete." % (iterations_used, MAX_ITERATIONS)
    )


def attempt_record(n: int, result: AgentResult, feedback: Optional[str]) -> Attempt:
    """Normalise whatever the agent reported into one auditable Attempt row."""
    if result.attempts:
        base = result.attempts[-1]
        return Attempt(
            n=n,
            confidence=base.confidence,
            failure_reason=base.failure_reason,
            feedback_injected=feedback,
            duration_ms=base.duration_ms,
        )
    return Attempt(n=n, confidence=result.final_confidence, feedback_injected=feedback)
