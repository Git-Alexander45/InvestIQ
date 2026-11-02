"use client";

import Link from "next/link";
import { use, useState } from "react";
import { Loading, PageHead } from "@/components/ui";
import { useApi } from "@/lib/api";

type R = { id: number; subject: string; text: string; kind: string; created_at: string };

export default function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data, error, loading } = useApi<R>(`/reports/${id}`);
  const [plain, setPlain] = useState(false);
  return (
    <div className="page">
      <PageHead title={data?.subject ?? "Report"} sub={<Link href="/reports">← all reports</Link>}>
        <div className="seg"><button className={!plain ? "on" : ""} onClick={() => setPlain(false)}>Formatted</button><button className={plain ? "on" : ""} onClick={() => setPlain(true)}>Plain text</button></div>
      </PageHead>
      <Loading error={error} loading={loading && !data} />
      {data && (plain
        ? <pre className="panel panel-body small" style={{ whiteSpace: "pre-wrap" }}>{data.text}</pre>
        : <iframe className="report-frame" sandbox="" src={`/api/iq/reports/${id}/html`} title={data.subject} />)}
    </div>
  );
}
