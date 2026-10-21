/**
 * Explorer grouping is deterministic and lossless.
 *
 * The hierarchy a person browses by is derived from the discovery response alone: categories
 * in the declared order, kinds sorted, and every artifact in exactly one group.
 */

import { describe, expect, it } from "vitest";

import type { ArtifactSummary } from "../api/types";
import { ARTIFACT, INVALID_ARTIFACT, VERSIONLESS_FACTOR } from "../test/api-fixtures";
import { artifactCounts, groupArtifacts } from "./grouping";

function artifact(
  overrides: Partial<ArtifactSummary> & Pick<ArtifactSummary, "artifact_id">,
): ArtifactSummary {
  return {
    ...ARTIFACT,
    ...overrides,
  };
}

describe("groupArtifacts", () => {
  it("orders categories by the declared vocabulary and kinds by name", () => {
    const groups = groupArtifacts([
      artifact({ artifact_id: "study", category: "studies", kind: "factor" }),
      artifact({ artifact_id: "scenario", category: "benchmarks", kind: "scenario" }),
      artifact({ artifact_id: "benchmark", category: "benchmarks", kind: "benchmark" }),
      artifact({ artifact_id: "schema", category: "schemas", kind: "metric" }),
    ]);

    expect(groups.map((group) => `${group.category}/${group.kind}`)).toEqual([
      "benchmarks/benchmark",
      "benchmarks/scenario",
      "studies/factor",
      "schemas/metric",
    ]);
  });

  it("preserves the server's artifact order inside one group", () => {
    const groups = groupArtifacts([
      artifact({ artifact_id: "second", logical_reference: "benchmarks/benchmark/b.json" }),
      artifact({ artifact_id: "first", logical_reference: "benchmarks/benchmark/a.json" }),
    ]);

    expect(groups[0]?.artifacts.map((entry) => entry.artifact_id)).toEqual(["second", "first"]);
  });

  it("describes every artifact exactly once", () => {
    const input = [ARTIFACT, VERSIONLESS_FACTOR, INVALID_ARTIFACT];
    const grouped = groupArtifacts(input).flatMap((group) => group.artifacts);

    expect(grouped).toHaveLength(input.length);
    expect(new Set(grouped.map((entry) => entry.artifact_id))).toEqual(
      new Set(input.map((entry) => entry.artifact_id)),
    );
  });

  it("counts validity from the published status only", () => {
    expect(artifactCounts([ARTIFACT, VERSIONLESS_FACTOR, INVALID_ARTIFACT])).toEqual({
      total: 3,
      valid: 2,
      invalid: 1,
    });
  });
});
