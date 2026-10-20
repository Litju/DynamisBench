/**
 * Runtime decoders for the `/api/v1` read models.
 *
 * The TypeScript interfaces in `types.ts` describe what this client accepts, but a type is
 * only a promise about code the compiler can see. A response crosses a process boundary, so
 * every accepted body is checked here before it is handed to a caller. These are manual,
 * dependency-free refiners: a decoder returns a fresh value built from the fields it has
 * validated, or `null` when the body is not the read model the API publishes.
 *
 * **What is checked.** Required fields and their scalar types, arrays and their elements,
 * nullable fields (present, and either `null` or their declared type), nested objects, the
 * closed vocabularies restated in `types.ts`, the semantic digest's algorithm and its
 * 64-character lowercase hex, the relationship between validation status, identity and
 * inspection content, and the one API version this client speaks. Nothing else:
 * `ArtifactInspectionResponse.content` is the validated domain model in JSON mode, and
 * re-implementing the scientific model's validation in TypeScript would be a second,
 * inevitably drifting authority. It is required to be a JSON object exactly when the
 * artifact is valid, and `null` exactly when it is invalid.
 *
 * **What is not retained.** A decoder never returns the input object, an unknown field, or
 * a rejected value. The decoded value is assembled from validated fields alone, so an
 * accepted read model carries exactly the contract and nothing a future server field might
 * have added. A rejected body is not wrapped, quoted or described: the caller reports
 * `invalid_response` and the bytes go out of scope with this call.
 *
 * The decoders are total functions over `unknown`: malformed JSON is the client's concern,
 * and a syntactically valid body that is the wrong shape is this module's.
 */

import { EXPECTED_API_VERSION } from "../session/types";
import {
  AUTHORING_FORMATS,
  DIAGNOSTIC_CODES,
  SOURCE_CATEGORIES,
  VALIDATION_STATUSES,
  type ApplicationInfoResponse,
  type ArtifactDiagnostic,
  type ArtifactInspectionResponse,
  type ArtifactSummary,
  type AuthoringFormat,
  type DiagnosticCode,
  type HealthResponse,
  type OpenWorkspaceResponse,
  type SemanticDigestView,
  type SourceCategory,
  type SourceCategoryStatus,
  type ValidationStatus,
  type WorkspaceDiscoveryResponse,
} from "./types";

type JsonObject = Record<string, unknown>;

/** A JSON object, which is the only root a read model may have. */
function asObject(value: unknown): JsonObject | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as JsonObject;
}

/** Every element decoded, or `null` if the value is not an array or one element failed. */
function decodeArray<T>(value: unknown, decode: (item: unknown) => T | null): T[] | null {
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

function isOneOf<T extends string>(values: readonly T[], value: unknown): value is T {
  return values.some((member) => member === value);
}

/**
 * A required string field, or `null` when it is missing or not a string.
 *
 * `null` is a valid JavaScript value for a field whose contract is a string only when the
 * contract says so; callers of a nullable field use [`nullableString`] instead.
 */
function requiredString(record: JsonObject, key: string): string | null {
  const value = record[key];
  return typeof value === "string" ? value : null;
}

/**
 * A required nullable string field.
 *
 * The distinction between `undefined` and `null` is the whole point: a missing key is a
 * response this client cannot read, while a present `null` is the contract's own way of
 * saying the artifact has no identifier, version, reference, location or category.
 */
function nullableString(record: JsonObject, key: string): string | null | undefined {
  if (!(key in record)) {
    return undefined;
  }
  const value = record[key];
  return value === null || typeof value === "string" ? value : undefined;
}

function requiredBoolean(record: JsonObject, key: string): boolean | null {
  const value = record[key];
  return typeof value === "boolean" ? value : null;
}

/** A required field whose value must belong to a closed vocabulary. */
function requiredEnum<T extends string>(
  record: JsonObject,
  key: string,
  vocabulary: readonly T[],
): T | null {
  const value = record[key];
  return isOneOf(vocabulary, value) ? value : null;
}

/** `sha256` and exactly sixty-four lowercase hexadecimal characters, or nothing. */
function decodeSemanticDigest(value: unknown): SemanticDigestView | null {
  const record = asObject(value);
  if (record === null) {
    return null;
  }

  const algorithm = record.algorithm;
  const hex = record.hex;

  if (algorithm !== "sha256" || typeof hex !== "string" || !/^[0-9a-f]{64}$/.test(hex)) {
    return null;
  }

  return { algorithm, hex };
}

/** `GET /api/v1/health` — the one health state, and this client's API version. */
export function decodeHealthResponse(value: unknown): HealthResponse | null {
  const record = asObject(value);
  if (record === null) {
    return null;
  }

  const application = requiredString(record, "application");
  const version = requiredString(record, "version");
  const apiVersion = requiredString(record, "api_version");

  if (record.status !== "ok" || application === null || version === null) {
    return null;
  }
  if (apiVersion !== EXPECTED_API_VERSION) {
    return null;
  }

  return {
    status: "ok",
    application,
    version,
    api_version: apiVersion,
  };
}

/** `GET /api/v1/info` — the build identity, under this client's API version. */
export function decodeApplicationInfoResponse(
  value: unknown,
): ApplicationInfoResponse | null {
  const record = asObject(value);
  if (record === null) {
    return null;
  }

  const application = requiredString(record, "application");
  const version = requiredString(record, "version");
  const apiVersion = requiredString(record, "api_version");

  if (application === null || version === null || apiVersion !== EXPECTED_API_VERSION) {
    return null;
  }

  return { application, version, api_version: apiVersion };
}

function decodeSourceCategoryStatus(value: unknown): SourceCategoryStatus | null {
  const record = asObject(value);
  if (record === null) {
    return null;
  }

  const category = requiredEnum<SourceCategory>(record, "category", SOURCE_CATEGORIES);
  const exists = requiredBoolean(record, "exists");

  if (category === null || exists === null) {
    return null;
  }

  return { category, exists };
}

function decodeArtifactDiagnostic(value: unknown): ArtifactDiagnostic | null {
  const record = asObject(value);
  if (record === null) {
    return null;
  }

  const code = requiredEnum<DiagnosticCode>(record, "code", DIAGNOSTIC_CODES);
  const message = requiredString(record, "message");
  const reference = nullableString(record, "reference");
  const location = nullableString(record, "location");
  const category = nullableString(record, "category");

  if (
    code === null ||
    message === null ||
    reference === undefined ||
    location === undefined ||
    category === undefined
  ) {
    return null;
  }

  return { code, message, reference, location, category };
}

/**
 * One artifact's portable summary.
 *
 * Takes an already-established object so inspection can validate the surrounding read model
 * and reuse this walk rather than restating it beside itself.
 *
 * Identity and validity are one statement, not independent fields: the authority produces a
 * valid artifact with an identifier and a well-formed digest, and an invalid artifact with
 * no identifier, version or digest at all. `version` is the one nullable member of a valid
 * artifact, because a `factor` definition genuinely has no version. Each field is type-checked
 * for itself, then admitted or refused as that relationship, because a body that pairs
 * `valid` with no digest (or `invalid` with a digest) describes a state the server cannot
 * publish.
 */
function decodeArtifactSummary(record: JsonObject): ArtifactSummary | null {
  const artifactId = requiredString(record, "artifact_id");
  const category = requiredEnum<SourceCategory>(record, "category", SOURCE_CATEGORIES);
  const kind = requiredString(record, "kind");
  const logicalReference = requiredString(record, "logical_reference");
  const authoringFormat = requiredEnum<AuthoringFormat>(
    record,
    "authoring_format",
    AUTHORING_FORMATS,
  );
  const validationStatus = requiredEnum<ValidationStatus>(
    record,
    "validation_status",
    VALIDATION_STATUSES,
  );
  const identifier = nullableString(record, "identifier");
  const version = nullableString(record, "version");
  const diagnostics = decodeArray(record.diagnostics, decodeArtifactDiagnostic);

  if (
    artifactId === null ||
    category === null ||
    kind === null ||
    logicalReference === null ||
    authoringFormat === null ||
    validationStatus === null ||
    identifier === undefined ||
    version === undefined ||
    diagnostics === null
  ) {
    return null;
  }

  let semanticDigest: SemanticDigestView | null;
  if (!("semantic_digest" in record)) {
    return null;
  }
  if (record.semantic_digest === null) {
    semanticDigest = null;
  } else {
    const decoded = decodeSemanticDigest(record.semantic_digest);
    if (decoded === null) {
      return null;
    }
    semanticDigest = decoded;
  }

  if (validationStatus === "valid") {
    if (identifier === null || semanticDigest === null) {
      return null;
    }
  } else if (identifier !== null || version !== null || semanticDigest !== null) {
    return null;
  }

  return {
    artifact_id: artifactId,
    category,
    kind,
    logical_reference: logicalReference,
    authoring_format: authoringFormat,
    validation_status: validationStatus,
    identifier,
    version,
    semantic_digest: semanticDigest,
    diagnostics,
  };
}

/** `POST /api/v1/workspaces/open` — the opaque identifier and the workspace's shape. */
export function decodeOpenWorkspaceResponse(value: unknown): OpenWorkspaceResponse | null {
  const record = asObject(value);
  if (record === null) {
    return null;
  }

  const workspaceId = requiredString(record, "workspace_id");
  const evidenceInsideSource = requiredBoolean(record, "evidence_inside_source");
  const sourceCategories = decodeArray(record.source_categories, decodeSourceCategoryStatus);

  if (workspaceId === null || evidenceInsideSource === null || sourceCategories === null) {
    return null;
  }

  return {
    workspace_id: workspaceId,
    evidence_inside_source: evidenceInsideSource,
    source_categories: sourceCategories,
  };
}

/** `GET /api/v1/workspaces/{workspaceId}/artifacts` — one discovery pass. */
export function decodeWorkspaceDiscoveryResponse(
  value: unknown,
): WorkspaceDiscoveryResponse | null {
  const record = asObject(value);
  if (record === null) {
    return null;
  }

  const workspaceId = requiredString(record, "workspace_id");
  const categories = decodeArray(record.categories, decodeSourceCategoryStatus);
  const issues = decodeArray(record.issues, decodeArtifactDiagnostic);
  const issuesTruncated = requiredBoolean(record, "issues_truncated");

  if (workspaceId === null || categories === null || issues === null || issuesTruncated === null) {
    return null;
  }

  const artifactsRecord = asObject(record.artifacts);
  if (artifactsRecord === null) {
    return null;
  }

  const artifacts = decodeArray(artifactsRecord.artifacts, (item) => {
    const artifact = asObject(item);
    return artifact === null ? null : decodeArtifactSummary(artifact);
  });
  if (artifacts === null) {
    return null;
  }

  return {
    workspace_id: workspaceId,
    categories,
    artifacts: { artifacts },
    issues,
    issues_truncated: issuesTruncated,
  };
}

/**
 * `GET /api/v1/workspaces/{workspaceId}/artifacts/{artifactId}` — one fresh inspection.
 *
 * `content` is the validated scientific model serialised in JSON mode and exists exactly
 * when the artifact is valid. The client checks that relationship and that `content` is an
 * object for a valid artifact or `null` for an invalid one; it deliberately does not
 * validate the model's own fields.
 */
export function decodeArtifactInspectionResponse(
  value: unknown,
): ArtifactInspectionResponse | null {
  const record = asObject(value);
  if (record === null) {
    return null;
  }

  const summary = decodeArtifactSummary(record);
  if (summary === null || !("content" in record)) {
    return null;
  }

  if (summary.validation_status === "valid") {
    const content = asObject(record.content);
    return content === null ? null : { ...summary, content };
  }

  return record.content === null ? { ...summary, content: null } : null;
}
