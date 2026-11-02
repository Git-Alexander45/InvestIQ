"use client";

import { Fragment, use, useState } from "react";
import { PriceChart, type Bar } from "@/components/charts";
import { BrokerageForm } from "@/components/BrokerageForm";
import { Asmt, Brokerage, CatBars, DataTable, Grade, Loading, PageHead, Panel, Price, SaveButton, type PriceInfo } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { fmtDate, fmtNum, fmtPct, fmtTime } from "@/lib/format";

type Detail = {
  instrument: { id: number; symbol: string; exchange: string; name: string; asset_class: string; security_type: string; currency: string;
                country: string | null; sector: string | null; region: string | null; currency_hedged: boolean | null; mer_pct: number | null; themes: string[] };
  price: PriceInfo | null;
  score: { overall: number; grade: string; confidence: number; coverage: number; model: string; as_of: string; horizon: string;
           category_scores: Record<string, { score: number; weight: number; available: boolean; note?: string | null;
                                              components: { label: string; value: number; subscore: number; source: string }[] }>;
           positives: string[]; negatives: string[]; risks: string[]; avoid_reasons: string[] } | null;
  recommendation: { assessment: string; quant_assessment: string; rationale: string; why_not_now: string | null; thesis: string | null; source: string } | null;
  analyses: { id: number; role: string; model: string; status: string; output: Record<string, unknown> | null; unsupported_claims: string[]; created_at: string }[];
  fundamentals: { as_of: string; source: string; currency: string; metrics: Record<string, unknown> } | null;
  etf: { holdings_count: number; top10_pct: number; effective_n: number; coverage_pct: number; as_of: string; source: string;
         countries: Record<string, number>; top_holdings: { name: string; weight_pct: number; sector: string | null; country: string | null }[] } | null;
  brokerage: Record<string, { status: string; evidence_note?: string; verified_at?: string }>;
  notes: { id: number; kind: string; body: string; created_at: string }[];
};
type Chart = { bars: Bar[]; indicators: Record<string, never>; meta: { source?: string; data_status?: string; currency?: string; last_ts?: string };
               notes: string[]; supported_intervals: string[] };

const INTERVALS = ["1min", "5min", "15min", "1h", "1d", "1wk", "1mo"];
const RANGES: Record<string, string[]> = { intraday: ["1D", "5D", "1M"], daily: ["1M", "3M", "6M", "YTD", "1Y", "3Y", "5Y", "MAX"] };
const IND = ["sma50", "sma200", "bb", "rsi", "macd"];

export default function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data, error, loading, reload } = useApi<Detail>(`/instruments/${id}`);
  const [interval, setInterval] = useState("1d");
  const intraday = ["1min", "5min", "15min", "1h"].includes(interval);
  const [range, setRange] = useState("1Y");
  const [ind, setInd] = useState<string[]>(["sma50", "sma200", "rsi", "macd"]);
  const r = intraday && !RANGES.intraday.includes(range) ? "5D" : range;
  const { data: chart, error: chartErr } = useApi<Chart>(`/instruments/${id}/bars?interval=${interval}&range=${r}&indicators=${ind.join(",")}`);
  const [tab, setTab] = useState("score");
  const [note, setNote] = useState("");
  const [alertV, setAlertV] = useState("");
  const [alertK, setAlertK] = useState("price_below");
  const [msg, setMsg] = useState<string | null>(null);
  if (!data) return <div className="page"><Loading error={error} loading={loading} /></div>;
  const i = data.instrument;
  const supported = chart?.supported_intervals ?? ["1d", "1wk", "1mo"];
  async function addNote() {
    if (!note.trim()) return;
    await api("/notes", { method: "POST", json: { instrument_id: i.id, kind: "note", body: note } });
    setNote(""); reload();
  }
  async function addAlert() {
    try {
      await api("/alerts", { method: "POST", json: { instrument_id: i.id, kind: alertK, threshold: Number(alertV) } });
      setMsg("Alert saved. It is checked after each research run (deterministic, no AI)."); setAlertV("");
    } catch (e) { setMsg(e instanceof Error ? e.message : "failed"); }
  }
  return (
    <div className="page">
      <PageHead title={`${i.symbol} · ${i.name}`} sub={<>{i.exchange} · {i.security_type.replace("_", " ")} · {i.asset_class.replace("_", " ")} exposure · trades in {i.currency}{i.currency_hedged ? " · currency-hedged" : ""}{i.sector ? ` · ${i.sector}` : ""}{i.country ? ` · ${i.country}` : ""}</>}>
        <SaveButton instrumentId={i.id} from="detail" />
      </PageHead>
      <div className="grid g4">
        <div className="panel kpi"><div className="label">Price</div><div style={{ marginTop: 4 }}><Price p={data.price} /></div></div>
        <div className="panel kpi"><div className="label">Grade</div><div className="value"><Grade g={data.score?.grade} /> <span className="mono">{fmtNum(data.score?.overall, 1)}</span></div>
          <div className="sub">confidence {fmtNum(data.score?.confidence, 2)} · data {Math.round((data.score?.coverage ?? 0) * 100)}% · {data.score?.horizon}</div></div>
        <div className="panel kpi"><div className="label">Assessment</div><div className="value"><Asmt a={data.recommendation?.assessment} /></div>
          <div className="sub">{data.recommendation?.source === "ai_reviewed" ? "AI-reviewed" : "quantitative only"}{data.recommendation && data.recommendation.quant_assessment !== data.recommendation.assessment ? ` · rules said ${data.recommendation.quant_assessment}` : ""}</div></div>
        <div className="panel kpi"><div className="label">Brokerage availability</div><div style={{ marginTop: 6 }}><Brokerage b={data.brokerage} /></div>
          <div className="sub">BUY requires VERIFIED at both</div></div>
      </div>
      <Panel title="Chart" meta={chart?.meta?.source ? `${chart.meta.source} · ${(chart.meta.data_status ?? "").replace(/_/g, " ")} · ${chart.meta.currency} · last ${fmtTime(chart.meta.last_ts)}` : ""}>
        <div className="row" style={{ marginBottom: 8 }}>
          <div className="seg">{INTERVALS.map((x) => (
            <button key={x} className={interval === x ? "on" : ""} disabled={!supported.includes(x)} title={supported.includes(x) ? "" : "Not offered by the configured data provider"}
              onClick={() => setInterval(x)}>{x}</button>))}</div>
          <div className="seg">{(intraday ? RANGES.intraday : RANGES.daily).map((x) => <button key={x} className={r === x ? "on" : ""} onClick={() => setRange(x)}>{x}</button>)}</div>
          <div className="seg">{IND.map((x) => <button key={x} className={ind.includes(x) ? "on" : ""} onClick={() => setInd(ind.includes(x) ? ind.filter((y) => y !== x) : [...ind, x])}>{x.toUpperCase()}</button>)}</div>
        </div>
        {chartErr && <div className="notice warn">{chartErr}</div>}
        {chart?.notes?.map((n) => <div key={n} className="notice warn small">{n}</div>)}
        {chart && chart.bars.length > 0 ? <PriceChart bars={chart.bars} indicators={chart.indicators} intraday={intraday} /> : !chartErr && <div className="empty">No price data stored for this range.</div>}
      </Panel>
      <section className="panel">
        <div className="tabs">{["score", "analysis", "fundamentals", ...(data.etf ? ["holdings"] : []), "brokerage", "notes"].map((t) => <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>{t}</button>)}</div>
        <div className="panel-body">
          {tab === "score" && data.score && (
            <div className="grid g2">
              <div>
                <CatBars cats={data.score.category_scores} />
                <p className="faint small">Model: {data.score.model}. Categories without data score a neutral 50 and lower confidence. Scored {fmtTime(data.score.as_of)}.</p>
              </div>
              <div className="stack">
                {data.recommendation && <div><b>Rationale.</b> {data.recommendation.rationale}{data.recommendation.why_not_now && <div className="muted">Not now: {data.recommendation.why_not_now}</div>}</div>}
                {data.score.positives.length > 0 && <div><b className="up">Positives</b><ul>{data.score.positives.map((p) => <li key={p}>{p}</li>)}</ul></div>}
                {data.score.negatives.length > 0 && <div><b className="down">Negatives</b><ul>{data.score.negatives.map((p) => <li key={p}>{p}</li>)}</ul></div>}
                {data.score.risks.length > 0 && <div><b className="muted">Risks</b><ul>{data.score.risks.map((p) => <li key={p}>{p}</li>)}</ul></div>}
              </div>
              <details className="span2"><summary>Evidence: every input with its source</summary>
                <DataTable rows={Object.entries(data.score.category_scores).flatMap(([k, v]) => v.components.map((c) => ({ cat: k, ...c })))} columns={[
                  { key: "cat", label: "Category" }, { key: "label", label: "Metric" },
                  { key: "value", label: "Value", num: true, render: (c) => fmtNum(c.value, 2) },
                  { key: "subscore", label: "Sub-score", num: true, render: (c) => fmtNum(c.subscore, 0) }, { key: "source", label: "Source" },
                ]} />
              </details>
            </div>
          )}
          {tab === "analysis" && (data.analyses.length ? data.analyses.map((a) => (
            <div key={a.id} className="panel" style={{ marginBottom: 8 }}>
              <div className="panel-head"><h2>{a.role.replace(/_/g, " ")}</h2><span className="meta">{a.model} · {a.status} · {fmtTime(a.created_at)}</span></div>
              <div className="panel-body">
                {a.unsupported_claims?.length > 0 && <div className="notice warn small">Unsupported claims removed: {a.unsupported_claims.join("; ")}</div>}
                <pre className="small" style={{ whiteSpace: "pre-wrap", margin: 0 }}>{JSON.stringify(a.output, null, 2)}</pre>
              </div>
            </div>
          )) : <div className="empty">No AI analysis yet. AI runs only for a short, budget-limited shortlist.</div>)}
          {tab === "fundamentals" && (data.fundamentals ? (
            <>
              <p className="muted small">Source {data.fundamentals.source} · as of {fmtTime(data.fundamentals.as_of)} · {data.fundamentals.currency}</p>
              <dl className="kv">{Object.entries(data.fundamentals.metrics).filter(([, v]) => typeof v === "number").map(([k, v]) => (
                <Fragment key={k}><dt>{k.replace(/_/g, " ")}</dt><dd>{fmtNum(v as number, Math.abs(v as number) > 1e5 ? 0 : 3)}</dd></Fragment>
              ))}</dl>
            </>
          ) : <div className="empty">No fundamentals stored.</div>)}
          {tab === "holdings" && data.etf && (
            <div className="grid g2">
              <div>
                <p className="muted small">{data.etf.holdings_count} holdings · top 10 = {fmtNum(data.etf.top10_pct, 1)}% · effective N {fmtNum(data.etf.effective_n, 0)} · {data.etf.source} {fmtDate(data.etf.as_of)}</p>
                <DataTable rows={data.etf.top_holdings} columns={[
                  { key: "name", label: "Holding" }, { key: "weight_pct", label: "Weight", num: true, render: (h) => `${fmtNum(h.weight_pct, 2)}%` },
                  { key: "sector", label: "Sector" }, { key: "country", label: "Country" },
                ]} />
              </div>
              <div><b className="muted small">Country exposure</b>
                {Object.entries(data.etf.countries).sort((a, b) => b[1] - a[1]).map(([c, w]) => <div key={c} className="cat-bar"><span className="small">{c}</span><div className="bar-track"><div className="bar-fill" style={{ width: `${w}%` }} /></div><span className="mono small">{fmtPct(w, 1, false)}</span></div>)}
              </div>
            </div>
          )}
          {tab === "brokerage" && <BrokerageForm instrumentId={i.id} symbol={i.symbol} exchange={i.exchange} currency={i.currency} onSaved={reload} />}
          {tab === "notes" && (
            <div className="grid g2">
              <div className="stack">
                <textarea className="field" rows={4} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Your notes, why you like it, your thesis…" />
                <div><button className="btn primary" onClick={addNote}>Add note</button></div>
                {data.notes.map((n) => <div key={n.id} className="notice"><span className="faint small">{fmtTime(n.created_at)} · {n.kind}</span><div>{n.body}</div></div>)}
              </div>
              <div className="stack">
                <b>Price alert</b>
                <div className="row">
                  <select className="field" value={alertK} onChange={(e) => setAlertK(e.target.value)}>
                    <option value="price_below">closes below</option><option value="price_above">closes above</option><option value="pct_move_day">moves ±% in a day</option>
                  </select>
                  <input className="field" type="number" value={alertV} onChange={(e) => setAlertV(e.target.value)} placeholder={alertK === "pct_move_day" ? "%" : i.currency} />
                  <button className="btn" onClick={addAlert} disabled={!alertV}>Add</button>
                </div>
                {msg && <span className="muted small">{msg}</span>}
              </div>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
