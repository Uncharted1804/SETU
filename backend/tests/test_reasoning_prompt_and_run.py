import pytest
from app.agents.reasoning import ReasoningAgent, _collect, _parse, build_messages
from app.contracts import (
    AgentInvocation,
    Chunk,
    ChunkMetadata,
    Finding,
    ReasoningOutput,
)
from app.mocks.scenarios import FLAGSHIP_CHUNKS, FLAGSHIP_FINDINGS, INJECTED_CHUNK
from app.security.injection import SYSTEM_DATA_RULE, assert_no_unwrapped


def test_build_messages_invariants():
    inv = AgentInvocation(
        agent="reasoning",
        model_id="reasoning-primary",
        model="qwen3:8b",
        prompt_summary="Summarize hydrotest findings",
        inputs={"why": "Review pressure vessel hydrotest results"},
        attempt=1,
    )

    clean_findings = FLAGSHIP_FINDINGS[:2]
    clean_chunks = [Chunk(**c) for c in FLAGSHIP_CHUNKS]
    quarantined = [
        Chunk(
            chunk_id=INJECTED_CHUNK["chunk_id"],
            text=INJECTED_CHUNK["text"],
            distance=0.4,
            metadata=ChunkMetadata(**INJECTED_CHUNK["metadata"]),
        )
    ]

    messages = build_messages(inv, clean_findings, clean_chunks, quarantined)
    assert len(messages) == 2

    # Invariant 3: SYSTEM_DATA_RULE is in system message
    assert messages[0]["role"] == "system"
    assert SYSTEM_DATA_RULE in messages[0]["content"]

    user_content = messages[1]["content"]

    # Invariant 1: No document text in ## TASK region
    task_section = user_content.split("## FINDINGS")[0]
    assert "## TASK" in task_section
    for c in clean_chunks:
        assert c.text not in task_section
    for f in clean_findings:
        assert f["text"] not in task_section

    # Invariant 2: Quarantined text never enters prompt at all
    assert INJECTED_CHUNK["text"] not in user_content
    assert "Total quarantined items: 1" in user_content
    assert INJECTED_CHUNK["chunk_id"] in user_content
    assert "vendor_letter_77.pdf" in user_content

    # Invariant 4: Every clean chunk/finding is wrapped inside appropriate tags
    untrusted_texts = [c.text for c in clean_chunks] + [f["text"] for f in clean_findings]
    assert_no_unwrapped(user_content, untrusted_texts)


def test_build_messages_retry_feedback():
    inv = AgentInvocation(
        agent="reasoning",
        model_id="reasoning-primary",
        model="qwen3:8b",
        prompt_summary="Retry after ungrounded draft",
        inputs={"why": "Re-draft hydrotest approval note"},
        attempt=2,
        feedback="Claim regarding NDT without deviation approval is unsupported by SOP-114.",
    )
    clean_chunks = [Chunk(**c) for c in FLAGSHIP_CHUNKS]
    messages = build_messages(inv, [], clean_chunks, [])
    user_content = messages[1]["content"]

    assert "RETRY FEEDBACK" in user_content
    assert "Claim regarding NDT without deviation approval" in user_content


def test_collect_prior_relays():
    inputs = {
        "why": "Test relay",
        "prior": [
            {
                "target": "vision",
                "ok": True,
                "summary": "2 findings",
                "payload": {"findings": FLAGSHIP_FINDINGS[:2]},
            },
            {
                "target": "kb_search",
                "ok": True,
                "summary": "1 chunk, 1 quarantined",
                "payload": {
                    "chunks": FLAGSHIP_CHUNKS[:1],
                    "quarantined": [INJECTED_CHUNK],
                },
            },
        ],
    }

    findings, chunks, quarantined = _collect(inputs)
    assert len(findings) == 2
    assert len(chunks) == 1
    assert chunks[0].chunk_id == FLAGSHIP_CHUNKS[0]["chunk_id"]
    assert len(quarantined) == 1
    assert quarantined[0].chunk_id == INJECTED_CHUNK["chunk_id"]


@pytest.mark.asyncio
async def test_reasoning_agent_run_mock_client():
    from app.config import get_registry, get_settings
    from app.agents.base import AgentContext
    from app.mocks.scenarios import APPROVAL_NOTE_BODY

    settings = get_settings()
    registry = get_registry()
    ctx = AgentContext(settings, registry)

    agent = ReasoningAgent(ctx)

    # Fake client simulating Ollama response with high self-reported confidence
    class FakeClient:
        async def ensure_model(self, model: str):
            pass

        async def chat(self, model, messages, **kwargs):
            return {
                "message": {
                    "content": {
                        "content": APPROVAL_NOTE_BODY,
                        "grounded": True,
                        "citations": [],
                        "unsupported_claims": [],
                        "confidence": 0.95,
                    }
                }
            }

    ctx.client = lambda: FakeClient()

    inv = AgentInvocation(
        agent="reasoning",
        model_id="reasoning-primary",
        model="qwen3:8b",
        prompt_summary="Draft note",
        inputs={
            "why": "Draft note",
            "prior": [
                {"target": "kb_search", "payload": {"chunks": FLAGSHIP_CHUNKS, "quarantined": []}}
            ],
        },
        attempt=1,
    )

    result = await agent.run(inv)

    assert result.agent == "reasoning"
    # Grounding ratio is 6/7 (~0.857). Self-reported is 0.95.
    # Confidence MUST be min(0.95, 6/7) == 6/7!
    assert pytest.approx(result.final_confidence, 0.01) == 6 / 7
    assert len(result.payload["unsupported_claims"]) == 1
    assert len(result.payload["citations"]) >= 3
    assert len(result.attempts) == 1
    assert result.attempts[0].n == 1
