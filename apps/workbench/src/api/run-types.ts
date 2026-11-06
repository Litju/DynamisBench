/**
 * The accepted `/api/v1/workspaces/{id}/studies` and `/runs` read models, as the frontend sees
 * them.
 *
 * Runs are planned, admitted, executed, sealed, normalized, verified and assessed by the
 * application's run service (`python/src/dynamisbench/pipeline`), in the isolated worker the
 * execution boundary supervises. The workbench only *asks*: it sends a study identifier and a
 * configuration in canonical units, and renders what the service answered — including its
 * refusals. Every run read is re-verified from sealed evidence by the service on every request;
 * a run that does not verify is answered as `rejected` with its reasons, never as data.
 *
 * Field names are exactly as they travel; vocabularies are restated as `as const` tuples and
 * reviewed against the server's `Literal` types in `dynamisbench/api/runs.py`.
 */

/** How the workbench presents a factor's canonical value (presentation only). */
export const FACTOR_DISPLAYS = ["degree", "millisecond", "second", "unitless"] as const;
export type FactorDisplay = (typeof FACTOR_DISPLAYS)[number];

export interface CatalogueFactor {
  readonly factor_id: string;
  readonly label: string;
  readonly quantity_id: string;
  /** The canonical unit of the value sent and stored (`1` for radians and gains). */
  readonly unit: string;
  readonly lower: number;
  readonly upper: number;
  readonly nominal: number;
  readonly display: FactorDisplay;
  /** When not empty, the only admissible values, exactly as they must be sent. */
  readonly choices: readonly number[];
}

export interface CatalogueStudy {
  readonly study_id: string;
  readonly version: string;
  readonly label: string;
  readonly research_question: string;
  readonly realization: { readonly identifier: string; readonly version: string; readonly label: string };
  readonly platform: string;
  readonly environment: string;
  readonly executable: boolean;
  readonly reason: string;
  readonly factors: readonly CatalogueFactor[];
  readonly presets: Readonly<Record<string, Readonly<Record<string, number>>>>;
  readonly limitations: readonly string[];
}

/** `GET /workspaces/{id}/studies` */
export interface StudyCatalogueResponse {
  readonly studies: readonly CatalogueStudy[];
  readonly invalid_documents: number;
}

/** What the workbench asks for: a study and a configuration in canonical units. */
export interface RunConfigurationRequest {
  readonly study_id: string;
  readonly case_id: string;
  readonly values: Readonly<Record<string, number>>;
}

export interface RunRefusal {
  readonly code: string;
  readonly message: string;
}

export interface DefinitionIdentity {
  readonly identifier: string;
  readonly version: string;
  readonly semantic_digest: string;
}

export interface AdapterIdentity {
  readonly adapter_id: string;
  readonly adapter_version: string;
  readonly implementation_digest: string | null;
  readonly engine: string | null;
  readonly engine_version: string | null;
  readonly python_version: string | null;
  readonly platform: string | null;
  readonly dependency_closure_digest: string | null;
}

/** `POST /workspaces/{id}/runs/preflight` */
export interface PreflightResponse {
  readonly decision: "ready" | "refused";
  readonly refusals: readonly RunRefusal[];
  readonly request_digest: string | null;
  readonly execution_fingerprint: string;
  readonly study: DefinitionIdentity;
  readonly definitions: Readonly<Record<string, DefinitionIdentity>>;
  readonly configuration: Readonly<Record<string, number>>;
  readonly adapter: AdapterIdentity;
  readonly timeout_seconds: number;
}

/** The pipeline states a run of this session passes through (operator information). */
export const RUN_PROGRESS_STATES = [
  "planning",
  "preflight",
  "starting",
  "running",
  "canceling",
  "sealing",
  "deriving",
  "completed",
  "failed",
  "refused",
  "canceled",
  "timed_out",
  "error",
] as const;
export type RunProgressState = (typeof RUN_PROGRESS_STATES)[number];

/** `POST /runs`, `GET /runs/{run}/progress`, `POST /runs/{run}/cancel` */
export interface RunProgressResponse {
  readonly run_id: string;
  readonly study_id: string;
  readonly case_id: string;
  readonly configuration: Readonly<Record<string, number>>;
  readonly state: RunProgressState;
  readonly active: boolean;
  readonly lifecycle: readonly string[];
  readonly refusals: readonly RunRefusal[];
  readonly message: string;
  readonly execution_evidence_digest: string | null;
  readonly derived_evidence_digest: string | null;
  readonly derived_outcome: string | null;
  readonly elapsed_s: number;
}

/** What reading a sealed run established, or the progress state of an unsealed one. */
export const RUN_READ_STATUSES = ["verified", "failed", "rejected", "incomplete"] as const;
export type RunReadStatus = (typeof RUN_READ_STATUSES)[number];
export type RunStatus = RunReadStatus | RunProgressState;

export interface OutcomeCounts {
  readonly pass: number;
  readonly fail: number;
  readonly not_evaluated: number;
  readonly reported: number;
}

export interface RunEntry {
  readonly run_id: string;
  readonly status: RunStatus;
  readonly reasons: readonly string[];
  readonly case_id: string;
  readonly configuration: Readonly<Record<string, number>>;
  readonly progress: RunProgressResponse | null;
  readonly execution_evidence_digest: string | null;
  readonly derived_evidence_digest: string | null;
  readonly trajectory_sha256: string | null;
  readonly completed: boolean | null;
  readonly timestep_s: number | null;
  readonly duration_s: number | null;
  readonly frame_count: number | null;
  /** The adapter's predeclared checks of the repetition. */
  readonly checks: OutcomeCounts;
  /** The benchmark metrics, assessed against the release's criteria. */
  readonly metrics: OutcomeCounts;
  /** The independent numerical verification of the canonical series. */
  readonly verification: OutcomeCounts;
}

/** `GET /workspaces/{id}/runs` */
export interface RunListResponse {
  readonly runs: readonly RunEntry[];
}

export interface BundleFile {
  readonly path: string;
  readonly sha256: string;
  readonly size_bytes: number;
}

export interface BundleVerification {
  readonly valid: boolean;
  readonly defects: readonly string[];
  readonly run_id: string | null;
  readonly outcome: string | null;
  readonly evidence_digest: string | null;
  readonly files: readonly BundleFile[];
}

export interface VerificationCheckView {
  readonly check_id: string;
  readonly category: string;
  readonly label: string;
  readonly method: string;
  readonly unit: string;
  readonly value: number | null;
  readonly tolerance: number | null;
  readonly status: string;
  readonly detail: string;
}

export interface MetricView {
  readonly metric_id: string;
  readonly quantity_id: string;
  readonly label: string;
  readonly description: string;
  readonly aggregation: string;
  readonly unit: string;
  readonly value: number | null;
  readonly operator: string | null;
  readonly threshold: number | null;
  readonly status: string;
}

/**
 * The provenance record of a derived bundle, as far as the workbench reads it. The full record
 * stays in the sealed bundle; these are the links the Evidence folio draws.
 */
export interface ProvenanceView {
  readonly execution_run_id: string;
  readonly execution_evidence_digest: string;
  readonly execution_outcome: string;
  readonly native: Readonly<Record<string, string>>;
  readonly source_documents: Readonly<Record<string, string>>;
  readonly definitions: Readonly<Record<string, DefinitionIdentity>>;
  readonly execution_fingerprint: string;
  readonly input_manifest_digest: string;
  readonly preflight_request_digest: string | null;
  readonly adapter: {
    readonly adapter_id: string;
    readonly adapter_version: string;
    readonly engine: string;
    readonly engine_version: string;
    readonly implementation_digest: string | null;
  };
  readonly trajectory_sha256: string | null;
  readonly canonical: Readonly<Record<string, string>>;
  readonly derivation_implementation: Readonly<Record<string, string>>;
  readonly claim: string;
}

/** One of the adapter's predeclared checks of the repetition, as the assessment sealed it. */
export interface AdapterCheckView {
  readonly criterion_id: string;
  readonly group: string;
  readonly label: string;
  readonly unit: string;
  readonly bound: string;
  readonly rationale: string;
  readonly value: number | null;
  readonly status: string;
}

/** `GET /workspaces/{id}/runs/{run}/evidence` */
export interface RunEvidenceResponse {
  readonly run_id: string;
  readonly status: RunReadStatus;
  readonly reasons: readonly string[];
  readonly execution: BundleVerification;
  readonly derived: BundleVerification;
  readonly case_id: string | null;
  readonly configuration: Readonly<Record<string, number>>;
  readonly failure: string | null;
  readonly provenance: ProvenanceView | null;
  readonly verification: readonly VerificationCheckView[];
  readonly metrics: readonly MetricView[];
  readonly adapter_checks: readonly AdapterCheckView[];
  readonly claim: string | null;
}
