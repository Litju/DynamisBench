import { useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent, type WheelEvent } from 'react';
import { fmt } from './kit';

export type Trace = { id: string; label: string; color: string; t: ArrayLike<number>; v: ArrayLike<number>; dash?: string; width?: number };

type Props = {
  title: string;
  unit: string;
  traces: Trace[];
  t: number;
  onTime: (t: number) => void;
  band?: { lo: ArrayLike<number>; hi: ArrayLike<number>; t: ArrayLike<number>; label: string };
  events?: { t: number; label: string }[];
  height?: number;
  window?: [number, number];
  onWindow?: (w: [number, number]) => void;
  symmetric?: boolean;
  footer?: string;
  selected?: boolean;
  testId?: string;
};

const PAD = { l: 58, r: 12, t: 8, b: 22 };

function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(600);
  useLayoutEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(200, e.contentRect.width)));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

function ticks(lo: number, hi: number, n = 5) {
  const span = hi - lo || 1;
  const step0 = span / n;
  const mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= step0) ?? mag * 10;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(Math.abs(v) < step * 1e-9 ? 0 : v);
  return out;
}

function sampleAt(t: ArrayLike<number>, v: ArrayLike<number>, x: number) {
  const n = t.length;
  if (n === 0) return NaN;
  const dt = (t[n - 1] - t[0]) / (n - 1);
  const i = Math.max(0, Math.min(n - 1, Math.round((x - t[0]) / dt)));
  return v[i];
}

export function Plot({ title, unit, traces, t, onTime, band, events = [], height = 150, window: win, onWindow, symmetric, footer, selected, testId }: Props) {
  const [ref, width] = useWidth();
  const [localWin, setLocalWin] = useState<[number, number]>([0, 2]);
  const w = win ?? localWin;
  const setW = (nw: [number, number]) => (onWindow ? onWindow(nw) : setLocalWin(nw));
  const iw = width - PAD.l - PAD.r, ih = height - PAD.t - PAD.b;
  const sx = (x: number) => PAD.l + ((x - w[0]) / (w[1] - w[0])) * iw;
  const ix = (px: number) => w[0] + ((px - PAD.l) / iw) * (w[1] - w[0]);

  const [lo, hi] = useMemo(() => {
    let a = Infinity, b = -Infinity;
    const scan = (tt: ArrayLike<number>, vv: ArrayLike<number>) => {
      for (let i = 0; i < tt.length; i++) if (tt[i] >= w[0] && tt[i] <= w[1]) { a = Math.min(a, vv[i]); b = Math.max(b, vv[i]); }
    };
    traces.forEach((tr) => scan(tr.t, tr.v));
    if (band) { scan(band.t, band.lo); scan(band.t, band.hi); }
    if (!Number.isFinite(a)) return [-1, 1];
    if (symmetric) { const m = Math.max(Math.abs(a), Math.abs(b)) || 1; return [-m * 1.08, m * 1.08]; }
    const pad = (b - a) * 0.08 || Math.abs(a) * 0.1 || 1;
    return [a - pad, b + pad];
  }, [traces, band, w[0], w[1], symmetric]); // eslint-disable-line react-hooks/exhaustive-deps
  const sy = (y: number) => PAD.t + (1 - (y - lo) / (hi - lo)) * ih;

  const path = (tt: ArrayLike<number>, vv: ArrayLike<number>) => {
    const n = tt.length;
    const visible = Math.max(1, Math.round(((w[1] - w[0]) / ((tt[n - 1] - tt[0]) || 1)) * n));
    const step = Math.max(1, Math.floor(visible / (iw * 1.5)));
    let dstr = '';
    let first = true;
    for (let i = 0; i < n; i += step) {
      if (tt[i] < w[0] - 0.01 || tt[i] > w[1] + 0.01) continue;
      dstr += `${first ? 'M' : 'L'}${sx(tt[i]).toFixed(1)},${sy(vv[i]).toFixed(1)}`;
      first = false;
    }
    return dstr;
  };

  const drag = useRef(false);
  const svgRef = useRef<SVGSVGElement>(null);
  const toT = (e: PointerEvent) => {
    const r = svgRef.current!.getBoundingClientRect();
    return Math.min(w[1], Math.max(w[0], ix(e.clientX - r.left)));
  };
  const onDown = (e: PointerEvent<SVGSVGElement>) => { drag.current = true; (e.target as Element).setPointerCapture?.(e.pointerId); onTime(toT(e)); };
  const onMove = (e: PointerEvent<SVGSVGElement>) => { if (drag.current) onTime(toT(e)); };
  const onUp = () => { drag.current = false; };
  const zoom = (factor: number, center: number) => {
    const span = Math.min(2, Math.max(0.02, (w[1] - w[0]) * factor));
    let a = center - (center - w[0]) * (span / (w[1] - w[0]));
    a = Math.max(0, Math.min(2 - span, a));
    setW([a, a + span]);
  };
  const svgWheel = useRef<(e: globalThis.WheelEvent) => void>(() => {});
  svgWheel.current = (e) => {
    e.preventDefault();
    const r = svgRef.current!.getBoundingClientRect();
    zoom(e.deltaY > 0 ? 1.25 : 0.8, ix(e.clientX - r.left));
  };
  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const fn = (e: globalThis.WheelEvent) => svgWheel.current(e);
    el.addEventListener('wheel', fn, { passive: false });
    return () => el.removeEventListener('wheel', fn);
  }, []);
  const onKey = (e: KeyboardEvent) => {
    const step = e.shiftKey ? 0.1 : 0.01;
    if (e.key === 'ArrowRight') { onTime(Math.min(2, t + step)); e.preventDefault(); }
    else if (e.key === 'ArrowLeft') { onTime(Math.max(0, t - step)); e.preventDefault(); }
    else if (e.key === '+' || e.key === '=') zoom(0.8, t);
    else if (e.key === '-') zoom(1.25, t);
    else if (e.key === '0') setW([0, 2]);
  };

  const yt = ticks(lo, hi, Math.max(3, Math.floor(ih / 32)));
  const xt = ticks(w[0], w[1], Math.max(4, Math.floor(iw / 80)));
  const cursorIn = t >= w[0] && t <= w[1];
  const readouts = traces.map((tr) => ({ tr, v: sampleAt(tr.t, tr.v, t) }));
  const zoomed = w[0] > 0 || w[1] < 2;

  return (
    <figure className={`m-0 flex min-w-0 flex-col rounded border ${selected ? 'border-sel bg-panel' : 'border-line bg-panel'}`} data-testid={testId}>
      <figcaption className="flex min-h-[26px] flex-wrap items-center gap-x-3 gap-y-0.5 px-2 pt-1 text-[12px]">
        <span className="font-semibold text-ink">{title}</span>
        <span className="text-ink-3">[{unit}]</span>
        <span className="ml-auto flex flex-wrap items-center gap-3 num">
          {readouts.map(({ tr, v }) => (
            <span key={tr.id} className="inline-flex items-center gap-1.5">
              <svg width="14" height="6" aria-hidden><line x1="0" y1="3" x2="14" y2="3" style={{ stroke: tr.color }} strokeWidth="2" strokeDasharray={tr.dash} /></svg>
              <span className="text-ink-3">{tr.label}</span>
              <span className="mono text-ink">{fmt(v, 6)}</span>
            </span>
          ))}
          {zoomed && <button className="btn btn-ghost h-[20px] px-1.5 text-[11px]" onClick={() => setW([0, 2])}>Reset zoom</button>}
        </span>
      </figcaption>
      <div ref={ref} className="min-w-0">
        <svg
          ref={svgRef}
          width={width}
          height={height}
          role="slider"
          tabIndex={0}
          aria-label={`${title} plot. Time cursor`}
          aria-valuemin={0}
          aria-valuemax={2}
          aria-valuenow={Number(t.toFixed(3))}
          aria-valuetext={`t = ${t.toFixed(3)} s; ${readouts.map(({ tr, v }) => `${tr.label} ${fmt(v, 6)} ${unit}`).join('; ')}`}
          onPointerDown={onDown}
          onPointerMove={onMove}
          onPointerUp={onUp}
          onDoubleClick={() => setW([0, 2])}
          onKeyDown={onKey}
          onWheelCapture={(e: WheelEvent) => e.stopPropagation()}
          style={{ touchAction: 'none', display: 'block', cursor: 'crosshair' }}
        >
          <defs>
            <clipPath id={`clip-${title.replace(/\W/g, '')}`}><rect x={PAD.l} y={PAD.t} width={iw} height={ih} /></clipPath>
          </defs>
          {yt.map((v) => (
            <g key={`y${v}`}>
              <line x1={PAD.l} x2={PAD.l + iw} y1={sy(v)} y2={sy(v)} style={{ stroke: v === 0 ? 'var(--color-grid-2)' : 'var(--color-grid)' }} />
              <text x={PAD.l - 6} y={sy(v) + 3.5} textAnchor="end" fontSize="10.5" style={{ fill: 'var(--color-ink-3)' }} className="num">{Math.abs(v) !== 0 && (Math.abs(v) < 1e-3 || Math.abs(v) >= 1e5) ? v.toExponential(1) : String(Number(v.toPrecision(4)))}</text>
            </g>
          ))}
          {xt.map((v) => (
            <g key={`x${v}`}>
              <line x1={sx(v)} x2={sx(v)} y1={PAD.t} y2={PAD.t + ih} style={{ stroke: 'var(--color-grid)' }} />
              <text x={sx(v)} y={height - 6} textAnchor="middle" fontSize="10.5" style={{ fill: 'var(--color-ink-3)' }} className="num">{String(Number(v.toFixed(3)))}</text>
            </g>
          ))}
          <g clipPath={`url(#clip-${title.replace(/\W/g, '')})`}>
            {band && (
              <path
                d={`${path(band.t, band.hi)}${(() => { let r = ''; for (let i = band.t.length - 1; i >= 0; i -= Math.max(1, Math.floor(band.t.length / iw))) r += `L${sx(band.t[i]).toFixed(1)},${sy(band.lo[i]).toFixed(1)}`; return r; })()}Z`}
                style={{ fill: 'var(--color-s1)' }} opacity={0.08}
              />
            )}
            {events.map((ev) => (
              <g key={ev.label}>
                <line x1={sx(ev.t)} x2={sx(ev.t)} y1={PAD.t} y2={PAD.t + ih} style={{ stroke: 'var(--color-warn)' }} strokeDasharray="3 3" />
                <text x={sx(ev.t) + 3} y={PAD.t + 10} fontSize="10" style={{ fill: 'var(--color-warn)' }}>{ev.label}</text>
              </g>
            ))}
            {traces.map((tr) => (
              <path key={tr.id} d={path(tr.t, tr.v)} fill="none" style={{ stroke: tr.color }} strokeWidth={tr.width ?? 1.5} strokeDasharray={tr.dash} vectorEffect="non-scaling-stroke" />
            ))}
          </g>
          <rect x={PAD.l} y={PAD.t} width={iw} height={ih} fill="none" style={{ stroke: 'var(--color-line-2)' }} />
          {cursorIn && (
            <g pointerEvents="none">
              <line x1={sx(t)} x2={sx(t)} y1={PAD.t} y2={PAD.t + ih} style={{ stroke: 'var(--color-cursor)' }} strokeWidth={1} />
              {readouts.map(({ tr, v }) => Number.isFinite(v) && <circle key={tr.id} cx={sx(t)} cy={sy(v)} r={3} style={{ fill: 'var(--color-panel)', stroke: tr.color }} strokeWidth={1.5} />)}
              <rect x={Math.min(sx(t) + 4, PAD.l + iw - 62)} y={PAD.t + ih - 16} width={58} height={14} rx={2} style={{ fill: 'var(--color-cursor)' }} />
              <text x={Math.min(sx(t) + 4, PAD.l + iw - 62) + 29} y={PAD.t + ih - 5.5} fontSize="10" style={{ fill: 'var(--color-panel)' }} textAnchor="middle" className="num">{t.toFixed(3)} s</text>
            </g>
          )}
        </svg>
      </div>
      {footer && <div className="px-2 pb-1 text-[11px] text-ink-3">{footer}</div>}
    </figure>
  );
}
