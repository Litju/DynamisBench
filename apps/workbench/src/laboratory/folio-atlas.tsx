/**
 * Folio II · Model Atlas: the compiled model as a lettered plate.
 *
 * The figures are engravings of the recording's first frame (the standing keyframe the
 * repetition starts from), frontal and sagittal; the legend, joint and contact tables are the
 * published model. Selecting a letter or a row selects that segment everywhere.
 */

import { useMemo } from "react";

import type { LaboratoryJoint, LaboratoryModelResponse } from "../api/laboratory-types";
import { bodyLabel, jointName } from "./anatomy";
import { useLabData } from "./data";
import { bodyPose, engrave, projectPoint, type EngravedItem, type OrthoView } from "./engraving";
import { at, column, formatNumber, shortDigest } from "./series";
import { primaryJointOf } from "./stage/stage";
import { useLaboratoryStore } from "./store";

/** Plate letters, in the Renaissance manner (no J). */
export const PLATE_LETTERS: readonly { letter: string; body: string; label: string }[] = [
  { letter: "A", body: "head", label: "Head & neck" },
  { letter: "B", body: "torso_upper", label: "Upper trunk" },
  { letter: "C", body: "torso_middle", label: "Middle trunk" },
  { letter: "D", body: "pelvis", label: "Pelvis (lower trunk)" },
  { letter: "E", body: "upper_arm_l", label: "Upper arm" },
  { letter: "F", body: "forearm_l", label: "Forearm" },
  { letter: "G", body: "hand_l", label: "Hand" },
  { letter: "H", body: "thigh_l", label: "Thigh" },
  { letter: "I", body: "shank_l", label: "Shank" },
  { letter: "K", body: "foot_l", label: "Foot" },
  { letter: "L", body: "barbell", label: "Barbell" },
];

export function AtlasFolio() {
  const { model, frames } = useLabData();
  const selectedBody = useLaboratoryStore((state) => state.selectedBody);
  const select = useLaboratoryStore((state) => state.select);
  const chooseBody = (body: string) => select(body, primaryJointOf(model.joints, body));
  const athleteBodies = model.bodies.filter((body) => body.name !== "barbell").length;
  const bar = model.bodies.find((body) => body.name === "barbell");

  return (
    <div className="lab-folio lab-atlas">
      <section className="lab-plate" aria-labelledby="atlas-title">
        <p className="lab-tabula">Tabula I</p>
        <h2 id="atlas-title" className="lab-plate-title">
          The athlete and the bar, in the standing keyframe
        </h2>
        <p className="lab-plate-sub">
          {formatNumber(model.subject.body_mass_kg, 0)} kg · {formatNumber(model.subject.stature_m, 3)} m · {athleteBodies} segments ·{" "}
          {model.joints.length} hinges · {model.counts.nu ?? "—"} torque actuators · {formatNumber(bar?.mass_kg ?? model.subject.barbell_mass_kg, 0)} kg IWF barbell, high-bar
        </p>
        <div className="lab-atlas-figures">
          <Figure
            kind="frontal"
            model={model}
            selectedBody={selectedBody}
            onSelect={chooseBody}
            caption="frontal — with the Vitruvian circle and square of the stature"
          />
          <Figure
            kind="sagittal"
            model={model}
            selectedBody={selectedBody}
            onSelect={chooseBody}
            caption="sagittal — recorded heights, CoM plumb over the mid-foot"
          />
        </div>
        <Sources modelDigest={model.model_sha256} />
      </section>
      <section className="lab-atlas-tables" aria-label="Model tables">
        <LegendTable model={model} selectedBody={selectedBody} onSelect={chooseBody} />
        <JointTable joints={model.joints} />
        <ContactCards model={model} />
        <p className="lab-folio-foot">
          model {shortDigest(model.model_sha256)} · nq {model.counts.nq} · nv {model.counts.nv} · nu {model.counts.nu} · {model.counts.nbody} bodies ·{" "}
          {model.counts.neq} equality constraints · {model.counts.npair} contact pairs · dt {formatNumber(model.timestep_s * 1000, 1)} ms ·{" "}
          {model.integrator} · frame {frames.pose.count > 0 ? "0" : "—"}
        </p>
      </section>
    </div>
  );
}

function Figure({
  kind,
  model,
  selectedBody,
  onSelect,
  caption,
}: {
  kind: "frontal" | "sagittal";
  model: LaboratoryModelResponse;
  selectedBody: string | null;
  onSelect: (body: string) => void;
  caption: string;
}) {
  const { frames } = useLabData();
  const pose = frames.pose;
  const stature = model.subject.stature_m;
  const width = kind === "frontal" ? 560 : 420;
  const height = 520;
  const scale = 262;
  const comX = at(column(frames.kinematics, "com.x"), 0);
  const view: OrthoView = {
    azimuth: kind === "frontal" ? 0 : -90,
    elevation: 0,
    scale,
    origin: [kind === "frontal" ? width / 2 : width / 2 - 40, height - 40],
    target: [Number.isFinite(comX) ? comX : 0.05, 0, 0],
  };
  const items = useMemo(() => engrave(model, pose, 0, view), [model, pose, kind]); // the view is a function of kind
  const floor = projectPoint(view, [view.target[0], 0, 0]);
  const letters = kind === "frontal" ? placeLetters(model, frames.pose, view, width) : [];

  const heights =
    kind === "sagittal"
      ? [
          { label: "bar", z: at(column(frames.kinematics, "bar.z"), 0) },
          { label: "CoM", z: at(column(frames.kinematics, "com.z"), 0) },
          { label: "hip", z: at(column(pose, "thigh_l.pz"), 0) },
          { label: "knee", z: at(column(pose, "shank_l.pz"), 0) },
          { label: "ankle", z: at(column(pose, "foot_l.pz"), 0) },
        ]
      : [];
  const com = projectPoint(view, [
    at(column(frames.kinematics, "com.x"), 0),
    at(column(frames.kinematics, "com.y"), 0),
    at(column(frames.kinematics, "com.z"), 0),
  ]);

  return (
    <figure className="lab-engraving" data-view={kind}>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${kind} view of the standing keyframe`}>
        <defs>
          <radialGradient id={`bone-${kind}`} cx="38%" cy="32%" r="75%">
            <stop offset="0" className="stop-light" />
            <stop offset="0.55" className="stop-mid" />
            <stop offset="1" className="stop-dark" />
          </radialGradient>
        </defs>
        {kind === "frontal" && (
          <g className="lab-vitruvian">
            <rect x={width / 2 - (stature * scale) / 2} y={floor[1] - stature * scale} width={stature * scale} height={stature * scale} />
            <circle cx={width / 2} cy={floor[1] - (stature * scale) / 2} r={(stature * scale) / 2} />
          </g>
        )}
        <line className="lab-engraving-floor" x1={16} x2={width - 16} y1={floor[1]} y2={floor[1]} />
        {items.map((item) => (
          <EngravedShape key={item.geom} item={item} gradient={`bone-${kind}`} selected={item.body === selectedBody} onSelect={onSelect} />
        ))}
        {kind === "sagittal" && (
          <g className="lab-heights">
            <line className="lab-plumb" x1={com[0]} x2={com[0]} y1={com[1]} y2={floor[1]} />
            <circle className="lab-com-mark" cx={com[0]} cy={com[1]} r={6} />
            {heights.map((entry, i) => {
              const y = floor[1] - entry.z * scale;
              const x = width - 196 + i * 22;
              return Number.isFinite(entry.z) ? (
                <g key={entry.label}>
                  <line x1={x} x2={x} y1={floor[1]} y2={y} />
                  <line x1={x - 5} x2={x + 5} y1={y} y2={y} />
                  <text x={x + 7} y={y + 3}>
                    {entry.label} {formatNumber(entry.z, 3)} m
                  </text>
                </g>
              ) : null;
            })}
          </g>
        )}
        {letters.map((entry) => (
          <g
            key={entry.letter}
            className="lab-letter"
            data-selected={entry.body === selectedBody}
            onClick={() => onSelect(entry.body)}
          >
            <line x1={entry.anchor[0]} y1={entry.anchor[1]} x2={entry.position[0]} y2={entry.position[1]} />
            <circle cx={entry.anchor[0]} cy={entry.anchor[1]} r={2.4} className="lab-letter-anchor" />
            <circle cx={entry.position[0]} cy={entry.position[1]} r={10} />
            <text x={entry.position[0]} y={entry.position[1] + 4} textAnchor="middle">
              {entry.letter}
            </text>
          </g>
        ))}
      </svg>
      <figcaption>{caption}</figcaption>
    </figure>
  );
}

function EngravedShape({
  item,
  gradient,
  selected,
  onSelect,
}: {
  item: EngravedItem;
  gradient: string;
  selected: boolean;
  onSelect: (body: string) => void;
}) {
  const className = `lab-geom lab-geom-${item.role}${selected ? " is-selected" : ""}${item.body.endsWith("_r") ? " is-far" : ""}`;
  const onClick = () => onSelect(item.body);
  switch (item.kind) {
    case "segment":
      return (
        <g className={className} onClick={onClick}>
          <line className="lab-geom-edge" x1={item.a[0]} y1={item.a[1]} x2={item.b[0]} y2={item.b[1]} strokeWidth={item.width + 2.2} strokeLinecap={item.round ? "round" : "butt"} />
          <line className="lab-geom-body" x1={item.a[0]} y1={item.a[1]} x2={item.b[0]} y2={item.b[1]} strokeWidth={item.width} strokeLinecap={item.round ? "round" : "butt"} />
        </g>
      );
    case "ellipse":
      return (
        <ellipse
          className={className}
          cx={item.cx}
          cy={item.cy}
          rx={item.rx}
          ry={item.ry}
          transform={`rotate(${item.angle.toFixed(2)} ${item.cx.toFixed(2)} ${item.cy.toFixed(2)})`}
          fill={`url(#${gradient})`}
          onClick={onClick}
        />
      );
    case "polygon":
      return <polygon className={className} points={item.points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ")} onClick={onClick} />;
    case "dot":
      return <circle className={`${className} lab-geom-dot`} cx={item.cx} cy={item.cy} r={item.r} />;
  }
}

/** Letters on the frontal figure: leader from each segment's CoM to a margin, spaced apart. */
function placeLetters(
  model: LaboratoryModelResponse,
  pose: ReturnType<typeof useLabData>["frames"]["pose"],
  view: OrthoView,
  width: number,
) {
  const placed: { letter: string; body: string; anchor: [number, number]; position: [number, number] }[] = [];
  for (const entry of PLATE_LETTERS) {
    const body = model.bodies.find((candidate) => candidate.name === entry.body);
    const world = bodyPose(pose, entry.body, 0);
    if (body === undefined || world === null) {
      continue;
    }
    const r = world.rotation;
    const c = body.com_m;
    const com = [
      world.position[0] + r[0] * c[0] + r[1] * c[1] + r[2] * c[2],
      world.position[1] + r[3] * c[0] + r[4] * c[1] + r[5] * c[2],
      world.position[2] + r[6] * c[0] + r[7] * c[1] + r[8] * c[2],
    ];
    const [x, y] = projectPoint(view, com);
    const right = x > width / 2 + 4 || entry.body === "barbell";
    placed.push({
      letter: entry.letter,
      body: entry.body,
      anchor: [entry.body === "barbell" ? x + 200 : x, y],
      position: [right ? width - 24 : 24, y],
    });
  }
  // Keep letters on each side at least 26 px apart.
  for (const side of [24, width - 24]) {
    const column = placed.filter((entry) => entry.position[0] === side).sort((a, b) => a.position[1] - b.position[1]);
    for (let i = 1; i < column.length; i += 1) {
      const previous = column[i - 1]!;
      const current = column[i]!;
      if (current.position[1] - previous.position[1] < 26) {
        current.position = [current.position[0], previous.position[1] + 26];
      }
    }
  }
  return placed;
}

function LegendTable({
  model,
  selectedBody,
  onSelect,
}: {
  model: LaboratoryModelResponse;
  selectedBody: string | null;
  onSelect: (body: string) => void;
}) {
  return (
    <section className="lab-card" aria-labelledby="atlas-legend">
      <h3 id="atlas-legend" className="lab-rubric">
        Legend — segment inertia (de Leva 1996) <span>A–L</span>
      </h3>
      <table className="lab-table">
        <thead>
          <tr>
            <th scope="col" aria-label="Letter" />
            <th scope="col">Segment</th>
            <th scope="col" className="num">Mass kg</th>
            <th scope="col" className="num">CoM z m</th>
            <th scope="col" className="num">Ixx</th>
            <th scope="col" className="num">Iyy</th>
            <th scope="col" className="num">Izz kg·m²</th>
          </tr>
        </thead>
        <tbody>
          {PLATE_LETTERS.map((entry) => {
            const body = model.bodies.find((candidate) => candidate.name === entry.body);
            if (body === undefined) {
              return null;
            }
            return (
              <tr key={entry.letter} data-selected={selectedBody === body.name}>
                <td>
                  <button type="button" className="lab-letter-button" aria-label={`Select ${entry.label}`} aria-pressed={selectedBody === body.name} onClick={() => onSelect(body.name)}>
                    {entry.letter}
                  </button>
                </td>
                <th scope="row">{entry.body === "barbell" ? `${entry.label} · ${formatNumber(body.mass_kg, 0)} kg` : entry.label}</th>
                <td className="num">{formatNumber(body.mass_kg, 4)}</td>
                <td className="num">{formatNumber(body.com_m[2], 4, true)}</td>
                {body.principal_inertia_kg_m2.map((value, i) => (
                  <td key={i} className="num">
                    {formatNumber(value, 4)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="lab-table-note">
        Total {formatNumber(model.total_mass_kg, 4)} kg (athlete {formatNumber(model.subject.body_mass_kg, 4)} + bar{" "}
        {formatNumber(model.subject.barbell_mass_kg, 4)}) — read from the compiled model
      </p>
    </section>
  );
}

/** One row per joint of the left side and of the axial chain (the right side mirrors it). */
export function atlasJoints(joints: readonly LaboratoryJoint[]): LaboratoryJoint[] {
  return joints.filter((joint) => !joint.name.endsWith("_r"));
}

function JointTable({ joints }: { joints: readonly LaboratoryJoint[] }) {
  const rows = atlasJoints(joints);
  const maxCapacity = Math.max(...joints.flatMap((joint) => [...joint.torque_capacity_nm]));
  const rom = (value: number) => `${((value + 180) / 360) * 100}%`;
  return (
    <section className="lab-card" aria-labelledby="atlas-joints">
      <h3 id="atlas-joints" className="lab-rubric">
        Joints — range of motion and torque capacity <span>{joints.length}</span>
      </h3>
      <table className="lab-table lab-joint-table">
        <thead>
          <tr>
            <th scope="col">Joint</th>
            <th scope="col">Range of motion −180° … 180°</th>
            <th scope="col">Capacity N·m (− | +)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((joint) => {
            const [low, high] = joint.range_deg;
            const [negative, positive] = joint.torque_capacity_nm;
            return (
              <tr key={joint.name}>
                <th scope="row">{jointName(joint.name).short}</th>
                <td>
                  <div className="lab-rom" aria-label={`${formatNumber(low, 0)} to ${formatNumber(high, 0)} degrees`}>
                    <span className="lab-rom-zero" />
                    <span className="lab-rom-bar" style={{ left: rom(low), width: `calc(${rom(high)} - ${rom(low)})` }} />
                    <em style={{ left: rom(low) }}>{formatNumber(low, 0)}</em>
                    <em style={{ left: rom(high) }}>{formatNumber(high, 0)}</em>
                  </div>
                </td>
                <td>
                  <div className="lab-cap" aria-label={`${formatNumber(negative, 0)} and ${formatNumber(positive, 0)} newton metres`}>
                    <span className="lab-cap-neg" style={{ width: `${(negative / maxCapacity) * 50}%` }} />
                    <span className="lab-cap-pos" style={{ width: `${(positive / maxCapacity) * 50}%` }} />
                    <em className="neg">{formatNumber(negative, 0)}</em>
                    <em className="pos">{formatNumber(positive, 0)}</em>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}

function ContactCards({ model }: { model: LaboratoryModelResponse }) {
  const contact = model.contact;
  const soles = model.geoms.filter((geom) => geom.role === "sole").length;
  return (
    <section className="lab-cards" aria-label="Contact, coupling and actuation">
      <article className="lab-card">
        <h3 className="lab-card-title">Plantar contact</h3>
        <ul>
          <li>
            {soles / 2} spheres per foot · r {formatNumber(contact.sole_point_radius_m * 1000, 0)} mm
          </li>
          <li>μ {formatNumber(contact.friction[0], 2)} · elliptic cone · no-slip</li>
          <li>
            normal time constant {formatNumber(contact.normal_time_constant_s * 1000, 0)} ms · friction{" "}
            {formatNumber(contact.friction_time_constant_s * 1000, 0)} ms
          </li>
          <li>load-bearing above {formatNumber(contact.loaded_threshold_n, 0)} N</li>
        </ul>
      </article>
      <article className="lab-card">
        <h3 className="lab-card-title">Barbell coupling</h3>
        <ul>
          <li>weld: bar centre → upper-trunk shelf</li>
          <li>connect: each hand → grip (±{formatNumber(model.subject.grip_half_width_m, 2)} m)</li>
          <li>{model.counts.neq} equality constraints · reported forces</li>
          <li>no self-collision</li>
        </ul>
      </article>
      <article className="lab-card">
        <h3 className="lab-card-title">Actuation</h3>
        <ul>
          <li>{model.counts.nu} joint torque generators</li>
          <li>asymmetric capacities (table above)</li>
          <li>{bodyLabel("pelvis")} root: free, unactuated</li>
          <li>dt {formatNumber(model.timestep_s * 1000, 1)} ms · {model.integrator}</li>
        </ul>
      </article>
    </section>
  );
}

function Sources({ modelDigest }: { modelDigest: string }) {
  return (
    <section className="lab-sources" aria-labelledby="atlas-sources">
      <h3 id="atlas-sources" className="lab-rubric">
        Sources of the plate
      </h3>
      <ul>
        <li>Segment mass, centre of mass and radii of gyration — de Leva P. (1996) J. Biomech. 29:1223–1230, males.</li>
        <li>Vertical landmarks — Drillis &amp; Contini (1966) via Winter (2009) Fig. 4.1 · hip joint centres — Bell et al. (1990).</li>
        <li>Joint ranges — AAOS (Greene &amp; Heckman 1994); weight-bearing dorsiflexion — Bennell et al. (1998).</li>
        <li>Barbell — IWF Technical and Competition Rules, men&apos;s bar: 2.20 m, Ø28 mm shaft, Ø50 mm sleeves, 20 kg.</li>
        <li>
          Generated MJCF, SHA-256 pinned: <code>{modelDigest}</code>
        </li>
      </ul>
    </section>
  );
}
