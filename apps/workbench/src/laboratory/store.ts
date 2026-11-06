/**
 * The laboratory's presentation state: one clock, one selection, and the view around them.
 *
 * Presentation only, in memory only. Server reads (the dataset, recordings, frames) live in
 * the Query cache; this store holds which recording is shown, where playback is, what is
 * selected and how the stage is drawn — the facts every pane projects. Nothing is persisted.
 */

import { create } from "zustand";

import { advance, frameAt } from "./series";
import { sameRef, type RecordingRef } from "./sources";

export const FOLIOS = ["study", "laboratory", "atlas", "analysis", "record"] as const;
export type Folio = (typeof FOLIOS)[number];

export const VIEW_PRESETS = ["oblique", "sagittal", "frontal", "plan"] as const;
export type ViewPreset = (typeof VIEW_PRESETS)[number];

export const FIGURE_MODES = ["anatomical", "scientific"] as const;
export type FigureMode = (typeof FIGURE_MODES)[number];

export const SPEEDS = [0.25, 0.5, 1, 2] as const;
export type Speed = (typeof SPEEDS)[number];

export const LAYERS = [
  "athlete",
  "grf",
  "com",
  "support",
  "plantar",
  "barPath",
  "comPath",
  "jointAxes",
  "floor",
] as const;
export type Layer = (typeof LAYERS)[number];

export const DOCK_PLOTS = [
  "kinematics",
  "kinetics",
  "ground",
  "balance",
  "contact",
  "energy",
  "compare",
] as const;
export type DockPlot = (typeof DOCK_PLOTS)[number];

/** The dock shows at most this many plots side by side. */
export const MAX_PINNED = 3;

export interface Timebase {
  readonly period: number;
  readonly count: number;
  readonly duration: number;
}

/**
 * The configuration being prepared in Study & Runs: a study, a case name and a value for every
 * factor in its canonical unit. Presentation state until it is sent; the run service decides.
 */
export interface RunDraft {
  readonly studyId: string;
  readonly caseId: string;
  readonly values: Readonly<Record<string, number>>;
}

export interface LaboratoryState {
  readonly folio: Folio;
  /** The workspace whose studies and runs the laboratory is bound to (route search), if any. */
  readonly workspaceId: string | null;
  /** The recording on show: a packaged recording or a workspace run. */
  readonly recording: RecordingRef | null;
  /** The recording compared with it, when chosen. */
  readonly compare: RecordingRef | null;
  /** The run whose evidence the Evidence folio inspects, when it is not the one on show. */
  readonly evidenceRunId: string | null;
  /** A run taken off the stage because reading it back no longer verifies, and why. */
  readonly withdrawn: { readonly runId: string; readonly reason: string } | null;
  /** The configuration being prepared, and the run this session last started. */
  readonly draft: RunDraft | null;
  readonly activeRunId: string | null;
  readonly timebase: Timebase;
  readonly time: number;
  readonly frame: number;
  readonly playing: boolean;
  readonly speed: Speed;
  readonly loop: boolean;
  readonly selectedBody: string | null;
  readonly selectedJoint: string | null;
  readonly view: ViewPreset;
  /** Incremented when a preset is re-applied, so the stage re-frames even on the same preset. */
  readonly viewRevision: number;
  readonly follow: boolean;
  /** The athlete as the anatomical figure, or as the model's own segment geometry. */
  readonly figureMode: FigureMode;
  readonly layers: Readonly<Record<Layer, boolean>>;
  readonly pinned: readonly DockPlot[];
  readonly railCollapsed: boolean;
  /** What the stage could draw with, and its measured render rate (frames per second). */
  readonly renderer: {
    readonly kind: "webgl2" | "unavailable" | "failed" | "lost";
    readonly fps: number | null;
  } | null;

  setFolio(folio: Folio): void;
  setWorkspace(workspaceId: string | null): void;
  setRecording(recording: RecordingRef): void;
  setCompare(recording: RecordingRef | null): void;
  inspectEvidence(runId: string | null): void;
  setDraft(draft: RunDraft | null): void;
  withdraw(runId: string, reason: string, fallback: RecordingRef | null): void;
  dismissWithdrawn(): void;
  setActiveRun(runId: string | null): void;
  setTimebase(timebase: Timebase): void;
  seek(time: number): void;
  seekFrame(frame: number): void;
  stepFrame(delta: number): void;
  togglePlay(): void;
  pause(): void;
  tick(elapsed: number): void;
  setSpeed(speed: Speed): void;
  toggleLoop(): void;
  select(body: string | null, joint: string | null): void;
  setView(view: ViewPreset): void;
  toggleFollow(): void;
  setFigureMode(mode: FigureMode): void;
  toggleLayer(layer: Layer): void;
  togglePinned(plot: DockPlot): void;
  toggleRail(): void;
  setRenderer(renderer: LaboratoryState["renderer"]): void;
}

const DEFAULT_LAYERS: Record<Layer, boolean> = {
  athlete: true,
  grf: true,
  com: true,
  support: true,
  plantar: true,
  barPath: true,
  comPath: false,
  jointAxes: false,
  floor: true,
};

/** The state a laboratory opens in: the nominal repetition's bottom-of-descent framing. */
export const INITIAL_LABORATORY_STATE = {
  folio: "laboratory" as Folio,
  workspaceId: null,
  recording: null,
  compare: null,
  evidenceRunId: null,
  withdrawn: null,
  draft: null,
  activeRunId: null,
  timebase: { period: 0.01, count: 1, duration: 0 },
  time: 0,
  frame: 0,
  playing: false,
  speed: 1 as Speed,
  loop: true,
  selectedBody: "shank_l",
  selectedJoint: "knee_flexion_l",
  view: "oblique" as ViewPreset,
  viewRevision: 0,
  follow: false,
  figureMode: "anatomical" as FigureMode,
  layers: DEFAULT_LAYERS,
  pinned: ["kinematics", "kinetics", "ground"] as DockPlot[],
  railCollapsed: false,
  renderer: null,
} satisfies Partial<LaboratoryState>;

function positioned(time: number, timebase: Timebase): { time: number; frame: number } {
  const clamped = Math.min(Math.max(0, time), timebase.duration);
  return { time: clamped, frame: frameAt(clamped, timebase.period, timebase.count) };
}

export const useLaboratoryStore = create<LaboratoryState>((set, get) => ({
  ...INITIAL_LABORATORY_STATE,

  setFolio: (folio) => set({ folio }),

  setWorkspace: (workspaceId) => {
    if (get().workspaceId !== workspaceId) {
      // Runs belong to their workspace: a run of another workspace is never left on show.
      const { recording, compare } = get();
      set({
        workspaceId,
        recording: recording?.source === "run" ? null : recording,
        compare: compare?.source === "run" ? null : compare,
        evidenceRunId: null,
        draft: null,
        activeRunId: null,
        playing: false,
      });
    }
  },

  setRecording: (recording) => {
    if (!sameRef(get().recording, recording)) {
      set({ recording, playing: false });
    }
  },

  setCompare: (compare) => set({ compare }),

  inspectEvidence: (evidenceRunId) => set({ evidenceRunId }),

  setDraft: (draft) => set({ draft }),

  withdraw: (runId, reason, fallback) => {
    const { recording, compare } = get();
    set({
      withdrawn: { runId, reason },
      recording: recording?.source === "run" && recording.id === runId ? fallback : recording,
      compare: compare?.source === "run" && compare.id === runId ? null : compare,
      playing: false,
    });
  },

  dismissWithdrawn: () => set({ withdrawn: null }),

  setActiveRun: (activeRunId) => set({ activeRunId }),

  setTimebase: (timebase) => {
    const { time } = get();
    set({ timebase, ...positioned(time, timebase) });
  },

  seek: (time) => set(positioned(time, get().timebase)),

  seekFrame: (frame) => {
    const { timebase } = get();
    const index = Math.min(Math.max(0, Math.round(frame)), Math.max(0, timebase.count - 1));
    set({ frame: index, time: Math.min(index * timebase.period, timebase.duration) });
  },

  stepFrame: (delta) => {
    const { frame, seekFrame } = get();
    set({ playing: false });
    seekFrame(frame + delta);
  },

  togglePlay: () => {
    const { playing, time, timebase } = get();
    // Pressing play on the last frame starts again from the first.
    if (!playing && time >= timebase.duration - 1e-9) {
      set({ playing: true, ...positioned(0, timebase) });
      return;
    }
    set({ playing: !playing });
  },

  pause: () => set({ playing: false }),

  tick: (elapsed) => {
    const { time, playing, speed, loop, timebase } = get();
    const next = advance({ time, playing }, elapsed, speed, timebase.duration, loop);
    if (next.time !== time || next.playing !== playing) {
      set({ playing: next.playing, ...positioned(next.time, timebase) });
    }
  },

  setSpeed: (speed) => set({ speed }),

  toggleLoop: () => set((state) => ({ loop: !state.loop })),

  select: (selectedBody, selectedJoint) => set({ selectedBody, selectedJoint }),

  setView: (view) => set((state) => ({ view, viewRevision: state.viewRevision + 1 })),

  toggleFollow: () => set((state) => ({ follow: !state.follow })),

  setFigureMode: (figureMode) => set({ figureMode }),

  toggleLayer: (layer) =>
    set((state) => ({ layers: { ...state.layers, [layer]: !state.layers[layer] } })),

  togglePinned: (plot) =>
    set((state) => {
      if (state.pinned.includes(plot)) {
        return state.pinned.length === 1
          ? {}
          : { pinned: state.pinned.filter((entry) => entry !== plot) };
      }
      const pinned = [...state.pinned, plot];
      return { pinned: pinned.slice(Math.max(0, pinned.length - MAX_PINNED)) };
    }),

  toggleRail: () => set((state) => ({ railCollapsed: !state.railCollapsed })),

  setRenderer: (renderer) => set({ renderer }),
}));

/** Reset the store to its opening state (tests, and a new session generation). */
export function resetLaboratoryStore(): void {
  useLaboratoryStore.setState({ ...INITIAL_LABORATORY_STATE });
}
