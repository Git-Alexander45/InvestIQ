export type DivReport = {
  total_value_cad: number; cash_cad: number; weights: Record<string, number>;
  by_asset_class: Record<string, number>; by_vehicle: Record<string, number>; by_region: Record<string, number>;
  by_country: Record<string, number>; by_sector: Record<string, number>; by_trading_currency: Record<string, number>;
  by_underlying_currency: Record<string, number>; top_companies: { key: string; name: string; weight_pct: number }[];
  etf_overlap: Record<string, Record<string, number>>; effective_positions: number; effective_companies: number;
  lookthrough_coverage_pct: number; correlations: Record<string, Record<string, number | null>> | null;
  portfolio_volatility_pct: number | null; portfolio_max_drawdown_pct: number | null; factor_exposure: Record<string, unknown>;
  flags: { type: string; severity: string; message: string }[]; data_problems?: string[]; holdings_entered?: number;
};
