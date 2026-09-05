"""
SETU connection classifier - the single source of truth for the four buckets.

OWNER: P4.

STATUS: NEWLY SCAFFOLDED BY P1 (2026-09-05).  The blueprint (Part 0.3 / Part 7)
describes this file as already built with 26 passing tests.  It did not exist in
this repository.  This implementation is written to the blueprint's specified
behaviour (section 3.2) and covered by backend/tests/test_netwatch_classifier.py,
which includes the three assertions the blueprint states verbatim.  P4 owns it
from here; treat it as a baseline, not as previously reviewed code.

The four buckets (blueprint 3.2):

  loopback             127.0.0.0/8, ::1, IPv4-mapped IPv6 loopback
  trusted_lan          inside the EXPLICITLY CONFIGURED subnet only
  external_unapproved  everything else - public IPs AND other private ranges
                       (Docker bridges, WSL NAT, a different 192.168.x/24)
  unknown              missing or unparseable remote address

Two decisions defended out loud:

  * `ip.is_private` is DELIBERATELY NOT USED.  RFC1918 membership is not trust.
    A stray Docker bridge at 172.17.0.2 or a VPN adapter is external unless it
    is inside the one subnet an operator actually configured.
  * LISTENING sockets are never connections.  A socket in LISTEN state is
    waiting for a peer, not talking to one, and counting it would be nonsense.
"""

from __future__ import annotations

import ipaddress
from typing import Iterable, Optional

Bucket = str  # "loopback" | "trusted_lan" | "external_unapproved" | "unknown"

LOOPBACK = "loopback"
TRUSTED_LAN = "trusted_lan"
EXTERNAL = "external_unapproved"
UNKNOWN = "unknown"

#: Socket states that are NOT an active connection to a peer.
NON_CONNECTION_STATES = frozenset({"LISTEN", "NONE", "CLOSED", "", None})


def parse_subnet(raw: Optional[str]) -> Optional[ipaddress._BaseNetwork]:
    """Parse a configured trusted subnet.  Returns None when unset.

    Raises ValueError when set-but-invalid so the caller can fail hard rather
    than silently degrade to "nothing is trusted" (blueprint 3.1: invalid
    config is a hard startup failure).
    """
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    return ipaddress.ip_network(value, strict=False)


def _normalise(addr: str) -> Optional[ipaddress._BaseAddress]:
    """Turn a remote address string into an ip address, unwrapping v4-mapped v6."""
    if addr is None:
        return None
    text = str(addr).strip()
    if not text:
        return None
    # Strip a zone id ("fe80::1%eth0") and any surrounding brackets.
    text = text.split("%", 1)[0].strip("[]")
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def classify_address(
    addr: Optional[str], trusted: Optional[ipaddress._BaseNetwork] = None
) -> Bucket:
    """Classify one remote address into exactly one of the four buckets."""
    ip = _normalise(addr) if addr is not None else None
    if ip is None:
        return UNKNOWN
    if ip.is_loopback:
        return LOOPBACK
    if trusted is not None:
        # Compare like with like: a v4 address is never inside a v6 network.
        if ip.version == trusted.version and ip in trusted:
            return TRUSTED_LAN
    # NOTE: no `ip.is_private` shortcut here.  That omission is the point.
    return EXTERNAL


def is_connection(state: Optional[str]) -> bool:
    """A socket counts as a connection only when it has a peer."""
    if state is None:
        return False
    return state.upper() not in NON_CONNECTION_STATES


def classify_connections(
    conns: Iterable[dict], trusted: Optional[ipaddress._BaseNetwork] = None
) -> dict[str, int]:
    """Count active connections per bucket.

    `conns` items are dicts with at least {"raddr": str|None, "status": str}.
    Listening sockets are excluded before classification.
    """
    counts = {LOOPBACK: 0, TRUSTED_LAN: 0, EXTERNAL: 0, UNKNOWN: 0}
    for conn in conns:
        if not is_connection(conn.get("status")):
            continue
        counts[classify_address(conn.get("raddr"), trusted)] += 1
    return counts


def sovereign_mode(counts: dict[str, int]) -> bool:
    """Sovereign iff no external connection is active.

    Trusted-LAN traffic NEVER fails this: colleagues using SETU is the
    deployment working as designed, not a fault.
    """
    return counts.get(EXTERNAL, 0) == 0
