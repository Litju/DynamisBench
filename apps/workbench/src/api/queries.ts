/**
 * Query and mutation factories: the keys and functions that own server state.
 *
 * Server/application state belongs to TanStack Query and to nothing else. Components use
 * these factories; they do not write a key, a URL or a fetch call of their own, and they do
 * not copy a response into Zustand. The factories live outside components so the same key is
 * used by the surface that reads it and by whatever later invalidates it.
 *
 * **Keys never contain a credential.** A key is `["api", ...]` plus opaque identifiers the
 * application itself minted for a workspace or an artifact. The credential is not part of a
 * key, a key is never persisted, and the whole cache is discarded when the session changes —
 * so the question "whose data is this?" is answered by the cache's lifetime rather than by a
 * secret in a key.
 */

import { mutationOptions, queryOptions, type QueryClient } from "@tanstack/react-query";

import type { ApiClient } from "./client";
import type {
  LaboratoryFrameGroup,
  LaboratoryIndexResponse,
  LaboratoryModelResponse,
  LaboratoryRecordingResponse,
} from "./laboratory-types";
import type {
  PreflightResponse,
  RunConfigurationRequest,
  RunEvidenceResponse,
  RunListResponse,
  RunProgressResponse,
  StudyCatalogueResponse,
} from "./run-types";
import type {
  ApplicationInfoResponse,
  ArtifactInspectionResponse,
  OpenWorkspaceRequest,
  OpenWorkspaceResponse,
  WorkspaceDiscoveryResponse,
} from "./types";

/**
 * Every key this application uses, in one place.
 *
 * Workspace and artifact identifiers are opaque handles the API minted; they are safe in a
 * key because they address nothing outside the application's own registry, and they are the
 * only way to tell two workspaces' data apart.
 */
export const apiQueryKeys = {
  info: () => ["api", "info"] as const,
  artifacts: (workspaceId: string) =>
    ["api", "workspace", workspaceId, "artifacts"] as const,
  artifact: (workspaceId: string, artifactId: string) =>
    ["api", "workspace", workspaceId, "artifacts", artifactId] as const,
  laboratory: () => ["api", "laboratory"] as const,
  laboratoryModel: () => ["api", "laboratory", "model"] as const,
  laboratoryRecording: (recordingId: string) =>
    ["api", "laboratory", "recordings", recordingId] as const,
  laboratoryFrames: (recordingId: string, group: LaboratoryFrameGroup) =>
    ["api", "laboratory", "recordings", recordingId, "frames", group] as const,
  laboratoryFigure: () => ["api", "laboratory", "figure"] as const,
  studies: (workspaceId: string) => ["api", "workspace", workspaceId, "studies"] as const,
  runs: (workspaceId: string) => ["api", "workspace", workspaceId, "runs"] as const,
  run: (workspaceId: string, runId: string) => ["api", "workspace", workspaceId, "runs", runId] as const,
  runProgress: (workspaceId: string, runId: string) =>
    ["api", "workspace", workspaceId, "runs", runId, "progress"] as const,
  runEvidence: (workspaceId: string, runId: string) =>
    ["api", "workspace", workspaceId, "runs", runId, "evidence"] as const,
  runRecording: (workspaceId: string, runId: string) =>
    ["api", "workspace", workspaceId, "runs", runId, "recording"] as const,
  runModel: (workspaceId: string, runId: string) =>
    ["api", "workspace", workspaceId, "runs", runId, "model"] as const,
  runFrames: (workspaceId: string, runId: string, group: LaboratoryFrameGroup) =>
    ["api", "workspace", workspaceId, "runs", runId, "frames", group] as const,
} as const;

/** Mutation keys, for the same reason. */
export const apiMutationKeys = {
  openWorkspace: () => ["api", "workspaces", "open"] as const,
  preflightRun: (workspaceId: string) => ["api", "workspace", workspaceId, "runs", "preflight"] as const,
  startRun: (workspaceId: string) => ["api", "workspace", workspaceId, "runs", "start"] as const,
  cancelRun: (workspaceId: string) => ["api", "workspace", workspaceId, "runs", "cancel"] as const,
} as const;

/** The build identity of the running application. */
export function apiInfoOptions(client: ApiClient | null) {
  return queryOptions<ApplicationInfoResponse>({
    queryKey: apiQueryKeys.info(),
    queryFn: () => {
      if (client === null) {
        // Disabled below, so this is reachable only if a caller enables a query it has no
        // client for — a programming error rather than a state any surface renders.
        throw new Error("the session provides no API client");
      }
      return client.info();
    },
    // The landing surface renders in every session state, so the factory carries the
    // enablement rather than making each caller remember to. No client means no request, and
    // the state the user sees is the session's own.
    enabled: client !== null,
  });
}

/** One read-only discovery pass over a workspace's source authority. */
export function workspaceArtifactsOptions(client: ApiClient, workspaceId: string) {
  return queryOptions<WorkspaceDiscoveryResponse>({
    queryKey: apiQueryKeys.artifacts(workspaceId),
    queryFn: () => client.listArtifacts(workspaceId),
  });
}

/** One artifact, re-read and revalidated by the application on every call. */
export function artifactInspectionOptions(
  client: ApiClient,
  workspaceId: string,
  artifactId: string,
) {
  return queryOptions<ArtifactInspectionResponse>({
    queryKey: apiQueryKeys.artifact(workspaceId, artifactId),
    queryFn: () => client.getArtifact(workspaceId, artifactId),
  });
}

/**
 * The laboratory's packaged dataset is immutable for the life of a session (it is pinned by
 * digest in the application), so its reads never go stale; the whole cache is still discarded
 * with the session like every other server read.
 */
const IMMUTABLE = { staleTime: Number.POSITIVE_INFINITY, gcTime: 10 * 60 * 1000 } as const;

/** The laboratory dataset's identity, claim and recordings. */
export function laboratoryIndexOptions(client: ApiClient) {
  return queryOptions<LaboratoryIndexResponse>({
    queryKey: apiQueryKeys.laboratory(),
    queryFn: () => client.laboratoryIndex(),
    ...IMMUTABLE,
  });
}

/** The compiled model the laboratory's recordings were integrated with. */
export function laboratoryModelOptions(client: ApiClient) {
  return queryOptions<LaboratoryModelResponse>({
    queryKey: apiQueryKeys.laboratoryModel(),
    queryFn: () => client.laboratoryModel(),
    ...IMMUTABLE,
  });
}

/** One recording's metadata, measurements, work ledger and checks. */
export function laboratoryRecordingOptions(client: ApiClient, recordingId: string) {
  return queryOptions<LaboratoryRecordingResponse>({
    queryKey: apiQueryKeys.laboratoryRecording(recordingId),
    queryFn: () => client.laboratoryRecording(recordingId),
    ...IMMUTABLE,
  });
}

/** Read-model reads of the laboratory never change within a session. */
export const LABORATORY_QUERY_TIMING = IMMUTABLE;

/**
 * Opening a workspace, as a mutation.
 *
 * A mutation rather than Zustand state: opening asks the application to do something and
 * answers with the opaque identifier the API will know the workspace by. The identifier
 * lives in whatever route reads it; the workspace's contents live in the query cache under
 * the keys above.
 */
export function openWorkspaceOptions(client: ApiClient) {
  return mutationOptions<OpenWorkspaceResponse, Error, OpenWorkspaceRequest>({
    mutationKey: apiMutationKeys.openWorkspace(),
    mutationFn: (request) => client.openWorkspace(request),
  });
}

/**
 * Runs are re-verified from sealed evidence on every read, and sealed evidence can be damaged on
 * disk at any time. A run read is therefore never treated as immutable: it is fresh for a short
 * while (so the stage, plots and folios share one read) and read again after that. Evidence is
 * always re-read when it is looked at.
 */
const RUN_READ_TIMING = { staleTime: 15_000, gcTime: 5 * 60 * 1000 } as const;

/** Polling interval of a run's progress while it is active, ms. */
export const RUN_PROGRESS_POLL_MS = 400;

/** The workspace's studies, whether each can run here, and their configuration surfaces. */
export function studyCatalogueOptions(client: ApiClient, workspaceId: string) {
  return queryOptions<StudyCatalogueResponse>({
    queryKey: apiQueryKeys.studies(workspaceId),
    queryFn: () => client.studyCatalogue(workspaceId),
    staleTime: 30_000,
  });
}

/** Every sealed run of the workspace (re-verified) and this session's runs in progress. */
export function runListOptions(client: ApiClient, workspaceId: string) {
  return queryOptions<RunListResponse>({
    queryKey: apiQueryKeys.runs(workspaceId),
    queryFn: () => client.listRuns(workspaceId),
    staleTime: 2_000,
    refetchInterval: (query) =>
      query.state.data?.runs.some((run) => run.progress?.active === true) ? 1_000 : false,
  });
}

/** The progress of one run this session started, polled while it is active. */
export function runProgressOptions(client: ApiClient, workspaceId: string, runId: string) {
  return queryOptions<RunProgressResponse>({
    queryKey: apiQueryKeys.runProgress(workspaceId, runId),
    queryFn: () => client.runProgress(workspaceId, runId),
    staleTime: 0,
    refetchInterval: (query) => (query.state.data?.active === false ? false : RUN_PROGRESS_POLL_MS),
  });
}

/** Both seals, the provenance chain, verification and assessment of one run: always re-read. */
export function runEvidenceOptions(client: ApiClient, workspaceId: string, runId: string) {
  return queryOptions<RunEvidenceResponse>({
    queryKey: apiQueryKeys.runEvidence(workspaceId, runId),
    queryFn: () => client.runEvidence(workspaceId, runId),
    staleTime: 0,
    refetchOnMount: "always",
  });
}

/** A verified run as a laboratory recording. */
export function runRecordingOptions(client: ApiClient, workspaceId: string, runId: string) {
  return queryOptions<LaboratoryRecordingResponse>({
    queryKey: apiQueryKeys.runRecording(workspaceId, runId),
    queryFn: () => client.runRecording(workspaceId, runId),
    ...RUN_READ_TIMING,
  });
}

/** The compiled model exactly as the run executed it. */
export function runModelOptions(client: ApiClient, workspaceId: string, runId: string) {
  return queryOptions<LaboratoryModelResponse>({
    queryKey: apiQueryKeys.runModel(workspaceId, runId),
    queryFn: () => client.runModel(workspaceId, runId),
    ...RUN_READ_TIMING,
  });
}

export const RUN_QUERY_TIMING = RUN_READ_TIMING;

/** Preflight one configuration: plans and admits; nothing starts and nothing is sealed. */
export function preflightRunOptions(client: ApiClient, workspaceId: string) {
  return mutationOptions<PreflightResponse, Error, RunConfigurationRequest>({
    mutationKey: apiMutationKeys.preflightRun(workspaceId),
    mutationFn: (request) => client.preflightRun(workspaceId, request),
  });
}

/** Ask the run service to execute one configuration in the isolated worker. */
export function startRunOptions(client: ApiClient, workspaceId: string) {
  return mutationOptions<RunProgressResponse, Error, RunConfigurationRequest>({
    mutationKey: apiMutationKeys.startRun(workspaceId),
    mutationFn: (request) => client.startRun(workspaceId, request),
  });
}

/** Ask the supervisor to terminate a run's worker; the run is sealed as canceled. */
export function cancelRunOptions(client: ApiClient, workspaceId: string) {
  return mutationOptions<RunProgressResponse, Error, string>({
    mutationKey: apiMutationKeys.cancelRun(workspaceId),
    mutationFn: (runId) => client.cancelRun(workspaceId, runId),
  });
}

/**
 * Discard every cached server read.
 *
 * Called when the desktop API session changes generation or becomes non-ready: data read
 * from one sidecar session must not be presented as the current session's data. A cache with
 * no persisted store is discarded by being emptied, which is the only removal this
 * application has to perform.
 */
export function discardServerState(queryClient: QueryClient): void {
  queryClient.clear();
}
