/**
 * The only place the frontend talks to the backend.  OWNER: P5.
 *
 * SAME ORIGIN IN PRODUCTION.  API_BASE is "" in the built app, so every call is
 * a relative path against whatever origin served index.html - which is the
 * FastAPI process itself.  The browser never makes a cross-origin request, so
 * no CORS header is needed and none is installed.
 *
 * In `npm run dev` the Vite proxy forwards /api to 127.0.0.1:8000, which keeps
 * the dev workflow same-origin too.  VITE_API_BASE exists as an escape hatch
 * for a teammate running the backend elsewhere; it requires SETU_DEV_MODE and
 * an explicit SETU_DEV_ORIGINS on that backend.
 */

import type {
  ApprovalRequest,
  AuditEntry,
  AuditVerification,
  HealthResponse,
  MockScenario,
  ModelRegistryView,
  NetworkStatus,
  SessionDetail,
  SessionSummary,
  TaskStatus,
} from "./types";

export const API_BASE: string = import.meta.env.VITE_API_BASE ?? "";

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(API_BASE + path, {
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    ...init,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = (body as { detail?: string }).detail ?? detail;
    } catch {
      /* non-JSON error body; keep the status text */
    }
    throw new Error(`${response.status} ${detail}`);
  }
  return (await response.json()) as T;
}

async function optionalJson<T>(path: string): Promise<T | null> {
  const response = await fetch(API_BASE + path, { credentials: "include" });
  if (response.status === 204) return null;
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

export const api = {
  health: () => json<HealthResponse>("/api/health"),

  sessions: () => json<SessionSummary[]>("/api/sessions"),
  currentSession: () => optionalJson<SessionDetail>("/api/sessions/current"),
  newSession: () => json<SessionDetail>("/api/sessions", { method: "POST" }),
  activateSession: (sessionId: string) =>
    json<SessionDetail>(`/api/sessions/${sessionId}/activate`, { method: "POST" }),

  createTask: (text: string, filePaths: string[], scenario?: string) =>
    json<{ task_id: string; session_id: string; stream_url: string }>("/api/tasks", {
      method: "POST",
      body: JSON.stringify({
        text,
        file_paths: filePaths,
        ...(scenario ? { scenario } : {}),
      }),
    }),

  task: (taskId: string) => json<TaskStatus>(`/api/tasks/${taskId}`),

  approve: (taskId: string, approvalId: string, approved: boolean) =>
    json<{ approved: boolean }>(`/api/tasks/${taskId}/approve`, {
      method: "POST",
      body: JSON.stringify({ approval_id: approvalId, approved }),
    }),

  cancel: (taskId: string) =>
    json<{ cancelled: boolean }>(`/api/tasks/${taskId}/cancel`, { method: "POST" }),

  upload: async (file: File): Promise<{ path: string; stored_name: string }> => {
    const form = new FormData();
    form.append("file", file);
    const response = await fetch(API_BASE + "/api/upload", {
      method: "POST",
      body: form,
      credentials: "include",
    });
    if (!response.ok) throw new Error(`upload failed: ${response.status}`);
    return response.json();
  },

  network: () => json<NetworkStatus>("/api/network-status"),
  models: () => json<ModelRegistryView>("/api/models"),
  audit: (limit = 60) =>
    json<{ path: string; entries: AuditEntry[] }>(`/api/audit?limit=${limit}`),
  verifyAudit: () => json<AuditVerification>("/api/audit/verify"),
  scenarios: () => json<MockScenario[]>("/api/mock/scenarios"),

  artifactUrl: (taskId: string, artifactId: string) =>
    `${API_BASE}/api/tasks/${taskId}/artifacts/${artifactId}`,

  streamUrl: (taskId: string) => `${API_BASE}/api/tasks/${taskId}/stream`,
};

export type { ApprovalRequest };
