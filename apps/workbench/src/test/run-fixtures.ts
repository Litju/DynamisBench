/**
 * Run-route fixtures: the run service's real answers, and a scripted service over them.
 *
 * The JSON files are the in-process API's answers for a real squat workspace, written by
 * `python/tools/workbench_run_fixtures.py` (three presets executed in the isolated worker; the
 * third one's sealed canonical series damaged on disk so that reading it back is *rejected*).
 * They change only when that tool is run again. Frame streams are synthetic but exactly
 * catalogued, like the laboratory's.
 */

import catalogueFixture from "./fixtures/runs/catalogue.json";
import evidenceAblationFixture from "./fixtures/runs/evidence-ablation.json";
import evidenceFixture from "./fixtures/runs/evidence.json";
import evidenceRejectedFixture from "./fixtures/runs/evidence-rejected.json";
import modelFixture from "./fixtures/runs/model.json";
import preflightRefusedFixture from "./fixtures/runs/preflight-refused.json";
import preflightFixture from "./fixtures/runs/preflight.json";
import progressFixture from "./fixtures/runs/progress-completed.json";
import recordingRejectedFixture from "./fixtures/runs/recording-rejected.json";
import recordingFixture from "./fixtures/runs/recording.json";
import runsFixture from "./fixtures/runs/runs.json";
import startedFixture from "./fixtures/runs/started.json";
import { errorResponse } from "./fetch-stub";
import { jsonResponse } from "./http-fixtures";
import { binaryResponse, frameStream } from "./laboratory-fixtures";

export const RUN_CATALOGUE: unknown = catalogueFixture;
export const RUN_PREFLIGHT: unknown = preflightFixture;
export const RUN_PREFLIGHT_REFUSED = preflightRefusedFixture as {
  status: number;
  body: { error: { code: string; message: string } };
};
export const RUN_STARTED: unknown = startedFixture;
export const RUN_PROGRESS_COMPLETED: unknown = progressFixture;
export const RUN_LIST: unknown = runsFixture;
export const RUN_EVIDENCE: unknown = evidenceFixture;
export const RUN_EVIDENCE_ABLATION: unknown = evidenceAblationFixture;
export const RUN_EVIDENCE_REJECTED: unknown = evidenceRejectedFixture;
export const RUN_RECORDING: unknown = recordingFixture;
export const RUN_RECORDING_REJECTED = recordingRejectedFixture as {
  status: number;
  body: { error: { code: string; message: string } };
};
export const RUN_MODEL: unknown = modelFixture;

export const NOMINAL_RUN_ID = (startedFixture as { run_id: string }).run_id;
export const ABLATION_RUN_ID = (evidenceAblationFixture as { run_id: string }).run_id;
export const REJECTED_RUN_ID = (evidenceRejectedFixture as { run_id: string }).run_id;

/** A workspace identifier of the shape the API mints. */
export const WORKSPACE_ID = "w0rkspace-Token_1";

interface ScriptedState {
  /** Whether the nominal run has been started in this session. */
  started: boolean;
  /** Whether the nominal run's sealed evidence has been damaged (it then reads back rejected). */
  rejectNominal: boolean;
  /** Progress reads answered "running" before the run completes. */
  runningReads: number;
  cancelled: boolean;
  readonly requests: { method: string; path: string; body: unknown }[];
}

function clone<T>(value: T): T {
  return structuredClone(value);
}

/** A run entry as the list answers it once the run's sealed evidence no longer verifies. */
function rejectedEntry(run: { run_id: string }): unknown {
  const rejected = (runsFixture as { runs: { run_id: string; status: string }[] }).runs.find((entry) => entry.status === "rejected");
  return { ...clone(rejected), run_id: run.run_id, progress: null };
}

/**
 * A scripted run service: the fixtures for a workspace in which the nominal run has not been
 * executed yet. Preflight answers ready for the nominal configuration and refuses a timestep
 * that does not divide the sample period, as the real planner does; starting the nominal run
 * answers with its progress, which completes after `runningReads` reads; the list then names it.
 */
export function scriptedRunService(
  options: { runningReads?: number; alreadyRun?: boolean; refusePreflight?: boolean } = {},
) {
  const state: ScriptedState = {
    started: options.alreadyRun ?? false,
    rejectNominal: false,
    runningReads: options.runningReads ?? 2,
    cancelled: false,
    requests: [],
  };
  const list = runsFixture as { runs: { run_id: string }[] };
  const progressOf = (running: boolean) => {
    const base = clone(progressFixture) as Record<string, unknown>;
    if (running) {
      return { ...base, state: "running", active: true, lifecycle: ["starting", "running"], message: "", derived_outcome: null, execution_evidence_digest: null, derived_evidence_digest: null };
    }
    return base;
  };

  function answer(url: string, init: RequestInit): Response | null {
    const path = new URL(url).pathname;
    const prefix = `/api/v1/workspaces/${WORKSPACE_ID}`;
    if (!path.startsWith(prefix)) {
      return null;
    }
    const rest = path.slice(prefix.length);
    const method = init.method ?? "GET";
    const body = typeof init.body === "string" ? (JSON.parse(init.body) as unknown) : null;
    state.requests.push({ method, path: rest, body });

    if (rest === "/studies" && method === "GET") return jsonResponse(clone(catalogueFixture));
    if (rest === "/runs/preflight" && method === "POST") {
      const values = (body as { values: Record<string, number> }).values;
      if (options.refusePreflight === true || values["f.squat.integration-timestep"] === 0.0003) {
        return errorResponse(RUN_PREFLIGHT_REFUSED.status, "http_error", RUN_PREFLIGHT_REFUSED.body.error.message);
      }
      return jsonResponse({ ...clone(preflightFixture), configuration: values });
    }
    if (rest === "/runs" && method === "POST") {
      state.started = true;
      return jsonResponse(clone(startedFixture), 202);
    }
    if (rest === "/runs" && method === "GET") {
      const runs = clone(list.runs)
        .filter((run) => state.started || run.run_id !== NOMINAL_RUN_ID)
        .map((run) => (state.rejectNominal && run.run_id === NOMINAL_RUN_ID ? rejectedEntry(run) : run));
      return jsonResponse({ runs });
    }
    const run = /^\/runs\/([^/]+)\/(progress|cancel|evidence|recording|model|frames\/([^/]+))$/.exec(rest);
    if (run === null) {
      return null;
    }
    const runId = decodeURIComponent(run[1]!);
    const what = run[2]!;
    if (what === "progress") {
      if (runId !== NOMINAL_RUN_ID || !state.started) return errorResponse(404, "http_error", "This session did not start that run.");
      if (state.runningReads > 0) {
        state.runningReads -= 1;
        return jsonResponse(progressOf(true));
      }
      return jsonResponse(progressOf(false));
    }
    if (what === "cancel") {
      state.cancelled = true;
      return jsonResponse({ ...progressOf(true), state: "canceling" });
    }
    if (what === "evidence") {
      if (runId === NOMINAL_RUN_ID && state.rejectNominal) {
        return jsonResponse({ ...clone(evidenceRejectedFixture), run_id: NOMINAL_RUN_ID });
      }
      if (runId === NOMINAL_RUN_ID) return jsonResponse(clone(evidenceFixture));
      if (runId === ABLATION_RUN_ID) return jsonResponse(clone(evidenceAblationFixture));
      if (runId === REJECTED_RUN_ID) return jsonResponse(clone(evidenceRejectedFixture));
      return errorResponse(404, "http_error", "the workspace has no such run");
    }
    if (runId === REJECTED_RUN_ID || (runId === NOMINAL_RUN_ID && state.rejectNominal)) {
      return errorResponse(RUN_RECORDING_REJECTED.status, "http_error", RUN_RECORDING_REJECTED.body.error.message);
    }
    const recording = { ...clone(recordingFixture), recording_id: runId } as Record<string, unknown>;
    if (what === "recording") return jsonResponse(recording);
    if (what === "model") return jsonResponse(clone(modelFixture));
    if (run[3] !== undefined) return binaryResponse(frameStream(recording, decodeURIComponent(run[3])));
    return null;
  }

  return { state, answer };
}
