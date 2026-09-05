"""
Connection classifier tests.  OWNER: P4.

STATUS NOTE.  The blueprint refers to "26 passing tests" that already existed.
They did not exist in this repository - see docs/STATUS.md.  This file was
written from the behaviour specified in blueprint section 3.2 and includes,
verbatim, the three assertions the blueprint states in the text.
"""

from __future__ import annotations

import pytest

from netwatch_classifier import (
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

TRUSTED = parse_subnet("192.168.50.0/24")


# -- loopback ----------------------------------------------------------------


@pytest.mark.parametrize(
    "addr",
    ["127.0.0.1", "127.0.0.53", "127.255.255.254", "::1", "::ffff:127.0.0.1"],
)
def test_loopback_addresses(addr):
    assert classify_address(addr, TRUSTED) == LOOPBACK


def test_loopback_without_a_configured_subnet():
    assert classify_address("127.0.0.1", None) == LOOPBACK


# -- trusted LAN -------------------------------------------------------------


@pytest.mark.parametrize("addr", ["192.168.50.1", "192.168.50.20", "192.168.50.254"])
def test_inside_the_configured_subnet_is_trusted(addr):
    assert classify_address(addr, TRUSTED) == TRUSTED_LAN


def test_ipv4_mapped_ipv6_inside_the_subnet_is_trusted():
    assert classify_address("::ffff:192.168.50.20", TRUSTED) == TRUSTED_LAN


def test_no_subnet_configured_means_nothing_is_trusted_lan():
    assert classify_address("192.168.50.20", None) == EXTERNAL


# -- the three assertions the blueprint states verbatim ----------------------


def test_docker_bridge_is_not_trusted_for_being_private():
    assert classify_address("172.17.0.2", TRUSTED) == EXTERNAL


def test_wsl_nat_is_not_trusted_for_being_private():
    assert classify_address("172.29.128.1", TRUSTED) == EXTERNAL


def test_a_different_private_slash24_is_not_trusted():
    assert classify_address("192.168.99.5", TRUSTED) == EXTERNAL


# -- external ----------------------------------------------------------------


@pytest.mark.parametrize(
    "addr",
    ["8.8.8.8", "1.1.1.1", "10.0.0.5", "172.16.4.4", "203.0.113.7", "2606:4700:4700::1111"],
)
def test_everything_else_is_external(addr):
    assert classify_address(addr, TRUSTED) == EXTERNAL


def test_ip_is_private_is_deliberately_not_used():
    """RFC1918 membership is not trust.  All four are private and all four are
    outside the configured subnet, so all four are external."""
    for addr in ("10.1.2.3", "172.20.0.1", "192.168.1.1", "192.168.51.1"):
        assert classify_address(addr, TRUSTED) == EXTERNAL


# -- unknown -----------------------------------------------------------------


@pytest.mark.parametrize("addr", [None, "", "   ", "not-an-ip", "999.1.1.1", "example.com"])
def test_missing_or_unparseable_is_unknown(addr):
    assert classify_address(addr, TRUSTED) == UNKNOWN


def test_zone_id_is_stripped_before_parsing():
    assert classify_address("fe80::1%eth0", TRUSTED) == EXTERNAL


# -- subnet parsing ----------------------------------------------------------


def test_parse_subnet_none_and_blank():
    assert parse_subnet(None) is None
    assert parse_subnet("") is None
    assert parse_subnet("   ") is None


def test_parse_subnet_rejects_garbage():
    with pytest.raises(ValueError):
        parse_subnet("not-a-subnet")


def test_parse_subnet_accepts_host_bits_set():
    assert str(parse_subnet("192.168.50.7/24")) == "192.168.50.0/24"


def test_v4_address_is_never_inside_a_v6_network():
    v6 = parse_subnet("fd00::/8")
    assert classify_address("192.168.50.20", v6) == EXTERNAL


# -- connection state --------------------------------------------------------


def test_listening_sockets_are_not_connections():
    assert is_connection("LISTEN") is False
    assert is_connection("NONE") is False
    assert is_connection(None) is False
    assert is_connection("ESTABLISHED") is True


def test_listening_sockets_are_excluded_from_counts():
    conns = [
        {"raddr": None, "status": "LISTEN"},
        {"raddr": "127.0.0.1", "status": "ESTABLISHED"},
        {"raddr": "192.168.50.20", "status": "ESTABLISHED"},
        {"raddr": "8.8.8.8", "status": "ESTABLISHED"},
    ]
    counts = classify_connections(conns, TRUSTED)
    assert counts == {LOOPBACK: 1, TRUSTED_LAN: 1, EXTERNAL: 1, UNKNOWN: 0}


def test_counts_are_zero_for_an_empty_sample():
    assert classify_connections([], TRUSTED) == {
        LOOPBACK: 0, TRUSTED_LAN: 0, EXTERNAL: 0, UNKNOWN: 0
    }


# -- sovereign mode ----------------------------------------------------------


def test_trusted_lan_traffic_never_fails_sovereign_mode():
    counts = {LOOPBACK: 1, TRUSTED_LAN: 5, EXTERNAL: 0, UNKNOWN: 0}
    assert sovereign_mode(counts) is True


def test_one_external_connection_fails_sovereign_mode():
    counts = {LOOPBACK: 1, TRUSTED_LAN: 0, EXTERNAL: 1, UNKNOWN: 0}
    assert sovereign_mode(counts) is False


def test_unknown_alone_does_not_fail_sovereign_mode_but_is_reported():
    counts = {LOOPBACK: 0, TRUSTED_LAN: 0, EXTERNAL: 0, UNKNOWN: 3}
    assert sovereign_mode(counts) is True
    assert counts[UNKNOWN] == 3
