"""
Audit chain tests.  OWNER: P6.

Tamper-evident within stated assumptions: a SELECTIVE edit is detectable.  A
rewrite of the whole file by someone with operator filesystem access is not, and
these tests do not pretend otherwise.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.security.audit import GENESIS, AuditLog, args_digest, compute_hash, verify_chain


@pytest.fixture()
def log(tmp_path):
    return AuditLog(tmp_path / "logs" / "audit.jsonl")


def _append(log, **kwargs):
    return asyncio.run(
        log.append(task_id="t_1", session="s_1", action="test", result="ok", **kwargs)
    )


def test_empty_log_verifies():
    from pathlib import Path

    result = verify_chain(Path("does-not-exist.jsonl"))
    assert result.ok is True
    assert result.entries_checked == 0


def test_first_entry_links_to_genesis(log):
    entry = _append(log)
    assert entry.prev_hash == GENESIS
    assert entry.entry_hash.startswith("sha256:")


def test_chain_links_forward(log):
    a = _append(log)
    b = _append(log)
    c = _append(log)
    assert b.prev_hash == a.entry_hash
    assert c.prev_hash == b.entry_hash


def test_a_clean_chain_verifies(log):
    for _ in range(5):
        _append(log)
    result = verify_chain(log.path)
    assert result.ok is True
    assert result.entries_checked == 5


def test_tampering_with_a_line_breaks_verification(log):
    for _ in range(3):
        _append(log)
    lines = log.path.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[1])
    entry["result"] = "tampered"
    lines[1] = json.dumps(entry, ensure_ascii=False)
    log.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = verify_chain(log.path)
    assert result.ok is False
    assert result.broken_at == 1
    assert "modified" in (result.reason or "")


def test_removing_a_line_breaks_verification(log):
    for _ in range(4):
        _append(log)
    lines = log.path.read_text(encoding="utf-8").splitlines()
    del lines[1]
    log.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = verify_chain(log.path)
    assert result.ok is False
    assert result.broken_at == 1


def test_canonical_hashing_is_key_order_independent():
    """sort_keys + fixed separators, or the verifier fails on correct data."""
    a = {"ts": "1", "action": "x", "result": "ok"}
    b = {"result": "ok", "action": "x", "ts": "1"}
    assert compute_hash(a) == compute_hash(b)


def test_entry_hash_is_excluded_from_its_own_hash():
    entry = {"ts": "1", "action": "x", "result": "ok"}
    without = compute_hash(entry)
    entry["entry_hash"] = without
    assert compute_hash(entry) == without


def test_every_attempt_is_recordable(log):
    for n in (1, 2, 3):
        _append(log, attempt=n, step=1, iteration=1, model="qwen3-vl:4b")
    entries = log.read_all()
    assert [e["attempt"] for e in entries] == [1, 2, 3]
    assert verify_chain(log.path).ok


def test_arguments_are_digested_not_copied(log):
    """Task, step and attempt context is logged in the clear; document content
    is not copied wholesale into a file with a different retention policy."""
    secret = "CONFIDENTIAL vendor pricing schedule"
    entry = _append(log, args={"content": secret})
    raw = log.path.read_text(encoding="utf-8")
    assert secret not in raw
    assert entry.args_hash.startswith("sha256:")


def test_args_digest_is_stable():
    assert args_digest({"a": 1, "b": 2}) == args_digest({"b": 2, "a": 1})


def test_concurrent_appends_do_not_break_the_chain(log):
    async def hammer():
        await asyncio.gather(
            *[
                log.append(task_id="t_%d" % i, session="s", action="a", result="ok")
                for i in range(20)
            ]
        )

    asyncio.run(hammer())
    result = verify_chain(log.path)
    assert result.ok is True
    assert result.entries_checked == 20


def test_audit_lives_outside_the_agent_writable_workspace(env):
    """The agent's writable world is data/workspace; the audit log is not in it."""
    assert not str(env.audit_path).startswith(str(env.workspace))
