/**
 * Explorer grouping: one deterministic arrangement of a discovery response's artifacts.
 *
 * The API publishes artifacts in the walk's documented order — the portable logical
 * reference — and this function does not reorder them. What it adds is the category/kind
 * hierarchy a person browses by, with categories in the declared `SOURCE_CATEGORIES` order
 * and kinds sorted by their portable name so two responses and two renders agree.
 *
 * Pure, and deliberately not a component concern: the same grouping is used by the Explorer
 * and asserted by the qualification suite without rendering anything.
 */

import { SOURCE_CATEGORIES, type ArtifactSummary, type SourceCategory } from "../api/types";

export interface ArtifactGroup {
  readonly category: SourceCategory;
  readonly kind: string;
  readonly artifacts: readonly ArtifactSummary[];
}

const CATEGORY_ORDER = new Map(SOURCE_CATEGORIES.map((category, index) => [category, index]));

/**
 * Group artifacts by category then kind, preserving the server's order inside each group.
 *
 * Categories the frontend's vocabulary does not know cannot arrive through the decoder, so
 * the fallback ordering is defensive rather than a second accepted category.
 */
export function groupArtifacts(artifacts: readonly ArtifactSummary[]): ArtifactGroup[] {
  const groups = new Map<string, ArtifactSummary[]>();
  const categoryOf = new Map<string, SourceCategory>();
  const kindOf = new Map<string, string>();

  for (const artifact of artifacts) {
    const key = `${artifact.category}\u0000${artifact.kind}`;
    const existing = groups.get(key);
    if (existing === undefined) {
      groups.set(key, [artifact]);
      categoryOf.set(key, artifact.category);
      kindOf.set(key, artifact.kind);
    } else {
      existing.push(artifact);
    }
  }

  return [...groups.entries()]
    .map(([key, members]) => ({
      category: categoryOf.get(key) ?? "benchmarks",
      kind: kindOf.get(key) ?? "",
      artifacts: members,
    }))
    .sort((left, right) => {
      const leftCategory = CATEGORY_ORDER.get(left.category) ?? Number.MAX_SAFE_INTEGER;
      const rightCategory = CATEGORY_ORDER.get(right.category) ?? Number.MAX_SAFE_INTEGER;
      if (leftCategory !== rightCategory) {
        return leftCategory - rightCategory;
      }
      return left.kind < right.kind ? -1 : left.kind > right.kind ? 1 : 0;
    });
}

/** Counts the Explorer reports beside the hierarchy, derived and never invented. */
export function artifactCounts(artifacts: readonly ArtifactSummary[]): {
  readonly total: number;
  readonly valid: number;
  readonly invalid: number;
} {
  let valid = 0;
  for (const artifact of artifacts) {
    if (artifact.validation_status === "valid") {
      valid += 1;
    }
  }
  return { total: artifacts.length, valid, invalid: artifacts.length - valid };
}
