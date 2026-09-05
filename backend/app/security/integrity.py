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
import hashlib
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


def verify_installed(registry: ModelRegistry, ollama_home: Optional[Path] = None) -> dict[str, str]:
    if ollama_home is None:
        ollama_home = Path.home() / ".ollama"
        
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    allowlist = load_allowlist(repo_root)
    
    models_info = {m["model"]: m for m in allowlist.get("models", [])}
    
    results = {}
    for entry in registry.entries:
        if not entry.enabled:
            continue
            
        if not entry.expected_manifest_digest:
            results[entry.id] = "UNAVAILABLE"
            continue
            
        info = models_info.get(entry.model)
        if not info or "manifest_path" not in info:
            results[entry.id] = "UNAVAILABLE"
            continue
            
        manifest_file = ollama_home / "models" / info["manifest_path"]
        if not manifest_file.is_file():
            results[entry.id] = "UNAVAILABLE"
            continue
            
        try:
            content = manifest_file.read_bytes()
            actual_digest = "sha256:" + hashlib.sha256(content).hexdigest()
            
            expected_in_allowlist = info.get("manifest_sha256")
            if not expected_in_allowlist:
                expected_in_allowlist = info.get("digest")
                
            if expected_in_allowlist and not expected_in_allowlist.startswith("sha256:"):
                expected_in_allowlist = "sha256:" + expected_in_allowlist
                
            if expected_in_allowlist and actual_digest == expected_in_allowlist and actual_digest == entry.expected_manifest_digest:
                results[entry.id] = "VERIFIED"
            else:
                results[entry.id] = "MISMATCH"
        except OSError:
            results[entry.id] = "UNAVAILABLE"
            
    return results


def annotate(registry: ModelRegistry, checked: bool = False) -> list[ModelEntry]:
    """Return registry entries for the UI.

    `checked=False` (the default, and the only value the scaffold ever passes)
    leaves `integrity_verified` as None so nothing is claimed that was not run.
    """
    out: list[ModelEntry] = []
    
    if checked:
        verification = verify_installed(registry)
    else:
        verification = {}

    for entry in registry.entries:
        if not checked:
            ver_status = None
        else:
            status = verification.get(entry.id)
            if status == "VERIFIED":
                ver_status = True
            elif status == "MISMATCH":
                ver_status = False
            else:
                ver_status = None
        out.append(entry.model_copy(update={"integrity_verified": ver_status}))
    return out
