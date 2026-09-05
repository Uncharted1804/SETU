"""
SETU configuration and model registry.  OWNER: P1.

Single source of truth for: run mode (mock vs real), paths, thresholds, attempt
budgets, the iteration cap, network topology and the model registry.

Design rule the blueprint is emphatic about (section 2.3, and the note appended
to the router pseudocode): model TAGS live in `config/models.yaml`, never in
router branches or agent files.  Adding or swapping a model for an existing
role is a YAML edit.  Adding a genuinely NEW capability is not - that needs an
agent implementation, and we say so out loud.

Startup assertions (blueprint 12.7).  The process refuses to start when:
  * OLLAMA_HOST is not a loopback address
  * SETU_TRUSTED_SUBNET is set but unparseable  (hard failure, never a silent
    fallback to single-laptop mode)
and CORS fails closed when SETU_DEV_MODE=1 without SETU_DEV_ORIGINS.

Nothing in this module downloads anything or imports a heavyweight dependency.
"""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import yaml

from .contracts import ModelEntry

VERSION = "0.1.0-scaffold"

# Repo root:  backend/app/config.py -> backend/app -> backend -> <repo>
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class ConfigError(RuntimeError):
    """Raised for a configuration state the process must not start with."""


# -----------------------------------------------------------------------------
# Policy constants - blueprint section 2.7.  Locked at Hour 0.  Do not tune
# these at 3 a.m.; change them here, in one place, with a reason in the commit.
# -----------------------------------------------------------------------------

THRESHOLDS: dict[str, float] = {"vision": 0.70, "reasoning": 0.65, "coding": 1.00}

#: Attempts, not retries.  vision 3 => 1 attempt + 2 retries.
MAX_ATTEMPTS: dict[str, int] = {"vision": 3, "reasoning": 3, "coding": 4}

#: Hard cap on DISPATCHED STEPS in one task.  Retries of a step do not consume
#: an iteration (contracts.py convention 5).  Not raised to fit a longer demo.
MAX_ITERATIONS: int = 5

#: Extensions that route to the vision entry agent.
VISION_EXTS: frozenset[str] = frozenset(
    {"pdf", "png", "jpg", "jpeg", "tif", "tiff", "webp", "bmp"}
)
#: Extensions that indicate spreadsheet work.
SHEET_EXTS: frozenset[str] = frozenset({"xlsx", "xls", "csv", "xlsm"})

CODE_SIGNALS: tuple[str, ...] = (
    "def ",
    "function",
    "traceback",
    "error:",
    ".py",
    "debug",
    "fix this code",
    "stack trace",
    "script",
    "compute",
    "calculate",
)

DOC_SIGNALS: tuple[str, ...] = (
    "word file",
    "word document",
    ".docx",
    "excel",
    "spreadsheet",
    "ppt",
    "powerpoint",
    "approval note",
    "deck",
    "report",
)


@dataclass(frozen=True)
class Settings:
    """Process configuration.  Built once at import of `get_settings()`."""

    # --- mode ---------------------------------------------------------------
    #: THE switch.  SETU_MOCK_MODE=1 (default) runs the whole system with
    #: deterministic adapters: no GPU, no Ollama, no Docker, no Tesseract, no
    #: embedding download, no knowledge base.  Same contracts, same dispatcher,
    #: same approval flow, same audit path, same SSE transport.
    mock_mode: bool = True

    # --- paths --------------------------------------------------------------
    workspace: Path = REPO_ROOT / "data" / "workspace"
    #: Audit lives OUTSIDE the agent-writable workspace, deliberately.
    audit_path: Path = REPO_ROOT / "logs" / "audit.jsonl"
    kb_path: Path = REPO_ROOT / "data" / "chroma"
    kb_corpus: Path = REPO_ROOT / "data" / "kb_corpus"
    templates: Path = REPO_ROOT / "templates"
    models_yaml: Path = REPO_ROOT / "config" / "models.yaml"
    frontend_dist: Path = REPO_ROOT / "frontend" / "dist"

    # --- model serving ------------------------------------------------------
    ollama_host: str = "127.0.0.1:11434"
    ollama_timeout_s: float = 120.0
    max_loaded_models: int = 1

    # --- network topology ---------------------------------------------------
    trusted_subnet: Optional[str] = None
    dev_mode: bool = False
    dev_origins: tuple[str, ...] = field(default_factory=tuple)

    # --- sandbox ------------------------------------------------------------
    sandbox_image: str = "setu-sandbox:py311"
    sandbox_timeout_s: int = 15

    @property
    def topology(self) -> str:
        return "lan" if self.trusted_subnet else "single_laptop"

    @property
    def bind_host(self) -> str:
        """LAN mode is opt-in.  Absent SETU_TRUSTED_SUBNET we bind loopback."""
        return "0.0.0.0" if self.trusted_subnet else "127.0.0.1"


def _truthy(value: Optional[str], default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _assert_loopback(host: str) -> None:
    """Blueprint 12.7: the backend refuses to start against a non-loopback Ollama."""
    raw = host if "//" in host else "http://" + host
    parsed = urlparse(raw)
    hostname = parsed.hostname or ""
    if hostname in {"localhost"}:
        return
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError as exc:
        raise ConfigError(
            "OLLAMA_HOST must be a loopback address; got %r (%s)" % (host, exc)
        ) from exc
    if not ip.is_loopback:
        raise ConfigError(
            "OLLAMA_HOST must be loopback-only (sovereignty layer 1); got %r" % host
        )


def _parse_trusted_subnet(raw: Optional[str]) -> Optional[str]:
    """Set but unparseable is a HARD failure - never a silent fallback."""
    if raw is None or raw.strip() == "":
        return None
    value = raw.strip()
    try:
        net = ipaddress.ip_network(value, strict=False)
    except ValueError as exc:
        raise ConfigError(
            "SETU_TRUSTED_SUBNET=%r is not a valid CIDR network: %s. "
            "Refusing to start rather than silently falling back to "
            "single-laptop mode." % (value, exc)
        ) from exc
    return str(net)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    env = os.environ
    host = env.get("OLLAMA_HOST", "127.0.0.1:11434")
    _assert_loopback(host)

    dev_mode = _truthy(env.get("SETU_DEV_MODE"), False)
    origins_raw = env.get("SETU_DEV_ORIGINS", "")
    origins = tuple(o.strip() for o in origins_raw.split(",") if o.strip())

    workspace = Path(env.get("SETU_WORKSPACE", str(REPO_ROOT / "data" / "workspace")))
    audit = Path(env.get("SETU_AUDIT_PATH", str(REPO_ROOT / "logs" / "audit.jsonl")))

    return Settings(
        mock_mode=_truthy(env.get("SETU_MOCK_MODE"), True),
        workspace=workspace.resolve(),
        audit_path=audit.resolve(),
        kb_path=Path(env.get("SETU_KB_PATH", str(REPO_ROOT / "data" / "chroma"))).resolve(),
        # P5 can point the backend at a dist built elsewhere; the demo box uses
        # the default so `npm run build` output is what gets served.
        frontend_dist=Path(
            env.get("SETU_FRONTEND_DIST", str(REPO_ROOT / "frontend" / "dist"))
        ).resolve(),
        ollama_host=host,
        ollama_timeout_s=float(env.get("SETU_OLLAMA_TIMEOUT", "120")),
        trusted_subnet=_parse_trusted_subnet(env.get("SETU_TRUSTED_SUBNET")),
        dev_mode=dev_mode,
        dev_origins=origins,
        sandbox_image=env.get("SETU_SANDBOX_IMAGE", "setu-sandbox:py311"),
        sandbox_timeout_s=int(env.get("SETU_SANDBOX_TIMEOUT", "15")),
    )


# -----------------------------------------------------------------------------
# Model registry
# -----------------------------------------------------------------------------

#: Capability -> the registry entry that serves it.  This mapping, plus
#: `config/models.yaml`, is the entire binding between a task and a model tag.
#: Neither router.py nor any agent module contains a model tag.
CAPABILITY_TAGS: dict[str, str] = {
    "vision": "vision",
    "planning": "planning",
    "code": "code",
}

#: Which YAML `capabilities` entry satisfies each router capability.
_CAPABILITY_MATCH: dict[str, tuple[str, ...]] = {
    "vision": ("vision",),
    "planning": ("planning", "drafting", "text"),
    "code": ("code", "calculation"),
}

#: Agent name -> capability it needs.
AGENT_CAPABILITY: dict[str, str] = {
    "vision": "vision",
    "reasoning": "planning",
    "coding": "code",
}


class ModelRegistry:
    """Reads `config/models.yaml`.  Never mutates it.

    The YAML on this machine is FROZEN at the T-5 benchmark gate and documents a
    deliberate Qwen3-family substitution for the blueprint's literal Qwen2.5
    tags.  See docs/DECISIONS.md D-002.
    """

    def __init__(self, entries: list[ModelEntry], defaults: dict) -> None:
        self._entries = entries
        self._by_id = {e.id: e for e in entries}
        self.defaults = defaults

    # -- construction --------------------------------------------------------

    @classmethod
    def from_yaml(cls, path: Path) -> "ModelRegistry":
        if not path.is_file():
            raise ConfigError("model registry not found at %s" % path)
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        defaults = raw.get("defaults") or {}
        entries: list[ModelEntry] = []
        for item in raw.get("models") or []:
            entries.append(
                ModelEntry(
                    id=item["id"],
                    provider=item.get("provider", defaults.get("provider", "ollama")),
                    model=item["model"],
                    capabilities=list(item.get("capabilities") or []),
                    context_limit=int(item.get("context_limit", 8192)),
                    max_output_tokens=int(item.get("max_output_tokens", 1024)),
                    temperature=float(item.get("temperature", 0.2)),
                    keep_alive=str(item.get("keep_alive", defaults.get("keep_alive", "10m"))),
                    enabled=bool(item.get("enabled", True)),
                    fallback=item.get("fallback"),
                    expected_manifest_digest=item.get("expected_manifest_digest") or "",
                    note=item.get("note"),
                    scope_note=item.get("scope_note"),
                )
            )
        if not entries:
            raise ConfigError("model registry at %s declares no models" % path)
        return cls(entries, defaults)

    # -- queries -------------------------------------------------------------

    @property
    def entries(self) -> list[ModelEntry]:
        return list(self._entries)

    def get(self, model_id: str) -> ModelEntry:
        try:
            return self._by_id[model_id]
        except KeyError as exc:
            raise ConfigError("no such model id: %r" % model_id) from exc

    def resolve(self, capability: str) -> ModelEntry:
        """First ENABLED entry whose capabilities satisfy `capability`.

        Order in the YAML is significant: primary first, then the smaller
        fallback.  This is the only place a capability becomes a model tag.
        """
        wanted = _CAPABILITY_MATCH.get(capability)
        if wanted is None:
            raise ConfigError("unknown capability %r" % capability)
        for entry in self._entries:
            if not entry.enabled:
                continue
            if any(c in entry.capabilities for c in wanted):
                return entry
        raise ConfigError(
            "no enabled model satisfies capability %r; check config/models.yaml" % capability
        )

    def resolve_for_agent(self, agent: str) -> ModelEntry:
        return self.resolve(AGENT_CAPABILITY[agent])

    def max_loaded_models(self) -> int:
        return int(self.defaults.get("max_loaded_models", 1))

    def host(self) -> str:
        return str(self.defaults.get("host", "127.0.0.1:11434"))


@lru_cache(maxsize=1)
def get_registry() -> ModelRegistry:
    return ModelRegistry.from_yaml(get_settings().models_yaml)


def reset_caches() -> None:
    """Test helper: drop memoised settings/registry after mutating os.environ."""
    get_settings.cache_clear()
    get_registry.cache_clear()
