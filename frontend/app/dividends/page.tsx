"use client";
import { BoardPanels } from "@/components/Board";
import { useScreen } from "@/components/Screener";
import { DataTable, Grade, PageHead, Panel, SymbolLink } from "@/components/ui";
import { fmtNum } from "@/lib/format";

export default function Page() {
  const { data } = useScreen("all");
  const payers = (data?.rows ?? []).filter((r) => (r.dividend_yield_pct ?? 0) > 0);
  return (
    <div className="page">
      <PageHead title="Dividend Intelligence" sub="Dividend growth and sustainability, not just high yield. Suspiciously high yields are capped. In a TFSA, US dividends lose 15% to withholding tax." />
      <BoardPanels keys={["dividend_growth"]} />
      <Panel title="All dividend payers in the universe" flush>
        <DataTable rows={payers} initialSort={{ key: "dividend_yield_pct", dir: -1 }} columns={[
          { key: "symbol", label: "Investment", render: (r) => <SymbolLink id={r.instrument_id} symbol={r.symbol} exchange={r.exchange} /> },
          { key: "name", label: "Name", render: (r) => <span className="muted">{r.name}</span> },
          { key: "grade", label: "Grade", render: (r) => <Grade g={r.grade} />, sort: (r) => r.overall },
          { key: "dividend_yield_pct", label: "Yield", num: true, render: (r) => `${fmtNum(r.dividend_yield_pct, 2)}%` },
          { key: "country", label: "Country" },
          { key: "wh", label: "TFSA withholding", render: (r) => (r.country === "US" ? <span className="tag unverified">15% lost</span> : <span className="faint">—</span>), sort: (r) => (r.country === "US" ? 1 : 0) },
        ]} />
      </Panel>
    </div>
  );
}
