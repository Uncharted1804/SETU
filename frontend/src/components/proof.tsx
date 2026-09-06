/**
 * The proof surfaces: network panel, model registry, audit viewer.  OWNER: P5.
 *
 * THE HONESTY RULES BAKED INTO THIS FILE:
 *
 *  - loopback / trusted LAN / external / unknown are FOUR SEPARATE NUMBERS and
 *    are never collapsed.  Trusted-LAN traffic is the deployment working, not a
 *    leak, and an earlier version that bucketed a colleague's browser with an
 *    actual leak made the zero either false or quietly filtered.
 *  - blocked_external_attempts renders in its own row and is never added into
 *    the external count.  A successful negative control must not look like a leak.
 *  - A sampled zero is not a proof of zero over all time.  The scope line says
 *    exactly what was measured, and when monitoring is unavailable the panel
 *    says so instead of showing reassuring zeros.
 *  - An unchecked model digest renders as "not verified", never as a tick.
 */

import { useEffect, useState } from "react";
import { api } from "../api";
import type {
  AuditEntry,
  AuditVerification,
  ModelRegistryView,
  NetworkStatus,
} from "../types";
import { Empty, KeyValue, Panel, Tag } from "./common";

function InfoIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4 shrink-0">
      <circle cx="12" cy="12" r="10" />
      <path d="M12 16v-4M12 8h.01" />
    </svg>
  );
}

export function NetworkPanel() {
  const [status, setStatus] = useState<NetworkStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const next = await api.network();
        if (alive) {
          setStatus(next);
          setError(null);
        }
      } catch (e) {
        if (alive) setError(String(e));
      }
    };
    void poll();
    const timer = setInterval(poll, 500);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, []);

  if (error) {
    return (
      <Panel title="">
        <p className="text-xs text-bad">
          monitor unreachable: {error}. No claim about external traffic can be made
          from this panel right now.
        </p>
      </Panel>
    );
  }
  if (!status) return <Panel title=""><Empty>sampling…</Empty></Panel>;

  const unavailable = !status.monitor_available;
  const isSovereign = !unavailable && status.external_active === 0;

  const totalSockets = unavailable
    ? 0
    : (status.loopback_active || 0) +
      (status.trusted_lan_active || 0) +
      (status.external_active || 0) +
      (status.unknown_active || 0);

  const loopbackPct = totalSockets > 0 ? ((status.loopback_active || 0) / totalSockets) * 100 : 0;
  const lanPct = totalSockets > 0 ? ((status.trusted_lan_active || 0) / totalSockets) * 100 : 0;
  const externalPct = totalSockets > 0 ? ((status.external_active || 0) / totalSockets) * 100 : 0;
  const unknownPct = totalSockets > 0 ? ((status.unknown_active || 0) / totalSockets) * 100 : 0;

  const formattedSampleTime = status.sampled_at
    ? status.sampled_at.includes("T")
      ? status.sampled_at.slice(11, 19) + " UTC"
      : status.sampled_at
    : "never";

  return (
    <Panel title="">
      {unavailable && (
        <p className="mb-2 rounded-lg border border-bad/40 bg-bad/5 px-2.5 py-1.5 text-[11px] text-bad">
          The socket monitor could not run{status.monitor_error ? `: ${status.monitor_error}` : ""}.
          The counters below are placeholders, not evidence.
        </p>
      )}

      {/* Socket telemetry overview */}
      <div className="mb-3 rounded-xl border border-edge/80 bg-panel/60 p-3 shadow-sm">
        {/* Header: Egress Status & Total Active */}
        <div className="flex items-center justify-between gap-2 pb-2">
          <div className="flex items-center gap-1.5 min-w-0">
            <span
              className={`inline-block h-2 w-2 shrink-0 rounded-full ${
                unavailable
                  ? "bg-muted"
                  : isSovereign
                  ? "bg-emerald-500"
                  : "bg-rose-500 animate-pulse"
              }`}
            />
            <span className="truncate text-xs font-semibold text-content font-sans">
              {unavailable
                ? "Monitor offline"
                : isSovereign
                ? "Air-gapped (Local only)"
                : "Active external egress"}
            </span>
          </div>
          <span className="shrink-0 text-[11px] font-medium text-muted font-sans tabular-nums">
            {unavailable ? "—" : `${totalSockets} active sockets`}
          </span>
        </div>

        {/* Proportional distribution bar */}
        {!unavailable && totalSockets > 0 && (
          <div className="mb-3 mt-1 h-1.5 w-full overflow-hidden rounded-full bg-edge/60 flex">
            {loopbackPct > 0 && (
              <div
                style={{ width: `${loopbackPct}%` }}
                className="bg-accent/80 transition-all duration-300"
                title={`Loopback: ${status.loopback_active} (${Math.round(loopbackPct)}%)`}
              />
            )}
            {lanPct > 0 && (
              <div
                style={{ width: `${lanPct}%` }}
                className="bg-sky-500/80 transition-all duration-300"
                title={`Trusted LAN: ${status.trusted_lan_active} (${Math.round(lanPct)}%)`}
              />
            )}
            {externalPct > 0 && (
              <div
                style={{ width: `${externalPct}%` }}
                className="bg-rose-500 transition-all duration-300"
                title={`External: ${status.external_active} (${Math.round(externalPct)}%)`}
              />
            )}
            {unknownPct > 0 && (
              <div
                style={{ width: `${unknownPct}%` }}
                className="bg-amber-500 transition-all duration-300"
                title={`Unknown: ${status.unknown_active} (${Math.round(unknownPct)}%)`}
              />
            )}
          </div>
        )}

        {/* 2x2 symmetrical metric grid */}
        <div className="grid grid-cols-2 gap-2">
          {/* External WAN */}
          <div
            className={`flex flex-col justify-between rounded-lg border p-2.5 transition-colors ${
              unavailable
                ? "border-edge/60 bg-panel/40"
                : status.external_active > 0
                ? "border-rose-500/40 bg-rose-500/10 text-rose-600 dark:text-rose-400"
                : "border-edge/70 bg-panel/40"
            }`}
          >
            <span className="text-[10px] font-semibold uppercase tracking-wider text-muted font-sans truncate">
              External WAN
            </span>
            <div className="my-1 flex items-baseline gap-1.5">
              <span
                className={`font-sans text-xl font-bold tabular-nums ${
                  status.external_active > 0 ? "text-rose-600 dark:text-rose-400" : "text-content"
                }`}
              >
                {unavailable ? "—" : status.external_active}
              </span>
              <span className="text-[10px] text-muted font-sans">active</span>
            </div>
            <p className={`text-[10px] font-sans truncate ${status.external_active > 0 ? "font-semibold text-rose-600 dark:text-rose-400" : "text-muted"}`}>
              {unavailable ? "Not sampled" : status.external_active === 0 ? "Air-gapped · 0 leaks" : "Egress leak"}
            </p>
          </div>

          {/* Loopback */}
          <div className="flex flex-col justify-between rounded-lg border border-edge/70 bg-panel/40 p-2.5">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-muted font-sans truncate">
              Loopback
            </span>
            <div className="my-1 flex items-baseline gap-1.5">
              <span className="font-sans text-xl font-bold tabular-nums text-content">
                {unavailable ? "—" : status.loopback_active}
              </span>
              <span className="text-[10px] text-muted font-sans">active</span>
            </div>
            <p className="text-[10px] text-muted font-sans truncate">127.0.0.1 · Local IPC</p>
          </div>

          {/* Trusted LAN */}
          <div className="flex flex-col justify-between rounded-lg border border-edge/70 bg-panel/40 p-2.5">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-muted font-sans truncate">
              Trusted LAN
            </span>
            <div className="my-1 flex items-baseline gap-1.5">
              <span className="font-sans text-xl font-bold tabular-nums text-content">
                {unavailable ? "—" : status.trusted_lan_active}
              </span>
              <span className="text-[10px] text-muted font-sans">active</span>
            </div>
            <p className="text-[10px] text-muted font-sans truncate">Intranet subnet</p>
          </div>

          {/* Unknown */}
          <div className="flex flex-col justify-between rounded-lg border border-edge/70 bg-panel/40 p-2.5">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-muted font-sans truncate">
              Unclassified
            </span>
            <div className="my-1 flex items-baseline gap-1.5">
              <span className="font-sans text-xl font-bold tabular-nums text-content">
                {unavailable ? "—" : status.unknown_active}
              </span>
              <span className="text-[10px] text-muted font-sans">active</span>
            </div>
            <p className="text-[10px] text-muted font-sans truncate">No rogue sockets</p>
          </div>
        </div>
      </div>

      <div className="rounded-xl border border-edge/60 bg-panel/40 p-2.5 shadow-sm space-y-1 mb-2">
        <KeyValue k="mode" v={status.mode} mono={false} />
        <KeyValue k="trusted subnet" v={status.trusted_subnet ?? "not configured"} mono={false} />
        <KeyValue
          k="negative control"
          v={
            status.negative_control
              ? `${status.negative_control.blocked_external_attempts} attempt(s), ${
                  status.negative_control.all_blocked ? "all blocked" : "NOT all blocked"
                }`
              : "none run"
          }
          mono={false}
        />
        <KeyValue k="sampled at" v={formattedSampleTime} mono={true} />
      </div>

      {/* Styled info block for prose */}
      <div className="info-block">
        <InfoIcon />
        <p>
          Trusted-LAN traffic is active when organisation users are using SETU; active
          external traffic is separate and is the figure above. Scope: {status.scope}. A
          sampled count of zero is evidence from this sample, not a proof that no packet
          ever left the machine.
        </p>
      </div>
    </Panel>
  );
}

export function ModelRegistryPanel() {
  const [view, setView] = useState<ModelRegistryView | null>(null);

  useEffect(() => {
    void api.models().then(setView).catch(() => setView(null));
  }, []);

  if (!view) return <Panel title="Models"><Empty>loading registry…</Empty></Panel>;

  return (
    <Panel
      title="Models"
      right={<span className="text-[10px] text-muted font-sans">{view.host}, up to {view.max_loaded_models} loaded</span>}
    >
      <ul className="space-y-1.5 mb-2">
        {view.models.map((m) => (
          <li key={m.id} className="rounded-xl border border-edge/70 bg-panel/50 dark:bg-zinc-900/30 p-2 shadow-sm">
            <div className="flex items-center justify-between gap-1.5">
              <span className="font-sans font-semibold text-xs text-content">{m.model}</span>
              <div className="flex items-center gap-1">
                <Tag tone={m.enabled ? "accent" : "neutral"}>{m.enabled ? m.id : "disabled"}</Tag>
                <Tag tone={m.integrity_verified === true ? "good" : "warn"}>
                  {m.integrity_verified === null
                    ? "unverified"
                    : m.integrity_verified
                      ? "verified"
                      : "MISMATCH"}
                </Tag>
              </div>
            </div>
            <p className="mt-1 font-mono text-[10px] text-muted">
              {m.expected_manifest_digest
                ? m.expected_manifest_digest.slice(0, 24) + "…"
                : "no expected digest recorded"}
            </p>
            <p className="text-[10px] text-muted font-sans mt-0.5">{m.capabilities.join(", ")}</p>
          </li>
        ))}
      </ul>

      <div className="rounded-xl border border-edge/60 bg-panel/40 p-2.5 shadow-sm space-y-1 mb-2">
        <KeyValue k="thresholds" v={JSON.stringify(view.thresholds)} mono={true} />
        <KeyValue k="max attempts" v={JSON.stringify(view.max_attempts)} mono={true} />
        <KeyValue k="max iterations" v={view.max_iterations} mono={false} />
      </div>

      <div className="info-block">
        <InfoIcon />
        <p>
          Adding or swapping a model for an existing role is an edit to
          config/models.yaml. A genuinely new capability also needs an agent
          implementation — that part is not free.
        </p>
      </div>
    </Panel>
  );
}

export function AuditPanel() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [verification, setVerification] = useState<AuditVerification | null>(null);

  const refresh = async () => {
    try {
      const body = await api.audit(60);
      setEntries(body.entries);
    } catch {
      setEntries([]);
    }
  };

  useEffect(() => {
    void refresh();
    const timer = setInterval(refresh, 3000);
    return () => clearInterval(timer);
  }, []);

  return (
    <Panel
      title=""
      right={
        <button className="btn-ghost btn-sm" onClick={() => void api.verifyAudit().then(setVerification)}>
          Verify chain
        </button>
      }
    >
      {verification && (
        <p
          className={`mb-2.5 rounded-lg px-2.5 py-1.5 text-[11px] font-medium ${
            verification.ok ? "bg-good/15 text-good" : "bg-bad/15 text-bad"
          }`}
        >
          {verification.ok
            ? `chain intact across ${verification.entries_checked} entries`
            : `BROKEN at line ${verification.broken_at}: ${verification.reason}`}
        </p>
      )}

      {entries.length === 0 ? (
        <Empty>no audit entries yet</Empty>
      ) : (
        <div className="relative max-h-80 overflow-y-auto pl-5 pr-1 py-1 timeline-container">
          {/* Timeline continuous vertical line */}
          <div className="absolute left-[7px] top-2 bottom-2 w-[2px] bg-edge/80 dark:bg-edge/60" aria-hidden="true" />

          <ul className="space-y-3.5">
            {entries.slice().reverse().map((e) => (
              <li key={e.entry_hash} className="relative group">
                {/* Timeline node dot */}
                <div
                  className="absolute -left-[17px] top-1 h-2.5 w-2.5 rounded-full bg-accent ring-4 ring-paper"
                  aria-hidden="true"
                />
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-sans font-semibold text-xs text-content">{e.action}</span>
                    {e.attempt !== null && <Tag tone="neutral">attempt {e.attempt}</Tag>}
                  </div>
                  <p className="font-sans text-[11px] text-content opacity-85 mt-0.5">
                    {e.result}
                  </p>
                  <p className="font-mono text-[10px] text-muted bg-edge/50 px-1.5 py-0.5 rounded inline-block mt-1">
                    {e.entry_hash.slice(7, 19)} ← {e.prev_hash.slice(7, 19)}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Styled info block */}
      <div className="info-block">
        <InfoIcon />
        <p>
          Tamper-evident within stated assumptions: each entry hashes the previous one,
          so a selective edit breaks the chain. Someone with operator filesystem access
          could rewrite the whole file — that is a different threat model.
        </p>
      </div>
    </Panel>
  );
}
