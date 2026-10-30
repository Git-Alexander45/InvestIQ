"use client";

import { useState } from "react";
import { DataTable, Grade, Loading, PageHead, Panel, SymbolLink } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { fmtNum, fmtTime } from "@/lib/format";

type Item = { id: number; instrument_id: number; symbol: string; exchange: string; name: string; grade: string | null; overall: number | null; saved_at: string; saved_from: string | null; archived: boolean };
type WL = { id: number; name: string; description: string | null; archived: boolean; items: Item[] };
type AlertRow = { id: number; symbol: string; instrument_id: number; kind: string; threshold: number; active: boolean; last_triggered_at: string | null };

export default function Page() {
  const [showArchived, setShowArchived] = useState(false);
  const { data, error, loading, reload } = useApi<WL[]>(`/watchlists${showArchived ? "?include_archived=true" : ""}`);
  const { data: alerts, reload: reloadAlerts } = useApi<AlertRow[]>("/alerts");
  const [name, setName] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  async function act(fn: () => Promise<unknown>) {
    try { await fn(); setMsg(null); reload(); reloadAlerts(); } catch (e) { setMsg(e instanceof Error ? e.message : "failed"); }
  }
  return (
    <div className="page">
      <PageHead title="Watchlists" sub="Save investments from anywhere with ☆ Save. Removing an item archives it, so nothing you saved is ever lost.">
        <label className="row small muted"><input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} /> show archived</label>
        <input className="field" placeholder="New watchlist name" value={name} onChange={(e) => setName(e.target.value)} />
        <button className="btn" disabled={!name.trim()} onClick={() => act(async () => { await api("/watchlists", { method: "POST", json: { name } }); setName(""); })}>Create</button>
      </PageHead>
      {msg && <div className="notice bad">{msg}</div>}
      <Loading error={error} loading={loading && !data} />
      {data?.map((w) => (
        <Panel key={w.id} title={`${w.name}${w.archived ? " (archived)" : ""}`} meta={`${w.items.length} saved`} flush>
          <DataTable rows={w.items} empty="Nothing saved yet." columns={[
            { key: "symbol", label: "Investment", render: (i) => <SymbolLink id={i.instrument_id} symbol={i.symbol} exchange={i.exchange} name={i.name} /> },
            { key: "name", label: "Name", render: (i) => <span className="muted">{i.name}</span> },
            { key: "grade", label: "Grade", render: (i) => <Grade g={i.grade} />, sort: (i) => i.overall },
            { key: "overall", label: "Score", num: true, render: (i) => fmtNum(i.overall, 1) },
            { key: "saved_at", label: "Saved", render: (i) => `${fmtTime(i.saved_at)}${i.saved_from ? ` · ${i.saved_from}` : ""}` },
            { key: "act", label: "", render: (i) => <button className="btn small" onClick={() => act(() => api(`/saved/${i.id}`, { method: "PATCH", json: { archived: !i.archived } }))}>{i.archived ? "Restore" : "Archive"}</button> },
          ]} />
        </Panel>
      ))}
      <Panel title="Price alerts" meta="checked after each research run; no AI involved" flush>
        <DataTable rows={alerts ?? []} empty="No alerts. Add one from an investment's Notes tab." columns={[
          { key: "symbol", label: "Investment", render: (a) => <SymbolLink id={a.instrument_id} symbol={a.symbol} /> },
          { key: "kind", label: "Rule", render: (a) => a.kind.replace(/_/g, " ") }, { key: "threshold", label: "Threshold", num: true },
          { key: "last_triggered_at", label: "Last fired", render: (a) => fmtTime(a.last_triggered_at) },
          { key: "active", label: "", render: (a) => <button className="btn small" onClick={() => act(() => api(`/alerts/${a.id}`, { method: "PATCH", json: { active: !a.active } }))}>{a.active ? "Pause" : "Resume"}</button> },
        ]} />
      </Panel>
    </div>
  );
}
