import pytest
from app.agents.reasoning import verify
from app.contracts import Chunk
from app.mocks.scenarios import APPROVAL_NOTE_BODY, FLAGSHIP_CHUNKS


def test_verify_flagship_approval_note():
    # Test with list of dicts
    citations, unsupported, ratio = verify(APPROVAL_NOTE_BODY, FLAGSHIP_CHUNKS)

    # Acceptance: exactly 1 unsupported claim
    assert len(unsupported) == 1
    assert "The test is therefore NOT acceptable" in unsupported[0]

    # Acceptance: >= 3 citations
    assert len(citations) >= 3
    cited_chunk_ids = {c.chunk_id for c in citations}
    assert cited_chunk_ids == {"SOP-114#c12", "SC-22#c03", "SOP-114#c19"}

    # Supported ratio
    assert pytest.approx(ratio, 0.01) == 6 / 7


def test_verify_with_chunk_objects():
    chunks = [Chunk(**c) for c in FLAGSHIP_CHUNKS]
    citations, unsupported, ratio = verify(APPROVAL_NOTE_BODY, chunks)

    assert len(unsupported) == 1
    assert len(citations) >= 3
    assert {c.chunk_id for c in citations} == {"SOP-114#c12", "SC-22#c03", "SOP-114#c19"}


def test_verify_empty_and_unsupported():
    # Empty draft
    cits, unsup, ratio = verify("", FLAGSHIP_CHUNKS)
    assert cits == []
    assert unsup == []
    assert ratio == 1.0

    # Completely alien text
    alien_draft = "Quantum computing uses qubits and entanglement."
    cits2, unsup2, ratio2 = verify(alien_draft, FLAGSHIP_CHUNKS)
    assert len(cits2) == 0
    assert len(unsup2) == 1
    assert ratio2 == 0.0
