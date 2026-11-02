"use client";

import { useState } from "react";
import { Loading, PageHead, Panel } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { fmtTime } from "@/lib/format";

type N = { id: number; kind: string; severity: string; title: string; body: string; read_at: string | null; created_at: string; deliveries: Record<string, string> };

export default function Page() {
  const [unread, setUnread] = useState(false);
  const [kind, setKind] = useState("");
  const { data, error, loading, reload } = useApi<N[]>(`/notifications?limit=500${unread ? "&unread_only=true" : ""}`, 60_000);
  const rows = (data ?? []).filter((n) => !kind || n.kind === kind);
  const kinds = [...new Set((data ?? []).map((n) => n.kind))];
  async function markAll() {
    await api("/notifications/read", { method: "POST", json: { ids: rows.filter((n) => !n.read_at).map((n) => n.id) } });
    reload();
  }
  return (
    <div className="page">
      <PageHead title="Notifications" sub="Every notification is kept here, including those also shown as Windows notifications. Simple events (prices, grades, failures) never use AI.">
        <label className="row small muted"><input type="checkbox" checked={unread} onChange={(e) => setUnread(e.target.checked)} /> unread only</label>
        <select className="field" value={kind} onChange={(e) => setKind(e.target.value)}><option value="">all kinds</option>{kinds.map((k) => <option key={k} value={k}>{k.replace(/_/g, " ")}</option>)}</select>
        <button className="btn" onClick={markAll}>Mark shown as read</button>
      </PageHead>
      <Loading error={error} loading={loading && !data} />
      <Panel title={`${rows.length} notifications`}>
        {rows.length === 0 && <div className="empty">Nothing here.</div>}
        {rows.map((n) => (
          <div key={n.id} style={{ padding: "7px 0", borderBottom: "1px solid var(--line)", opacity: n.read_at ? 0.6 : 1 }}>
            <div className="row">
              <span className={`tag ${n.severity === "error" ? "unavailable" : n.severity === "warning" ? "unverified" : "verified"}`}>{n.severity}</span>
              <span className="tag">{n.kind.replace(/_/g, " ")}</span>
              <b>{n.title}</b>
              <span className="spacer" />
              <span className="faint small">{fmtTime(n.created_at)} · desktop: {n.deliveries?.desktop ?? "—"}</span>
            </div>
            <div className="muted small" style={{ whiteSpace: "pre-wrap" }}>{n.body}</div>
          </div>
        ))}
      </Panel>
    </div>
  );
}
