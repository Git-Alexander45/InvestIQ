"use client";

import { Bars } from "@/components/charts";
import type { DivReport } from "@/components/divtypes";
import { Loading, PageHead, Panel } from "@/components/ui";
import { useApi } from "@/lib/api";

type PaperDetail = { latest_snapshot: { holdings: { symbol: string; value_cad: number; asset_class: string }[]; cash_cad: number; total_value_cad: number } | null };

function byClass(p?: PaperDetail | null): Record<string, number> {
  const s = p?.latest_snapshot;
  if (!s || !s.total_value_cad) return {};
  const out: Record<string, number> = { cash: (s.cash_cad / s.total_value_cad) * 100 };
  for (const h of s.holdings) out[h.asset_class] = (out[h.asset_class] ?? 0) + (h.value_cad / s.total_value_cad) * 100;
  return out;
}

function PaperAlloc({ code }: { code: string }) {
  const { data } = useApi<PaperDetail>(`/paper/${code}`);
  return <div><b className="mono">Portfolio {code}</b><Bars data={byClass(data)} /></div>;
}

export default function Page() {
  const { data, error, loading } = useApi<DivReport>("/diversification");
  return (
    <div className="page">
      <PageHead title="Asset Allocation" sub="Your holdings by underlying exposure (what you actually own through funds), trading currency and vehicle, beside the simulated portfolios." />
      <Loading error={error} loading={loading && !data} />
      {data && data.holdings_entered === 0 && <div className="notice">No holdings entered yet. Add them in Portfolio Analytics.</div>}
      {data && (
        <div className="grid g3">
          <Panel title="Asset class (look-through)"><Bars data={data.by_asset_class} /></Panel>
          <Panel title="Region"><Bars data={data.by_region} /></Panel>
          <Panel title="Sector"><Bars data={data.by_sector} /></Panel>
          <Panel title="Trading currency"><Bars data={data.by_trading_currency} /></Panel>
          <Panel title="Underlying currency exposure" meta="hedging considered"><Bars data={data.by_underlying_currency} /></Panel>
          <Panel title="Vehicle"><Bars data={data.by_vehicle} /></Panel>
        </div>
      )}
      <Panel title="Paper portfolio allocations" meta="simulation">
        <div className="grid g4">
          {["A", "B", "C", "D"].map((c) => <PaperAlloc key={c} code={c} />)}
        </div>
      </Panel>
    </div>
  );
}
