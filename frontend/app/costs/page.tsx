"use client";

import { useState } from "react";
import { Bars } from "@/components/charts";
import { DataTable, Kpi, Loading, PageHead, Panel } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { fmtNum, fmtTime } from "@/lib/format";

type Costs = { status: { month: string; limit_cad: number; spent_cad: number; reserved_cad: number; remaining_cad: number; paused: boolean; premium_paused: boolean; requests: number; blocked: number };
               daily: { date: string; cost_cad: number; requests: number }[]; by_task: { task: string; requests: number; cost_cad: number }[];
               by_month: { month: string; cost_cad: number }[]; policy: string };
type Req = { id: number; created_at: string; task: string; tier: string; model: string; served_model: string | null; status: string; input_tokens: number; output_tokens: number; cost_cad: number; usd_cad_rate: number; error: string | null };
type Ext = { id: number; service: string; category: string; amount: number; currency: string; period: string; note: string | null; started_on: string | null };

export default function Page() {
  const { data, error, loading } = useApi<Costs>("/ai/costs", 60_000);
  const { data: reqs } = useApi<Req[]>("/ai/requests?limit=200");
  const { data: ext, reload } = useApi<Ext[]>("/external-costs");
  const [f, setF] = useState({ service: "", category: "market_data", amount: "", currency: "USD", period: "monthly", note: "" });
  const [msg, setMsg] = useState<string | null>(null);
  async function add() {
    try { await api("/external-costs", { method: "POST", json: { ...f, amount: Number(f.amount), note: f.note || null } }); setMsg("Recorded."); reload(); }
    catch (e) { setMsg(e instanceof Error ? e.message : "failed"); }
  }
  const s = data?.status;
  return (
    <div className="page">
      <PageHead title="API Cost Monitor" sub={data?.policy ?? "AI spending against the hard monthly CAD limit, plus external services you pay for."} />
      <Loading error={error} loading={loading && !data} />
      {s && (
        <div className="grid g4">
          <Kpi label={`Spent in ${s.month}`} value={`${fmtNum(s.spent_cad, 4)} CAD`} sub={`${s.requests} requests, ${s.blocked} blocked by budget`} />
          <Kpi label="Limit" value={`${fmtNum(s.limit_cad, 2)} CAD`} sub="change in Settings (raising needs confirmation)" />
          <Kpi label="Remaining" value={`${fmtNum(s.remaining_cad, 4)} CAD`} tone={s.paused ? "down" : ""} sub={s.paused ? "AI PAUSED until next month" : s.premium_paused ? "premium analysis paused (reserve)" : "available"} />
          <Kpi label="In flight" value={`${fmtNum(s.reserved_cad, 4)} CAD`} sub="worst-case reservations for running calls" />
        </div>
      )}
      <div className="grid g3">
        <Panel title="Daily spend (CAD)"><Bars unit="" data={Object.fromEntries((data?.daily ?? []).map((d) => [d.date, d.cost_cad]))} /></Panel>
        <Panel title="By task (CAD)"><Bars unit="" data={Object.fromEntries((data?.by_task ?? []).map((d) => [d.task, d.cost_cad]))} /></Panel>
        <Panel title="By month (CAD)"><Bars unit="" data={Object.fromEntries((data?.by_month ?? []).map((d) => [d.month, d.cost_cad]))} /></Panel>
      </div>
      <Panel title="AI requests" meta="every call, including blocked and failed ones" flush>
        <DataTable rows={reqs ?? []} maxHeight={420} empty="No AI requests yet." columns={[
          { key: "created_at", label: "Time", render: (r) => fmtTime(r.created_at) }, { key: "task", label: "Task" }, { key: "tier", label: "Tier" },
          { key: "model", label: "Model", render: (r) => <span className="small">{r.model}{r.served_model && r.served_model !== r.model ? ` → ${r.served_model}` : ""}</span> },
          { key: "status", label: "Status", render: (r) => <span className={`tag ${r.status === "ok" ? "verified" : r.status.startsWith("blocked") ? "unverified" : r.status === "reserved" ? "" : "unavailable"}`}>{r.status}</span> },
          { key: "tokens", label: "Tokens in/out", num: true, sort: (r) => r.input_tokens + r.output_tokens, render: (r) => `${r.input_tokens}/${r.output_tokens}` },
          { key: "cost_cad", label: "CAD", num: true, render: (r) => fmtNum(r.cost_cad, 4) },
          { key: "error", label: "Note", wrap: true, render: (r) => <span className="small muted">{r.error ?? ""}</span> },
        ]} />
      </Panel>
      <Panel title="External service costs" meta="entered by you; InvestIQ never subscribes or pays for anything">
        <div className="form-grid">
          <label className="fl">Service<input className="field" value={f.service} onChange={(e) => setF({ ...f, service: e.target.value })} /></label>
          <label className="fl">Category<select className="field" value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}>{["market_data", "email", "ai", "hosting", "other"].map((x) => <option key={x}>{x}</option>)}</select></label>
          <label className="fl">Amount<input className="field" type="number" min={0} value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></label>
          <label className="fl">Currency<select className="field" value={f.currency} onChange={(e) => setF({ ...f, currency: e.target.value })}><option>USD</option><option>CAD</option></select></label>
          <label className="fl">Period<select className="field" value={f.period} onChange={(e) => setF({ ...f, period: e.target.value })}>{["monthly", "annual", "one_time"].map((x) => <option key={x}>{x}</option>)}</select></label>
          <label className="fl">Note<input className="field" value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} /></label>
        </div>
        <div className="row" style={{ marginTop: 8 }}><button className="btn primary" disabled={!f.service || f.amount === ""} onClick={add}>Record cost</button>{msg && <span className="muted small">{msg}</span>}</div>
        <DataTable rows={ext ?? []} empty="No external costs recorded." columns={[
          { key: "service", label: "Service" }, { key: "category", label: "Category" },
          { key: "amount", label: "Amount", num: true, render: (x) => `${fmtNum(x.amount)} ${x.currency}` }, { key: "period", label: "Period" }, { key: "note", label: "Note", wrap: true },
        ]} />
      </Panel>
    </div>
  );
}
