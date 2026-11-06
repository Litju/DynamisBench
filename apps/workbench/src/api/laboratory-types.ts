/**
 * The accepted `/api/v1/laboratory` read models, as the frontend sees them.
 *
 * The laboratory publishes a packaged, SHA-pinned dataset of diagnostic recordings of the
 * MuJoCo barbell back-squat model. Field names are exactly as they travel. The closed
 * vocabularies are restated as `as const` tuples and reviewed against the server's
 * `Literal` types in `dynamisbench/api/laboratory.py`.
 *
 * Nothing here is authority over the model: the workbench renders what the API read from the
 * packaged dataset, and a recording is a diagnostic record of a model run, not sealed evidence.
 */

export const LABORATORY_RECORDING_KINDS = ["nominal", "timestep-companion", "ablation", "run"] as const;
export type LaboratoryRecordingKind = (typeof LABORATORY_RECORDING_KINDS)[number];

export const LABORATORY_GEOM_TYPES = [
  "sphere",
  "capsule",
  "ellipsoid",
  "cylinder",
  "box",
  "plane",
  "other",
] as const;
export type LaboratoryGeomType = (typeof LABORATORY_GEOM_TYPES)[number];

export const LABORATORY_GEOM_ROLES = ["floor", "barbell", "sole", "visual", "segment"] as const;
export type LaboratoryGeomRole = (typeof LABORATORY_GEOM_ROLES)[number];

export const LABORATORY_CHECK_STATUSES = ["pass", "fail", "not_evaluated"] as const;
export type LaboratoryCheckStatus = (typeof LABORATORY_CHECK_STATUSES)[number];

/** The transport groups of a recording's frame columns (`/frames/{group}`). */
export const LABORATORY_FRAME_GROUPS = ["pose", "kinematics", "kinetics"] as const;
export type LaboratoryFrameGroup = (typeof LABORATORY_FRAME_GROUPS)[number];

export type Vec3 = readonly [number, number, number];
export type Quat = readonly [number, number, number, number];

export interface LaboratoryRecordingEntry {
  readonly recording_id: string;
  readonly label: string;
  readonly kind: LaboratoryRecordingKind;
  readonly description: string;
  readonly timestep_s: number;
  readonly duration_s: number;
  readonly frame_count: number;
  readonly trajectory_sha256: string;
  readonly completed: boolean;
  readonly checks_passed: number;
  readonly checks_failed: number;
  readonly checks_not_evaluated: number;
}

/** `GET /api/v1/laboratory` */
export interface LaboratoryIndexResponse {
  readonly dataset_schema: string;
  readonly dataset_id: string;
  readonly manifest_sha256: string;
  readonly generated_with: Readonly<Record<string, string>>;
  readonly claim: string;
  readonly plan: Readonly<Record<string, number>>;
  readonly recordings: readonly LaboratoryRecordingEntry[];
}

export interface LaboratoryBody {
  readonly name: string;
  readonly parent: string;
  readonly mass_kg: number;
  readonly com_m: Vec3;
  readonly principal_inertia_kg_m2: Vec3;
  /** The body frame's position in its parent at the model's reference configuration, m. */
  readonly position_m: Vec3;
  /** The body frame's orientation in its parent (w, x, y, z). */
  readonly quaternion: Quat;
}

export interface LaboratoryGeom {
  readonly name: string;
  readonly body: string;
  readonly type: LaboratoryGeomType;
  readonly size_m: Vec3;
  readonly position_m: Vec3;
  readonly quaternion: Quat;
  readonly role: LaboratoryGeomRole;
}

export interface LaboratoryJoint {
  readonly name: string;
  readonly body: string;
  readonly axis: Vec3;
  readonly range_deg: readonly [number, number];
  readonly torque_capacity_nm: readonly [number, number];
  readonly damping_n_m_s: number;
  readonly position_m: Vec3;
}

export interface LaboratorySubject {
  readonly body_mass_kg: number;
  readonly stature_m: number;
  readonly barbell_mass_kg: number;
  readonly grip_half_width_m: number;
}

export interface LaboratoryContact {
  readonly sole_point_radius_m: number;
  readonly friction: Vec3;
  readonly normal_time_constant_s: number;
  readonly friction_time_constant_s: number;
  readonly loaded_threshold_n: number;
}

/** `GET /api/v1/laboratory/model` */
export interface LaboratoryModelResponse {
  readonly model_sha256: string;
  readonly counts: Readonly<Record<string, number>>;
  readonly total_mass_kg: number;
  readonly bodies: readonly LaboratoryBody[];
  readonly geoms: readonly LaboratoryGeom[];
  readonly joints: readonly LaboratoryJoint[];
  readonly sole_points: readonly string[];
  readonly timestep_s: number;
  readonly integrator: string;
  readonly gravity_m_s2: number;
  readonly subject: LaboratorySubject;
  readonly contact: LaboratoryContact;
}

export interface LaboratoryEvent {
  readonly phase: string;
  readonly t: number;
}

export interface LaboratoryPhaseSpan {
  readonly phase: string;
  readonly start_s: number;
  readonly end_s: number;
}

export interface LaboratoryCheck {
  readonly criterion_id: string;
  readonly group: string;
  readonly label: string;
  readonly unit: string;
  readonly bound: string;
  readonly rationale: string;
  readonly value: number | null;
  readonly status: LaboratoryCheckStatus;
}

/**
 * A free-form measurement summary: nested objects whose leaves are numbers, strings, arrays
 * of numbers, or arrays of such objects. Validated structurally; read with `summaryNumber`.
 */
export type SummaryValue =
  | number
  | string
  | boolean
  | readonly number[]
  | readonly SummaryTree[]
  | SummaryTree;
export interface SummaryTree {
  readonly [key: string]: SummaryValue;
}

/** `GET /api/v1/laboratory/recordings/{id}` */
export interface LaboratoryRecordingResponse {
  readonly recording_id: string;
  readonly label: string;
  readonly kind: LaboratoryRecordingKind;
  readonly description: string;
  readonly timestep_s: number;
  readonly duration_s: number;
  readonly steps: number;
  readonly completed: boolean;
  readonly failure: string;
  readonly trajectory_sha256: string;
  readonly command_events: readonly LaboratoryEvent[];
  readonly phase_spans: readonly LaboratoryPhaseSpan[];
  readonly summary: SummaryTree;
  readonly extrema: Readonly<Record<string, number>>;
  readonly work: Readonly<Record<string, Readonly<Record<string, number>>>>;
  readonly numerics: Readonly<Record<string, number>>;
  readonly checks: readonly LaboratoryCheck[];
  readonly frame_count: number;
  readonly sample_period_s: number;
  readonly body_names: readonly string[];
  readonly frame_groups: Readonly<Record<LaboratoryFrameGroup, readonly string[]>>;
}

/**
 * One frame group, decoded from its Arrow IPC stream: `t` and named `float64` columns, one row
 * per 10 ms snapshot. Columns are typed arrays and are never copied per frame.
 */
export interface LaboratoryFrameTable {
  readonly group: LaboratoryFrameGroup;
  readonly count: number;
  readonly t: Float64Array;
  readonly columns: ReadonlyMap<string, Float64Array>;
}
