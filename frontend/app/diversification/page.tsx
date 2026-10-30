"use client";

import { useState } from "react";
import { Bars } from "@/components/charts";
import type { DivReport } from "@/components/divtypes";
import { InstrumentPicker, type Pick } from "@/components/InstrumentPicker";
import { DataTable, Kpi, Loading, PageHead, Panel } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { fmtNum } from "@/lib/format";

type WhatIf = { instrument: string; weight_pct: number; acceptable: boolean; new_warnings: string[]; note: string;
                detail: { effective_companies_before: number; effective_companies_after: number }; after: DivReport };

export default function Page() {
  const { data, error, loading } = useApi<DivReport>("/diversification");
  const [pick, setPick] = useState<Pick | null>(null);
  const [amount, setAmount] = useState("1000");
  const [cash, setCash] = useState("0");
  const [wi, setWi] = useState<WhatIf | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  async function run() {
    if (!pick) return;
    try { setWi(await api<WhatIf>("/diversification/what-if", { method: "POST", json: { instrument_id: pick.id, amount_cad: Number(amount), cash_cad: Number(cash) } })); setMsg(null); }
    catch (e) { setMsg(e instanceof Error ? e.message : "failed"); }
  }
  const overlap = data ? Object.entries(data.etf_overlap).flatMap(([a, m]) => Object.entries(m).filter(([b]) => a < b).map(([b, v]) => ({ pair: `${a} / ${b}`, overlap: v }))) : [];
  return (
    <div className="page">
      <PageHead title="Diversification Analysis" sub="Look-through exposure across your ETFs and stocks: hidden concentration, fund overlap, correlation and currency risk." />
      <Loading error={error} loading={loading && !data} />
      {data && (
        <>
          <div className="grid g4">
            <Kpi label="Effective positions" value={fmtNum(data.effective_positions, 1)} sub="1 / sum of squared weights" />
            <Kpi label="Effective companies" value={fmtNum(data.effective_companies, 1)} sub="after ETF look-through" />
            <Kpi label="Look-through coverage" value={`${fmtNum(data.lookthrough_coverage_pct, 0)}%`} sub="fund weight with holdings data" />
            <Kpi label="Volatility (1y)" value={data.portfolio_volatility_pct == null ? "—" : `${fmtNum(data.portfolio_volatility_pct, 1)}%`} sub={`max drawdown ${data.portfolio_max_drawdown_pct == null ? "—" : fmtNum(data.portfolio_max_drawdown_pct, 1) + "%"}`} />
          </div>
          {data.flags.map((f, i) => <div key={i} className={`notice ${f.severity === "warning" ? "warn" : ""}`}>{f.message}</div>)}
          {data.data_problems?.map((p) => <div key={p} className="notice bad small">{p}</div>)}
          <div className="grid g3">
            <Panel title="Top underlying companies" flush>
              <DataTable rows={data.top_companies} empty="No holdings entered." columns={[{ key: "name", label: "Company" }, { key: "weight_pct", label: "Weight", num: true, render: (r) => `${fmtNum(r.weight_pct, 2)}%` }]} />
            </Panel>
            <Panel title="Country (look-through)"><Bars data={data.by_country} /></Panel>
            <Panel title="ETF overlap" flush>
              <DataTable rows={overlap} empty="Fewer than two funds with holdings data." columns={[{ key: "pair", label: "Funds" }, { key: "overlap", label: "Overlap", num: true, render: (r) => `${fmtNum(r.overlap, 1)}%` }]} />
            </Panel>
          </div>
        </>
      )}
      <Panel title="What if I add…" meta="hypothetical only; nothing is bought">
        <div className="row" style={{ alignItems: "flex-end" }}>
          <InstrumentPicker value={pick} onChange={setPick} />
          <label className="fl">Amount (CAD)<input className="field" type="number" min={1} value={amount} onChange={(e) => setAmount(e.target.value)} /></label>
          <label className="fl">Cash available (CAD)<input className="field" type="number" min={0} value={cash} onChange={(e) => setCash(e.target.value)} /></label>
          <button className="btn primary" disabled={!pick} onClick={run}>Evaluate</button>
        </div>
        {msg && <div className="notice bad">{msg}</div>}
        {wi && (
          <div className="stack" style={{ marginTop: 10 }}>
            <div className={`notice ${wi.acceptable ? "ok" : "warn"}`}>
              {wi.instrument} at {wi.weight_pct.toFixed(1)}% of the portfolio: {wi.acceptable ? "no new diversification warnings." : "creates new warnings:"}
              {wi.new_warnings.map((w) => <div key={w}>• {w}</div>)}
            </div>
            <div className="muted small">Effective companies {fmtNum(wi.detail.effective_companies_before, 1)} → {fmtNum(wi.detail.effective_companies_after, 1)}. {wi.note}</div>
            <div className="grid g2"><Panel title="Sector after"><Bars data={wi.after.by_sector} /></Panel><Panel title="Country after"><Bars data={wi.after.by_country} /></Panel></div>
          </div>
        )}
      </Panel>
    </div>
  );
}
