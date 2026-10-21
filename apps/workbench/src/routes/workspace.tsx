/**
 * The workspace route: Explorer | Workspace | Inspector over one opaque workspace identifier.
 *
 * This is a read-only workbench. The route reads discovery and inspection through the typed
 * client and TanStack Query, keeps the selected artifact identifier in component state, and
 * renders the API's own read models. It never writes, never opens a file itself, and never
 * turns a root path into a route parameter.
 *
 * **Selection is scoped twice.** The query key carries both the workspace and the artifact,
 * and the rendered inspection is accepted only when its `artifact_id` is the one currently
 * selected. A slow answer for a previously selected artifact therefore cannot become the
 * current selection: it lives under its own key and is filtered out here as well.
 *
 * **A stale identifier is a bounded state, not a recovery routine.** If the sidecar restarted,
 * the registry is empty and an identifier from the previous process answers 404. The route
 * says so and offers the explicit open flow; it never re-opens from remembered roots, because
 * there are none to remember.
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createRoute, Link } from "@tanstack/react-router";
import { AlertCircle, RotateCcw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { ApiClientError } from "../api/errors";
import {
  apiQueryKeys,
  artifactInspectionOptions,
  workspaceArtifactsOptions,
} from "../api/queries";
import type { ArtifactInspectionResponse, ArtifactSummary } from "../api/types";
import { useApiClient, useSession } from "../session/provider";
import { Badge } from "../ui/badge";
import { ActivityPanel } from "../workbench/activity";
import { ArtifactContent } from "../workbench/artifact-tree";
import { ExplorerPane } from "../workbench/explorer";
import { InspectorPane } from "../workbench/inspector";
import { rootRoute } from "./root";

export const workspaceRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/workspace/$workspaceId",
  component: WorkspacePage,
});

function WorkspacePage() {
  const { workspaceId } = workspaceRoute.useParams();

  return (
    <div className="mx-auto flex w-full max-w-[110rem] flex-col gap-4">
      <WorkspaceWorkbench workspaceId={workspaceId} />
      <ActivityPanel />
    </div>
  );
}

function WorkspaceWorkbench({ workspaceId }: { workspaceId: string }) {
  const { session } = useSession();
  const client = useApiClient();
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // A credential rotation is a new session generation: the Query cache is discarded by the
  // provider, and the selection belongs to the previous generation too.
  useEffect(() => {
    setSelectedId(null);
  }, [client, workspaceId]);

  const discovery = useQuery({
    ...(client === null
      ? { queryKey: apiQueryKeys.artifacts(workspaceId), queryFn: () => Promise.reject() }
      : workspaceArtifactsOptions(client, workspaceId)),
    enabled: client !== null,
  });

  const selectedSummary = useMemo<ArtifactSummary | null>(() => {
    if (selectedId === null || discovery.data === undefined) {
      return null;
    }
    return (
      discovery.data.artifacts.artifacts.find(
        (artifact) => artifact.artifact_id === selectedId,
      ) ?? null
    );
  }, [discovery.data, selectedId]);

  const inspection = useQuery({
    ...(client === null || selectedId === null
      ? {
          queryKey: apiQueryKeys.artifact(workspaceId, selectedId ?? "none"),
          queryFn: () => Promise.reject(),
        }
      : artifactInspectionOptions(client, workspaceId, selectedId)),
    enabled: client !== null && selectedId !== null,
  });

  const currentInspection =
    inspection.data !== undefined && inspection.data.artifact_id === selectedId
      ? inspection.data
      : null;

  if (session.phase !== "ready" || client === null) {
    return (
      <section className="rounded-lg border border-slate-200 bg-white p-6">
        <h1 className="text-lg font-semibold tracking-tight">Workspace</h1>
        <p className="mt-2 text-sm text-slate-600">
          The local API session is not ready, so this workspace cannot be read.{" "}
          {session.phase === "unavailable"
            ? "Open the workbench inside the DynamisBench desktop shell to start a session."
            : "The workspace will become available when the session is ready again."}
        </p>
        <p className="mt-2 text-xs text-slate-500">
          Opaque identifier <code className="rounded bg-slate-100 px-1 py-0.5">{workspaceId}</code>
        </p>
      </section>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="flex flex-col gap-0.5">
          <h1 className="text-lg font-semibold tracking-tight">Workspace</h1>
          <p className="text-xs text-slate-500">
            Opaque identifier <code className="rounded bg-slate-100 px-1 py-0.5">{workspaceId}</code>
          </p>
        </div>
        <span className="text-xs text-slate-500">
          Read-only source authority · inspection re-reads on every request
        </span>
      </div>

      {discovery.isPending && <PaneMessage>Discovering workspace authority…</PaneMessage>}

      {discovery.isError && (
        <WorkspaceFailure
          title="The workspace could not be discovered"
          error={discovery.error}
          workspaceId={workspaceId}
        />
      )}

      {discovery.data !== undefined && (
        <div className="grid gap-4 lg:grid-cols-[minmax(15rem,0.85fr)_minmax(0,2fr)_minmax(16rem,1fr)]">
          <Pane>
            <ExplorerPane
              discovery={discovery.data}
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          </Pane>

          <Pane>
            <WorkspaceContentPane
              workspaceId={workspaceId}
              selectedSummary={selectedSummary}
              selectedId={selectedId}
              inspection={currentInspection}
              inspectionPending={inspection.isPending && selectedId !== null}
              inspectionError={inspection.error}
              onReRead={() => {
                if (selectedId !== null) {
                  void queryClient.invalidateQueries({
                    queryKey: apiQueryKeys.artifact(workspaceId, selectedId),
                  });
                }
              }}
            />
          </Pane>

          <Pane>
            <InspectorPane artifact={currentInspection ?? selectedSummary} />
          </Pane>
        </div>
      )}
    </div>
  );
}

function WorkspaceContentPane({
  workspaceId,
  selectedSummary,
  selectedId,
  inspection,
  inspectionPending,
  inspectionError,
  onReRead,
}: {
  workspaceId: string;
  selectedSummary: ArtifactSummary | null;
  selectedId: string | null;
  inspection: ArtifactInspectionResponse | null;
  inspectionPending: boolean;
  inspectionError: unknown;
  onReRead(): void;
}) {
  return (
    <section aria-labelledby="workspace-content-heading" className="flex min-h-0 flex-col gap-3">
      <div className="flex items-baseline justify-between gap-2">
        <h2 id="workspace-content-heading" className="text-sm font-semibold text-slate-800">
          Validated content
        </h2>
        <div className="flex items-center gap-2">
          {selectedSummary !== null && (
            <Badge tone={selectedSummary.validation_status === "valid" ? "ready" : "danger"}>
              {selectedSummary.validation_status}
            </Badge>
          )}
          {selectedId !== null && (
            <button
              type="button"
              onClick={onReRead}
              disabled={inspectionPending}
              className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium text-slate-600 hover:bg-slate-100 hover:text-slate-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 disabled:opacity-50"
            >
              <RotateCcw aria-hidden className="h-3 w-3" />
              Re-read
            </button>
          )}
        </div>
      </div>

      {selectedId === null ? (
        <p className="text-sm text-slate-500">
          Select an artifact in the Explorer to inspect its validated content. Files are
          re-read and revalidated by the application; this pane never reads them.
        </p>
      ) : inspectionError !== null && inspectionError !== undefined ? (
        <InspectionFailure workspaceId={workspaceId} error={inspectionError} />
      ) : inspectionPending ? (
        <p className="text-sm text-slate-500">Reading and validating the selected artifact…</p>
      ) : inspection === null ? (
        <p className="text-sm text-slate-500">
          This artifact is no longer part of the current discovery response.
        </p>
      ) : inspection.validation_status === "valid" && inspection.content !== null ? (
        <>
          <p className="text-xs text-slate-500">
            Validated {inspection.kind} content, serialised from the domain model. Read-only.
          </p>
          <div className="min-h-0 overflow-auto rounded-md border border-slate-200 bg-slate-50 p-3">
            <ArtifactContent content={inspection.content} />
          </div>
        </>
      ) : (
        <div className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-900">
          <p className="font-medium">No validated content is published for this artifact.</p>
          <p className="mt-1 text-xs">
            The document did not produce a validated definition. Bounded diagnostics are in the
            Inspector and in the artifact's Explorer entry.
          </p>
        </div>
      )}
    </section>
  );
}

function InspectionFailure({ workspaceId, error }: { workspaceId: string; error: unknown }) {
  if (isNotFound(error)) {
    return (
      <StaleIdentifier
        title="This artifact is no longer registered"
        detail="The application no longer knows this identifier. A restarted sidecar starts with an empty registry, and this workbench does not reopen workspaces from remembered roots."
        workspaceId={workspaceId}
      />
    );
  }

  return (
    <div role="alert" className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-900">
      <p className="flex items-center gap-1.5 font-medium">
        <AlertCircle aria-hidden className="h-4 w-4" />
        The artifact could not be inspected
      </p>
      <p className="mt-1 text-xs">{failureText(error)}</p>
    </div>
  );
}

function WorkspaceFailure({
  title,
  error,
  workspaceId,
}: {
  title: string;
  error: unknown;
  workspaceId: string;
}) {
  if (isNotFound(error)) {
    return (
      <StaleIdentifier
        title="This workspace is no longer registered"
        detail="The application no longer knows this workspace identifier. A restarted sidecar starts with an empty registry, and this workbench does not reopen workspaces from remembered roots."
        workspaceId={workspaceId}
      />
    );
  }

  return (
    <div role="alert" className="rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900">
      <p className="flex items-center gap-1.5 font-medium">
        <AlertCircle aria-hidden className="h-4 w-4" />
        {title}
      </p>
      <p className="mt-1 text-xs">{failureText(error)}</p>
    </div>
  );
}

function StaleIdentifier({
  title,
  detail,
  workspaceId,
}: {
  title: string;
  detail: string;
  workspaceId: string;
}) {
  return (
    <div
      role="status"
      className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900"
    >
      <p className="font-medium">{title}</p>
      <p className="mt-1 text-xs">{detail}</p>
      <p className="mt-2 break-all text-xs text-amber-800">
        Identifier <code>{workspaceId}</code>
      </p>
      <Link
        to="/"
        hash="open-workspace"
        className="mt-3 inline-flex items-center gap-1.5 rounded-md bg-amber-900 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-amber-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500"
      >
        <RotateCcw aria-hidden className="h-3.5 w-3.5" />
        Open a workspace again
      </Link>
    </div>
  );
}

function Pane({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-[24rem] flex-col rounded-lg border border-slate-200 bg-white p-4">
      {children}
    </div>
  );
}

function PaneMessage({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-500">
      {children}
    </div>
  );
}

function isNotFound(error: unknown): boolean {
  return error instanceof ApiClientError && error.kind === "http" && error.status === 404;
}

function failureText(error: unknown): string {
  return error instanceof ApiClientError
    ? (error.apiMessage ?? error.message)
    : "The application API could not complete the request.";
}
