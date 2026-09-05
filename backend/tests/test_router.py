"""
Router decision tests.  OWNER: P1.

The router picks the ENTRY agent only, resolves model tags from
config/models.yaml, and never hardcodes a tag string.
"""

from __future__ import annotations

import pytest

from app.config import get_registry
from app.contracts import TaskEnvelope
from app.router import route_task


@pytest.fixture()
def registry(env):
    return get_registry()


def _task(text: str, files: list[str] | None = None) -> TaskEnvelope:
    return TaskEnvelope(session_id="s_1", task_id="t_1", text=text, file_paths=files or [])


def test_pdf_routes_to_vision(registry):
    d = route_task(_task("draft an approval note", ["uploads/scan.pdf"]), registry)
    assert d.agent == "vision"
    assert d.rule_id == "R1_FILE_EXT"
    assert d.matched_signal == "pdf"


@pytest.mark.parametrize("ext", ["png", "jpg", "jpeg", "tiff", "webp"])
def test_image_extensions_route_to_vision(registry, ext):
    d = route_task(_task("what is this", ["uploads/a." + ext]), registry)
    assert d.agent == "vision"


def test_xlsx_routes_to_reasoning_entry(registry):
    d = route_task(_task("check these against spec", ["uploads/sensor.xlsx"]), registry)
    assert d.agent == "reasoning"
    assert d.rule_id == "R2_SHEET_EXT"


def test_code_signal_routes_to_coding(registry):
    d = route_task(_task("here is a traceback, fix this code"), registry)
    assert d.agent == "coding"
    assert d.rule_id == "R3_CODE_SIGNAL"


def test_deliverable_signal_routes_to_reasoning(registry):
    d = route_task(_task("make me a word document summarising this"), registry)
    assert d.agent == "reasoning"
    assert d.rule_id == "R4_DELIVERABLE"


def test_default_is_reasoning(registry):
    d = route_task(_task("what were the main points of yesterday's meeting"), registry)
    assert d.agent == "reasoning"
    assert d.rule_id == "R0_DEFAULT"
    assert d.matched_signal is None


def test_mixed_attachments_are_deterministic_and_vision_wins(registry):
    """D-004: a page image cannot be read by any other agent; a workbook is
    reachable later through sheet_op inside the loop."""
    a = route_task(_task("compare these", ["uploads/a.xlsx", "uploads/b.pdf"]), registry)
    b = route_task(_task("compare these", ["uploads/b.pdf", "uploads/a.xlsx"]), registry)
    assert a.agent == b.agent == "vision"
    assert a.rule_id == b.rule_id == "R1_FILE_EXT"


def test_attachment_beats_a_text_signal(registry):
    d = route_task(_task("fix this code please", ["uploads/scan.pdf"]), registry)
    assert d.agent == "vision"


def test_model_tags_come_from_the_registry_not_the_router(registry):
    """The router must never contain a literal model tag.  This asserts the
    resolved tag matches whatever config/models.yaml currently says."""
    for text, files, capability in [
        ("hello", ["a.pdf"], "vision"),
        ("hello", [], "planning"),
        ("fix this code", [], "code"),
    ]:
        d = route_task(_task(text, files), registry)
        assert d.model == registry.resolve(capability).model
        assert d.model_id == registry.resolve(capability).id


def test_router_source_contains_no_hardcoded_model_tag():
    import pathlib

    source = (pathlib.Path(__file__).resolve().parent.parent / "app" / "router.py").read_text(
        encoding="utf-8"
    )
    code = "\n".join(
        line for line in source.splitlines()
        if not line.strip().startswith("#")
    )
    for tag in ("qwen", "llama", "granite", "mistral"):
        assert tag not in code.lower(), "router.py must resolve tags from the registry"


def test_latency_is_recorded(registry):
    d = route_task(_task("hello"), registry)
    assert d.latency_ms >= 0.0
    assert d.reason  # rendered in the UI banner
