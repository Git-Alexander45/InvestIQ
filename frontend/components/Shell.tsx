"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, useApi } from "@/lib/api";
import { fmtNum, fmtTime } from "@/lib/format";

type NavItem = { href: string; label: string };
export const NAV: { group: string; items: NavItem[] }[] = [
  { group: "Overview", items: [{ href: "/", label: "Dashboard" }, { href: "/markets", label: "Global Market Overview" }] },
  {
    group: "Research",
    items: [
      { href: "/intelligence", label: "Investment Intelligence" },
      { href: "/screener/stocks", label: "Stock Screener" },
      { href: "/screener/etfs", label: "ETF Screener" },
      { href: "/growth", label: "Growth Opportunities" },
      { href: "/undervalued", label: "Undervalued Investments" },
      { href: "/dividends", label: "Dividend Intelligence" },
      { href: "/international", label: "International Markets" },
      { href: "/tfsa", label: "TFSA Intelligence" },
    ],
  },
  {
    group: "My portfolio",
    items: [
      { href: "/portfolio", label: "Portfolio Analytics" },
      { href: "/allocation", label: "Asset Allocation" },
      { href: "/diversification", label: "Diversification Analysis" },
    ],
  },
  { group: "Information", items: [{ href: "/news", label: "News Intelligence" }, { href: "/reports", label: "AI Research Reports" }] },
  {
    group: "Learning",
    items: [
      { href: "/paper", label: "Paper Trading" },
      { href: "/strategy", label: "Strategy Performance" },
      { href: "/predictions", label: "Prediction History" },
    ],
  },
  { group: "Personal", items: [{ href: "/watchlists", label: "Watchlists" }, { href: "/notifications", label: "Notifications" }] },
  { group: "System", items: [{ href: "/costs", label: "API Cost Monitor" }, { href: "/settings", label: "Settings" }] },
];

type Status = {
  last_cycle: { date: string; status: string; finished_at: string | null } | null;
  ai_budget: { spent_cad: number; limit_cad: number; paused: boolean };
  synthetic_mode: boolean;
  warnings: string[];
  schedule: { next_run_utc: string; due_now: string | null };
};

function SearchBox() {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<{ id: number; symbol: string; exchange: string; name: string; score?: { grade: string } | null }[]>([]);
  const router = useRouter();
  useEffect(() => {
    if (q.trim().length < 1) { setRows([]); return; }
    const t = setTimeout(() => {
      api<typeof rows>(`/instruments?q=${encodeURIComponent(q.trim())}&limit=12`).then(setRows).catch(() => setRows([]));
    }, 180);
    return () => clearTimeout(t);
  }, [q]);
  return (
    <div className="search">
      <input
        placeholder="Search ticker or name…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && rows[0]) { router.push(`/investment/${rows[0].id}`); setQ(""); } }}
        aria-label="Search investments"
      />
      {rows.length > 0 && (
        <div className="search-results" onClick={() => setQ("")}>
          {rows.map((r) => (
            <Link key={r.id} href={`/investment/${r.id}`}>
              <span className="sym">{r.symbol}</span>
              <span className="faint small">{r.exchange}</span>
              <span className="muted" style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{r.name}</span>
              {r.score && <span className={`grade g${r.score.grade[0]}`} style={{ marginLeft: "auto" }}>{r.score.grade}</span>}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const { data: status } = useApi<Status>("/status", 60_000);
  const { data: unread } = useApi<unknown[]>("/notifications?unread_only=true&limit=99", 60_000);
  const cyc = status?.last_cycle;
  const cycTone = !cyc ? "" : cyc.status === "succeeded" ? "ok" : cyc.status === "failed" ? "bad" : "warn";
  const b = status?.ai_budget;
  return (
    <div className="shell">
      <nav className="rail" aria-label="Sections">
        <div className="brand"><span className="brand-mark">IQ</span><span>InvestIQ <small>local</small></span></div>
        {NAV.map((g) => (
          <div key={g.group} className="nav-group">
            <h6>{g.group}</h6>
            {g.items.map((it) => {
              const n = NAV.flatMap((x) => x.items).findIndex((x) => x.href === it.href) + 1;
              const active = it.href === "/" ? path === "/" : path.startsWith(it.href);
              return (
                <Link key={it.href} href={it.href} className={`nav-link${active ? " active" : ""}`}>
                  <span className="num">{n}</span>{it.label}
                  {it.href === "/notifications" && unread && unread.length > 0 && <span className="badge-dot">{unread.length}</span>}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>
      <div className="main">
        {status?.synthetic_mode && <div className="synthetic-banner">SYNTHETIC TEST DATA — NOT REAL MARKET INFORMATION</div>}
        <header className="topbar">
          <SearchBox />
          <div className="pills">
            {cyc ? (
              <Link href="/reports" className={`pill ${cycTone}`} title={cyc.finished_at ? `Finished ${fmtTime(cyc.finished_at)}` : ""}>
                Research <b>{cyc.date}</b> {cyc.status.replace("_", " ")}
              </Link>
            ) : (
              <span className="pill warn">No research yet</span>
            )}
            {status && <span className="pill">Next run <b>{fmtTime(status.schedule.next_run_utc)}</b> ET</span>}
            {b && (
              <Link href="/costs" className={`pill ${b.paused ? "bad" : b.spent_cad > b.limit_cad * 0.8 ? "warn" : ""}`}>
                AI <b>{fmtNum(b.spent_cad, 2)}</b> / {fmtNum(b.limit_cad, 2)} CAD
              </Link>
            )}
            {status && status.warnings.length > 0 && (
              <Link href="/settings" className="pill warn" title={status.warnings.join("\n")}>{status.warnings.length} setup notes</Link>
            )}
          </div>
        </header>
        {children}
      </div>
    </div>
  );
}
