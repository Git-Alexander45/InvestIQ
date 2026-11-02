"use client";
import { BoardPanels } from "@/components/Board";
import { PageHead } from "@/components/ui";

export default function Page() {
  return (
    <div className="page">
      <PageHead title="Undervalued Investments" sub="Ranked 60% valuation and 40% overall grade. Financial strength of at least 50 is required, to avoid value traps." />
      <BoardPanels keys={["undervalued", "defensive"]} />
    </div>
  );
}
