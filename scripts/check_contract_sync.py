"""
Frontend/backend contract drift check.  OWNER: P1.

    python scripts/check_contract_sync.py

Deliberately a CHECK rather than a code generator.  A generator would rewrite
P5's types on every backend edit and hide the moment the two diverged; what the
team actually needs is a loud failure at the Gate.  It also means no
heavyweight codegen toolchain has to be installed on six machines.

How it works: it imports the Pydantic models directly (no server required),
parses the TypeScript interfaces in frontend/src/types.ts with a small regex,
and reports fields present in one and missing in the other.

Exit codes: 0 in sync, 1 drift detected.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app import contracts as C  # noqa: E402

TYPES_TS = REPO_ROOT / "frontend" / "src" / "types.ts"

#: TypeScript interface name -> backend model.  Add a row when you add a shape
#: the UI consumes; an unlisted interface is not checked.
PAIRS: dict[str, type] = {
    "RouterDecision": C.RouterDecision,
    "PlanStep": C.PlanStep,
    "Plan": C.Plan,
    "ApprovalRequest": C.ApprovalRequest,
    "ArtifactRef": C.ArtifactRef,
    "StructuredError": C.StructuredError,
    "TaskStatus": C.TaskStatus,
    "NegativeControl": C.NegativeControl,
    "NetworkStatus": C.NetworkStatus,
    "ModelEntry": C.ModelEntry,
    "ModelRegistryView": C.ModelRegistryView,
    "AuditEntry": C.AuditEntry,
    "AuditVerification": C.AuditVerification,
    "HealthResponse": C.HealthResponse,
    "SetuEvent": C.Event,
}

INTERFACE_RE = re.compile(r"export interface (\w+)\s*\{(.*?)\n\}", re.DOTALL)
FIELD_RE = re.compile(r"^\s*(?:readonly\s+)?(\w+)\??\s*:", re.MULTILINE)


def ts_interfaces(source: str) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for name, body in INTERFACE_RE.findall(source):
        # Drop comment lines so a field name mentioned in prose is not counted.
        clean = "\n".join(
            line
            for line in body.splitlines()
            if not line.strip().startswith(("//", "*", "/*"))
        )
        found[name] = set(FIELD_RE.findall(clean))
    return found


def main() -> int:
    if not TYPES_TS.is_file():
        print("frontend/src/types.ts not found - nothing to check")
        return 0

    interfaces = ts_interfaces(TYPES_TS.read_text(encoding="utf-8"))
    problems: list[str] = []

    for ts_name, model in PAIRS.items():
        if ts_name not in interfaces:
            problems.append("MISSING INTERFACE  %s (backend model %s)" % (ts_name, model.__name__))
            continue
        backend_fields = set(model.model_fields)
        ts_fields = interfaces[ts_name]
        missing_in_ts = backend_fields - ts_fields
        unknown_in_ts = ts_fields - backend_fields
        if missing_in_ts:
            problems.append(
                "%s: frontend is missing %s" % (ts_name, ", ".join(sorted(missing_in_ts)))
            )
        if unknown_in_ts:
            problems.append(
                "%s: frontend declares fields the backend does not have: %s"
                % (ts_name, ", ".join(sorted(unknown_in_ts)))
            )

    # The literal unions the UI switches on must match the backend exactly.
    source = TYPES_TS.read_text(encoding="utf-8")
    for union_name, values in (
        ("EventType", C.EventType.__args__),  # type: ignore[attr-defined]
        ("TaskState", C.TaskState.__args__),  # type: ignore[attr-defined]
        ("ToolName", C.ToolName.__args__),  # type: ignore[attr-defined]
        ("AgentName", C.AgentName.__args__),  # type: ignore[attr-defined]
    ):
        block = re.search(r"export type %s\s*=(.*?);" % union_name, source, re.DOTALL)
        if not block:
            problems.append("MISSING UNION  %s" % union_name)
            continue
        declared = set(re.findall(r'"([^"]+)"', block.group(1)))
        expected = set(values)
        if declared != expected:
            problems.append(
                "%s drift: backend-only %s, frontend-only %s"
                % (union_name, sorted(expected - declared), sorted(declared - expected))
            )

    if problems:
        print("CONTRACT DRIFT DETECTED\n")
        for line in problems:
            print("  " + line)
        print("\nFix frontend/src/types.ts (P5) or announce the contract change (P1).")
        return 1

    print("contracts in sync: %d interfaces and 4 unions checked" % len(PAIRS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
