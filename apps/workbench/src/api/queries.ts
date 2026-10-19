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
} as const;

/** Mutation keys, for the same reason. */
export const apiMutationKeys = {
  openWorkspace: () => ["api", "workspaces", "open"] as const,
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
