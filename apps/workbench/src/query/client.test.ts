/**
 * Query ownership: the one client, the policy it carries, and the keys.
 *
 * Server/application state belongs to TanStack Query and to nothing else, and the keys those
 * states are filed under can say nothing about the session that read them. What the cache
 * does when the session changes is asserted in `session-cache.test.tsx`, where a provider is
 * driving it.
 */

import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { apiMutationKeys, apiQueryKeys } from "../api/queries";
import { createWorkbenchQueryClient } from "./client";

describe("apiQueryKeys", () => {
  it("names server state by the application's own opaque identifiers", () => {
    expect(apiQueryKeys.info()).toEqual(["api", "info"]);
    expect(apiQueryKeys.artifacts("w-1")).toEqual(["api", "workspace", "w-1", "artifacts"]);
    expect(apiQueryKeys.artifact("w-1", "a-1")).toEqual([
      "api",
      "workspace",
      "w-1",
      "artifacts",
      "a-1",
    ]);
    expect(apiMutationKeys.openWorkspace()).toEqual(["api", "workspaces", "open"]);
  });

  it("holds nothing a session owns: no credential, no origin, no root", () => {
    const keys = [
      apiQueryKeys.info(),
      apiQueryKeys.artifacts("w-1"),
      apiQueryKeys.artifact("w-1", "a-1"),
      apiMutationKeys.openWorkspace(),
    ];

    for (const key of keys) {
      const serialized = JSON.stringify(key);
      for (const forbidden of [
        "credential",
        "Authorization",
        "Bearer",
        "token",
        "http://",
        "C:\\",
      ]) {
        expect(serialized).not.toContain(forbidden);
      }
    }
  });
});

describe("the one QueryClient", () => {
  it("does not retry", () => {
    const client = createWorkbenchQueryClient();

    expect(client).toBeInstanceOf(QueryClient);
    expect(client.getDefaultOptions().queries?.retry).toBe(false);
    expect(client.getDefaultOptions().mutations?.retry).toBe(false);
  });

  it("persists nothing and starts empty", () => {
    const client = createWorkbenchQueryClient();

    expect(client.getQueryCache().getAll()).toEqual([]);
    expect(client.getMutationCache().getAll()).toEqual([]);
    // No cache policy beyond retry is set here, and no persistence exists to set one for:
    // a stored cache would be a second copy of server data outside Query's lifetime.
    expect(client.getDefaultOptions().queries?.staleTime).toBeUndefined();
    expect(client.getDefaultOptions().queries?.gcTime).toBeUndefined();
  });
});
