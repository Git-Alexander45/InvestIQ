"use client";
import { BoardPanels } from "@/components/Board";
import { PageHead } from "@/components/ui";

export default function Page() {
  return (
    <div className="page">
      <PageHead title="Growth Opportunities" sub="Aggressive-growth stocks, diversified growth ETFs and emerging-industry companies. A promising industry does not make a promising company: each company's own grade decides." />
      <BoardPanels keys={["aggressive_growth_stocks", "diversified_growth_etfs", "emerging_industries"]} />
    </div>
  );
}
