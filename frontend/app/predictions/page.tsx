"use client";

import Link from "next/link";
import { Asmt, DataTable, Grade, Loading, PageHead, Panel } from "@/components/ui";
import { useApi } from "@/lib/api";
import { fmtNum, fmtPct, fmtTime, tone } from "@/lib/format";

type Cell = { n: number; scored: number; hit_rate_pct: number | null; avg_excess_return_pct: number | null; small_sample: boolean };
type Summary = { total_predictions: number; evaluations: number; note: string; assessment?: Record<string, Record<string, Cell>>;
                 source?: Record<string, Record<string, Cell>>; ai_vs_quant: Record<string, { ai_minus_quant_excess_pct: number; conclusive: boolean }> };
type P = { id: number; instrument_id: number; assessment: string; grade: string; overall: number; source: string; made_at: string; price_at: number; currency: string;
           evaluations: { checkpoint_days: number; total_return_pct: number; excess_return_pct: number | null; success: boolean | null }[] };
const CPS = ["7", "30", "90", "180", "365"];

function Matrix({ title, data }: { title: string; data?: Record<string, Record<string, Cell>> }) {
  const rows = Object.entries(data ?? {}).map(([k, v]) => ({ k, v }));
  return (
    <Panel title={title} meta="hit rate · avg excess vs benchmark (n)" flush>
      <DataTable rows={rows} empty="No evaluations yet: the first checkpoint is 7 days after a prediction." columns={[
        { key: "k", label: "" },
        ...CPS.map((cp) => ({ key: cp, label: `${cp}d`, num: true, sort: (r: { v: Record<string, Cell> }) => r.v[cp]?.hit_rate_pct, render: (r: { v: Record<string, Cell> }) => {
          const c = r.v[cp];
          return c ? <span title={c.small_sample ? "small sample: not statistically meaningful" : ""} className={c.small_sample ? "faint" : ""}>{fmtNum(c.hit_rate_pct, 0)}% · <span className={tone(c.avg_excess_return_pct)}>{fmtPct(c.avg_excess_return_pct, 1)}</span> ({c.n})</span> : "—";
        } })),
      ]} />
    </Panel>
  );
}

export default function Page() {
  const { data, error, loading } = useApi<Summary>("/predictions/summary");
  const { data: list } = useApi<P[]>("/predictions?limit=300");
  return (
    <div className="page">
      <PageHead title="Prediction History" sub="Every recommendation is tracked at 7, 30, 90, 180 and 365 days against a benchmark, including dividends. Checkpoints are evaluation points, not sell signals. Nothing is cherry-picked." />
      <Loading error={error} loading={loading && !data} />
      {data && <div className="notice small">{data.total_predictions} predictions, {data.evaluations} evaluations. {data.note}</div>}
      <div className="grid g2">
        <Matrix title="By assessment" data={data?.assessment} />
        <Matrix title="AI-reviewed vs quant-only" data={data?.source} />
      </div>
      <Panel title="Predictions" flush>
        <DataTable rows={list ?? []} maxHeight={600} columns={[
          { key: "made_at", label: "Made", render: (p) => fmtTime(p.made_at) },
          { key: "instrument_id", label: "Investment", render: (p) => <Link href={`/investment/${p.instrument_id}`}>#{p.instrument_id}</Link> },
          { key: "assessment", label: "Call", render: (p) => <Asmt a={p.assessment} /> }, { key: "grade", label: "Grade", render: (p) => <Grade g={p.grade} />, sort: (p) => p.overall },
          { key: "price_at", label: "Price", num: true, render: (p) => `${fmtNum(p.price_at)} ${p.currency}` }, { key: "source", label: "Source" },
          ...CPS.map((cp) => ({ key: `e${cp}`, label: `${cp}d`, num: true, sort: (p: P) => p.evaluations.find((e) => String(e.checkpoint_days) === cp)?.total_return_pct, render: (p: P) => {
            const e = p.evaluations.find((x) => String(x.checkpoint_days) === cp);
            return e ? <span className={e.success == null ? "" : e.success ? "up" : "down"}>{fmtPct(e.total_return_pct, 1)}</span> : <span className="faint">·</span>;
          } })),
        ]} />
      </Panel>
    </div>
  );
}
