/**
 * Contract gates for the runtime decoders.
 *
 * Every decoder has a positive gate (the accepted read model survives unchanged) and a
 * negative gate for each part of its shape: a non-object root, a missing required field, a
 * wrong scalar, a wrong array, an unknown closed-vocabulary value, a malformed nested
 * digest, and a nullable field carrying the wrong type. The negative cases are deliberately
 * shaped like plausible server regressions rather than like arbitrary garbage: `{}` is a
 * handler that forgot its model, `"sha1"` is a digest implementation that changed, and an
 * unknown diagnostic code is a vocabulary that grew without this client.
 *
 * A decoder returns `null` rather than describing what was wrong, because the rejection is
 * reported as one bounded `invalid_response` and the rejected body is not retained.
 */

import { describe, expect, it } from "vitest";

import {
  APPLICATION_INFO,
  ARTIFACT,
  DIAGNOSTIC,
  DISCOVERY,
  HEALTH,
  INSPECTION,
  OPEN_WORKSPACE,
  SEMANTIC_DIGEST,
} from "../test/api-fixtures";
import {
  decodeApplicationInfoResponse,
  decodeArtifactInspectionResponse,
  decodeHealthResponse,
  decodeOpenWorkspaceResponse,
  decodeWorkspaceDiscoveryResponse,
} from "./decode";

/** A copy with one field replaced, without mutating the accepted fixture. */
function withField<T extends object>(value: T, key: string, replacement: unknown): T {
  return { ...value, [key]: replacement };
}

/** A copy with one field removed. */
function withoutField<T extends object>(value: T, key: string): T {
  const copy = { ...value } as Record<string, unknown>;
  delete copy[key];
  return copy as T;
}

describe("decodeHealthResponse", () => {
  it("accepts the published health read model", () => {
    expect(decodeHealthResponse(HEALTH)).toEqual(HEALTH);
  });

  it.each([
    ["an empty object", {}],
    ["a non-object root", ["ok"]],
    ["a null root", null],
    ["an unknown status", withField(HEALTH, "status", "degraded")],
    ["a missing status", withoutField(HEALTH, "status")],
    ["a non-string application", withField(HEALTH, "application", 1)],
    ["a missing version", withoutField(HEALTH, "version")],
    ["a foreign API version", withField(HEALTH, "api_version", "v2")],
    ["a missing API version", withoutField(HEALTH, "api_version")],
  ])("refuses %s", (_label, value) => {
    expect(decodeHealthResponse(value)).toBeNull();
  });
});

describe("decodeApplicationInfoResponse", () => {
  it("accepts the published info read model", () => {
    expect(decodeApplicationInfoResponse(APPLICATION_INFO)).toEqual(APPLICATION_INFO);
  });

  it.each([
    ["an empty object", {}],
    ["a non-object root", "DynamisBench"],
    ["a missing application", withoutField(APPLICATION_INFO, "application")],
    ["a non-string version", withField(APPLICATION_INFO, "version", 0)],
    ["a foreign API version", withField(APPLICATION_INFO, "api_version", "v2")],
  ])("refuses %s", (_label, value) => {
    expect(decodeApplicationInfoResponse(value)).toBeNull();
  });
});

describe("decodeOpenWorkspaceResponse", () => {
  it("accepts the published open-workspace read model", () => {
    expect(decodeOpenWorkspaceResponse(OPEN_WORKSPACE)).toEqual(OPEN_WORKSPACE);
  });

  it.each([
    ["an empty object", {}],
    ["a missing workspace identifier", withoutField(OPEN_WORKSPACE, "workspace_id")],
    ["a non-string workspace identifier", withField(OPEN_WORKSPACE, "workspace_id", 7)],
    ["a missing evidence-inside-source bit", withoutField(OPEN_WORKSPACE, "evidence_inside_source")],
    ["a string evidence-inside-source bit", withField(OPEN_WORKSPACE, "evidence_inside_source", "false")],
    ["a non-array category list", withField(OPEN_WORKSPACE, "source_categories", {})],
    [
      "an unknown source category",
      withField(OPEN_WORKSPACE, "source_categories", [
        { category: "invented_category", exists: true },
      ]),
    ],
    [
      "a non-boolean category existence bit",
      withField(OPEN_WORKSPACE, "source_categories", [{ category: "benchmarks", exists: "true" }]),
    ],
    [
      "a non-object category status",
      withField(OPEN_WORKSPACE, "source_categories", ["benchmarks"]),
    ],
  ])("refuses %s", (_label, value) => {
    expect(decodeOpenWorkspaceResponse(value)).toBeNull();
  });
});

describe("decodeWorkspaceDiscoveryResponse", () => {
  it("accepts the published discovery read model", () => {
    expect(decodeWorkspaceDiscoveryResponse(DISCOVERY)).toEqual(DISCOVERY);
  });

  it.each([
    ["an empty object", {}],
    ["a missing workspace identifier", withoutField(DISCOVERY, "workspace_id")],
    ["a non-array category list", withField(DISCOVERY, "categories", "benchmarks")],
    ["a missing artifact list", withoutField(DISCOVERY, "artifacts")],
    ["an array artifact list", withField(DISCOVERY, "artifacts", [])],
    ["a discovery payload whose artifacts key is not an array", withField(DISCOVERY, "artifacts", { artifacts: {} })],
    [
      "an artifact with an unknown source category",
      withField(DISCOVERY, "artifacts", {
        artifacts: [withField(ARTIFACT, "category", "invented_category")],
      }),
    ],
    [
      "an artifact with an unknown authoring format",
      withField(DISCOVERY, "artifacts", {
        artifacts: [withField(ARTIFACT, "authoring_format", "toml")],
      }),
    ],
    [
      "an artifact with an unknown validation status",
      withField(DISCOVERY, "artifacts", {
        artifacts: [withField(ARTIFACT, "validation_status", "unknown")],
      }),
    ],
    [
      "an artifact with a non-string identifier",
      withField(DISCOVERY, "artifacts", {
        artifacts: [withField(ARTIFACT, "identifier", 1)],
      }),
    ],
    [
      "an artifact with a missing nullable version",
      withField(DISCOVERY, "artifacts", {
        artifacts: [withoutField(ARTIFACT, "version")],
      }),
    ],
    [
      "an artifact with a missing digest field",
      withField(DISCOVERY, "artifacts", {
        artifacts: [withoutField(ARTIFACT, "semantic_digest")],
      }),
    ],
    [
      "an artifact whose digest uses another algorithm",
      withField(DISCOVERY, "artifacts", {
        artifacts: [
          withField(ARTIFACT, "semantic_digest", withField(SEMANTIC_DIGEST, "algorithm", "sha1")),
        ],
      }),
    ],
    [
      "an artifact whose digest hex is uppercase",
      withField(DISCOVERY, "artifacts", {
        artifacts: [
          withField(ARTIFACT, "semantic_digest", withField(SEMANTIC_DIGEST, "hex", SEMANTIC_DIGEST.hex.toUpperCase())),
        ],
      }),
    ],
    [
      "an artifact whose digest hex is short",
      withField(DISCOVERY, "artifacts", {
        artifacts: [
          withField(ARTIFACT, "semantic_digest", withField(SEMANTIC_DIGEST, "hex", "0".repeat(63))),
        ],
      }),
    ],
    [
      "an artifact whose digest hex is not hexadecimal",
      withField(DISCOVERY, "artifacts", {
        artifacts: [
          withField(ARTIFACT, "semantic_digest", withField(SEMANTIC_DIGEST, "hex", "g".repeat(64))),
        ],
      }),
    ],
    [
      "an artifact with a non-array diagnostic list",
      withField(DISCOVERY, "artifacts", {
        artifacts: [withField(ARTIFACT, "diagnostics", {})],
      }),
    ],
    [
      "an artifact with a malformed diagnostic",
      withField(DISCOVERY, "artifacts", {
        artifacts: [
          withField(ARTIFACT, "diagnostics", [withField(DIAGNOSTIC, "message", 1)]),
        ],
      }),
    ],
    [
      "an artifact diagnostic with an unknown code",
      withField(DISCOVERY, "artifacts", {
        artifacts: [
          withField(ARTIFACT, "diagnostics", [withField(DIAGNOSTIC, "code", "invented_code")]),
        ],
      }),
    ],
    [
      "an artifact diagnostic with a missing nullable reference",
      withField(DISCOVERY, "artifacts", {
        artifacts: [
          withField(ARTIFACT, "diagnostics", [withoutField(DIAGNOSTIC, "reference")]),
        ],
      }),
    ],
    ["a non-array issue list", withField(DISCOVERY, "issues", {})],
    ["an unknown issue code", withField(DISCOVERY, "issues", [withField(DIAGNOSTIC, "code", "invented_code")])],
    ["a string truncation flag", withField(DISCOVERY, "issues_truncated", "false")],
    ["a missing truncation flag", withoutField(DISCOVERY, "issues_truncated")],
  ])("refuses %s", (_label, value) => {
    expect(decodeWorkspaceDiscoveryResponse(value)).toBeNull();
  });

  it("accepts an invalid artifact with null identity, version and digest", () => {
    const invalid = {
      ...ARTIFACT,
      validation_status: "invalid",
      identifier: null,
      version: null,
      semantic_digest: null,
      diagnostics: [DIAGNOSTIC],
    };

    expect(
      decodeWorkspaceDiscoveryResponse(withField(DISCOVERY, "artifacts", { artifacts: [invalid] })),
    ).toEqual(withField(DISCOVERY, "artifacts", { artifacts: [invalid] }));
  });
});

describe("decodeArtifactInspectionResponse", () => {
  it("accepts the published inspection read model", () => {
    expect(decodeArtifactInspectionResponse(INSPECTION)).toEqual(INSPECTION);
  });

  it("accepts an inspected artifact whose content is null", () => {
    expect(decodeArtifactInspectionResponse({ ...INSPECTION, content: null })).toEqual({
      ...INSPECTION,
      content: null,
    });
  });

  it.each([
    ["an empty object", {}],
    ["a missing content field", withoutField(INSPECTION, "content")],
    ["array content", withField(INSPECTION, "content", [])],
    ["scalar content", withField(INSPECTION, "content", "schema_version: 1")],
    ["a missing artifact identifier", withoutField(INSPECTION, "artifact_id")],
    ["an unknown category", withField(INSPECTION, "category", "invented_category")],
    ["a malformed nested digest", withField(INSPECTION, "semantic_digest", { algorithm: "sha256", hex: "abc" })],
    ["a malformed nested diagnostic", withField(INSPECTION, "diagnostics", [{ code: "parse_error" }])],
    ["a non-string logical reference", withField(INSPECTION, "logical_reference", 1)],
  ])("refuses %s", (_label, value) => {
    expect(decodeArtifactInspectionResponse(value)).toBeNull();
  });
});
