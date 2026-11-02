"use client";

import { useState } from "react";
import { BrokerageForm } from "@/components/BrokerageForm";
import { Asmt, Brokerage, DataTable, Loading, PageHead, Panel, SymbolLink } from "@/components/ui";
import { useApi } from "@/lib/api";

type Pending = { items: { instrument_id: number; symbol: string; exchange: string; name: string; assessment: string; quant_assessment: string;
                          status: Record<string, { status: string }> }[]; how_to: Record<string, string> };
type Pick = { id: number; symbol: string; exchange: string; currency: string };
type Tpl = { columns: string[]; example: string };

export default function Page() {
  const { data, error, loading, reload } = useApi<Pending>("/brokerage/pending");
  const { data: tpl } = useApi<Tpl>("/brokerage-csv-template");
  const [sel, setSel] = useState<Pick | null>(null);
  const [result, setResult] = useState<string | null>(null);
  async function upload(file: File) {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch("/api/iq/brokerage/import", { method: "POST", body: fd });
    const body = await res.json();
    setResult(res.ok ? `Imported ${body.imported} rows. ${body.rows.filter((r: { ok: boolean }) => !r.ok).map((r: { line: number; error: string }) => `Line ${r.line}: ${r.error}`).join(" ")}` : body.detail);
    reload();
  }
  return (
    <div className="page">
      <PageHead title="Brokerage verification" sub="Investments the research would consider that are not yet verified at both Wealthsimple and Questrade. InvestIQ never logs in to brokerages or asks for credentials." />
      {data && <div className="grid g2">{Object.entries(data.how_to).map(([k, v]) => <div key={k} className="notice small"><b>{k}</b>: {v}</div>)}</div>}
      <Loading error={error} loading={loading && !data} />
      <Panel title="Needs verification" flush>
        <DataTable rows={data?.items ?? []} empty="Everything currently considered is verified." columns={[
          { key: "symbol", label: "Investment", render: (r) => <SymbolLink id={r.instrument_id} symbol={r.symbol} exchange={r.exchange} name={r.name} /> },
          { key: "name", label: "Name", render: (r) => <span className="muted">{r.name}</span> },
          { key: "assessment", label: "Assessment", render: (r) => <Asmt a={r.assessment} /> },
          { key: "status", label: "Now", render: (r) => <Brokerage b={r.status} /> },
          { key: "go", label: "", render: (r) => <button className="btn small" onClick={() => setSel({ id: r.instrument_id, symbol: r.symbol, exchange: r.exchange, currency: "CAD" })}>Record…</button> },
        ]} />
      </Panel>
      {sel && <Panel title={`Record verification: ${sel.symbol}`}><BrokerageForm instrumentId={sel.id} symbol={sel.symbol} exchange={sel.exchange} currency={sel.currency} onSaved={reload} /></Panel>}
      <Panel title="Import a CSV of checks">
        <p className="muted small">Columns: <span className="mono">{tpl?.columns.join(",")}</span><br />Example: <span className="mono">{tpl?.example}</span></p>
        <input type="file" accept=".csv,text/csv" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
        {result && <div className="notice small" style={{ marginTop: 8 }}>{result}</div>}
      </Panel>
    </div>
  );
}
