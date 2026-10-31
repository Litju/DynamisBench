import { Box, ChevronLeft, ChevronRight } from "lucide-react";

import { useState, type ReactNode } from "react";

import type { ArtifactSummary } from "../api/types";

import { useUiStore } from "../store/ui";

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
          <dd>Unavailable</dd>
        </div>

        <div>
          <dt>Native evidence / assessment</dt>
          <dd>Unavailable / not assessed</dd>
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
                <span className="wb-tag">READ ONLY</span>
                <button disabled title="No production preflight API">
                  Preflight
                </button>
                <button disabled title="No production execution API">
                  Execute
                </button>
                <button disabled title="No production cancellation API">
                  Cancel
                </button>

                <label className="ml-auto">
                  Layout{" "}
                  <select
                    aria-label="Laboratory layout"
                    value={layout}
                    onChange={(e) => setLayout(e.target.value)}
                  >
                    <option value="bottom">Bottom</option>
                    <option value="side">Side</option>
                    <option value="scene">Scene only</option>
                  </select>
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
                    <span className="wb-tag">UNAVAILABLE</span>
                  </div>
                  <div className="wb-unavailable">
                    <Box size={36} strokeWidth={1} />
                    <strong>No materialized scientific scene</strong>
                    <p>
                      Inspect validated source definitions below. Geometry,
                      model simulation and recorded trajectories are not
                      published by the current application API.
                    </p>
                  </div>
                  <div className="wb-toolbar">
                    <button disabled>Play</button>
                    <span>Recorded playback unavailable</span>
                    <span className="ml-auto">No trajectory</span>
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
                    <Unavailable
                      title={
                        dock === "signals"
                          ? "Signals unavailable"
                          : "Execution log unavailable"
                      }
                      detail="No production execution or canonical trajectory API is connected. Application activity below describes source operations only."
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
                <Unavailable
                  title={
                    mode === "analysis"
                      ? "Scientific analysis unavailable"
                      : "Native evidence unavailable"
                  }
                  detail={
                    mode === "analysis"
                      ? "Comparisons, validation and uncertainty assessment require accepted result and scientific contracts. Source validation is not scientific qualification."
                      : "Source identity and diagnostics are available in the Inspector. Native execution evidence, canonical results and assessments are not published by the current API."
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

function Unavailable({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="wb-unavailable" role="status">
      <span className="wb-tag">NOT IMPLEMENTED</span>
      <strong>{title}</strong>
      <p>{detail}</p>
    </div>
  );
}
