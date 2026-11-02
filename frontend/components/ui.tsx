"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { api, useApi } from "@/lib/api";
import { fmtNum } from "@/lib/format";

export function PageHead({ title, sub, children }: { title: string; sub?: React.ReactNode; children?: React.ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {sub && <p>{sub}</p>}
      </div>
      {children && <div className="actions">{children}</div>}
    </div>
  );
}

export function Panel({ title, meta, children, flush, className }: {
  title?: React.ReactNode; meta?: React.ReactNode; children: React.ReactNode; flush?: boolean; className?: string;
}) {
  return (
    <section className={`panel ${className ?? ""}`}>
      {title && <div className="panel-head"><h2>{title}</h2>{meta && <span className="meta">{meta}</span>}</div>}
      <div className={`panel-body${flush ? " flush" : ""}`}>{children}</div>
    </section>
  );
}

export function Kpi({ label, value, sub, tone }: { label: string; value: React.ReactNode; sub?: React.ReactNode; tone?: string }) {
  return (
    <div className="panel kpi">
      <div className="label">{label}</div>
      <div className={`value ${tone ?? ""}`}>{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}

export function Grade({ g }: { g?: string | null }) {
  if (!g) return <span className="faint">—</span>;
  return <span className={`grade g${g[0]}`}>{g}</span>;
}

export function Asmt({ a }: { a?: string | null }) {
  if (!a) return <span className="faint">—</span>;
  return <span className={`asmt ${a}`}>{a}</span>;
}

type BStatus = Record<string, { status: string; evidence_note?: string; verified_at?: string }> | null | undefined;
export function Brokerage({ b }: { b: BStatus }) {
  if (!b) return <span className="faint">—</span>;
  return (
    <span className="row" style={{ gap: 4 }}>
      {(["wealthsimple", "questrade"] as const).map((k) => {
        const s = b[k]?.status ?? "UNVERIFIED";
        return (
          <span key={k} className={`tag ${s.toLowerCase()}`} title={`${k}: ${s}${b[k]?.evidence_note ? ` — ${b[k]?.evidence_note}` : ""}`}>
            {k === "wealthsimple" ? "WS" : "QT"} {s === "VERIFIED" ? "✓" : s === "UNAVAILABLE" ? "✕" : "?"}
          </span>
        );
      })}
    </span>
  );
}

export type PriceInfo = {
  price: number; currency: string; cad?: number | null; usd?: number | null; as_of?: string | null; source?: string | null;
  status?: string | null; fx?: FxInfo | null; [key: `fx_${string}`]: FxInfo | undefined;
};
type FxInfo = { rate: number; as_of: string | null; source: string; type?: string };

const fxOf = (p: PriceInfo): FxInfo | null =>
  p.fx ?? ((Object.entries(p).find(([k]) => k.startsWith("fx_"))?.[1] as FxInfo | undefined) ?? null);

/** Every price shows trading currency, CAD and USD equivalents, FX, source and live/delayed status. */
export function Price({ p, compact }: { p?: PriceInfo | null; compact?: boolean }) {
  if (!p) return <span className="faint">no price data</span>;
  const other = p.currency === "CAD" ? (p.usd != null ? `≈ ${fmtNum(p.usd)} USD` : "USD n/a") : p.cad != null ? `≈ ${fmtNum(p.cad)} CAD` : "CAD n/a";
  const st = (p.status ?? "unknown").replace(/_/g, " ");
  const stClass = p.status === "real_time" ? "status-live" : "status-delayed";
  const fx = fxOf(p);
  if (compact) {
    return (
      <span className="price" title={`${p.source ?? "?"} · ${st} · ${p.as_of ?? ""}${fx ? ` · FX ${fx.rate} (${fx.source}, ${fx.as_of})` : ""}`}>
        <span className="main-px">{fmtNum(p.price)} <span className="faint">{p.currency}</span></span>
        <span className="eq">{other}</span>
      </span>
    );
  }
  return (
    <span className="price">
      <span className="main-px">{fmtNum(p.price)} {p.currency}</span>
      <span className="eq">{other}</span>
      <span className="src">
        <span className={stClass}>{st}</span> · {p.source ?? "unknown source"} · {p.as_of ?? "—"}
        {fx && <> · FX {fx.rate.toFixed(4)} ({fx.source}, {fx.as_of ?? "date n/a"}; daily reference rate)</>}
      </span>
    </span>
  );
}

export function Loading({ error, loading }: { error?: string | null; loading?: boolean }) {
  if (error) return <div className="notice bad">{error}</div>;
  if (loading) return <div className="empty">Loading…</div>;
  return null;
}

export type Column<T> = {
  key: string; label: string; num?: boolean; render?: (r: T) => React.ReactNode; sort?: (r: T) => number | string | null | undefined;
  wrap?: boolean; title?: string;
};

export function DataTable<T>({ rows, columns, initialSort, empty, maxHeight }: {
  rows: T[]; columns: Column<T>[]; initialSort?: { key: string; dir: 1 | -1 }; empty?: string; maxHeight?: number;
}) {
  const [sort, setSort] = useState(initialSort ?? null);
  const sorted = useMemo(() => {
    if (!sort) return rows;
    const col = columns.find((c) => c.key === sort.key);
    if (!col) return rows;
    const get = col.sort ?? ((r: T) => (r as Record<string, unknown>)[col.key] as number | string | null);
    return [...rows].sort((a, b) => {
      const va = get(a), vb = get(b);
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      return (va < vb ? -1 : va > vb ? 1 : 0) * sort.dir;
    });
  }, [rows, sort, columns]);
  if (!rows.length) return <div className="empty">{empty ?? "Nothing to show yet."}</div>;
  return (
    <div className="table-scroll" style={maxHeight ? { maxHeight } : undefined}>
      <table className="data">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} title={c.title} className={`sortable ${c.num ? "num" : ""}`}
                onClick={() => setSort((s) => ({ key: c.key, dir: s && s.key === c.key ? (s.dir === 1 ? -1 : 1) : c.num ? -1 : 1 }))}>
                {c.label}{sort?.key === c.key ? (sort.dir === 1 ? " ▲" : " ▼") : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c.key} className={`${c.num ? "num" : ""} ${c.wrap ? "wrap" : ""}`}>
                  {c.render ? c.render(r) : String((r as Record<string, unknown>)[c.key] ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function SymbolLink({ id, symbol, exchange, name }: { id: number; symbol: string; exchange?: string; name?: string }) {
  return (
    <Link href={`/investment/${id}`} title={name}>
      <span className="sym">{symbol}</span>{exchange && <span className="faint small"> {exchange}</span>}
    </Link>
  );
}

type Watchlist = { id: number; name: string; items: { instrument_id: number }[] };

/** "Save" on every investment: adds it to a watchlist (default: the first one). */
export function SaveButton({ instrumentId, from }: { instrumentId: number; from: string }) {
  const { data: lists, reload } = useApi<Watchlist[]>("/watchlists");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const saved = lists?.some((w) => w.items.some((i) => i.instrument_id === instrumentId));
  async function save(listId: number) {
    setBusy(true);
    try {
      await api(`/watchlists/${listId}/items`, { method: "POST", json: { instrument_id: instrumentId, saved_from: from } });
      setMsg("saved");
      reload();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "failed");
    } finally {
      setBusy(false);
    }
  }
  if (!lists) return null;
  if (saved) return <span className="tag verified" title="In a watchlist">★ saved</span>;
  if (lists.length <= 1) {
    return <button className="btn small" disabled={busy || !lists.length} onClick={() => save(lists[0].id)}>{msg ?? "☆ Save"}</button>;
  }
  return (
    <select className="field small" defaultValue="" disabled={busy} onChange={(e) => e.target.value && save(Number(e.target.value))}>
      <option value="">☆ Save to…</option>
      {lists.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
    </select>
  );
}

export function CatBars({ cats }: { cats: Record<string, { score: number; weight: number; available: boolean; note?: string | null }> }) {
  return (
    <div>
      {Object.entries(cats).map(([k, v]) => (
        <div key={k} className="cat-bar" title={v.note ?? ""}>
          <span className="muted small">{k.replace(/_/g, " ")} <span className="faint">({v.weight}%)</span></span>
          <div className="bar-track"><div className="bar-fill" style={{ width: `${v.score}%`, background: v.available ? undefined : "#3a4a5a" }} /></div>
          <span className="mono small">{v.available ? v.score.toFixed(0) : "n/a"}</span>
        </div>
      ))}
    </div>
  );
}
