"use client";

import { useState } from "react";
import { Loading, PageHead, Panel } from "@/components/ui";
import { useApi } from "@/lib/api";
import { fmtTime } from "@/lib/format";

type N = { item: { id: number; title: string; url: string; source_key: string; published_at: string | null; official: boolean; summary: string | null };
           assessment: { topic: string; impact: string; confirmation: string; importance: number; confidence: number; horizon: string;
                         what_happened: string; affected_symbols: string[]; affected_sectors: string[]; affected_etfs: string[]; method: string } };

const TOPICS = ["", "central_bank", "inflation", "employment", "economic_reports", "tariffs_trade", "elections_politics", "geopolitics", "regulation", "earnings", "corporate_action", "insider", "institutional", "technology", "supply_chain", "energy", "commodities", "general"];

export default function Page() {
  const [days, setDays] = useState(3);
  const [topic, setTopic] = useState("");
  const [official, setOfficial] = useState(false);
  const [sym, setSym] = useState("");
  const q = `/news?days=${days}${topic ? `&topic=${topic}` : ""}${official ? "&official_only=true" : ""}${sym ? `&symbol=${encodeURIComponent(sym)}` : ""}`;
  const { data, error, loading } = useApi<N[]>(q);
  return (
    <div className="page">
      <PageHead title="News Intelligence" sub="Headlines from official and licensed sources with InvestIQ's assessment: what happened, whether it is confirmed, likely impact and affected securities. Duplicates are merged." />
      <div className="row">
        <div className="seg">{[1, 3, 7, 30].map((d) => <button key={d} className={days === d ? "on" : ""} onClick={() => setDays(d)}>{d}d</button>)}</div>
        <select className="field" value={topic} onChange={(e) => setTopic(e.target.value)}>{TOPICS.map((t) => <option key={t} value={t}>{t ? t.replace(/_/g, " ") : "all topics"}</option>)}</select>
        <label className="row small muted"><input type="checkbox" checked={official} onChange={(e) => setOfficial(e.target.checked)} /> official sources only</label>
        <input className="field" placeholder="symbol" value={sym} onChange={(e) => setSym(e.target.value.toUpperCase())} style={{ width: 100 }} />
      </div>
      <Loading error={error} loading={loading && !data} />
      {data && (
        <Panel title={`${data.length} items`}>
          {data.length === 0 && <div className="empty">No news collected for this filter.</div>}
          {data.map(({ item, assessment: a }) => (
            <article key={item.id} style={{ padding: "8px 0", borderBottom: "1px solid var(--line)" }}>
              <div className="row">
                <span className={`tag ${a.impact === "positive" ? "verified" : a.impact === "negative" ? "unavailable" : ""}`}>{a.impact}</span>
                <span className={`tag ${a.confirmation === "confirmed" ? "verified" : "unverified"}`}>{a.confirmation}</span>
                <span className="tag">{a.topic.replace(/_/g, " ")}</span>
                <a href={item.url} target="_blank" rel="noopener noreferrer"><b>{item.title}</b></a>
                <span className="spacer" />
                <span className="faint small">{item.source_key}{item.official ? " (official)" : ""} · {fmtTime(item.published_at)}</span>
              </div>
              <div className="muted small">{a.what_happened}</div>
              <div className="faint small">
                importance {a.importance.toFixed(2)} · confidence {a.confidence.toFixed(2)} · {a.horizon} · {a.method}
                {a.affected_symbols.length > 0 && <> · affects {a.affected_symbols.join(", ")}</>}
                {a.affected_etfs.length > 0 && <> · via ETFs {a.affected_etfs.slice(0, 5).join(", ")}</>}
              </div>
            </article>
          ))}
        </Panel>
      )}
    </div>
  );
}
