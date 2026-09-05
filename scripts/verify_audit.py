"""
Walk the audit hash chain.  OWNER: P6.

    python scripts/verify_audit.py
    python scripts/verify_audit.py --path logs/audit.jsonl --json
    python scripts/verify_audit.py --show 20        # tail the chain as blocks

Exit codes: 0 chain intact, 1 chain broken, 2 could not read the log.

WHAT A GREEN RESULT MEANS.  Every entry hashes the previous one over a canonical
serialisation, so a SELECTIVE edit - changing one line and leaving the rest -
breaks the chain at that line.  It does NOT mean nobody could rewrite the whole
file: an attacker with operator filesystem access can recompute every hash.
Tamper-evident, not tamper-proof, and that is the honest claim to make.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.security.audit import verify_chain  # noqa: E402


def default_path() -> Path:
    return Path(os.environ.get("SETU_AUDIT_PATH", str(REPO_ROOT / "logs" / "audit.jsonl")))


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the SETU audit chain")
    parser.add_argument("--path", default=None, help="audit JSONL path")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--show", type=int, default=0, help="print the last N entries")
    args = parser.parse_args()

    path = Path(args.path) if args.path else default_path()
    if not path.exists():
        message = "no audit log at %s (nothing has run yet)" % path
        print(json.dumps({"ok": True, "reason": message}) if args.json else message)
        return 0

    result = verify_chain(path)

    if args.json:
        print(result.model_dump_json(indent=2))
    else:
        print("audit log : %s" % path)
        print("entries   : %d" % result.entries_checked)
        if result.ok:
            print("CHAIN INTACT - every entry hashes the one before it.")
            print("(Tamper-evident within stated assumptions: a selective edit is")
            print(" detectable; a full rewrite by an operator-level attacker is not.)")
        else:
            print("CHAIN BROKEN at line %s" % result.broken_at)
            print("reason    : %s" % result.reason)

    if args.show:
        entries = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ][-args.show :]
        print("\n--- last %d entries ---" % len(entries))
        for entry in entries:
            print(
                "%s  %-22s %-10s attempt=%s  %s <- %s"
                % (
                    entry.get("ts", "")[:19],
                    entry.get("action", ""),
                    str(entry.get("result", ""))[:10],
                    entry.get("attempt"),
                    str(entry.get("entry_hash", ""))[7:19],
                    str(entry.get("prev_hash", ""))[7:19],
                )
            )

    return 0 if result.ok else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OSError as exc:
        print("could not read the audit log: %s" % exc, file=sys.stderr)
        raise SystemExit(2)
