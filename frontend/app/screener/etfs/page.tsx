"use client";
import { Screener } from "@/components/Screener";
import { PageHead } from "@/components/ui";

export default function Page() {
  return (
    <div className="page">
      <PageHead title="ETF Screener" sub="ETFs and funds by exposure (equity, bonds, commodities, cash), MER, diversification and long-term risk-adjusted return." />
      <Screener kind="funds" />
    </div>
  );
}
