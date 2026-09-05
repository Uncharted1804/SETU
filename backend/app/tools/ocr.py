"""
The three-tier OCR cascade.  OWNER: P2.

NOT A REGISTERED TOOL.  This is an internal service used by agents/vision.py.
The model-callable surface is exactly seven functions and this is not one of
them - adding it would break the claim in blueprint 12.3 Layer 3.

    Tier 1  PyMuPDF text layer   digital PDFs. Exact, ~50 ms, zero GPU.
    Tier 2  Tesseract            clean scanned print. ~1 s/page, CPU only.
    Tier 3  local vision model   handwriting, drawings, tables, layout, and
                                 anything Tier 2 returns low confidence on.

Do not send everything to the VLM: it is slower, worse on clean print, and a
weaker story.  Each Finding records which tier produced it, so a mixed-tier
extraction can be shown on screen.

P2 TODO, in order.  Acceptance for each is stated so it can be checked by
someone other than P2:
  1. tier1_text_layer()  - acceptance: a digital PDF yields exact text with
     extraction_tier="text_layer" and per-block bboxes in PDF points.
  2. rasterize()         - acceptance: 300 dpi PNG per page, written inside the
     workspace via ctx.resolve, never to a temp dir outside the jail.
  3. tier2_tesseract()   - acceptance: the demo scan yields >= 5 findings with
     word-level confidences; a page with no text layer is detected, not assumed.
  4. preprocess()        - acceptance: on attempt 2, CLAHE + deskew measurably
     raises Tesseract mean confidence on the deliberately blurry demo region.
  5. crop_to_bbox()      - acceptance: retry re-asks about ONE region, not the
     whole page (this is the difference between an informed retry and a blind one).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..contracts import ErrorCode, ExtractionTier, Finding
from .base import ToolError, optional_import

#: Below this mean tier-2 confidence, escalate the region to the vision model.
TESSERACT_ESCALATION_THRESHOLD = 0.75


def has_text_layer(pdf_path: Path) -> bool:
    """Tier-1 gate.  A digital PDF is answered in ~50 ms with zero GPU."""
    fitz = optional_import("pymupdf", owner="P2", purpose="PDF text layer")
    with fitz.open(str(pdf_path)) as doc:
        for page in doc:
            if page.get_text("text").strip():
                return True
    return False


def tier1_text_layer(pdf_path: Path, source_rel: str) -> list[Finding]:
    """NOT IMPLEMENTED - P2.  See the module docstring for acceptance."""
    raise NotImplementedError("P2 owns the OCR cascade (tools/ocr.py tier 1)")


def rasterize(pdf_path: Path, out_dir: Path, dpi: int = 300) -> list[Path]:
    """NOT IMPLEMENTED - P2.  Must write inside the workspace jail."""
    raise NotImplementedError("P2 owns rasterization (tools/ocr.py::rasterize)")


def preprocess(image_path: Path, clahe: bool = True, deskew: bool = True) -> Path:
    """NOT IMPLEMENTED - P2.  OpenCV earns its place on the RETRY, not attempt 1."""
    raise NotImplementedError("P2 owns image preprocessing (tools/ocr.py::preprocess)")


def crop_to_bbox(image_path: Path, bbox: list[float], pad: int = 12) -> Path:
    """NOT IMPLEMENTED - P2.  Retry crops to the low-confidence region."""
    raise NotImplementedError("P2 owns retry cropping (tools/ocr.py::crop_to_bbox)")


def tier2_tesseract(image_path: Path, source_rel: str, page: int) -> list[Finding]:
    """NOT IMPLEMENTED - P2.

    The wrapper is `pytesseract`; the Tesseract BINARY is installed separately
    and vendored under vendor/installers + vendor/tessdata.  If the binary is
    absent this must raise a clear ToolError, never fall back to the VLM
    silently - a silent fallback hides the cascade the demo is meant to show.
    """
    raise NotImplementedError("P2 owns the OCR cascade (tools/ocr.py tier 2)")


def tesseract_available() -> tuple[bool, str]:
    """Cheap readiness probe used by /api/ready.  Runs no OCR."""
    import shutil

    exe = shutil.which("tesseract")
    if exe:
        return True, exe
    return False, "tesseract binary not found on PATH"


def cascade_plan(has_layer: bool, tier2_confidence: Optional[float]) -> ExtractionTier:
    """The routing decision inside the cascade, kept pure so it is testable.

    This is real logic, not a stub: P2 fills in the extractors around it.
    """
    if has_layer:
        return "text_layer"
    if tier2_confidence is None:
        return "tesseract"
    if tier2_confidence < TESSERACT_ESCALATION_THRESHOLD:
        return "vlm"
    return "tesseract"


def require_binary(name: str, owner: str) -> None:
    import shutil

    if shutil.which(name) is None:
        raise ToolError(
            ErrorCode.NOT_IMPLEMENTED,
            "%s is not installed; %s owns this dependency. "
            "Run in mock mode to work without it." % (name, owner),
        )
