/**
 * A linked time-series plot: published columns against the recording's time, with the phase
 * wash, the shared playhead and click-to-seek.
 *
 * Curves are built once per data set (the SVG paths are memoised); only the playhead layer
 * follows the clock. Every plot carries a value table for assistive technology, sampled every
 * half second from the same columns it draws.
 */

import { memo, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode, type RefObject } from "react";

import type { LaboratoryPhaseSpan } from "../api/laboratory-types";
import { phaseVariable } from "./palette";
import { at, extent, formatNumber, niceTicks } from "./series";
import { useLaboratoryStore } from "./store";

export interface PlotSeries {
  readonly key: string;
  readonly label: string;
  readonly values: Float64Array | undefined;
  /** A CSS colour, normally a `var(--codex-…)` pigment. */
  readonly color: string;
  readonly dashed?: boolean;
  readonly width?: number;
}

export interface PlotProps {
  readonly title: string;
  readonly unit: string;
  readonly t: Float64Array;
  readonly series: readonly PlotSeries[];
  readonly spans: readonly LaboratoryPhaseSpan[];
  readonly duration: number;
  readonly digits?: number;
  /** A published bound drawn as a dashed rule. */
  readonly bound?: { readonly value: number; readonly label: string };
  readonly domain?: readonly [number, number];
  readonly note?: string;
  /** Whether the plot follows the shared clock (comparison plots on other folios may too). */
  readonly linked?: boolean;
  /** A compact control set in the caption row (never floated over the legend or drawing). */
  readonly control?: ReactNode;
}

const MARGIN = { left: 40, right: 12, top: 12, bottom: 22 } as const;

export function useElementSize(ref: RefObject<HTMLElement | null>, fallback: { width: number; height: number }) {
  const [size, setSize] = useState(fallback);
  useEffect(() => {
    const element = ref.current;
    if (element === null || typeof ResizeObserver === "undefined") {
      return;
    }
    const observer = new ResizeObserver(([entry]) => {
      if (entry === undefined) {
        return;
      }
      // The drawing is exactly the box it was given: never wider or taller than its frame,
      // which is what kept curves from overflowing into a neighbouring plot.
      const width = Math.max(1, Math.round(entry.contentRect.width));
      const height = Math.max(1, Math.round(entry.contentRect.height));
      setSize((previous) => (previous.width === width && previous.height === height ? previous : { width, height }));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref]);
  return size;
}

export function Plot(props: PlotProps) {
  const { title, unit, t, series, spans, duration, digits = 1, bound, domain, note, linked = true, control } = props;
  const frameRef = useRef<HTMLDivElement>(null);
  const { width, height } = useElementSize(frameRef, { width: 420, height: 230 });
  const seek = useLaboratoryStore((state) => state.seek);
  const pause = useLaboratoryStore((state) => state.pause);

  const innerWidth = Math.max(1, width - MARGIN.left - MARGIN.right);
  const innerHeight = Math.max(1, height - MARGIN.top - MARGIN.bottom);
  const [yMin, yMax] = useMemo(() => {
    if (domain !== undefined) {
      return domain;
    }
    const values = series.flatMap((entry) => (entry.values === undefined ? [] : [entry.values]));
    const base = extent(values);
    if (bound !== undefined) {
      return [Math.min(base[0], bound.value), Math.max(base[1], bound.value)] as const;
    }
    return base;
  }, [series, domain, bound]);
  const x = (time: number) => MARGIN.left + (time / Math.max(duration, 1e-9)) * innerWidth;
  const y = (value: number) => MARGIN.top + (1 - (value - yMin) / Math.max(yMax - yMin, 1e-12)) * innerHeight;

  const paths = useMemo(
    () =>
      series.map((entry) => {
        const values = entry.values;
        if (values === undefined) {
          return "";
        }
        let d = "";
        let pen = false;
        const n = Math.min(values.length, t.length);
        for (let i = 0; i < n; i += 1) {
          const value = values[i] ?? Number.NaN;
          if (!Number.isFinite(value)) {
            pen = false;
            continue;
          }
          d += `${pen ? "L" : "M"}${x(at(t, i)).toFixed(1)},${y(value).toFixed(1)}`;
          pen = true;
        }
        return d;
      }),
    // x and y are functions of these inputs only.
    [series, t, width, height, yMin, yMax, duration],
  );

  // Fewer ticks where there is little room, and no time label under the axis unit: labels never
  // collide with each other or with "t s" at narrow widths.
  const yTicks = niceTicks(yMin, yMax, innerHeight < 90 ? 3 : 5);
  const unitClearance = 30;
  const tTicks = niceTicks(0, duration, innerWidth < 240 ? 3 : 6).filter(
    (tick) => Number.isInteger(tick) && x(tick) + 8 < width - MARGIN.right - unitClearance,
  );

  const seekFrom = (event: ReactPointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const scale = width / Math.max(1, rect.width);
    const px = (event.clientX - rect.left) * scale;
    const time = ((px - MARGIN.left) / innerWidth) * duration;
    seek(Math.min(Math.max(time, 0), duration));
  };

  const table = useMemo(() => {
    const rows: { time: number; values: string[] }[] = [];
    for (let i = 0; i < t.length; i += 50) {
      rows.push({
        time: at(t, i),
        values: series.map((entry) => formatNumber(at(entry.values, i), digits)),
      });
    }
    return rows;
  }, [series, t, digits]);

  return (
    <figure className="lab-plot" data-plot={title}>
      <figcaption>
        <span className="lab-plot-title">{title}</span>
        {control}
        <span className="lab-plot-unit">{unit}</span>
      </figcaption>
      <Legend series={series} digits={digits} linked={linked} />
      <div ref={frameRef} className="lab-plot-frame">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          width={width}
          height={height}
          role="img"
          aria-label={`${title}, ${unit}${note === undefined ? "" : `. ${note}`}. Click to seek.`}
          onPointerDown={(event) => {
            if (!linked) return;
            pause();
            event.currentTarget.setPointerCapture(event.pointerId);
            seekFrom(event);
          }}
          onPointerMove={(event) => {
            if (linked && event.currentTarget.hasPointerCapture(event.pointerId)) seekFrom(event);
          }}
        >
          <g className="lab-plot-wash">
            {spans.map((span) => (
              <rect
                key={`${span.phase}-${span.start_s}`}
                x={x(span.start_s)}
                y={MARGIN.top}
                width={Math.max(0, x(Math.min(duration, span.end_s + 0.01)) - x(span.start_s))}
                height={innerHeight}
                fill={phaseVariable(span.phase)}
                data-phase={span.phase}
              />
            ))}
          </g>
          <g className="lab-plot-strip">
            {spans.map((span) => (
              <rect
                key={`${span.phase}-${span.start_s}`}
                x={x(span.start_s)}
                y={MARGIN.top - 7}
                width={Math.max(0, x(Math.min(duration, span.end_s + 0.01)) - x(span.start_s))}
                height={3}
                fill={phaseVariable(span.phase)}
              />
            ))}
          </g>
          <g className="lab-plot-grid">
            {yTicks.map((tick) => (
              <g key={tick}>
                <line x1={MARGIN.left} x2={width - MARGIN.right} y1={y(tick)} y2={y(tick)} />
                <text x={MARGIN.left - 6} y={y(tick) + 3} textAnchor="end">
                  {Math.abs(tick) >= 100 ? tick.toFixed(0) : Number(tick.toPrecision(3))}
                </text>
              </g>
            ))}
            {tTicks.map((tick) => (
              <text key={tick} x={x(tick)} y={height - 8} textAnchor="middle">
                {tick}
              </text>
            ))}
            <text x={width - MARGIN.right} y={height - 8} textAnchor="end" className="lab-plot-axis-unit">
              t s
            </text>
            <line className="lab-plot-axis" x1={MARGIN.left} x2={MARGIN.left} y1={MARGIN.top} y2={MARGIN.top + innerHeight} />
            <line className="lab-plot-axis" x1={MARGIN.left} x2={width - MARGIN.right} y1={MARGIN.top + innerHeight} y2={MARGIN.top + innerHeight} />
          </g>
          {bound !== undefined && (
            <g className="lab-plot-bound">
              <line x1={MARGIN.left} x2={width - MARGIN.right} y1={y(bound.value)} y2={y(bound.value)} />
              <text x={width - MARGIN.right - 4} y={y(bound.value) - 4} textAnchor="end">
                {bound.label}
              </text>
            </g>
          )}
          <g className="lab-plot-curves">
            {series.map((entry, i) => (
              <path
                key={entry.key}
                d={paths[i]}
                stroke={entry.color}
                strokeWidth={entry.width ?? 1.6}
                strokeDasharray={entry.dashed === true ? "5 4" : undefined}
                fill="none"
                data-series={entry.key}
              />
            ))}
          </g>
          {linked && (
            <Playhead
              series={series}
              x={x}
              y={y}
              top={MARGIN.top - 8}
              bottom={MARGIN.top + innerHeight}
            />
          )}
        </svg>
      </div>
      <table className="sr-only">
        <caption>
          {title} ({unit}), every 0.5 s
        </caption>
        <thead>
          <tr>
            <th scope="col">t (s)</th>
            {series.map((entry) => (
              <th key={entry.key} scope="col">
                {entry.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.map((row) => (
            <tr key={row.time}>
              <th scope="row">{formatNumber(row.time, 2)}</th>
              {row.values.map((value, i) => (
                <td key={series[i]?.key ?? i}>{value}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {note !== undefined && <p className="lab-plot-note">{note}</p>}
    </figure>
  );
}

const Playhead = memo(function Playhead({
  series,
  x,
  y,
  top,
  bottom,
}: {
  series: readonly PlotSeries[];
  x: (time: number) => number;
  y: (value: number) => number;
  top: number;
  bottom: number;
}) {
  const frame = useLaboratoryStore((state) => state.frame);
  const time = useLaboratoryStore((state) => state.time);
  const px = x(time);
  return (
    <g className="lab-plot-playhead" data-frame={frame}>
      <line x1={px} x2={px} y1={top} y2={bottom} />
      <path d={`M${px - 4},${top - 4}L${px + 4},${top - 4}L${px},${top + 2}Z`} />
      {series.map((entry) => {
        const value = at(entry.values, frame);
        return Number.isFinite(value) ? (
          <circle key={entry.key} cx={px} cy={y(value)} r={2.6} fill={entry.color} />
        ) : null;
      })}
    </g>
  );
});

function Legend({ series, digits, linked }: { series: readonly PlotSeries[]; digits: number; linked: boolean }) {
  const frame = useLaboratoryStore((state) => (linked ? state.frame : -1));
  return (
    <ul className="lab-plot-legend">
      {series.map((entry) => (
        <li key={entry.key}>
          <svg width="18" height="6" aria-hidden="true">
            <line x1="0" x2="18" y1="3" y2="3" stroke={entry.color} strokeWidth="2" strokeDasharray={entry.dashed === true ? "4 3" : undefined} />
          </svg>
          <span title={entry.label}>{entry.label}</span>
          {linked && <output>{formatNumber(at(entry.values, frame), digits)}</output>}
        </li>
      ))}
    </ul>
  );
}
