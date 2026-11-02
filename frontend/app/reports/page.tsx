"use client";

import Link from "next/link";
import { DataTable, Loading, PageHead, Panel } from "@/components/ui";
import { useApi } from "@/lib/api";
import { fmtTime } from "@/lib/format";

type R = { id: number; cycle_id: number | null; kind: string; subject: string; created_at: string };
type C = { id: number; cycle_date: string; attempt: number; status: string; triggered_by: string; started_at: string; finished_at: string | null;
           ai_cost_cad: number; degraded_reasons: string[]; error: string | null };

export default function Page() {
  const { data, error, loading } = useApi<R[]>("/reports");
  const { data: cycles } = useApi<C[]>("/cycles", 30_000);
  return (
    <div className="page">
      <PageHead title="AI Research Reports" sub="Every daily report and failure notice, exactly as emailed, plus the step-by-step record of each research run." />
      <Loading error={error} loading={loading && !data} />
      <div className="grid g2">
        <Panel title="Reports" flush>
          <DataTable rows={data ?? []} columns={[
            { key: "created_at", label: "Created", render: (r) => fmtTime(r.created_at) },
            { key: "kind", label: "Kind", render: (r) => <span className={`tag ${r.kind === "failure" ? "unavailable" : ""}`}>{r.kind}</span> },
            { key: "subject", label: "Subject", render: (r) => <Link href={`/reports/${r.id}`}>{r.subject}</Link>, wrap: true },
          ]} />
        </Panel>
        <Panel title="Research runs" flush>
          <DataTable rows={cycles ?? []} columns={[
            { key: "cycle_date", label: "Day" }, { key: "attempt", label: "Try", num: true },
            { key: "status", label: "Status", render: (c) => <span className={`tag ${c.status === "failed" ? "unavailable" : c.status === "succeeded" ? "verified" : "unverified"}`}>{c.status.replace("_", " ")}</span> },
            { key: "triggered_by", label: "By" }, { key: "finished_at", label: "Finished", render: (c) => fmtTime(c.finished_at) },
            { key: "ai_cost_cad", label: "AI CAD", num: true, render: (c) => c.ai_cost_cad?.toFixed(4) },
            { key: "notes", label: "Notes", wrap: true, render: (c) => <span className="small muted">{c.error ?? c.degraded_reasons?.join("; ")}</span> },
          ]} />
        </Panel>
      </div>
    </div>
  );
}
