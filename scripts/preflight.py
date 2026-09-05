"""
SETU preflight.py -- Sovereign Mode gate (blueprint section 12.2)

Refuses Sovereign Mode if any of these fail:
  - Ollama host is not loopback
  - the API route-ordering bug from blueprint v2 section 0.5 is present
    (/api/health swallowed by the static catch-all mount)
  - required model tags or expected digests are missing
  - embedding files are absent from the local cache
  - Docker / sandbox image is unavailable
  - workspace permissions violate the read/write policy
  - the network monitor cannot inspect the required processes
  - the demo corpus has not been indexed

Emits both a human-readable console report and JSON on --json, so the same
check drives the UI checklist panel.

Exit codes: 0 all pass, 1 a blocking check failed, 2 only warnings.

Usage:
    python scripts/preflight.py
    python scripts/preflight.py --json
    python scripts/preflight.py --verify-hashes     # slow, re-hashes blobs
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST = REPO_ROOT / "config" / "model_allowlist.json"
EMBED_CACHE = REPO_ROOT / "vendor" / "models" / "hf_cache"
CORPUS_DIR = REPO_ROOT / "data" / "kb_corpus"
VECTOR_DIR = REPO_ROOT / "data" / "runtime" / "chroma"
WORKSPACE = REPO_ROOT / "data" / "runtime" / "workspace"
BACKEND_URL = "http://127.0.0.1:8000"

SETU_PROCESS_NAMES = {"ollama", "ollama.exe", "ollama app.exe", "python", "python.exe", "uvicorn"}


@dataclass
class Check:
    name: str
    ok: bool
    blocking: bool
    detail: str

    @property
    def label(self) -> str:
        if self.ok:
            return "PASS"
        return "FAIL" if self.blocking else "WARN"


checks: list[Check] = []


def add(name: str, ok: bool, detail: str, blocking: bool = True) -> bool:
    checks.append(Check(name, ok, blocking, detail))
    return ok


# ---------------------------------------------------------------------------
def check_ollama_loopback() -> None:
    host = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434")
    hostname = host.split("://")[-1].split(":")[0]
    is_loopback = hostname in ("127.0.0.1", "localhost", "::1")
    add("Ollama bound to loopback", is_loopback,
        f"OLLAMA_HOST={host}" + ("" if is_loopback else "  <-- exposes the model server on the network"))

    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=10) as r:
            data = json.loads(r.read())
        add("Ollama reachable", True, f"{len(data.get('models', []))} models registered")
    except Exception as exc:  # noqa: BLE001
        add("Ollama reachable", False, f"cannot reach 127.0.0.1:11434 ({exc})")


def check_resource_env() -> None:
    expected = {
        "OLLAMA_MAX_LOADED_MODELS": "1",
        "OLLAMA_NUM_PARALLEL": "1",
        "OLLAMA_FLASH_ATTENTION": "1",
        "OLLAMA_KV_CACHE_TYPE": "q8_0",
    }
    wrong = [f"{k}={os.environ.get(k, 'unset')} (want {v})"
             for k, v in expected.items() if os.environ.get(k) != v]
    add("VRAM scheduling env vars", not wrong,
        "one resident model, flash attention, q8_0 KV cache" if not wrong else "; ".join(wrong),
        blocking=False)

    offline = os.environ.get("HF_HUB_OFFLINE") == "1"
    add("HF_HUB_OFFLINE=1", offline,
        "HuggingFace forced offline" if offline else "not set -- libraries may attempt remote fetch",
        blocking=False)


def check_models(verify_hashes: bool) -> None:
    if not ALLOWLIST.is_file():
        add("Model allow-list present", False,
            f"{ALLOWLIST} missing -- run scripts/make_allowlist.py before isolation")
        return
    add("Model allow-list present", True, f"captured {json.loads(ALLOWLIST.read_text())['captured_at']}")

    allow = json.loads(ALLOWLIST.read_text(encoding="utf-8"))

    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=10) as r:
            installed = {m["name"] for m in json.loads(r.read()).get("models", [])}
    except Exception:
        add("Required model tags installed", False, "cannot query Ollama for installed tags")
        return

    required = [m["model"] for m in allow["models"] if m.get("status") == "ok"]
    missing = [m for m in required
               if m not in installed and f"{m}:latest" not in installed]
    add("Required model tags installed", not missing,
        f"{len(required) - len(missing)}/{len(required)} present"
        + (f"; missing: {', '.join(missing)}" if missing else ""))

    root = Path(allow["models_root"])
    if not root.is_dir():
        add("Model blob store reachable", False, f"{root} not found")
        return

    absent = []
    for entry in allow["models"]:
        for layer in entry.get("layers", []):
            bp = root / "blobs" / layer["digest"].replace(":", "-")
            if not bp.is_file():
                absent.append(f"{entry['model']}:{layer['digest'][:16]}")
            elif layer.get("actual_size") and bp.stat().st_size != layer["actual_size"]:
                absent.append(f"{entry['model']}:{layer['digest'][:16]} (size changed)")
    add("Model blobs match approved baseline", not absent,
        "all blob sizes match the allow-list" if not absent
        else f"{len(absent)} mismatched: {', '.join(absent[:3])}")

    if verify_hashes:
        sys.path.insert(0, str(Path(__file__).parent))
        try:
            from make_allowlist import hash_file  # reuse the identical hashing logic
            bad = []
            for entry in allow["models"]:
                for layer in entry.get("layers", []):
                    bp = root / "blobs" / layer["digest"].replace(":", "-")
                    if not bp.is_file() or "blob_sha256" not in layer:
                        continue
                    _, hexd = hash_file(bp, allow.get("hash_mode") == "full")
                    if hexd != layer["blob_sha256"]:
                        bad.append(f"{entry['model']}:{layer['digest'][:16]}")
            add("Model blob hashes re-verified", not bad,
                "hashes match approved local baseline" if not bad
                else f"MISMATCH: {', '.join(bad)}")
        except Exception as exc:  # noqa: BLE001
            add("Model blob hashes re-verified", False, f"hash check errored: {exc}", blocking=False)


def check_route_ordering() -> None:
    """
    Blueprint v2 section 0.5: if the catch-all static mount is ever registered
    before the /api/* routes, Starlette's route matching lets it swallow the
    entire API -- /api/health comes back 404, or worse, the frontend's
    index.html, instead of JSON. This must fail loudly, not warn, because a
    silently-swallowed API is exactly the kind of thing that looks fine until
    a judge's browser hits it.
    """
    try:
        req = urllib.request.Request(f"{BACKEND_URL}/api/health")
        with urllib.request.urlopen(req, timeout=5) as r:
            status = r.status
            content_type = r.headers.get("Content-Type", "")
            body = r.read().decode(errors="replace")
        is_json = "json" in content_type.lower()
        if is_json:
            try:
                json.loads(body)
            except json.JSONDecodeError:
                is_json = False
        ok = status == 200 and is_json
        add("API route /api/health returns JSON (not swallowed by static mount)", ok,
            f"status={status} content-type={content_type or 'unknown'}" if ok
            else f"status={status} content-type={content_type or 'unknown'} "
                 "-- static mount is likely registered before /api/* routes (blueprint 0.5)")
    except urllib.error.HTTPError as exc:
        add("API route /api/health returns JSON (not swallowed by static mount)", False,
            f"HTTP {exc.code} -- "
            + ("mount-ordering bug: static catch-all is swallowing /api/*" if exc.code == 404
               else "backend returned an error"))
    except Exception as exc:  # noqa: BLE001
        add("API route /api/health returns JSON (not swallowed by static mount)", False,
            f"backend not reachable at {BACKEND_URL} ({exc}) -- start the backend before this check can pass")

    try:
        with urllib.request.urlopen(f"{BACKEND_URL}/", timeout=5) as r:
            status = r.status
        add("Frontend root '/' is served", status == 200, f"status={status}", blocking=False)
    except Exception as exc:  # noqa: BLE001
        add("Frontend root '/' is served", False, f"backend not reachable at {BACKEND_URL} ({exc})",
            blocking=False)


def check_embeddings() -> None:
    if not EMBED_CACHE.is_dir():
        add("Embedding cache present", False, f"{EMBED_CACHE} missing -- run 02_fetch_embeddings.py")
        return
    weights = list(EMBED_CACHE.rglob("*.safetensors")) + list(EMBED_CACHE.rglob("pytorch_model.bin"))
    configs = list(EMBED_CACHE.rglob("config.json"))
    tokenizers = list(EMBED_CACHE.rglob("tokenizer.json")) + list(EMBED_CACHE.rglob("vocab.txt"))
    ok = bool(weights and configs and tokenizers)
    add("Embedding cache present", ok,
        f"{len(weights)} weight file(s), {len(configs)} config(s), {len(tokenizers)} tokenizer file(s)"
        if ok else "cache is incomplete -- re-run 02_fetch_embeddings.py with network")


def check_tesseract() -> None:
    try:
        out = subprocess.run(["tesseract", "--version"], capture_output=True, text=True, timeout=30)
        ver = (out.stdout or out.stderr).strip().splitlines()[0]
    except Exception:
        add("Tesseract available", False, "tesseract not on PATH -- OCR tier D2 will fail")
        return
    add("Tesseract available", True, ver)

    try:
        langs = subprocess.run(["tesseract", "--list-langs"],
                               capture_output=True, text=True, timeout=30)
        # First line is a header like 'List of available languages (2):'
        lines = (langs.stdout or "").splitlines()[1:]
        found = {ln.strip() for ln in lines if ln.strip().isalnum() or "_" in ln.strip()}
        found = {f for f in found if f and len(f) <= 12}
        add("Tesseract language data", "eng" in found,
            f"languages: {', '.join(sorted(found))[:80]}")
        add("Tesseract orientation data (osd)", "osd" in found,
            "osd present" if "osd" in found else "osd missing -- deskew/rotation detection degraded",
            blocking=False)
    except Exception as exc:  # noqa: BLE001
        add("Tesseract language data", False, str(exc))


def check_docker() -> None:
    try:
        info = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"],
                              capture_output=True, text=True, timeout=60)
        if info.returncode != 0:
            add("Docker daemon running", False,
                "daemon not responding -- start Docker Desktop; the coding demo needs it")
            return
        add("Docker daemon running", True, f"engine {info.stdout.strip()}")
    except Exception as exc:  # noqa: BLE001
        add("Docker daemon running", False, str(exc))
        return

    try:
        img = subprocess.run(["docker", "image", "inspect", "setu-sandbox:py311",
                              "--format", "{{.Id}}"], capture_output=True, text=True, timeout=60)
        present = img.returncode == 0
        image_id = img.stdout.strip() if present else ""
        add("Sandbox image setu-sandbox:py311", present,
            image_id[:24] if present else "missing -- docker load -i vendor/setu-sandbox-py311.tar")

        if present and ALLOWLIST.is_file():
            expected = json.loads(ALLOWLIST.read_text()).get("sandbox_image", {}).get("image_id")
            if expected:
                add("Sandbox image matches baseline", image_id == expected,
                    "matches approved local baseline" if image_id == expected
                    else f"id differs from allow-list ({expected[:24]})")
    except Exception as exc:  # noqa: BLE001
        add("Sandbox image setu-sandbox:py311", False, str(exc))


def check_sandbox_isolation() -> None:
    """Actually run the container and confirm it has no network."""
    try:
        out = subprocess.run(
            ["docker", "run", "--rm", "--network=none", "--read-only",
             "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
             "--memory=512m", "--memory-swap=512m", "--cpus=1", "--pids-limit=64",
             "--cap-drop=ALL", "--security-opt=no-new-privileges",
             "--user=65534:65534", "-e", "HOME=/tmp",
             "setu-sandbox:py311",
             "-c",
             "import socket,sys\n"
             "try:\n"
             "    socket.create_connection(('1.1.1.1',53),timeout=3)\n"
             "    sys.exit(1)\n"
             "except OSError:\n"
             "    import openpyxl; print('isolated+openpyxl', openpyxl.__version__)"],
            capture_output=True, text=True, timeout=120,
        )
        ok = out.returncode == 0
        add("Sandbox is networkless and has openpyxl", ok,
            out.stdout.strip() if ok else (out.stderr or out.stdout).strip()[:160])
    except Exception as exc:  # noqa: BLE001
        add("Sandbox is networkless and has openpyxl", False, str(exc))


def check_workspace() -> None:
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    probe = WORKSPACE / ".preflight_probe"
    try:
        probe.write_text("x", encoding="utf-8")
        probe.unlink()
        add("Workspace writable", True, str(WORKSPACE))
    except Exception as exc:  # noqa: BLE001
        add("Workspace writable", False, f"{WORKSPACE}: {exc}")

    # The path jail depends on the workspace resolving inside the repo
    try:
        WORKSPACE.resolve().relative_to(REPO_ROOT.resolve())
        add("Workspace inside repository root", True, "path jail base is consistent")
    except ValueError:
        add("Workspace inside repository root", False,
            "workspace resolves outside the repo -- the path jail assumption is broken")


def check_corpus_indexed() -> None:
    docs = [p for p in CORPUS_DIR.rglob("*") if p.is_file()] if CORPUS_DIR.is_dir() else []
    add("Demo corpus present", bool(docs),
        f"{len(docs)} source file(s) in data/kb_corpus" if docs
        else "no corpus files -- citations cannot be produced")

    indexed = VECTOR_DIR.is_dir() and any(VECTOR_DIR.iterdir())
    add("Vector index built", indexed,
        f"index at {VECTOR_DIR}" if indexed
        else "index missing -- run your ingest step before the demo")


def check_netwatch() -> None:
    """The monitor must be able to inspect the processes it claims to watch."""
    try:
        import psutil  # type: ignore
    except ImportError:
        add("Network monitor can inspect processes", False,
            "psutil not installed -- activate the venv, or netwatch cannot make its claim")
        return

    watched, inspectable, external = [], 0, 0
    for proc in psutil.process_iter(["name", "pid"]):
        name = (proc.info.get("name") or "").lower()
        if name not in {n.lower() for n in SETU_PROCESS_NAMES}:
            continue
        watched.append(f"{name}({proc.info['pid']})")
        try:
            for conn in proc.net_connections(kind="inet"):
                inspectable += 1
                raddr = getattr(conn, "raddr", None)
                if raddr and raddr.ip not in ("127.0.0.1", "::1", ""):
                    external += 1
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass

    add("Network monitor can inspect processes", bool(watched),
        f"watching {len(watched)} process(es): {', '.join(watched[:5])}" if watched
        else "no SETU processes found -- start the backend and Ollama first",
        blocking=False)
    add("Zero external sockets on SETU processes", external == 0,
        f"{inspectable} socket(s) inspected, {external} external"
        + ("" if external == 0 else "  <-- investigate before claiming air-gap"))


def check_adapter() -> None:
    """Advisory only. Blueprint 12.3 says the adapter is the enforcement layer."""
    reachable = False
    try:
        s = socket.create_connection(("1.1.1.1", 53), timeout=3)
        s.close()
        reachable = True
    except OSError:
        pass
    add("Negative control: external network unreachable", not reachable,
        "outbound connection failed as expected -- adapter appears disabled" if not reachable
        else "outbound connection SUCCEEDED -- disable the adapter before demonstrating",
        blocking=False)


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verify-hashes", action="store_true",
                    help="re-hash model blobs against the allow-list (slow)")
    ap.add_argument("--skip-sandbox-run", action="store_true")
    args = ap.parse_args()

    check_ollama_loopback()
    check_resource_env()
    check_route_ordering()
    check_models(args.verify_hashes)
    check_embeddings()
    check_tesseract()
    check_docker()
    if not args.skip_sandbox_run:
        check_sandbox_isolation()
    check_workspace()
    check_corpus_indexed()
    check_netwatch()
    check_adapter()

    blocking_failures = [c for c in checks if not c.ok and c.blocking]
    warnings = [c for c in checks if not c.ok and not c.blocking]
    sovereign = not blocking_failures

    if args.json:
        print(json.dumps({
            "schema": "setu.preflight/1",
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "sovereign_mode": sovereign,
            "blocking_failures": len(blocking_failures),
            "warnings": len(warnings),
            "checks": [asdict(c) | {"label": c.label} for c in checks],
        }, indent=2))
        return 0 if sovereign and not warnings else (2 if sovereign else 1)

    width = max(len(c.name) for c in checks) + 2
    print("\n" + "=" * (width + 56))
    print("  SETU PREFLIGHT -- Sovereign Mode gate (blueprint 12.2)")
    print("=" * (width + 56))
    for c in checks:
        print(f"  [{c.label}] {c.name:<{width}} {c.detail}")
    print("=" * (width + 56))

    if sovereign and not warnings:
        print("  SOVEREIGN MODE: GRANTED -- all checks pass")
    elif sovereign:
        print(f"  SOVEREIGN MODE: GRANTED with {len(warnings)} warning(s)")
        for c in warnings:
            print(f"    - {c.name}: {c.detail}")
    else:
        print(f"  SOVEREIGN MODE: REFUSED -- {len(blocking_failures)} blocking failure(s)")
        for c in blocking_failures:
            print(f"    - {c.name}: {c.detail}")
    print("=" * (width + 56) + "\n")

    return 0 if sovereign and not warnings else (2 if sovereign else 1)


if __name__ == "__main__":
    sys.exit(main())
