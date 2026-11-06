/**
 * The inspector: the selected joint within its range, its segment, and the plantar load map.
 *
 * Every number is the current frame of a published column or a published model property. The
 * tracking error is the published angle minus the published reference (a display difference);
 * the dial's arc is the joint's published range of motion.
 */

import type { LaboratoryJoint } from "../api/laboratory-types";
import { axisLabel, bodyLabel, jointName } from "./anatomy";
import { useLabData } from "./data";
import { at, column, formatNumber, niceTicks } from "./series";
import { useLaboratoryStore } from "./store";

export function Inspector() {
  const { model } = useLabData();
  const selectedJoint = useLaboratoryStore((state) => state.selectedJoint);
  const selectedBody = useLaboratoryStore((state) => state.selectedBody);
  const joint = model.joints.find((entry) => entry.name === selectedJoint) ?? null;
  const body = model.bodies.find((entry) => entry.name === (joint?.body ?? selectedBody)) ?? null;

  return (
    <aside className="lab-inspector" aria-label="Inspector">
      <h2 className="lab-rubric">Inspector — {joint === null ? "selected segment" : "selected joint"}</h2>
      {joint !== null ? <JointPanel joint={joint} /> : <FreeBody name={body?.name ?? null} />}
      {body !== null && (
        <section className="lab-inspector-section" aria-label="Segment">
          <h3 className="lab-rubric">Segment — {bodyLabel(body.name)}</h3>
          <dl className="lab-facts">
            <div>
              <dt>Mass</dt>
              <dd>{formatNumber(body.mass_kg, 4)} kg</dd>
            </div>
            <div>
              <dt>CoM in body frame</dt>
              <dd>{body.com_m.map((value) => formatNumber(value, 3)).join(" · ")} m</dd>
            </div>
            <div>
              <dt>Principal inertia</dt>
              <dd>{body.principal_inertia_kg_m2.map((value) => formatNumber(value, 4)).join(" · ")} kg·m²</dd>
            </div>
          </dl>
          <p className="lab-source">
            {body.name === "barbell"
              ? "IWF men's bar: 20 kg, coaxial cylinders"
              : "de Leva (1996), male; scaled to 75 kg · 1.75 m"}
          </p>
        </section>
      )}
      <PlantarMap />
    </aside>
  );
}

function FreeBody({ name }: { name: string | null }) {
  return (
    <div className="lab-inspector-joint">
      <p className="lab-joint-title">{name === null ? "Nothing selected" : bodyLabel(name)}</p>
      <p className="lab-joint-sub">
        {name === "pelvis"
          ? "root of the tree · six-degree-of-freedom free joint, unactuated"
          : name === "barbell"
            ? "free body · welded to the upper-trunk shelf, connected at both grips"
            : "select a joint in the model tree or on the stage"}
      </p>
    </div>
  );
}

function JointPanel({ joint }: { joint: LaboratoryJoint }) {
  const { frames } = useLabData();
  const frame = useLaboratoryStore((state) => state.frame);
  const kinematics = frames.kinematics;
  const kinetics = frames.kinetics;
  const name = jointName(joint.name);
  const angle = at(column(kinematics, `${joint.name}.angle_deg`), frame);
  const reference = at(column(kinematics, `${joint.name}.reference_deg`), frame);
  const velocity = at(column(kinematics, `${joint.name}.velocity_deg_s`), frame);
  const torque = at(column(kinetics, `${joint.name}.torque_nm`), frame);
  const activation = at(column(kinetics, "activation_max"), frame);
  const [negativeCapacity, positiveCapacity] = joint.torque_capacity_nm;

  return (
    <section className="lab-inspector-joint" aria-label="Selected joint" data-joint={joint.name}>
      <p className="lab-joint-title">{name.title}</p>
      <p className="lab-joint-sub">
        {joint.name} · hinge about {axisLabel(joint.axis)} · {joint.body}
      </p>
      <Dial joint={joint} angle={angle} reference={reference} movement={name.movement} />
      <dl className="lab-facts">
        <div>
          <dt>Angular velocity</dt>
          <dd className="lapis">{formatNumber(velocity, 1, true)} °/s</dd>
        </div>
        <div>
          <dt>Tracking error (angle − reference)</dt>
          <dd>{formatNumber(angle - reference, 2, true)} °</dd>
        </div>
        <div>
          <dt>Actuator torque</dt>
          <dd className="sanguine">{formatNumber(torque, 1, true)} N·m</dd>
        </div>
      </dl>
      <CapacityBar torque={torque} negative={negativeCapacity} positive={positiveCapacity} />
      <dl className="lab-facts">
        <div>
          <dt>Peak activation, all actuators</dt>
          <dd>{formatNumber(activation, 2)}</dd>
        </div>
        <div>
          <dt>Damping</dt>
          <dd>{formatNumber(joint.damping_n_m_s, 1)} N·m·s/rad</dd>
        </div>
      </dl>
    </section>
  );
}

const DIAL_START = 200;
const DIAL_SWEEP = 220;

function polar(cx: number, cy: number, radius: number, degrees: number): [number, number] {
  const radians = (degrees * Math.PI) / 180;
  return [cx + radius * Math.cos(radians), cy - radius * Math.sin(radians)];
}

function arc(cx: number, cy: number, radius: number, from: number, to: number): string {
  const [x0, y0] = polar(cx, cy, radius, from);
  const [x1, y1] = polar(cx, cy, radius, to);
  const large = Math.abs(to - from) > 180 ? 1 : 0;
  const sweep = to < from ? 1 : 0;
  return `M${x0.toFixed(2)},${y0.toFixed(2)}A${radius},${radius} 0 ${large} ${sweep} ${x1.toFixed(2)},${y1.toFixed(2)}`;
}

/** The joint's published range of motion as a dial, with the angle and its reference. */
export function Dial({
  joint,
  angle,
  reference,
  movement,
}: {
  joint: LaboratoryJoint;
  angle: number;
  reference: number;
  movement: string;
}) {
  const [low, high] = joint.range_deg;
  const toDial = (value: number) =>
    DIAL_START - (Math.min(Math.max(value, low), high) - low) / Math.max(high - low, 1e-9) * DIAL_SWEEP;
  const cx = 130;
  const cy = 104;
  const radius = 78;
  const zero = Math.min(Math.max(0, low), high);
  const value = Number.isFinite(angle) ? angle : zero;
  const ticks = niceTicks(low, high, 5).filter((tick) => tick >= low && tick <= high);
  const [nx, ny] = polar(cx, cy, radius - 10, toDial(value));
  const [r0x, r0y] = polar(cx, cy, radius - 6, toDial(reference));
  const [r1x, r1y] = polar(cx, cy, radius + 8, toDial(reference));
  return (
    <figure className="lab-dial">
      <svg viewBox="0 0 260 170" role="img" aria-label={`${formatNumber(angle, 1)} degrees of ${movement}, range ${formatNumber(low, 0)} to ${formatNumber(high, 0)} degrees`}>
        <path className="lab-dial-track" d={arc(cx, cy, radius, DIAL_START, DIAL_START - DIAL_SWEEP)} />
        <path className="lab-dial-value" d={arc(cx, cy, radius, toDial(zero), toDial(value))} />
        {ticks.map((tick) => {
          const [tx, ty] = polar(cx, cy, radius + 16, toDial(tick));
          const [a, b] = polar(cx, cy, radius + 5, toDial(tick));
          const [c, d] = polar(cx, cy, radius - 5, toDial(tick));
          return (
            <g key={tick}>
              <line className="lab-dial-tick" x1={a} y1={b} x2={c} y2={d} />
              <text x={tx} y={ty + 3} textAnchor="middle">
                {tick}
              </text>
            </g>
          );
        })}
        {Number.isFinite(reference) && (
          <line className="lab-dial-reference" x1={r0x} y1={r0y} x2={r1x} y2={r1y} />
        )}
        <line className="lab-dial-needle" x1={cx} y1={cy} x2={nx} y2={ny} />
        <circle className="lab-dial-hub" cx={cx} cy={cy} r={4.5} />
        <text className="lab-dial-readout" x={cx} y={cy + 36} textAnchor="middle">
          {formatNumber(angle, 1)}°
        </text>
        <text className="lab-dial-caption" x={cx} y={cy + 54} textAnchor="middle">
          {movement}
        </text>
        <text className="lab-dial-range" x={14} y={164}>
          ROM {formatNumber(low, 0)}…{formatNumber(high, 0)}°
        </text>
        <text className="lab-dial-legend" x={246} y={164} textAnchor="end">
          ▮ ref
        </text>
      </svg>
    </figure>
  );
}

/** Torque against the joint's published asymmetric capacity (−negative … +positive). */
function CapacityBar({ torque, negative, positive }: { torque: number; negative: number; positive: number }) {
  const span = negative + positive;
  const zero = (negative / span) * 100;
  const value = Number.isFinite(torque) ? torque : 0;
  const left = value < 0 ? zero - (Math.min(-value, negative) / span) * 100 : zero;
  const width = (Math.min(Math.abs(value), value < 0 ? negative : positive) / span) * 100;
  return (
    <div className="lab-capacity" role="meter" aria-label="Actuator torque against capacity" aria-valuemin={-negative} aria-valuemax={positive} aria-valuenow={Number(value.toFixed(1))}>
      <div className="lab-capacity-track">
        <span className="lab-capacity-zero" style={{ left: `${zero}%` }} />
        <span className="lab-capacity-value" style={{ left: `${left}%`, width: `${width}%` }} />
      </div>
      <div className="lab-capacity-scale">
        <span>−{formatNumber(negative, 0)}</span>
        <span>capacity used {formatNumber((Math.abs(value) / (value < 0 ? negative : positive)) * 100, 0)} %</span>
        <span>+{formatNumber(positive, 0)}</span>
      </div>
    </div>
  );
}

/** The two soles at true scale from above, with one disc per published plantar load. */
export function PlantarMap() {
  const { model, frames } = useLabData();
  const frame = useLaboratoryStore((state) => state.frame);
  const kinetics = frames.kinetics;
  const soles = model.geoms.filter((geom) => geom.role === "sole");
  const scale = 760; // px per metre
  const width = 300;
  const height = 250;
  const heel = at(column(kinetics, "heel_load_fraction"), frame);
  const loaded = at(column(kinetics, "loaded_contacts"), frame);
  const threshold = model.contact.loaded_threshold_n;
  const feet = [
    { body: "foot_l", side: "l", label: "left", cx: 88 },
    { body: "foot_r", side: "r", label: "right", cx: 212 },
  ] as const;
  return (
    <section className="lab-inspector-section" aria-label="Plantar load">
      <h3 className="lab-rubric">Plantar load · N</h3>
      <svg className="lab-plantar" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Plantar load map, viewed from above, anterior up">
        {feet.map((foot) => {
          const points = soles.filter((geom) => geom.body === foot.body);
          // From above with anterior up: +x (anterior) is up, +y (the athlete's left) is left.
          const place = (x: number, y: number): [number, number] => [foot.cx - y * scale, 205 - (x + 0.04) * scale];
          const outline = points.map((geom) => place(geom.position_m[0], geom.position_m[1]));
          return (
            <g key={foot.body} data-foot={foot.side}>
              <path className="lab-sole-outer" d={orderedOutline(outline)} />
              <path className="lab-sole-inner" d={orderedOutline(outline)} />
              {points.map((geom) => {
                const point = geom.name.slice(`${foot.body}_`.length);
                const load = at(column(kinetics, `contact.${foot.side}_${point}.normal_n`), frame);
                const [x, y] = place(geom.position_m[0], geom.position_m[1]);
                const radius = 3 + 1.05 * Math.sqrt(Math.max(0, Number.isFinite(load) ? load : 0));
                const bearing = load > threshold;
                // +y is drawn to the left, so points on the +y side of a foot label leftwards.
                const labelLeft = geom.position_m[1] > 0;
                return (
                  <g key={geom.name} data-point={point} data-loaded={bearing}>
                    <circle cx={x} cy={y} r={radius} className={bearing ? "lab-disc" : "lab-disc lab-disc-unloaded"} />
                    <text x={labelLeft ? x - radius - 4 : x + radius + 4} y={y + 3} textAnchor={labelLeft ? "end" : "start"}>
                      {formatNumber(load, 0)}
                    </text>
                  </g>
                );
              })}
              <text className="lab-sole-label" x={foot.cx} y={243} textAnchor="middle">
                {foot.label}
              </text>
            </g>
          );
        })}
      </svg>
      <dl className="lab-facts">
        <div>
          <dt>Heel share (lesser foot)</dt>
          <dd className="verdigris">{formatNumber(heel * 100, 1)} %</dd>
        </div>
        <div>
          <dt>Loaded contacts (&gt; {formatNumber(threshold, 0)} N)</dt>
          <dd className="verdigris">
            {formatNumber(loaded, 0)} / {2 * model.sole_points.length}
          </dd>
        </div>
      </dl>
    </section>
  );
}

/** A rounded outline around sole points: their convex hull, drawn with a wide round stroke. */
function orderedOutline(points: readonly (readonly [number, number])[]): string {
  if (points.length === 0) {
    return "";
  }
  const cx = points.reduce((sum, [x]) => sum + x, 0) / points.length;
  const cy = points.reduce((sum, [, y]) => sum + y, 0) / points.length;
  const ordered = [...points].sort(
    (a, b) => Math.atan2(a[1] - cy, a[0] - cx) - Math.atan2(b[1] - cy, b[0] - cx),
  );
  return `M${ordered.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join("L")}Z`;
}
