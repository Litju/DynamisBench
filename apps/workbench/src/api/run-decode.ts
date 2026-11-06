/**
 * Runtime decoders for the study-catalogue and run read models.
 *
 * The discipline of `decode.ts` and `laboratory-decode.ts`: total functions over `unknown` that
 * return a fresh value assembled from validated fields, or `null` when the body is not the
 * published read model. Digests must be 64 lowercase hex, numbers must be finite, closed
 * vocabularies are closed. A run identifier must be the shape the run service mints, so an
 * identifier can never smuggle a path segment into a later request.
 *
 * The evidence read model is *projected*: the sealed run record, provenance and assessment are
 * large documents whose authority is the bundle; the workbench keeps the links it draws and
 * checks the ones it relies on (every digest it shows is a digest).
 */

import {
  type AdapterCheckView,
  FACTOR_DISPLAYS,
  RUN_PROGRESS_STATES,
  RUN_READ_STATUSES,
  type AdapterIdentity,
  type BundleFile,
  type BundleVerification,
  type CatalogueFactor,
  type CatalogueStudy,
  type DefinitionIdentity,
  type MetricView,
  type OutcomeCounts,
  type PreflightResponse,
  type ProvenanceView,
  type RunEntry,
  type RunEvidenceResponse,
  type RunListResponse,
  type RunProgressResponse,
  type RunRefusal,
  type RunStatus,
  type StudyCatalogueResponse,
  type VerificationCheckView,
} from "./run-types";

type JsonObject = Record<string, unknown>;

const SHA256 = /^[0-9a-f]{64}$/;
const IDENTIFIER = /^[A-Za-z0-9_.:@-]{1,128}$/;
/** `run-<10 hex of the execution fingerprint>-<3 digits>`, as the run service mints it. */
export const RUN_ID = /^run-[0-9a-f]{10}-\d{3}$/;
const MAX_TEXT = 2_000;

function asObject(value: unknown): JsonObject | null {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? (value as JsonObject) : null;
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

function runId(value: unknown): string | null {
  return typeof value === "string" && RUN_ID.test(value) ? value : null;
}

function bool(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

/** `null` stays `null`; anything else must decode. `undefined` marks a failure. */
function nullable<T>(value: unknown, decode: (item: unknown) => T | null): T | null | undefined {
  if (value === null) {
    return null;
  }
  const decoded = decode(value);
  return decoded === null ? undefined : decoded;
}

function oneOf<T extends string>(vocabulary: readonly T[], value: unknown): T | null {
  return vocabulary.some((member) => member === value) ? (value as T) : null;
}

function record<T>(value: unknown, decodeKey: (key: string) => string | null, decodeValue: (item: unknown) => T | null): Record<string, T> | null {
  const object = asObject(value);
  if (object === null) {
    return null;
  }
  const decoded: Record<string, T> = {};
  for (const [key, item] of Object.entries(object)) {
    const element = decodeValue(item);
    if (decodeKey(key) === null || element === null) {
      return null;
    }
    decoded[key] = element;
  }
  return decoded;
}

const numbers = (value: unknown) => record(value, identifier, finite);
const relativePath = (value: unknown): string | null =>
  typeof value === "string" && /^[A-Za-z0-9_.-]+(?:\/[A-Za-z0-9_.-]+)*$/.test(value) && !value.split("/").includes("..") && value.length <= 256
    ? value
    : null;

// --- catalogue --------------------------------------------------------------------------------

function decodeFactor(value: unknown): CatalogueFactor | null {
  const object = asObject(value);
  if (object === null) {
    return null;
  }
  const factorId = identifier(object.factor_id);
  const label = text(object.label);
  const quantityId = identifier(object.quantity_id);
  const unit = text(object.unit);
  const lower = finite(object.lower);
  const upper = finite(object.upper);
  const nominal = finite(object.nominal);
  const display = oneOf(FACTOR_DISPLAYS, object.display);
  const choices = list(object.choices, finite);
  if (
    factorId === null ||
    label === null ||
    quantityId === null ||
    unit === null ||
    lower === null ||
    upper === null ||
    nominal === null ||
    display === null ||
    choices === null ||
    !(lower <= nominal && nominal <= upper) ||
    choices.some((choice) => choice < lower || choice > upper)
  ) {
    return null;
  }
  return { factor_id: factorId, label, quantity_id: quantityId, unit, lower, upper, nominal, display, choices };
}

function decodeStudy(value: unknown): CatalogueStudy | null {
  const object = asObject(value);
  const realization = asObject(object?.realization);
  if (object === null || realization === null) {
    return null;
  }
  const studyId = identifier(object.study_id);
  const version = text(object.version);
  const label = text(object.label);
  const question = text(object.research_question);
  const realizationId = identifier(realization.identifier);
  const realizationVersion = text(realization.version);
  const realizationLabel = text(realization.label);
  const platform = text(object.platform);
  const environment = text(object.environment);
  const executable = bool(object.executable);
  const reason = text(object.reason);
  const factors = list(object.factors, decodeFactor);
  const presets = record(object.presets, identifier, numbers);
  const limitations = list(object.limitations, text);
  if (
    studyId === null ||
    version === null ||
    label === null ||
    question === null ||
    realizationId === null ||
    realizationVersion === null ||
    realizationLabel === null ||
    platform === null ||
    environment === null ||
    executable === null ||
    reason === null ||
    factors === null ||
    presets === null ||
    limitations === null
  ) {
    return null;
  }
  const known = new Set(factors.map((factor) => factor.factor_id));
  if (known.size !== factors.length || !Object.values(presets).every((preset) => Object.keys(preset).every((key) => known.has(key)))) {
    return null;
  }
  return {
    study_id: studyId,
    version,
    label,
    research_question: question,
    realization: { identifier: realizationId, version: realizationVersion, label: realizationLabel },
    platform,
    environment,
    executable,
    reason,
    factors,
    presets,
    limitations,
  };
}

/** `GET /workspaces/{id}/studies` */
export function decodeStudyCatalogueResponse(value: unknown): StudyCatalogueResponse | null {
  const object = asObject(value);
  if (object === null) {
    return null;
  }
  const studies = list(object.studies, decodeStudy);
  const invalid = count(object.invalid_documents);
  if (studies === null || invalid === null) {
    return null;
  }
  return { studies, invalid_documents: invalid };
}

// --- preflight and progress -------------------------------------------------------------------

function decodeRefusal(value: unknown): RunRefusal | null {
  const object = asObject(value);
  const code = identifier(object?.code);
  const message = text(object?.message);
  return code === null || message === null ? null : { code, message };
}

function decodeDefinition(value: unknown): DefinitionIdentity | null {
  const object = asObject(value);
  const id = identifier(object?.identifier);
  const version = text(object?.version);
  const semantic = digest(object?.semantic_digest);
  return id === null || version === null || semantic === null ? null : { identifier: id, version, semantic_digest: semantic };
}

function decodeAdapter(value: unknown): AdapterIdentity | null {
  const object = asObject(value);
  if (object === null) {
    return null;
  }
  const adapterId = identifier(object.adapter_id);
  const adapterVersion = text(object.adapter_version);
  const implementation = nullable(object.implementation_digest, digest);
  const engine = nullable(object.engine, text);
  const engineVersion = nullable(object.engine_version, text);
  const python = nullable(object.python_version, text);
  const platform = nullable(object.platform, text);
  const closure = nullable(object.dependency_closure_digest, digest);
  if (
    adapterId === null ||
    adapterVersion === null ||
    implementation === undefined ||
    engine === undefined ||
    engineVersion === undefined ||
    python === undefined ||
    platform === undefined ||
    closure === undefined
  ) {
    return null;
  }
  return {
    adapter_id: adapterId,
    adapter_version: adapterVersion,
    implementation_digest: implementation,
    engine,
    engine_version: engineVersion,
    python_version: python,
    platform,
    dependency_closure_digest: closure,
  };
}

/** `POST /workspaces/{id}/runs/preflight` */
export function decodePreflightResponse(value: unknown): PreflightResponse | null {
  const object = asObject(value);
  if (object === null) {
    return null;
  }
  const decision = oneOf(["ready", "refused"] as const, object.decision);
  const refusals = list(object.refusals, decodeRefusal);
  const request = nullable(object.request_digest, digest);
  const fingerprint = digest(object.execution_fingerprint);
  const study = decodeDefinition(object.study);
  const definitions = record(object.definitions, identifier, decodeDefinition);
  const configuration = numbers(object.configuration);
  const adapter = decodeAdapter(object.adapter);
  const timeout = finite(object.timeout_seconds);
  if (
    decision === null ||
    refusals === null ||
    request === undefined ||
    fingerprint === null ||
    study === null ||
    definitions === null ||
    configuration === null ||
    adapter === null ||
    timeout === null ||
    // A ready decision has no refusals; a refused one names at least one.
    (decision === "ready") !== (refusals.length === 0)
  ) {
    return null;
  }
  return {
    decision,
    refusals,
    request_digest: request,
    execution_fingerprint: fingerprint,
    study,
    definitions,
    configuration,
    adapter,
    timeout_seconds: timeout,
  };
}

/** `POST /runs`, `GET /runs/{run}/progress`, `POST /runs/{run}/cancel` */
export function decodeRunProgressResponse(value: unknown): RunProgressResponse | null {
  const object = asObject(value);
  if (object === null) {
    return null;
  }
  const id = runId(object.run_id);
  const studyId = identifier(object.study_id);
  const caseId = identifier(object.case_id);
  const configuration = numbers(object.configuration);
  const state = oneOf(RUN_PROGRESS_STATES, object.state);
  const active = bool(object.active);
  const lifecycle = list(object.lifecycle, identifier);
  const refusals = list(object.refusals, decodeRefusal);
  const message = text(object.message);
  const execution = nullable(object.execution_evidence_digest, digest);
  const derived = nullable(object.derived_evidence_digest, digest);
  const outcome = nullable(object.derived_outcome, identifier);
  const elapsed = finite(object.elapsed_s);
  if (
    id === null ||
    studyId === null ||
    caseId === null ||
    configuration === null ||
    state === null ||
    active === null ||
    lifecycle === null ||
    refusals === null ||
    message === null ||
    execution === undefined ||
    derived === undefined ||
    outcome === undefined ||
    elapsed === null
  ) {
    return null;
  }
  return {
    run_id: id,
    study_id: studyId,
    case_id: caseId,
    configuration,
    state,
    active,
    lifecycle,
    refusals,
    message,
    execution_evidence_digest: execution,
    derived_evidence_digest: derived,
    derived_outcome: outcome,
    elapsed_s: elapsed,
  };
}

// --- run list -----------------------------------------------------------------------------------

function decodeCounts(value: unknown): OutcomeCounts | null {
  const object = asObject(value);
  if (object === null) {
    return null;
  }
  const pass = count(object.pass);
  const fail = count(object.fail);
  const notEvaluated = count(object.not_evaluated);
  const reported = count(object.reported ?? 0);
  if (pass === null || fail === null || notEvaluated === null || reported === null) {
    return null;
  }
  return { pass, fail, not_evaluated: notEvaluated, reported };
}

function decodeRunEntry(value: unknown): RunEntry | null {
  const object = asObject(value);
  if (object === null) {
    return null;
  }
  const id = runId(object.run_id);
  const status = oneOf<RunStatus>([...RUN_READ_STATUSES, ...RUN_PROGRESS_STATES], object.status);
  const reasons = list(object.reasons, text);
  const caseId = typeof object.case_id === "string" && (object.case_id === "" || IDENTIFIER.test(object.case_id)) ? object.case_id : null;
  const configuration = numbers(object.configuration);
  const progress = nullable(object.progress, decodeRunProgressResponse);
  const execution = nullable(object.execution_evidence_digest, digest);
  const derived = nullable(object.derived_evidence_digest, digest);
  const trajectory = nullable(object.trajectory_sha256, digest);
  const completed = nullable(object.completed, bool);
  const timestep = nullable(object.timestep_s, finite);
  const duration = nullable(object.duration_s, finite);
  const frames = nullable(object.frame_count, count);
  const checks = decodeCounts(object.checks);
  const metrics = decodeCounts(object.metrics);
  const verification = decodeCounts(object.verification);
  if (
    id === null ||
    status === null ||
    reasons === null ||
    caseId === null ||
    configuration === null ||
    progress === undefined ||
    execution === undefined ||
    derived === undefined ||
    trajectory === undefined ||
    completed === undefined ||
    timestep === undefined ||
    duration === undefined ||
    frames === undefined ||
    checks === null ||
    metrics === null ||
    verification === null ||
    (progress !== null && progress.run_id !== id)
  ) {
    return null;
  }
  return {
    run_id: id,
    status,
    reasons,
    case_id: caseId,
    configuration,
    progress,
    execution_evidence_digest: execution,
    derived_evidence_digest: derived,
    trajectory_sha256: trajectory,
    completed,
    timestep_s: timestep,
    duration_s: duration,
    frame_count: frames,
    checks,
    metrics,
    verification,
  };
}

/** `GET /workspaces/{id}/runs` */
export function decodeRunListResponse(value: unknown): RunListResponse | null {
  const object = asObject(value);
  const runs = list(object?.runs, decodeRunEntry);
  if (runs === null || new Set(runs.map((run) => run.run_id)).size !== runs.length) {
    return null;
  }
  return { runs };
}

// --- evidence -------------------------------------------------------------------------------------

function decodeBundleFile(value: unknown): BundleFile | null {
  const object = asObject(value);
  const path = relativePath(object?.path);
  const sha = digest(object?.sha256);
  const size = count(object?.size_bytes);
  return path === null || sha === null || size === null ? null : { path, sha256: sha, size_bytes: size };
}

function decodeBundle(value: unknown): BundleVerification | null {
  const object = asObject(value);
  if (object === null) {
    return null;
  }
  const valid = bool(object.valid);
  const defects = list(object.defects, text);
  const id = nullable(object.run_id ?? null, text);
  const outcome = nullable(object.outcome ?? null, identifier);
  const evidence = nullable(object.evidence_digest ?? null, digest);
  const files = list(object.files, decodeBundleFile);
  if (valid === null || defects === null || id === undefined || outcome === undefined || evidence === undefined || files === null) {
    return null;
  }
  return { valid, defects, run_id: id, outcome, evidence_digest: evidence, files };
}

function decodeVerificationCheck(value: unknown): VerificationCheckView | null {
  const object = asObject(value);
  if (object === null) {
    return null;
  }
  const checkId = identifier(object.check_id);
  const category = text(object.category);
  const label = text(object.label);
  const method = text(object.method);
  const unit = text(object.unit);
  const checkValue = nullable(object.value ?? null, finite);
  const tolerance = nullable(object.tolerance ?? null, finite);
  const status = identifier(object.status);
  const detail = text(object.detail ?? "");
  if (
    checkId === null ||
    category === null ||
    label === null ||
    method === null ||
    unit === null ||
    checkValue === undefined ||
    tolerance === undefined ||
    status === null ||
    detail === null
  ) {
    return null;
  }
  return { check_id: checkId, category, label, method, unit, value: checkValue, tolerance, status, detail };
}

function decodeMetric(value: unknown): MetricView | null {
  const object = asObject(value);
  if (object === null) {
    return null;
  }
  const metricId = identifier(object.metric_id);
  const quantityId = identifier(object.quantity_id);
  const label = text(object.label);
  const description = text(object.description);
  const aggregation = text(object.aggregation);
  const unit = text(object.unit);
  const metricValue = nullable(object.value ?? null, finite);
  const operator = nullable(object.operator ?? null, identifier);
  const threshold = nullable(object.threshold ?? null, finite);
  const status = identifier(object.status);
  if (
    metricId === null ||
    quantityId === null ||
    label === null ||
    description === null ||
    aggregation === null ||
    unit === null ||
    metricValue === undefined ||
    operator === undefined ||
    threshold === undefined ||
    status === null
  ) {
    return null;
  }
  return {
    metric_id: metricId,
    quantity_id: quantityId,
    label,
    description,
    aggregation,
    unit,
    value: metricValue,
    operator,
    threshold,
    status,
  };
}

function decodeProvenance(value: unknown): ProvenanceView | null | undefined {
  const object = asObject(value);
  if (object === null) {
    return undefined;
  }
  if (Object.keys(object).length === 0) {
    return null; // nothing could be read from a rejected derived bundle
  }
  const execution = asObject(object.execution);
  const adapter = asObject(object.adapter);
  if (execution === null || adapter === null) {
    return undefined;
  }
  const executionRun = runId(execution.run_id);
  const executionDigest = digest(execution.evidence_digest);
  const executionOutcome = identifier(execution.outcome);
  const native = record(execution.native, relativePath, digest);
  const sources = record(object.source_documents, identifier, relativePath);
  const definitionsObject = asObject(object.definitions);
  const fingerprint = digest(object.execution_fingerprint);
  const inputs = digest(object.input_manifest_digest);
  const request = nullable(object.preflight_request_digest ?? null, digest);
  const adapterId = identifier(adapter.adapter_id);
  const adapterVersion = text(adapter.adapter_version);
  const engine = text(adapter.engine);
  const engineVersion = text(adapter.engine_version);
  const implementation = nullable(adapter.implementation_digest ?? null, digest);
  const trajectory = nullable(object.trajectory_sha256 ?? null, digest);
  const canonical = record(object.canonical, relativePath, digest);
  const derivation = record(object.derivation_implementation, (key) => (key.length <= 128 ? key : null), digest);
  const claim = text(object.claim);
  if (
    executionRun === null ||
    executionDigest === null ||
    executionOutcome === null ||
    native === null ||
    sources === null ||
    definitionsObject === null ||
    fingerprint === null ||
    inputs === null ||
    request === undefined ||
    adapterId === null ||
    adapterVersion === null ||
    engine === null ||
    engineVersion === null ||
    implementation === undefined ||
    trajectory === undefined ||
    canonical === null ||
    derivation === null ||
    claim === null
  ) {
    return undefined;
  }
  const definitions: Record<string, DefinitionIdentity> = {};
  for (const [key, entry] of Object.entries(definitionsObject)) {
    const reference = asObject(entry);
    const semantic = asObject(reference?.semantic_digest);
    const decoded = decodeDefinition({
      identifier: reference?.identifier,
      version: reference?.version,
      semantic_digest: semantic?.hex,
    });
    if (identifier(key) === null || decoded === null) {
      return undefined;
    }
    definitions[key] = decoded;
  }
  return {
    execution_run_id: executionRun,
    execution_evidence_digest: executionDigest,
    execution_outcome: executionOutcome,
    native,
    source_documents: sources,
    definitions,
    execution_fingerprint: fingerprint,
    input_manifest_digest: inputs,
    preflight_request_digest: request,
    adapter: {
      adapter_id: adapterId,
      adapter_version: adapterVersion,
      engine,
      engine_version: engineVersion,
      implementation_digest: implementation,
    },
    trajectory_sha256: trajectory,
    canonical,
    derivation_implementation: derivation,
    claim,
  };
}

function decodeAdapterCheck(value: unknown): AdapterCheckView | null {
  const object = asObject(value);
  if (object === null) {
    return null;
  }
  const criterionId = identifier(object.criterion_id);
  const group = text(object.group);
  const label = text(object.label);
  const unit = text(object.unit);
  const bound = text(object.bound);
  const rationale = text(object.rationale);
  const checkValue = nullable(object.value ?? null, finite);
  const status = identifier(object.status);
  if (
    criterionId === null ||
    group === null ||
    label === null ||
    unit === null ||
    bound === null ||
    rationale === null ||
    checkValue === undefined ||
    status === null
  ) {
    return null;
  }
  return { criterion_id: criterionId, group, label, unit, bound, rationale, value: checkValue, status };
}

/** `GET /workspaces/{id}/runs/{run}/evidence` */
export function decodeRunEvidenceResponse(value: unknown): RunEvidenceResponse | null {
  const object = asObject(value);
  if (object === null) {
    return null;
  }
  const id = runId(object.run_id);
  const status = oneOf(RUN_READ_STATUSES, object.status);
  const reasons = list(object.reasons, text);
  const execution = decodeBundle(object.execution);
  const derived = decodeBundle(object.derived);
  const runRecord = asObject(object.run_record);
  const provenance = decodeProvenance(object.provenance);
  const verification = list(object.verification, decodeVerificationCheck);
  const assessment = asObject(object.assessment);
  if (
    id === null ||
    status === null ||
    reasons === null ||
    execution === null ||
    derived === null ||
    runRecord === null ||
    provenance === undefined ||
    verification === null ||
    assessment === null
  ) {
    return null;
  }
  const factorCase = asObject(runRecord.factor_case);
  const caseId = factorCase === null ? null : identifier(factorCase.case_id);
  const configuration = factorCase === null ? {} : numbers(factorCase.values);
  const failure = runRecord.failure === undefined || runRecord.failure === null ? null : text(runRecord.failure);
  const metrics = assessment.metrics === undefined ? [] : list(assessment.metrics, decodeMetric);
  const adapterChecks = assessment.adapter_checks === undefined ? [] : list(assessment.adapter_checks, decodeAdapterCheck);
  const claim = assessment.claim ?? runRecord.claim ?? null;
  if (configuration === null || metrics === null || adapterChecks === null || (claim !== null && text(claim) === null)) {
    return null;
  }
  // A verified run has both seals, its provenance and its verification; anything less is not.
  if (status === "verified" && (!execution.valid || !derived.valid || provenance === null || verification.length === 0)) {
    return null;
  }
  return {
    run_id: id,
    status,
    reasons,
    execution,
    derived,
    case_id: caseId,
    configuration,
    failure,
    provenance,
    verification,
    metrics,
    adapter_checks: adapterChecks,
    claim: claim === null ? null : (claim as string),
  };
}
