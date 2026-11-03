import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { REF, TERMINAL, type Lifecycle } from '../data/authority';
import { HUMAN_COORDS } from '../data/models';
import { MYO_COORDS, useMyoModel } from '../data/myosim';
import { idx, seriesById } from '../data/numerics';
import { ModelScene } from '../scene/Scene';
import { draftDiff, useWB, type DemoOutcome, type DockTab, type State } from '../state';
import { Empty, Icon, LifecycleChip, Src, Tag } from '../ui/kit';
import { Plot } from '../ui/Plot';

const COLORS = { theta: 'var(--color-s1)', omega: 'var(--color-s2)', energy: 'var(--color-s3)', bobx: 'var(--color-s4)', bobz: 'var(--color-s5)' };

/* ---------------- run / preflight toolbar ---------------- */

function useWide(min: number) {
  const [w, setW] = useState(() => window.innerWidth >= min);
  useEffect(() => {
    const on = () => setW(window.innerWidth >= min);
    window.addEventListener('resize', on);
    return () => window.removeEventListener('resize', on);
  }, [min]);
  return w;
}

const STEPS: { key: string; label: string; states: Lifecycle[] }[] = [
  { key: 'draft', label: 'Configure', states: ['draft'] },
  { key: 'pf', label: 'Preflight', states: ['preflight_ready', 'refused'] },
  { key: 'exec', label: 'Execute', states: ['starting', 'running', 'canceling'] },
  { key: 'term', label: 'Terminal', states: ['completed', 'failed', 'timed_out', 'canceled'] },
];

export function RunToolbar() {
  const { s, d } = useWB();
  const run = s.runs.find((r) => r.id === s.activeRun && r.study === s.study);
  const busy = run && !TERMINAL.includes(run.state);
  const diff = draftDiff(s.draft);
  const current: Lifecycle = run ? run.state : s.preflight ? (s.preflight.decision === 'ready' ? 'preflight_ready' : 'refused') : 'draft';
  const stepIndex = STEPS.findIndex((x) => x.states.includes(current));
  const wide = useWide(1500);
  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-line bg-panel px-2.5 py-1.5" role="toolbar" aria-label="Simulation execution">
      <button className="btn" onClick={() => d({ type: 'select', id: 'ctx.scenario' })} title="Open scenario settings in the inspector">
        <Icon name="ref" size={13} />
        <span className="mono">{s.study === 'pendulum-qual' ? REF.scenarioId : 'sc.loaded-cmj'}</span>
        {diff.length > 0 && <span className="tag tag-design">draft · {diff.length}</span>}
      </button>
      <button className="btn" onClick={() => d({ type: 'preflight' })} disabled={!!busy} data-testid="btn-preflight">Check preflight</button>
      <span className="mx-0.5 h-5 w-px bg-line" />
      <label className="flex items-center gap-1.5 text-[12px] text-ink-2">
        <span className="hidden xl:inline">Demo outcome</span>
        <select className="field" value={s.outcome} onChange={(e) => d({ type: 'outcome', outcome: e.target.value as DemoOutcome })} aria-label="Injected design-demo outcome" disabled={!!busy} data-testid="outcome">
          <option value="complete">Process completes</option>
          <option value="fail">Inject worker failure</option>
          <option value="timeout">Inject timeout</option>
        </select>
      </label>
      <button className="btn btn-primary" onClick={() => d({ type: 'start' })} disabled={!!busy} data-testid="btn-run">
        <Icon name="play" size={12} /> Execute <span className="opacity-80">(demo)</span>
      </button>
      <button className="btn" onClick={() => d({ type: 'cancel' })} disabled={!busy || run?.state === 'canceling'} data-testid="btn-cancel"><Icon name="stop" size={11} /> Cancel</button>
      <ol className="ml-auto flex items-center gap-0 text-[11.5px]" aria-label="Lifecycle progress">
        {STEPS.map((st, i) => (i !== stepIndex && !wide ? null : (
          <li key={st.key} className="flex items-center">
            <span className={`rounded px-1.5 py-0.5 ${i === stepIndex ? 'bg-accent-soft font-semibold text-accent-2' : i < stepIndex ? 'text-ink-2' : 'text-ink-3'}`} aria-current={i === stepIndex ? 'step' : undefined}>{st.label}</span>
            {i < STEPS.length - 1 && wide && <span className="px-0.5 text-ink-3">›</span>}
          </li>
        )))}
        <li className="ml-2" data-testid="lifecycle">{current === 'draft' ? <span className="text-ink-3">not checked</span> : <LifecycleChip state={current} />}</li>
      </ol>
    </div>
  );
}

/* ---------------- viewport with overlays ---------------- */

const OVERLAYS: { key: keyof State['overlays']; label: string; p: boolean | string; h: boolean | string }[] = [
  { key: 'geometry', label: 'Display geometry', p: true, h: true },
  { key: 'frames', label: 'Coordinate frames', p: true, h: true },
  { key: 'labels', label: 'Labels', p: true, h: true },
  { key: 'grid', label: 'Ground grid', p: true, h: true },
  { key: 'com', label: 'Centre of mass', p: true, h: 'No inertial data (asset not materialized)' },
  { key: 'trace', label: 'Bob trajectory trace', p: true, h: 'No trajectory source' },
  { key: 'gravity', label: 'Gravity load at COM', p: true, h: 'No mass data' },
];

export function Viewport({ compact, ghost }: { compact?: boolean; ghost?: string | null }) {
  const { s, d } = useWB();
  const isP = s.study === 'pendulum-qual';
  const [menu, setMenu] = useState(false);
  return (
    <div className="relative h-full min-h-0 w-full overflow-hidden bg-scene" data-testid="viewport-wrap">
      <ModelScene ghostSeries={ghost} compact={compact} />
      <div className={`pointer-events-none absolute left-2 top-2 flex max-w-[62%] flex-col items-start gap-1 ${compact ? 'hidden' : ''}`}>
        {isP ? (
          <span className="chip pointer-events-auto flex flex-wrap items-center gap-x-3 gap-y-0.5 px-2 py-1 text-[11.5px] text-ink-2" data-testid="data-sources">
            <span className="text-ink-3">Data</span>
            <span className="inline-flex items-center gap-1.5"><Src tag="AUTHORITY" label={false} />structure: reviewed MJCF</span>
            <span className="inline-flex items-center gap-1.5"><Src tag="DESIGN_ONLY" label={false} />rod/bob: display (model has no geoms)</span>
            <span className="inline-flex items-center gap-1.5" data-testid="trajectory-source"><Src tag="RECOMPUTED" label={false} />motion: reference ODE, not MuJoCo</span>
          </span>
        ) : (
          <span className="chip pointer-events-auto flex flex-wrap items-center gap-x-3 gap-y-0.5 border-design-line px-2 py-1 text-[11.5px] text-ink-2" data-testid="schematic-banner">
            <b className="text-ink">No human physics result.</b>
            {s.humanGeo === 'myosim'
              ? <span className="inline-flex items-center gap-1.5"><Src tag="EXTERNAL" label={false} />geometry &amp; kinematic tree: MyoSim reference model (Apache-2.0), not a DynamisBench realization</span>
              : <span className="inline-flex items-center gap-1.5"><Src tag="DESIGN_ONLY" label={false} />geometry: representative schematic</span>}
            <span className="inline-flex items-center gap-1.5" data-testid="trajectory-source"><Src tag="NOT_IMPLEMENTED" label={false} />motion: none (static pose)</span>
          </span>
        )}
      </div>
      <div className="pointer-events-none absolute right-2 top-2 flex max-w-[36%] flex-col items-end gap-1">
        {compact && <span className="chip px-2 py-0.5 text-[11px] text-ink-2"><Src tag={isP ? 'RECOMPUTED' : 'NOT_IMPLEMENTED'} label={isP ? 'reference ODE (prototype)' : 'no motion'} /></span>}
        {ghost && <span className="chip px-2 py-0.5 text-[11.5px]"><span className="mr-1 inline-block h-2 w-2 rounded-full bg-cand" />ghost: {seriesById(ghost).label}</span>}
        {!compact && (
          <div className="pointer-events-auto flex items-center gap-1">
            {!isP && (
              <div className="seg" role="group" aria-label="Human geometry">
                <button aria-pressed={s.humanGeo === 'myosim'} onClick={() => d({ type: 'humanGeo', geo: 'myosim' })} data-testid="geo-myosim" title="MyoSim reference geometry (external, Apache-2.0)">MyoSim</button>
                <button aria-pressed={s.humanGeo === 'schematic'} onClick={() => d({ type: 'humanGeo', geo: 'schematic' })} data-testid="geo-schematic" title="Design-only schematic">Schematic</button>
              </div>
            )}
            <div className="seg" role="group" aria-label="Laboratory layout">
              <button aria-pressed={!s.focus && s.layout === 'bottom'} onClick={() => d({ type: 'layout', layout: 'bottom' })} title="Signals below the scene" data-testid="layout-bottom">Bottom</button>
              <button aria-pressed={!s.focus && s.layout === 'side'} onClick={() => d({ type: 'layout', layout: 'side' })} title="Signals beside the scene" data-testid="layout-side">Side</button>
              <button aria-pressed={s.focus} onClick={() => d({ type: 'focus' })} title="Scene only (F); Esc restores" data-testid="layout-focus">Scene <span className="mono text-[10px] text-ink-3">F</span></button>
            </div>
          </div>
        )}
      </div>
      {!compact && (
        <div className="absolute bottom-2 left-2 flex items-center gap-1.5">
          <div className="seg" role="group" aria-label="View presets">
            {(['iso', 'sagittal', 'frontal', 'top'] as const).map((p) => (
              <button key={p} aria-pressed={s.view.preset === p} onClick={() => d({ type: 'view', preset: p })}>{p === 'sagittal' ? 'Sagittal (x–z)' : p === 'frontal' ? 'Frontal (y–z)' : p === 'top' ? 'Top' : 'Iso'}</button>
            ))}
          </div>
          <button className="btn h-[26px]" onClick={() => d({ type: 'view', preset: s.view.preset })} title="Reset camera to the current preset"><Icon name="reset" size={12} /> Reset view</button>
          <div className="relative">
            <button className="btn h-[26px]" aria-expanded={menu} aria-haspopup="true" onClick={() => setMenu((m) => !m)} data-testid="overlays-btn">Overlays <Icon name="chev-d" size={11} /></button>
            {menu && (
              <div className="absolute bottom-[30px] left-0 z-20 w-[290px] rounded-md border border-line bg-panel p-1.5 shadow-lg" role="group" aria-label="Scene overlays">
                {OVERLAYS.map((o) => {
                  const avail = isP ? o.p : o.h;
                  const ok = avail === true;
                  return (
                    <label key={o.key} className={`flex items-start gap-2 rounded px-1.5 py-1 ${ok ? 'hover:bg-sunk' : 'opacity-75'}`}>
                      <input type="checkbox" className="mt-0.5" checked={ok && s.overlays[o.key]} disabled={!ok} onChange={() => d({ type: 'overlay', key: o.key })} />
                      <span>
                        <span className="text-[12px]">{o.label}</span>
                        {!ok && <span className="block text-[11px] text-ink-3">Unavailable — {avail}</span>}
                      </span>
                    </label>
                  );
                })}
                <div className="mt-1 border-t border-line px-1.5 pt-1.5 text-[11px] text-ink-3">Forces, muscles, contacts and markers: not shown — no data source exists.</div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------------- transport ---------------- */

export function Transport() {
  const { s, d } = useWB();
  const isP = s.study === 'pendulum-qual';
  if (!isP) {
    return (
      <div className="flex items-center gap-3 border-t border-line bg-panel px-3 py-1.5 text-[12px] text-ink-3" data-testid="transport-disabled">
        <button className="btn btn-icon" disabled aria-label="Play (unavailable)"><Icon name="play" size={12} /></button>
        <input type="range" disabled className="w-64" aria-label="Time (unavailable)" />
        <span>Playback unavailable — this model has no trajectory source. The schematic does not move as though simulated.</span>
      </div>
    );
  }
  const i = idx(s.t);
  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-line bg-panel px-2.5 py-1.5" role="group" aria-label="Recorded playback">
      <button className="btn btn-icon" onClick={() => d({ type: 'time', t: 0 })} aria-label="Go to start"><Icon name="start" size={12} /></button>
      <button className="btn btn-icon" onClick={() => d({ type: 'time', t: s.t - 0.01 })} aria-label="Step back 10 ms"><Icon name="step-b" size={12} /></button>
      <button className="btn btn-icon btn-primary" onClick={() => d({ type: 'play' })} aria-label={s.playing ? 'Pause' : 'Play'} data-testid="btn-play"><Icon name={s.playing ? 'pause' : 'play'} size={12} /></button>
      <button className="btn btn-icon" onClick={() => d({ type: 'time', t: s.t + 0.01 })} aria-label="Step forward 10 ms"><Icon name="step-f" size={12} /></button>
      <button className="btn btn-icon" onClick={() => d({ type: 'time', t: 2 })} aria-label="Go to end"><Icon name="end" size={12} /></button>
      <div className="relative min-w-[120px] flex-1">
        <input type="range" min={0} max={2} step={0.001} value={s.t} onChange={(e) => d({ type: 'time', t: Number(e.target.value) })} className="w-full" aria-label="Playback time" aria-valuetext={`${s.t.toFixed(3)} seconds`} data-testid="time-slider" list="checkpoints" />
        <datalist id="checkpoints">{REF.checkpoints.map((c) => <option key={c} value={c} />)}</datalist>
      </div>
      <span className="mono whitespace-nowrap text-ink" data-testid="time-readout">t = {s.t.toFixed(3)} s <span className="text-ink-3">/ 2.000 · #{i}</span></span>
      <select className="field" value={s.speed} onChange={(e) => d({ type: 'speed', speed: Number(e.target.value) })} aria-label="Playback speed">
        {[0.1, 0.25, 0.5, 1].map((v) => <option key={v} value={v}>{v}×</option>)}
      </select>
      <button className="btn btn-icon" aria-pressed={s.loop} onClick={() => d({ type: 'loop' })} aria-label="Loop playback"><Icon name="loop" size={13} /></button>
      <span className="hidden text-[11px] text-ink-3 min-[1800px]:inline">Playback moves a cursor through recorded samples; it never advances a solver.</span>
    </div>
  );
}

/* ---------------- dock ---------------- */

function PhasePortrait({ height }: { height: number }) {
  const { s, d } = useWB();
  const ser = seriesById('series.rk4-1ms');
  const ref = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(300);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(160, e.contentRect.width)));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  const H = height, P = 34;
  const tMax = 0.56, wMax = 1.75; // display bounds (rad, rad/s) covering the 30-degree orbit
  const sx = (v: number) => P + ((v + tMax) / (2 * tMax)) * (w - P - 10);
  const sy = (v: number) => 8 + (1 - (v + wMax) / (2 * wMax)) * (H - 30);
  const path = useMemo(() => {
    let p = '';
    for (let i = 0; i < ser.t.length; i += 8) p += `${i ? 'L' : 'M'}${sx(ser.theta[i]).toFixed(1)},${sy(ser.omega[i]).toFixed(1)}`;
    return p;
  }, [w, H]); // eslint-disable-line react-hooks/exhaustive-deps
  const i = idx(s.t);
  const pick = (cx: number, cy: number) => {
    let best = 0, bd = Infinity;
    for (let k = 0; k < ser.t.length; k += 2) { const dd = (sx(ser.theta[k]) - cx) ** 2 + (sy(ser.omega[k]) - cy) ** 2; if (dd < bd) { bd = dd; best = k; } }
    d({ type: 'time', t: ser.t[best] });
  };
  return (
    <figure className="m-0 flex min-w-0 flex-col rounded border border-line bg-panel" data-testid="plot-phase">
      <figcaption className="flex min-h-[26px] items-center gap-2 px-2 pt-1 text-[12px]">
        <span className="font-semibold text-ink">Phase portrait θ–ω</span><span className="text-ink-3">[rad, rad·s⁻¹]</span>
        <span className="mono ml-auto text-ink">({ser.theta[i].toFixed(4)}, {ser.omega[i].toFixed(4)})</span>
      </figcaption>
      <div ref={ref} className="min-w-0">
        <svg width={w} height={H} role="img" aria-label={`Phase portrait. At t = ${s.t.toFixed(3)} s, θ = ${ser.theta[i].toFixed(4)} rad, ω = ${ser.omega[i].toFixed(4)} rad/s. Click the orbit to move the time cursor.`}
          onClick={(e) => { const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect(); pick(e.clientX - r.left, e.clientY - r.top); }} style={{ cursor: 'crosshair', display: 'block' }}>
          <line x1={sx(0)} x2={sx(0)} y1={8} y2={H - 22} style={{ stroke: 'var(--color-grid-2)' }} />
          <line x1={P} x2={w - 10} y1={sy(0)} y2={sy(0)} style={{ stroke: 'var(--color-grid-2)' }} />
          {[-0.5, 0.5].map((v) => <text key={v} x={sx(v)} y={H - 8} fontSize="10.5" textAnchor="middle" style={{ fill: 'var(--color-ink-3)' }}>{v}</text>)}
          {[-1.5, 1.5].map((v) => <text key={v} x={P - 5} y={sy(v) + 3.5} fontSize="10.5" textAnchor="end" style={{ fill: 'var(--color-ink-3)' }}>{v}</text>)}
          <path d={path} fill="none" style={{ stroke: 'var(--color-s1)' }} strokeWidth={1.4} />
          <circle cx={sx(ser.theta[i])} cy={sy(ser.omega[i])} r={4} style={{ fill: 'var(--color-panel)', stroke: 'var(--color-cursor)' }} strokeWidth={1.6} />
          <rect x={P} y={8} width={w - P - 10} height={H - 30} fill="none" style={{ stroke: 'var(--color-line-2)' }} />
        </svg>
      </div>
    </figure>
  );
}

export function SignalStack({ height = 118, highlight, columns = 2 }: { height?: number; highlight?: string[]; columns?: 1 | 2 }) {
  const { s, d } = useWB();
  const [win, setWin] = useState<[number, number]>([0, 2]);
  const ser = seriesById('series.rk4-1ms');
  const sel = highlight ?? [];
  const events = REF.checkpoints.slice(1, -1).map((c) => ({ t: c, label: `ckpt ${c}` }));
  const bob = sel.includes('bobx') || sel.includes('bobz');
  const bx = useRef<Float64Array | null>(null), bz = useRef<Float64Array | null>(null), de = useRef<Float64Array | null>(null);
  if (!bx.current) { bx.current = ser.theta.map((v) => -Math.sin(v)); bz.current = ser.theta.map((v) => -Math.cos(v)); de.current = ser.energy.map((v) => v - ser.energy[0]); }
  const onTime = (t: number) => d({ type: 'time', t });
  return (
    <div className="@container" data-testid="signal-stack">
      <div className={`grid gap-1.5 ${columns === 2 ? '@3xl:grid-cols-2' : ''}`}>
        <Plot testId="plot-theta" title="Hinge angle θ" unit="rad" traces={[{ id: 'th', label: 'θ', color: COLORS.theta, t: ser.t, v: ser.theta }]} t={s.t} onTime={onTime} window={win} onWindow={setWin} events={events} height={height} symmetric selected={sel.includes('theta')} />
        <Plot testId="plot-omega" title="Hinge angular velocity ω" unit="rad·s⁻¹" traces={[{ id: 'om', label: 'ω', color: COLORS.omega, t: ser.t, v: ser.omega }]} t={s.t} onTime={onTime} window={win} onWindow={setWin} events={events} height={height} symmetric selected={sel.includes('omega')} />
        {bob ? (
          <Plot testId="plot-bob" title="Site bob position (world)" unit="m" traces={[{ id: 'x', label: 'x', color: COLORS.bobx, t: ser.t, v: bx.current! }, { id: 'z', label: 'z', color: COLORS.bobz, t: ser.t, v: bz.current! }]} t={s.t} onTime={onTime} window={win} onWindow={setWin} height={height} selected />
        ) : (
          <Plot testId="plot-energy" title={`Energy drift E − E₀ (E₀ = ${ser.energy[0].toFixed(6)} J)`} unit="J" traces={[{ id: 'e', label: 'ΔE', color: COLORS.energy, t: ser.t, v: de.current! }]} t={s.t} onTime={onTime} window={win} onWindow={setWin} height={height} selected={sel.includes('energy')} />
        )}
        <PhasePortrait height={height} />
      </div>
      <p className="mb-0 mt-1.5 flex flex-wrap items-center gap-x-3 text-[11px] text-ink-3">
        <Src tag="RECOMPUTED" />
        <span>q.pendulum.* · frame hinge · relative_to_start · 1 kHz{bob ? ' · bob x = −L·sin θ, z = −L·cos θ' : ''}</span>
        <span>Linked: drag or ←/→ on a plot moves time · wheel zooms all · double-click resets · click the orbit</span>
      </p>
    </div>
  );
}

function HumanSignals({ side }: { side?: boolean }) {
  const items = [
    { q: 'q.knee.flexion_angle', label: 'Knee flexion angle (right)', unit: '1 (rad)', frame: 'world · relative_to_event (initial-contact)' },
    { q: 'q.foot.vertical_force', label: 'Vertical ground reaction force', unit: 'N (m·kg·s⁻²)', frame: 'world · +z up · 1 kHz' },
    { q: 'q.jump.height', label: 'Jump height (COM apex)', unit: 'm', frame: 'world · irregular' },
  ];
  return (
    <div className={`grid gap-1.5 ${side ? '' : 'md:grid-cols-3'}`} data-testid="human-signals">
      {items.map((it) => (
        <div key={it.q} className="flex min-h-[150px] flex-col rounded border border-line bg-panel">
          <div className="flex items-center gap-2 px-2 pt-1.5 text-[12px]"><span className="font-semibold">{it.label}</span><span className="text-ink-3">[{it.unit}]</span></div>
          <div className="mono px-2 text-[10.5px] text-ink-3">{it.q} · {it.frame}</div>
          <div className="relative m-2 flex flex-1 items-center justify-center rounded border border-dashed border-line-2 bg-panel-2 text-center text-[12px] text-ink-3">
            <span>No trajectory · <b className="font-semibold">not produced</b><br /><span className="text-[11px]">No qualified realization; no measured reference loaded.</span></span>
          </div>
        </div>
      ))}
    </div>
  );
}

function DataTable() {
  const { s, d } = useWB();
  const ser = seriesById('series.rk4-1ms');
  const cur = idx(s.t);
  const rows: number[] = [];
  for (let i = 0; i <= 2000; i += 10) rows.push(i);
  const ref = useRef<HTMLTableRowElement>(null);
  const nearest = Math.round(cur / 10) * 10;
  useEffect(() => { ref.current?.scrollIntoView({ block: 'nearest' }); }, [nearest]);
  const row = (i: number, exact?: boolean) => (
    <tr key={exact ? 'exact' : i} ref={!exact && i === nearest ? ref : undefined} className={(!exact && i === nearest) || exact ? 'is-current' : ''} onClick={() => d({ type: 'time', t: i / 1000 })} style={{ cursor: 'pointer' }}>
      <td className="mono">{exact ? '▶ ' : ''}{(i / 1000).toFixed(3)}</td>
      <td className="mono">{i}</td>
      <td className="mono">{ser.theta[i].toFixed(9)}</td>
      <td className="mono">{ser.omega[i].toFixed(9)}</td>
      <td className="mono">{ser.energy[i].toFixed(9)}</td>
      <td className="mono">{(-Math.sin(ser.theta[i])).toFixed(6)}</td>
      <td className="mono">{(-Math.cos(ser.theta[i])).toFixed(6)}</td>
    </tr>
  );
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 pb-1 text-[11.5px] text-ink-3"><Tag tag="RECOMPUTED" /> Table alternative to the plots · 10 ms rows · exact sample at cursor pinned · click a row to move the shared time cursor</div>
      <div className="scroll-thin min-h-0 flex-1 overflow-auto rounded border border-line" data-testid="data-table">
        <table className="data">
          <caption className="sr-only">Reference trajectory samples</caption>
          <thead><tr><th>t [s]</th><th>sample</th><th>θ [rad]</th><th>ω [rad·s⁻¹]</th><th>E [J]</th><th>bob x [m]</th><th>bob z [m]</th></tr></thead>
          <tbody>
            {row(cur, true)}
            {rows.map((i) => row(i))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function MyoCoordinates() {
  const { s, d } = useWB();
  const { model } = useMyoModel();
  if (!model) return <Empty title="Loading MyoSim reference model" tag="EXTERNAL">Reading xml/myolegs_chain.xml and xml/myotorso_chain.xml.</Empty>;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-2 pb-1 text-[11.5px] text-ink-3"><Src tag="EXTERNAL" label="axes and ranges: MyoSim" /><Src tag="DESIGN_ONLY" label="pose values: inspection only, not simulation states" /> Coupled knee/patella DOFs are held at 0. <button className="btn ml-auto h-[22px]" onClick={() => d({ type: 'resetMyoPose' })} data-testid="reset-pose">Reset pose</button></div>
      <div className="scroll-thin min-h-0 flex-1 overflow-auto rounded border border-line">
        <table className="data">
          <thead><tr><th>Coordinate</th><th>Body</th><th style={{ textAlign: 'left' }}>Pose</th><th>Value [rad]</th><th>Range [rad]</th><th>Range [deg]</th></tr></thead>
          <tbody>
            {MYO_COORDS.map((c) => {
              const j = model.joints.get(c.joint);
              if (!j) return null;
              const [lo, hi] = j.range ?? [-Math.PI, Math.PI];
              const v = s.myoPose[c.joint] ?? 0;
              return (
                <tr key={c.joint} className={s.selection === `mjoint.${c.joint}` ? 'is-current' : ''}>
                  <td><button className="btn btn-ghost mono h-[20px] px-1 text-[11.5px]" onClick={() => d({ type: 'select', id: `mjoint.${c.joint}` })}>{c.joint}</button></td>
                  <td className="text-ink-3">{j.body}</td>
                  <td style={{ textAlign: 'left' }}><input type="range" min={lo} max={hi} step="any" value={v} onChange={(e) => d({ type: 'myoPose', joint: c.joint, value: Number(e.target.value) })} aria-label={`${c.joint} pose value`} className="w-40" data-testid={`myopose-${c.joint}`} /></td>
                  <td className="mono">{v.toFixed(3)}</td>
                  <td className="mono text-ink-3">{lo.toFixed(3)} … {hi.toFixed(3)}</td>
                  <td className="mono text-ink-3">{(lo * 180 / Math.PI).toFixed(0)}° … {(hi * 180 / Math.PI).toFixed(0)}°</td>
                </tr>
              );
            })}
            {(['pelvis_tx', 'pelvis_tz', 'pelvis_tilt'] as const).map((id) => {
              const c = HUMAN_COORDS.find((x) => x.id === id)!;
              return (
                <tr key={id}>
                  <td className="mono">{c.label}</td>
                  <td className="text-ink-3">display root</td>
                  <td style={{ textAlign: 'left' }}><input type="range" min={c.min} max={c.max} step={0.005} value={s.pose[id]} onChange={(e) => d({ type: 'pose', id, value: Number(e.target.value) })} aria-label={`${c.label} pose value`} className="w-40" data-testid={`pose-${id}`} /></td>
                  <td className="mono">{s.pose[id].toFixed(3)}</td>
                  <td className="mono text-ink-3" colSpan={2}>display only (free joint not in the chain files)</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Coordinates() {
  const { s, d } = useWB();
  if (s.humanGeo === 'myosim') return <MyoCoordinates />;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 pb-1 text-[11.5px] text-ink-3"><Tag tag="DESIGN_ONLY" /> Coordinate pose editor (schematic inspection, after OpenSim Creator's coordinate panel). Values are not simulation states. <button className="btn ml-auto h-[22px]" onClick={() => d({ type: 'resetPose' })}>Reset pose</button></div>
      <div className="scroll-thin min-h-0 flex-1 overflow-auto rounded border border-line">
        <table className="data">
          <thead><tr><th>Coordinate</th><th>Joint</th><th style={{ textAlign: 'left' }}>Pose</th><th>Value</th><th>Unit</th><th>Range</th></tr></thead>
          <tbody>
            {HUMAN_COORDS.map((c) => (
              <tr key={c.id} className={s.selection === c.joint ? 'is-current' : ''}>
                <td className="mono">{c.label}</td>
                <td><button className="btn btn-ghost h-[20px] px-1 text-[11.5px]" onClick={() => d({ type: 'select', id: c.joint })}>{c.joint.slice(6)}</button></td>
                <td style={{ textAlign: 'left' }}><input type="range" min={c.min} max={c.max} step={0.01} value={s.pose[c.id]} onChange={(e) => d({ type: 'pose', id: c.id, value: Number(e.target.value) })} aria-label={`${c.label} pose value`} className="w-40" data-testid={`pose-${c.id}`} /></td>
                <td className="mono">{s.pose[c.id].toFixed(2)}</td>
                <td>{c.unit}</td>
                <td className="text-ink-3">display {c.min}…{c.max}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RunLog() {
  const { s, d } = useWB();
  const runs = s.runs.filter((r) => r.study === s.study);
  const run = runs.find((r) => r.id === s.activeRun) ?? runs[0];
  if (!run) return <Empty title="No executions yet" tag="DESIGN_ONLY">Use <b>Check preflight</b>, then <b>Execute (design demo)</b>. The prototype demonstrates the accepted lifecycle states (RunLifecycleState) and refusal codes; it never invokes a simulator, worker or API.</Empty>;
  return (
    <div className="flex h-full min-h-0 gap-2">
      <ul className="scroll-thin m-0 w-[200px] flex-none list-none overflow-auto rounded border border-line p-1" aria-label="Executions">
        {runs.map((r) => (
          <li key={r.id}>
            <button className={`flex w-full items-center gap-2 rounded px-1.5 py-1 text-left ${r.id === run.id ? 'bg-accent-soft' : 'hover:bg-sunk'}`} onClick={() => d({ type: 'activeRun', id: r.id })}>
              <span className="mono text-[11.5px]">{r.id}</span><span className="ml-auto"><LifecycleChip state={r.state} demo={false} /></span>
            </button>
          </li>
        ))}
      </ul>
      <div className="scroll-thin min-h-0 flex-1 overflow-auto rounded border border-line bg-panel p-2 font-mono text-[11.5px] leading-[1.6]" role="log" aria-live="polite" data-testid="run-log">
        {run.log.map((l, i) => (
          <div key={i} className={l.level === 'error' ? 'text-err' : l.level === 'warn' ? 'text-warn' : 'text-ink-2'}>
            <span className="text-ink-3">[{String(l.t).padStart(2, '0')}]</span> {l.level.toUpperCase().padEnd(5)} {l.text}
          </div>
        ))}
      </div>
    </div>
  );
}

function PreflightReport() {
  const { s, d } = useWB();
  const pf = s.preflight;
  if (!pf) return <Empty title="Preflight not checked for the current configuration" tag="NOT_ASSESSED" action={<button className="btn" onClick={() => d({ type: 'preflight' })}>Check preflight</button>}>Any configuration change invalidates the previous preflight result.</Empty>;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="mb-1 flex items-center gap-2 text-[12px]">
        <span className={`font-semibold ${pf.decision === 'ready' ? 'text-ok' : 'text-err'}`} data-testid="preflight-decision">Decision: {pf.decision === 'ready' ? 'READY (admission only — not a promise of success)' : 'REFUSED'}</span>
        <span className="ml-auto text-[11px] text-ink-3"><Tag tag="DESIGN_ONLY">Deterministic demo</Tag> grounded in execution/contracts.py RefusalCode; real preflight runs outside the app</span>
      </div>
      <div className="scroll-thin min-h-0 flex-1 overflow-auto rounded border border-line">
        <table className="data">
          <thead><tr><th>Check</th><th style={{ textAlign: 'left' }}>Outcome</th><th style={{ textAlign: 'left' }}>Code</th><th style={{ textAlign: 'left' }}>Message</th><th style={{ textAlign: 'left' }}>Basis</th></tr></thead>
          <tbody>
            {pf.checks.map((c) => (
              <tr key={c.label}>
                <td>{c.label}</td>
                <td style={{ textAlign: 'left' }} className={c.ok ? 'text-ok' : 'text-err'}>{c.ok ? 'admissible' : 'refused'}</td>
                <td style={{ textAlign: 'left' }} className="mono">{c.code ?? '—'}</td>
                <td style={{ textAlign: 'left', whiteSpace: 'normal' }}>{c.message}</td>
                <td style={{ textAlign: 'left', whiteSpace: 'normal' }} className="mono text-ink-3">{c.basis}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function Dock({ side }: { side?: boolean }) {
  const { s, d } = useWB();
  const isP = s.study === 'pendulum-qual';
  const [h, setH] = useState(() => Math.round(Math.min(340, Math.max(220, window.innerHeight * 0.33))));
  const [w, setW] = useState(() => Math.round(Math.min(560, Math.max(380, window.innerWidth * 0.27))));
  const drag = useRef<number | null>(null);
  const nRuns = s.runs.filter((r) => r.study === s.study).length;
  const tabs: { id: DockTab; label: string }[] = [
    { id: 'signals', label: 'Signals' },
    { id: 'table', label: isP ? 'Table' : 'Coordinates' },
    { id: 'log', label: `Log${nRuns ? ` (${nRuns})` : ''}` },
    { id: 'preflight', label: 'Preflight' },
  ];
  const sel = s.selection;
  const ent = sel ? (sel === 'joint.hinge' || sel === 'coord.hinge' || sel === 'q.angle' || sel === 'q.omega' ? ['theta', 'omega'] : sel === 'body.pendulum' ? ['energy'] : sel === 'site.bob' ? ['bobx', 'bobz'] : []) : [];
  let content: ReactNode;
  if (s.dock === 'signals') content = isP ? <SignalStack highlight={ent} columns={side ? 1 : 2} height={side ? 150 : Math.max(86, Math.floor((h - 132) / 2))} /> : <HumanSignals side={side} />;
  else if (s.dock === 'table') content = isP ? <DataTable /> : <Coordinates />;
  else if (s.dock === 'log') content = <RunLog />;
  else content = <PreflightReport />;
  const resize = side ? (
    <div className="resize-v" role="separator" aria-orientation="vertical" aria-label="Resize signal panel" aria-valuenow={w} tabIndex={0}
      onKeyDown={(e) => { if (e.key === 'ArrowLeft') setW((v) => Math.min(900, v + 20)); if (e.key === 'ArrowRight') setW((v) => Math.max(320, v - 20)); }}
      onPointerDown={(e) => { drag.current = e.clientX; (e.target as Element).setPointerCapture(e.pointerId); }}
      onPointerMove={(e) => { if (drag.current !== null) { setW((v) => Math.min(900, Math.max(320, v + (drag.current! - e.clientX)))); drag.current = e.clientX; } }}
      onPointerUp={() => { drag.current = null; }} />
  ) : (
    <div className="resize-h" role="separator" aria-orientation="horizontal" aria-label="Resize dock" aria-valuenow={h} tabIndex={0}
      onKeyDown={(e) => { if (e.key === 'ArrowUp') setH((v) => Math.min(640, v + 20)); if (e.key === 'ArrowDown') setH((v) => Math.max(160, v - 20)); }}
      onPointerDown={(e) => { drag.current = e.clientY; (e.target as Element).setPointerCapture(e.pointerId); }}
      onPointerMove={(e) => { if (drag.current !== null) { setH((v) => Math.min(640, Math.max(160, v + (drag.current! - e.clientY)))); drag.current = e.clientY; } }}
      onPointerUp={() => { drag.current = null; }} />
  );
  const open = side || s.dockOpen;
  return (
    <section className={`flex flex-none bg-panel-2 ${side ? 'flex-row border-l border-line' : 'flex-col border-t border-line'}`} style={side ? { width: w } : { height: open ? h : 37 }} aria-label="Analysis dock">
      {resize}
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div className="flex flex-none items-center border-b border-line bg-panel px-1" role="tablist" aria-label="Dock views">
          {tabs.map((t) => (
            <button key={t.id} role="tab" className="dock-tab" aria-selected={s.dock === t.id} onClick={() => d({ type: 'dock', tab: t.id })} data-testid={`dock-${t.id}`}>{t.label}</button>
          ))}
          {!side && <button className="btn btn-ghost btn-icon ml-auto" onClick={() => d({ type: 'dockToggle' })} aria-label={s.dockOpen ? 'Collapse dock' : 'Expand dock'} aria-expanded={s.dockOpen}><Icon name={s.dockOpen ? 'chev-d' : 'chev'} size={12} /></button>}
        </div>
        {open && <div className="scroll-thin min-h-0 flex-1 overflow-auto p-2" role="tabpanel">{content}</div>}
      </div>
    </section>
  );
}

export function LabMode() {
  const { s } = useWB();
  const side = s.layout === 'side' && !s.focus;
  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-md border border-line bg-panel" data-testid="lab" data-layout={s.focus ? 'focus' : s.layout}>
      <RunToolbar />
      <div className="flex min-h-0 flex-1">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div className="min-h-[240px] flex-1"><Viewport /></div>
          <Transport />
        </div>
        {side && <Dock side />}
      </div>
      {!side && !s.focus && <Dock />}
    </div>
  );
}
