/**
 * Where a recording on show comes from, and the one catalogue the panes list.
 *
 * Two sources, never confused:
 *
 * * **dataset** — the packaged, SHA-pinned laboratory recordings. Diagnostic records of model
 *   runs integrated offline; not sealed evidence.
 * * **run** — a run of a workspace study, executed through RunSpec, preflight and the isolated
 *   worker, sealed, normalized, verified and assessed. Its reads are re-verified from sealed
 *   evidence by the run service on every request; only a *verified* run is playable.
 *
 * A reference names the source explicitly: an identifier alone never decides where a read goes.
 */

import type { LaboratoryIndexResponse, LaboratoryRecordingEntry } from "../api/laboratory-types";
import type { RunEntry, RunListResponse, RunStatus } from "../api/run-types";

export type RecordingSource = "dataset" | "run";

export interface RecordingRef {
  readonly source: RecordingSource;
  readonly id: string;
}

export function sameRef(a: RecordingRef | null, b: RecordingRef | null): boolean {
  return a !== null && b !== null && a.source === b.source && a.id === b.id;
}

export function refKey(ref: RecordingRef): string {
  return `${ref.source}:${ref.id}`;
}

/** One entry of the unified catalogue: a packaged recording or a workspace run. */
export interface CatalogueEntry extends LaboratoryRecordingEntry {
  readonly ref: RecordingRef;
  /** `packaged` for the dataset; the read status (or progress state) of a run. */
  readonly status: "packaged" | RunStatus;
  readonly reasons: readonly string[];
  /** Whether the entry can be put on the stage: packaged, or a verified run. */
  readonly playable: boolean;
  readonly run: RunEntry | null;
}

const NO_DIGEST = "0".repeat(64);

/** Display label of a run: its case and identifier. */
export function runLabel(run: Pick<RunEntry, "case_id" | "run_id">): string {
  return `${run.case_id === "" ? "run" : run.case_id} · ${run.run_id}`;
}

function runEntry(run: RunEntry): CatalogueEntry {
  const timestep = run.timestep_s ?? run.configuration["f.squat.integration-timestep"] ?? Number.NaN;
  const passed = run.checks.pass + run.metrics.pass + run.verification.pass;
  const failed = run.checks.fail + run.metrics.fail + run.verification.fail;
  const notEvaluated = run.checks.not_evaluated + run.verification.not_evaluated;
  return {
    ref: { source: "run", id: run.run_id },
    recording_id: run.run_id,
    label: runLabel(run),
    kind: "run",
    description: "",
    timestep_s: timestep,
    duration_s: run.duration_s ?? Number.NaN,
    frame_count: run.frame_count ?? 0,
    trajectory_sha256: run.trajectory_sha256 ?? NO_DIGEST,
    completed: run.completed ?? false,
    checks_passed: passed,
    checks_failed: failed,
    checks_not_evaluated: notEvaluated,
    status: run.status,
    reasons: run.reasons,
    playable: run.status === "verified",
    run,
  };
}

/** The dataset's recordings followed by the workspace's runs (newest last). */
export function buildCatalogue(
  index: LaboratoryIndexResponse | undefined,
  runs: RunListResponse | undefined,
): CatalogueEntry[] {
  const entries: CatalogueEntry[] = [];
  for (const entry of index?.recordings ?? []) {
    entries.push({
      ...entry,
      ref: { source: "dataset", id: entry.recording_id },
      status: "packaged",
      reasons: [],
      playable: true,
      run: null,
    });
  }
  for (const run of runs?.runs ?? []) {
    entries.push(runEntry(run));
  }
  return entries;
}

export function findEntry(entries: readonly CatalogueEntry[], ref: RecordingRef | null): CatalogueEntry | undefined {
  return ref === null ? undefined : entries.find((entry) => sameRef(entry.ref, ref));
}
