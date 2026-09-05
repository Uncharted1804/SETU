"""Bounded, dependency-free active-content screening for incoming uploads.

This is deliberately a byte-level pre-staging check, not malware detection and
not a document parser.  It performs no network I/O, never executes content, and
does not extract archive members to disk.  P1 may call :func:`scan_upload`
before an upload is materialized in a task workspace.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath
from zipfile import BadZipFile, ZipFile


# Matches the current route-level cap without importing P1's API module.
MAX_SCAN_BYTES = 32 * 1024 * 1024
MAX_ZIP_ENTRIES = 512


@dataclass(frozen=True)
class UploadScanResult:
    """A UI-safe decision P1 can render without translating scanner internals."""

    allowed: bool
    reason: str
    detected_type: str


_IMAGE_SIGNATURES = {
    ".png": (b"\x89PNG\r\n\x1a\n", "PNG image"),
    ".jpg": (b"\xff\xd8\xff", "JPEG image"),
    ".jpeg": (b"\xff\xd8\xff", "JPEG image"),
}
_INERT_TEXT_EXTENSIONS = {".txt", ".csv"}
_REJECTED_ATTACHMENT_EXTENSIONS = {
    ".doc", ".docb", ".docm", ".dotm", ".xls", ".xlsb", ".xlsm", ".xlam",
    ".ppt", ".pptx", ".pptm", ".potm", ".ppsm", ".rtf", ".html", ".htm", ".hta",
    ".svg", ".xml", ".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz",
    ".py", ".pyw", ".js", ".mjs", ".ts", ".sh", ".ps1", ".bat", ".cmd",
    ".rb", ".php", ".pl", ".exe", ".msi",
}
_EXECUTABLE_SIGNATURES = (
    (b"MZ", "Windows executable"),
    (b"\x7fELF", "ELF executable"),
    (b"\xfe\xed\xfa\xce", "Mach-O executable"),
    (b"\xcf\xfa\xed\xfe", "Mach-O executable"),
)
_PDF_ACTIVE_MARKERS = (
    (b"/JavaScript", "PDF JavaScript action"),
    (b"/JS", "PDF JavaScript action"),
    (b"/Launch", "PDF launch action"),
    (b"/OpenAction", "PDF open action"),
    (b"/AA", "PDF additional action"),
    (b"/EmbeddedFiles", "PDF embedded-file action"),
    (b"/EmbeddedFile", "PDF embedded-file action"),
    (b"/GoToE", "PDF embedded-file action"),
)


def _allow(reason: str, detected_type: str) -> UploadScanResult:
    return UploadScanResult(True, reason, detected_type)


def _block(reason: str, detected_type: str = "unknown") -> UploadScanResult:
    return UploadScanResult(False, reason, detected_type)


def _signature(data: bytes) -> str:
    for magic, label in _EXECUTABLE_SIGNATURES:
        if data.startswith(magic):
            return label
    if data.startswith(b"%PDF-"):
        return "PDF document"
    if data.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return "ZIP archive"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG image"
    if data.startswith(b"\xff\xd8\xff"):
        return "JPEG image"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "GIF image"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "WebP image"
    return "unknown"


def _scan_ooxml(data: bytes, extension: str) -> UploadScanResult:
    """Read only bounded ZIP central-directory names; never extract members."""
    try:
        with ZipFile(BytesIO(data)) as archive:
            entries = archive.infolist()
    except BadZipFile:
        return _block("blocked: invalid ZIP container for %s" % extension, "ZIP archive")
    if len(entries) > MAX_ZIP_ENTRIES:
        return _block("blocked: ZIP archive has too many entries to inspect safely", "ZIP archive")

    names = {entry.filename.replace("\\", "/").lower() for entry in entries}
    if any(PurePath(name).name.lower() == "vbaproject.bin" for name in names):
        return _block("blocked: Office macro content (vbaProject.bin) detected", "OOXML document")

    required_prefix = {".docx": "word/", ".xlsx": "xl/"}[extension]
    if not any(name.startswith(required_prefix) for name in names):
        return _block(
            "blocked: extension %s does not match the OOXML package contents" % extension,
            "ZIP archive",
        )
    return _allow("allowed: clean %s OOXML package" % extension, "OOXML document")


def _scan_pdf(data: bytes) -> UploadScanResult:
    for marker, reason in _PDF_ACTIVE_MARKERS:
        if marker in data:
            return _block("blocked: " + reason, "PDF document")
    return _allow("allowed: PDF has no obvious active-content markers", "PDF document")


def scan_upload(filename: str, content: bytes) -> UploadScanResult:
    """Screen one already-bounded upload without writing, extracting, or running it.

    Callers should pass the original client filename and the exact bytes they
    intend to stage.  Files above ``MAX_SCAN_BYTES`` are rejected so ZIP metadata
    inspection is never unbounded even when this function is used independently
    of P1's route-level upload cap.
    """
    if not isinstance(content, bytes):
        return _block("blocked: upload content must be bytes")
    if len(content) > MAX_SCAN_BYTES:
        return _block("blocked: upload exceeds scanner limit of %d bytes" % MAX_SCAN_BYTES)

    extension = PurePath(filename or "").suffix.lower()
    detected = _signature(content)
    if detected.endswith("executable"):
        return _block("blocked: executable/binary signature detected (%s)" % detected, detected)
    if extension in _REJECTED_ATTACHMENT_EXTENSIONS:
        return _block("blocked: unsupported attachment type %s" % extension, detected)

    if extension in {".docx", ".xlsx"}:
        if detected != "ZIP archive":
            return _block(
                "blocked: extension %s does not match file signature (%s)" % (extension, detected),
                detected,
            )
        return _scan_ooxml(content, extension)

    if extension == ".pdf":
        if detected != "PDF document":
            return _block(
                "blocked: extension .pdf does not match file signature (%s)" % detected,
                detected,
            )
        return _scan_pdf(content)

    if extension in _IMAGE_SIGNATURES:
        magic, expected = _IMAGE_SIGNATURES[extension]
        valid = content.startswith(magic)
        if not valid:
            return _block(
                "blocked: extension %s does not match file signature (%s)" % (extension, detected),
                detected,
            )
        return _allow("allowed: %s signature matches extension" % expected, expected)

    if extension in _INERT_TEXT_EXTENSIONS:
        if detected != "unknown" or b"\x00" in content:
            return _block(
                "blocked: inert text extension %s does not match file content (%s)" % (extension, detected),
                detected,
            )
        return _allow("allowed: inert text attachment", "text")

    return _block("blocked: unsupported upload type %s" % (extension or "<none>"), detected)


__all__ = ["MAX_SCAN_BYTES", "MAX_ZIP_ENTRIES", "UploadScanResult", "scan_upload"]
