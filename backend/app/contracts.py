"""
SETU shared contracts.  OWNER: P1.  * SHARED FILE *

Every change here is announced to the whole team before it is committed.
Five other people import from this module; a silent field rename costs an
integration hour.

Source: SETU_MASTER_BLUEPRINT_v2.md Part 6, extended with the shared types the
blueprint left implicit (chunks, write results, task lifecycle, artifacts,
errors, approvals, invocations, typed tool arguments and event payloads).
Where this file diverges from the blueprint's Part 6 listing, the reason is
recorded in docs/DECISIONS.md.

CONVENTIONS (these are the answers to the five questions everybody asks):

1. PATHS.  Every path crossing this boundary is a POSIX-style RELATIVE path
   inside the workspace root (`data/workspace` by default), e.g.
   "uploads/scan_a1b2.pdf".  Absolute paths and backslash separators are
   rejected by the path jail.  Artifacts are additionally addressable by an
   opaque `artifact_id`; a raw path is never accepted from a client.
2. IDENTIFIERS.  `task_id` and `session_id` are SERVER-GENERATED.  A client may
   not choose them.  Format: "t_" / "s_" + 12 lowercase hex chars.
3. PAGES AND BOXES.  Pages are 1-INDEXED.  `bbox` is [x0, y0, x1, y1] in PDF
   points (72/inch), origin TOP-LEFT, with x0 < x1 and y0 < y1.
4. CONFIDENCE.  Always a float in [0.0, 1.0].  Higher is better.  Coding
   confidence is objective (1.0 iff exit_code == 0), never self-reported.
5. ATTEMPTS AND ITERATIONS.  `Attempt.n` is 1-INDEXED and counts attempts of a
   SINGLE step (bounded by MAX_ATTEMPTS[agent]).  Orchestration iterations are
   counted separately, 1-indexed, and bounded by MAX_ITERATIONS (5).  Retrying
   a step does NOT consume an iteration; each dispatched step does.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# -----------------------------------------------------------------------------
# Names and enumerations
# -----------------------------------------------------------------------------

AgentName = Literal["vision", "reasoning", "coding"]

ToolName = Literal[
    "kb_search",
    "read_file",
    "write_file",
    "list_dir",
    "run_python",
    "sheet_op",
    "docgen",
]

#: Exactly seven.  See docs/ARCHITECTURE.md, "the capability surface".
TOOL_NAMES: tuple[str, ...] = (
    "kb_search",
    "read_file",
    "write_file",
    "list_dir",
    "run_python",
    "sheet_op",
    "docgen",
)

AGENT_NAMES: tuple[str, ...] = ("vision", "reasoning", "coding")

Capability = Literal["vision", "planning", "code"]

ExtractionTier = Literal["text_layer", "tesseract", "vlm"]

TrustLevel = Literal["trusted", "untrusted", "quarantined"]

Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class ErrorCode:
    """Stable machine-readable error codes.

    Tool failures never raise out of the dispatcher: they are converted into a
    StructuredError, attached to the step observation, and emitted as an
    `error` event.  The loop continues so the planner can react to the failure.
    """

    PATH_ESCAPE = "PATH_ESCAPE"
    NOT_FOUND = "NOT_FOUND"
    INVALID_ARGS = "INVALID_ARGS"
    TOOL_FAILED = "TOOL_FAILED"
    SANDBOX_UNAVAILABLE = "SANDBOX_UNAVAILABLE"
    SANDBOX_TIMEOUT = "SANDBOX_TIMEOUT"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    APPROVAL_REJECTED = "APPROVAL_REJECTED"
    ITERATION_CAP = "ITERATION_CAP"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    QUARANTINED = "QUARANTINED"
    INTERNAL = "INTERNAL"


class StructuredError(BaseModel):
    """The only shape an error ever takes as it crosses a boundary."""

    code: str
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False


# -----------------------------------------------------------------------------
# Entry
# -----------------------------------------------------------------------------


class TaskEnvelope(BaseModel):
    """The task as the orchestrator sees it.  Identifiers are server-assigned."""

    session_id: str
    task_id: str
    text: str
    file_paths: list[str] = Field(default_factory=list)
    user: str = "local"
    #: Bounded transcript from earlier turns in this session. The router still
    #: routes on `text`; a real planner may use this as conversation context.
    conversation_context: str = ""

    @field_validator("file_paths")
    @classmethod
    def _relative_only(cls, v: list[str]) -> list[str]:
        for p in v:
            if p.startswith("/") or p.startswith("\\") or ":" in p[:3]:
                raise ValueError("file_paths must be workspace-relative, got " + repr(p))
        return v


class TaskCreateRequest(BaseModel):
    """POST /api/tasks body.  No task_id: the server assigns it (convention 2)."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=8000)
    file_paths: list[str] = Field(default_factory=list)
    session_id: Optional[str] = None
    #: Optional named mock scenario.  Ignored (and warned about) in real mode.
    scenario: Optional[str] = None


class RouterDecision(BaseModel):
    """Which agent handles the ENTRY point.  The router never picks step 2."""

    agent: AgentName
    model: str  # resolved from config/models.yaml, never hardcoded
    model_id: str  # registry id, e.g. "vision-primary"
    capability: Capability
    reason: str  # human sentence - RENDERED IN THE UI BANNER
    rule_id: str  # "R1_FILE_EXT"
    matched_signal: Optional[str] = None
    latency_ms: float = 0.0


# -----------------------------------------------------------------------------
# Plan / loop
# -----------------------------------------------------------------------------

StepStatus = Literal["pending", "running", "done", "failed", "skipped"]


class PlanStep(BaseModel):
    n: int = Field(ge=1)
    kind: Literal["agent", "tool"]
    target: str  # AgentName when kind=="agent", ToolName when kind=="tool"
    args: dict[str, Any] = Field(default_factory=dict)
    why: str  # shown in the checklist
    status: StepStatus = "pending"

    @model_validator(mode="after")
    def _target_in_allowlist(self) -> "PlanStep":
        allowed = AGENT_NAMES if self.kind == "agent" else TOOL_NAMES
        if self.target not in allowed:
            raise ValueError(
                "%s target %r is not allowlisted; allowed=%s"
                % (self.kind, self.target, allowed)
            )
        return self

    def scope_key(self) -> str:
        """Identity used to decide whether a revised step is inside approved scope."""
        return self.kind + ":" + self.target


class Plan(BaseModel):
    steps: list[PlanStep] = Field(default_factory=list)
    approved: bool = False  # Layer 4 gate
    revisions: int = 0
    #: scope_key() values the human approved.  A revised step outside this set
    #: triggers a fresh approval request (see orchestration/approvals.py).
    approved_scope: list[str] = Field(default_factory=list)


# -----------------------------------------------------------------------------
# Vision
# -----------------------------------------------------------------------------


class Finding(BaseModel):
    id: str
    text: str
    page: int = Field(ge=1)  # convention 3: 1-indexed
    bbox: Optional[list[float]] = None  # [x0,y0,x1,y1] PDF points, top-left origin
    confidence: Confidence
    source_file: str  # workspace-relative
    extraction_tier: ExtractionTier

    @field_validator("bbox")
    @classmethod
    def _bbox_shape(cls, v: Optional[list[float]]) -> Optional[list[float]]:
        if v is None:
            return v
        if len(v) != 4:
            raise ValueError("bbox must be [x0, y0, x1, y1]")
        if not (v[0] < v[2] and v[1] < v[3]):
            raise ValueError("bbox must satisfy x0<x1 and y0<y1")
        return v


class VisionOutput(BaseModel):
    findings: list[Finding] = Field(default_factory=list)
    page_legibility: Confidence
    overall_confidence: Confidence
    raw_text: str = ""
    injection_flags: list[str] = Field(default_factory=list)


# -----------------------------------------------------------------------------
# Knowledge base / reasoning
# -----------------------------------------------------------------------------


class ChunkMetadata(BaseModel):
    """Carried on every indexed chunk.  `trust_level` drives the injection defence."""

    source_file: str
    page: int = Field(ge=1)
    chunk_id: str
    trust_level: TrustLevel = "untrusted"
    ingested_at: Optional[str] = None
    injection_flags: list[str] = Field(default_factory=list)


class Chunk(BaseModel):
    """kb_search result element."""

    chunk_id: str
    text: str
    #: Cosine DISTANCE (lower is closer).  Not a similarity score.
    distance: float = Field(ge=0.0)
    metadata: ChunkMetadata


class Citation(BaseModel):
    chunk_id: str
    source_file: str
    page: int = Field(ge=1)
    snippet: str


class ReasoningOutput(BaseModel):
    content: str
    grounded: bool
    citations: list[Citation] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)  # Verifier yellow flags
    confidence: Confidence


# -----------------------------------------------------------------------------
# Coding / sandbox
# -----------------------------------------------------------------------------


class CodingOutput(BaseModel):
    code: str
    language: str = "python"
    stdout: str = ""
    stderr: str = ""
    exit_code: int
    duration_ms: float = 0.0
    artifacts: list[str] = Field(default_factory=list)
    #: OBJECTIVE: 1.0 iff exit_code == 0.  A zero exit code is evidence the code
    #: RAN, not proof the logic is correct - say it that way to a judge.
    confidence: Confidence
    sandbox_command: list[str] = Field(default_factory=list)  # rendered in the UI
    sandbox_available: bool = True

    @model_validator(mode="after")
    def _objective_confidence(self) -> "CodingOutput":
        expected = 1.0 if self.exit_code == 0 else 0.0
        if abs(self.confidence - expected) > 1e-9:
            raise ValueError(
                "coding confidence is objective: must be 1.0 iff exit_code==0 "
                "(exit_code=%s, confidence=%s)" % (self.exit_code, self.confidence)
            )
        return self


# -----------------------------------------------------------------------------
# Spreadsheet
# -----------------------------------------------------------------------------


class SheetSchema(BaseModel):
    sheets: list[str]
    dims: dict[str, tuple[int, int]]  # sheet -> (rows, cols)
    headers: dict[str, list[str]]
    dtypes: dict[str, dict[str, str]]
    null_counts: dict[str, dict[str, int]]


class SheetRows(BaseModel):
    sheet: str
    headers: list[str]
    rows: list[list[Any]]
    truncated: bool = False
    total_rows: int = 0


class ComputeResult(BaseModel):
    script: str  # "calculations with steps shown"
    intermediates: dict[str, Any] = Field(default_factory=dict)
    result: Any = None
    exit_code: int
    stderr: str = ""


class WriteResult(BaseModel):
    """Returned by write_file and by sheet_op("write")."""

    path: str  # workspace-relative
    bytes_written: int = Field(ge=0)
    created: bool  # False means an existing file was replaced
    sha256: str


# -----------------------------------------------------------------------------
# Typed tool arguments - one model per registered tool
# -----------------------------------------------------------------------------


class KbSearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1)
    k: int = Field(default=5, ge=1, le=20)


class ReadFileArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1)
    max_bytes: int = Field(default=200_000, ge=1, le=5_000_000)


class WriteFileArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1)
    content: str


class ListDirArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = "."


class RunPythonArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1)
    timeout: int = Field(default=15, ge=1, le=60)
    #: Workspace-relative files mounted READ-ONLY into the sandbox.
    input_paths: list[str] = Field(default_factory=list)


SheetOperation = Literal["describe", "read", "compute", "write"]


class SheetOpArgs(BaseModel):
    """ONE tool, four operations, with per-operation validation.

    The blueprint's Part 6 sketch used `**kw`; an unvalidated public interface
    is exactly the guesswork this file exists to remove, so the extra arguments
    are declared and cross-checked here instead.
    """

    model_config = ConfigDict(extra="forbid")

    op: SheetOperation
    path: str = Field(min_length=1)

    # op="read"
    sheet: Optional[str] = None
    range: Optional[str] = None
    max_rows: int = Field(default=200, ge=1, le=5000)

    # op="compute"
    spec: Optional[str] = None

    # op="write"
    data: Optional[dict[str, Any]] = None
    formatting: Optional[dict[str, Any]] = None
    out_path: Optional[str] = None

    @model_validator(mode="after")
    def _per_operation_requirements(self) -> "SheetOpArgs":
        if self.op == "compute" and not self.spec:
            raise ValueError("sheet_op(compute) requires `spec`")
        if self.op == "write":
            if self.data is None:
                raise ValueError("sheet_op(write) requires `data`")
            if not self.out_path:
                raise ValueError(
                    "sheet_op(write) requires `out_path`: an input workbook is never overwritten"
                )
            if self.out_path == self.path:
                raise ValueError("sheet_op(write) must not overwrite its input")
        forbidden = {
            "describe": ["sheet", "range", "spec", "data", "formatting", "out_path"],
            "read": ["spec", "data", "formatting", "out_path"],
            "compute": ["data", "formatting", "out_path"],
            "write": ["range", "spec"],
        }[self.op]
        for name in forbidden:
            if getattr(self, name) is not None:
                raise ValueError("sheet_op(%s) does not accept `%s`" % (self.op, name))
        return self


DocKind = Literal["docx", "xlsx", "pptx"]


class DocgenArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: DocKind
    data: dict[str, Any]
    template: Optional[str] = None
    out_name: Optional[str] = None


TOOL_ARG_MODELS: dict[str, type[BaseModel]] = {
    "kb_search": KbSearchArgs,
    "read_file": ReadFileArgs,
    "write_file": WriteFileArgs,
    "list_dir": ListDirArgs,
    "run_python": RunPythonArgs,
    "sheet_op": SheetOpArgs,
    "docgen": DocgenArgs,
}


# -----------------------------------------------------------------------------
# Artifacts (declared before ToolResult, which references them)
# -----------------------------------------------------------------------------


class ArtifactRef(BaseModel):
    """A produced file.  Clients download by artifact_id, never by path."""

    artifact_id: str
    task_id: str
    name: str  # server-controlled storage name
    path: str  # workspace-relative
    media_type: str
    size_bytes: int = Field(ge=0)
    sha256: str
    created_at: str
    simulated: bool = False


# -----------------------------------------------------------------------------
# Invocations and results
# -----------------------------------------------------------------------------


class Attempt(BaseModel):
    n: int = Field(ge=1)  # 1-indexed, per step (convention 5)
    confidence: Confidence
    failure_reason: Optional[str] = None
    feedback_injected: Optional[str] = None  # PROVES the retry was informed
    duration_ms: float = 0.0


class AgentInvocation(BaseModel):
    agent: AgentName
    model_id: str
    model: str
    prompt_summary: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    attempt: int = Field(default=1, ge=1)
    feedback: Optional[str] = None


class AgentResult(BaseModel):
    agent: AgentName
    model: str
    payload: dict[str, Any] = Field(default_factory=dict)
    attempts: list[Attempt] = Field(default_factory=list)
    final_confidence: Confidence
    needs_human_review: bool = False
    escalation_reason: Optional[str] = None
    error: Optional[StructuredError] = None
    simulated: bool = False  # True in mock mode - the UI labels it


class ToolInvocation(BaseModel):
    tool: ToolName
    args: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    tool: ToolName
    ok: bool
    payload: dict[str, Any] = Field(default_factory=dict)
    error: Optional[StructuredError] = None
    duration_ms: float = 0.0
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    simulated: bool = False


class Observation(BaseModel):
    """What the loop accumulates.  The planner reads ONLY these."""

    step_n: int
    kind: Literal["agent", "tool"]
    target: str
    ok: bool
    summary: str  # short, planner-readable
    payload: dict[str, Any] = Field(default_factory=dict)
    error: Optional[StructuredError] = None
    confidence: Optional[Confidence] = None
    attempts: list[Attempt] = Field(default_factory=list)
    iteration: int = Field(ge=1)
    simulated: bool = False


# -----------------------------------------------------------------------------
# Approvals
# -----------------------------------------------------------------------------

ApprovalKind = Literal["plan", "plan_revision", "write"]


class ApprovalRequest(BaseModel):
    approval_id: str
    task_id: str
    kind: ApprovalKind
    created_at: str
    summary: str
    #: For kind="plan"/"plan_revision": the steps awaiting approval.
    steps: list[PlanStep] = Field(default_factory=list)
    #: For kind="write": the ACTUAL content or diff about to be committed.
    #: Layer 4 requires the human to review the change, not just its filename.
    preview: Optional[str] = None
    target_path: Optional[str] = None
    decided: bool = False


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_id: str
    approved: bool
    note: Optional[str] = None


# -----------------------------------------------------------------------------
# Task lifecycle
# -----------------------------------------------------------------------------

TaskState = Literal[
    "created",
    "routing",
    "planning",
    "awaiting_approval",
    "running",
    "completed",
    "failed",
    "rejected",
    "needs_human_review",
    "cancelled",
]

#: A task in a terminal state never runs again.
TERMINAL_STATES: frozenset[str] = frozenset(
    {"completed", "failed", "rejected", "needs_human_review", "cancelled"}
)
#: States from which execution can still be resumed by a human decision.
RESUMABLE_STATES: frozenset[str] = frozenset({"awaiting_approval"})


class TaskStatus(BaseModel):
    task_id: str
    session_id: str
    state: TaskState
    created_at: str
    updated_at: str
    text: str
    router_decision: Optional[RouterDecision] = None
    plan: Optional[Plan] = None
    iterations_used: int = 0
    max_iterations: int = 5
    pending_approval: Optional[ApprovalRequest] = None
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    error: Optional[StructuredError] = None
    mock_mode: bool = True


class TaskCreateResponse(BaseModel):
    task_id: str
    session_id: str
    state: TaskState
    stream_url: str


class TaskResult(BaseModel):
    task_id: str
    state: TaskState
    summary: str
    observations: list[Observation] = Field(default_factory=list)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    needs_human_review: bool = False
    escalation_reason: Optional[str] = None
    iterations_used: int = 0
    error: Optional[StructuredError] = None
    mock_mode: bool = True


# -----------------------------------------------------------------------------
# Audit
# -----------------------------------------------------------------------------


class AuditEntry(BaseModel):
    ts: str
    session: str
    task_id: str
    user: str = "local"
    action: str
    args_hash: str
    model: Optional[str] = None
    route_confidence: Optional[float] = None
    attempt: Optional[int] = None
    step: Optional[int] = None
    iteration: Optional[int] = None
    result: str
    prev_hash: str
    entry_hash: str


class AuditVerification(BaseModel):
    ok: bool
    entries_checked: int
    broken_at: Optional[int] = None  # 0-indexed line number
    reason: Optional[str] = None
    path: str


# -----------------------------------------------------------------------------
# Network (matches the shipped classifier)
# -----------------------------------------------------------------------------


class NegativeControl(BaseModel):
    blocked_external_attempts: int = Field(ge=0)
    all_blocked: bool


class NetworkStatus(BaseModel):
    mode: Literal["single_laptop", "lan"]
    trusted_subnet: Optional[str] = None
    loopback_active: int = Field(ge=0)
    trusted_lan_active: int = Field(ge=0)
    external_active: int = Field(ge=0)
    unknown_active: int = Field(ge=0)
    sovereign_mode: bool
    negative_control: Optional[NegativeControl] = None
    #: Honesty fields.  A sampled count of zero is not proof of zero traffic over
    #: all time, and the UI must be able to say when monitoring failed.
    monitor_available: bool = True
    monitor_error: Optional[str] = None
    sampled_at: Optional[str] = None
    scope: str = "setu process sockets, sampled"
    simulated: bool = False


# -----------------------------------------------------------------------------
# Model registry (exposed to the UI)
# -----------------------------------------------------------------------------


class ModelEntry(BaseModel):
    id: str
    provider: str = "ollama"
    model: str
    capabilities: list[str] = Field(default_factory=list)
    context_limit: int = 8192
    max_output_tokens: int = 1024
    temperature: float = 0.2
    keep_alive: str = "10m"
    enabled: bool = True
    fallback: Optional[str] = None
    expected_manifest_digest: str = ""
    #: None means "never checked".  Do NOT render an unchecked digest as verified.
    integrity_verified: Optional[bool] = None
    note: Optional[str] = None
    scope_note: Optional[str] = None


class ModelRegistryView(BaseModel):
    models: list[ModelEntry]
    thresholds: dict[str, float]
    max_attempts: dict[str, int]
    max_iterations: int
    max_loaded_models: int
    host: str
    mock_mode: bool
    integrity_checked: bool = False


# -----------------------------------------------------------------------------
# SSE events
# -----------------------------------------------------------------------------

EventType = Literal[
    # Blueprint section 6.1 - names preserved exactly.
    "route",
    "plan",
    "step_start",
    "token",
    "step_done",
    "attempt",
    "escalate",
    "artifact",
    "audit",
    "error",
    # Added by this scaffold, documented in docs/CONTRACTS.md.
    "state",  # task state transition
    "approval_request",  # a human decision is required
    "approval_resolved",  # decision recorded
    "quarantine",  # untrusted content flagged
    "done",  # terminal: the stream closes after this
]


class Event(BaseModel):
    """The SSE envelope: {type, data}, plus an id used for replay."""

    type: EventType
    data: dict[str, Any] = Field(default_factory=dict)
    #: Monotonic per-task sequence number, starting at 1.  Sent as the SSE `id:`
    #: field so a reconnecting browser can resume with Last-Event-ID.
    seq: int = Field(default=0, ge=0)
    ts: str = ""


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    mock_mode: bool
    version: str


class ReadinessCheck(BaseModel):
    name: str
    ok: bool
    detail: str = ""
    #: True when the check could not be run at all (e.g. Docker absent).
    #: An unrun check is never reported as a pass.
    skipped: bool = False


class ReadinessResponse(BaseModel):
    ready: bool
    mock_mode: bool
    checks: list[ReadinessCheck]
