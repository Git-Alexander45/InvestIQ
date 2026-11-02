"use client";

import Link from "next/link";
import { useState } from "react";
import { PrefForm } from "@/components/PrefForm";
import { DataTable, Loading, PageHead, Panel } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { fmtTime } from "@/lib/format";

type Settings = { preferences: Record<string, Record<string, unknown>>; schema: Record<string, { properties?: Record<string, never> }>;
                  system: { env: string; api_host: string; api_port: number; database: string; configured: Record<string, boolean>; synthetic_allowed: boolean; note: string } };
type Health = { warnings: string[]; database: { revision: string; head: string; migrations_pending: boolean; dialect: string }; last_backup: { status: string; created_at: string; restore_tested_at: string | null } | null };
type Backups = { backups: { id: number; path: string; size_bytes: number; status: string; created_at: string; verified_at: string | null; restore_tested_at: string | null; method: string }[];
                 disk: { directory: string; count: number; total_bytes: number; note: string } };

const SECTIONS: { key: string; title: string; help: string }[] = [
  { key: "research_schedule", title: "Daily research time", help: "Runs every day at this local time. Missed runs (computer asleep or off) run as soon as InvestIQ is running again." },
  { key: "email", title: "Email", help: "Provider credentials (SMTP password, Resend key) go in the .env file. 'outbox' saves reports as files." },
  { key: "notifications", title: "Notifications", help: "Windows notifications per event type. Every notification is also kept in the in-app centre." },
  { key: "ai_budget", title: "AI spending limit", help: "Hard monthly limit in CAD. AI pauses when reached. It is never raised automatically; raising it asks for confirmation." },
  { key: "ai_models", title: "AI model configuration", help: "Which model handles each tier. Premium analysis only runs for a short, filtered shortlist." },
  { key: "display", title: "Currency display", help: "Primary and secondary currency for amounts." },
  { key: "universe", title: "Asset classes and research universe", help: "Which asset classes and regions are researched." },
  { key: "risk_limits", title: "Risk limits", help: "Concentration and diversification limits used for portfolio-fit checks." },
  { key: "brokerage", title: "Brokerage verification", help: "Whether BUY requires verification at both Wealthsimple and Questrade, and when verifications expire." },
  { key: "market_data", title: "Market data providers", help: "API keys go in .env. Providers without keys are skipped and the run is marked degraded." },
  { key: "paper_trading", title: "Paper trading", help: "Simulation costs: commission, FX fee, slippage. Virtual money only." },
];

export default function Page() {
  const { data, error, loading, reload } = useApi<Settings>("/settings");
  const { data: health } = useApi<Health>("/status");
  const { data: bk, reload: reloadBk } = useApi<Backups>("/backups");
  const [msg, setMsg] = useState<string | null>(null);
  const [inst, setInst] = useState({ symbol: "", exchange: "TSX", name: "", asset_class: "equity", security_type: "common_stock", currency: "CAD", country: "CA", sector: "" });
  async function act(fn: () => Promise<unknown>, ok: string) {
    setMsg("Working…");
    try { await fn(); setMsg(ok); reloadBk(); } catch (e) { setMsg(e instanceof Error ? e.message : "failed"); }
  }
  return (
    <div className="page">
      <PageHead title="Settings" sub="Every change is saved as a new version with the previous one kept, and recorded in the audit log." />
      <Loading error={error} loading={loading && !data} />
      {health && health.warnings.length > 0 && <div className="notice warn">{health.warnings.map((w) => <div key={w}>• {w}</div>)}</div>}
      {msg && <div className="notice">{msg}</div>}
      {data && (
        <Panel title="System" meta={`${data.system.env} · API ${data.system.api_host}:${data.system.api_port} · ${data.system.database}`}>
          <div className="row">{Object.entries(data.system.configured).map(([k, v]) => <span key={k} className={`tag ${v ? "verified" : "unverified"}`}>{k.replace(/_/g, " ")} {v ? "configured" : "not set"}</span>)}</div>
          <p className="muted small">{data.system.note}</p>
          {health && <p className="faint small">Database {health.database.dialect} revision {health.database.revision} (latest {health.database.head}){health.database.migrations_pending ? " — run 'investiq migrate'" : ""}.</p>}
        </Panel>
      )}
      {data && SECTIONS.map((s) => (
        <details key={s.key} className="panel" open={s.key === "research_schedule"}>
          <summary className="panel-head" style={{ listStyle: "none" }}><h2>{s.title}</h2><span className="meta"><Link href="#" onClick={(e) => e.preventDefault()}>{s.key}</Link></span></summary>
          <div className="panel-body">
            <p className="muted small" style={{ marginTop: 0 }}>{s.help}</p>
            <PrefForm prefKey={s.key} schema={data.schema[s.key] as never} value={data.preferences[s.key]} onSaved={reload} />
          </div>
        </details>
      ))}
      <Panel title="Add an investment to the research universe" meta="identity only; data comes from providers">
        <div className="form-grid">
          <label className="fl">Symbol<input className="field" value={inst.symbol} onChange={(e) => setInst({ ...inst, symbol: e.target.value.toUpperCase() })} /></label>
          <label className="fl">Exchange<select className="field" value={inst.exchange} onChange={(e) => setInst({ ...inst, exchange: e.target.value })}>
            {["TSX", "TSXV", "NEO", "CBOE_CA", "NYSE", "NASDAQ", "NYSEARCA", "BATS", "LSE", "XETRA", "EURONEXT", "SIX", "TSE", "HKEX", "ASX", "OTHER"].map((x) => <option key={x}>{x}</option>)}</select></label>
          <label className="fl">Name<input className="field" value={inst.name} onChange={(e) => setInst({ ...inst, name: e.target.value })} /></label>
          <label className="fl">Underlying exposure<select className="field" value={inst.asset_class} onChange={(e) => setInst({ ...inst, asset_class: e.target.value })}>
            {["equity", "bond", "commodity", "precious_metal", "cash_equivalent", "multi_asset"].map((x) => <option key={x}>{x}</option>)}</select></label>
          <label className="fl">Vehicle<select className="field" value={inst.security_type} onChange={(e) => setInst({ ...inst, security_type: e.target.value })}>
            {["common_stock", "adr", "etf", "mutual_fund", "reit", "preferred", "trust"].map((x) => <option key={x}>{x}</option>)}</select></label>
          <label className="fl">Trading currency<select className="field" value={inst.currency} onChange={(e) => setInst({ ...inst, currency: e.target.value })}>
            {["CAD", "USD", "EUR", "GBP", "JPY", "CHF", "AUD", "HKD"].map((x) => <option key={x}>{x}</option>)}</select></label>
          <label className="fl">Country (ISO)<input className="field" maxLength={2} value={inst.country} onChange={(e) => setInst({ ...inst, country: e.target.value.toUpperCase() })} /></label>
          <label className="fl">Sector<input className="field" value={inst.sector} onChange={(e) => setInst({ ...inst, sector: e.target.value })} /></label>
        </div>
        <button className="btn primary" style={{ marginTop: 8 }} disabled={!inst.symbol || !inst.name}
          onClick={() => act(() => api("/instruments", { method: "POST", json: { ...inst, sector: inst.sector || null, country: inst.country || null } }), `${inst.symbol} added; it will be researched in the next cycle.`)}>Add</button>
      </Panel>
      <Panel title="Brokerage verification" meta={<Link href="/brokerage">open queue</Link>}>
        <p className="muted small" style={{ margin: 0 }}>Record what you see in the Wealthsimple and Questrade apps, one at a time or by CSV import. BUY assessments require both to be VERIFIED.</p>
      </Panel>
      <Panel title="Backups and data export" meta={bk ? `${bk.disk.count} files · ${(bk.disk.total_bytes / 1e6).toFixed(1)} MB in ${bk.disk.directory}` : ""} flush>
        <div className="panel-body row">
          <button className="btn primary" onClick={() => act(() => api("/backups", { method: "POST" }), "Backup created and verified.")}>Back up now</button>
          <button className="btn" onClick={() => act(async () => { const r = await api<{ file: string }>("/export", { method: "POST" }); window.location.href = `/api/iq/export/${r.file}`; }, "Export ready.")}>Export all data (CSV zip)</button>
          <span className="faint small">{bk?.disk.note}</span>
        </div>
        <DataTable rows={bk?.backups ?? []} empty="No backups yet." columns={[
          { key: "created_at", label: "Created", render: (b) => fmtTime(b.created_at) }, { key: "method", label: "Method" },
          { key: "size_bytes", label: "Size", num: true, render: (b) => `${(b.size_bytes / 1e6).toFixed(2)} MB` },
          { key: "status", label: "Status", render: (b) => <span className={`tag ${b.status === "verified" ? "verified" : b.status === "failed" ? "unavailable" : "unverified"}`}>{b.status}</span> },
          { key: "restore_tested_at", label: "Restore test", render: (b) => (b.restore_tested_at ? fmtTime(b.restore_tested_at) : "—") },
          { key: "act", label: "", render: (b) => (
            <span className="row">
              <button className="btn small" onClick={() => act(() => api(`/backups/${b.id}/verify`, { method: "POST" }), "Verified.")}>Verify</button>
              <button className="btn small" onClick={() => act(() => api(`/backups/${b.id}/restore-test`, { method: "POST" }), "Restore test passed: row counts match.")}>Restore test</button>
            </span>) },
        ]} />
      </Panel>
    </div>
  );
}
