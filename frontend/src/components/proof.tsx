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
      <Panel title="Network">
        <p className="text-xs text-bad">
          monitor unreachable: {error}. No claim about external traffic can be made
          from this panel right now.
        </p>
      </Panel>
    );
  }
  if (!status) return <Panel title="Network"><Empty>sampling…</Empty></Panel>;

  const unavailable = !status.monitor_available;

  return (
    <Panel
      title="Network"
      right={
        <Tag tone={unavailable ? "bad" : status.sovereign_mode ? "good" : "bad"}>
          {unavailable ? "MONITOR UNAVAILABLE" : status.sovereign_mode ? "SOVEREIGN" : "EXTERNAL TRAFFIC"}
        </Tag>
      }
    >
      {unavailable && (
        <p className="mb-2 rounded border border-bad/40 bg-bad/5 px-2 py-1 text-[11px] text-bad">
          The socket monitor could not run{status.monitor_error ? `: ${status.monitor_error}` : ""}.
          The counters below are placeholders, not evidence.
        </p>
      )}

      <div className="mb-3 grid grid-cols-2 gap-2">
        <div className="rounded border border-edge/60 p-2">
          <p className="text-[10px] uppercase tracking-wider text-muted">external</p>
          <p
            className={`font-mono text-3xl font-semibold ${
              unavailable ? "text-muted" : status.external_active === 0 ? "text-good" : "text-bad"
            }`}
          >
            {unavailable ? "—" : status.external_active}
          </p>
          <p className="text-[10px] text-muted">the number that matters</p>
        </div>
        <div className="space-y-1 rounded border border-edge/60 p-2">
          <KeyValue k="loopback" v={unavailable ? "—" : status.loopback_active} />
          <KeyValue k="trusted LAN" v={unavailable ? "—" : status.trusted_lan_active} />
          <KeyValue k="unknown" v={unavailable ? "—" : status.unknown_active} />
        </div>
      </div>

      <KeyValue k="mode" v={status.mode} />
      <KeyValue k="trusted subnet" v={status.trusted_subnet ?? "not configured"} />
      <KeyValue
        k="negative control"
        v={
          status.negative_control
            ? `${status.negative_control.blocked_external_attempts} attempt(s), ${
                status.negative_control.all_blocked ? "all blocked" : "NOT all blocked"
              }`
            : "none run"
        }
      />
      <KeyValue k="sampled at" v={status.sampled_at ?? "never"} />

      <p className="mt-2 border-t border-edge pt-2 text-[10px] leading-relaxed text-muted">
        Trusted-LAN traffic is active when organisation users are using SETU; active
        external traffic is separate and is the figure above. Scope: {status.scope}. A
        sampled count of zero is evidence from this sample, not a proof that no packet
        ever left the machine.
      </p>
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
      right={<span className="text-[10px] text-muted">{view.host} · max loaded {view.max_loaded_models}</span>}
    >
      <ul className="space-y-1">
        {view.models.map((m) => (
          <li key={m.id} className="rounded border border-edge/60 px-2 py-1.5">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs text-slate-200">{m.model}</span>
              <Tag tone={m.enabled ? "accent" : "neutral"}>{m.enabled ? m.id : "disabled"}</Tag>
              <Tag tone={m.integrity_verified === true ? "good" : "warn"}>
                {m.integrity_verified === null
                  ? "digest not verified"
                  : m.integrity_verified
                    ? "verified"
                    : "MISMATCH"}
              </Tag>
            </div>
            <p className="mt-0.5 font-mono text-[10px] text-muted">
              {m.expected_manifest_digest
                ? m.expected_manifest_digest.slice(0, 26) + "…"
                : "no expected digest recorded"}
            </p>
            <p className="text-[10px] text-muted">{m.capabilities.join(", ")}</p>
          </li>
        ))}
      </ul>
      <div className="mt-2 border-t border-edge pt-2">
        <KeyValue k="thresholds" v={JSON.stringify(view.thresholds)} />
        <KeyValue k="max attempts" v={JSON.stringify(view.max_attempts)} />
        <KeyValue k="max iterations" v={view.max_iterations} />
      </div>
      <p className="mt-2 text-[10px] leading-relaxed text-muted">
        Adding or swapping a model for an existing role is an edit to
        config/models.yaml. A genuinely new capability also needs an agent
        implementation — that part is not free.
      </p>
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
      title="Audit"
      right={
        <button
          onClick={() => void api.verifyAudit().then(setVerification)}
          className="rounded bg-edge px-2 py-0.5 text-[10px] text-slate-300 hover:bg-edge/70"
        >
          verify chain
        </button>
      }
    >
      {verification && (
        <p
          className={`mb-2 rounded px-2 py-1 text-[11px] ${
            verification.ok ? "bg-good/10 text-good" : "bg-bad/10 text-bad"
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
        <ul className="max-h-72 space-y-0.5 overflow-auto">
          {entries.slice().reverse().map((e) => (
            <li key={e.entry_hash} className="border-b border-edge/40 py-1 last:border-0">
              <div className="flex items-center gap-2">
                <span className="font-mono text-[11px] text-slate-200">{e.action}</span>
                {e.attempt !== null && <Tag>attempt {e.attempt}</Tag>}
              </div>
              <p className="font-mono text-[10px] text-muted">
                {e.result} · {e.entry_hash.slice(7, 19)} ← {e.prev_hash.slice(7, 19)}
              </p>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-[10px] leading-relaxed text-muted">
        Tamper-evident within stated assumptions: each entry hashes the previous one,
        so a selective edit breaks the chain. Someone with operator filesystem access
        could rewrite the whole file — that is a different threat model.
      </p>
    </Panel>
  );
}
