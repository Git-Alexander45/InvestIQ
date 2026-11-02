"use client";

import { useApi } from "@/lib/api";
import { BOARD_LABELS, fmtNum } from "@/lib/format";
import { Asmt, Brokerage, type Column, DataTable, Grade, Loading, Panel, Price, SaveButton, SymbolLink, type PriceInfo } from "./ui";

export type BoardRow = {
  rank: number; instrument_id: number; symbol: string; exchange: string; name: string; asset_class: string;
  security_type: string; board_score: number; method: string; overall: number; grade: string; confidence: number;
  coverage: number; assessment: string | null; why_not_now: string | null;
  brokerage: Record<string, { status: string }> | null; price: PriceInfo | null;
};
export type Boards = { cycle: { cycle_date: string; status: string } | null; boards: Record<string, BoardRow[]> };

export function useBoards() {
  return useApi<Boards>("/leaderboards");
}

const COMPACT = new Set(["rank", "symbol", "grade", "overall", "assessment", "price", "save"]);

export function BoardTable({ rows, limit, compact }: { rows: BoardRow[]; limit?: number; compact?: boolean }) {
  return (
    <DataTable
      rows={limit ? rows.slice(0, limit) : rows}
      empty="No qualifying investments today. Waiting is a valid outcome."
      columns={([
        { key: "rank", label: "#", num: true },
        { key: "symbol", label: "Investment", render: (r) => <SymbolLink id={r.instrument_id} symbol={r.symbol} exchange={r.exchange} name={r.name} /> },
        { key: "name", label: "Name", render: (r) => <span className="muted">{r.name}</span> },
        { key: "grade", label: "Grade", render: (r) => <Grade g={r.grade} />, sort: (r) => r.overall },
        { key: "overall", label: "Score", num: true, render: (r) => fmtNum(r.overall, 1) },
        { key: "board_score", label: "Board", num: true, render: (r) => fmtNum(r.board_score, 1), title: "Ranking score for this board" },
        { key: "confidence", label: "Conf.", num: true, render: (r) => fmtNum(r.confidence, 2) },
        { key: "assessment", label: "Assessment", render: (r) => <Asmt a={r.assessment} /> },
        { key: "price", label: "Price", render: (r) => <Price p={r.price} compact />, sort: (r) => r.price?.cad ?? null },
        { key: "brokerage", label: "Brokerages", render: (r) => <Brokerage b={r.brokerage} /> },
        { key: "why", label: "Why not now", wrap: true, render: (r) => <span className="small muted">{r.why_not_now ?? ""}</span> },
        { key: "save", label: "", render: (r) => <SaveButton instrumentId={r.instrument_id} from="leaderboard" /> },
      ] as Column<BoardRow>[]).filter((c) => !compact || COMPACT.has(c.key))}
    />
  );
}

export function BoardPanels({ keys, limit }: { keys: string[]; limit?: number }) {
  const { data, error, loading } = useBoards();
  if (!data) return <Loading error={error} loading={loading} />;
  if (!data.cycle) return <div className="notice">No completed research cycle yet. Run research from the Dashboard.</div>;
  return (
    <>
      {keys.map((k) => (
        <Panel key={k} title={BOARD_LABELS[k] ?? k} meta={`${data.boards[k]?.[0]?.method ?? ""} · research ${data.cycle?.cycle_date}`} flush>
          <BoardTable rows={data.boards[k] ?? []} limit={limit} />
        </Panel>
      ))}
    </>
  );
}
