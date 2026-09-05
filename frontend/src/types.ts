/**
 * Frontend mirrors of backend/app/contracts.py.  OWNER: P5, but the SHAPES are
 * owned by P1 - a change here without a change there is a bug waiting for the
 * demo.
 *
 * SYNCHRONISATION.  These types are kept in step with the backend by a
 * generated-schema check rather than a code generator:
 *
 *     python scripts/check_contract_sync.py
 *
 * It reads the live OpenAPI schema (or the Pydantic models directly, so it runs
 * without a server) and asserts that every field named in this file exists on
 * the corresponding backend model.  It is deliberately a CHECK, not a
 * generator: a generator would rewrite P5's file on every backend edit, and the
 * point is to notice drift, not to hide it.  Run it before every Gate.
 */

export type AgentName = "vision" | "reasoning" | "coding";

export type ToolName =
  | "kb_search"
  | "read_file"
  | "write_file"
  | "list_dir"
  | "run_python"
  | "sheet_op"
  | "docgen";

export type TaskState =
  | "created"
  | "routing"
  | "planning"
  | "awaiting_approval"
  | "running"
  | "completed"
  | "failed"
  | "rejected"
  | "needs_human_review"
  | "cancelled";

export const TERMINAL_STATES: TaskState[] = [
  "completed",
  "failed",
  "rejected",
  "needs_human_review",
  "cancelled",
];

export type EventType =
  | "route"
  | "plan"
  | "step_start"
  | "token"
  | "step_done"
  | "attempt"
  | "escalate"
  | "artifact"
  | "audit"
  | "error"
  | "state"
  | "approval_request"
  | "approval_resolved"
  | "quarantine"
  | "done";

export interface SetuEvent {
  type: EventType;
  data: Record<string, unknown>;
  seq: number;
  ts: string;
}

export interface RouterDecision {
  agent: AgentName;
  model: string;
  model_id: string;
  capability: string;
  reason: string;
  rule_id: string;
  matched_signal: string | null;
  latency_ms: number;
}

export type StepStatus = "pending" | "running" | "done" | "failed" | "skipped";

export interface PlanStep {
  n: number;
  kind: "agent" | "tool";
  target: string;
  args: Record<string, unknown>;
  why: string;
  status: StepStatus;
}

export interface Plan {
  steps: PlanStep[];
  approved: boolean;
  revisions: number;
  approved_scope: string[];
}

export interface ApprovalRequest {
  approval_id: string;
  task_id: string;
  kind: "plan" | "plan_revision" | "write";
  created_at: string;
  summary: string;
  steps: PlanStep[];
  preview: string | null;
  target_path: string | null;
  decided: boolean;
}

export interface ArtifactRef {
  artifact_id: string;
  task_id: string;
  name: string;
  path: string;
  media_type: string;
  size_bytes: number;
  sha256: string;
  created_at: string;
  simulated: boolean;
}

export interface StructuredError {
  code: string;
  message: string;
  detail: Record<string, unknown>;
  retryable: boolean;
}

export interface TaskStatus {
  task_id: string;
  session_id: string;
  state: TaskState;
  created_at: string;
  updated_at: string;
  text: string;
  router_decision: RouterDecision | null;
  plan: Plan | null;
  iterations_used: number;
  max_iterations: number;
  pending_approval: ApprovalRequest | null;
  artifacts: ArtifactRef[];
  error: StructuredError | null;
  mock_mode: boolean;
}

export interface NegativeControl {
  blocked_external_attempts: number;
  all_blocked: boolean;
}

export interface NetworkStatus {
  mode: "single_laptop" | "lan";
  trusted_subnet: string | null;
  loopback_active: number;
  trusted_lan_active: number;
  external_active: number;
  unknown_active: number;
  sovereign_mode: boolean;
  negative_control: NegativeControl | null;
  monitor_available: boolean;
  monitor_error: string | null;
  sampled_at: string | null;
  scope: string;
  simulated: boolean;
}

export interface ModelEntry {
  id: string;
  provider: string;
  model: string;
  capabilities: string[];
  context_limit: number;
  max_output_tokens: number;
  temperature: number;
  keep_alive: string;
  enabled: boolean;
  fallback: string | null;
  expected_manifest_digest: string;
  /** null means NEVER CHECKED. Never render null as a tick. */
  integrity_verified: boolean | null;
  note: string | null;
  scope_note: string | null;
}

export interface ModelRegistryView {
  models: ModelEntry[];
  thresholds: Record<string, number>;
  max_attempts: Record<string, number>;
  max_iterations: number;
  max_loaded_models: number;
  host: string;
  mock_mode: boolean;
  integrity_checked: boolean;
}

export interface AuditEntry {
  ts: string;
  session: string;
  task_id: string;
  user: string;
  action: string;
  args_hash: string;
  model: string | null;
  route_confidence: number | null;
  attempt: number | null;
  step: number | null;
  iteration: number | null;
  result: string;
  prev_hash: string;
  entry_hash: string;
}

export interface AuditVerification {
  ok: boolean;
  entries_checked: number;
  broken_at: number | null;
  reason: string | null;
  path: string;
}

export interface MockScenario {
  key: string;
  title: string;
  description: string;
  steps: number;
  expected_state: string;
}

export interface HealthResponse {
  status: "ok";
  mock_mode: boolean;
  version: string;
}
