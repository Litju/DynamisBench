/**
 * The dock: up to three pinned plots of the recording, linked to the one clock.
 *
 * Each plot draws published columns. Where a plot shows a display derivation it says so in
 * its title or note: extensor moments are the published joint torques with the sign flipped
 * (extension is the negative sense of each flexion axis), the vertical ground reaction is the
 * sum of the two published foot forces over the published weight, margins are shown in mm.
 */

import { useMemo } from "react";

import type { LaboratoryFrameTable, LaboratoryRecordingResponse } from "../api/laboratory-types";
import { useLabData, useRecordingSet } from "./data";
import { entryOptionLabel } from "./entry-label";
import { findEntry, refKey, sameRef, type CatalogueEntry, type RecordingRef } from "./sources";
import { Plot, type PlotSeries } from "./plot";
import { column, combine, mapColumn } from "./series";
import { DOCK_PLOTS, MAX_PINNED, useLaboratoryStore, type DockPlot } from "./store";

export const DOCK_LABELS: Record<DockPlot, string> = {
  kinematics: "Kinematics",
  kinetics: "Kinetics",
  ground: "Ground reaction",
  balance: "Balance",
  contact: "Contact",
  energy: "Energy",
  compare: "Compare runs",
};

const negate = (values: Float64Array | undefined) => mapColumn(values, (value) => -value);
const millimetres = (values: Float64Array | undefined) => mapColumn(values, (value) => value * 1000);

/**
 * The default companion of a recording: the packaged nominal ↔ the no-internal-model ablation;
 * anything else (another packaged recording or a workspace run) ↔ the packaged nominal.
 */
export function defaultCompanion(ref: RecordingRef, entries: readonly CatalogueEntry[]): RecordingRef | null {
  const playable = entries.filter((entry) => entry.playable);
  const nominal = playable.find((entry) => entry.ref.source === "dataset" && entry.kind === "nominal")?.ref ?? null;
  if (!sameRef(ref, nominal)) {
    return nominal;
  }
  return (
    playable.find((entry) => entry.ref.source === "dataset" && entry.kind === "ablation")?.ref ??
    playable.find((entry) => !sameRef(entry.ref, ref))?.ref ??
    null
  );
}

export function Dock() {
  const pinned = useLaboratoryStore((state) => state.pinned);
  const togglePinned = useLaboratoryStore((state) => state.togglePinned);
  return (
    <section className="lab-dock" aria-label="Plots">
      <div className="lab-dock-tabs" role="toolbar" aria-label="Pinned plots">
        {DOCK_PLOTS.map((plot) => (
          <button key={plot} type="button" aria-pressed={pinned.includes(plot)} onClick={() => togglePinned(plot)}>
            {DOCK_LABELS[plot]}
          </button>
        ))}
        <span className="lab-dock-hint">
          {pinned.length} of {MAX_PINNED} plots pinned · click a plot to seek
        </span>
      </div>
      <div className="lab-dock-plots" data-count={pinned.length}>
        {pinned.map((plot) => (
          <DockPlotView key={plot} plot={plot} />
        ))}
      </div>
    </section>
  );
}

function DockPlotView({ plot }: { plot: DockPlot }) {
  if (plot === "compare") {
    return <ComparePlot />;
  }
  return <RecordingPlot plot={plot} />;
}

function RecordingPlot({ plot }: { plot: Exclude<DockPlot, "compare"> }) {
  const { recording, frames, weightN } = useLabData();
  const definition = useMemo(
    () => plotDefinition(plot, recording, frames.kinematics, frames.kinetics, weightN),
    [plot, recording, frames.kinematics, frames.kinetics, weightN],
  );
  return (
    <Plot
      title={definition.title}
      unit={definition.unit}
      t={frames.kinematics.t}
      series={definition.series}
      spans={recording.phase_spans}
      duration={frames.kinematics.t[frames.kinematics.count - 1] ?? recording.duration_s}
      digits={definition.digits}
      {...(definition.note === undefined ? {} : { note: definition.note })}
    />
  );
}

interface PlotDefinition {
  readonly title: string;
  readonly unit: string;
  readonly series: PlotSeries[];
  readonly digits: number;
  readonly note?: string;
}

export function plotDefinition(
  plot: Exclude<DockPlot, "compare">,
  recording: LaboratoryRecordingResponse,
  kinematics: LaboratoryFrameTable,
  kinetics: LaboratoryFrameTable,
  weightN: number,
): PlotDefinition {
  void recording;
  switch (plot) {
    case "kinematics":
      return {
        title: "Kinematics — joint angles",
        unit: "deg",
        digits: 1,
        series: [
          { key: "knee", label: "knee", values: column(kinematics, "knee_flexion_l.angle_deg"), color: "var(--codex-lapis)" },
          { key: "hip", label: "hip", values: column(kinematics, "hip_flexion_l.angle_deg"), color: "var(--codex-ochre)" },
          { key: "ankle", label: "ankle", values: column(kinematics, "ankle_dorsiflexion_l.angle_deg"), color: "var(--codex-verdigris)" },
          { key: "knee-ref", label: "knee ref", values: column(kinematics, "knee_flexion_l.reference_deg"), color: "var(--codex-ink-2)", dashed: true, width: 1.1 },
        ],
      };
    case "kinetics":
      return {
        title: "Kinetics — extensor moments",
        unit: "N·m",
        digits: 1,
        note: "extensor moment = −τ about each flexion axis (left side)",
        series: [
          { key: "knee", label: "knee", values: negate(column(kinetics, "knee_flexion_l.torque_nm")), color: "var(--codex-sanguine)" },
          { key: "hip", label: "hip", values: negate(column(kinetics, "hip_flexion_l.torque_nm")), color: "var(--codex-gold)" },
          { key: "lumbar", label: "lumbar", values: negate(column(kinetics, "lumbar_flexion.torque_nm")), color: "var(--codex-ink-2)", dashed: true },
          { key: "ankle", label: "ankle", values: negate(column(kinetics, "ankle_dorsiflexion_l.torque_nm")), color: "var(--codex-verdigris)" },
        ],
      };
    case "ground": {
      const vertical = combine(column(kinetics, "grf_left.z"), column(kinetics, "grf_right.z"), (a, b) => (a + b) / weightN);
      return {
        title: "Ground reaction — vertical",
        unit: "× weight",
        digits: 3,
        note: "both feet over the published weight; plan = the internal model's prediction",
        series: [
          { key: "measured", label: "measured", values: vertical, color: "var(--codex-sanguine)" },
          {
            key: "plan",
            label: "internal-model plan",
            values: mapColumn(column(kinetics, "grf_planned_vertical_n"), (value) => value / weightN),
            color: "var(--codex-ink-2)",
            dashed: true,
            width: 1.2,
          },
        ],
      };
    }
    case "balance":
      return {
        title: "Balance — margins to the loaded support polygon",
        unit: "mm",
        digits: 0,
        series: [
          { key: "cop", label: "CoP margin", values: millimetres(column(kinetics, "cop_margin_m")), color: "var(--codex-verdigris)" },
          { key: "xcom", label: "XCoM margin", values: millimetres(column(kinetics, "xcom_margin_m")), color: "var(--codex-lapis)" },
        ],
      };
    case "contact":
      return {
        title: "Contact — plantar loads, left foot",
        unit: "N",
        digits: 0,
        series: [
          { key: "heel-lateral", label: "heel lat.", values: column(kinetics, "contact.l_heel_lateral.normal_n"), color: "var(--codex-verdigris)" },
          { key: "heel-medial", label: "heel med.", values: column(kinetics, "contact.l_heel_medial.normal_n"), color: "var(--codex-verdigris)", dashed: true },
          { key: "met1", label: "met 1", values: column(kinetics, "contact.l_met1.normal_n"), color: "var(--codex-lapis)" },
          { key: "met5", label: "met 5", values: column(kinetics, "contact.l_met5.normal_n"), color: "var(--codex-lapis)", dashed: true },
          { key: "hallux", label: "hallux", values: column(kinetics, "contact.l_hallux.normal_n"), color: "var(--codex-gold)" },
        ],
      };
    case "energy":
      return {
        title: "Energy — actuator power",
        unit: "W",
        digits: 0,
        note: "Σ τ·ω over all joint actuators",
        series: [
          { key: "power", label: "actuator power", values: column(kinetics, "actuator_power_w"), color: "var(--codex-sanguine)" },
        ],
      };
  }
}

function ComparePlot() {
  const { client, entries, ref, recording, frames, workspaceId } = useLabData();
  const compare = useLaboratoryStore((state) => state.compare);
  const setCompare = useLaboratoryStore((state) => state.setCompare);
  const companionRef =
    compare !== null && !sameRef(compare, ref) && findEntry(entries, compare)?.playable === true
      ? compare
      : defaultCompanion(ref, entries);
  const companion = useRecordingSet(client, companionRef, ["kinematics"], workspaceId);
  const other = companion.tables.kinematics;
  const otherLabel = findEntry(entries, companionRef)?.label ?? "companion";
  const t = other !== undefined && other.count > frames.kinematics.count ? other.t : frames.kinematics.t;
  const series = useMemo<PlotSeries[]>(
    () => [
      { key: "this", label: "this recording", values: column(frames.kinematics, "knee_flexion_l.angle_deg"), color: "var(--codex-lapis)" },
      { key: "other", label: otherLabel, values: column(other, "knee_flexion_l.angle_deg"), color: "var(--codex-sanguine)", dashed: true },
    ],
    [frames.kinematics, other, otherLabel],
  );
  const choices = entries.filter((entry) => entry.playable && !sameRef(entry.ref, ref));
  return (
    <div className="lab-compare">
      <Plot
        title="Compare runs — knee flexion"
        unit="deg"
        control={
          <label className="lab-compare-select">
            <span>with</span>
            <select
              aria-label="Companion recording"
              value={companionRef === null ? "" : refKey(companionRef)}
              onChange={(event) => {
                const chosen = choices.find((entry) => refKey(entry.ref) === event.target.value);
                setCompare(chosen === undefined ? null : chosen.ref);
              }}
            >
              {choices.map((entry) => (
                <option key={refKey(entry.ref)} value={refKey(entry.ref)}>
                  {entryOptionLabel(entry)}
                </option>
              ))}
            </select>
          </label>
        }
        t={t}
        series={series}
        spans={recording.phase_spans}
        duration={t[t.length - 1] ?? recording.duration_s}
        digits={2}
        note={
          companion.state.status === "loading"
            ? "reading the companion recording…"
            : companion.state.status === "error"
              ? "the companion could not be read"
              : "left knee, both recordings on the same 10 ms grid"
        }
      />
    </div>
  );
}
