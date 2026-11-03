import { useEffect, useState } from 'react';
import { TERMINAL } from './data/authority';
import { AnalysisMode } from './modes/Analysis';
import { EvidenceMode } from './modes/Evidence';
import { LabMode, Viewport } from './modes/Lab';
import { StudyMode } from './modes/Study';
import { Inspector } from './shell/Inspector';
import { Navigator } from './shell/Navigator';
import { draftDiff, STUDIES, useWB, type Mode } from './state';
import { Icon, LifecycleChip, SourceLegend, Src } from './ui/kit';

const MODES: { id: Mode; label: string; key: string }[] = [
  { id: 'study', label: 'Study & Model', key: '1' },
  { id: 'lab', label: 'Simulation Laboratory', key: '2' },
  { id: 'analysis', label: 'Analysis & VVUQ', key: '3' },
  { id: 'evidence', label: 'Evidence & Provenance', key: '4' },
];

function Ctx({ label, value, onClick, testId }: { label: string; value: React.ReactNode; onClick?: () => void; testId?: string }) {
  const inner = (
    <>
      <span className="text-[10.5px] uppercase tracking-[.04em] text-ink-3">{label}</span>
      <span className="mono block w-full truncate text-[11.5px] text-ink">{value}</span>
    </>
  );
  return onClick ? (
    <button className="flex min-w-0 max-w-[240px] shrink flex-col items-start overflow-hidden rounded px-2 py-0.5 text-left hover:bg-sunk" onClick={onClick} data-testid={testId}>{inner}</button>
  ) : <div className="flex min-w-0 max-w-[240px] shrink flex-col overflow-hidden px-2 py-0.5" data-testid={testId}>{inner}</div>;
}

function TopBar() {
  const { s, d } = useWB();
  const st = STUDIES[s.study];
  const run = s.runs.find((r) => r.id === s.activeRun && r.study === s.study);
  const diff = s.study === 'pendulum-qual' ? draftDiff(s.draft) : [];
  return (
    <header className="flex h-[46px] flex-none items-center gap-1 border-b border-line bg-panel px-3" aria-label="Scientific context">
      <div className="mr-2 flex items-center gap-2">
        <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden><circle cx="10" cy="4" r="2" style={{ fill: 'var(--color-accent)' }} /><path d="M10 4 L14.5 15" style={{ stroke: 'var(--color-accent)' }} strokeWidth="1.6" /><circle cx="14.5" cy="15.5" r="2.6" fill="none" style={{ stroke: 'var(--color-accent)' }} strokeWidth="1.6" /><path d="M3 18h14" style={{ stroke: 'var(--color-ink-4)' }} strokeWidth="1.2" /></svg>
        <div className="leading-tight">
          <div className="text-[13px] font-semibold text-ink">DynamisBench</div>
          <div className="whitespace-nowrap text-[10.5px] text-ink-3">Workbench prototype</div>
        </div>
      </div>
      <span className="h-7 w-px bg-line" />
      <Ctx label="Study" value={s.study === 'pendulum-qual' ? 'db.reference.pendulum' : 'study.contact-stiffness-sensitivity'} onClick={() => d({ type: 'mode', mode: 'study' })} testId="ctx-study" />
      <Ctx label="Model / realization" value={st.realization} onClick={() => d({ type: 'select', id: 'ctx.realization' })} />
      <Ctx label="Scenario" value={<>{st.scenario}{diff.length > 0 && <span className="ml-1 text-warn">· draft</span>}</>} onClick={() => d({ type: 'select', id: 'ctx.scenario' })} />
      <Ctx label="Execution" value={run ? <span className="inline-flex items-center gap-1.5">{run.id} <LifecycleChip state={run.state} demo={false} /></span> : 'none'} onClick={run ? () => d({ type: 'select', id: `run:${run.id}` }) : undefined} testId="ctx-run" />
      <Ctx label="Capability" value={s.study === 'pendulum-qual' ? 'forward_dynamics · qualified' : 'not admissible'} />
      <button className="ml-auto flex items-center gap-1.5 rounded px-2 py-1 hover:bg-sunk" onClick={() => d({ type: 'mode', mode: 'evidence' })} data-testid="ctx-evidence">
        <span className="text-[10.5px] uppercase tracking-[.04em] text-ink-3">Evidence</span>
        <Src tag="NOT_IMPLEMENTED" label="native: not produced" />
        <Src tag="NOT_ASSESSED" label="assessment: none" />
      </button>
    </header>
  );
}

function ModeBar() {
  const { s, d } = useWB();
  const [help, setHelp] = useState(false);
  const [legend, setLegend] = useState(false);
  return (
    <div className="relative flex h-[35px] flex-none items-end border-b border-line bg-panel px-2" role="tablist" aria-label="Research modes">
      {MODES.map((m) => (
        <button key={m.id} role="tab" aria-selected={s.mode === m.id} className="mode-tab" onClick={() => d({ type: 'mode', mode: m.id })} data-testid={`mode-${m.id}`} title={`Alt+${m.key}`}>
          {m.label}
        </button>
      ))}
      <div className="mb-1.5 ml-auto flex items-center gap-2">
        <span className="rounded border border-design-line bg-design-soft px-2 py-0.5 text-[11px] text-design" data-testid="prototype-banner">Design prototype<span className="hidden xl:inline"> · no backend, worker or simulator is called · not for scientific use</span><span className="xl:hidden"> · no backend · not for scientific use</span></span>
        <button className="btn btn-ghost h-[24px] px-2 text-[12px]" aria-expanded={legend} onClick={() => { setLegend((v) => !v); setHelp(false); }} data-testid="legend-btn">Sources</button>
        <button className="btn btn-ghost h-[24px] px-2 text-[12px]" aria-expanded={help} onClick={() => { setHelp((h) => !h); setLegend(false); }}>Keys</button>
        <button className="btn btn-ghost h-[24px] px-2 text-[12px]" aria-pressed={s.theme === 'dark'} onClick={() => d({ type: 'theme' })} data-testid="theme-btn" title="Toggle light / dark theme">{s.theme === 'dark' ? 'Light' : 'Dark'}</button>
      </div>
      {legend && (
        <div className="absolute right-2 top-[34px] z-30 w-[560px] rounded-md border border-line bg-panel p-3 shadow-lg" role="dialog" aria-label="Data source legend">
          <div className="sec-h mb-2">Data source legend — every value carries one</div>
          <SourceLegend />
        </div>
      )}
      {help && (
        <div className="absolute right-2 top-[34px] z-30 w-[300px] rounded-md border border-line bg-panel p-3 text-[12px] shadow-lg" role="dialog" aria-label="Keyboard shortcuts">
          <table className="w-full"><tbody>
            {[['Alt+1…4', 'switch research mode'], ['Space', 'play / pause recorded playback'], ['← / →', 'step time 10 ms (Shift: 100 ms)'], ['Home / End', 'start / end of record'], ['Tree: ↑ ↓ ← → Enter', 'navigate and select'], ['Plot focused: + − 0', 'zoom in / out / reset'], ['F', 'scene-only Laboratory (Esc restores)'], ['[ / ]', 'collapse navigator / inspector'], ['Esc', 'close this panel']].map(([k, v]) => <tr key={k}><td className="mono py-0.5 pr-3 text-ink">{k}</td><td className="text-ink-2">{v}</td></tr>)}
          </tbody></table>
        </div>
      )}
    </div>
  );
}

function useShortcuts() {
  const { s, d } = useWB();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement;
      const typing = el.closest('input, select, textarea, [role="slider"], [role="tree"], [contenteditable]');
      if (e.altKey && ['1', '2', '3', '4'].includes(e.key)) { d({ type: 'mode', mode: MODES[Number(e.key) - 1].id }); e.preventDefault(); return; }
      if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === 'f' || e.key === 'F') { if (s.mode === 'lab') d({ type: 'focus' }); return; }
      if (e.key === 'Escape' && s.focus) { d({ type: 'focus', on: false }); return; }
      if (e.key === '[') { d({ type: 'panel', which: 'nav' }); return; }
      if (e.key === ']') { d({ type: 'panel', which: 'insp' }); return; }
      if (s.study !== 'pendulum-qual') return;
      if (e.key === ' ' && !el.closest('button')) { d({ type: 'play' }); e.preventDefault(); }
      else if (e.key === 'ArrowRight') { d({ type: 'time', t: s.t + (e.shiftKey ? 0.1 : 0.01) }); e.preventDefault(); }
      else if (e.key === 'ArrowLeft') { d({ type: 'time', t: s.t - (e.shiftKey ? 0.1 : 0.01) }); e.preventDefault(); }
      else if (e.key === 'Home') d({ type: 'time', t: 0 });
      else if (e.key === 'End') d({ type: 'time', t: 2 });
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [s.t, s.study, s.mode, s.focus, d]);
}

function ContextViewport() {
  const { s, d } = useWB();
  const ghost = s.mode === 'analysis' && s.analysis === 'compare' && s.study === 'pendulum-qual' && s.compare.candidate !== 'series.rk4-1ms' ? s.compare.candidate : null;
  return (
    <section className="panel flex flex-none flex-col overflow-hidden" style={{ height: 250 }} aria-label="Linked 3D context">
      <header className="panel-h">3D context <span className="ml-auto normal-case tracking-normal font-normal"><button className="btn btn-ghost h-[22px] px-1.5 text-[11.5px]" onClick={() => d({ type: 'mode', mode: 'lab' })}>Open in Lab <Icon name="chev" size={10} /></button></span></header>
      <div className="min-h-0 flex-1"><Viewport compact ghost={ghost} /></div>
      {s.study === 'pendulum-qual' && <div className="mono border-t border-line px-2 py-1 text-[11px] text-ink-2">t = {s.t.toFixed(3)} s · shared time cursor</div>}
    </section>
  );
}

function Rail({ side, label, onOpen }: { side: 'left' | 'right'; label: string; onOpen: () => void }) {
  return (
    <button className="panel flex w-[30px] flex-col items-center gap-2 py-2 text-ink-3 hover:text-ink" onClick={onOpen} aria-label={`Show ${label}`} title={`Show ${label}`} data-testid={`rail-${side}`}>
      <Icon name="chev" size={12} />
      <span className="text-[11px] font-semibold uppercase tracking-[.06em]" style={{ writingMode: 'vertical-rl', transform: side === 'left' ? 'rotate(180deg)' : undefined }}>{label}</span>
    </button>
  );
}

export function App() {
  const { s, d } = useWB();
  useShortcuts();
  const busy = s.runs.some((r) => !TERMINAL.includes(r.state));
  const focus = s.focus && s.mode === 'lab';
  const nav = s.navOpen && !focus, insp = s.inspOpen && !focus;
  const wide = typeof window !== 'undefined' && window.innerWidth >= 1536;
  const cols = `${nav ? (wide ? '280px' : '248px') : focus ? '0px' : '30px'} minmax(0,1fr) ${insp ? (wide ? '360px' : '316px') : focus ? '0px' : '30px'}`;
  return (
    <div className="flex h-full min-w-[960px] flex-col" data-mode={s.mode} data-busy={busy}>
      <TopBar />
      <ModeBar />
      <main className={`grid min-h-0 flex-1 p-2 ${focus ? 'gap-0' : 'gap-2'}`} style={{ gridTemplateColumns: cols }}>
        {nav ? <Navigator onCollapse={() => d({ type: 'panel', which: 'nav' })} /> : focus ? <span /> : <Rail side="left" label="Navigator" onOpen={() => d({ type: 'panel', which: 'nav' })} />}
        <div className="min-h-0 min-w-0" aria-live="off">
          {s.mode === 'lab' && <LabMode />}
          {s.mode === 'study' && <StudyMode />}
          {s.mode === 'analysis' && <AnalysisMode />}
          {s.mode === 'evidence' && <EvidenceMode />}
        </div>
        {insp ? (
          <div className="flex min-h-0 flex-col gap-2">
            {(s.mode === 'analysis' || s.mode === 'study') && <ContextViewport />}
            <div className="min-h-0 flex-1"><Inspector onCollapse={() => d({ type: 'panel', which: 'insp' })} /></div>
          </div>
        ) : focus ? <span /> : <Rail side="right" label="Inspector" onOpen={() => d({ type: 'panel', which: 'insp' })} />}
      </main>
    </div>
  );
}
