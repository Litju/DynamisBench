import { LCMJ20, REF, type SourceTag } from './authority';

export type Prop = {
  name: string;
  value: string;
  unit?: string;
  frame?: string;
  tag: SourceTag;
  note?: string;
  live?: 'theta' | 'omega' | 'energy' | 'bobx' | 'bobz' | `coord:${string}` | `myo:${string}`;
};

export type EntityKind =
  | 'model' | 'group' | 'frame' | 'body' | 'joint' | 'coordinate' | 'site' | 'contact' | 'actuator' | 'sensor' | 'solver' | 'quantity' | 'empty';

export type Entity = {
  id: string;
  kind: EntityKind;
  label: string;
  sub?: string;
  parent?: string;
  tag: SourceTag;
  summary?: string;
  props?: Prop[];
  signals?: string[]; // signal ids linked to this entity
  pickable?: boolean;
};

export type ModelId = 'pendulum' | 'lcmj-schematic';

const x = REF;
const P = (name: string, value: string | number, unit?: string, tag: SourceTag = 'AUTHORITY', extra: Partial<Prop> = {}): Prop => ({
  name, value: String(value), unit, tag, ...extra,
});

export const PENDULUM_ENTITIES: Entity[] = [
  { id: 'model', kind: 'model', label: 'dynamisbench-reference-pendulum', sub: 'MJCF · 1 body · 1 DOF', tag: 'AUTHORITY',
    summary: 'Deliberately minimal MuJoCo model used to qualify the first real adapter. Not a human-movement model.',
    props: [
      P('Asset (workspace authority path)', x.modelSourcePath), P('Packaged asset', 'assets/reference_pendulum.xml'),
      P('Raw-byte SHA-256', x.modelSha256), P('nq / nv / nu', '1 / 1 / 0'), P('nbody / njnt / ngeom / nsite', '2 / 1 / 0 / 1'),
      P('compiler', 'angle=radian, coordinate=local, inertiafromgeom=false'),
      P('Conventions', 'radians, metres, kilograms, seconds; +rotation about +y by right-hand rule'),
    ] },
  { id: 'g.frames', kind: 'group', label: 'Frames', parent: 'model', tag: 'AUTHORITY' },
  { id: 'frame.world', kind: 'frame', label: 'world', sub: 'right-handed · gravity −z', parent: 'g.frames', tag: 'AUTHORITY', pickable: true,
    summary: 'Right-handed world frame with gravity along -z. (reference_case.py _world_frame)',
    props: [P('Parent', 'global'), P('Axes', 'x, y, z'), P('Handedness', 'right'), P('Gravity', `0, 0, −${x.gravity}`, 'm·s⁻²', 'AUTHORITY', { frame: 'world' })] },
  { id: 'frame.hinge', kind: 'frame', label: 'hinge', sub: 'axis +y', parent: 'g.frames', tag: 'AUTHORITY', pickable: true,
    summary: 'The single hinge axis, positive by the right-hand rule about +y.',
    props: [P('Parent', 'world'), P('Axis', 'y'), P('Origin', '0, 0, 0', 'm', 'AUTHORITY', { frame: 'world' })] },
  { id: 'g.bodies', kind: 'group', label: 'Bodies', parent: 'model', tag: 'AUTHORITY' },
  { id: 'body.world', kind: 'body', label: 'world', sub: 'body 0 · fixed', parent: 'g.bodies', tag: 'AUTHORITY' , summary: 'MuJoCo world body (body 0).', props: [P('Body id', 0)] },
  { id: 'body.pendulum', kind: 'body', label: 'pendulum', sub: 'body 1 · 1 kg', parent: 'g.bodies', tag: 'AUTHORITY', pickable: true,
    summary: 'One rigid body on one frictionless hinge. The model declares no geoms; drawn rod and bob are display geometry.',
    signals: ['energy', 'bobx', 'bobz'],
    props: [
      P('Mass', x.massKg, 'kg'), P('COM position', '0, 0, −1', 'm', 'AUTHORITY', { frame: 'pendulum body' }),
      P('COM inertia (diag)', '0.001, 0.001, 0.001', 'kg·m²'), P('Hinge-axis inertia I', x.hingeInertiaKgM2.toFixed(3), 'kg·m²', 'AUTHORITY', { note: 'COM inertia + m·L² (parallel axis)' }),
      P('Geometry', 'none (ngeom = 0)'),
      P('Energy E = ½Iω² + mgL(1−cos θ)', '', 'J', 'RECOMPUTED', { live: 'energy' }),
    ] },
  { id: 'g.joints', kind: 'group', label: 'Joints & coordinates', parent: 'model', tag: 'AUTHORITY' },
  { id: 'joint.hinge', kind: 'joint', label: 'hinge', sub: 'hinge · axis +y', parent: 'g.joints', tag: 'AUTHORITY', pickable: true,
    summary: 'Frictionless, unlimited hinge connecting world → pendulum.', signals: ['theta', 'omega'],
    props: [
      P('Type', 'hinge'), P('Axis', '0, 1, 0', '', 'AUTHORITY', { frame: 'pendulum body' }), P('Position', '0, 0, 0', 'm'),
      P('Limited', 'false'), P('Damping', 0, 'N·m·s·rad⁻¹'), P('Armature', 0, 'kg·m²'), P('Friction loss', 0, 'N·m'),
      P('q0 hinge angle θ(t)', '', 'rad', 'RECOMPUTED', { live: 'theta' }), P('q̇0 angular velocity ω(t)', '', 'rad·s⁻¹', 'RECOMPUTED', { live: 'omega' }),
    ] },
  { id: 'coord.hinge', kind: 'coordinate', label: 'q0 · hinge angle', sub: 'qpos[0] · rad', parent: 'joint.hinge', tag: 'AUTHORITY', pickable: false,
    summary: 'Generalised coordinate of the hinge, measured from the downward vertical.', signals: ['theta', 'omega'],
    props: [
      P('Quantity', 'q.pendulum.hinge-angle 1.0.0'), P('Unit', '1 (rad)'), P('Frame', 'hinge'), P('Sign', 'positive rotation about +y by the right-hand rule'),
      P('Time basis', 'relative_to_start'), P('Sampling', 'uniform 1000 Hz'), P('Uncertainty', 'numerical integration error only; no measurement uncertainty'),
      P('Initial value', `${x.theta0} (30°)`, 'rad'), P('θ(t)', '', 'rad', 'RECOMPUTED', { live: 'theta' }), P('ω(t)', '', 'rad·s⁻¹', 'RECOMPUTED', { live: 'omega' }),
    ] },
  { id: 'g.sites', kind: 'group', label: 'Sites', parent: 'model', tag: 'AUTHORITY' },
  { id: 'site.bob', kind: 'site', label: 'bob', sub: 'site · r = 0.02 m', parent: 'g.sites', tag: 'AUTHORITY', pickable: true,
    summary: 'Marker site at the centre of mass. Not a contact geometry.', signals: ['bobx', 'bobz'],
    props: [P('Position', '0, 0, −1', 'm', 'AUTHORITY', { frame: 'pendulum body' }), P('Size', 0.02, 'm'),
      P('x(t) = −L sin θ', '', 'm', 'RECOMPUTED', { live: 'bobx', frame: 'world' }), P('z(t) = −L cos θ', '', 'm', 'RECOMPUTED', { live: 'bobz', frame: 'world' })] },
  { id: 'g.contact', kind: 'empty', label: 'Contacts', sub: 'none — no geoms', parent: 'model', tag: 'AUTHORITY', summary: x.contactPolicy },
  { id: 'g.act', kind: 'empty', label: 'Actuators', sub: 'none — nu = 0', parent: 'model', tag: 'AUTHORITY', summary: x.controlPolicy },
  { id: 'g.sensors', kind: 'empty', label: 'Sensors', sub: 'none — nsensor = 0', parent: 'model', tag: 'AUTHORITY', summary: 'The model declares no sensors.' },
  { id: 'solver', kind: 'solver', label: 'Solver & integration', sub: `${x.integrator} · ${x.solver} · Δt ${x.timestep} s`, tag: 'AUTHORITY',
    summary: 'Reviewed <option> block of the MJCF; the adapter refuses a model whose options changed.',
    props: [P('Integrator', x.integrator), P('Constraint solver', x.solver), P('Iterations', x.iterations), P('Tolerance', '1e-12'), P('Timestep', x.timestep, 's'),
      P('Duration', x.duration, 's'), P('Steps', x.steps), P('Jacobian / cone', 'auto / elliptic'), P('Precision', 'float64')] },
  { id: 'g.quant', kind: 'group', label: 'Declared quantities', tag: 'AUTHORITY' },
  { id: 'q.angle', kind: 'quantity', label: 'q.pendulum.hinge-angle', sub: 'unit 1 · hinge', parent: 'g.quant', tag: 'AUTHORITY', signals: ['theta'],
    summary: 'Planar pendulum hinge angle measured from the downward vertical.', props: [P('Dimension', 'dimensionless'), P('Unit', '1'), P('Frame', 'hinge'), P('Mapped from', 'native hinge-angle (rad)')] },
  { id: 'q.omega', kind: 'quantity', label: 'q.pendulum.hinge-angular-velocity', sub: 's⁻¹ · hinge', parent: 'g.quant', tag: 'AUTHORITY', signals: ['omega'],
    summary: 'Time derivative of the planar pendulum hinge angle.', props: [P('Dimension', 'T⁻¹'), P('Unit', 's^-1'), P('Frame', 'hinge'), P('Mapped from', 'native hinge-angular-velocity (rad/s)')] },
  { id: 'q.gravity', kind: 'quantity', label: 'q.pendulum.gravity', sub: 'm/s² · world', parent: 'g.quant', tag: 'AUTHORITY',
    summary: 'Uniform downward gravitational acceleration. Single sample.', props: [P('Value', x.gravity, 'm·s⁻²'), P('Uncertainty', 'declared standard gravity; not an empirical estimate')] },
];

/* ---- LCMJ20 planar sagittal subject: DESIGN-ONLY schematic structure ---- */

export type CoordDef = { id: string; label: string; joint: string; unit: 'rad' | 'm'; min: number; max: number; def: number };

export const HUMAN_COORDS: CoordDef[] = [
  { id: 'pelvis_tx', label: 'pelvis_tx', joint: 'joint.ground_pelvis', unit: 'm', min: -0.3, max: 0.3, def: 0 },
  { id: 'pelvis_tz', label: 'pelvis_tz', joint: 'joint.ground_pelvis', unit: 'm', min: 0.5, max: 1.3, def: 0.93 },
  { id: 'pelvis_tilt', label: 'pelvis_tilt', joint: 'joint.ground_pelvis', unit: 'rad', min: -0.8, max: 0.8, def: 0 },
  { id: 'lumbar_ext', label: 'lumbar_extension', joint: 'joint.lumbar', unit: 'rad', min: -0.9, max: 0.5, def: 0 },
  { id: 'hip_r', label: 'hip_flexion_r', joint: 'joint.hip_r', unit: 'rad', min: -0.5, max: 2.0, def: 0 },
  { id: 'knee_r', label: 'knee_flexion_r', joint: 'joint.knee_r', unit: 'rad', min: 0, max: 2.2, def: 0 },
  { id: 'ankle_r', label: 'ankle_dorsiflexion_r', joint: 'joint.ankle_r', unit: 'rad', min: -0.8, max: 0.5, def: 0 },
  { id: 'hip_l', label: 'hip_flexion_l', joint: 'joint.hip_l', unit: 'rad', min: -0.5, max: 2.0, def: 0 },
  { id: 'knee_l', label: 'knee_flexion_l', joint: 'joint.knee_l', unit: 'rad', min: 0, max: 2.2, def: 0 },
  { id: 'ankle_l', label: 'ankle_dorsiflexion_l', joint: 'joint.ankle_l', unit: 'rad', min: -0.8, max: 0.5, def: 0 },
];

export const SEG = { thigh: 0.42, shank: 0.43, ankleH: 0.08, foot: 0.25, heel: 0.06, trunk: 0.52, pelvisHalf: 0.09, head: 0.1 };

const NA = (name: string, unit?: string): Prop => ({ name, value: 'not available', unit, tag: 'NOT_IMPLEMENTED' });
const bodyProps = (len?: number): Prop[] => [
  NA('Mass', 'kg'), NA('COM position', 'm'), NA('Inertia tensor', 'kg·m²'),
  ...(len ? [{ name: 'Display length', value: len.toFixed(2), unit: 'm', tag: 'DESIGN_ONLY' as SourceTag, note: 'schematic drawing length, not anthropometry' }] : []),
];
const joint = (id: string, label: string, parent: string, child: string, coord: string, key: string, conv: string): Entity => ({
  id, kind: 'joint', label, sub: `hinge · ${parent} → ${child}`, parent: 'g.hjoints', tag: 'DESIGN_ONLY', pickable: true, signals: [key],
  summary: 'Schematic planar hinge (sagittal, about the medio-lateral axis). Topology is illustrative of a planar sagittal multi-segment subject; no joint definition exists in authority.',
  props: [
    { name: 'Parent → child', value: `${parent} → ${child}`, tag: 'DESIGN_ONLY' },
    { name: 'Coordinate', value: coord, tag: 'DESIGN_ONLY' },
    { name: 'Display sign convention', value: conv, tag: 'DESIGN_ONLY' },
    { name: 'Pose value', value: '', unit: 'rad', tag: 'DESIGN_ONLY', live: `coord:${key}` },
    NA('Range / limits', 'rad'), NA('Damping', 'N·m·s·rad⁻¹'),
  ],
});

export const HUMAN_ENTITIES: Entity[] = [
  { id: 'model', kind: 'model', label: 'LCMJ20 planar sagittal subject', sub: 'schematic · 13 bodies · 10 DOF', tag: 'DESIGN_ONLY',
    summary: `Representative articulated schematic for the target UX. Fixture conceptual model: "${LCMJ20.conceptualModel}" No licensed human model asset exists in the repository; no human physics result is shown.`,
    props: [
      { name: 'Realization (fixture)', value: LCMJ20.realization.id, tag: 'FIXTURE' },
      { name: 'Asset', value: LCMJ20.realization.asset.path, tag: 'FIXTURE' },
      { name: 'Asset SHA-256', value: LCMJ20.realization.asset.sha256, tag: 'FIXTURE', note: 'all-zero placeholder in the test fixture' },
      { name: 'Engine specifier', value: `mujoco ${LCMJ20.realization.engineSpecifier}`, tag: 'FIXTURE' },
      { name: 'Integrator', value: LCMJ20.realization.integrator, tag: 'FIXTURE' },
      { name: 'Geometry', value: 'anatomical proxy shapes (lathe/rounded primitives), not a mesh asset', tag: 'DESIGN_ONLY' },
    ] },
  { id: 'g.hframes', kind: 'group', label: 'Frames', parent: 'model', tag: 'FIXTURE' },
  { id: 'frame.world', kind: 'frame', label: 'world', sub: 'right-handed · vertical +z', parent: 'g.hframes', tag: 'FIXTURE', pickable: true,
    summary: 'Right-handed world frame with the vertical along +z (fixture quantity frame).', props: [{ name: 'Axes', value: 'x, y, z', tag: 'FIXTURE' }, { name: 'Display: anterior', value: '+x', tag: 'DESIGN_ONLY' }] },
  { id: 'g.hbodies', kind: 'group', label: 'Bodies', parent: 'model', tag: 'DESIGN_ONLY' },
  { id: 'body.plate', kind: 'body', label: 'force_plate', sub: 'ground · rigid', parent: 'g.hbodies', tag: 'FIXTURE', pickable: true,
    summary: 'Rigid supporting surface (fixture assumption).', props: [{ name: 'Assumption', value: 'Rigid supporting surface.', tag: 'FIXTURE' }, { name: 'Calibration', value: 'not available', tag: 'NOT_IMPLEMENTED' }] },
  { id: 'body.pelvis', kind: 'body', label: 'pelvis', parent: 'g.hbodies', tag: 'DESIGN_ONLY', pickable: true, props: bodyProps(0.18), signals: ['pelvis_tz'] },
  { id: 'body.torso', kind: 'body', label: 'torso', parent: 'g.hbodies', tag: 'DESIGN_ONLY', pickable: true, props: bodyProps(SEG.trunk) },
  { id: 'body.head', kind: 'body', label: 'head', sub: 'welded to torso', parent: 'g.hbodies', tag: 'DESIGN_ONLY', pickable: true, props: bodyProps() },
  ...(['r', 'l'] as const).map((s) => ({ id: `body.arm_${s}`, kind: 'body' as const, label: `arm_${s}`, sub: 'welded to torso · no DOF', parent: 'g.hbodies', tag: 'DESIGN_ONLY' as SourceTag, pickable: true,
    summary: 'Upper arm, forearm and hand drawn as one welded display body. A planar jump model may give arms their own DOF; none is defined here.', props: bodyProps() })),
  ...(['r', 'l'] as const).flatMap((s) => [
    { id: `body.thigh_${s}`, kind: 'body' as const, label: `femur_${s}`, parent: 'g.hbodies', tag: 'DESIGN_ONLY' as SourceTag, pickable: true, props: bodyProps(SEG.thigh) },
    { id: `body.shank_${s}`, kind: 'body' as const, label: `tibia_${s}`, parent: 'g.hbodies', tag: 'DESIGN_ONLY' as SourceTag, pickable: true, props: bodyProps(SEG.shank) },
    { id: `body.foot_${s}`, kind: 'body' as const, label: `foot_${s}`, parent: 'g.hbodies', tag: 'DESIGN_ONLY' as SourceTag, pickable: true, props: bodyProps(SEG.foot) },
  ]),
  { id: 'g.hjoints', kind: 'group', label: 'Joints & coordinates', parent: 'model', tag: 'DESIGN_ONLY' },
  { id: 'joint.ground_pelvis', kind: 'joint', label: 'ground_pelvis', sub: 'planar · 3 DOF', parent: 'g.hjoints', tag: 'DESIGN_ONLY', pickable: false,
    summary: 'Schematic planar joint: pelvis_tx, pelvis_tz, pelvis_tilt.', signals: ['pelvis_tz'],
    props: [{ name: 'Coordinates', value: 'pelvis_tx, pelvis_tz, pelvis_tilt', tag: 'DESIGN_ONLY' }, { name: 'pelvis_tz', value: '', unit: 'm', tag: 'DESIGN_ONLY', live: 'coord:pelvis_tz' }] },
  { id: 'joint.lumbar', kind: 'joint', label: 'lumbar', sub: 'hinge · pelvis → torso', parent: 'g.hjoints', tag: 'DESIGN_ONLY', pickable: true, signals: ['lumbar_ext'],
    summary: 'Schematic lumbar hinge.', props: [{ name: 'Pose value', value: '', unit: 'rad', tag: 'DESIGN_ONLY', live: 'coord:lumbar_ext' }, NA('Range / limits', 'rad')] },
  ...(['r', 'l'] as const).flatMap((s) => [
    joint(`joint.hip_${s}`, `hip_${s}`, 'pelvis', `femur_${s}`, `hip_flexion_${s}`, `hip_${s}`, 'flexion +, thigh anterior'),
    joint(`joint.knee_${s}`, `knee_${s}`, `femur_${s}`, `tibia_${s}`, `knee_flexion_${s}`, `knee_${s}`, 'flexion +, shank posterior'),
    joint(`joint.ankle_${s}`, `ankle_${s}`, `tibia_${s}`, `foot_${s}`, `ankle_dorsiflexion_${s}`, `ankle_${s}`, 'dorsiflexion +, toes up'),
  ]),
  { id: 'g.hcontact', kind: 'group', label: 'Contacts', parent: 'model', tag: 'FIXTURE' },
  { id: 'contact.foot_plate', kind: 'contact', label: 'foot ↔ force_plate', sub: 'declared · not parameterised', parent: 'g.hcontact', tag: 'FIXTURE', pickable: false,
    summary: 'Contact is implied by the fixture (vertical GRF on the foot; contact-stiffness factor). No contact model, stiffness or geometry exists.',
    props: [{ name: 'Stiffness', value: 'not available', tag: 'NOT_IMPLEMENTED', note: 'fixture: "Contact stiffness is not calibrated against the reference plate."' },
      { name: 'Study factor', value: 'f.contact-stiffness · uniform 0.8–1.2 (scale)', tag: 'FIXTURE' }] },
  { id: 'g.hact', kind: 'empty', label: 'Actuators', sub: 'none defined', parent: 'model', tag: 'NOT_IMPLEMENTED', summary: 'No actuator, muscle or controller set exists for this subject. Fixture SUT sut.baseline-0 is referenced but not modelled.' },
  { id: 'g.hsens', kind: 'group', label: 'Sensors', parent: 'model', tag: 'FIXTURE' },
  { id: 'sensor.foot', kind: 'sensor', label: 'force_sensor_foot', sub: 'native source · fixture', parent: 'g.hsens', tag: 'FIXTURE', signals: ['grf'],
    summary: 'Native source named in the realization quantity mapping for q.foot.vertical_force and q.jump.height (transform sensor-nearest 1.0.0).',
    props: [{ name: 'Maps to', value: 'q.foot.vertical_force, q.jump.height', tag: 'FIXTURE' }, { name: 'Transform', value: 'sensor-nearest 1.0.0', tag: 'FIXTURE' }, { name: 'Output', value: 'not produced', tag: 'NOT_IMPLEMENTED' }] },
  { id: 'solver', kind: 'solver', label: 'Solver & integration', sub: 'implicitfast · fixture', tag: 'FIXTURE',
    summary: 'Only the integrator is declared in the fixture realization.', props: [{ name: 'Integrator', value: 'implicitfast', tag: 'FIXTURE' }, { name: 'Timestep / solver / tolerance', value: 'not declared', tag: 'NOT_IMPLEMENTED' }] },
  { id: 'g.hquant', kind: 'group', label: 'Declared quantities', tag: 'FIXTURE' },
  { id: 'q.grf', kind: 'quantity', label: 'q.foot.vertical_force', sub: 'N · world · +z up', parent: 'g.hquant', tag: 'FIXTURE', signals: ['grf'],
    summary: 'Vertical component of the ground reaction force on the foot.', props: [{ name: 'Unit', value: 'm*kg*s^-2 (N)', tag: 'FIXTURE' }, { name: 'Sign', value: 'upward, away from the supporting surface', tag: 'FIXTURE' }, { name: 'Sampling', value: 'uniform 1000 Hz', tag: 'FIXTURE' }, { name: 'Data', value: 'not produced', tag: 'NOT_IMPLEMENTED' }] },
  { id: 'q.height', kind: 'quantity', label: 'q.jump.height', sub: 'm · COM · irregular', parent: 'g.hquant', tag: 'FIXTURE', signals: ['height'],
    summary: 'Apex height of the centre of mass above its standing value.', props: [{ name: 'Unit', value: 'm', tag: 'FIXTURE' }, { name: 'Uncertainty', value: 'expected to be dominated by marker placement variability', tag: 'FIXTURE' }, { name: 'Data', value: 'not produced', tag: 'NOT_IMPLEMENTED' }] },
  { id: 'q.knee', kind: 'quantity', label: 'q.knee.flexion_angle', sub: 'unit 1 · r-knee · event-relative', parent: 'g.hquant', tag: 'FIXTURE', signals: ['knee_r'],
    summary: 'Sagittal flexion angle of the right knee (separate fixture).', props: [{ name: 'Time basis', value: 'relative_to_event · initial-contact', tag: 'FIXTURE' }, { name: 'Data', value: 'not produced', tag: 'NOT_IMPLEMENTED' }] },
];

export const ENTITIES: Record<ModelId, Entity[]> = { pendulum: PENDULUM_ENTITIES, 'lcmj-schematic': HUMAN_ENTITIES };
export const entityOf = (model: ModelId, id: string | null) => (id ? ENTITIES[model].find((e) => e.id === id) ?? null : null);
