"use client";

import { Heatmap } from "@/components/charts";
import { useScreen } from "@/components/Screener";
import { Loading, PageHead, Panel } from "@/components/ui";
import { useApi } from "@/lib/api";
import { tone } from "@/lib/format";

type Market = {
  markets: { label: string; symbol: string; day_change: string; one_year: string; price_text: string; source?: string; as_of?: string }[];
  usd_cad: { rate: number; as_of: string; source: string; note: string } | null;
};

export default function Page() {
  const { data, error, loading } = useApi<Market>("/market/overview");
  const { data: scr } = useScreen("all");
  const sectors: Record<string, number[]> = {};
  for (const r of scr?.rows ?? []) {
    if (r.security_type === "common_stock" && r.sector && r.change_1d_pct != null) (sectors[r.sector] ??= []).push(r.change_1d_pct);
  }
  return (
    <div className="page">
      <PageHead title="Global Market Overview" sub="Market proxies by region and asset class. Prices are end-of-day or delayed from your configured provider; nothing here is a live quote unless it says so." />
      <Loading error={error} loading={loading && !data} />
      {data && (
        <div className="grid g4">
          {data.markets.map((m) => (
            <div key={m.symbol} className="panel kpi">
              <div className="label">{m.label} · {m.symbol}</div>
              <div className={`value ${tone(parseFloat(m.day_change))}`}>{m.day_change.replace(" (1d)", "")}</div>
              <div className="sub mono">{m.one_year}</div>
              <div className="sub">{m.price_text}</div>
            </div>
          ))}
        </div>
      )}
      {data?.usd_cad && (
        <div className="notice">USD/CAD <b className="mono">{data.usd_cad.rate.toFixed(4)}</b> · {data.usd_cad.source} · {data.usd_cad.as_of}. {data.usd_cad.note}</div>
      )}
      <Panel title="Sector heatmap" meta="average daily move of stocks in the universe">
        <Heatmap scale={2} cells={Object.entries(sectors).map(([s, v]) => ({ label: s, sub: `${v.length} stocks`, value: v.reduce((a, b) => a + b, 0) / v.length }))} />
      </Panel>
      <Panel title="All instruments" meta="daily move">
        <Heatmap cells={(scr?.rows ?? []).map((r) => ({ label: r.symbol, sub: r.exchange, value: r.change_1d_pct, href: `/investment/${r.instrument_id}` }))} />
      </Panel>
    </div>
  );
}
