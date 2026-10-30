"use client";

import { useState } from "react";
import { Asmt, Brokerage, DataTable, Grade, Loading, PageHead, Panel, SaveButton, SymbolLink } from "@/components/ui";
import { useApi } from "@/lib/api";
import { fmtNum } from "@/lib/format";

type Item = {
  recommendation: { assessment: string; quant_assessment: string; source: string; rationale: string; why_not_now: string | null;
                    thesis: string | null; primary_eligible: boolean; brokerage_status: Record<string, { status: string }>; price: number | null; price_currency: string | null };
  score: { overall: number; grade: string; confidence: number; coverage: number; positives: string[]; negatives: string[]; risks: string[] };
  instrument: { id: number; symbol: string; exchange: string; name: string; asset_class: string; security_type: string };
};
type Recs = { cycle: { cycle_date: string; strategy_version_id: number | null } | null; items: Item[] };

export default function Page() {
  const [a, setA] = useState("");
  const { data, error, loading } = useApi<Recs>(`/recommendations${a ? `?assessment=${a}` : ""}`);
  return (
    <div className="page">
      <PageHead title="Investment Intelligence" sub="Every investment's assessment from the latest research, with the reasons for and against. AI can only make an assessment more cautious, never less." />
      <div className="seg">
        {["", "BUY", "WATCH", "HOLD", "SELL", "AVOID"].map((x) => <button key={x} className={a === x ? "on" : ""} onClick={() => setA(x)}>{x || "All"}</button>)}
      </div>
      <Loading error={error} loading={loading && !data} />
      {data && (
        <Panel title={`${data.items.length} investments`} meta={data.cycle ? `research ${data.cycle.cycle_date}` : ""} flush>
          <DataTable rows={data.items} initialSort={{ key: "overall", dir: -1 }} maxHeight={760} columns={[
            { key: "symbol", label: "Investment", render: (r) => <SymbolLink id={r.instrument.id} symbol={r.instrument.symbol} exchange={r.instrument.exchange} name={r.instrument.name} />, sort: (r) => r.instrument.symbol },
            { key: "grade", label: "Grade", render: (r) => <Grade g={r.score.grade} />, sort: (r) => r.score.overall },
            { key: "overall", label: "Score", num: true, render: (r) => fmtNum(r.score.overall, 1), sort: (r) => r.score.overall },
            { key: "coverage", label: "Data", num: true, title: "Share of scoring weight backed by data", render: (r) => `${Math.round(r.score.coverage * 100)}%`, sort: (r) => r.score.coverage },
            { key: "assessment", label: "Assessment", render: (r) => <span className="row"><Asmt a={r.recommendation.assessment} />{r.recommendation.source === "ai_reviewed" && <span className="tag">AI reviewed</span>}</span>, sort: (r) => r.recommendation.assessment },
            { key: "brokerage", label: "Brokerages", render: (r) => <Brokerage b={r.recommendation.brokerage_status} /> },
            { key: "why", label: "Rationale", wrap: true, render: (r) => (
              <div className="small">
                <div>{r.recommendation.rationale}</div>
                {r.recommendation.why_not_now && <div className="muted">Not now: {r.recommendation.why_not_now}</div>}
                {r.score.risks?.length > 0 && <div className="faint">Risks: {r.score.risks.slice(0, 2).join("; ")}</div>}
              </div>
            ) },
            { key: "save", label: "", render: (r) => <SaveButton instrumentId={r.instrument.id} from="intelligence" /> },
          ]} />
        </Panel>
      )}
    </div>
  );
}
