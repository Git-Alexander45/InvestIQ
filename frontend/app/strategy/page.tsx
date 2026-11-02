"use client";

import { useState } from "react";
import { DataTable, Loading, PageHead, Panel } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { fmtPct, fmtTime } from "@/lib/format";

type SV = { id: number; name: string; version: number; kind: string; notes: string; config_hash: string; created_at: string; config: Record<string, unknown> };
type Strat = { production_id: number; frozen_id: number; versions: SV[]; promotions: { strategy_version_id: number; reason: string; created_at: string }[] };
type Run = { id: number; strategy_version_id: number; start_date: string; end_date: string; split_date: string; passed_validation: boolean;
             validation_notes: string[]; variants_tested: number; in_sample: Record<string, number>; out_of_sample: Record<string, number>; created_at: string; data_sources: string[] };
type Bt = { running: boolean; last_result: Record<string, unknown> | null; runs: Run[] };

export default function Page() {
  const { data, error, loading, reload } = useApi<Strat>("/strategies");
  const { data: bt, reload: reloadBt } = useApi<Bt>("/backtests", 15_000);
  const [form, setForm] = useState({ strategy_version_id: "", start: "2019-01-01", split: "2023-01-01", end: "2025-12-31" });
  const [cfg, setCfg] = useState("");
  const [notes, setNotes] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  async function act(fn: () => Promise<unknown>, ok: string) {
    try { await fn(); setMsg(ok); reload(); reloadBt(); } catch (e) { setMsg(e instanceof Error ? e.message : "failed"); }
  }
  const latestExp = data?.versions.filter((v) => v.kind === "experimental").at(-1);
  return (
    <div className="page">
      <PageHead title="Strategy Performance" sub="The frozen baseline never changes. Experimental versions are tested by walk-forward backtests with a fixed out-of-sample period; only you can promote one, and only after it passes." />
      {msg && <div className="notice">{msg}</div>}
      <Loading error={error} loading={loading && !data} />
      {data && (
        <Panel title="Strategy versions" flush>
          <DataTable rows={data.versions} columns={[
            { key: "id", label: "ID", num: true }, { key: "name", label: "Name", render: (v) => <b>{v.name} v{v.version}</b> },
            { key: "kind", label: "Kind", render: (v) => <span className="row"><span className="tag">{v.kind}</span>{v.id === data.production_id && <span className="tag verified">production</span>}</span> },
            { key: "notes", label: "Notes", wrap: true }, { key: "created_at", label: "Created", render: (v) => fmtTime(v.created_at) },
            { key: "hash", label: "Config", render: (v) => <span className="mono faint small">{v.config_hash.slice(0, 10)}</span> },
          ]} />
        </Panel>
      )}
      <div className="grid g2">
        <Panel title="Run a backtest">
          <div className="form-grid">
            <label className="fl">Strategy version<select className="field" value={form.strategy_version_id} onChange={(e) => setForm({ ...form, strategy_version_id: e.target.value })}>
              <option value="">choose…</option>{data?.versions.map((v) => <option key={v.id} value={v.id}>{v.name} v{v.version}</option>)}</select></label>
            <label className="fl">Start<input className="field" type="date" value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value })} /></label>
            <label className="fl">Out-of-sample from<input className="field" type="date" value={form.split} onChange={(e) => setForm({ ...form, split: e.target.value })} /></label>
            <label className="fl">End<input className="field" type="date" value={form.end} onChange={(e) => setForm({ ...form, end: e.target.value })} /></label>
          </div>
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn primary" disabled={!form.strategy_version_id || bt?.running}
              onClick={() => act(() => api("/backtests", { method: "POST", json: { ...form, strategy_version_id: Number(form.strategy_version_id) } }), "Backtest started; results appear below.")}>Start backtest</button>
            {bt?.running && <span className="muted small">running…</span>}
          </div>
          <p className="faint small">AI and news are excluded from backtests (not reproducible point in time). Entries are at the first close after each decision; delisted instruments stay in the universe until delisting.</p>
        </Panel>
        <Panel title="New experimental version">
          <p className="muted small">Paste a full configuration (start from the current experimental one). It is validated; weights must sum to 100 per model.</p>
          <div className="row"><button className="btn small" onClick={() => setCfg(JSON.stringify(latestExp?.config ?? {}, null, 2))}>Load current experimental config</button></div>
          <textarea className="field mono small" rows={8} style={{ width: "100%", marginTop: 6 }} value={cfg} onChange={(e) => setCfg(e.target.value)} />
          <input className="field" style={{ width: "100%", marginTop: 6 }} placeholder="What changed and why" value={notes} onChange={(e) => setNotes(e.target.value)} />
          <button className="btn" style={{ marginTop: 6 }} disabled={!cfg || notes.length < 3}
            onClick={() => act(async () => api("/strategies/experimental", { method: "POST", json: { config: JSON.parse(cfg), notes } }), "Experimental version created.")}>Create version</button>
        </Panel>
      </div>
      <Panel title="Backtest results" meta="all runs are kept, pass or fail" flush>
        <DataTable rows={bt?.runs ?? []} empty="No backtests yet." columns={[
          { key: "id", label: "Run", num: true }, { key: "strategy_version_id", label: "Version", num: true },
          { key: "period", label: "Period", render: (r) => <span className="small">{r.start_date} → {r.split_date} → {r.end_date}</span> },
          { key: "is", label: "In-sample excess", num: true, sort: (r) => r.in_sample.excess_vs_baseline_pct, render: (r) => fmtPct(r.in_sample.excess_vs_baseline_pct ?? null) },
          { key: "oos", label: "Out-of-sample excess", num: true, sort: (r) => r.out_of_sample.excess_vs_baseline_pct, render: (r) => fmtPct(r.out_of_sample.excess_vs_baseline_pct ?? null) },
          { key: "passed_validation", label: "Validation", render: (r) => <span className={`tag ${r.passed_validation ? "verified" : "unavailable"}`}>{r.passed_validation ? "passed" : "failed"}</span> },
          { key: "validation_notes", label: "Notes", wrap: true, render: (r) => <span className="small muted">{r.validation_notes.join("; ")}</span> },
          { key: "promote", label: "", render: (r) => r.passed_validation && r.strategy_version_id !== data?.production_id ? (
            <button className="btn small" onClick={() => {
              const reason = window.prompt("Promote this strategy to production? It will drive future recommendations. Reason (min 10 characters):");
              if (reason) act(() => api(`/strategies/${r.strategy_version_id}/promote`, { method: "POST", json: { backtest_run_id: r.id, reason, confirm: true } }), "Promoted.");
            }}>Promote…</button>) : null },
        ]} />
      </Panel>
    </div>
  );
}
