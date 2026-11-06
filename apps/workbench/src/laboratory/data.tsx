/**
 * The laboratory's server reads, and the one context every pane reads them from.
 *
 * Reads are TanStack queries over the typed client: the packaged dataset (index, model, one
 * recording and its three frame groups) and, when the laboratory is bound to a workspace, the
 * workspace's runs (list, and per verified run its recording, model and frame groups). The
 * context holds the *accepted* set for the recording on show, so a pane never renders one
 * recording's metadata beside another recording's frames or another run's model. While the
 * next recording loads, the previous set stays on show and the shell says so.
 */

import { useQueries, useQuery } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useMemo, useRef, type ReactNode } from "react";

import type { ApiClient } from "../api/client";
import type {
  LaboratoryFrameGroup,
  LaboratoryFrameTable,
  LaboratoryIndexResponse,
  LaboratoryModelResponse,
  LaboratoryRecordingResponse,
} from "../api/laboratory-types";
import {
  apiQueryKeys,
  laboratoryIndexOptions,
  laboratoryModelOptions,
  laboratoryRecordingOptions,
  runListOptions,
  runModelOptions,
  runRecordingOptions,
} from "../api/queries";
import type { RunListResponse } from "../api/run-types";
import { laboratoryFramesOptions, runFramesOptions } from "./frames";
import { buildCatalogue, sameRef, type CatalogueEntry, type RecordingRef } from "./sources";
import type { StageFrames } from "./stage/scene";
import { LIVE_WORKSPACE_RUN_API_AVAILABLE } from "./m1-capabilities";

export interface LabData {
  readonly client: ApiClient;
  /** The packaged dataset's index (its claim, engine and manifest identity). */
  readonly index: LaboratoryIndexResponse;
  /** Packaged recordings and, when bound to a workspace, its runs. */
  readonly entries: readonly CatalogueEntry[];
  readonly workspaceId: string | null;
  /** The recording on show and where it came from. */
  readonly ref: RecordingRef;
  /** The model the recording on show was integrated with (a run's own compiled model). */
  readonly model: LaboratoryModelResponse;
  readonly recording: LaboratoryRecordingResponse;
  readonly frames: StageFrames;
  /** Body weight of athlete and bar, N: published total mass × published gravity. */
  readonly weightN: number;
}

const LabDataContext = createContext<LabData | null>(null);

export function LabDataProvider({ value, children }: { value: LabData; children: ReactNode }) {
  return <LabDataContext.Provider value={value}>{children}</LabDataContext.Provider>;
}

export function useLabData(): LabData {
  const data = useContext(LabDataContext);
  if (data === null) {
    throw new Error("the laboratory data context is not mounted");
  }
  return data;
}

const GROUPS: readonly LaboratoryFrameGroup[] = ["pose", "kinematics", "kinetics"];

export type LoadState =
  | { readonly status: "loading"; readonly step: string }
  | { readonly status: "error"; readonly error: unknown; readonly step: string }
  | { readonly status: "ready" };

/** The dataset index, and the workspace's runs when the laboratory is bound to one. */
export function useCatalogue(client: ApiClient, workspaceId: string | null) {
  const index = useQuery(laboratoryIndexOptions(client));
  const runs = useQuery({
    ...(workspaceId === null || !LIVE_WORKSPACE_RUN_API_AVAILABLE
      ? unavailable<RunListResponse>(
          apiQueryKeys.runs(workspaceId ?? "none"),
          "workspace-run reads are unavailable in the M1 read-only integration",
        )
      : runListOptions(client, workspaceId)),
    enabled: workspaceId !== null && LIVE_WORKSPACE_RUN_API_AVAILABLE,
  });
  const runData: RunListResponse | undefined =
    workspaceId === null || !LIVE_WORKSPACE_RUN_API_AVAILABLE ? undefined : runs.data;
  const entries = useMemo(() => buildCatalogue(index.data, runData), [index.data, runData]);
  return { index, runs, entries };
}

function unavailable<T>(key: readonly unknown[], reason: string) {
  return {
    queryKey: key,
    queryFn: (): Promise<T> => Promise.reject(new Error(reason)),
    enabled: false,
  };
}

/** The model of one recording: the packaged model, or the run's own compiled model. */
export function useRecordingModel(client: ApiClient, ref: RecordingRef | null, workspaceId: string | null) {
  const options =
    ref === null
      ? unavailable<LaboratoryModelResponse>(apiQueryKeys.laboratoryModel(), "no recording is selected")
      : ref.source === "dataset"
        ? { ...laboratoryModelOptions(client), enabled: true }
        : workspaceId === null
          ? unavailable<LaboratoryModelResponse>(apiQueryKeys.runModel("none", ref.id), "no workspace is bound")
          : { ...runModelOptions(client, workspaceId, ref.id), enabled: true };
  return useQuery<LaboratoryModelResponse>(options);
}

/** One recording (packaged or run) and its frame groups. */
export function useRecordingSet(
  client: ApiClient,
  ref: RecordingRef | null,
  groups: readonly LaboratoryFrameGroup[] = GROUPS,
  workspaceId: string | null = null,
): {
  readonly recording: LaboratoryRecordingResponse | undefined;
  readonly tables: Partial<Record<LaboratoryFrameGroup, LaboratoryFrameTable>>;
  readonly state: LoadState;
} {
  const recordingOptions =
    ref === null
      ? unavailable<LaboratoryRecordingResponse>(apiQueryKeys.laboratoryRecording("none"), "no recording is selected")
      : ref.source === "dataset"
        ? { ...laboratoryRecordingOptions(client, ref.id), enabled: true }
        : workspaceId === null
          ? unavailable<LaboratoryRecordingResponse>(apiQueryKeys.runRecording("none", ref.id), "no workspace is bound")
          : { ...runRecordingOptions(client, workspaceId, ref.id), enabled: true };
  const recording = useQuery<LaboratoryRecordingResponse>(recordingOptions);
  const data = ref !== null && recording.data?.recording_id === ref.id ? recording.data : undefined;
  const frames = useQueries({
    queries: groups.map((group) => {
      if (data === undefined || ref === null) {
        return unavailable<LaboratoryFrameTable>(
          apiQueryKeys.laboratoryFrames(ref?.id ?? "none", group),
          "the recording is not loaded",
        );
      }
      if (ref.source === "dataset") {
        return { ...laboratoryFramesOptions(client, data, group), enabled: true };
      }
      return workspaceId === null
        ? unavailable<LaboratoryFrameTable>(apiQueryKeys.runFrames("none", ref.id, group), "no workspace is bound")
        : { ...runFramesOptions(client, workspaceId, data, group), enabled: true };
    }),
  });

  const tables: Partial<Record<LaboratoryFrameGroup, LaboratoryFrameTable>> = {};
  groups.forEach((group, i) => {
    const table = frames[i]?.data;
    if (table !== undefined && data !== undefined && table.count === data.frame_count) {
      tables[group] = table;
    }
  });

  let state: LoadState;
  if (ref !== null && ref.source === "run" && workspaceId === null) {
    state = { status: "error", error: new Error("no workspace is bound"), step: "run" };
  } else if (recording.isError) {
    state = { status: "error", error: recording.error, step: ref?.source === "run" ? "run" : "recording" };
  } else if (data === undefined) {
    state = { status: "loading", step: ref?.source === "run" ? "run" : "recording" };
  } else {
    const failed = frames.findIndex((query) => query.isError);
    if (failed >= 0) {
      state = { status: "error", error: frames[failed]?.error, step: `${groups[failed]} frames` };
    } else {
      const missing = groups.find((group) => tables[group] === undefined);
      state = missing === undefined ? { status: "ready" } : { status: "loading", step: `${missing} frames` };
    }
  }
  return { recording: data, tables, state };
}

/**
 * The accepted data set for the recording on show: the newest complete set, held while a
 * newer one loads.
 */
export function useAcceptedLabData(
  client: ApiClient,
  ref: RecordingRef | null,
  workspaceId: string | null,
): {
  readonly data: LabData | null;
  readonly pending: LoadState;
  readonly index: LaboratoryIndexResponse | undefined;
  readonly entries: readonly CatalogueEntry[];
} {
  const { index, entries } = useCatalogue(client, workspaceId);
  const model = useRecordingModel(client, ref, workspaceId);
  const set = useRecordingSet(client, ref, GROUPS, workspaceId);
  const accepted = useRef<LabData | null>(null);

  const candidate = useMemo<LabData | null>(() => {
    const pose = set.tables.pose;
    const kinematics = set.tables.kinematics;
    const kinetics = set.tables.kinetics;
    if (
      ref === null ||
      index.data === undefined ||
      model.data === undefined ||
      set.recording === undefined ||
      pose === undefined ||
      kinematics === undefined ||
      kinetics === undefined
    ) {
      return null;
    }
    return {
      client,
      index: index.data,
      entries,
      workspaceId,
      ref,
      model: model.data,
      recording: set.recording,
      frames: { pose, kinematics, kinetics },
      weightN: model.data.total_mass_kg * model.data.gravity_m_s2,
    };
  }, [
    client,
    ref,
    index.data,
    entries,
    workspaceId,
    model.data,
    set.recording,
    set.tables.pose,
    set.tables.kinematics,
    set.tables.kinetics,
  ]);

  useEffect(() => {
    if (candidate !== null) {
      accepted.current = candidate;
    }
  }, [candidate]);

  // A new session generation has a new client: nothing read through the old one is shown.
  // A run of another workspace is never shown in this one.
  if (
    accepted.current !== null &&
    (accepted.current.client !== client ||
      (accepted.current.ref.source === "run" && accepted.current.workspaceId !== workspaceId))
  ) {
    accepted.current = null;
  }
  // The catalogue (run statuses) is always the newest one, even while the held set is shown.
  const held = accepted.current === null ? null : { ...accepted.current, entries };

  let pending: LoadState;
  if (index.isError) {
    pending = { status: "error", error: index.error, step: "dataset index" };
  } else if (index.data === undefined) {
    pending = { status: "loading", step: "dataset index" };
  } else if (model.isError) {
    pending = { status: "error", error: model.error, step: "model" };
  } else if (ref !== null && model.data === undefined) {
    pending = { status: "loading", step: "model" };
  } else {
    pending = set.state;
  }
  const shown = candidate !== null && sameRef(candidate.ref, ref) ? candidate : held;
  return { data: shown, pending, index: index.data, entries };
}
