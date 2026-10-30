"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export type Pick = { id: number; symbol: string; exchange: string; name: string; currency: string };

export function InstrumentPicker({ value, onChange }: { value: Pick | null; onChange: (p: Pick | null) => void }) {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<Pick[]>([]);
  useEffect(() => {
    if (!q.trim()) { setRows([]); return; }
    const t = setTimeout(() => api<Pick[]>(`/instruments?q=${encodeURIComponent(q.trim())}&limit=10`).then(setRows).catch(() => setRows([])), 180);
    return () => clearTimeout(t);
  }, [q]);
  if (value) {
    return <span className="row"><b className="sym">{value.symbol}</b><span className="faint small">{value.exchange} · {value.name}</span><button className="btn small" onClick={() => onChange(null)}>change</button></span>;
  }
  return (
    <div className="search" style={{ flex: "1 1 260px" }}>
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find ticker or name…" />
      {rows.length > 0 && (
        <div className="search-results">
          {rows.map((r) => (
            <a key={r.id} href="#" onClick={(e) => { e.preventDefault(); onChange(r); setQ(""); }}>
              <span className="sym">{r.symbol}</span><span className="faint small">{r.exchange}</span><span className="muted">{r.name}</span>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
