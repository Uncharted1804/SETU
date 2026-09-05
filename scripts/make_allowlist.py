"""
SETU make_allowlist.py -- capture the trusted integrity baseline (blueprint 12.6)

Walks the Ollama manifest directory, records each model's manifest digest and
every layer digest, hashes the actual blob files on disk, and records the
sandbox image id. Writes config/model_allowlist.json.

The point of blueprint F10: a manifest cannot verify itself. This file is
captured NOW, while the machine is still trusted and online, and committed to
the repository. preflight.py later re-hashes blobs against it.

Run this ONCE at T-5, after the benchmark has frozen your model choice.
Re-run only if you deliberately change a model, and record why.

Stdlib only.

Usage:
    python scripts/make_allowlist.py
    python scripts/make_allowlist.py --out config/model_allowlist.json --full-hash
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

MODELS = [
    "qwen3:8b", "qwen2.5-coder:7b", "qwen3-vl:4b",
    "qwen3:4b-instruct", "qwen2.5-coder:3b", "qwen3-vl:2b",
    "granite3.2-vision:2b",  # blueprint v2 4.3/14.1: pre-pulled vision emergency fallback
]

# Hashing 5 GB blobs takes a while. By default we hash the first and last
# 64 MB plus the size, which detects truncation and most tampering cheaply.
# --full-hash does the honest complete SHA-256; use it at least once.
PARTIAL_WINDOW = 64 * 1024 * 1024


def models_root() -> Path | None:
    """Locate the Ollama models directory across platforms."""
    if env := os.environ.get("OLLAMA_MODELS"):
        p = Path(env)
        if p.is_dir():
            return p
    candidates = [
        Path.home() / ".ollama" / "models",
        Path("/usr/share/ollama/.ollama/models"),
        Path("/var/lib/ollama/.ollama/models"),
    ]
    if os.name == "nt" and (lad := os.environ.get("LOCALAPPDATA")):
        candidates.insert(1, Path(lad) / "Ollama" / "models")
    for c in candidates:
        if (c / "manifests").is_dir():
            return c
    return None


def find_manifest(root: Path, model: str) -> Path | None:
    """manifests/<registry>/<namespace>/<name>/<tag>"""
    name, _, tag = model.partition(":")
    tag = tag or "latest"
    manifests = root / "manifests"
    if not manifests.is_dir():
        return None
    for path in manifests.rglob(tag):
        if path.is_file() and path.parent.name == name:
            return path
    return None


def blob_path(root: Path, digest: str) -> Path:
    """sha256:abc -> blobs/sha256-abc"""
    return root / "blobs" / digest.replace(":", "-")


def hash_file(path: Path, full: bool) -> tuple[str, str]:
    """Returns (mode, hexdigest)."""
    h = hashlib.sha256()
    size = path.stat().st_size
    with path.open("rb") as f:
        if full or size <= 2 * PARTIAL_WINDOW:
            for chunk in iter(lambda: f.read(4 * 1024 * 1024), b""):
                h.update(chunk)
            return "full", h.hexdigest()
        h.update(f.read(PARTIAL_WINDOW))
        f.seek(-PARTIAL_WINDOW, os.SEEK_END)
        h.update(f.read(PARTIAL_WINDOW))
        h.update(str(size).encode())
        return "partial", h.hexdigest()


def capture_model(root: Path, model: str, full: bool) -> dict:
    entry = {"model": model, "status": "missing", "layers": []}
    mf = find_manifest(root, model)
    if not mf:
        return entry

    manifest_bytes = mf.read_bytes()
    entry["manifest_path"] = str(mf.relative_to(root))
    entry["manifest_sha256"] = hashlib.sha256(manifest_bytes).hexdigest()

    try:
        manifest = json.loads(manifest_bytes)
    except json.JSONDecodeError:
        entry["status"] = "unreadable_manifest"
        return entry

    layers = list(manifest.get("layers", []))
    if cfg := manifest.get("config"):
        layers.append({**cfg, "mediaType": cfg.get("mediaType", "config")})

    total = 0
    for layer in layers:
        digest = layer.get("digest", "")
        bp = blob_path(root, digest)
        rec = {
            "media_type": layer.get("mediaType", ""),
            "digest": digest,
            "declared_size": layer.get("size", 0),
        }
        if bp.is_file():
            actual = bp.stat().st_size
            mode, hexd = hash_file(bp, full)
            rec.update({
                "present": True,
                "actual_size": actual,
                "size_matches": actual == layer.get("size", actual),
                "hash_mode": mode,
                "blob_sha256": hexd,
            })
            total += actual
        else:
            rec["present"] = False
        entry["layers"].append(rec)
        print(f"      {digest[:19]}... {'ok' if rec.get('present') else 'MISSING'}")

    entry["total_bytes"] = total
    entry["status"] = "ok" if all(l.get("present") for l in entry["layers"]) else "incomplete_blobs"
    return entry


def capture_sandbox() -> dict:
    try:
        out = subprocess.run(
            ["docker", "image", "inspect", "setu-sandbox:py311", "--format", "{{.Id}}|{{.Size}}"],
            capture_output=True, text=True, timeout=60,
        )
        if out.returncode == 0 and "|" in out.stdout:
            image_id, size = out.stdout.strip().split("|", 1)
            return {"image": "setu-sandbox:py311", "present": True,
                    "image_id": image_id, "size_bytes": int(size)}
    except Exception as exc:  # noqa: BLE001
        return {"image": "setu-sandbox:py311", "present": False, "error": str(exc)}
    return {"image": "setu-sandbox:py311", "present": False,
            "error": "not found -- run 03_build_sandbox.ps1"}


def capture_versions() -> dict:
    v = {}
    for key, cmd in [("ollama", ["ollama", "--version"]),
                     ("docker", ["docker", "--version"]),
                     ("python", [sys.executable, "--version"])]:
        try:
            o = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            v[key] = (o.stdout or o.stderr).strip().splitlines()[0]
        except Exception:
            v[key] = "unavailable"
    return v


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO_ROOT / "config" / "model_allowlist.json"))
    ap.add_argument("--full-hash", action="store_true",
                    help="complete SHA-256 of every blob (slow, do this at least once)")
    ap.add_argument("--models", nargs="*", default=MODELS)
    args = ap.parse_args()

    root = models_root()
    if not root:
        print("[!] Could not locate the Ollama models directory.")
        print("[!] Set OLLAMA_MODELS or check that models are pulled.")
        return 1
    print(f"[*] models root: {root}")
    print(f"[*] hash mode:   {'FULL sha256' if args.full_hash else 'partial (head+tail+size)'}")

    allowlist = {
        "schema": "setu.model_allowlist/1",
        "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "captured_on": os.environ.get("COMPUTERNAME") or os.uname().nodename,
        "hash_mode": "full" if args.full_hash else "partial",
        "models_root": str(root),
        "versions": capture_versions(),
        "models": [],
        "sandbox_image": capture_sandbox(),
        "note": (
            "Captured before isolation while the machine was trusted. "
            "preflight.py re-verifies against this file. The UI must say "
            "'matches approved local baseline', not 'verified'."
        ),
    }

    for model in args.models:
        print(f"\n[*] {model}")
        entry = capture_model(root, model, args.full_hash)
        allowlist["models"].append(entry)
        print(f"    status: {entry['status']}"
              + (f", {entry.get('total_bytes', 0) / 1e9:.2f} GB" if entry.get("total_bytes") else ""))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(allowlist, indent=2), encoding="utf-8")

    ok = sum(1 for m in allowlist["models"] if m["status"] == "ok")
    print(f"\n[+] wrote {out}")
    print(f"[+] {ok}/{len(allowlist['models'])} models captured cleanly")
    print(f"[+] sandbox image: {'present' if allowlist['sandbox_image'].get('present') else 'MISSING'}")
    print("\nCommit this file, and copy it to the backup drive.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
