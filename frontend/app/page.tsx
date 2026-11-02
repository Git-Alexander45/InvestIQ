"use client";

import Link from "next/link";
import { useState } from "react";
import { BoardTable, type BoardRow } from "@/components/Board";
import { DataTable, Kpi, Loading, PageHead, Panel } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { BOARD_LABELS, fmtNum, fmtPct, fmtTime, tone } from "@/lib/format";

type Dash = {
  last_cycle: { id: number; cycle_date: string; status: string; finished_at: string | null; degraded_reasons: string[]; ai_cost_cad: number; error: string | null } | null;
  top: Record<string, BoardRow[]>;
  unread_notifications: number;
  ai_budget: { spent_cad: number; limit_cad: number; remaining_cad: number; paused: boolean };
  paper: { portfolio: string; name: string; kind: string; value_cad: number | null; total_return_pct: number | null; max_drawdown_pct: number | null }[];
};
type Market = { markets: { label: string; symbol: string; day_change: string; one_year: string; price_text: string }[] };
type Note = { id: number; kind: string; severity: string; title: string; body: string; created_at: string };

export default function Dashboard() {
  const { data, error, loading, reload } = useApi<Dash>("/dashboard", 60_000);
  const { data: mk } = useApi<Market>("/market/overview");
  const { data: notes } = useApi<Note[]>("/notifications?limit=8");
  const [runMsg, setRunMsg] = useState<string | null>(null);
  async function run(force = false) {
    try {
      await api("/cycles/run", { method: "POST", json: { force } });
      setRunMsg("Research started. Progress appears under AI Research Reports.");
      setTimeout(reload, 5000);
    } catch (e) {
      setRunMsg(e instanceof Error ? e.message : "could not start");
    }
  }
  const c = data?.last_cycle;
  return (
    <div className="page">
      <PageHead title="Dashboard" sub="Today's research at a glance. Assessments are research opinions; InvestIQ never places real trades.">
        <button className="btn primary" onClick={() => run(false)}>Run research now</button>
      </PageHead>
      {runMsg && <div className="notice">{runMsg}</div>}
      <Loading error={error} loading={loading && !data} />
      {data && (
        <>
          <div className="grid g4">
            <Kpi label="Last research" value={c ? c.cycle_date : "—"} tone={c?.status === "failed" ? "down" : ""}
              sub={c ? `${c.status.replace("_", " ")} · ${fmtTime(c.finished_at)}` : "not run yet"} />
            <Kpi label="AI spend this month" value={`${fmtNum(data.ai_budget.spent_cad, 2)} CAD`}
              sub={`of ${fmtNum(data.ai_budget.limit_cad, 2)} CAD hard limit${data.ai_budget.paused ? " · PAUSED" : ""}`} />
            <Kpi label="Unread notifications" value={data.unread_notifications} sub={<Link href="/notifications">open centre</Link>} />
            <Kpi label="Best paper portfolio" value={(() => {
              const best = [...data.paper].filter((p) => p.kind === "paper" && p.total_return_pct != null).sort((a, b) => (b.total_return_pct ?? 0) - (a.total_return_pct ?? 0))[0];
              return best ? `${best.portfolio} ${fmtPct(best.total_return_pct)}` : "—";
            })()} sub="simulation, virtual 100k CAD each" />
          </div>
          {c && c.degraded_reasons?.length > 0 && (
            <div className="notice warn">Degraded run: {c.degraded_reasons.slice(0, 4).join("; ")}</div>
          )}
          {c?.status === "failed" && <div className="notice bad">The last research cycle failed: {c.error}</div>}
          {mk && (
            <Panel title="Markets" meta="end-of-day; see Global Market Overview">
              <div className="grid g4">
                {mk.markets.map((m) => (
                  <div key={m.symbol} className="stack" style={{ gap: 2 }}>
                    <span className="muted small">{m.label}</span>
                    <span className={`mono ${tone(parseFloat(m.day_change))}`}>{m.day_change}</span>
                    <span className="faint small mono">{m.one_year}</span>
                  </div>
                ))}
              </div>
            </Panel>
          )}
          <div className="grid g2">
            {["best_overall", "aggressive_growth_stocks", "diversified_growth_etfs", "tfsa"].map((k) => (
              <Panel key={k} title={BOARD_LABELS[k]} meta={<Link href={k === "tfsa" ? "/tfsa" : k === "best_overall" ? "/intelligence" : "/growth"}>more</Link>} flush>
                <BoardTable rows={data.top[k] ?? []} compact />
              </Panel>
            ))}
          </div>
          <div className="grid g2">
            <Panel title="Paper trading vs benchmarks" meta={<Link href="/paper">details</Link>} flush>
              <DataTable rows={data.paper} columns={[
                { key: "portfolio", label: "Portfolio", render: (r) => <span><b className="mono">{r.portfolio}</b> <span className="muted small">{r.name}</span></span> },
                { key: "value_cad", label: "Value (CAD)", num: true, render: (r) => fmtNum(r.value_cad, 0) },
                { key: "total_return_pct", label: "Return", num: true, render: (r) => <span className={tone(r.total_return_pct)}>{fmtPct(r.total_return_pct)}</span> },
                { key: "max_drawdown_pct", label: "Max DD", num: true, render: (r) => fmtPct(r.max_drawdown_pct) },
              ]} />
            </Panel>
            <Panel title="Recent notifications" meta={<Link href="/notifications">all</Link>}>
              {notes?.length ? notes.map((n) => (
                <div key={n.id} style={{ padding: "4px 0", borderBottom: "1px solid var(--line)" }}>
                  <div className="row"><span className={`tag ${n.severity === "error" ? "unavailable" : n.severity === "warning" ? "unverified" : ""}`}>{n.kind.replace(/_/g, " ")}</span><b>{n.title}</b><span className="spacer" /><span className="faint small">{fmtTime(n.created_at)}</span></div>
                  <div className="muted small">{n.body}</div>
                </div>
              )) : <div className="empty">No notifications.</div>}
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
