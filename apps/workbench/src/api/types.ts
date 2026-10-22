/**
 * The accepted `/api/v1` response vocabulary, as the frontend sees it.
 *
 * These types mirror the read models the application boundary publishes — field names
 * exactly as they travel, so this module is the accepted contract rather than a translation
 * of it. A translation layer would be a second place for a field to be renamed, and the
 * response models are already deliberately presentation-shaped: no domain class, no
 * validator, no raw authoring text, no absolute path.
 *
 * The closed vocabularies are restated as `as const` tuples rather than imported, because
 * the frontend cannot import Python: a value that is not in a tuple is not accepted into the
 * type, and the tuples are small enough to review against the server's own enums.
 *
 * The one thing a client may rely on without a field for it: a read model never carries the
 * session credential. There is no type here in which one could be returned.
 */

/** The declared source categories a workspace can hold authority in. */
export const SOURCE_CATEGORIES = [
  "benchmarks",
  "realizations",
  "studies",
  "references",
  "schemas",
] as const;

export type SourceCategory = (typeof SOURCE_CATEGORIES)[number];

/** The serialisations an authoring document may be written in. */
export const AUTHORING_FORMATS = ["json", "yaml"] as const;

export type AuthoringFormat = (typeof AUTHORING_FORMATS)[number];

/** Whether an artifact produced a validated definition. */
export const VALIDATION_STATUSES = ["valid", "invalid"] as const;

export type ValidationStatus = (typeof VALIDATION_STATUSES)[number];

/** The closed set of reasons a source-authority read can be refused. */
export const DIAGNOSTIC_CODES = [
  "unsupported_entry",
  "too_large",
  "invalid_utf8",
  "parse_error",
  "duplicate_key",
  "expected_object",
  "schema_validation",
  "path_scope_violation",
  "read_error",
] as const;

export type DiagnosticCode = (typeof DIAGNOSTIC_CODES)[number];

/** The closed set of application/API failure codes. */
export const API_ERROR_CODES = [
  "not_found",
  "method_not_allowed",
  "invalid_request",
  "http_error",
  "unauthorized",
  "internal_error",
] as const;

export type ApiErrorCode = (typeof API_ERROR_CODES)[number];

/** The closed vocabulary of application events carried by `/api/v1/events`. */
export const APPLICATION_EVENT_NAMES = [
  "stream.ready",
  "workspace.opened",
  "workspace.discovered",
  "artifact.inspected",
] as const;

export type ApplicationEventName = (typeof APPLICATION_EVENT_NAMES)[number];

/** The exact payload `stream.ready` carries: what this transport will do. */
export interface StreamReadyEventData {
  heartbeat_seconds: number;
  queue_capacity: number;
}

/** The exact payload `workspace.opened` carries: an opaque handle and the workspace's shape. */
export interface WorkspaceOpenedEventData {
  workspace_id: string;
  categories_present: number;
  evidence_inside_source: boolean;
}

/** The exact payload `workspace.discovered` carries: counts and one truncation fact. */
export interface WorkspaceDiscoveredEventData {
  workspace_id: string;
  artifact_count: number;
  valid_count: number;
  invalid_count: number;
  issue_count: number;
  issues_truncated: boolean;
}

/**
 * The exact payload `artifact.inspected` carries.
 *
 * `workspace_id` and `artifact_id` are opaque handles; `category` and `validation_status`
 * are closed vocabularies and `kind` is a bounded authority-kind token. No field can hold
 * a root, a credential, content or a diagnostic message.
 */
export interface ArtifactInspectedEventData {
  workspace_id: string;
  artifact_id: string;
  category: SourceCategory;
  kind: string;
  validation_status: ValidationStatus;
  diagnostic_count: number;
}

/**
 * One event frame, exactly as the SSE `data:` field carries it.
 *
 * A discriminated union rather than an open mapping: each event name owns one payload
 * interface, so `data` cannot grow a key no event publishes and a consumer reading a field
 * after narrowing the event name is reading the accepted contract. An event that does not
 * match one of these four members is refused by the decoder.
 */
export type ApplicationEvent =
  | { schema_version: 1; event: "stream.ready"; data: StreamReadyEventData }
  | { schema_version: 1; event: "workspace.opened"; data: WorkspaceOpenedEventData }
  | { schema_version: 1; event: "workspace.discovered"; data: WorkspaceDiscoveredEventData }
  | { schema_version: 1; event: "artifact.inspected"; data: ArtifactInspectedEventData };

/** `GET /api/v1/health` — the application process is serving its versioned API. */
export interface HealthResponse {
  status: "ok";
  application: string;
  version: string;
  api_version: string;
}

/** `GET /api/v1/info` — the build identity a client needs before anything else. */
export interface ApplicationInfoResponse {
  application: string;
  version: string;
  api_version: string;
}

/**
 * The digest of a validated definition's meaning.
 *
 * A client compares the hex; nothing here decodes it into a path, a name, or the bytes it
 * was taken over, and the algorithm travels with it so a comparison is a comparison.
 */
export interface SemanticDigestView {
  algorithm: "sha256";
  hex: string;
}

/** One bounded reason a source document is not valid authority. */
export interface ArtifactDiagnostic {
  code: DiagnosticCode;
  message: string;
  reference: string | null;
  location: string | null;
  category: string | null;
}

/** What one source-authority artifact is, in portable terms. */
export interface ArtifactSummary {
  artifact_id: string;
  category: SourceCategory;
  kind: string;
  logical_reference: string;
  authoring_format: AuthoringFormat;
  validation_status: ValidationStatus;
  identifier: string | null;
  version: string | null;
  semantic_digest: SemanticDigestView | null;
  diagnostics: ArtifactDiagnostic[];
}

/** A discovery response's artifacts, in the walk's own documented order. */
export interface ArtifactSummaryList {
  artifacts: ArtifactSummary[];
}

/** Whether one declared source category currently exists — and nothing about where. */
export interface SourceCategoryStatus {
  category: SourceCategory;
  exists: boolean;
}

/**
 * The two declared roots of an existing workspace, as the workbench names them.
 *
 * The only request that carries absolute operational paths, because it *is* the workspace
 * selection operation: a person running the workbench says which repository and which
 * evidence directory to use. Everything after identifies the workspace by the opaque
 * identifier the response returned.
 *
 * These two fields are the one place the frontend's own vocabulary differs from the wire's:
 * the shell says `sourceRoot`/`evidenceRoot` and the API says `source_root`/`evidence_root`,
 * and the client maps between them at the single request builder rather than making every
 * caller remember which side spells it which way.
 */
export interface OpenWorkspaceRequest {
  sourceRoot: string;
  evidenceRoot: string;
}

/** The opaque identifier to use, plus a read-only description of the opened workspace. */
export interface OpenWorkspaceResponse {
  workspace_id: string;
  evidence_inside_source: boolean;
  source_categories: SourceCategoryStatus[];
}

/** One read-only pass over a workspace's source authority. */
export interface WorkspaceDiscoveryResponse {
  workspace_id: string;
  categories: SourceCategoryStatus[];
  artifacts: ArtifactSummaryList;
  issues: ArtifactDiagnostic[];
  issues_truncated: boolean;
}

/**
 * One artifact, re-read and revalidated just now, plus its validated read model.
 *
 * `content` is the validated domain model serialised in JSON mode — never the authoring
 * text it was written in. Inspection re-reads on every call, so a file edited between two
 * responses changes this response.
 */
export interface ArtifactInspectionResponse extends ArtifactSummary {
  content: Record<string, unknown> | null;
}

/** The body of every failed application/API response. */
export interface ErrorResponse {
  error: {
    code: ApiErrorCode;
    message: string;
  };
}
