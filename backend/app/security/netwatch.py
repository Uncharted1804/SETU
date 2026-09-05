"""
Layer 9 - three-way network classification.  OWNER: P4.

Thin re-export of scripts/netwatch_classifier.py (the single source of truth)
plus the live sampler that backs GET /api/network-status.

STATUS: NEWLY SCAFFOLDED BY P1 (2026-09-05); the blueprint marks it DONE but it
did not exist here.

HONESTY CONTRACT - read this before writing any UI copy against it:

  * `external_active` is a count of connections observed IN ONE SAMPLE of this
    process's sockets.  Zero means "nothing external was open when we looked",
    not "no packet has ever left this machine".  `scope` and `sampled_at` carry
    that qualification into the API response so the panel can render it.
  * If psutil cannot enumerate sockets (permissions, platform), we set
    `monitor_available=False` and surface the error.  We never emit zeros from a
    failed sample, because a zero the user cannot distinguish from a failure is
    worse than no number at all.
  * `blocked_external_attempts` is tracked SEPARATELY from `external_active` and
    is never added into it.  A successful negative control must not make the
    panel look like a leak.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_SCRIPTS = Path(__file__).resolve().parent.parent.parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from netwatch_classifier import (  # noqa: E402  (path shim above is intentional)
    EXTERNAL,
    LOOPBACK,
    TRUSTED_LAN,
    UNKNOWN,
    classify_address,
    classify_connections,
    is_connection,
    parse_subnet,
    sovereign_mode,
)

from ..config import Settings  # noqa: E402
from ..contracts import NegativeControl, NetworkStatus  # noqa: E402

__all__ = [
    "classify_address",
    "classify_connections",
    "is_connection",
    "parse_subnet",
    "sovereign_mode",
    "LOOPBACK",
    "TRUSTED_LAN",
    "EXTERNAL",
    "UNKNOWN",
    "NetworkMonitor",
]


class NetworkMonitor:
    """Samples this process's sockets and classifies them.

    Negative-control attempts are recorded by whoever performs them (the
    offline_check script, or a UI-triggered probe) via `record_blocked_attempt`.
    This module never performs an outbound request itself.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._blocked_attempts = 0
        self._blocked_all = True

    def record_blocked_attempt(self, blocked: bool) -> None:
        self._blocked_attempts += 1
        if not blocked:
            self._blocked_all = False

    def sample(self) -> NetworkStatus:
        trusted_raw = self.settings.trusted_subnet
        trusted = parse_subnet(trusted_raw)
        mode = "lan" if trusted_raw else "single_laptop"
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")

        counts = None
        monitor_error: Optional[str] = None
        try:
            import psutil

            proc = psutil.Process(os.getpid())
            raw = []
            for c in proc.net_connections(kind="inet"):
                raw.append(
                    {
                        "raddr": c.raddr.ip if c.raddr else None,
                        "status": c.status,
                    }
                )
            counts = classify_connections(raw, trusted)
        except Exception as exc:  # psutil missing, permission denied, platform quirk
            monitor_error = "%s: %s" % (type(exc).__name__, exc)

        if counts is None:
            # Fail visibly.  Never emit zeros from a failed sample.
            return NetworkStatus(
                mode=mode,
                trusted_subnet=trusted_raw,
                loopback_active=0,
                trusted_lan_active=0,
                external_active=0,
                unknown_active=0,
                sovereign_mode=False,
                negative_control=NegativeControl(
                    blocked_external_attempts=self._blocked_attempts,
                    all_blocked=self._blocked_all,
                ),
                monitor_available=False,
                monitor_error=monitor_error,
                sampled_at=now,
                scope="UNAVAILABLE - counts below are placeholders, not evidence",
            )

        return NetworkStatus(
            mode=mode,
            trusted_subnet=trusted_raw,
            loopback_active=counts[LOOPBACK],
            trusted_lan_active=counts[TRUSTED_LAN],
            external_active=counts[EXTERNAL],
            unknown_active=counts[UNKNOWN],
            sovereign_mode=sovereign_mode(counts),
            negative_control=NegativeControl(
                blocked_external_attempts=self._blocked_attempts,
                all_blocked=self._blocked_all,
            ),
            monitor_available=True,
            sampled_at=now,
            scope="setu backend process sockets, single sample",
        )
