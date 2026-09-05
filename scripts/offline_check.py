"""
SETU offline_check.py -- the three-part network proof (blueprint section 12.3)

  1. ENFORCEMENT     adapter state; the sandbox has no network interface
  2. OBSERVATION     external sockets held by SETU processes = 0, with elapsed time
  3. NEGATIVE CONTROL an ordinary external request fails while local tasks continue

Deliberately does NOT claim a host-wide zero. Windows keeps unrelated system
connections alive, and claiming otherwise is the easiest way to lose credibility
in front of a judge who knows that. This reports SETU-process scope and adapter
state separately, exactly as the blueprint requires.

Run it during the T-1 rehearsal and screenshot the output -- it is demo evidence.

Usage:
    python scripts/offline_check.py
    python scripts/offline_check.py --json
    python scripts/offline_check.py --watch 300     # monitor for 5 minutes
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

SETU_PROCESS_NAMES = {"ollama", "ollama.exe", "ollama app.exe",
                      "python", "python.exe", "pythonw.exe", "uvicorn", "node"}
LOOPBACK = {"127.0.0.1", "::1", "0.0.0.0", "::", ""}

NEGATIVE_CONTROL_TARGETS = [
    ("https://example.com", "HTTP to a well-known public host"),
    ("1.1.1.1", 53, "raw TCP to a public DNS resolver"),
]


# ---------------------------------------------------------------------------
# 1. Enforcement
# ---------------------------------------------------------------------------
def adapter_state() -> list[dict]:
    """Best-effort adapter enumeration. Advisory: the screenshot is the proof."""
    adapters = []
    if sys.platform == "win32":
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-NetAdapter | Select-Object Name,Status,InterfaceDescription "
                 "| ConvertTo-Json -Compress"],
                capture_output=True, text=True, timeout=30,
            )
            data = json.loads(out.stdout) if out.stdout.strip() else []
            if isinstance(data, dict):
                data = [data]
            for a in data:
                adapters.append({"name": a.get("Name"), "status": a.get("Status"),
                                 "description": a.get("InterfaceDescription")})
        except Exception as exc:  # noqa: BLE001
            adapters.append({"error": str(exc)})
    else:
        try:
            out = subprocess.run(["ip", "-o", "link", "show"],
                                 capture_output=True, text=True, timeout=15)
            for line in out.stdout.splitlines():
                parts = line.split(":")
                if len(parts) > 2:
                    name = parts[1].strip()
                    adapters.append({"name": name,
                                     "status": "Up" if "UP" in parts[2] else "Down"})
        except Exception as exc:  # noqa: BLE001
            adapters.append({"error": str(exc)})
    return adapters


def sandbox_has_no_network() -> tuple[bool, str]:
    """Run the real sandbox profile and confirm it cannot reach the network."""
    try:
        out = subprocess.run(
            ["docker", "run", "--rm", "--network=none", "--read-only",
             "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
             "--cap-drop=ALL", "--security-opt=no-new-privileges",
             "--user=65534:65534", "-e", "HOME=/tmp",
             "setu-sandbox:py311", "-c",
             "import socket,sys\n"
             "try:\n"
             "    socket.create_connection(('1.1.1.1',53),timeout=4)\n"
             "    print('REACHABLE'); sys.exit(1)\n"
             "except OSError as e:\n"
             "    print('unreachable:', type(e).__name__)"],
            capture_output=True, text=True, timeout=120,
        )
        return out.returncode == 0, (out.stdout or out.stderr).strip()[:160]
    except FileNotFoundError:
        return False, "docker not found"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


# ---------------------------------------------------------------------------
# 2. Observation
# ---------------------------------------------------------------------------
def scan_setu_sockets() -> dict:
    try:
        import psutil  # type: ignore
    except ImportError:
        return {"error": "psutil not installed -- activate the venv"}

    watched, external, loopback_count, denied = [], [], 0, 0
    for proc in psutil.process_iter(["name", "pid", "cmdline"]):
        name = (proc.info.get("name") or "").lower()
        if name not in {n.lower() for n in SETU_PROCESS_NAMES}:
            continue
        cmd = " ".join(proc.info.get("cmdline") or [])[:100]
        entry = {"pid": proc.info["pid"], "name": name, "cmdline": cmd, "sockets": 0}
        try:
            for conn in proc.net_connections(kind="inet"):
                entry["sockets"] += 1
                raddr = getattr(conn, "raddr", None)
                if raddr and raddr.ip not in LOOPBACK:
                    external.append({"pid": proc.info["pid"], "name": name,
                                     "remote": f"{raddr.ip}:{raddr.port}",
                                     "status": conn.status})
                else:
                    loopback_count += 1
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            denied += 1
            entry["sockets"] = "access denied"
        watched.append(entry)

    return {
        "processes": watched,
        "process_count": len(watched),
        "loopback_sockets": loopback_count,
        "external_sockets": external,
        "external_count": len(external),
        "access_denied": denied,
        "inspectable": denied == 0,
    }


# ---------------------------------------------------------------------------
# 3. Negative control
# ---------------------------------------------------------------------------
def negative_control() -> list[dict]:
    results = []
    for target in NEGATIVE_CONTROL_TARGETS:
        if len(target) == 2:
            url, desc = target
            try:
                urllib.request.urlopen(url, timeout=8)
                results.append({"target": url, "description": desc,
                                "blocked": False, "detail": "SUCCEEDED -- not offline"})
            except Exception as exc:  # noqa: BLE001
                results.append({"target": url, "description": desc,
                                "blocked": True, "detail": f"{type(exc).__name__}"})
        else:
            host, port, desc = target
            try:
                s = socket.create_connection((host, port), timeout=6)
                s.close()
                results.append({"target": f"{host}:{port}", "description": desc,
                                "blocked": False, "detail": "SUCCEEDED -- not offline"})
            except OSError as exc:
                results.append({"target": f"{host}:{port}", "description": desc,
                                "blocked": True, "detail": f"{type(exc).__name__}"})
    return results


def local_still_works() -> tuple[bool, str]:
    """The other half of the negative control: SETU keeps working."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=10) as r:
            n = len(json.loads(r.read()).get("models", []))
        return True, f"Ollama responded on loopback with {n} models"
    except Exception as exc:  # noqa: BLE001
        return False, f"local model server unreachable: {exc}"


# ---------------------------------------------------------------------------
def build_report() -> dict:
    adapters = adapter_state()
    up = [a for a in adapters if a.get("status") in ("Up", "UP")
          and a.get("name", "").lower() not in ("lo", "loopback")]
    sandbox_ok, sandbox_detail = sandbox_has_no_network()
    sockets = scan_setu_sockets()
    neg = negative_control()
    local_ok, local_detail = local_still_works()

    return {
        "schema": "setu.offline_check/1",
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "enforcement": {
            "adapters": adapters,
            "non_loopback_adapters_up": [a.get("name") for a in up],
            "sandbox_networkless": sandbox_ok,
            "sandbox_detail": sandbox_detail,
        },
        "observation": sockets,
        "negative_control": {
            "attempts": neg,
            "all_blocked": all(r["blocked"] for r in neg),
            "local_still_works": local_ok,
            "local_detail": local_detail,
        },
        "scope_note": (
            "External socket count is scoped to the named SETU processes only. "
            "This is not a host-wide claim; Windows maintains unrelated system "
            "connections. Adapter state is reported separately."
        ),
    }


def print_report(rep: dict) -> None:
    print("\n" + "=" * 74)
    print("  SETU OFFLINE VERIFICATION -- blueprint 12.3")
    print(f"  {rep['timestamp']}")
    print("=" * 74)

    e = rep["enforcement"]
    print("\n  [1] ENFORCEMENT")
    for a in e["adapters"][:8]:
        if "error" in a:
            print(f"      adapter query error: {a['error']}")
            continue
        mark = "UP  " if a.get("status") in ("Up", "UP") else "DOWN"
        print(f"      {mark}  {a.get('name')}  {(a.get('description') or '')[:44]}")
    if e["non_loopback_adapters_up"]:
        print(f"      >> STILL UP: {', '.join(e['non_loopback_adapters_up'])}")
        print("      >> Disable these before demonstrating the air-gap claim.")
    else:
        print("      >> No non-loopback adapter is up.")
    print(f"      sandbox --network=none: {'CONFIRMED' if e['sandbox_networkless'] else 'NOT CONFIRMED'}"
          f"  ({e['sandbox_detail']})")

    o = rep["observation"]
    print("\n  [2] OBSERVATION (SETU process scope only)")
    if "error" in o:
        print(f"      {o['error']}")
    else:
        print(f"      monitored processes: {o['process_count']}")
        for p in o["processes"][:8]:
            print(f"        pid {p['pid']:<7} {p['name']:<16} sockets={p['sockets']}")
        print(f"      loopback sockets: {o['loopback_sockets']}")
        print(f"      EXTERNAL sockets: {o['external_count']}")
        for x in o["external_sockets"][:5]:
            print(f"        !! {x['name']} pid {x['pid']} -> {x['remote']} ({x['status']})")
        if not o["inspectable"]:
            print(f"      note: {o['access_denied']} process(es) denied inspection "
                  "-- run as the owning user, or the monitor cannot make its claim")

    n = rep["negative_control"]
    print("\n  [3] NEGATIVE CONTROL")
    for r in n["attempts"]:
        mark = "BLOCKED " if r["blocked"] else "REACHED!"
        print(f"      {mark} {r['target']:<26} {r['description']}  [{r['detail']}]")
    print(f"      local SETU still working: {'YES' if n['local_still_works'] else 'NO'}"
          f"  ({n['local_detail']})")

    print("\n" + "-" * 74)
    verdict_ok = (
        not e["non_loopback_adapters_up"]
        and n["all_blocked"]
        and n["local_still_works"]
        and o.get("external_count", 1) == 0
    )
    if verdict_ok:
        print("  RESULT: offline posture verified on all three axes.")
        print("  Safe to state: adapter down, zero external sockets on SETU processes,")
        print("  external request fails while local workflow continues.")
    else:
        print("  RESULT: NOT fully verified. Do not make the air-gap claim yet.")
    print("  " + rep["scope_note"])
    print("=" * 74 + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--watch", type=int, metavar="SECONDS",
                    help="re-scan sockets every 10s for this long and report the max")
    args = ap.parse_args()

    rep = build_report()

    if args.watch:
        print(f"[*] watching SETU sockets for {args.watch}s ...")
        start, peak = time.time(), rep["observation"].get("external_count", 0)
        while time.time() - start < args.watch:
            time.sleep(10)
            s = scan_setu_sockets()
            peak = max(peak, s.get("external_count", 0))
            elapsed = int(time.time() - start)
            print(f"    t+{elapsed:>4}s  external={s.get('external_count', '?')}  "
                  f"loopback={s.get('loopback_sockets', '?')}")
        rep["observation"]["peak_external_over_watch"] = peak
        rep["observation"]["watch_seconds"] = args.watch

    if args.json:
        print(json.dumps(rep, indent=2))
    else:
        print_report(rep)

    e, o, n = rep["enforcement"], rep["observation"], rep["negative_control"]
    ok = (not e["non_loopback_adapters_up"] and n["all_blocked"]
          and n["local_still_works"] and o.get("external_count", 1) == 0)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
