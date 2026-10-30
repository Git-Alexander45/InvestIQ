export const fmtNum = (v: number | null | undefined, d = 2) =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : v.toLocaleString("en-CA", { minimumFractionDigits: d, maximumFractionDigits: d });

export const fmtPct = (v: number | null | undefined, d = 2, sign = true) =>
  v === null || v === undefined ? "—" : `${sign && v > 0 ? "+" : ""}${v.toFixed(d)}%`;

export const fmtCad = (v: number | null | undefined, d = 0) => (v === null || v === undefined ? "—" : `${fmtNum(v, d)} CAD`);

export const fmtDate = (v: string | null | undefined) => (v ? v.slice(0, 10) : "—");

export const fmtTime = (v: string | null | undefined) =>
  v ? new Date(v).toLocaleString("en-CA", { timeZone: "America/Toronto", hour12: false }) : "—";

export const tone = (v: number | null | undefined) => (v === null || v === undefined ? "" : v > 0 ? "up" : v < 0 ? "down" : "");

export const BOARD_LABELS: Record<string, string> = {
  best_overall: "Best overall",
  aggressive_growth_stocks: "Aggressive-growth stocks",
  diversified_growth_etfs: "Diversified growth ETFs",
  undervalued: "Undervalued",
  emerging_industries: "Emerging industries",
  dividend_growth: "Dividend growth",
  international: "International",
  defensive: "Defensive",
  commodities_precious_metals: "Commodities & precious metals",
  tfsa: "Canadian TFSA",
};
