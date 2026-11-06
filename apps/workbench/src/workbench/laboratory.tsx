import { Box, ChevronLeft, ChevronRight } from "lucide-react";

import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState, type ReactNode } from "react";

import { ApiClientError } from "../api/errors";
import { apiQueryKeys, runListOptions } from "../api/queries";
import type { RunListResponse } from "../api/run-types";
import type { ArtifactSummary } from "../api/types";
import { useApiClient } from "../session/provider";

import { useUiStore } from "../store/ui";
import { LIVE_WORKSPACE_RUN_API_AVAILABLE, LIVE_WORKSPACE_RUN_API_UNAVAILABLE_MESSAGE } from "../laboratory/m1-capabilities";

/** What the workspace's runs are, as the run service read them back from their seals. */
function useRunSummary(workspaceId: string): { execution: string; evidence: string; available: boolean } {
  const client = useApiClient();
  const runs = useQuery({
    ...(client === null || !LIVE_WORKSPACE_RUN_API_AVAILABLE
      ? {
          queryKey: apiQueryKeys.runs(workspaceId),
          queryFn: (): Promise<RunListResponse> => Promise.reject(new Error(LIVE_WORKSPACE_RUN_API_UNAVAILABLE_MESSAGE)),
        }
      : runListOptions(client, workspaceId)),
    enabled: client !== null && LIVE_WORKSPACE_RUN_API_AVAILABLE,
    retry: false,
  });
  if (!LIVE_WORKSPACE_RUN_API_AVAILABLE) {
    return {
      execution: "Live workspace runs unavailable in M1",
      evidence: "Packaged diagnostic recordings are available in the Laboratory",
      available: true,
    };
  }
  if (runs.isError) {
    const unavailable = runs.error instanceof ApiClientError && runs.error.status === 503;
    return {
      execution: unavailable ? "Unavailable in this session" : "Could not be read",
      evidence: "—",
      available: false,
    };
  }
  if (runs.data === undefined) {
    return { execution: "Reading…", evidence: "Reading…", available: true };
  }
  const list = runs.data.runs;
  const active = list.filter((run) => run.progress?.active === true).length;
  const verified = list.filter((run) => run.status === "verified").length;
  const failed = list.filter((run) => run.status === "failed").length;
  const rejected = list.filter((run) => run.status === "rejected" || run.status === "incomplete").length;
  return {
    execution: list.length === 0 ? "No runs yet" : `${list.length} run${list.length === 1 ? "" : "s"}${active > 0 ? ` · ${active} active` : ""}`,
    evidence:
      list.length === 0
        ? "No sealed evidence yet"
        : `${verified} verified · ${failed} failed${rejected > 0 ? ` · ${rejected} rejected` : ""}`,
    available: true,
  };
}

export function WorkbenchLayout({
  navigator,
  inspector,
  content,
  artifact,
  workspaceId,
  status,
}: {
  navigator: ReactNode;
  inspector: ReactNode;
  content: ReactNode;

  artifact: ArtifactSummary | null;
  workspaceId: string;
  status: string;
}) {
  const { sidebarCollapsed, toggleSidebar, mode } = useUiStore();

  const [inspectorCollapsed, setInspectorCollapsed] = useState(false);

  const [layout, setLayout] = useState("bottom");

  const runs = useRunSummary(workspaceId);

  const [dock, setDock] = useState("source");

  const title =
    mode === "study"
      ? "Study & Model"
      : mode === "analysis"
        ? "Analysis & VVUQ"
        : "Evidence & Provenance";

  return (
    <>
      <h1 className="sr-only">Workspace</h1>

      <dl className="wb-context" aria-label="Scientific context">
        <div>
          <dt>Workspace</dt>
          <dd title={workspaceId}>
            <code>{workspaceId}</code>
          </dd>
        </div>

        <div>
          <dt>Source / model definition</dt>
          <dd>
            {artifact?.identifier ??
              artifact?.logical_reference ??
              "No source selected"}
          </dd>
        </div>

        <div>
          <dt>Source validation</dt>
          <dd>{status}</dd>
        </div>

        <div>
          <dt>Execution</dt>
          <dd>{runs.execution}</dd>
        </div>

        <div>
          <dt>Sealed evidence / assessment</dt>
          <dd>{runs.evidence}</dd>
        </div>
      </dl>

      <div
        className="wb-columns"
        style={{
          gridTemplateColumns: `${sidebarCollapsed ? "30px" : "minmax(180px,232px)"} minmax(0,1fr) ${inspectorCollapsed ? "30px" : "minmax(220px,280px)"}`,
        }}
      >
        <aside className="wb-pane" aria-label="Navigator">
          <div className="wb-pane-title">
            <span className={sidebarCollapsed ? "sr-only" : ""}>Navigator</span>
            <button
              type="button"
              onClick={toggleSidebar}
              aria-expanded={!sidebarCollapsed}
              aria-label={
                sidebarCollapsed ? "Expand Navigator" : "Collapse Navigator"
              }
            >
              {sidebarCollapsed ? (
                <ChevronRight size={14} />
              ) : (
                <ChevronLeft size={14} />
              )}
            </button>
          </div>

          {sidebarCollapsed ? (
            <span className="wb-rail">Navigator</span>
          ) : (
            <div className="wb-pane-body">{navigator}</div>
          )}
        </aside>

        <section
          className="wb-lab"
          aria-label={mode === "lab" ? "Simulation Laboratory" : title}
        >
          {mode === "lab" ? (
            <>
              <div className="wb-pane wb-toolbar">
                <strong>Simulation Laboratory</strong>
                <Link
                  to="/laboratory"
                  search={{ workspace: workspaceId }}
                  className="wb-link-button"
                  aria-disabled={!runs.available}
                >
                  Open in the laboratory
                </Link>
                <span className="wb-tag">{runs.execution}</span>

                <label className="ml-auto">
                  Layout{" "}
                  <select
                    aria-label="Laboratory layout"
                    aria-describedby="laboratory-layout-availability"
                    value={layout}
                    onChange={(e) => setLayout(e.target.value)}
                  >
                    <option value="bottom">Bottom</option>
                    <option value="side">Side</option>
                  </select>
                  <span id="laboratory-layout-availability" className="sr-only">The 3D scene of this workspace's runs is drawn in its laboratory.</span>
                </label>
              </div>

              <div
                className="wb-lab-content"
                data-layout={layout}
                style={{
                  gridTemplateColumns:
                    layout === "side"
                      ? "minmax(0,1fr) minmax(0,1fr)"
                      : "minmax(0,1fr)",
                }}
              >
                <div className="wb-pane wb-scene">
                  <div className="wb-pane-title">
                    <span>Model scene</span>
                    <span className="wb-tag">IN THE LABORATORY</span>
                  </div>
                  <div className="wb-unavailable">
                    <Box size={36} strokeWidth={1} />
                    <strong>Studies run in the laboratory</strong>
                    <p>
                      Configure a study of this workspace, preflight and execute
                      it in the isolated worker, play the sealed and verified
                      run in 3D, analyse and compare it, and inspect its
                      evidence — in the{" "}
                      <Link
                        to="/laboratory"
                        search={{ workspace: workspaceId }}
                        className="text-accent underline"
                      >
                        laboratory of this workspace
                      </Link>
                      . Source definitions are inspected below.
                    </p>
                  </div>
                  <div className="wb-toolbar">
                    <span>{runs.execution}</span>
                    <span className="ml-auto">{runs.evidence}</span>
                  </div>
                </div>

                <div className="wb-pane wb-dock" hidden={layout === "scene"}>
                  <div className="wb-toolbar" aria-label="Laboratory dock">
                    {(
                      [
                        ["source", "Source content"],
                        ["signals", "Signals"],
                        ["log", "Execution log"],
                      ] as const
                    ).map(([id, label]) => (
                      <button
                        key={id}
                        type="button"
                        aria-pressed={dock === id}
                        onClick={() => setDock(id)}
                      >
                        {label}
                      </button>
                    ))}
                  </div>

                  <div className="wb-pane-body" hidden={dock !== "source"}>
                    {content}
                  </div>

                  {dock !== "source" && (
                    <InTheLaboratory
                      workspaceId={workspaceId}
                      title={
                        dock === "signals"
                          ? "Signals of this workspace's runs"
                          : "Execution of this workspace's runs"
                      }
                      detail={
                        dock === "signals"
                          ? "The canonical series of every verified run is plotted, linked to one playback clock, in the laboratory's Laboratory and Analysis folios."
                          : `${runs.execution} · ${runs.evidence}. Preflight, execution, progress, cancellation and each run's read-back status are in the laboratory's Study & Runs folio.`
                      }
                    />
                  )}
                </div>
              </div>
            </>
          ) : (
            <div className="wb-pane flex flex-1 flex-col">
              <div className="wb-pane-title">{title}</div>

              {mode === "study" ? (
                <div className="wb-pane-body">{content}</div>
              ) : (
                <InTheLaboratory
                  workspaceId={workspaceId}
                  title={
                    mode === "analysis"
                      ? "Analysis of this workspace's runs"
                      : "Evidence of this workspace's runs"
                  }
                  detail={
                    mode === "analysis"
                      ? "Summaries, the work–energy ledger and comparison of verified runs are in the laboratory's Analysis folio. Validation against measured data and uncertainty quantification are not available: numerical verification and assessment against predeclared criteria are not scientific validation."
                      : `${runs.evidence}. Both sealed bundles of every run, its provenance chain, verification and assessment are inspected in the laboratory's Evidence folio; source identity and diagnostics are in the Inspector.`
                  }
                />
              )}
            </div>
          )}
        </section>

        <aside className="wb-pane" aria-label="Source Inspector">
          <div className="wb-pane-title">
            <span className={inspectorCollapsed ? "sr-only" : ""}>
              Source properties
            </span>
            <button
              type="button"
              onClick={() => setInspectorCollapsed(!inspectorCollapsed)}
              aria-expanded={!inspectorCollapsed}
              aria-label={
                inspectorCollapsed ? "Expand Inspector" : "Collapse Inspector"
              }
            >
              {inspectorCollapsed ? (
                <ChevronLeft size={14} />
              ) : (
                <ChevronRight size={14} />
              )}
            </button>
          </div>
          {inspectorCollapsed ? (
            <span className="wb-rail">Inspector</span>
          ) : (
            <div className="wb-pane-body">{inspector}</div>
          )}
        </aside>
      </div>
    </>
  );
}

function InTheLaboratory({
  workspaceId,
  title,
  detail,
}: {
  workspaceId: string;
  title: string;
  detail: string;
}) {
  return (
    <div className="wb-unavailable" role="status">
      <span className="wb-tag">IN THE LABORATORY</span>
      <strong>{title}</strong>
      <p>{detail}</p>
      <Link to="/laboratory" search={{ workspace: workspaceId }} className="text-accent underline">
        Open the laboratory of this workspace
      </Link>
    </div>
  );
}
