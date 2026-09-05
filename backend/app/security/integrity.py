"""
Layer 7 - model integrity verification.  OWNER: P6.

Ollama stores weights as content-addressed blobs and each model tag has a
manifest digest.  config/models.yaml already carries `expected_manifest_digest`
for every enabled entry (filled in by scripts/make_allowlist.py).

THE HONESTY RULE FOR THIS MODULE: `integrity_verified` is Optional[bool] in the
contract, and `None` means NEVER CHECKED.  The UI must render an unchecked
digest as "not verified", never as a tick.  A digest printed next to a green
check that nobody computed is worse than showing nothing.

P6 TODO (owner: P6, acceptance: `GET /api/models` reports integrity_verified
True/False from a real digest comparison on this machine, and the registry panel
shows one verified and one deliberately-unchecked row):
  - implement `verify_installed()` against the local Ollama manifest directory
    (%USERPROFILE%\\.ollama\\models\\manifests) WITHOUT calling the network
  - compare to expected_manifest_digest and to config/model_allowlist.json
  - surface a mismatch as a startup warning, not a silent pass
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ..config import ModelRegistry
from ..contracts import ModelEntry


def allowlist_path(repo_root: Path) -> Path:
    return repo_root / "config" / "model_allowlist.json"


def load_allowlist(repo_root: Path) -> dict:
    p = allowlist_path(repo_root)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def annotate(registry: ModelRegistry, checked: bool = False) -> list[ModelEntry]:
    """Return registry entries for the UI.

    `checked=False` (the default, and the only value the scaffold ever passes)
    leaves `integrity_verified` as None so nothing is claimed that was not run.
    """
    out: list[ModelEntry] = []
    for entry in registry.entries:
        out.append(entry.model_copy(update={"integrity_verified": None if not checked else False}))
    return out


def verify_installed(registry: ModelRegistry, ollama_home: Optional[Path] = None) -> dict:
    """NOT IMPLEMENTED - P6.

    Must read local manifests only.  It must not call the Ollama HTTP API for a
    digest it could read from disk, and it must never trigger a model pull.
    """
    raise NotImplementedError(
        "P6 owns model integrity verification. Until it is implemented, "
        "GET /api/models reports integrity_verified=null (never checked)."
    )
