"use client";

import {
  CandlestickSeries,
  ColorType,
  createChart,
  HistogramSeries,
  type IChartApi,
  LineSeries,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

const BASE = {
  layout: { background: { type: ColorType.Solid, color: "#0d141c" }, textColor: "#7d91a5", fontSize: 11,
            panes: { separatorColor: "#1c2a38", separatorHoverColor: "#263848" } },
  grid: { vertLines: { color: "#121d28" }, horzLines: { color: "#121d28" } },
  rightPriceScale: { borderColor: "#1c2a38" },
  timeScale: { borderColor: "#1c2a38", timeVisible: true, secondsVisible: false },
  crosshair: { mode: 0 },
  autoSize: true,
} as const;

export type Bar = { ts: string; open: number; high: number; low: number; close: number; volume: number | null };
type Ind = Record<string, (number | null)[] | Record<string, (number | null)[]>>;

const toTime = (ts: string, intraday: boolean): Time =>
  (intraday ? (Math.floor(new Date(ts).getTime() / 1000) as UTCTimestamp) : ts.slice(0, 10)) as Time;

function line(values: (number | null)[], times: Time[]) {
  return values.map((v, i) => (v == null ? { time: times[i] } : { time: times[i], value: v }));
}

const MA_COLORS = ["#f2b84b", "#39c2d7", "#b48cff", "#ff8fb1"];

export function PriceChart({ bars, indicators, intraday, height = 520 }: {
  bars: Bar[]; indicators: Ind; intraday: boolean; height?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current || !bars.length) return;
    const chart: IChartApi = createChart(ref.current, { ...BASE, height });
    const times = bars.map((b) => toTime(b.ts, intraday));
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: "#2fcf8a", downColor: "#f2647a", borderVisible: false, wickUpColor: "#2fcf8a", wickDownColor: "#f2647a",
    });
    candles.setData(bars.map((b, i) => ({ time: times[i], open: b.open, high: b.high, low: b.low, close: b.close })));
    const vol = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "vol" });
    vol.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    vol.setData(bars.map((b, i) => ({ time: times[i], value: b.volume ?? 0, color: b.close >= b.open ? "#1d5b4588" : "#6d2a3788" })));
    let ci = 0;
    for (const [name, v] of Object.entries(indicators)) {
      if (Array.isArray(v) && (name.startsWith("sma") || name.startsWith("ema"))) {
        const s = chart.addSeries(LineSeries, { color: MA_COLORS[ci++ % MA_COLORS.length], lineWidth: 1, priceLineVisible: false,
                                                lastValueVisible: false, title: name.toUpperCase() });
        s.setData(line(v, times));
      }
    }
    const bb = indicators.bollinger as Record<string, (number | null)[]> | undefined;
    if (bb) {
      for (const k of ["upper", "middle", "lower"]) {
        const s = chart.addSeries(LineSeries, { color: k === "middle" ? "#5b7489" : "#3b6c8a", lineWidth: 1, lineStyle: k === "middle" ? 2 : 0,
                                                priceLineVisible: false, lastValueVisible: false });
        s.setData(line(bb[k], times));
      }
    }
    let pane = 1;
    const rsiKey = Object.keys(indicators).find((k) => k.startsWith("rsi"));
    if (rsiKey) {
      const s = chart.addSeries(LineSeries, { color: "#b48cff", lineWidth: 1, priceLineVisible: false, title: "RSI" }, pane);
      s.setData(line(indicators[rsiKey] as (number | null)[], times));
      s.createPriceLine({ price: 70, color: "#6d2a37", lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: "" });
      s.createPriceLine({ price: 30, color: "#1d5b45", lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: "" });
      pane++;
    }
    const macd = indicators.macd as Record<string, (number | null)[]> | undefined;
    if (macd) {
      const h = chart.addSeries(HistogramSeries, { priceLineVisible: false, lastValueVisible: false }, pane);
      h.setData(macd.histogram.map((v, i) => (v == null ? { time: times[i] } : { time: times[i], value: v, color: v >= 0 ? "#1d7a5a" : "#8a3343" })));
      chart.addSeries(LineSeries, { color: "#39c2d7", lineWidth: 1, priceLineVisible: false, title: "MACD" }, pane).setData(line(macd.macd, times));
      chart.addSeries(LineSeries, { color: "#f2b84b", lineWidth: 1, priceLineVisible: false, title: "Signal" }, pane).setData(line(macd.signal, times));
      pane++;
    }
    const panes = chart.panes();
    if (panes.length > 1) {
      panes[0].setStretchFactor(3);
      for (let i = 1; i < panes.length; i++) panes[i].setStretchFactor(1);
    }
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [bars, indicators, intraday, height]);
  return <div ref={ref} className="chart-box" style={{ height }} />;
}

export type Curve = { name: string; points: [string, number][]; color?: string; dashed?: boolean };
const CURVE_COLORS = ["#39c2d7", "#f2b84b", "#2fcf8a", "#b48cff", "#8a9bb0", "#ff8fb1", "#6aa6ff", "#c9d36a"];

/** Several value series (e.g. portfolios rebased to 100) on one time axis. */
export function LinesChart({ curves, height = 320 }: { curves: Curve[]; height?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, { ...BASE, height, timeScale: { ...BASE.timeScale, timeVisible: false } });
    curves.forEach((c, i) => {
      if (!c.points.length) return;
      const s = chart.addSeries(LineSeries, { color: c.color ?? CURVE_COLORS[i % CURVE_COLORS.length], lineWidth: 2,
                                              lineStyle: c.dashed ? 2 : 0, title: c.name, priceLineVisible: false });
      s.setData(c.points.map(([t, v]) => ({ time: t.slice(0, 10) as Time, value: v })));
    });
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [curves, height]);
  return <div ref={ref} className="chart-box" style={{ height }} />;
}

/** Horizontal percentage bars (allocation, exposure). */
export function Bars({ data, max, unit = "%" }: { data: Record<string, number>; max?: number; unit?: string }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const top = max ?? Math.max(1, ...entries.map((e) => e[1]));
  if (!entries.length) return <div className="empty">No data</div>;
  return (
    <div className="stack" style={{ gap: 4 }}>
      {entries.map(([k, v]) => (
        <div key={k} className="cat-bar">
          <span className="small muted" style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{k}</span>
          <div className="bar-track"><div className="bar-fill" style={{ width: `${Math.min(100, (v / top) * 100)}%` }} /></div>
          <span className="mono small">{v.toFixed(1)}{unit}</span>
        </div>
      ))}
    </div>
  );
}

/** Colour cells by a value (e.g. daily % change), grouped by a label. */
export function Heatmap({ cells, scale = 3 }: { cells: { label: string; sub?: string; value: number | null; href?: string }[]; scale?: number }) {
  const color = (v: number | null) => {
    if (v == null) return "#1a2531";
    const t = Math.max(-1, Math.min(1, v / scale));
    return t >= 0 ? `rgba(47, 207, 138, ${0.15 + 0.7 * t})` : `rgba(242, 100, 122, ${0.15 + 0.7 * -t})`;
  };
  return (
    <div className="heat">
      {cells.map((c) => (
        <a key={c.label + (c.sub ?? "")} className="heat-cell" style={{ background: color(c.value) }} href={c.href}>
          <span className="s">{c.label}</span>
          <span className="v">{c.sub ? `${c.sub} · ` : ""}{c.value == null ? "n/a" : `${c.value > 0 ? "+" : ""}${c.value.toFixed(2)}%`}</span>
        </a>
      ))}
    </div>
  );
}
