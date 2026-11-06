/**
 * Folio III · Analysis: the recording's published measurements, its work–energy ledger, its
 * phases, and comparisons against its companions.
 *
 * Summary cards and the ledger are the recording's published summary and work record. The
 * ledger's residual column is the same arithmetic the `ledger` criterion applies (actuator work
 * − damping − ΔE); its outcome is the published check. Comparison curves are published columns
 * of two recordings on the same 10 ms grid; where a curve is a difference of two such columns
 * it says so.
 */

import { useMemo } from "react";

import { measuredPhases, summaryNumber } from "../api/laboratory-decode";
import type { LaboratoryPhaseSpan, LaboratoryRecordingResponse } from "../api/laboratory-types";
import { useLabData, useRecordingSet } from "./data";
import { findEntry, sameRef } from "./sources";
import { useLaboratoryStore } from "./store";
import { phaseVariable, phaseWash } from "./palette";
import { Plot, type PlotSeries } from "./plot";
import { column, combine, formatNumber, mapColumn, niceTicks } from "./series";

const PHASE_ORDER = ["standing", "descent", "bottom", "ascent", "return"] as const;
const PHASE_TITLES: Record<string, string> = {
  standing: "Standing",
  descent: "Descent",
  bottom: "Bottom",
  ascent: "Ascent",
  return: "Return",
};

function span(phases: readonly LaboratoryPhaseSpan[], phase: string): number | null {
  const found = phases.find((entry) => entry.phase === phase);
  return found === undefined ? null : found.end_s - found.start_s;
}

/** The first number of a published bound ("> 20" → 20), for drawing it as a rule. */
export function boundValue(bound: string): number | null {
  const match = /[-+]?\d*\.?\d+(?:e[-+]?\d+)?/i.exec(bound);
  return match === null ? null : Number(match[0]);
}

export function AnalysisFolio() {
  const { recording, model, ref } = useLabData();
  const s = recording.summary;
  const measured = measuredPhases(s);
  const bodyMass = model.subject.body_mass_kg;
  const e = recording.extrema;
  const cards = [
    {
      key: "depth",
      pigment: "lapis",
      rubric: "Depth",
      value: formatNumber(summaryNumber(s, "bottom.knee_flexion_deg"), 1),
      unit: "° knee",
      lines: [
        `hip ${formatNumber(summaryNumber(s, "bottom.hip_flexion_deg"), 1)}°`,
        `ankle ${formatNumber(summaryNumber(s, "bottom.ankle_dorsiflexion_deg"), 1)}°`,
        `trunk ${formatNumber(summaryNumber(s, "bottom.trunk_inclination_deg"), 1)}° · spine ±${formatNumber(summaryNumber(s, "ranges.max_abs_lumbar_flexion_deg"), 1)}°`,
      ],
    },
    {
      key: "tempo",
      pigment: "lapis",
      rubric: "Tempo (measured)",
      value: formatNumber(span(measured, "descent"), 2),
      unit: "s down",
      lines: [
        `bottom ${formatNumber(span(measured, "bottom"), 2)} s · ascent ${formatNumber(span(measured, "ascent"), 2)} s`,
        `peak knee ${formatNumber(summaryNumber(s, "ranges.peak_knee_speed_descent_deg_s"), 0)} / ${formatNumber(summaryNumber(s, "ranges.peak_knee_speed_ascent_deg_s"), 0)} °/s`,
        `knee reversals ${formatNumber(summaryNumber(s, "smoothness.knee_speed_reversals_in_descent"), 0)} down · ${formatNumber(summaryNumber(s, "smoothness.knee_speed_reversals_in_ascent"), 0)} up`,
      ],
    },
    {
      key: "moments",
      pigment: "sanguine",
      rubric: "Peak moments",
      value: formatNumber(summaryNumber(s, "torques.knee_flexion_l.peak_extensor_nm"), 0),
      unit: "N·m knee",
      lines: [
        `${formatNumber(summaryNumber(s, "torques.knee_flexion_l.peak_extensor_nm_per_kg"), 2)} N·m/kg (per ${formatNumber(bodyMass, 0)} kg)`,
        `hip ${formatNumber(summaryNumber(s, "torques.hip_flexion_l.peak_extensor_nm"), 0)} N·m · ankle ${formatNumber(summaryNumber(s, "torques.ankle_dorsiflexion_l.peak_extensor_nm"), 0)} N·m`,
        `lumbar ${formatNumber(summaryNumber(s, "torques.lumbar_flexion.peak_extensor_nm"), 0)} N·m`,
      ],
    },
    {
      key: "ground",
      pigment: "sanguine",
      rubric: "Ground reaction",
      value: formatNumber(summaryNumber(s, "ground_reaction.max_vertical_over_weight"), 2),
      unit: "× weight",
      lines: [
        `min ${formatNumber(summaryNumber(s, "ground_reaction.min_vertical_over_weight"), 2)} × W · mean ${formatNumber(summaryNumber(s, "ground_reaction.mean_vertical_over_weight"), 4)} × W`,
        `plan error ${formatNumber((summaryNumber(s, "ground_reaction.planned_minus_measured_rms_over_weight") ?? Number.NaN) * 100, 1)} % W RMS`,
        `shear ≤ ${formatNumber((summaryNumber(s, "ground_reaction.max_shear_over_vertical") ?? Number.NaN) * 100, 1)} % of vertical`,
      ],
    },
    {
      key: "balance",
      pigment: "verdigris",
      rubric: "Balance",
      value: formatNumber((summaryNumber(s, "balance.min_cop_margin_m") ?? Number.NaN) * 1000, 0),
      unit: "mm CoP",
      lines: [
        `XCoM margin ≥ ${formatNumber((summaryNumber(s, "balance.min_xcom_margin_m") ?? Number.NaN) * 1000, 0)} mm`,
        `bar travel ${formatNumber((summaryNumber(s, "barbell.vertical_travel_m") ?? Number.NaN) * 1000, 0)} mm · drift ${formatNumber((summaryNumber(s, "barbell.horizontal_range_m") ?? Number.NaN) * 1000, 0)} mm`,
        `CoM drop ${formatNumber((summaryNumber(s, "energy.com_drop_m") ?? Number.NaN) * 1000, 0)} mm`,
      ],
    },
    {
      key: "contact",
      pigment: "verdigris",
      rubric: "Contact",
      value: `${formatNumber(e.min_loaded_sole_contacts, 0)}/${2 * model.sole_points.length}`,
      unit: "loaded",
      lines: [
        `min point load ${formatNumber(e.min_contact_point_load_n, 0)} N`,
        `slip ${formatNumber((e.max_sole_point_slip_m ?? Number.NaN) * 1000, 2)} mm · friction use ≤ ${formatNumber((e.max_friction_utilization ?? Number.NaN) * 100, 0)} %`,
        `heel share ≥ ${formatNumber((e.min_heel_load_fraction_per_foot ?? Number.NaN) * 100, 1)} % per foot`,
      ],
    },
  ];

  return (
    <div className="lab-folio lab-analysis">
      <header className="lab-folio-head">
        <h2 className="lab-plate-title">Quantitative analysis of the {ref.source === "run" ? "run" : "recording"}</h2>
        <p className="lab-marginal">
          every value is sampled from synchronized snapshots of the MuJoCo simulation and{" "}
          {ref.source === "run" ? "read from the run's sealed, re-verified evidence" : "published by the dataset"} · bounds are the predeclared
          criteria
        </p>
      </header>
      <div className="lab-summary-cards">
        {cards.map((card) => (
          <article key={card.key} className="lab-summary-card" data-pigment={card.pigment} aria-label={card.rubric}>
            <h3 className="lab-rubric">{card.rubric}</h3>
            <p className="lab-summary-value">
              <strong>{card.value}</strong> <span>{card.unit}</span>
            </p>
            <ul>
              {card.lines.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </article>
        ))}
      </div>
      <div className="lab-analysis-middle">
        <Ledger recording={recording} />
        <PhaseRegister recording={recording} />
      </div>
      <Comparisons />
    </div>
  );
}

function Ledger({ recording }: { recording: LaboratoryRecordingResponse }) {
  const rows = PHASE_ORDER.flatMap((phase) => {
    const work = recording.work[phase];
    if (work === undefined) {
      return [];
    }
    const positive = work.positive_j ?? Number.NaN;
    const negative = work.negative_j ?? Number.NaN;
    const damping = work.damping_dissipation_j ?? Number.NaN;
    const change = work.mechanical_energy_change_j ?? Number.NaN;
    return [{ phase, positive, negative, damping, change, residual: positive + negative - damping - change }];
  });
  const total = rows.reduce(
    (sum, row) => ({
      positive: sum.positive + row.positive,
      negative: sum.negative + row.negative,
      damping: sum.damping + row.damping,
      change: sum.change + row.change,
      residual: sum.residual + row.residual,
    }),
    { positive: 0, negative: 0, damping: 0, change: 0, residual: 0 },
  );
  const check = recording.checks.find((entry) => entry.criterion_id === "ledger");
  const j = (value: number) => `${formatNumber(value, 2, true)} J`;
  return (
    <section className="lab-card lab-ledger" aria-labelledby="ledger-title">
      <h3 id="ledger-title" className="lab-card-title lab-display">
        Ledger of work and energy
      </h3>
      <p className="lab-marginal">per phase, double entry: actuator work − damping dissipation = change of mechanical energy</p>
      <table className="lab-table">
        <thead>
          <tr>
            <th scope="col">Phase</th>
            <th scope="col" className="num">Actuator +</th>
            <th scope="col" className="num">Actuator −</th>
            <th scope="col" className="num">Damping</th>
            <th scope="col" className="num">ΔE mechanical</th>
            <th scope="col" className="num">Residual</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.phase}>
              <th scope="row">
                <span className="lab-phase-swatch" style={{ background: phaseVariable(row.phase) }} aria-hidden="true" />
                {PHASE_TITLES[row.phase] ?? row.phase}
              </th>
              <td className="num">{j(row.positive)}</td>
              <td className="num">{j(row.negative)}</td>
              <td className="num">{j(row.damping)}</td>
              <td className="num">{j(row.change)}</td>
              <td className="num">{j(row.residual)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <th scope="row">Summa</th>
            <td className="num">{j(total.positive)}</td>
            <td className="num">{j(total.negative)}</td>
            <td className="num">{j(total.damping)}</td>
            <td className="num">{j(total.change)}</td>
            <td className="num">{j(total.residual)}</td>
          </tr>
        </tfoot>
      </table>
      {check !== undefined && (
        <p className="lab-ledger-seal" data-status={check.status}>
          <Seal status={check.status} /> {check.label}: {formatNumber(check.value, 3)} {check.unit} (bound {check.bound}) —{" "}
          {check.status === "pass" ? "balances" : check.status === "fail" ? "does not balance" : "not evaluated"}
        </p>
      )}
    </section>
  );
}

export function Seal({ status }: { status: "pass" | "fail" | "not_evaluated" }) {
  return (
    <svg className="lab-seal" data-status={status} viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
      <circle cx="10" cy="10" r="8.2" />
      <circle cx="10" cy="10" r="5.6" className="lab-seal-inner" />
      {status === "pass" ? (
        <path d="M6.6 10.2l2.3 2.3 4.6-4.8" />
      ) : status === "fail" ? (
        <path d="M7 7l6 6M13 7l-6 6" />
      ) : (
        <path d="M6.5 10h7" />
      )}
    </svg>
  );
}

function PhaseRegister({ recording }: { recording: LaboratoryRecordingResponse }) {
  const measured = measuredPhases(recording.summary);
  const duration = recording.duration_s;
  const ticks = niceTicks(0, duration, 6).filter((tick) => Number.isInteger(tick));
  const left = (value: number) => `${(value / duration) * 100}%`;
  const strip = (spans: readonly LaboratoryPhaseSpan[], close: number) => (
    <div className="lab-register-strip">
      {spans.map((entry, i) => {
        const name = entry.phase === "return" ? "standing" : entry.phase;
        // A boundary close to the previous one gets its time label above the strip, so two
        // labels never overprint; a phase too short for its name clips it (the title has it).
        const crowded = i > 0 && entry.start_s - (spans[i - 1]?.start_s ?? 0) < 0.09 * duration;
        return (
          <span
            key={`${entry.phase}-${entry.start_s}`}
            title={`${name}: ${formatNumber(entry.start_s, 2)}–${formatNumber(entry.end_s, 2)} s`}
            style={{ left: left(entry.start_s), width: `calc(${left(Math.min(duration, entry.end_s + close))} - ${left(entry.start_s)})`, background: phaseWash(entry.phase, 46) }}
          >
            <b>{name}</b>
            <em data-crowded={crowded}>{formatNumber(entry.start_s, 2)}</em>
          </span>
        );
      })}
    </div>
  );
  return (
    <section className="lab-card lab-register" aria-labelledby="register-title">
      <h3 id="register-title" className="lab-card-title lab-display">
        Phases — commanded and measured
      </h3>
      <p className="lab-marginal">commanded transitions fire on measured state; measured phases are segmented from the motion alone</p>
      <div className="lab-register-row">
        <span className="lab-register-label">commanded</span>
        {strip(recording.phase_spans, recording.sample_period_s)}
      </div>
      <div className="lab-register-row">
        <span className="lab-register-label">measured</span>
        {strip(measured, 0)}
      </div>
      <div className="lab-register-row lab-register-axis" aria-hidden="true">
        <span className="lab-register-label" />
        <div className="lab-register-strip">
          {ticks.map((tick) => (
            <i key={tick} style={{ left: left(tick) }}>
              {tick} s
            </i>
          ))}
        </div>
      </div>
      <p className="lab-register-note">
        measured descent {formatNumber(span(measured, "descent"), 2)} s · bottom {formatNumber(span(measured, "bottom"), 2)} s · ascent{" "}
        {formatNumber(span(measured, "ascent"), 2)} s
      </p>
    </section>
  );
}

function Comparisons() {
  const { client, entries, ref, recording, frames, weightN, workspaceId } = useLabData();
  const compare = useLaboratoryStore((state) => state.compare);
  const dataset = entries.filter((entry) => entry.playable && entry.ref.source === "dataset");
  const nominal = dataset.find((entry) => entry.kind === "nominal")?.ref ?? null;
  const ablation = dataset.find((entry) => entry.kind === "ablation" && !sameRef(entry.ref, ref))?.ref ?? null;
  const companion = dataset.find((entry) => entry.kind === "timestep-companion")?.ref ?? null;
  const isNominal = sameRef(ref, nominal);
  const chosen = compare !== null && !sameRef(compare, ref) && findEntry(entries, compare)?.playable === true ? compare : null;
  const otherRef = chosen ?? (isNominal ? ablation : nominal);
  const other = useRecordingSet(client, otherRef, ["kinematics", "kinetics"], workspaceId);
  const fine = useRecordingSet(client, isNominal && chosen === null ? companion : null, ["kinematics"], workspaceId);
  const otherLabel = findEntry(entries, otherRef)?.label ?? "companion";
  const heelCheck = recording.checks.find((entry) => entry.criterion_id === "heel");
  const heelBound = heelCheck === undefined ? null : boundValue(heelCheck.bound);
  const duration = frames.kinematics.t[frames.kinematics.count - 1] ?? recording.duration_s;

  const heel = useMemo<PlotSeries[]>(
    () => [
      { key: "this", label: recording.label, values: mapColumn(column(frames.kinetics, "heel_load_fraction"), (v) => v * 100), color: "var(--codex-verdigris)" },
      { key: "other", label: otherLabel, values: mapColumn(column(other.tables.kinetics, "heel_load_fraction"), (v) => v * 100), color: "var(--codex-sanguine)" },
    ],
    [frames.kinetics, other.tables.kinetics, recording.label, otherLabel],
  );
  const planError = (kinetics: typeof frames.kinetics | undefined) =>
    combine(
      combine(column(kinetics, "grf_left.z"), column(kinetics, "grf_right.z"), (a, b) => a + b),
      column(kinetics, "grf_planned_vertical_n"),
      (measured, planned) => ((measured - planned) / weightN) * 100,
    );
  const plan = useMemo<PlotSeries[]>(
    () => [
      { key: "this", label: recording.label, values: planError(frames.kinetics), color: "var(--codex-verdigris)" },
      { key: "other", label: otherLabel, values: planError(other.tables.kinetics), color: "var(--codex-sanguine)" },
    ],
    // planError reads only its argument and the published weight.
    [frames.kinetics, other.tables.kinetics, recording.label, otherLabel, weightN],
  );
  const timestepStudy = isNominal && chosen === null;
  const knee = useMemo<PlotSeries[]>(
    () => [
      {
        key: "difference",
        label: timestepStudy ? "knee: dt 1 ms − dt 0.5 ms" : `knee: this − ${otherLabel}`,
        values: timestepStudy
          ? mapColumn(
              combine(column(frames.kinematics, "knee_flexion_l.angle_deg"), column(fine.tables.kinematics, "knee_flexion_l.angle_deg"), (a, b) => a - b),
              (v) => v * 1000,
            )
          : combine(column(frames.kinematics, "knee_flexion_l.angle_deg"), column(other.tables.kinematics, "knee_flexion_l.angle_deg"), (a, b) => a - b),
        color: "var(--codex-lapis)",
      },
    ],
    [frames.kinematics, fine.tables.kinematics, other.tables.kinematics, timestepStudy, otherLabel],
  );
  const maxKnee = recording.numerics.max_knee_angle_difference_deg;

  return (
    <section className="lab-comparisons" aria-label="Comparisons">
      <Plot
        title="Compare runs — heel load share (lesser foot)"
        unit="%"
        t={frames.kinetics.t}
        series={heel}
        spans={recording.phase_spans}
        duration={duration}
        digits={1}
        {...(heelBound === null || heelCheck === undefined ? {} : { bound: { value: heelBound, label: `bound ${heelCheck.bound} ${heelCheck.unit}` } })}
        note={other.state.status === "loading" ? "reading the companion…" : `published heel_load_fraction of both recordings`}
      />
      <Plot
        title="Compare runs — measured − planned vertical GRF"
        unit="% weight"
        t={frames.kinetics.t}
        series={plan}
        spans={recording.phase_spans}
        duration={duration}
        digits={2}
        note="difference of two published columns, over the published weight"
      />
      {timestepStudy ? (
        <Plot
          title="Timestep study — knee angle difference"
          unit="millidegree"
          t={frames.kinematics.t}
          series={knee}
          spans={recording.phase_spans}
          duration={duration}
          digits={1}
          note={`difference of two published columns; the published maximum is ${formatNumber((maxKnee ?? Number.NaN) * 1000, 1)} millidegree`}
        />
      ) : (
        <Plot
          title="Compare runs — knee angle difference"
          unit="deg"
          t={frames.kinematics.t}
          series={knee}
          spans={recording.phase_spans}
          duration={duration}
          digits={2}
          note={
            other.state.status === "error"
              ? "the compared recording could not be read"
              : `this − ${otherLabel}, left knee, on the shared 10 ms grid (rows beyond the shorter recording are not drawn)`
          }
        />
      )}
    </section>
  );
}
