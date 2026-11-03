/**
 * Centralised demo adapter for the workbench prototype.
 *
 * Every value here carries a data-source tag. Values tagged AUTHORITY are transcribed by hand
 * from the accepted repository (path given in `src`). Nothing in this prototype imports or
 * calls the Python core, the FastAPI sidecar or the MuJoCo worker.
 */

export type SourceTag =
  | 'AUTHORITY' // transcribed from accepted repository source
  | 'QUALIFIED' // accepted + qualified per RES-550 / RES-555 audit (values live in CI receipts)
  | 'FIXTURE' // python/tests/fixtures test-corpus definition (schema test data, not a release)
  | 'EXTERNAL' // third-party reference model (MyoSim, Apache-2.0); not DynamisBench authority
  | 'RECOMPUTED' // computed in the browser by this prototype from AUTHORITY constants
  | 'DESIGN_ONLY' // illustrative geometry / interaction, no scientific authority
  | 'NOT_IMPLEMENTED' // stage or capability has no implementation yet
  | 'NOT_ASSESSED'; // no assessment exists; never read as failure

export const TAG_INFO: Record<SourceTag, { label: string; tone: string; text: string }> = {
  AUTHORITY: { label: 'Authority', tone: 'auth', text: 'Transcribed from accepted repository source.' },
  QUALIFIED: { label: 'Qualified', tone: 'qual', text: 'Accepted and qualified (RES-550); numeric receipts are CI artifacts, not in this repo.' },
  FIXTURE: { label: 'Test fixture', tone: 'fix', text: 'Schema test-corpus definition (python/tests/fixtures). Not a released benchmark, not data.' },
  EXTERNAL: { label: 'External reference model', tone: 'ext', text: 'MyoSim MyoLegs/MyoTorso (Apache-2.0, from Rajagopal 2016, MIT). Real model data, but not a DynamisBench realization and not qualified.' },
  RECOMPUTED: { label: 'Prototype computation', tone: 'calc', text: 'Computed in this browser from authority constants. Not MuJoCo output, not evidence.' },
  DESIGN_ONLY: { label: 'Design only', tone: 'design', text: 'Illustrative representation. No scientific authority.' },
  NOT_IMPLEMENTED: { label: 'Not implemented', tone: 'none', text: 'No implementation exists in DynamisBench yet.' },
  NOT_ASSESSED: { label: 'Not assessed', tone: 'none', text: 'No assessment exists. Absence of evidence is not a failed validation.' },
};

/* ---------- RES-550 fixed reference: python/src/dynamisbench/adapters/mujoco/reference.py ---------- */

export const REF = {
  src: 'python/src/dynamisbench/adapters/mujoco/reference.py',
  adapterId: 'dynamisbench.mujoco.reference',
  adapterVersion: '0.1.0',
  engine: 'mujoco',
  engineVersion: '3.17.0',
  pythonVersion: '3.12.13',
  benchmarkId: 'db.reference.pendulum',
  benchmarkVersion: '1.0.0',
  scenarioId: 'sc.reference.pendulum',
  scenarioVersion: '1.0.0',
  realizationId: 'rl.mujoco.reference-pendulum',
  realizationVersion: '1.0.0',
  sutId: 'sut.reference.pendulum',
  sutVersion: '1.0.0',
  environmentVersion: '1.0.0',
  outcome: 'reference-state',
  seed: 0,
  modelSourcePath: 'models/reference/pendulum.xml',
  modelAsset: 'python/src/dynamisbench/adapters/mujoco/assets/reference_pendulum.xml',
  modelSha256: 'eac679a723ccfebb48ea5ee40692fa6ee38f965772b484b94b827be6b9dbfdfd',
  digests: {
    benchmark: '7998fdd62b5d3b29fa5c04a50d9dce9daf506703777e2cc3b51b3ca69f88f7bd',
    scenario: 'ef31253d815a43b7893e9628e03be6632f385dbd75b568ce816a561261057ccb',
    realization: 'f31340c60166f8f37b6a4609929ef7ccf23554b294fb57889e4644d04c86d8cb',
    sut: '7dd9bb16f04c8b15bc012b87660b55d24bd7e6108daffafeaf84f62c719a51ee',
    'environment (windows-x86-64)': '5391e3ba772aa7fa3b7d01f42a56585f24a4525527e6cd0ba5e672f447ae5231',
    'environment (linux-x86-64)': '8652ad6cc054383eb301183f3036e01f673ccbe8e93b807e4c0968ffa5a73963',
  } as Record<string, string>,
  massKg: 1.0,
  comDistanceM: 1.0,
  comInertiaKgM2: 0.001,
  hingeInertiaKgM2: 0.001 + 1.0 * 1.0 ** 2,
  gravity: 9.80665,
  theta0: 0.5235987755982988,
  omega0: 0.0,
  timestep: 0.001,
  duration: 2.0,
  steps: 2000,
  integrator: 'RK4',
  solver: 'Newton',
  iterations: 100,
  tolerance: 1e-12,
  checkpoints: [0.0, 0.5, 1.0, 1.5, 2.0],
  controlPolicy: 'zero control; the model has no actuators',
  jointConstraints: 'none; one unconstrained hinge',
  contactPolicy: 'no geoms; no contacts',
  randomnessPolicy: 'no stochastic process; the RunSpec seed is recorded, not consumed',
  nativeStateLayout: 'qpos[0]=hinge angle (rad); qvel[0]=hinge angular velocity (rad/s)',
  capabilities: ['forward_dynamics'],
};

/* qualification_criteria.py — predeclared numerical acceptance criteria (qualification-only). */
export const CRITERIA = {
  src: 'python/src/dynamisbench/adapters/mujoco/qualification_criteria.py',
  angle_rad: 1e-8,
  angular_velocity_rad_s: 1e-7,
  energy_relative: 1e-9,
  energy_reconstruction_j: 1e-12,
  period_s: 1e-4,
  velocity_consistency_rad_s: 1e-3,
  final_time_s: 1e-9,
  refinement_min_ratio: 8.0,
  refinement_final_angle_rad: 1e-8,
  refinementTimesteps: [0.01, 0.005, 0.0025, 0.00125], // qualification.py _REFINEMENT_TIMESTEPS_S
  crossPlatform: { angle: 1e-9, angularVelocity: 1e-8, period: 1e-5 },
  claimLimit:
    'Numerical solution verification of the fixed MuJoCo planar-pendulum reference against an independent nonlinear pendulum solve and a finite-amplitude period. This is not human biomechanical validation, not a scientific benchmark acceptance, not VVUQ PASS, and not sealed native evidence.',
};

/* reference_case.py — benchmark release text (verbatim). */
export const PENDULUM_RELEASE = {
  src: 'python/src/dynamisbench/adapters/mujoco/reference_case.py',
  label: 'Synthetic planar pendulum adapter reference',
  intendedUse:
    'Numerical and process-contract verification of the first real DynamisBench MuJoCo adapter on a low-dimensional rigid-body system.',
  intendedNonUse:
    'Not a human-movement benchmark, not a DB-LCMJ20 realization, and not evidence of biomechanical validity.',
  conceptualModel:
    'One rigid body on a frictionless hinge with a point mass at 1 m, uniform standard gravity, no contacts and no actuation.',
  claimCeiling:
    'Agreement with an independent nonlinear pendulum solution within predeclared numerical tolerances on the qualified environment; no scientific validation.',
  assumptions: ['Rigid body, ideal hinge, uniform gravity, no damping, no contacts, no actuation, double precision, deterministic execution.'],
  applicability: ['Single planar pendulum, zero control, 30 degree initial angle, 2 s horizon.'],
  discrepancies: ['The reference is synthetic; it is not a physical experiment or a human model.'],
  uncertainty: ['No stochastic process; only numerical integration error is expected.'],
  credibility: ['unit_problem'],
  reference: {
    id: 'r.reference.pendulum',
    label: 'Independent nonlinear pendulum reference',
    category: 'solution_verification',
    origin: 'synthetic',
    license: 'CC0-1.0',
  },
  metric: { id: 'm.reference.hinge-angle.mean', label: 'Mean hinge angle', note: 'Placeholder statistic. No assessment is computed in RES-550.' },
  factor: 'f.reference.gravity',
};

/* python/tests/fixtures/domain/valid/*.json — LCMJ20 schema fixtures (test data). */
export const LCMJ20 = {
  src: 'python/tests/fixtures/domain/valid/benchmark_release.lcmj20.json',
  benchmarkId: 'db.lcmj20',
  label: 'Benchmark Family 001 — loaded countermovement jump',
  intendedUse: 'Comparative assessment of human-movement models on a jump task.',
  intendedNonUse: 'Not a clinical assessment and not a fatigue or injury model.',
  conceptualModel: 'A planar sagittal multi-segment subject on a rigid force plate.',
  claimCeiling: 'Relative model comparison within the stated applicability domain.',
  applicability: ['young healthy adults', 'loaded two-footed jump'],
  assumptions: ['Rigid supporting surface.'],
  discrepancies: ['Contact compliance is not identified.', 'Contact stiffness is not calibrated against the reference plate. (realization)'],
  uncertainty: ['Marker placement variability dominates jump height uncertainty.'],
  credibility: ['benchmark_reference_case', 'complete_system'],
  scenario: { id: 'sc.loaded-cmj', label: 'Loaded countermovement jump', duration: 2.0, event: { id: 'takeoff', t: 0.3, tol: 0.005 } },
  realization: {
    id: 'rl.mujoco.loaded-cmj',
    engineSpecifier: '== 3.3.0',
    integrator: 'implicitfast',
    capabilities: ['analysis', 'forward_dynamics', 'interactive_dynamics', 'inverse_dynamics', 'state_snapshot', 'trajectory_optimization'],
    asset: { id: 'subject-model', path: 'models/realization/subject.xml', sha256: '0'.repeat(64) },
    mappings: [
      { quantity: 'q.foot.vertical_force', source: 'force_sensor_foot', transform: 'sensor-nearest 1.0.0' },
      { quantity: 'q.jump.height', source: 'force_sensor_foot', transform: 'sensor-nearest 1.0.0' },
    ],
  },
  reference: { id: 'r.baseline-0', category: 'model_validation', origin: 'experimental', citation: null as string | null },
  metric: { id: 'm.jump_height.rmse', label: 'Jump height RMSE', criterion: '< 0.01 m', window: '0.0–1.0 s' },
  study: {
    id: 'study.contact-stiffness-sensitivity',
    label: 'Contact stiffness sensitivity',
    question: 'How much does jump height depend on contact stiffness?',
    plan: 'Aggregate per-replicate canonical jump height, then report the mean and half-range across seeds.',
    replicates: 3,
    seeds: [11, 12, 13],
    requires: ['forward_dynamics', 'state_snapshot'],
    factors: [
      { id: 'f.contact-stiffness', label: 'Contact stiffness scale', role: 'factor', dist: 'uniform', lower: 0.8, upper: 1.2, unit: '1', target: 'rl.mujoco.loaded-cmj · contact-stiffness' },
      { id: 'f.gravity', label: 'Gravitational acceleration', role: 'controlled', dist: 'point', value: 9.80665, unit: 'm·s⁻²', target: 'rl.mujoco.loaded-cmj · gravity' },
    ],
  },
};

/* execution/contracts.py */
export const LIFECYCLE = ['preflight_ready', 'refused', 'starting', 'running', 'canceling', 'canceled', 'timed_out', 'failed', 'completed'] as const;
export type Lifecycle = (typeof LIFECYCLE)[number] | 'draft';
export const TERMINAL: Lifecycle[] = ['refused', 'canceled', 'timed_out', 'failed', 'completed'];

export type RefusalCode =
  | 'invalid_run_spec'
  | 'fingerprint_mismatch'
  | 'realization_identity_mismatch'
  | 'environment_identity_mismatch'
  | 'adapter_engine_mismatch'
  | 'unknown_capability'
  | 'unsupported_capability'
  | 'unstaged_asset'
  | 'asset_digest_mismatch'
  | 'forbidden_path'
  | 'duplicate_execution'
  | 'worker_timeout'
  | 'worker_canceled'
  | 'worker_failed'
  | 'worker_abnormal_exit';

export const STATUS_MAP = [
  { area: 'Workspace discovery & inspection API', status: 'IMPLEMENTED', dep: 'M2 (RES-380)' },
  { area: 'Domain definitions, semantic identity, planning/RunSpec compiler', status: 'IMPLEMENTED', dep: 'M1' },
  { area: 'Isolated worker supervisor + capability preflight', status: 'IMPLEMENTED', dep: 'RES-549 (outside app)' },
  { area: 'MuJoCo fixed reference pendulum forward dynamics', status: 'QUALIFIED', dep: 'RES-550, Windows + Linux receipts' },
  { area: 'Production run / cancel API from the app', status: 'NOT_IMPLEMENTED', dep: 'no accepted endpoint' },
  { area: 'Content-addressed inputs + native evidence sealing', status: 'NOT_IMPLEMENTED', dep: 'RES-555 / RES-561' },
  { area: 'Canonical quantity / assessment provenance', status: 'PLANNED', dep: 'M4 RES-569' },
  { area: 'Multibody/contact verification + empirical validation', status: 'PLANNED', dep: 'M5 RES-570' },
  { area: 'MuJoCo vs OpenSim/Moco comparison', status: 'PLANNED', dep: 'M7 RES-571' },
  { area: 'Human musculoskeletal model, measured data, UQ execution', status: 'NOT_IMPLEMENTED', dep: 'no licensed asset or dataset' },
];
