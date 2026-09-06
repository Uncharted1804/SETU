"""
The entry router.  OWNER: P1.

It answers exactly ONE question, before anything expensive runs: which agent
handles the ENTRY point of this task?  It does not plan, it does not pick step
two, and it never calls a model to decide which model to call.

The orchestrator chains everything after the entry point.  "I have findings, so
now I need to draft" is a decision made in the loop from what came back - not
here.  That sentence is the answer to the judge question P1 owns.

MODEL TAGS ARE NOT IN THIS FILE.  Rules resolve a CAPABILITY; the capability is
turned into a tag by config.ModelRegistry, reading config/models.yaml.  This is
the blueprint's requirement R5 and the explicit warning appended to the
blueprint's own router pseudocode (section 2.3).

ATTACHMENT PRECEDENCE (deterministic, including mixed attachments).  The
blueprint lists file-extension rules before text rules but does not say what
happens when a PDF and an XLSX arrive together.  Decision D-004: VISION WINS.
A page image cannot be read by any other agent, whereas a workbook is reachable
later via sheet_op inside the loop.  Precedence, highest first:

    1. any vision-capable extension present        -> vision
    2. else any spreadsheet extension present      -> reasoning (spreadsheet task)
    3. else a code signal in the text              -> coding
    4. else a deliverable signal in the text       -> reasoning
    5. else                                        -> reasoning (default)

Within rule 1 and 2 the FIRST matching attachment in the submitted order is
reported as `matched_signal`, so the decision is reproducible from the request.
"""

from __future__ import annotations

import re
import time
from typing import Optional

from .config import CODE_SIGNALS, DOC_SIGNALS, SHEET_EXTS, VISION_EXTS, ModelRegistry
from .contracts import RouterDecision, TaskEnvelope


def _ext(path: str) -> str:
    return path.rsplit(".", 1)[-1].lower() if "." in path else ""


def _first_signal(text: str, signals: tuple[str, ...]) -> Optional[str]:
    """First signal (in order) present in `text`, or None.

    A plain word/phrase ("code", "write a program") is matched on word
    boundaries so it fires on "write a c code" without also firing on
    "encode"/"decode"/"programme". A signal carrying punctuation (".py",
    "c++", "c#", "error:", "print(") is matched as a literal substring
    instead - boundary matching corrupts a pattern built from those
    characters, and each is already distinctive enough on its own.
    """
    for sig in signals:
        core = sig.strip()
        if not core:
            continue
        if re.search(r"[^\w\s]", core):
            if core in text:
                return sig
        elif re.search(r"\b" + re.escape(core) + r"\b", text):
            return sig
    return None


def _decide(
    registry: ModelRegistry,
    agent: str,
    capability: str,
    reason: str,
    rule_id: str,
    matched: Optional[str],
    t0: float,
) -> RouterDecision:
    entry = registry.resolve(capability)
    return RouterDecision(
        agent=agent,  # type: ignore[arg-type]
        model=entry.model,
        model_id=entry.id,
        capability=capability,  # type: ignore[arg-type]
        reason=reason,
        rule_id=rule_id,
        matched_signal=matched,
        latency_ms=round((time.perf_counter() - t0) * 1000, 3),
    )


def route_task(task: TaskEnvelope, registry: ModelRegistry) -> RouterDecision:
    """Rule-based entry routing.  Cheap, instant, and fully explainable."""
    t0 = time.perf_counter()
    text = (task.text or "").lower()

    # Rule 1 - a page image or PDF is present.  Highest precedence (D-004).
    for path in task.file_paths:
        ext = _ext(path)
        if ext in VISION_EXTS:
            return _decide(
                registry,
                "vision",
                "vision",
                "%s attached - page requires visual extraction" % ext,
                "R1_FILE_EXT",
                ext,
                t0,
            )

    # Rule 2 - a workbook is present.  Reasoning is the entry point; the loop
    # reaches the data through sheet_op, which is a TOOL, not an agent.
    for path in task.file_paths:
        ext = _ext(path)
        if ext in SHEET_EXTS:
            return _decide(
                registry,
                "reasoning",
                "planning",
                "%s attached - spreadsheet task, entry via planning" % ext,
                "R2_SHEET_EXT",
                ext,
                t0,
            )

    # Rule 3 - code-flavoured signals in the free text.
    code_sig = _first_signal(text, CODE_SIGNALS)
    if code_sig is not None:
        return _decide(
            registry,
            "coding",
            "code",
            "code signal: %r - requires executable computation" % code_sig,
            "R3_CODE_SIGNAL",
            code_sig,
            t0,
        )

    # Rule 4 - an explicit deliverable was requested.
    doc_sig = _first_signal(text, DOC_SIGNALS)
    if doc_sig is not None:
        return _decide(
            registry,
            "reasoning",
            "planning",
            "deliverable requested: %r" % doc_sig,
            "R4_DELIVERABLE",
            doc_sig,
            t0,
        )

    # Default.
    return _decide(
        registry,
        "reasoning",
        "planning",
        "no specific signal - general reasoning with retrieval grounding",
        "R0_DEFAULT",
        None,
        t0,
    )
