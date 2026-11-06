/**
 * The biomechanics laboratory: five folios over the squat model's recordings and runs.
 *
 * I Study & Runs (study, configuration, preflight, execution, runs) · II Laboratory (stage,
 * timeline, plots, inspector) · III Model Atlas · IV Analysis · V Evidence.
 *
 * The page reads through the session's typed client, holds presentation state in the laboratory
 * store, and runs one playback clock. Two sources are shown and never confused: the packaged
 * laboratory dataset (diagnostic records, not sealed evidence) and — when the route is bound to
 * an open workspace — that workspace's runs, which the application's run service executed in
 * the isolated worker and sealed, and which are re-verified from evidence on every read. The
 * page itself executes nothing and computes no physics: it asks, and renders the answers.
 */

import { ChevronDown } from "lucide-react";
import { useEffect, useRef } from "react";
import { useSearch } from "@tanstack/react-router";

import { ApiClientError } from "../api/errors";
import type { ApiClient } from "../api/client";
import { useSession } from "../session/provider";
import type { WorkbenchSession } from "../session/types";
import { runtimeState } from "../shell/runtime-state";
import { useAcceptedLabData, useLabData, LabDataProvider, type LoadState } from "./data";
import { Dock } from "./dock";
import { AnalysisFolio } from "./folio-analysis";
import { AtlasFolio } from "./folio-atlas";
import { RecordFolio } from "./folio-record";
import { StudyFolio } from "./folio-study";
import { Inspector } from "./inspector";
import { Rail } from "./rail";
import { at, formatNumber, nearestBoundary, shortDigest } from "./series";
import { Stage } from "./stage/stage";
import { entryOptionLabel } from "./entry-label";
import { findEntry, refKey, sameRef, type RecordingRef } from "./sources";
import { FOLIOS, VIEW_PRESETS, resetLaboratoryStore, useLaboratoryStore, type Folio } from "./store";
import { Timeline } from "./timeline";

const FOLIO_LABELS: Record<Folio, { numeral: string; label: string }> = {
  study: { numeral: "I", label: "Study & Runs" },
  laboratory: { numeral: "II", label: "Laboratory" },
  atlas: { numeral: "III", label: "Model Atlas" },
  analysis: { numeral: "IV", label: "Analysis" },
  record: { numeral: "V", label: "Evidence" },
};

export function LaboratoryPage() {
  const { session, client } = useSession();
  if (client === null) {
    return <SessionNotReady session={session} />;
  }
  return <LaboratoryLoader client={client} />;
}

/**
 * The laboratory before there is a client to read with. Each session phase says what is true:
 * a desktop session that is still starting is waiting, not absent, and a failed or stopped one
 * is reported with the shell's own bounded account rather than as an ordinary browser.
 */
function SessionNotReady({ session }: { session: WorkbenchSession }) {
  const state = runtimeState(session, { status: "pending" });
  const waiting = session.phase === "starting" || session.phase === "ready";
  return (
    <section
      className="lab-absent"
      aria-labelledby="lab-absent-title"
      aria-busy={waiting}
      data-session-phase={session.phase}
    >
      <h1 id="lab-absent-title">Biomechanics laboratory</h1>
      {session.phase === "unavailable" ? (
        <p>
          A ready local API session is required to read the laboratory dataset. This is unavailable in an ordinary browser; open
          the DynamisBench desktop application.
        </p>
      ) : waiting ? (
        <p role="status">Waiting for the local API session to become ready before the laboratory is read…</p>
      ) : (
        <p role="alert">
          {state.label}: {state.detail} The laboratory is read once the session is ready again.
        </p>
      )}
    </section>
  );
}

function LaboratoryLoader({ client }: { client: ApiClient }) {
  const search = useSearch({ strict: false }) as { workspace?: string };
  const boundWorkspace = typeof search.workspace === "string" ? search.workspace : null;
  const workspaceId = useLaboratoryStore((state) => state.workspaceId);
  const setWorkspace = useLaboratoryStore((state) => state.setWorkspace);
  const ref = useLaboratoryStore((state) => state.recording);
  const setRecording = useLaboratoryStore((state) => state.setRecording);
  const { data, pending, index, entries } = useAcceptedLabData(client, ref, workspaceId);

  // A new session generation starts the laboratory from its opening state.
  const previousClient = useRef(client);
  useEffect(() => {
    if (previousClient.current !== client) {
      previousClient.current = client;
      resetLaboratoryStore();
    }
  }, [client]);

  // The route's workspace binds the laboratory to that workspace's studies and runs.
  useEffect(() => {
    setWorkspace(boundWorkspace);
  }, [boundWorkspace, setWorkspace]);

  // A run whose sealed evidence no longer verifies is taken off the stage at once, and the
  // laboratory says so: a held copy of it is never shown as a result.
  const withdraw = useLaboratoryStore((state) => state.withdraw);
  const compare = useLaboratoryStore((state) => state.compare);
  useEffect(() => {
    for (const candidate of [ref, compare]) {
      if (candidate?.source !== "run") continue;
      const entry = findEntry(entries, candidate);
      if (entry !== undefined && !entry.playable && entry.run?.progress?.active !== true) {
        const nominal = index?.recordings.find((recording) => recording.kind === "nominal");
        withdraw(
          candidate.id,
          `${entry.status}: ${entry.reasons[0] ?? "its sealed evidence does not verify"}`,
          nominal === undefined ? null : { source: "dataset", id: nominal.recording_id },
        );
      }
    }
  }, [entries, ref, compare, index, withdraw]);

  // Open on the nominal recording once the index is known.
  useEffect(() => {
    if (ref === null && index !== undefined) {
      const nominal = index.recordings.find((entry) => entry.kind === "nominal") ?? index.recordings[0];
      if (nominal !== undefined) {
        setRecording({ source: "dataset", id: nominal.recording_id });
      }
    }
  }, [index, ref, setRecording]);

  if (data === null) {
    return <LoadingPlate state={pending} />;
  }
  return (
    <LabDataProvider value={data}>
      <LaboratoryWorkbench pending={pending} />
    </LabDataProvider>
  );
}

function describeFailure(error: unknown): string {
  if (error instanceof ApiClientError) {
    return error.message;
  }
  if (error instanceof Error && error.name === "FrameTableError") {
    return error.message;
  }
  if (error instanceof Error && error.name === "ArrowDecodeError") {
    return error.message;
  }
  return "The laboratory dataset could not be read.";
}

function LoadingPlate({ state }: { state: LoadState }) {
  return (
    <section className="lab-loading" aria-live="polite" aria-busy={state.status === "loading"}>
      <Emblem size={54} />
      {state.status === "error" ? (
        <>
          <h1>The laboratory could not be read</h1>
          <p role="alert">
            Reading the {state.step} failed. {describeFailure(state.error)}
          </p>
        </>
      ) : (
        <>
          <h1>Reading the laboratory dataset</h1>
          <p>{state.status === "loading" ? `${state.step}…` : "ready"}</p>
        </>
      )}
    </section>
  );
}

export function Emblem({ size = 28 }: { size?: number }) {
  // Circle, square and plumb: the measured figure, in one mark.
  return (
    <svg className="lab-emblem" width={size} height={size} viewBox="0 0 40 40" aria-hidden="true">
      <circle cx="20" cy="20" r="17" />
      <rect x="9" y="9" width="22" height="22" />
      <line x1="20" y1="3" x2="20" y2="32" />
      <circle cx="20" cy="34" r="2.6" className="lab-emblem-bob" />
    </svg>
  );
}

function LaboratoryWorkbench({ pending }: { pending: LoadState }) {
  const data = useLabData();
  const folio = useLaboratoryStore((state) => state.folio);
  const setTimebase = useLaboratoryStore((state) => state.setTimebase);
  const { recording, frames } = data;

  // The clock's timebase is the accepted recording's own.
  useEffect(() => {
    const t = frames.kinematics.t;
    setTimebase({
      period: recording.sample_period_s,
      count: recording.frame_count,
      duration: at(t, t.length - 1),
    });
  }, [recording, frames.kinematics.t, setTimebase]);

  usePlaybackClock();
  useLaboratoryKeyboard();

  return (
    <div className="lab" data-folio={folio} data-source={data.ref.source}>
      <LabBar pending={pending} />
      <Ribbon />
      <div className="lab-notices">
        <Withdrawn />
      </div>
      <div className="lab-body">
        {folio === "study" && <StudyFolio />}
        {folio === "laboratory" && <LaboratoryFolio />}
        {folio === "atlas" && <AtlasFolio />}
        {folio === "analysis" && <AnalysisFolio />}
        {folio === "record" && <RecordFolio />}
      </div>
      <StatusBar />
    </div>
  );
}

function LaboratoryFolio() {
  return (
    <div className="lab-folio-laboratory">
      <Rail />
      <div className="lab-centre">
        <Stage />
        <Timeline />
        <Dock />
      </div>
      <Inspector />
    </div>
  );
}

function parseRefKey(key: string): RecordingRef | null {
  const separator = key.indexOf(":");
  const source = key.slice(0, separator);
  const id = key.slice(separator + 1);
  return (source === "dataset" || source === "run") && id !== "" ? { source, id } : null;
}

function LabBar({ pending }: { pending: LoadState }) {
  const { entries, ref } = useLabData();
  const folio = useLaboratoryStore((state) => state.folio);
  const setFolio = useLaboratoryStore((state) => state.setFolio);
  const requested = useLaboratoryStore((state) => state.recording);
  const setRecording = useLaboratoryStore((state) => state.setRecording);
  const loadingOther = requested !== null && !sameRef(requested, ref);
  const playable = entries.filter((entry) => entry.playable);
  const requestedLabel = findEntry(entries, requested)?.label ?? requested?.id ?? "";
  return (
    <div className="lab-bar">
      <div className="lab-bar-title">
        <h1>Biomechanics Laboratory</h1>
        <span>barbell back squat · MuJoCo</span>
      </div>
      <nav className="lab-folios" aria-label="Folios">
        {FOLIOS.map((entry) => (
          <button key={entry} type="button" aria-pressed={folio === entry} onClick={() => setFolio(entry)}>
            <span className="lab-numeral">{FOLIO_LABELS[entry].numeral}</span> {FOLIO_LABELS[entry].label}
          </button>
        ))}
      </nav>
      <label className="lab-recording-select">
        <span>Recording</span>
        <select
          aria-label="Recording"
          value={refKey(requested ?? ref)}
          onChange={(event) => {
            const next = parseRefKey(event.target.value);
            if (next !== null) setRecording(next);
          }}
        >
          {playable.some((entry) => entry.ref.source === "dataset") && (
            <optgroup label="Packaged dataset">
              {playable
                .filter((entry) => entry.ref.source === "dataset")
                .map((entry) => (
                  <option key={refKey(entry.ref)} value={refKey(entry.ref)}>
                    {entryOptionLabel(entry)}
                  </option>
                ))}
            </optgroup>
          )}
          {playable.some((entry) => entry.ref.source === "run") && (
            <optgroup label="Workspace runs (sealed, verified)">
              {playable
                .filter((entry) => entry.ref.source === "run")
                .map((entry) => (
                  <option key={refKey(entry.ref)} value={refKey(entry.ref)}>
                    {entryOptionLabel(entry)}
                  </option>
                ))}
            </optgroup>
          )}
        </select>
        <ChevronDown size={14} aria-hidden />
      </label>
      <span className="lab-pending" role="status">
        {loadingOther
          ? pending.status === "error"
            ? `could not read ${requestedLabel}: ${describeFailure(pending.error)}`
            : `reading ${requestedLabel}…`
          : ""}
      </span>
    </div>
  );
}

function Withdrawn() {
  const withdrawn = useLaboratoryStore((state) => state.withdrawn);
  const dismiss = useLaboratoryStore((state) => state.dismissWithdrawn);
  if (withdrawn === null) {
    return null;
  }
  return (
    <p className="lab-withdrawn" role="alert">
      <strong>Run {withdrawn.runId} was withdrawn from the stage</strong>
      <span className="lab-withdrawn-reason" title={withdrawn.reason}>
        — {withdrawn.reason.slice(0, 240)}
      </span>
      <button type="button" onClick={dismiss} aria-label="Dismiss the withdrawal notice">
        ×
      </button>
    </p>
  );
}

function Ribbon() {
  const { index, recording, model, ref } = useLabData();
  const run = ref.source === "run";
  return (
    <dl className="lab-ribbon" aria-label="Provenance" data-source={ref.source}>
      <div>
        <dt>{run ? "Run" : "Recording"}</dt>
        <dd>
          {recording.recording_id} · dt {formatNumber(recording.timestep_s * 1000, 2)} ms · {recording.frame_count} frames @{" "}
          {formatNumber(1 / recording.sample_period_s, 0)} Hz
        </dd>
      </div>
      <div>
        <dt>Trajectory</dt>
        <dd title={recording.trajectory_sha256}>{shortDigest(recording.trajectory_sha256)}</dd>
      </div>
      <div>
        <dt>Model</dt>
        <dd title={model.model_sha256}>{shortDigest(model.model_sha256)}</dd>
      </div>
      <div>
        <dt>Engine</dt>
        <dd>
          MuJoCo {index.generated_with.engine_version ?? "—"} · {model.integrator}
        </dd>
      </div>
      {run ? (
        <>
          <div>
            <dt>Source</dt>
            <dd>workspace run · RunSpec → preflight → isolated worker</dd>
          </div>
          <p className="lab-sealed">Sealed run — execution and derived bundles re-verified on read</p>
        </>
      ) : (
        <>
          <div>
            <dt>Dataset</dt>
            <dd title={index.manifest_sha256}>{index.dataset_id} · packaged, SHA-pinned</dd>
          </div>
          <p className="lab-not-sealed">Diagnostic record — not sealed DynamisBench evidence</p>
        </>
      )}
    </dl>
  );
}

function StatusBar() {
  const { recording, frames, index, ref } = useLabData();
  const frame = useLaboratoryStore((state) => state.frame);
  const count = useLaboratoryStore((state) => state.timebase.count);
  const selected = useLaboratoryStore((state) => state.selectedJoint ?? state.selectedBody);
  const folio = useLaboratoryStore((state) => state.folio);
  const time = at(frames.kinematics.t, frame);
  return (
    <footer className="lab-status" aria-label="Status">
      <span>
        frame {frame + 1} / {count} · t {formatNumber(time, 3)} s · record {formatNumber(1 / recording.sample_period_s, 0)} Hz
        {folio === "laboratory" ? <StageRate /> : null} · selection: {selected ?? "none"}
      </span>
      <span>
        {ref.source === "run"
          ? `workspace run · trajectory ${shortDigest(recording.trajectory_sha256)} · sealed, verified on read`
          : `${index.dataset_id} · trajectory ${shortDigest(recording.trajectory_sha256)} · not sealed evidence`}
      </span>
    </footer>
  );
}

function StageRate() {
  const renderer = useLaboratoryStore((state) => state.renderer);
  if (renderer === null) {
    return null;
  }
  return (
    <>
      {" "}
      ·{" "}
      {renderer.kind === "webgl2"
        ? `render ${renderer.fps === null ? "on demand" : `${renderer.fps} fps`} · WebGL2`
        : renderer.kind === "lost"
          ? "WebGL context lost"
          : renderer.kind === "failed"
            ? "stage renderer failed"
            : "stage unavailable (no WebGL2)"}
    </>
  );
}

/** Advance playback with the wall clock while playing; never synthesise a frame. */
function usePlaybackClock() {
  const playing = useLaboratoryStore((state) => state.playing);
  useEffect(() => {
    if (!playing) {
      return;
    }
    let previous = performance.now();
    let handle = requestAnimationFrame(function step(now) {
      useLaboratoryStore.getState().tick((now - previous) / 1000);
      previous = now;
      if (useLaboratoryStore.getState().playing) {
        handle = requestAnimationFrame(step);
      }
    });
    return () => cancelAnimationFrame(handle);
  }, [playing]);
}

function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  const tag = target.tagName;
  return tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" || target.isContentEditable;
}

/** The laboratory's shortcuts (DESIGN.md §4), active on the Laboratory folio. */
function useLaboratoryKeyboard() {
  const { recording } = useLabData();
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const store = useLaboratoryStore.getState();
      if (store.folio !== "laboratory" || event.ctrlKey || event.metaKey || event.altKey || isEditable(event.target)) {
        return;
      }
      const target = event.target instanceof HTMLElement ? event.target : null;
      const onControl = target !== null && (target.tagName === "BUTTON" || target.getAttribute("role") === "slider");
      switch (event.key) {
        case " ":
          if (onControl) return; // the focused control's own activation
          event.preventDefault();
          store.togglePlay();
          return;
        case "ArrowLeft":
        case "ArrowRight":
          if (target?.getAttribute("role") === "slider") return;
          event.preventDefault();
          store.stepFrame((event.key === "ArrowLeft" ? -1 : 1) * (event.shiftKey ? 10 : 1));
          return;
        case "Home":
        case "End":
          if (target?.getAttribute("role") === "slider") return;
          event.preventDefault();
          store.pause();
          store.seekFrame(event.key === "Home" ? 0 : store.timebase.count - 1);
          return;
        case "[":
        case "]":
          event.preventDefault();
          store.pause();
          store.seek(nearestBoundary(recording.phase_spans, store.time, event.key === "]" ? 1 : -1, store.timebase.duration));
          return;
        case "1":
        case "2":
        case "3":
        case "4": {
          const preset = VIEW_PRESETS[Number(event.key) - 1];
          if (preset !== undefined) {
            event.preventDefault();
            store.setView(preset);
          }
          return;
        }
        default:
          return;
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [recording.phase_spans]);
}
