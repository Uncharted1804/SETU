"""Focused, in-memory coverage for the P4 upload active-content scanner."""

from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from app.security.upload_scan import scan_upload


def _ooxml(*entries: str) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        for entry in entries:
            archive.writestr(entry, b"<xml/>")
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("report.docx", _ooxml("[Content_Types].xml", "word/document.xml")),
        ("readings.xlsx", _ooxml("[Content_Types].xml", "xl/workbook.xml")),
        ("scan.pdf", b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"),
        ("photo.png", b"\x89PNG\r\n\x1a\nclean"),
        ("notes.txt", b"ordinary text\n"),
        ("readings.csv", b"reading,status\n12.3,ok\n"),
    ],
)
def test_clean_supported_documents_and_images_are_allowed(name, content):
    result = scan_upload(name, content)

    assert result.allowed is True
    assert result.reason.startswith("allowed:")


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("macro.docx", _ooxml("[Content_Types].xml", "word/document.xml", "word/vbaProject.bin")),
        ("macro.xlsx", _ooxml("[Content_Types].xml", "xl/workbook.xml", "xl/vbaProject.bin")),
    ],
)
def test_macro_enabled_office_content_is_blocked(name, content):
    result = scan_upload(name, content)

    assert result.allowed is False
    assert "macro" in result.reason.lower()


@pytest.mark.parametrize(
    "marker", [b"/JavaScript", b"/JS", b"/Launch", b"/OpenAction", b"/AA", b"/EmbeddedFiles"]
)
def test_active_pdf_markers_are_blocked(marker):
    result = scan_upload("active.pdf", b"%PDF-1.7\n1 0 obj\n<< " + marker + b" >>\nendobj")

    assert result.allowed is False
    assert "blocked:" in result.reason


def test_extension_signature_mismatch_is_blocked():
    result = scan_upload("scan.png", b"%PDF-1.4\n%%EOF")

    assert result.allowed is False
    assert "does not match file signature" in result.reason


def test_executable_masquerade_is_blocked_even_with_a_document_extension():
    result = scan_upload("invoice.pdf", b"MZ\x90\x00")

    assert result.allowed is False
    assert "executable" in result.reason


@pytest.mark.parametrize("name", ["calculation.py", "briefing.pptx", "archive.zip", "page.html", "diagram.svg", "data.xml"])
def test_non_v1_attachment_types_are_rejected(name):
    result = scan_upload(name, b"print(2 + 2)\n")

    assert result.allowed is False
    assert "unsupported attachment type" in result.reason
