"""
Layer 8 - same-origin frontend, CORS off by default.  OWNER: P4.

STATUS: NEWLY SCAFFOLDED BY P1 (2026-09-05).  The blueprint marks this file
"DONE - do not modify"; it did not exist in this repository.  Written to the
behaviour specified in blueprint 3.8 / 12.5 and covered by tests.

The real deployment installs NO CORS middleware at all, because the browser
loads the UI from the same origin it calls (`frontend/dist` is mounted on the
same FastAPI app).  There is no cross-origin request, so there is no header to
misconfigure.

Dev mode is the one exception, and it is gated twice:

  SETU_DEV_MODE unset                 -> middleware NOT installed
  SETU_DEV_MODE=1 + SETU_DEV_ORIGINS  -> installed, scoped to exactly those origins
  SETU_DEV_MODE=1, origins unset      -> NOT installed, warning logged (fail closed)

`allow_origins=["*"]` is never produced by this module under any input.  A
wildcard would let any site a colleague happens to have open reach a
LAN-scoped backend, defeating the subnet scoping the firewall enforces.
"""

from __future__ import annotations

import logging

from ..config import Settings

log = logging.getLogger("setu.security.cors")

WILDCARD = "*"


def cors_decision(settings: Settings) -> tuple[bool, list[str], str]:
    """Pure decision function, so the policy is testable without an app.

    Returns (install, origins, reason).
    """
    if not settings.dev_mode:
        return False, [], "dev mode off: same-origin deployment, no CORS header installed"
    origins = [o for o in settings.dev_origins if o and o != WILDCARD]
    if len(origins) != len(settings.dev_origins):
        return (
            False,
            [],
            "SETU_DEV_ORIGINS contained a wildcard; refusing to install permissive CORS",
        )
    if not origins:
        return (
            False,
            [],
            "SETU_DEV_MODE=1 but SETU_DEV_ORIGINS is empty; failing closed "
            "(no middleware installed)",
        )
    return True, origins, "dev mode on, scoped to explicit origins"


def apply_cors(app, settings: Settings) -> tuple[bool, str]:
    """Install the middleware if and only if the decision says so."""
    install, origins, reason = cors_decision(settings)
    if not install:
        log.warning("CORS not installed: %s", reason)
        return False, reason
    from starlette.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )
    log.warning("CORS INSTALLED for dev origins %s - never do this on the demo box", origins)
    return True, reason
