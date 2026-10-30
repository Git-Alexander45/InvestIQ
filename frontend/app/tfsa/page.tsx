"use client";

import { useState } from "react";
import { BoardPanels } from "@/components/Board";
import { Loading, PageHead, Panel } from "@/components/ui";
import { api, useApi } from "@/lib/api";
import { fmtCad, fmtDate } from "@/lib/format";

type Pick = { symbol: string; tfsa_score: number; growth?: number; dividend?: number } | null;
type Tfsa = {
  profile: { contribution_room_cad: number | null; room_as_of: string | null; source_note: string | null; entered_at: string } | null;
  picks: { best_overall: Pick; best_growth: Pick; best_dividend: Pick } | null;
  rules: string[];
};

export default function Page() {
  const { data, error, loading, reload } = useApi<Tfsa>("/tfsa");
  const [room, setRoom] = useState("");
  const [asOf, setAsOf] = useState("");
  const [src, setSrc] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  async function save() {
    try {
      await api("/tfsa/profile", { method: "POST", json: { contribution_room_cad: room ? Number(room) : null, room_as_of: asOf || null, source_note: src || null } });
      setMsg("Saved. Earlier entries are kept in history.");
      reload();
    } catch (e) { setMsg(e instanceof Error ? e.message : "failed"); }
  }
  return (
    <div className="page">
      <PageHead title="TFSA Intelligence" sub="Suitability for a Canadian TFSA: qualified-investment status, MER, foreign withholding drag, leverage, concentration and currency exposure." />
      <Loading error={error} loading={loading && !data} />
      {data && (
        <div className="grid g3">
          {(["best_overall", "best_growth", "best_dividend"] as const).map((k) => {
            const p = data.picks?.[k];
            return (
              <div key={k} className="panel kpi">
                <div className="label">{k.replace("best_", "Best ")} for a TFSA</div>
                <div className="value">{p ? p.symbol : "none qualified"}</div>
                <div className="sub">{p ? `TFSA score ${p.tfsa_score.toFixed(1)}` : "Waiting is a valid outcome."}</div>
              </div>
            );
          })}
        </div>
      )}
      <div className="grid g2">
        <Panel title="Your contribution room">
          {data?.profile ? (
            <p>Room <b className="mono">{fmtCad(data.profile.contribution_room_cad)}</b> as of {fmtDate(data.profile.room_as_of)} <span className="muted">({data.profile.source_note ?? "no source noted"})</span></p>
          ) : <p className="muted">Not entered. InvestIQ never assumes your room; check CRA My Account.</p>}
          <div className="form-grid">
            <label className="fl">Room (CAD)<input className="field" type="number" min={0} value={room} onChange={(e) => setRoom(e.target.value)} /></label>
            <label className="fl">As of<input className="field" type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} /></label>
            <label className="fl">Source<input className="field" value={src} onChange={(e) => setSrc(e.target.value)} placeholder="CRA My Account" /></label>
          </div>
          <div className="row" style={{ marginTop: 8 }}><button className="btn primary" onClick={save}>Save</button>{msg && <span className="muted small">{msg}</span>}</div>
        </Panel>
        <Panel title="TFSA rules InvestIQ applies">
          <ul style={{ margin: 0, paddingLeft: 18 }}>{data?.rules.map((r) => <li key={r} className="muted">{r}</li>)}</ul>
        </Panel>
      </div>
      <BoardPanels keys={["tfsa"]} />
    </div>
  );
}
