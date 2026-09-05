"""
Layer 5 - the append-only, hash-chained audit log.  OWNER: P6.

Tamper-EVIDENT, not tamper-proof, and the distinction matters when a judge asks.
The assumptions under which the claim holds:

  * The log file lives OUTSIDE the agent-writable workspace (logs/audit.jsonl by
    default).  No registered tool can reach it - there is no delete_file tool and
    the path jail confines every write to data/workspace.
  * An attacker with filesystem access as the operator can rewrite the whole
    chain.  What the chain buys you is that a SELECTIVE edit - changing one line
    and leaving the rest - is detectable, which is the realistic internal-audit
    threat model.

The hashing detail that costs an hour at 2 a.m. if you get it wrong
(blueprint 12.2): the payload is serialised with `sort_keys=True` and
`separators=(",", ":")`, and `entry_hash` is removed before hashing.  Verifier
and writer must agree byte for byte.

Appends are serialised through an asyncio lock so two concurrent steps cannot
interleave and break the chain.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..contracts import AuditEntry, AuditVerification

GENESIS = "sha256:GENESIS"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def canonical_payload(entry: dict[str, Any]) -> bytes:
    """The exact bytes that get hashed.  Writer and verifier share this function."""
    body = {k: v for k, v in entry.items() if k != "entry_hash"}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_hash(entry: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_payload(entry)).hexdigest()


def args_digest(args: Any) -> str:
    """Hash of a step's arguments.

    We log the DIGEST rather than the arguments themselves so a scanned
    inspection report or a vendor letter is not copied wholesale into an audit
    file that has a different retention policy from the workspace.  Task, step
    and attempt context is logged in the clear, because that is what an auditor
    needs to follow the sequence.
    """
    try:
        blob = json.dumps(args, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        blob = repr(args)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


class AuditLog:
    """Serialised writer over one JSONL file."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._alock = asyncio.Lock()
        self._tlock = threading.Lock()

    # -- reading -------------------------------------------------------------

    def last_hash(self) -> str:
        if not self.path.is_file():
            return GENESIS
        last = GENESIS
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    last = json.loads(line).get("entry_hash", last)
                except json.JSONDecodeError:
                    continue
        return last

    def read_all(self, limit: Optional[int] = None) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        out: list[dict[str, Any]] = []
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    out.append({"_malformed": line})
        if limit is not None:
            return out[-limit:]
        return out

    # -- writing -------------------------------------------------------------

    def _append_sync(self, entry: dict[str, Any]) -> dict[str, Any]:
        with self._tlock:
            entry = dict(entry)
            entry["prev_hash"] = self.last_hash()
            entry.pop("entry_hash", None)
            entry["entry_hash"] = compute_hash(entry)
            with open(self.path, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            return entry

    async def append(
        self,
        *,
        task_id: str,
        session: str,
        action: str,
        result: str,
        args: Any = None,
        user: str = "local",
        model: Optional[str] = None,
        route_confidence: Optional[float] = None,
        attempt: Optional[int] = None,
        step: Optional[int] = None,
        iteration: Optional[int] = None,
    ) -> AuditEntry:
        """Append one entry.  Every attempt is audited, not just the final one."""
        raw = {
            "ts": _now(),
            "session": session,
            "task_id": task_id,
            "user": user,
            "action": action,
            "args_hash": args_digest(args),
            "model": model,
            "route_confidence": route_confidence,
            "attempt": attempt,
            "step": step,
            "iteration": iteration,
            "result": result,
        }
        async with self._alock:
            written = await asyncio.to_thread(self._append_sync, raw)
        return AuditEntry(**written)


def verify_chain(path: Path) -> AuditVerification:
    """Walk the chain.  Returns the first break, if any.

    Used by scripts/verify_audit.py and by GET /api/audit/verify.
    """
    p = Path(path)
    if not p.is_file():
        return AuditVerification(
            ok=True, entries_checked=0, reason="no audit file yet", path=str(p)
        )
    prev = GENESIS
    checked = 0
    with open(p, "r", encoding="utf-8") as fh:
        for idx, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                return AuditVerification(
                    ok=False,
                    entries_checked=checked,
                    broken_at=idx,
                    reason="line %d is not valid JSON: %s" % (idx, exc),
                    path=str(p),
                )
            if entry.get("prev_hash") != prev:
                return AuditVerification(
                    ok=False,
                    entries_checked=checked,
                    broken_at=idx,
                    reason="prev_hash mismatch at line %d: chain is broken or an "
                    "entry was removed" % idx,
                    path=str(p),
                )
            recomputed = compute_hash(entry)
            if recomputed != entry.get("entry_hash"):
                return AuditVerification(
                    ok=False,
                    entries_checked=checked,
                    broken_at=idx,
                    reason="entry_hash mismatch at line %d: this line was modified" % idx,
                    path=str(p),
                )
            prev = entry["entry_hash"]
            checked += 1
    return AuditVerification(ok=True, entries_checked=checked, path=str(p))
