import { createContext, useContext, useEffect, useReducer, type Dispatch, type ReactNode } from 'react';
import { CRITERIA, LCMJ20, REF, TERMINAL, type Lifecycle, type RefusalCode } from './data/authority';
import { HUMAN_COORDS, type ModelId } from './data/models';

export type Mode = 'study' | 'lab' | 'analysis' | 'evidence';
export type StudyId = 'pendulum-qual' | 'lcmj-sensitivity';
export type AnalysisTab = 'verification' | 'compare' | 'validation' | 'uq';
export type DockTab = 'signals' | 'table' | 'log' | 'preflight';
export type DemoOutcome = 'complete' | 'fail' | 'timeout';

export const STUDIES: Record<StudyId, { label: string; model: ModelId; benchmark: string; realization: string; scenario: string; sut: string; env: string; tag: 'AUTHORITY' | 'FIXTURE' }> = {
  'pendulum-qual': {
    label: 'Reference pendulum — adapter solution verification', model: 'pendulum', tag: 'AUTHORITY',
    benchmark: `${REF.benchmarkId} ${REF.benchmarkVersion}`, realization: `${REF.realizationId} ${REF.realizationVersion}`,
    scenario: `${REF.scenarioId} ${REF.scenarioVersion}`, sut: `${REF.sutId} ${REF.sutVersion}`, env: 'env.mujoco.reference.windows-x86-64 1.0.0',
  },
  'lcmj-sensitivity': {
    label: `${LCMJ20.study.label} (LCMJ20 fixture)`, model: 'lcmj-schematic', tag: 'FIXTURE',
    benchmark: 'db.lcmj20 1.0.0', realization: 'rl.mujoco.loaded-cmj 1.0.0', scenario: 'sc.loaded-cmj 1.0.0', sut: 'sut.baseline-0 1.0.0', env: 'env.mujoco.x86-64 1.0.0',
  },
};

export type Draft = { theta0Deg: number; duration: number; timestep: number; seed: number; integrator: string };
export const REFERENCE_DRAFT: Draft = { theta0Deg: 30, duration: REF.duration, timestep: REF.timestep, seed: REF.seed, integrator: REF.integrator };

export type Check = { label: string; ok: boolean; code?: RefusalCode; message: string; basis: string };
export type Preflight = { decision: 'ready' | 'refused'; checks: Check[]; draftChanged: string[]; at: number };

export type LogLine = { t: number; level: 'info' | 'warn' | 'error'; text: string };
export type DemoRun = { id: string; study: StudyId; state: Lifecycle; outcome: DemoOutcome; log: LogLine[]; progress: number; created: number; refusal?: RefusalCode };

export type State = {
  mode: Mode;
  study: StudyId;
  selection: string | null;
  hover: string | null;
  t: number;
  playing: boolean;
  speed: number;
  loop: boolean;
  draft: Draft;
  preflight: Preflight | null;
  runs: DemoRun[];
  activeRun: string | null;
  outcome: DemoOutcome;
  overlays: { frames: boolean; geometry: boolean; com: boolean; gravity: boolean; trace: boolean; grid: boolean; labels: boolean };
  view: { preset: 'iso' | 'sagittal' | 'frontal' | 'top'; nonce: number };
  dock: DockTab;
  dockOpen: boolean;
  analysis: AnalysisTab;
  pose: Record<string, number>;
  compare: { baseline: string; candidate: string; signal: 'theta' | 'omega' | 'energy'; absTol: number; relTol: number; window: [number, number] };
  uq: { factorLower: number; factorUpper: number; samples: number };
  evidenceFocus: string | null;
  theme: 'light' | 'dark';
  humanGeo: 'myosim' | 'schematic';
  myoPose: Record<string, number>;
  layout: 'bottom' | 'side';
  focus: boolean;
  navOpen: boolean;
  inspOpen: boolean;
};

function readPref(key: string, fallback: string) {
  try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; }
}
function writePref(key: string, value: string) {
  try { localStorage.setItem(key, value); } catch { /* per-viewer convenience only */ }
}

const defaultPose = () => Object.fromEntries(HUMAN_COORDS.map((c) => [c.id, c.def]));

export const initialState = (): State => {
  const q = new URLSearchParams(location.search);
  const study = (q.get('study') as StudyId) in STUDIES ? (q.get('study') as StudyId) : 'pendulum-qual';
  const mode = (['study', 'lab', 'analysis', 'evidence'] as Mode[]).includes(q.get('mode') as Mode) ? (q.get('mode') as Mode) : 'lab';
  const t = Number(q.get('t'));
  return {
    mode, study,
    selection: q.get('sel') ?? (study === 'pendulum-qual' ? 'joint.hinge' : 'mjoint.knee_angle_r'),
    hover: null,
    t: Number.isFinite(t) ? Math.min(2, Math.max(0, t)) : 0,
    playing: false, speed: 1, loop: true,
    draft: { ...REFERENCE_DRAFT }, preflight: null, runs: [], activeRun: null, outcome: 'complete',
    overlays: { frames: true, geometry: true, com: true, gravity: false, trace: true, grid: true, labels: true },
    view: { preset: 'iso', nonce: 0 },
    dock: 'signals', dockOpen: true,
    analysis: (['verification', 'compare', 'validation', 'uq'] as AnalysisTab[]).includes(q.get('tab') as AnalysisTab) ? (q.get('tab') as AnalysisTab) : 'verification',
    pose: defaultPose(),
    compare: { baseline: 'series.rk4-1ms', candidate: 'series.rk4-10ms', signal: 'theta', absTol: CRITERIA.angle_rad, relTol: 0, window: [0, 2] },
    uq: { factorLower: 0.8, factorUpper: 1.2, samples: 3 },
    evidenceFocus: null,
    theme: readPref('db.theme', 'light') as State['theme'],
    layout: (readPref('db.layout', window.innerWidth >= 1680 ? 'side' : 'bottom') as State['layout']),
    focus: false,
    humanGeo: 'myosim',
    myoPose: {},
    navOpen: true,
    inspOpen: true,
  };
};

export type Action =
  | { type: 'mode'; mode: Mode }
  | { type: 'study'; study: StudyId }
  | { type: 'select'; id: string | null }
  | { type: 'hover'; id: string | null }
  | { type: 'time'; t: number }
  | { type: 'play'; on?: boolean }
  | { type: 'advance'; dt: number }
  | { type: 'speed'; speed: number }
  | { type: 'loop' }
  | { type: 'draft'; patch: Partial<Draft> }
  | { type: 'resetDraft' }
  | { type: 'preflight' }
  | { type: 'start' }
  | { type: 'tick'; id: string }
  | { type: 'cancel' }
  | { type: 'outcome'; outcome: DemoOutcome }
  | { type: 'activeRun'; id: string | null }
  | { type: 'overlay'; key: keyof State['overlays'] }
  | { type: 'view'; preset: State['view']['preset'] }
  | { type: 'dock'; tab: DockTab }
  | { type: 'dockToggle' }
  | { type: 'analysis'; tab: AnalysisTab }
  | { type: 'pose'; id: string; value: number }
  | { type: 'resetPose' }
  | { type: 'compare'; patch: Partial<State['compare']> }
  | { type: 'uq'; patch: Partial<State['uq']> }
  | { type: 'evidenceFocus'; id: string | null }
  | { type: 'theme' }
  | { type: 'humanGeo'; geo: State['humanGeo'] }
  | { type: 'myoPose'; joint: string; value: number }
  | { type: 'resetMyoPose' }
  | { type: 'layout'; layout: State['layout'] }
  | { type: 'focus'; on?: boolean }
  | { type: 'panel'; which: 'nav' | 'insp' };

export function draftDiff(d: Draft) {
  const out: string[] = [];
  if (d.theta0Deg !== REFERENCE_DRAFT.theta0Deg) out.push(`initial angle ${d.theta0Deg}° ≠ 30°`);
  if (d.duration !== REFERENCE_DRAFT.duration) out.push(`duration ${d.duration} s ≠ 2 s`);
  if (d.timestep !== REFERENCE_DRAFT.timestep) out.push(`timestep ${d.timestep} s ≠ 0.001 s`);
  if (d.seed !== REFERENCE_DRAFT.seed) out.push(`seed ${d.seed} ≠ 0`);
  if (d.integrator !== REFERENCE_DRAFT.integrator) out.push(`integrator ${d.integrator} ≠ RK4`);
  return out;
}

/** Deterministic design-demo preflight, grounded in the documented RefusalCode vocabulary. */
export function computePreflight(study: StudyId, draft: Draft): Preflight {
  const checks: Check[] = [];
  const diff = draftDiff(draft);
  if (study === 'pendulum-qual') {
    checks.push({ label: 'Required capabilities', ok: true, message: 'forward_dynamics required; adapter advertises forward_dynamics', basis: 'preflight.py capability check' });
    checks.push({ label: 'Engine / version admission', ok: true, message: 'realization mujoco == 3.17.0; environment ENGINE requirement == 3.17.0', basis: 'execution/versions.py' });
    checks.push({ label: 'Model asset digest', ok: true, message: `models/reference/pendulum.xml sha256 ${REF.modelSha256.slice(0, 12)}… matches reviewed bytes`, basis: 'reference.py MODEL_SHA256' });
    checks.push({ label: 'Platform', ok: true, message: 'windows-x86-64 is a qualified reference platform', basis: 'reference.py platform_tag' });
    checks.push(
      diff.length === 0
        ? { label: 'Scenario authority (pinned digests)', ok: true, message: `draft equals sc.reference.pendulum 1.0.0 (semantic digest ${REF.digests.scenario.slice(0, 12)}…)`, basis: 'worker.py _verify_reference_authority' }
        : { label: 'Scenario authority (pinned digests)', ok: false, code: 'worker_failed', message: `draft changes ${diff.join('; ')}. A RunSpec compiled from it no longer matches the pinned scenario digest; the fixed adapter fails before the first physics step.`, basis: 'worker.py _verify_reference_authority → WorkerStatus.FAILED → supervisor worker_failed' },
    );
  } else {
    checks.push({ label: 'Required capabilities', ok: false, code: 'unsupported_capability', message: 'study requires forward_dynamics, state_snapshot; the qualified worker environment advertises forward_dynamics only', basis: 'preflight.py _capability_refusals' });
    checks.push({ label: 'Engine / version admission', ok: false, code: 'adapter_engine_mismatch', message: 'realization requires mujoco == 3.3.0; the only qualified adapter is compiled for 3.17.0', basis: 'execution/versions.py' });
    checks.push({ label: 'Model asset staging', ok: false, code: 'unstaged_asset', message: 'subject-model (models/realization/subject.xml) has a placeholder digest and is not staged', basis: 'preflight.py asset checks; RES-555 materialization pending' });
    checks.push({ label: 'Human model physics', ok: false, message: 'No qualified human musculoskeletal realization exists. The schematic is design-only.', basis: 'RES-575 scope; M5 RES-570' });
  }
  return { decision: checks.every((c) => c.ok) ? 'ready' : 'refused', checks, draftChanged: diff, at: Date.now() };
}

let runCounter = 0;

function reducer(s: State, a: Action): State {
  switch (a.type) {
    case 'mode': return { ...s, mode: a.mode, focus: a.mode === 'lab' ? s.focus : false };
    case 'study': {
      if (a.study === s.study) return s;
      return { ...s, study: a.study, selection: a.study === 'pendulum-qual' ? 'joint.hinge' : s.humanGeo === 'myosim' ? 'mjoint.knee_angle_r' : 'joint.knee_r', preflight: null, playing: false, draft: { ...REFERENCE_DRAFT }, activeRun: s.runs.find((r) => r.study === a.study)?.id ?? null };
    }
    case 'select': return { ...s, selection: a.id };
    case 'hover': return s.hover === a.id ? s : { ...s, hover: a.id };
    case 'time': return { ...s, t: Math.min(2, Math.max(0, Math.round(a.t * 1000) / 1000)) };
    case 'play': return { ...s, playing: a.on ?? !s.playing, t: (a.on ?? !s.playing) && s.t >= 2 ? 0 : s.t };
    case 'advance': {
      if (!s.playing) return s;
      const t = s.t + a.dt * s.speed;
      if (t >= 2) return s.loop ? { ...s, t: t - 2 } : { ...s, t: 2, playing: false };
      return { ...s, t };
    }
    case 'speed': return { ...s, speed: a.speed };
    case 'loop': return { ...s, loop: !s.loop };
    case 'draft': return { ...s, draft: { ...s.draft, ...a.patch }, preflight: null };
    case 'resetDraft': return { ...s, draft: { ...REFERENCE_DRAFT }, preflight: null };
    case 'preflight': return { ...s, preflight: computePreflight(s.study, s.draft), dock: 'preflight', dockOpen: true };
    case 'start': {
      const pf = s.preflight ?? computePreflight(s.study, s.draft);
      const id = `demo-${String(++runCounter).padStart(3, '0')}`;
      const now = Date.now();
      const base: DemoRun = { id, study: s.study, state: 'starting', outcome: s.outcome, progress: 0, created: now, log: [{ t: 0, level: 'info', text: 'DESIGN DEMO — no simulator, worker or API is invoked by this prototype.' }] };
      if (pf.decision === 'refused') {
        const codes = pf.checks.filter((c) => !c.ok && c.code).map((c) => c.code!);
        const run: DemoRun = { ...base, state: 'refused', refusal: codes[0], log: [...base.log, ...pf.checks.filter((c) => !c.ok).map((c) => ({ t: 0, level: 'error' as const, text: `refused${c.code ? ` [${c.code}]` : ''}: ${c.message}` })), { t: 0, level: 'info', text: 'Terminal state: refused. No process was started; nothing to cancel.' }] };
        return { ...s, preflight: pf, runs: [run, ...s.runs], activeRun: id, dock: 'log', dockOpen: true };
      }
      const run: DemoRun = { ...base, log: [...base.log, { t: 0, level: 'info', text: 'preflight_ready → starting: supervisor would launch the isolated worker environment' }] };
      return { ...s, preflight: pf, runs: [run, ...s.runs], activeRun: id, dock: 'log', dockOpen: true };
    }
    case 'tick': {
      const runs = s.runs.map((r) => {
        if (r.id !== a.id || TERMINAL.includes(r.state)) return r;
        const p = r.progress + 1;
        const log = [...r.log];
        let state: Lifecycle = r.state;
        if (r.state === 'canceling') {
          return { ...r, state: 'canceled' as Lifecycle, refusal: 'worker_canceled' as RefusalCode, log: [...log, { t: p, level: 'warn' as const, text: 'canceled [worker_canceled]: process tree terminated and verified empty (design demo)' }] };
        }
        if (p === 1) { state = 'running'; log.push({ t: p, level: 'info', text: 'starting → running: worker would verify reference authority, then step physics' }); }
        if (r.outcome === 'fail' && p === 4) {
          return { ...r, progress: p, state: 'failed' as Lifecycle, refusal: 'worker_failed' as RefusalCode, log: [...log, { t: p, level: 'error' as const, text: 'failed [worker_failed]: injected design-demo failure — worker reported FAILED; bounded diagnostics are the account of why' }] };
        }
        if (r.outcome === 'timeout' && p === 6) {
          return { ...r, progress: p, state: 'timed_out' as Lifecycle, refusal: 'worker_timeout' as RefusalCode, log: [...log, { t: p, level: 'error' as const, text: 'timed_out [worker_timeout]: injected design-demo timeout — supervisor deadline exceeded' }] };
        }
        if (r.outcome === 'complete' && p === 5) {
          return { ...r, progress: p, state: 'completed' as Lifecycle, log: [...log,
            { t: p, level: 'info' as const, text: 'completed: worker process reported COMPLETED (a process fact, not a scientific result)' },
            { t: p, level: 'warn' as const, text: 'native evidence: not produced (RES-555); canonical: not produced (M4); assessment: not assessed' }] };
        }
        return { ...r, progress: p, state, log };
      });
      return { ...s, runs };
    }
    case 'cancel': {
      const runs = s.runs.map((r) => (r.id === s.activeRun && (r.state === 'starting' || r.state === 'running') ? { ...r, state: 'canceling' as Lifecycle, log: [...r.log, { t: r.progress, level: 'warn' as const, text: 'cancel requested → canceling' }] } : r));
      return { ...s, runs };
    }
    case 'outcome': return { ...s, outcome: a.outcome };
    case 'activeRun': return { ...s, activeRun: a.id };
    case 'overlay': return { ...s, overlays: { ...s.overlays, [a.key]: !s.overlays[a.key] } };
    case 'view': return { ...s, view: { preset: a.preset, nonce: s.view.nonce + 1 } };
    case 'dock': return { ...s, dock: a.tab, dockOpen: true };
    case 'dockToggle': return { ...s, dockOpen: !s.dockOpen };
    case 'analysis': return { ...s, analysis: a.tab };
    case 'pose': return { ...s, pose: { ...s.pose, [a.id]: a.value } };
    case 'resetPose': return { ...s, pose: defaultPose() };
    case 'compare': return { ...s, compare: { ...s.compare, ...a.patch } };
    case 'uq': return { ...s, uq: { ...s.uq, ...a.patch } };
    case 'evidenceFocus': return { ...s, evidenceFocus: a.id };
    case 'humanGeo': return { ...s, humanGeo: a.geo, selection: a.geo === 'myosim' ? 'mjoint.knee_angle_r' : 'joint.knee_r' };
    case 'myoPose': return { ...s, myoPose: { ...s.myoPose, [a.joint]: a.value } };
    case 'resetMyoPose': return { ...s, myoPose: {}, pose: defaultPose() };
    case 'theme': return { ...s, theme: s.theme === 'light' ? 'dark' : 'light' };
    case 'layout': return { ...s, layout: a.layout, focus: false, dockOpen: true };
    case 'focus': return { ...s, focus: a.on ?? !s.focus };
    case 'panel': return a.which === 'nav' ? { ...s, navOpen: !s.navOpen } : { ...s, inspOpen: !s.inspOpen };
  }
}

const Ctx = createContext<{ s: State; d: Dispatch<Action> } | null>(null);

export function WorkbenchProvider({ children }: { children: ReactNode }) {
  const [s, d] = useReducer(reducer, undefined, initialState);

  // URL carries the scientific context (study, mode, selection, time) for deep links.
  useEffect(() => {
    const q = new URLSearchParams();
    q.set('study', s.study); q.set('mode', s.mode);
    if (s.selection) q.set('sel', s.selection);
    if (s.mode === 'analysis') q.set('tab', s.analysis);
    if (!s.playing) q.set('t', s.t.toFixed(3));
    const url = `/workbench?${q.toString()}`;
    if (location.pathname + location.search !== url) history.replaceState(null, '', url);
  }, [s.study, s.mode, s.selection, s.analysis, s.t, s.playing]);

  useEffect(() => { document.documentElement.dataset.theme = s.theme; writePref('db.theme', s.theme); }, [s.theme]);
  useEffect(() => { writePref('db.layout', s.layout); }, [s.layout]);

  // Playback clock: advances the recorded-time cursor only; never a solver step.
  useEffect(() => {
    if (!s.playing) return;
    let raf = 0;
    let last: number | null = null;
    const loop = (now: number) => {
      if (last !== null) d({ type: 'advance', dt: (now - last) / 1000 });
      last = now;
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [s.playing]);

  // Demo lifecycle timer.
  const active = s.runs.find((r) => r.id === s.activeRun);
  useEffect(() => {
    if (!active || TERMINAL.includes(active.state)) return;
    const h = setTimeout(() => d({ type: 'tick', id: active.id }), 650);
    return () => clearTimeout(h);
  }, [active?.id, active?.state, active?.progress]); // eslint-disable-line react-hooks/exhaustive-deps

  return <Ctx.Provider value={{ s, d }}>{children}</Ctx.Provider>;
}

export function useWB() {
  const c = useContext(Ctx);
  if (!c) throw new Error('WorkbenchProvider missing');
  return c;
}
