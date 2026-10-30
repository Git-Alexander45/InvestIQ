"use client";
import { BoardPanels } from "@/components/Board";
import { Heatmap } from "@/components/charts";
import { useScreen } from "@/components/Screener";
import { PageHead, Panel } from "@/components/ui";

export default function Page() {
  const { data } = useScreen("all");
  const intl = (data?.rows ?? []).filter((r) => r.country && !["CA", "US"].includes(r.country) || (r.region && !["canada", "united_states"].includes(r.region)));
  return (
    <div className="page">
      <PageHead title="International Markets" sub="Non-North-American companies and funds with at least half their look-through exposure outside Canada and the US. Check currency exposure and foreign withholding." />
      <Panel title="Daily move, international investments" meta="end-of-day">
        <Heatmap cells={intl.map((r) => ({ label: r.symbol, sub: r.country ?? r.region ?? "", value: r.change_1d_pct, href: `/investment/${r.instrument_id}` }))} />
      </Panel>
      <BoardPanels keys={["international"]} />
    </div>
  );
}
