"use client";

import { useState } from "react";
import { api, useApi } from "@/lib/api";
import { fmtTime } from "@/lib/format";
import { DataTable } from "./ui";

type Hist = { current: Record<string, { status: string; evidence_note?: string; verified_at?: string; expired?: boolean }>;
              history: { id: number; brokerage: string; status: string; ticker: string; exchange: string; evidence_note: string; evidence_source: string; verified_at: string }[] };

/** Manual verification: the owner checks the brokerage app and records what they saw. No logins, no credentials. */
export function BrokerageForm({ instrumentId, symbol, exchange, currency, onSaved }: {
  instrumentId: number; symbol: string; exchange: string; currency: string; onSaved?: () => void;
}) {
  const { data, reload } = useApi<Hist>(`/brokerage/${instrumentId}`);
  const [f, setF] = useState({ brokerage: "wealthsimple", status: "VERIFIED", ticker: symbol, exchange, trading_currency: currency, tfsa_eligible: "true", evidence_note: "", checked_on: "" });
  const [msg, setMsg] = useState<string | null>(null);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  async function save() {
    try {
      await api("/brokerage/verify", { method: "POST", json: {
        instrument_id: instrumentId, brokerage: f.brokerage, status: f.status, ticker: f.ticker, exchange: f.exchange,
        trading_currency: f.trading_currency || null, tfsa_eligible: f.tfsa_eligible === "" ? null : f.tfsa_eligible === "true",
        evidence_note: f.evidence_note, checked_on: f.checked_on || null } });
      setMsg("Recorded."); reload(); onSaved?.();
    } catch (e) { setMsg(e instanceof Error ? e.message : "failed"); }
  }
  return (
    <div className="stack">
      <div className="notice small">Check the brokerage app or website yourself, then record what you saw. InvestIQ never logs in to brokerages and never asks for passwords. Verifications expire after the period set in Settings.</div>
      <div className="form-grid">
        <label className="fl">Brokerage<select className="field" value={f.brokerage} onChange={set("brokerage")}><option value="wealthsimple">Wealthsimple</option><option value="questrade">Questrade</option></select></label>
        <label className="fl">Status<select className="field" value={f.status} onChange={set("status")}><option>VERIFIED</option><option>UNAVAILABLE</option><option>UNVERIFIED</option></select></label>
        <label className="fl">Ticker shown<input className="field" value={f.ticker} onChange={set("ticker")} /></label>
        <label className="fl">Exchange shown<input className="field" value={f.exchange} onChange={set("exchange")} /></label>
        <label className="fl">Currency<select className="field" value={f.trading_currency} onChange={set("trading_currency")}><option>CAD</option><option>USD</option></select></label>
        <label className="fl">Buyable in TFSA<select className="field" value={f.tfsa_eligible} onChange={set("tfsa_eligible")}><option value="true">yes</option><option value="false">no</option><option value="">not checked</option></select></label>
        <label className="fl">Checked on<input className="field" type="date" value={f.checked_on} onChange={set("checked_on")} /></label>
      </div>
      <label className="fl">What you saw (evidence)<input className="field" value={f.evidence_note} onChange={set("evidence_note")} placeholder="e.g. Listed in WS app as RY (TSX, CAD), buy button available in TFSA" /></label>
      <div className="row"><button className="btn primary" onClick={save} disabled={f.evidence_note.trim().length < 3}>Record verification</button>{msg && <span className="muted small">{msg}</span>}</div>
      {data && (
        <DataTable rows={data.history} columns={[
          { key: "verified_at", label: "Checked", render: (h) => fmtTime(h.verified_at) }, { key: "brokerage", label: "Brokerage" },
          { key: "status", label: "Status", render: (h) => <span className={`tag ${h.status.toLowerCase()}`}>{h.status}</span> },
          { key: "ticker", label: "Ticker" }, { key: "exchange", label: "Exch." }, { key: "evidence_source", label: "How" },
          { key: "evidence_note", label: "Evidence", wrap: true },
        ]} empty="No verification recorded yet: both brokerages count as UNVERIFIED." />
      )}
    </div>
  );
}
