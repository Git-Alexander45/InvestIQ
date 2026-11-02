"use client";

import { useState } from "react";
import { LinesChart } from "@/components/charts";
import { DataTable, Loading, PageHead, Panel } from "@/components/ui";
import { useApi } from "@/lib/api";
import { fmtNum, fmtPct, fmtTime, tone } from "@/lib/format";

type M = { portfolio: string; name: string; kind: string; value_cad?: number; total_return_pct?: number; annualized_return_pct?: number | null;
           max_drawdown_pct?: number; volatility_pct?: number | null; sharpe?: number | null; win_rate_pct?: number | null; closed_trades?: number;
           dividends_net_cad?: number; withholding_tax_cad?: number; trading_costs_cad?: { total: number; fx_fees: number; slippage: number; commissions: number };
           observations: number; note?: string; annualized_return_note?: string };
type Overview = { portfolios: Record<string, M>; curves: Record<string, [string, number][]>; excess_vs_benchmarks_pct: Record<string, Record<string, number | null>>; notice: string };
type Detail = { portfolio: { code: string; name: string; description: string; policy: Record<string, unknown> };
                latest_snapshot: { holdings: { symbol: string; quantity: number; price: number; currency: string; value_cad: number; unrealized_cad: number; price_source: string; price_date: string }[]; cash_cad: number } | null;
                orders: { id: number; symbol: string; side: string; quantity: number; status: string; reason: string; decision_at: string; decision_price: number }[];
                fills: { id: number; symbol: string; side: string; quantity: number; fill_price: number; currency: string; fx_rate_to_cad: number; gross_cad: number; fx_fee_cad: number; slippage_cad: number; filled_at: string }[];
                dividends: { symbol: string; gross_cad: number; withholding_cad: number; net_cad: number; paid_at: string; reinvested: boolean }[] };

export default function Page() {
  const { data, error, loading } = useApi<Overview>("/paper");
  const [sel, setSel] = useState("A");
  const { data: d } = useApi<Detail>(`/paper/${sel}`);
  const rows = data ? Object.values(data.portfolios) : [];
  return (
    <div className="page">
      <PageHead title="Paper Trading" sub="Four simulated 100,000 CAD portfolios against buy-and-hold benchmarks, with realistic fills (next open), slippage, FX fees, dividends and withholding tax. Virtual money only." />
      <Loading error={error} loading={loading && !data} />
      {data && (
        <>
          <Panel title="Growth of 100 (all portfolios and benchmarks)" meta="dashed = benchmark">
            <LinesChart curves={Object.entries(data.curves).map(([k, pts]) => ({ name: k, points: pts, dashed: k.startsWith("BM_") }))} />
          </Panel>
          <Panel title="Performance" meta="every portfolio and benchmark is always reported" flush>
            <DataTable rows={rows} columns={[
              { key: "portfolio", label: "Code", render: (r) => <button className="btn small" onClick={() => setSel(r.portfolio)}>{r.portfolio}</button> },
              { key: "name", label: "Name", render: (r) => <span className="muted">{r.name}</span> },
              { key: "value_cad", label: "Value CAD", num: true, render: (r) => fmtNum(r.value_cad, 0) },
              { key: "total_return_pct", label: "Total", num: true, render: (r) => <span className={tone(r.total_return_pct)}>{fmtPct(r.total_return_pct)}</span> },
              { key: "annualized_return_pct", label: "Ann.", num: true, render: (r) => (r.annualized_return_pct == null ? <span className="faint" title={r.annualized_return_note}>n/a</span> : fmtPct(r.annualized_return_pct)) },
              { key: "max_drawdown_pct", label: "Max DD", num: true, render: (r) => fmtPct(r.max_drawdown_pct) },
              { key: "volatility_pct", label: "Vol", num: true, render: (r) => fmtNum(r.volatility_pct, 1) },
              { key: "sharpe", label: "Sharpe", num: true, render: (r) => fmtNum(r.sharpe, 2) },
              { key: "win_rate_pct", label: "Win %", num: true, render: (r) => fmtNum(r.win_rate_pct, 0) },
              { key: "dividends_net_cad", label: "Divs net", num: true, render: (r) => fmtNum(r.dividends_net_cad, 0) },
              { key: "costs", label: "Costs", num: true, sort: (r) => r.trading_costs_cad?.total, render: (r) => fmtNum(r.trading_costs_cad?.total, 0) },
              { key: "vs", label: "vs XEQT", num: true, sort: (r) => data.excess_vs_benchmarks_pct[r.portfolio]?.BM_GLOBAL, render: (r) => fmtPct(data.excess_vs_benchmarks_pct[r.portfolio]?.BM_GLOBAL ?? null) },
            ]} />
          </Panel>
        </>
      )}
      {d && (
        <div className="grid g2">
          <Panel title={`${d.portfolio.code} holdings`} meta={d.latest_snapshot ? `cash ${fmtNum(d.latest_snapshot.cash_cad, 0)} CAD` : ""} flush>
            <DataTable rows={d.latest_snapshot?.holdings ?? []} empty="No positions yet." columns={[
              { key: "symbol", label: "Symbol" }, { key: "quantity", label: "Qty", num: true },
              { key: "price", label: "Price", num: true, render: (h) => `${fmtNum(h.price)} ${h.currency}` },
              { key: "value_cad", label: "Value CAD", num: true, render: (h) => fmtNum(h.value_cad, 0) },
              { key: "unrealized_cad", label: "Unreal.", num: true, render: (h) => <span className={tone(h.unrealized_cad)}>{fmtNum(h.unrealized_cad, 0)}</span> },
              { key: "price_source", label: "Source", render: (h) => <span className="faint small">{h.price_source} {h.price_date}</span> },
            ]} />
          </Panel>
          <Panel title={`${d.portfolio.code} orders`} meta="decided after close, filled next open" flush>
            <DataTable rows={d.orders} maxHeight={320} columns={[
              { key: "decision_at", label: "Decided", render: (o) => fmtTime(o.decision_at) }, { key: "symbol", label: "Symbol" },
              { key: "side", label: "Side" }, { key: "quantity", label: "Qty", num: true }, { key: "status", label: "Status" },
              { key: "reason", label: "Reason", wrap: true, render: (o) => <span className="small muted">{o.reason}</span> },
            ]} />
          </Panel>
          <Panel title="Fills" flush>
            <DataTable rows={d.fills} maxHeight={320} columns={[
              { key: "filled_at", label: "Filled", render: (f) => fmtTime(f.filled_at) }, { key: "symbol", label: "Symbol" }, { key: "side", label: "Side" },
              { key: "quantity", label: "Qty", num: true }, { key: "fill_price", label: "Price", num: true, render: (f) => `${fmtNum(f.fill_price)} ${f.currency}` },
              { key: "fx_rate_to_cad", label: "FX", num: true, render: (f) => f.fx_rate_to_cad.toFixed(4) },
              { key: "fx_fee_cad", label: "FX fee", num: true, render: (f) => fmtNum(f.fx_fee_cad) }, { key: "slippage_cad", label: "Slip.", num: true, render: (f) => fmtNum(f.slippage_cad) },
            ]} />
          </Panel>
          <Panel title="Dividends" flush>
            <DataTable rows={d.dividends} maxHeight={320} empty="No dividends received yet." columns={[
              { key: "paid_at", label: "Paid", render: (x) => fmtTime(x.paid_at) }, { key: "symbol", label: "Symbol" },
              { key: "gross_cad", label: "Gross", num: true, render: (x) => fmtNum(x.gross_cad) }, { key: "withholding_cad", label: "Withheld", num: true, render: (x) => fmtNum(x.withholding_cad) },
              { key: "net_cad", label: "Net", num: true, render: (x) => fmtNum(x.net_cad) }, { key: "reinvested", label: "DRIP", render: (x) => (x.reinvested ? "yes" : "no") },
            ]} />
          </Panel>
        </div>
      )}
      {data && <div className="notice small">{data.notice} Portfolios A–D buy only investments assessed BUY (score of at least 80 and, unless you turn it off in Settings → Paper trading, verified at both brokerages). Holding cash while nothing qualifies is a valid outcome, and benchmarks always invest.</div>}
    </div>
  );
}
