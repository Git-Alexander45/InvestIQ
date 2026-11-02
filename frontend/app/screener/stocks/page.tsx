"use client";
import { Screener } from "@/components/Screener";
import { PageHead } from "@/components/ui";

export default function Page() {
  return (
    <div className="page">
      <PageHead title="Stock Screener" sub="Every stock scored in the latest research cycle. Scores are 3–5 year research opinions with data coverage and confidence; short-term moves are not used for grades." />
      <Screener kind="stocks" />
    </div>
  );
}
