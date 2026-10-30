"use client";

import { useState } from "react";
import { InstrumentPicker, type Pick } from "@/components/InstrumentPicker";
import { DataTable, Kpi, Loading, PageHead, Panel, Price, SymbolLink, type PriceInfo } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { fmtNum, fmtTime, tone } from "@/lib/format";

type Holding = { id: number; instrument_id: number; symbol: string; exchange: string; name: string; account_type: string; quantity: number;
                 average_cost: number; cost_currency: string; price: PriceInfo | null; value_cad: number | null; cost_cad: number | null;
                 gain_cad: number | null; entered_at: string; note: string | null };
type Holdings = { holdings: Holding[]; total_value_cad: number; note: string };
type Hist = { id: number; symbol: string; exchange: string; account_type: string; quantity: number; average_cost: number; cost_currency: string; entered_at: string }[];

export default function Page() {
  const { data, error, loading, reload } = useApi<Holdings>("/holdings");
  const { data: hist, reload: reloadHist } = useApi<Hist>("/holdings/history");
  const [pick, setPick] = useState<Pick | null>(null);
  const [f, setF] = useState({ account_type: "TFSA", quantity: "", average_cost: "", cost_currency: "CAD", note: "" });
  const [msg, setMsg] = useState<string | null>(null);
  async function save() {
    if (!pick) return;
    try {
      await api("/holdings", { method: "POST", json: { instrument_id: pick.id, account_type: f.account_type, quantity: Number(f.quantity),
        average_cost: Number(f.average_cost || 0), cost_currency: f.cost_currency, note: f.note || null } });
      setMsg(`Saved ${pick.symbol}. Enter quantity 0 to record a closed position.`);
      setPick(null); setF({ ...f, quantity: "", average_cost: "", note: "" }); reload(); reloadHist();
    } catch (e) { setMsg(e instanceof Error ? e.message : "failed"); }
  }
  const cost = data?.holdings.reduce((a, h) => a + (h.cost_cad ?? 0), 0) ?? 0;
  return (
    <div className="page">
      <PageHead title="Portfolio Analytics" sub="Your real holdings, entered by you. InvestIQ never connects to your brokerage, never asks for passwords and never assumes balances." />
      <Loading error={error} loading={loading && !data} />
      {data && (
        <div className="grid g3">
          <Kpi label="Market value" value={`${fmtNum(data.total_value_cad, 0)} CAD`} sub="priced at latest stored close" />
          <Kpi label="Cost basis" value={`${fmtNum(cost, 0)} CAD`} sub="converted at current reference FX" />
          <Kpi label="Unrealised gain" value={`${fmtNum(data.total_value_cad - cost, 0)} CAD`} tone={tone(data.total_value_cad - cost)} />
        </div>
      )}
      <Panel title="Enter or update a holding">
        <div className="row" style={{ alignItems: "flex-end" }}>
          <InstrumentPicker value={pick} onChange={(p) => { setPick(p); if (p) setF({ ...f, cost_currency: p.currency === "USD" ? "USD" : "CAD" }); }} />
          <label className="fl">Account<select className="field" value={f.account_type} onChange={(e) => setF({ ...f, account_type: e.target.value })}>
            {["TFSA", "RRSP", "FHSA", "NON_REGISTERED"].map((a) => <option key={a}>{a}</option>)}</select></label>
          <label className="fl">Quantity<input className="field" type="number" min={0} step="any" value={f.quantity} onChange={(e) => setF({ ...f, quantity: e.target.value })} /></label>
          <label className="fl">Average cost<input className="field" type="number" min={0} step="any" value={f.average_cost} onChange={(e) => setF({ ...f, average_cost: e.target.value })} /></label>
          <label className="fl">Cost currency<select className="field" value={f.cost_currency} onChange={(e) => setF({ ...f, cost_currency: e.target.value })}><option>CAD</option><option>USD</option></select></label>
          <label className="fl">Note<input className="field" value={f.note} onChange={(e) => setF({ ...f, note: e.target.value })} /></label>
          <button className="btn primary" disabled={!pick || f.quantity === ""} onClick={save}>Save</button>
        </div>
        {msg && <div className="muted small" style={{ marginTop: 6 }}>{msg}</div>}
        <div className="faint small" style={{ marginTop: 6 }}>Not in the list? Add it to the research universe from Settings → Universe.</div>
      </Panel>
      {data && (
        <Panel title="Current holdings" meta={data.note} flush>
          <DataTable rows={data.holdings} empty="No holdings entered." columns={[
            { key: "symbol", label: "Investment", render: (h) => <SymbolLink id={h.instrument_id} symbol={h.symbol} exchange={h.exchange} name={h.name} /> },
            { key: "account_type", label: "Account" },
            { key: "quantity", label: "Qty", num: true, render: (h) => fmtNum(h.quantity, 4) },
            { key: "average_cost", label: "Avg cost", num: true, render: (h) => `${fmtNum(h.average_cost)} ${h.cost_currency}` },
            { key: "price", label: "Price", render: (h) => <Price p={h.price} compact />, sort: (h) => h.price?.cad },
            { key: "value_cad", label: "Value CAD", num: true, render: (h) => fmtNum(h.value_cad, 0) },
            { key: "gain_cad", label: "Gain CAD", num: true, render: (h) => <span className={tone(h.gain_cad)}>{fmtNum(h.gain_cad, 0)}</span> },
            { key: "weight", label: "Weight", num: true, sort: (h) => h.value_cad, render: (h) => (h.value_cad && data.total_value_cad ? `${((h.value_cad / data.total_value_cad) * 100).toFixed(1)}%` : "—") },
          ]} />
        </Panel>
      )}
      <Panel title="Entry history" meta="every edit is kept" flush>
        <DataTable rows={hist ?? []} columns={[
          { key: "entered_at", label: "Entered", render: (h) => fmtTime(h.entered_at) }, { key: "symbol", label: "Symbol" },
          { key: "account_type", label: "Account" }, { key: "quantity", label: "Qty", num: true },
          { key: "average_cost", label: "Avg cost", num: true, render: (h) => `${fmtNum(h.average_cost)} ${h.cost_currency}` },
        ]} />
      </Panel>
    </div>
  );
}
