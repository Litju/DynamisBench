/**
 * Accepted `/api/v1` read models, for the client and decoder tests.
 *
 * These are the positive side of the contract gates: every field the RES-377 read models
 * publish, with the closed vocabularies' own spellings and a semantic digest in the exact
 * algorithm/hex form. A test that needs "a valid response" starts here and changes one fact
 * at a time, so a negative gate names the single field it is about.
 */

import type {
  ApplicationInfoResponse,
  ArtifactDiagnostic,
  ArtifactInspectionResponse,
  ArtifactSummary,
  HealthResponse,
  OpenWorkspaceResponse,
  SemanticDigestView,
  SourceCategoryStatus,
  WorkspaceDiscoveryResponse,
} from "../api/types";

export const HEALTH: HealthResponse = {
  status: "ok",
  application: "DynamisBench",
  version: "0.0.0",
  api_version: "v1",
};

export const APPLICATION_INFO: ApplicationInfoResponse = {
  application: "DynamisBench",
  version: "0.0.0",
  api_version: "v1",
};

export const SEMANTIC_DIGEST: SemanticDigestView = {
  algorithm: "sha256",
  hex: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
};

export const DIAGNOSTIC: ArtifactDiagnostic = {
  code: "schema_validation",
  message: "The document did not satisfy its declared model.",
  reference: "benchmarks/benchmark/example.json",
  location: "version",
  category: "benchmark",
};

export const SOURCE_CATEGORIES: SourceCategoryStatus[] = [
  { category: "benchmarks", exists: true },
  { category: "realizations", exists: true },
  { category: "studies", exists: false },
  { category: "references", exists: false },
  { category: "schemas", exists: true },
];

export const ARTIFACT: ArtifactSummary = {
  artifact_id: "artifact-1",
  category: "benchmarks",
  kind: "benchmark",
  logical_reference: "benchmarks/benchmark/example.json",
  authoring_format: "json",
  validation_status: "valid",
  identifier: "example",
  version: "1.0.0",
  semantic_digest: SEMANTIC_DIGEST,
  diagnostics: [],
};

/**
 * A valid artifact of the one kind that has no version.
 *
 * `factor` definitions are identified by `factor_id` alone (ADR-002's one versionless
 * kind), so this is the positive control for a valid summary whose `version` is `null`
 * while its identifier and digest are present.
 */
export const VERSIONLESS_FACTOR: ArtifactSummary = {
  artifact_id: "artifact-2",
  category: "studies",
  kind: "factor",
  logical_reference: "studies/factor/load.json",
  authoring_format: "json",
  validation_status: "valid",
  identifier: "load",
  version: null,
  semantic_digest: SEMANTIC_DIGEST,
  diagnostics: [],
};

export const OPEN_WORKSPACE: OpenWorkspaceResponse = {
  workspace_id: "workspace-1",
  evidence_inside_source: false,
  source_categories: SOURCE_CATEGORIES,
};

export const DISCOVERY: WorkspaceDiscoveryResponse = {
  workspace_id: "workspace-1",
  categories: SOURCE_CATEGORIES,
  artifacts: { artifacts: [ARTIFACT] },
  issues: [DIAGNOSTIC],
  issues_truncated: false,
};

export const INSPECTION: ArtifactInspectionResponse = {
  ...ARTIFACT,
  content: { schema_version: "1", id: "example" },
};
