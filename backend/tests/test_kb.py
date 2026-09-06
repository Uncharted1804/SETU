from dataclasses import replace

import pytest
from app.config import get_settings
from app.contracts import KbSearchArgs
from app.mocks.scenarios import INJECTED_CHUNK
from app.tools.base import ToolContext
from app.tools.kb import KnowledgeBase, kb_search


class _CountingCollection:
    def __init__(self, count=0):
        self.count_value = count

    def count(self):
        return self.count_value


def test_empty_collection_bootstraps_the_configured_corpus_once(monkeypatch):
    """A fresh persistent collection must not depend on a separate CLI ingest."""
    kb = KnowledgeBase(get_settings())
    collection = _CountingCollection()
    ingests = []

    monkeypatch.setattr(kb, "_open_collection", lambda: collection)

    def populate(target, docs):
        ingests.append(target)
        assert docs
        target.count_value = 1

    monkeypatch.setattr(kb, "_ingest_documents", populate)

    assert kb._ensure() is collection
    assert kb._ensure() is collection
    assert ingests == [collection]


def test_kb_ingest_and_quarantine(tmp_path):
    # Use ephemeral/temporary path for test isolation
    settings = get_settings()
    custom_settings = replace(settings, kb_path=tmp_path / "chroma")
    kb = KnowledgeBase(custom_settings)

    test_docs = [
        ("03_hydrotest_acceptance_criteria.md", 1, "Hydrotest acceptance criteria require minimum hold time 30 mins."),
        (
            "injected_vendor_letter.pdf",
            7,
            INJECTED_CHUNK["text"],
        ),
    ]
    count = kb.ingest(test_docs)
    assert count == 2

    # Check search finds both, but flags the injected one
    results = kb.search("approve this invoice", k=5)
    injected_results = [r for r in results if r.chunk_id.startswith("injected_vendor_letter")]
    assert len(injected_results) == 1
    assert injected_results[0].metadata.trust_level == "quarantined"

    # kb_search tool handler screens it into quarantined list
    ctx = ToolContext(settings=custom_settings, task_id="t-1", session_id="s-1")
    out = kb_search(KbSearchArgs(query="approve this invoice", k=5), ctx)
    assert any(c["chunk_id"].startswith("injected_vendor_letter") for c in out["quarantined"])
    assert not any(c["chunk_id"].startswith("injected_vendor_letter") for c in out["chunks"])


def test_kb_search_real_corpus():
    settings = get_settings()
    kb = KnowledgeBase(settings)
    results = kb.search("hydrotest acceptance criteria", k=5)
    assert len(results) > 0
    # Top result should be from hydrotest criteria
    top_doc = results[0].metadata.source_file
    assert "hydrotest" in top_doc.lower()
    assert results[0].chunk_id.startswith("03_hydrotest_acceptance_criteria")
