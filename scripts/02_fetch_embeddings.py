"""
SETU 02_fetch_embeddings.py

Downloads BAAI/bge-small-en-v1.5 into a repo-local cache, then immediately
re-loads it in forced-offline mode to prove the cache is complete.

Blueprint section 6.1 (embeddings on CPU) and 6.2 (HF offline settings).

Run this BEFORE setting HF_HUB_OFFLINE=1 permanently -- the download needs
network. The verification pass sets it temporarily in-process.

Usage:
    python scripts/02_fetch_embeddings.py
    python scripts/02_fetch_embeddings.py --model BAAI/bge-small-en-v1.5
"""

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE = REPO_ROOT / "vendor" / "models" / "hf_cache"
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
FALLBACK_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def download(model_id: str, cache_dir: Path) -> Path:
    """Snapshot the full repo so nothing is fetched lazily at demo time."""
    from huggingface_hub import snapshot_download

    print(f"[*] downloading {model_id} -> {cache_dir}")
    path = snapshot_download(
        repo_id=model_id,
        cache_dir=str(cache_dir),
        # Skip the duplicate weight formats. Keep safetensors + all config/tokenizer
        # files, and the sentence-transformers module configs.
        ignore_patterns=["*.msgpack", "*.h5", "*.ot", "*.onnx", "openvino/*"],
    )
    print(f"[+] snapshot at {path}")
    return Path(path)


def verify_offline(model_id: str, cache_dir: Path) -> bool:
    """
    Re-import in a forced-offline process state and encode a sentence.
    This is the check that actually matters: it proves the cache is complete,
    not merely that a download reported success.
    """
    print("\n[*] verifying with HF_HUB_OFFLINE=1 and local_files_only=True")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(
            model_id,
            cache_folder=str(cache_dir),
            local_files_only=True,
            device="cpu",
        )
        vecs = model.encode(
            ["boiler feed pump vibration limit", "hydrostatic test pressure"],
            normalize_embeddings=True,
        )
        dim = len(vecs[0])
        print(f"[+] offline load OK. dim={dim}, vectors={len(vecs)}")
        print(f"[+] record this dimension in your vector index config: {dim}")
        return True
    except Exception as exc:  # noqa: BLE001 - we want the raw reason printed
        print(f"[!] OFFLINE LOAD FAILED: {type(exc).__name__}: {exc}")
        print("[!] The cache is incomplete. Re-run the download with network on.")
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--cache-dir", default=str(DEFAULT_CACHE))
    ap.add_argument(
        "--with-fallback",
        action="store_true",
        help="also cache the MiniLM fallback named in blueprint 6.1",
    )
    args = ap.parse_args()

    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Make sure we are NOT offline during the download step
    for var in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
        if os.environ.pop(var, None):
            print(f"[*] temporarily cleared {var} for download")

    try:
        download(args.model, cache_dir)
        if args.with_fallback:
            download(FALLBACK_MODEL, cache_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"[!] download failed: {exc}")
        print("[!] Check network, then re-run.")
        return 1

    ok = verify_offline(args.model, cache_dir)

    print("\n" + "=" * 60)
    if ok:
        print("PASS. Add this to your backend config:")
        print(f"  EMBED_MODEL     = {args.model!r}")
        print(f"  EMBED_CACHE_DIR = {str(cache_dir)!r}")
        print("  local_files_only=True on every load call")
        print("\nYou may now set HF_HUB_OFFLINE=1 permanently.")
    else:
        print("FAIL. Do not set HF_HUB_OFFLINE=1 yet.")
    print("=" * 60)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
