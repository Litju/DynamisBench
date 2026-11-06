/**
 * The codex rail: the packaged recordings, the bound workspace's runs, the model tree, and the
 * stage layers. A run that is not verified is listed with its status and cannot be put on the
 * stage; its evidence can still be inspected.
 */

import { ChevronsLeft, ChevronsRight } from "lucide-react";

import type { LaboratoryRecordingEntry } from "../api/laboratory-types";
import { sameRef, type CatalogueEntry } from "./sources";
import { bodyLabel, bodyTree } from "./anatomy";
import { useLabData } from "./data";
import { primaryJointOf } from "./stage/stage";
import { LAYERS, useLaboratoryStore, type Layer } from "./store";

export const LAYER_LABELS: Record<Layer, string> = {
  athlete: "Athlete & barbell",
  grf: "Ground reaction vectors",
  com: "Centre of mass & plumb",
  support: "Support polygon (loaded)",
  plantar: "Plantar load discs",
  barPath: "Bar path",
  comPath: "CoM path",
  jointAxes: "Joint axes",
  floor: "Floor instrument",
};

const LAYER_PIGMENTS: Record<Layer, string> = {
  athlete: "var(--codex-bone)",
  grf: "var(--codex-sanguine)",
  com: "var(--codex-gold)",
  support: "var(--codex-verdigris)",
  plantar: "var(--codex-verdigris)",
  barPath: "var(--codex-gold)",
  comPath: "var(--codex-ochre)",
  jointAxes: "var(--codex-lapis)",
  floor: "var(--codex-ink-3)",
};

/** "dt 1 ms · all 22 checks pass" / "6 checks fail" */
export function recordingStatus(
  entry: LaboratoryRecordingEntry & Partial<Pick<CatalogueEntry, "status" | "playable" | "reasons">>,
): { text: string; tone: "pass" | "fail" | "partial" | "active" } {
  if (entry.status === "failed" && (entry.reasons ?? []).some((reason) => reason.includes("(canceled"))) {
    return { text: "canceled · sealed as a failure", tone: "fail" };
  }
  if (entry.status !== undefined && entry.status !== "packaged" && entry.status !== "verified") {
    const active = ["planning", "preflight", "starting", "running", "canceling", "sealing", "deriving"].includes(entry.status);
    return { text: active ? `${entry.status.replace("_", " ")}…` : entry.status.replace("_", " "), tone: active ? "active" : "fail" };
  }
  const dt = `dt ${formatMilliseconds(entry.timestep_s)}`;
  if (!entry.completed) {
    return { text: `${dt} · did not complete`, tone: "fail" };
  }
  if (entry.checks_failed > 0) {
    return { text: `${dt} · ${entry.checks_failed} of ${entry.checks_passed + entry.checks_failed + entry.checks_not_evaluated} checks fail`, tone: "fail" };
  }
  if (entry.checks_not_evaluated > 0) {
    return { text: `${dt} · ${entry.checks_passed} pass · ${entry.checks_not_evaluated} not evaluated`, tone: "partial" };
  }
  return { text: `${dt} · all ${entry.checks_passed} checks pass`, tone: "pass" };
}

function formatMilliseconds(seconds: number): string {
  const ms = seconds * 1000;
  if (!Number.isFinite(ms)) return "— ms";
  const rounded = Math.round(ms * 1000) / 1000;
  return `${Number.isInteger(rounded) ? rounded.toFixed(0) : String(Number(rounded.toPrecision(3)))} ms`;
}

export function Rail() {
  const collapsed = useLaboratoryStore((state) => state.railCollapsed);
  const toggleRail = useLaboratoryStore((state) => state.toggleRail);
  return (
    <aside className="lab-rail" aria-label="Codex" data-collapsed={collapsed}>
      <button
        type="button"
        className="lab-rail-toggle"
        onClick={toggleRail}
        aria-expanded={!collapsed}
        aria-label={collapsed ? "Expand codex rail" : "Collapse codex rail"}
      >
        {collapsed ? <ChevronsRight size={14} aria-hidden /> : <ChevronsLeft size={14} aria-hidden />}
      </button>
      {collapsed ? (
        <span className="lab-rail-spine">Recordings · Model · Layers</span>
      ) : (
        <>
          <Recordings />
          <ModelTree />
          <Layers />
        </>
      )}
    </aside>
  );
}

function Recordings() {
  const { entries, ref, workspaceId } = useLabData();
  const setRecording = useLaboratoryStore((state) => state.setRecording);
  const requested = useLaboratoryStore((state) => state.recording);
  const setFolio = useLaboratoryStore((state) => state.setFolio);
  const inspectEvidence = useLaboratoryStore((state) => state.inspectEvidence);
  const packaged = entries.filter((entry) => entry.ref.source === "dataset");
  const runs = entries.filter((entry) => entry.ref.source === "run");
  const item = (entry: CatalogueEntry) => {
    const status = recordingStatus(entry);
    const shown = sameRef(entry.ref, ref);
    return (
      <li key={`${entry.ref.source}:${entry.ref.id}`}>
        <button
          type="button"
          aria-pressed={shown}
          aria-busy={sameRef(requested, entry.ref) && !shown}
          onClick={() => {
            if (entry.playable) {
              setRecording(entry.ref);
            } else {
              inspectEvidence(entry.ref.id);
              setFolio("record");
            }
          }}
          data-tone={status.tone}
          data-source={entry.ref.source}
          title={entry.playable ? undefined : `not playable (${entry.status}) — opens its evidence`}
        >
          <span className="lab-dot" aria-hidden="true" />
          <span className="lab-recording-label">{entry.label}</span>
          <span className="lab-recording-status">{status.text}</span>
        </button>
      </li>
    );
  };
  return (
    <section className="lab-rail-section" aria-labelledby="lab-recordings">
      <h2 id="lab-recordings" className="lab-rubric">
        Recordings <span>i</span>
      </h2>
      <ul className="lab-recordings" aria-label="Packaged recordings">
        {packaged.map(item)}
      </ul>
      {workspaceId !== null && (
        <>
          <h3 className="lab-rail-subhead">Workspace runs</h3>
          {runs.length === 0 ? (
            <p className="lab-rail-empty">No runs yet — configure and execute one in Study &amp; Runs.</p>
          ) : (
            <ul className="lab-recordings" aria-label="Workspace runs">
              {runs.map(item)}
            </ul>
          )}
        </>
      )}
    </section>
  );
}

function ModelTree() {
  const { model } = useLabData();
  const selectedBody = useLaboratoryStore((state) => state.selectedBody);
  const selectedJoint = useLaboratoryStore((state) => state.selectedJoint);
  const select = useLaboratoryStore((state) => state.select);
  const nodes = bodyTree(model);
  return (
    <section className="lab-rail-section lab-rail-tree" aria-labelledby="lab-model">
      <h2 id="lab-model" className="lab-rubric">
        Model <span>ii</span>
      </h2>
      <ul aria-label="Bodies and joints">
        {nodes.map((node) => (
          <li key={node.body.name}>
            <button
              type="button"
              style={{ paddingLeft: `${8 + node.depth * 12}px` }}
              aria-pressed={selectedBody === node.body.name}
              onClick={() => select(node.body.name, primaryJointOf(model.joints, node.body.name))}
            >
              <span>{bodyLabel(node.body.name)}</span>
              <small>
                {node.joints.length > 0
                  ? `${node.joints.length} hinge${node.joints.length === 1 ? "" : "s"}`
                  : node.body.parent === "world"
                    ? node.body.name === "pelvis"
                      ? "root · free joint"
                      : "free joint · weld + grips"
                    : "rigid to parent"}
              </small>
            </button>
            {selectedBody === node.body.name && node.joints.length > 1 && (
              <ul className="lab-tree-joints" aria-label={`Joints of ${bodyLabel(node.body.name)}`}>
                {node.joints.map((joint) => (
                  <li key={joint.name}>
                    <button
                      type="button"
                      style={{ paddingLeft: `${20 + node.depth * 12}px` }}
                      aria-pressed={selectedJoint === joint.name}
                      onClick={() => select(node.body.name, joint.name)}
                    >
                      {joint.name}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

function Layers() {
  const layers = useLaboratoryStore((state) => state.layers);
  const toggleLayer = useLaboratoryStore((state) => state.toggleLayer);
  return (
    <section className="lab-rail-section" aria-labelledby="lab-layers">
      <h2 id="lab-layers" className="lab-rubric">
        Layers <span>iii</span>
      </h2>
      <ul className="lab-layers">
        {LAYERS.map((layer) => (
          <li key={layer}>
            <button type="button" role="switch" aria-checked={layers[layer]} onClick={() => toggleLayer(layer)}>
              <span className="lab-swatch" style={{ background: LAYER_PIGMENTS[layer] }} aria-hidden="true" />
              <span>{LAYER_LABELS[layer]}</span>
              <span className="lab-switch" aria-hidden="true" />
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
