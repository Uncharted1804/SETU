"""
Reasoning agent.  OWNER: P3.

Job: drafting, summarising, approval notes, plan generation and - critically -
driving the tool loop.  Model: capability "planning" from config/models.yaml
(currently qwen3:8b).  Threshold 0.65, 3 attempts.

Confidence signal: TWO things - the model's self-reported score AND whether the
output is grounded in the retrieved knowledge base.  An ungrounded draft is not
a confident draft no matter what number the model emits.

THE VERIFIER.  After drafting, every substantive claim is checked against the
retrieved chunks.  Claims with no support land in `unsupported_claims` and
render yellow.  It satisfies R10's grounding intent, it is the honest answer to
"what if the model is wrong", and it is the mechanism that catches an injected
claim (security/injection.py defence 4).

What changes on retry: pull more or different KB context, or ask the model to
critique its own first draft before rewriting.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Iterable

from rapidfuzz import fuzz

from ..contracts import (
    AgentInvocation,
    AgentResult,
    Attempt,
    Citation,
    Chunk,
    Finding,
    ReasoningOutput,
)
from ..security.injection import (
    SYSTEM_DATA_RULE,
    build_context_block,
    build_findings_block,
    screen_chunks,
    screen_findings,
)
from .base import AgentContext


def verify(
    draft: str,
    chunks: list[Chunk] | list[dict],
    cutoff: float = 49.0,
) -> tuple[list[Citation], list[str], float]:
    """Sentence-split; rapidfuzz.fuzz.partial_ratio each against every chunk.text.
    Best >= cutoff -> Citation(chunk_id, source_file, page, snippet).
    Below -> unsupported_claims. Third value is supported/total."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", draft or "") if s.strip()]
    if not sentences:
        return [], [], 1.0

    citations: list[Citation] = []
    unsupported_claims: list[str] = []

    for sent in sentences:
        best_score = -1.0
        best_chunk: Any = None
        for c in chunks:
            c_text = c.get("text", "") if isinstance(c, dict) else getattr(c, "text", "")
            score = fuzz.partial_ratio(sent, c_text)
            if score > best_score:
                best_score = score
                best_chunk = c

        if best_score >= cutoff and best_chunk is not None:
            if isinstance(best_chunk, dict):
                chunk_id = best_chunk.get("chunk_id", "unknown")
                meta = best_chunk.get("metadata", {})
                source_file = meta.get("source_file", "unknown") if isinstance(meta, dict) else "unknown"
                page = max(1, int(meta.get("page", 1) if isinstance(meta, dict) else 1))
            else:
                chunk_id = getattr(best_chunk, "chunk_id", "unknown")
                meta = getattr(best_chunk, "metadata", None)
                source_file = getattr(meta, "source_file", "unknown") if meta else "unknown"
                page = max(1, int(getattr(meta, "page", 1) if meta else 1))

            citations.append(
                Citation(
                    chunk_id=chunk_id,
                    source_file=source_file,
                    page=page,
                    snippet=sent[:160],
                )
            )
        else:
            unsupported_claims.append(sent)

    ratio = len(citations) / len(sentences)
    return citations, unsupported_claims, ratio


def _collect(inputs: dict) -> tuple[list[dict], list[Chunk], list[Chunk]]:
    """Walk inputs['prior']: payload['findings'] where target=='vision';
    payload['chunks'] / ['quarantined'] where target=='kb_search'.
    Validate through Finding(**f), tolerating malformed entries."""
    findings: list[dict] = []
    chunks: list[Chunk] = []
    quarantined: list[Chunk] = []

    priors = inputs.get("prior", []) if isinstance(inputs, dict) else []
    for item in priors:
        if not isinstance(item, dict):
            continue
        target = item.get("target")
        payload = item.get("payload", {})
        if not isinstance(payload, dict):
            continue

        if target == "vision":
            raw_findings = payload.get("findings", [])
            if isinstance(raw_findings, list):
                for f in raw_findings:
                    if isinstance(f, dict):
                        try:
                            valid_f = Finding(**f)
                            findings.append(valid_f.model_dump())
                        except Exception:
                            findings.append(f)
                    elif hasattr(f, "model_dump"):
                        findings.append(f.model_dump())

        elif target == "kb_search":
            raw_chunks = payload.get("chunks", [])
            if isinstance(raw_chunks, list):
                for c in raw_chunks:
                    try:
                        chunks.append(c if isinstance(c, Chunk) else Chunk(**c))
                    except Exception:
                        pass

            raw_quarantined = payload.get("quarantined", [])
            if isinstance(raw_quarantined, list):
                for q in raw_quarantined:
                    try:
                        quarantined.append(q if isinstance(q, Chunk) else Chunk(**q))
                    except Exception:
                        pass

    if not findings and "findings" in inputs:
        for f in inputs["findings"]:
            findings.append(f if isinstance(f, dict) else f.model_dump())
    if not chunks and "chunks" in inputs:
        for c in inputs["chunks"]:
            chunks.append(c if isinstance(c, Chunk) else Chunk(**c))
    if not quarantined and "quarantined" in inputs:
        for q in inputs["quarantined"]:
            quarantined.append(q if isinstance(q, Chunk) else Chunk(**q))

    return findings, chunks, quarantined


def build_messages(
    inv: AgentInvocation,
    clean_findings: list[dict],
    clean_chunks: list[Chunk],
    quarantined: list[Chunk | dict],
) -> list[dict[str, str]]:
    """Three-region structure: TASK trusted / FINDINGS untrusted / CONTEXT untrusted / QUARANTINED counts only."""
    system_message = (
        "You are SETU's sovereign reasoning agent. Your role is grounded drafting, summarizing, "
        "and approval note generation.\n\n"
        f"{SYSTEM_DATA_RULE}\n\n"
        "Cite chunk_id for every factual claim. Ground every statement in the provided context and findings."
    )

    task_desc = inv.inputs.get("why") or inv.prompt_summary or "Draft reasoning deliverable grounded in context."
    if inv.attempt >= 2 and inv.feedback:
        task_desc += (
            f"\n\n[RETRY FEEDBACK]: Address the following critique from the previous attempt:\n{inv.feedback}"
        )

    if clean_findings:
        findings_block = build_findings_block(clean_findings)
    else:
        findings_block = "No extracted document findings provided."

    if clean_chunks:
        context_block = build_context_block(clean_chunks)
    else:
        context_block = "No knowledge base context retrieved."

    if quarantined:
        q_lines = [f"Total quarantined items: {len(quarantined)}"]
        for q in quarantined:
            if isinstance(q, dict):
                meta = q.get("metadata", {})
                sf = meta.get("source_file") or q.get("source_file", "unknown")
                p = meta.get("page") or q.get("page", "unknown")
                cid = q.get("chunk_id", "unknown")
            else:
                meta = getattr(q, "metadata", None)
                sf = getattr(meta, "source_file", "unknown") if meta else "unknown"
                p = getattr(meta, "page", "unknown") if meta else "unknown"
                cid = getattr(q, "chunk_id", "unknown")
            q_lines.append(f"- Quarantined chunk {cid} from {sf}, page {p} (flagged for prompt injection)")
        quarantined_block = "\n".join(q_lines)
    else:
        quarantined_block = "Total quarantined items: 0"

    user_message = (
        f"## TASK\n{task_desc}\n\n"
        f"## FINDINGS\n{findings_block}\n\n"
        f"## CONTEXT\n{context_block}\n\n"
        f"## QUARANTINED\n{quarantined_block}"
    )

    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message},
    ]


def _parse(raw: dict) -> tuple[str, float]:
    """Extract drafted text and self-reported confidence from Ollama chat response."""
    msg = raw.get("message", {}) if isinstance(raw, dict) else {}
    content = msg.get("content", "")
    if isinstance(content, dict):
        draft = content.get("content", "")
        self_conf = float(content.get("confidence", 0.8))
        return str(draft), self_conf
    if isinstance(content, str):
        content_str = content.strip()
        try:
            parsed = json.loads(content_str)
            if isinstance(parsed, dict):
                draft = parsed.get("content", content_str)
                self_conf = float(parsed.get("confidence", 0.8))
                return str(draft), self_conf
        except Exception:
            pass
        return content_str, 0.8
    return str(content), 0.8


class ReasoningAgent:
    name = "reasoning"

    def __init__(self, ctx: AgentContext) -> None:
        self.ctx = ctx

    async def run(self, inv: AgentInvocation) -> AgentResult:
        entry = self.ctx.model_for("reasoning")
        client = self.ctx.client()
        await client.ensure_model(entry.model)

        t0 = time.perf_counter()
        findings, chunks, quarantined = _collect(inv.inputs)
        clean_chunks, dirty_chunks = screen_chunks(chunks)
        clean_findings, flagged_findings = screen_findings(findings)

        all_quarantined = quarantined + dirty_chunks + flagged_findings
        messages = build_messages(inv, clean_findings, clean_chunks, all_quarantined)

        raw = await client.chat(
            entry.model,
            messages,
            options={
                "temperature": entry.temperature,
                "num_predict": entry.max_output_tokens,
            },
            keep_alive=entry.keep_alive,
            format_schema=ReasoningOutput.model_json_schema(),
        )
        duration_ms = (time.perf_counter() - t0) * 1000.0

        draft_text, self_conf = _parse(raw)
        citations, unsupported, ratio = verify(draft_text, clean_chunks)
        confidence = min(self_conf, ratio)

        grounded = len(unsupported) == 0 and ratio >= 0.65
        out = ReasoningOutput(
            content=draft_text,
            grounded=grounded,
            citations=citations,
            unsupported_claims=unsupported,
            confidence=confidence,
        )

        summary_text = (
            f"Approval note drafted, {len(citations)} citations, "
            f"{len(unsupported)} unsupported claim(s)"
        )
        payload = out.model_dump()
        payload["_summary"] = summary_text

        attempt = Attempt(
            n=inv.attempt,
            confidence=confidence,
            feedback_injected=inv.feedback,
            duration_ms=duration_ms,
        )

        needs_review = confidence < 0.65 or len(unsupported) > 0
        escalation = (
            f"{len(unsupported)} ungrounded claim(s) require human review"
            if len(unsupported) > 0 else None
        )

        return AgentResult(
            agent="reasoning",
            model=entry.model,
            payload=payload,
            attempts=[attempt],
            final_confidence=confidence,
            needs_human_review=needs_review,
            escalation_reason=escalation,
        )
