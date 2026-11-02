"use client";

import { useMemo, useState } from "react";
import { useApi } from "@/lib/api";
import { fmtNum, fmtPct, tone } from "@/lib/format";
import { Asmt, DataTable, Grade, Loading, Panel, Price, SaveButton, SymbolLink, type Column, type PriceInfo } from "./ui";

export type ScreenRow = {
  instrument_id: number; symbol: string; exchange: string; name: string; asset_class: string; security_type: string;
  sector: string | null; country: string | null; region: string | null; currency: string; themes: string[];
  overall: number; grade: string; confidence: number; coverage: number; model: string; assessment: string;
  primary_eligible: boolean; categories: Record<string, number | null>; change_1d_pct: number | null;
  return_1y_pct: number | null; return_5y_ann_pct: number | null; volatility_1y_pct: number | null;
  max_drawdown_3y_pct: number | null; pe: number | null; dividend_yield_pct: number | null;
  revenue_growth_1y_pct: number | null; mer_pct: number | null; holdings_count: number | null; price: PriceInfo | null;
};
export type Screen = { cycle: { cycle_date: string } | null; rows: ScreenRow[] };

export function useScreen(kind: "all" | "stocks" | "funds") {
  return useApi<Screen>(`/screener?kind=${kind}`);
}

const GRADES = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D", "F"];

export function Screener({ kind }: { kind: "stocks" | "funds" }) {
  const { data, error, loading } = useScreen(kind);
  const [f, setF] = useState({ q: "", minScore: 0, minGrade: "F", sector: "", country: "", assessment: "", maxPe: "", minYield: "", maxMer: "", assetClass: "" });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  const rows = useMemo(() => (data?.rows ?? []).filter((r) => {
    if (f.q && !`${r.symbol} ${r.name}`.toLowerCase().includes(f.q.toLowerCase())) return false;
    if (r.overall < Number(f.minScore || 0)) return false;
    if (GRADES.indexOf(r.grade) > GRADES.indexOf(f.minGrade)) return false;
    if (f.sector && r.sector !== f.sector) return false;
    if (f.country && r.country !== f.country) return false;
    if (f.assessment && r.assessment !== f.assessment) return false;
    if (f.assetClass && r.asset_class !== f.assetClass) return false;
    if (f.maxPe && (r.pe == null || r.pe > Number(f.maxPe))) return false;
    if (f.minYield && (r.dividend_yield_pct ?? 0) < Number(f.minYield)) return false;
    if (f.maxMer && (r.mer_pct == null || r.mer_pct > Number(f.maxMer))) return false;
    return true;
  }), [data, f]);
  const uniq = (k: "sector" | "country" | "asset_class") => [...new Set((data?.rows ?? []).map((r) => r[k]).filter(Boolean) as string[])].sort();
  const cols: Column<ScreenRow>[] = [
    { key: "symbol", label: "Investment", render: (r) => <SymbolLink id={r.instrument_id} symbol={r.symbol} exchange={r.exchange} name={r.name} /> },
    { key: "name", label: "Name", render: (r) => <span className="muted">{r.name.slice(0, 34)}</span> },
    { key: "grade", label: "Grade", render: (r) => <Grade g={r.grade} />, sort: (r) => r.overall },
    { key: "overall", label: "Score", num: true, render: (r) => fmtNum(r.overall, 1) },
    { key: "assessment", label: "Asmt", render: (r) => <Asmt a={r.assessment} /> },
    { key: "price", label: "Price", render: (r) => <Price p={r.price} compact />, sort: (r) => r.price?.cad },
    { key: "change_1d_pct", label: "1D", num: true, render: (r) => <span className={tone(r.change_1d_pct)}>{fmtPct(r.change_1d_pct)}</span> },
    { key: "return_1y_pct", label: "1Y", num: true, render: (r) => <span className={tone(r.return_1y_pct)}>{fmtPct(r.return_1y_pct, 1)}</span> },
    { key: "volatility_1y_pct", label: "Vol", num: true, render: (r) => fmtNum(r.volatility_1y_pct, 1) },
  ];
  if (kind === "stocks") {
    cols.push(
      { key: "sector", label: "Sector", render: (r) => <span className="muted small">{r.sector ?? "—"}</span> },
      { key: "pe", label: "P/E", num: true, render: (r) => fmtNum(r.pe, 1) },
      { key: "revenue_growth_1y_pct", label: "Rev g", num: true, render: (r) => fmtPct(r.revenue_growth_1y_pct, 1) },
      { key: "growth", label: "Growth", num: true, sort: (r) => r.categories.growth, render: (r) => fmtNum(r.categories.growth ?? null, 0) },
      { key: "valuation", label: "Value", num: true, sort: (r) => r.categories.valuation, render: (r) => fmtNum(r.categories.valuation ?? null, 0) },
    );
  } else {
    cols.push(
      { key: "asset_class", label: "Exposure", render: (r) => <span className="muted small">{r.asset_class.replace("_", " ")}</span> },
      { key: "mer_pct", label: "MER", num: true, render: (r) => (r.mer_pct == null ? "—" : `${r.mer_pct.toFixed(2)}%`) },
      { key: "holdings_count", label: "Holdings", num: true, render: (r) => fmtNum(r.holdings_count, 0) },
      { key: "return_5y_ann_pct", label: "5Y ann.", num: true, render: (r) => fmtPct(r.return_5y_ann_pct, 1) },
    );
  }
  cols.push(
    { key: "dividend_yield_pct", label: "Yield", num: true, render: (r) => (r.dividend_yield_pct == null ? "—" : `${r.dividend_yield_pct.toFixed(2)}%`) },
    { key: "country", label: "Ctry", render: (r) => <span className="small">{r.country ?? "—"}</span> },
    { key: "save", label: "", render: (r) => <SaveButton instrumentId={r.instrument_id} from={`${kind}-screener`} /> },
  );
  return (
    <>
      <Panel title="Filters" meta={data?.cycle ? `scores from research ${data.cycle.cycle_date}` : ""}>
        <div className="form-grid">
          <label className="fl">Search<input className="field" value={f.q} onChange={set("q")} placeholder="ticker or name" /></label>
          <label className="fl">Minimum score<input className="field" type="number" min={0} max={100} value={f.minScore} onChange={set("minScore")} /></label>
          <label className="fl">Minimum grade<select className="field" value={f.minGrade} onChange={set("minGrade")}>{GRADES.map((g) => <option key={g}>{g}</option>)}</select></label>
          <label className="fl">Assessment<select className="field" value={f.assessment} onChange={set("assessment")}><option value="">any</option>{["BUY", "WATCH", "HOLD", "SELL", "AVOID"].map((a) => <option key={a}>{a}</option>)}</select></label>
          {kind === "stocks" ? (
            <>
              <label className="fl">Sector<select className="field" value={f.sector} onChange={set("sector")}><option value="">any</option>{uniq("sector").map((s) => <option key={s}>{s}</option>)}</select></label>
              <label className="fl">Max P/E<input className="field" type="number" value={f.maxPe} onChange={set("maxPe")} /></label>
            </>
          ) : (
            <>
              <label className="fl">Exposure<select className="field" value={f.assetClass} onChange={set("assetClass")}><option value="">any</option>{uniq("asset_class").map((s) => <option key={s}>{s}</option>)}</select></label>
              <label className="fl">Max MER %<input className="field" type="number" step="0.05" value={f.maxMer} onChange={set("maxMer")} /></label>
            </>
          )}
          <label className="fl">Country<select className="field" value={f.country} onChange={set("country")}><option value="">any</option>{uniq("country").map((s) => <option key={s}>{s}</option>)}</select></label>
          <label className="fl">Min yield %<input className="field" type="number" step="0.1" value={f.minYield} onChange={set("minYield")} /></label>
        </div>
      </Panel>
      <Loading error={error} loading={loading && !data} />
      {data && (
        <Panel title={`${rows.length} of ${data.rows.length}`} flush>
          <DataTable rows={rows} columns={cols} initialSort={{ key: "overall", dir: -1 }} maxHeight={720}
            empty={data.cycle ? "No investment matches these filters." : "No completed research cycle yet."} />
        </Panel>
      )}
    </>
  );
}
