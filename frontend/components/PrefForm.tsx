"use client";

import { useState } from "react";
import { api } from "@/lib/api";

type Schema = { properties?: Record<string, Prop>; $defs?: Record<string, Schema>; title?: string };
type Prop = { type?: string; enum?: string[]; anyOf?: Prop[]; $ref?: string; title?: string; description?: string; minimum?: number;
              maximum?: number; exclusiveMinimum?: number; additionalProperties?: Prop | boolean; items?: Prop; const?: string };

const label = (k: string) => k.replace(/_/g, " ").replace(/\bcad\b/i, "CAD").replace(/\bpct\b/i, "%");

function resolve(p: Prop): Prop {
  if (p.anyOf) {
    const nonNull = p.anyOf.find((x) => x.type !== "null");
    return { ...p, ...(nonNull ?? {}), anyOf: undefined };
  }
  return p;
}

/** Renders a preference from its JSON schema. Nested objects fall back to a JSON editor. */
export function PrefForm({ prefKey, schema, value, onSaved }: { prefKey: string; schema: Schema; value: Record<string, unknown>; onSaved: () => void }) {
  const [v, setV] = useState<Record<string, unknown>>(value);
  const [json, setJson] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const set = (k: string, x: unknown) => setV({ ...v, [k]: x });
  async function save(confirmBudget = false) {
    try {
      const body: Record<string, unknown> = { ...v };
      for (const [k, s] of Object.entries(json)) body[k] = JSON.parse(s);
      await api(`/settings/${prefKey}`, { method: "PUT", json: { value: body, reason: reason || null, confirm_budget_increase: confirmBudget } });
      setMsg({ ok: true, text: "Saved. The previous version is kept in history." });
      onSaved();
    } catch (e) {
      const text = e instanceof Error ? e.message : "failed";
      if (prefKey === "ai_budget" && text.includes("confirm") && window.confirm(`${text}\n\nRaise the budget?`)) return save(true);
      setMsg({ ok: false, text });
    }
  }
  return (
    <div className="stack">
      <div className="form-grid">
        {Object.entries(schema.properties ?? {}).map(([k, raw]) => {
          const p = resolve(raw);
          const cur = v[k];
          if (p.$ref || (p.type === "object" && !(p.additionalProperties && typeof p.additionalProperties === "object" && p.additionalProperties.type === "boolean"))) {
            return (
              <label key={k} className="fl" style={{ gridColumn: "1 / -1" }}>{label(k)}
                <textarea className="field mono small" rows={6} defaultValue={JSON.stringify(cur, null, 2)} onChange={(e) => setJson({ ...json, [k]: e.target.value })} />
              </label>
            );
          }
          if (p.type === "object") {
            const obj = (cur ?? {}) as Record<string, boolean>;
            return (
              <fieldset key={k} className="fl" style={{ gridColumn: "1 / -1", border: "1px solid var(--line)", borderRadius: 6 }}>
                <legend>{label(k)}</legend>
                <div className="row">{Object.entries(obj).map(([ok, ov]) => (
                  <label key={ok} className="row small"><input type="checkbox" checked={ov} onChange={(e) => set(k, { ...obj, [ok]: e.target.checked })} />{label(ok)}</label>
                ))}</div>
              </fieldset>
            );
          }
          if (p.type === "array") {
            return <label key={k} className="fl">{label(k)} (comma separated)<input className="field" defaultValue={((cur as string[]) ?? []).join(", ")}
              onChange={(e) => set(k, e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} /></label>;
          }
          if (p.type === "boolean") {
            return <label key={k} className="row small" style={{ alignSelf: "end" }}><input type="checkbox" checked={!!cur} onChange={(e) => set(k, e.target.checked)} />{label(k)}</label>;
          }
          if (p.enum) {
            return <label key={k} className="fl">{label(k)}<select className="field" value={String(cur ?? "")} onChange={(e) => set(k, e.target.value)}>{p.enum.map((o) => <option key={o}>{o}</option>)}</select></label>;
          }
          if (p.type === "number" || p.type === "integer") {
            return <label key={k} className="fl">{label(k)}<input className="field" type="number" step={p.type === "integer" ? 1 : "any"} min={p.minimum} max={p.maximum}
              value={cur == null ? "" : String(cur)} onChange={(e) => set(k, e.target.value === "" ? null : Number(e.target.value))} /></label>;
          }
          return <label key={k} className="fl">{label(k)}<input className="field" value={cur == null ? "" : String(cur)} onChange={(e) => set(k, e.target.value || null)} /></label>;
        })}
      </div>
      <div className="row">
        <input className="field" placeholder="Reason for the change (optional)" value={reason} onChange={(e) => setReason(e.target.value)} style={{ flex: 1 }} />
        <button className="btn primary" onClick={() => save()}>Save</button>
      </div>
      {msg && <div className={`notice small ${msg.ok ? "ok" : "bad"}`}>{msg.text}</div>}
    </div>
  );
}
