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

bbox format: [x0, y0, x1, y1] in PDF points (72/inch), origin TOP-LEFT,
x0 < x1, y0 < y1.  PyMuPDF returns (x0, y0, x1, y1) tuples in PDF points
natively.  Tesseract returns pixel-space boxes; we store those as-is when
no PDF point conversion is available (source is a raw image, not a PDF page).
Pages are 1-indexed (contracts.py convention 3).
"""

from __future__ import annotations

import secrets
import tempfile
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
    """Extract text and bboxes from the embedded text layer of a digital PDF.

    Acceptance: a digital PDF yields exact text with extraction_tier="text_layer"
    and per-block bboxes in PDF points (72/inch), origin top-left.
    Pages are 1-indexed.  bbox is [x0, y0, x1, y1].
    """
    fitz = optional_import("pymupdf", owner="P2", purpose="PDF text layer")
    findings: list[Finding] = []
    with fitz.open(str(pdf_path)) as doc:
        for page_idx, page in enumerate(doc):
            page_num = page_idx + 1  # 1-indexed
            # get_text("blocks") returns (x0, y0, x1, y1, text, block_no, block_type)
            blocks = page.get_text("blocks")
            for block in blocks:
                x0, y0, x1, y1, text = block[:5]
                text = text.strip()
                if not text:
                    continue
                # bbox must satisfy x0<x1 and y0<y1
                if x0 >= x1 or y0 >= y1:
                    continue
                findings.append(
                    Finding(
                        id="t1_" + secrets.token_hex(4),
                        text=text,
                        page=page_num,
                        bbox=[float(x0), float(y0), float(x1), float(y1)],
                        confidence=1.0,  # text layer is exact
                        source_file=source_rel,
                        extraction_tier="text_layer",
                    )
                )
    return findings


def rasterize(pdf_path: Path, out_dir: Path, dpi: int = 300) -> list[Path]:
    """Render each PDF page to a PNG at `dpi` dots per inch.

    Output PNGs are written to out_dir (inside the workspace jail).
    Returns a list of absolute Paths, one per page, in page order.

    Acceptance: 300 dpi PNG per page, written inside the workspace via ctx.resolve.
    """
    fitz = optional_import("pymupdf", owner="P2", purpose="PDF rasterization")
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    zoom = dpi / 72.0  # 72 PDF points per inch
    mat = fitz.Matrix(zoom, zoom)
    with fitz.open(str(pdf_path)) as doc:
        for page_idx, page in enumerate(doc):
            pix = page.get_pixmap(matrix=mat, alpha=False)
            out_path = out_dir / ("page_%04d.png" % (page_idx + 1))
            pix.save(str(out_path))
            paths.append(out_path)
    return paths


def preprocess(image_path: Path, clahe: bool = True, deskew: bool = True) -> Path:
    """Apply contrast enhancement (CLAHE) and optional deskew to an image.

    Returns the path to the processed image (written alongside the original
    with a `_pre` suffix so the original is preserved for comparison).

    Acceptance: on attempt 2, CLAHE + deskew measurably raises Tesseract mean
    confidence on the deliberately blurry demo region.
    """
    cv2 = optional_import("cv2", owner="P2", purpose="image preprocessing")
    np = optional_import("numpy", owner="P2", purpose="image preprocessing")

    img = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if img is None:
        raise ToolError(
            ErrorCode.NOT_FOUND,
            "preprocess: cannot open image at %s" % image_path,
            path=str(image_path),
        )

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    if clahe:
        clahe_obj = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray = clahe_obj.apply(gray)

    if deskew:
        gray = _deskew(gray, cv2, np)

    out_path = image_path.parent / (image_path.stem + "_pre.png")
    cv2.imwrite(str(out_path), gray)
    return out_path


def _deskew(gray, cv2, np):
    """Estimate and correct document skew using moment-based angle detection."""
    # Threshold and find coordinates of non-zero pixels
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    coords = np.column_stack(np.where(thresh > 0))
    if len(coords) < 5:
        return gray  # not enough content to measure skew
    angle = cv2.minAreaRect(coords)[-1]
    # minAreaRect returns angles in [-90, 0); correct to small tilt
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle
    if abs(angle) < 0.5:
        return gray  # negligible skew, skip rotation
    h, w = gray.shape
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    rotated = cv2.warpAffine(
        gray, M, (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return rotated


def crop_to_bbox(image_path: Path, bbox: list[float], pad: int = 12) -> Path:
    """Crop the image to the given bbox, with optional padding.

    bbox is [x0, y0, x1, y1] in the same coordinate space as the image (pixels
    when the source is a rasterised page).  A pad of 12 pixels is added on all
    sides so the model sees a little context around the target region.

    Returns path to the cropped image written alongside the source with `_crop`.

    Acceptance: retry re-asks about ONE region, not the whole page.
    """
    cv2 = optional_import("cv2", owner="P2", purpose="bbox cropping")

    img = cv2.imread(str(image_path))
    if img is None:
        raise ToolError(
            ErrorCode.NOT_FOUND,
            "crop_to_bbox: cannot open image at %s" % image_path,
            path=str(image_path),
        )

    h, w = img.shape[:2]
    x0 = max(0, int(bbox[0]) - pad)
    y0 = max(0, int(bbox[1]) - pad)
    x1 = min(w, int(bbox[2]) + pad)
    y1 = min(h, int(bbox[3]) + pad)

    if x1 <= x0 or y1 <= y0:
        # Degenerate bbox — return the full image rather than failing
        return image_path

    crop = img[y0:y1, x0:x1]
    out_path = image_path.parent / (image_path.stem + "_crop.png")
    cv2.imwrite(str(out_path), crop)
    return out_path


def tier2_tesseract(image_path: Path, source_rel: str, page: int) -> list[Finding]:
    """Run Tesseract on a rasterised page image and return word-level Findings.

    The wrapper is `pytesseract`; the Tesseract BINARY is installed separately.
    If the binary is absent this raises a clear ToolError, never falls back to
    the VLM silently - a silent fallback hides the cascade the demo is meant to
    show.

    Confidence: Tesseract's word-level confidence (0-100) is normalised to [0,1].
    Finding confidence is the per-word value.

    Acceptance: the demo scan yields >= 5 findings with word-level confidences;
    a page with no text layer is detected, not assumed.
    """
    require_binary("tesseract", "P2")
    pytesseract = optional_import("pytesseract", owner="P2", purpose="Tesseract OCR")
    Image = optional_import("PIL.Image", owner="P2", purpose="Tesseract OCR")

    try:
        img = Image.open(str(image_path))
    except Exception as exc:
        raise ToolError(
            ErrorCode.TOOL_FAILED,
            "tier2_tesseract: cannot open image %s: %s" % (image_path, exc),
            path=str(image_path),
        ) from exc

    try:
        data = pytesseract.image_to_data(
            img,
            output_type=pytesseract.Output.DICT,
            config="--oem 3 --psm 6",
        )
    except pytesseract.TesseractNotFoundError as exc:
        raise ToolError(
            ErrorCode.TOOL_FAILED,
            "Tesseract binary not found: %s.  Install Tesseract and ensure it is on PATH." % exc,
        ) from exc
    except Exception as exc:
        raise ToolError(
            ErrorCode.TOOL_FAILED,
            "Tesseract OCR failed on %s: %s" % (image_path, exc),
            path=str(image_path),
        ) from exc

    findings: list[Finding] = []
    n = len(data["text"])
    for i in range(n):
        text = (data["text"][i] or "").strip()
        if not text:
            continue
        conf_raw = data["conf"][i]
        # Tesseract returns -1 for blocks with no confidence measurement
        if conf_raw < 0:
            continue
        confidence = float(conf_raw) / 100.0
        confidence = max(0.0, min(1.0, confidence))

        x = data["left"][i]
        y = data["top"][i]
        w = data["width"][i]
        h = data["height"][i]

        # Ensure valid bbox (some Tesseract outputs have zero-size boxes)
        if w <= 0 or h <= 0:
            bbox = None
        else:
            bbox = [float(x), float(y), float(x + w), float(y + h)]

        findings.append(
            Finding(
                id="t2_" + secrets.token_hex(4),
                text=text,
                page=page,
                bbox=bbox,
                confidence=confidence,
                source_file=source_rel,
                extraction_tier="tesseract",
            )
        )
    return findings


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
            ErrorCode.TOOL_FAILED,
            "%s is not installed; %s owns this dependency. "
            "Run in mock mode to work without it." % (name, owner),
        )


def mean_confidence(findings: list[Finding]) -> float:
    """Average confidence across a list of findings.  Returns 0.0 if empty."""
    if not findings:
        return 0.0
    return sum(f.confidence for f in findings) / len(findings)
