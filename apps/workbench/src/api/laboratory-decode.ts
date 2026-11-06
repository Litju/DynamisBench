/**
 * Runtime decoders for the `/api/v1/laboratory` JSON read models.
 *
 * The same discipline as `decode.ts`: total functions over `unknown` that return a fresh value
 * assembled from validated fields, or `null` when the body is not the published read model.
 * An unknown field is never carried into an accepted value, a non-finite number is refused
 * (JSON cannot carry one, so one here is a forged body), and digests must be 64 lowercase hex.
 *
 * The free-form measurement `summary` is validated structurally — objects whose leaves are
 * finite numbers, strings, booleans, arrays of numbers or arrays of such objects, to a bounded
 * depth — because it is presentation data whose keys the workbench reads by name. Nothing in
 * it is re-derived here: a value the workbench shows is a value the API published.
 */

import {
  LABORATORY_CHECK_STATUSES,
  LABORATORY_FRAME_GROUPS,
  LABORATORY_GEOM_ROLES,
  LABORATORY_GEOM_TYPES,
  LABORATORY_RECORDING_KINDS,
  type LaboratoryBody,
  type LaboratoryCheck,
  type LaboratoryContact,
  type LaboratoryEvent,
  type LaboratoryFrameGroup,
  type LaboratoryGeom,
  type LaboratoryIndexResponse,
  type LaboratoryJoint,
  type LaboratoryModelResponse,
  type LaboratoryPhaseSpan,
  type LaboratoryRecordingEntry,
  type LaboratoryRecordingResponse,
  type LaboratorySubject,
  type Quat,
  type SummaryTree,
  type SummaryValue,
  type Vec3,
} from "./laboratory-types";

type JsonObject = Record<string, unknown>;

const SHA256 = /^[0-9a-f]{64}$/;
/** Identifiers the laboratory publishes: recordings, bodies, joints, geoms, columns. */
const IDENTIFIER = /^[A-Za-z0-9_.:-]{1,96}$/;
const MAX_SUMMARY_DEPTH = 6;
const MAX_TEXT = 2_000;

function asObject(value: unknown): JsonObject | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as JsonObject;
}

function list<T>(value: unknown, decode: (item: unknown) => T | null): T[] | null {
  if (!Array.isArray(value)) {
    return null;
  }
  const decoded: T[] = [];
  for (const item of value) {
    const element = decode(item);
    if (element === null) {
      return null;
    }
    decoded.push(element);
  }
  return decoded;
}

function finite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function count(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.length <= MAX_TEXT ? value : null;
}

function identifier(value: unknown): string | null {
  return typeof value === "string" && IDENTIFIER.test(value) ? value : null;
}

function digest(value: unknown): string | null {
  return typeof value === "string" && SHA256.test(value) ? value : null;
}

function oneOf<T extends string>(vocabulary: readonly T[], value: unknown): T | null {
  return vocabulary.some((member) => member === value) ? (value as T) : null;
}

function tuple(value: unknown, length: number): number[] | null {
  const numbers = list(value, finite);
  return numbers !== null && numbers.length === length ? numbers : null;
}

function vec3(value: unknown): Vec3 | null {
  const numbers = tuple(value, 3);
  return numbers === null ? null : [numbers[0]!, numbers[1]!, numbers[2]!];
}

function pair(value: unknown): readonly [number, number] | null {
  const numbers = tuple(value, 2);
  return numbers === null ? null : [numbers[0]!, numbers[1]!];
}

function quat(value: unknown): Quat | null {
  const numbers = tuple(value, 4);
  return numbers === null ? null : [numbers[0]!, numbers[1]!, numbers[2]!, numbers[3]!];
}

/** A flat `{name: number}` record with identifier keys. */
function numberRecord(value: unknown): Record<string, number> | null {
  const record = asObject(value);
  if (record === null) {
    return null;
  }
  const decoded: Record<string, number> = {};
  for (const [key, item] of Object.entries(record)) {
    const number = finite(item);
    if (identifier(key) === null || number === null) {
      return null;
    }
    decoded[key] = number;
  }
  return decoded;
}

function stringRecord(value: unknown): Record<string, string> | null {
  const record = asObject(value);
  if (record === null) {
    return null;
  }
  const decoded: Record<string, string> = {};
  for (const [key, item] of Object.entries(record)) {
    const string = text(item);
    if (identifier(key) === null || string === null) {
      return null;
    }
    decoded[key] = string;
  }
  return decoded;
}

function decodeRecordingEntry(value: unknown): LaboratoryRecordingEntry | null {
  const record = asObject(value);
  if (record === null) {
    return null;
  }
  const recordingId = identifier(record.recording_id);
  const label = text(record.label);
  const kind = oneOf(LABORATORY_RECORDING_KINDS, record.kind);
  const description = text(record.description);
  const timestep = finite(record.timestep_s);
  const duration = finite(record.duration_s);
  const frameCount = count(record.frame_count);
  const trajectory = digest(record.trajectory_sha256);
  const completed = typeof record.completed === "boolean" ? record.completed : null;
  const passed = count(record.checks_passed);
  const failed = count(record.checks_failed);
  const notEvaluated = count(record.checks_not_evaluated);
  if (
    recordingId === null ||
    label === null ||
    kind === null ||
    description === null ||
    timestep === null ||
    duration === null ||
    frameCount === null ||
    trajectory === null ||
    completed === null ||
    passed === null ||
    failed === null ||
    notEvaluated === null
  ) {
    return null;
  }
  return {
    recording_id: recordingId,
    label,
    kind,
    description,
    timestep_s: timestep,
    duration_s: duration,
    frame_count: frameCount,
    trajectory_sha256: trajectory,
    completed,
    checks_passed: passed,
    checks_failed: failed,
    checks_not_evaluated: notEvaluated,
  };
}

/** `GET /api/v1/laboratory` — the dataset's identity, claim and recordings. */
export function decodeLaboratoryIndexResponse(value: unknown): LaboratoryIndexResponse | null {
  const record = asObject(value);
  if (record === null) {
    return null;
  }
  const schema = text(record.dataset_schema);
  const datasetId = text(record.dataset_id);
  const manifest = digest(record.manifest_sha256);
  const generatedWith = stringRecord(record.generated_with);
  const claim = text(record.claim);
  const plan = numberRecord(record.plan);
  const recordings = list(record.recordings, decodeRecordingEntry);
  if (
    schema === null ||
    datasetId === null ||
    manifest === null ||
    generatedWith === null ||
    claim === null ||
    plan === null ||
    recordings === null ||
    recordings.length === 0
  ) {
    return null;
  }
  const ids = new Set(recordings.map((entry) => entry.recording_id));
  if (ids.size !== recordings.length) {
    return null;
  }
  return {
    dataset_schema: schema,
    dataset_id: datasetId,
    manifest_sha256: manifest,
    generated_with: generatedWith,
    claim,
    plan,
    recordings,
  };
}

function decodeBody(value: unknown): LaboratoryBody | null {
  const record = asObject(value);
  if (record === null) {
    return null;
  }
  const name = identifier(record.name);
  const parent = identifier(record.parent);
  const mass = finite(record.mass_kg);
  const com = vec3(record.com_m);
  const inertia = vec3(record.principal_inertia_kg_m2);
  const position = vec3(record.position_m);
  const quaternion = quat(record.quaternion);
  if (
    name === null ||
    parent === null ||
    mass === null ||
    com === null ||
    inertia === null ||
    position === null ||
    quaternion === null
  ) {
    return null;
  }
  return {
    name,
    parent,
    mass_kg: mass,
    com_m: com,
    principal_inertia_kg_m2: inertia,
    position_m: position,
    quaternion,
  };
}

function decodeGeom(value: unknown): LaboratoryGeom | null {
  const record = asObject(value);
  if (record === null) {
    return null;
  }
  const name = identifier(record.name);
  const body = identifier(record.body);
  const type = oneOf(LABORATORY_GEOM_TYPES, record.type);
  const size = vec3(record.size_m);
  const position = vec3(record.position_m);
  const quaternion = quat(record.quaternion);
  const role = oneOf(LABORATORY_GEOM_ROLES, record.role);
  if (
    name === null ||
    body === null ||
    type === null ||
    size === null ||
    position === null ||
    quaternion === null ||
    role === null
  ) {
    return null;
  }
  return { name, body, type, size_m: size, position_m: position, quaternion, role };
}

function decodeJoint(value: unknown): LaboratoryJoint | null {
  const record = asObject(value);
  if (record === null) {
    return null;
  }
  const name = identifier(record.name);
  const body = identifier(record.body);
  const axis = vec3(record.axis);
  const range = pair(record.range_deg);
  const capacity = pair(record.torque_capacity_nm);
  const damping = finite(record.damping_n_m_s);
  const position = vec3(record.position_m);
  if (
    name === null ||
    body === null ||
    axis === null ||
    range === null ||
    capacity === null ||
    damping === null ||
    position === null ||
    range[0] > range[1]
  ) {
    return null;
  }
  return {
    name,
    body,
    axis,
    range_deg: range,
    torque_capacity_nm: capacity,
    damping_n_m_s: damping,
    position_m: position,
  };
}

function decodeSubject(value: unknown): LaboratorySubject | null {
  const record = asObject(value);
  if (record === null) {
    return null;
  }
  const mass = finite(record.body_mass_kg);
  const stature = finite(record.stature_m);
  const bar = finite(record.barbell_mass_kg);
  const grip = finite(record.grip_half_width_m);
  if (mass === null || stature === null || bar === null || grip === null) {
    return null;
  }
  return { body_mass_kg: mass, stature_m: stature, barbell_mass_kg: bar, grip_half_width_m: grip };
}

function decodeContact(value: unknown): LaboratoryContact | null {
  const record = asObject(value);
  if (record === null) {
    return null;
  }
  const radius = finite(record.sole_point_radius_m);
  const friction = vec3(record.friction);
  const normal = finite(record.normal_time_constant_s);
  const tangential = finite(record.friction_time_constant_s);
  const threshold = finite(record.loaded_threshold_n);
  if (
    radius === null ||
    friction === null ||
    normal === null ||
    tangential === null ||
    threshold === null
  ) {
    return null;
  }
  return {
    sole_point_radius_m: radius,
    friction,
    normal_time_constant_s: normal,
    friction_time_constant_s: tangential,
    loaded_threshold_n: threshold,
  };
}

/** `GET /api/v1/laboratory/model` — the compiled model the recordings were integrated with. */
export function decodeLaboratoryModelResponse(value: unknown): LaboratoryModelResponse | null {
  const record = asObject(value);
  if (record === null) {
    return null;
  }
  const modelDigest = digest(record.model_sha256);
  const counts = numberRecord(record.counts);
  const totalMass = finite(record.total_mass_kg);
  const bodies = list(record.bodies, decodeBody);
  const geoms = list(record.geoms, decodeGeom);
  const joints = list(record.joints, decodeJoint);
  const solePoints = list(record.sole_points, identifier);
  const timestep = finite(record.timestep_s);
  const integrator = text(record.integrator);
  const gravity = finite(record.gravity_m_s2);
  const subject = decodeSubject(record.subject);
  const contact = decodeContact(record.contact);
  if (
    modelDigest === null ||
    counts === null ||
    totalMass === null ||
    bodies === null ||
    geoms === null ||
    joints === null ||
    solePoints === null ||
    timestep === null ||
    integrator === null ||
    gravity === null ||
    subject === null ||
    contact === null
  ) {
    return null;
  }
  // Every geom and joint hangs from a published body (or the world): a model that names a body
  // it does not describe cannot be drawn.
  const names = new Set(["world", ...bodies.map((body) => body.name)]);
  if (
    !bodies.every((body) => names.has(body.parent)) ||
    !geoms.every((geom) => names.has(geom.body)) ||
    !joints.every((joint) => names.has(joint.body))
  ) {
    return null;
  }
  return {
    model_sha256: modelDigest,
    counts,
    total_mass_kg: totalMass,
    bodies,
    geoms,
    joints,
    sole_points: solePoints,
    timestep_s: timestep,
    integrator,
    gravity_m_s2: gravity,
    subject,
    contact,
  };
}

function decodeEvent(value: unknown): LaboratoryEvent | null {
  const record = asObject(value);
  if (record === null) {
    return null;
  }
  const phase = identifier(record.phase);
  const t = finite(record.t);
  return phase === null || t === null ? null : { phase, t };
}

export function decodePhaseSpan(value: unknown): LaboratoryPhaseSpan | null {
  const record = asObject(value);
  if (record === null) {
    return null;
  }
  const phase = identifier(record.phase);
  const start = finite(record.start_s);
  const end = finite(record.end_s);
  if (phase === null || start === null || end === null || end < start) {
    return null;
  }
  return { phase, start_s: start, end_s: end };
}

function decodeCheck(value: unknown): LaboratoryCheck | null {
  const record = asObject(value);
  if (record === null) {
    return null;
  }
  const criterionId = identifier(record.criterion_id);
  const group = text(record.group);
  const label = text(record.label);
  const unit = text(record.unit);
  const bound = text(record.bound);
  const rationale = text(record.rationale);
  const status = oneOf(LABORATORY_CHECK_STATUSES, record.status);
  const checkValue = record.value === null ? null : finite(record.value);
  if (
    criterionId === null ||
    group === null ||
    label === null ||
    unit === null ||
    bound === null ||
    rationale === null ||
    status === null ||
    (record.value !== null && checkValue === null) ||
    // A check that was evaluated has a value; one that was not has none.
    (status === "not_evaluated") !== (checkValue === null)
  ) {
    return null;
  }
  return {
    criterion_id: criterionId,
    group,
    label,
    unit,
    bound,
    rationale,
    value: checkValue,
    status,
  };
}

function decodeSummaryValue(value: unknown, depth: number): SummaryValue | null {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }
  if (typeof value === "string") {
    return text(value);
  }
  if (typeof value === "boolean") {
    return value;
  }
  if (Array.isArray(value)) {
    if (value.every((item) => typeof item === "number")) {
      return list(value, finite);
    }
    return list(value, (item) => decodeSummaryTree(item, depth + 1));
  }
  return decodeSummaryTree(value, depth + 1);
}

function decodeSummaryTree(value: unknown, depth: number): SummaryTree | null {
  const record = asObject(value);
  if (record === null || depth > MAX_SUMMARY_DEPTH) {
    return null;
  }
  const decoded: Record<string, SummaryValue> = {};
  for (const [key, item] of Object.entries(record)) {
    const element = decodeSummaryValue(item, depth);
    if (identifier(key) === null || element === null) {
      return null;
    }
    decoded[key] = element;
  }
  return decoded;
}

function decodeWork(value: unknown): Record<string, Record<string, number>> | null {
  const record = asObject(value);
  if (record === null) {
    return null;
  }
  const decoded: Record<string, Record<string, number>> = {};
  for (const [phase, entry] of Object.entries(record)) {
    const numbers = numberRecord(entry);
    if (identifier(phase) === null || numbers === null) {
      return null;
    }
    decoded[phase] = numbers;
  }
  return decoded;
}

function decodeFrameGroups(value: unknown): Record<LaboratoryFrameGroup, string[]> | null {
  const record = asObject(value);
  if (record === null) {
    return null;
  }
  const groups: Partial<Record<LaboratoryFrameGroup, string[]>> = {};
  for (const group of LABORATORY_FRAME_GROUPS) {
    const columns = list(record[group], identifier);
    if (columns === null) {
      return null;
    }
    groups[group] = columns;
  }
  return groups as Record<LaboratoryFrameGroup, string[]>;
}

/** `GET /api/v1/laboratory/recordings/{id}` — one recording's metadata and measurements. */
export function decodeLaboratoryRecordingResponse(
  value: unknown,
): LaboratoryRecordingResponse | null {
  const record = asObject(value);
  if (record === null) {
    return null;
  }
  const recordingId = identifier(record.recording_id);
  const label = text(record.label);
  const kind = oneOf(LABORATORY_RECORDING_KINDS, record.kind);
  const description = text(record.description);
  const timestep = finite(record.timestep_s);
  const duration = finite(record.duration_s);
  const steps = count(record.steps);
  const completed = typeof record.completed === "boolean" ? record.completed : null;
  const failure = text(record.failure);
  const trajectory = digest(record.trajectory_sha256);
  const events = list(record.command_events, decodeEvent);
  const spans = list(record.phase_spans, decodePhaseSpan);
  const summary = decodeSummaryTree(record.summary, 0);
  const extrema = numberRecord(record.extrema);
  const work = decodeWork(record.work);
  const numerics = numberRecord(record.numerics);
  const checks = list(record.checks, decodeCheck);
  const frameCount = count(record.frame_count);
  const period = finite(record.sample_period_s);
  const bodyNames = list(record.body_names, identifier);
  const frameGroups = decodeFrameGroups(record.frame_groups);
  if (
    recordingId === null ||
    label === null ||
    kind === null ||
    description === null ||
    timestep === null ||
    duration === null ||
    steps === null ||
    completed === null ||
    failure === null ||
    trajectory === null ||
    events === null ||
    spans === null ||
    summary === null ||
    extrema === null ||
    work === null ||
    numerics === null ||
    checks === null ||
    frameCount === null ||
    period === null ||
    period <= 0 ||
    bodyNames === null ||
    frameGroups === null
  ) {
    return null;
  }
  return {
    recording_id: recordingId,
    label,
    kind,
    description,
    timestep_s: timestep,
    duration_s: duration,
    steps,
    completed,
    failure,
    trajectory_sha256: trajectory,
    command_events: events,
    phase_spans: spans,
    summary,
    extrema,
    work,
    numerics,
    checks,
    frame_count: frameCount,
    sample_period_s: period,
    body_names: bodyNames,
    frame_groups: frameGroups,
  };
}

/**
 * A number in the summary tree at a dotted path (`"bottom.knee_flexion_deg"`), or `null` when
 * the recording did not publish one there.
 */
export function summaryNumber(summary: SummaryTree, path: string): number | null {
  let node: SummaryValue | undefined = summary;
  for (const key of path.split(".")) {
    if (typeof node !== "object" || node === null || Array.isArray(node)) {
      return null;
    }
    node = (node as SummaryTree)[key];
  }
  return typeof node === "number" ? node : null;
}

/** The measured phases the recording's summary publishes, or none. */
export function measuredPhases(summary: SummaryTree): LaboratoryPhaseSpan[] {
  const phases = summary.measured_phases;
  if (!Array.isArray(phases)) {
    return [];
  }
  return list(phases, decodePhaseSpan) ?? [];
}
