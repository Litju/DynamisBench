/**
 * The Explorer pane: the workspace's authority, grouped and selectable.
 *
 * It renders exactly what discovery published. An artifact's validity, diagnostics and
 * truncation flag are the API's facts; the pane adds hierarchy and a selection control, and
 * nothing that could be read as a scientific assessment of its own. Every selection is a
 * real button, so it is reachable by tab, activated by Enter or Space, and announces its
 * selected state.
 */

import { AlertTriangle, FileJson, FileText } from "lucide-react";

import type { ArtifactSummary, WorkspaceDiscoveryResponse } from "../api/types";
import { Badge } from "../ui/badge";
import { artifactCounts, groupArtifacts } from "./grouping";

export function ExplorerPane({
  discovery,
  selectedId,
  onSelect,
}: {
  discovery: WorkspaceDiscoveryResponse;
  selectedId: string | null;
  onSelect(artifactId: string): void;
}) {
  const groups = groupArtifacts(discovery.artifacts.artifacts);
  const counts = artifactCounts(discovery.artifacts.artifacts);

  return (
    <section aria-labelledby="explorer-heading" className="flex min-h-0 flex-col gap-3">
      <div className="flex items-baseline justify-between gap-2">
        <h2 id="explorer-heading" className="text-sm font-semibold text-slate-800">
          Explorer
        </h2>
        <span className="text-xs text-slate-500">
          {counts.total} artifact{counts.total === 1 ? "" : "s"}
        </span>
      </div>

      <div className="flex flex-wrap gap-1.5" aria-label="Artifact counts">
        <Badge tone="ready">{counts.valid} valid</Badge>
        <Badge tone={counts.invalid > 0 ? "danger" : "neutral"}>{counts.invalid} invalid</Badge>
      </div>

      {discovery.issues.length > 0 && (
        <div className="rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-800">
          <p className="font-medium">
            {discovery.issues.length} structural issue
            {discovery.issues.length === 1 ? "" : "s"} in the workspace layout
            {discovery.issues_truncated ? " (list truncated)" : ""}
          </p>
          <ul className="mt-1 space-y-1">
            {discovery.issues.map((issue, index) => (
              <li key={`${issue.code}-${issue.reference ?? "workspace"}-${index}`}>
                <span className="font-medium">{issue.code}</span>
                {issue.reference !== null && <span>: {issue.reference}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {groups.length === 0 ? (
        <p className="rounded-md border border-dashed border-slate-300 p-3 text-sm text-slate-500">
          This workspace holds no source-authority artifacts in the declared categories.
        </p>
      ) : (
        <div className="min-h-0 overflow-y-auto pr-1" role="listbox" aria-label="Workspace artifacts">
          {groups.map((group) => (
            <div key={`${group.category}/${group.kind}`} className="mb-3">
              <h3 className="px-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                {group.category} / {group.kind}
              </h3>
              <ul className="mt-1 space-y-0.5">
                {group.artifacts.map((artifact) => (
                  <li key={artifact.artifact_id}>
                    <ArtifactOption
                      artifact={artifact}
                      selected={artifact.artifact_id === selectedId}
                      onSelect={onSelect}
                    />
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function ArtifactOption({
  artifact,
  selected,
  onSelect,
}: {
  artifact: ArtifactSummary;
  selected: boolean;
  onSelect(artifactId: string): void;
}) {
  const Icon = artifact.authoring_format === "json" ? FileJson : FileText;
  const label = artifact.identifier ?? artifact.logical_reference;

  return (
    <button
      type="button"
      role="option"
      aria-selected={selected}
      onClick={() => onSelect(artifact.artifact_id)}
      className={
        "flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors " +
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 " +
        (selected ? "bg-slate-200 text-slate-900" : "text-slate-700 hover:bg-slate-100")
      }
    >
      <Icon aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
      <span className="min-w-0 flex-1">
        <span className="block truncate font-medium">{label}</span>
        <span className="block truncate text-xs text-slate-500">{artifact.logical_reference}</span>
      </span>
      {artifact.validation_status === "invalid" ? (
        <AlertTriangle aria-label="Invalid" className="mt-0.5 h-4 w-4 shrink-0 text-rose-600" />
      ) : (
        <span className="mt-0.5 text-xs text-emerald-700">valid</span>
      )}
    </button>
  );
}
