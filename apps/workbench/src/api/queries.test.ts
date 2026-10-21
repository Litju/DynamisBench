/**
 * The query and mutation factories: outside components, and wired to the client's methods.
 *
 * The key shape is asserted in `src/query/client.test.ts`. What matters here is that each
 * factory reads through the typed client with the accepted request vocabulary — the one
 * place a camelCase shell name meets the API's own snake_case field names.
 */

import { describe, expect, it, vi } from "vitest";

import type { ApiClient } from "./client";
import {
  apiInfoOptions,
  artifactInspectionOptions,
  openWorkspaceOptions,
  workspaceArtifactsOptions,
} from "./queries";
import type {
  ApplicationInfoResponse,
  ArtifactInspectionResponse,
  OpenWorkspaceResponse,
  WorkspaceDiscoveryResponse,
} from "./types";

const INFO: ApplicationInfoResponse = {
  application: "DynamisBench",
  version: "0.0.0",
  api_version: "v1",
};

function stubClient() {
  const client: ApiClient = {
    health: vi.fn(),
    info: vi.fn(async () => INFO),
    openWorkspace: vi.fn(
      async () =>
        ({
          workspace_id: "w-1",
          evidence_inside_source: false,
          source_categories: [],
        }) satisfies OpenWorkspaceResponse,
    ),
    listArtifacts: vi.fn(
      async () =>
        ({
          workspace_id: "w-1",
          categories: [],
          artifacts: { artifacts: [] },
          issues: [],
          issues_truncated: false,
        }) satisfies WorkspaceDiscoveryResponse,
    ),
    getArtifact: vi.fn(
      async () =>
        ({
          artifact_id: "a-1",
          category: "benchmarks",
          kind: "benchmark",
          logical_reference: "benchmarks/benchmark/x.json",
          authoring_format: "json",
          validation_status: "valid",
          identifier: null,
          version: null,
          semantic_digest: null,
          diagnostics: [],
          content: null,
        }) satisfies ArtifactInspectionResponse,
    ),
    streamEvents: () => (async function* () {})(),
  };

  return client;
}

/** Run a query function the way the cache would. */
async function runQuery<T>(options: { queryFn?: unknown }): Promise<T> {
  const queryFn = options.queryFn as (context: unknown) => Promise<T>;
  return await queryFn({});
}

describe("query factories", () => {
  it("read the application's info", async () => {
    const client = stubClient();
    const options = apiInfoOptions(client);

    expect(options.queryKey).toEqual(["api", "info"]);
    await expect(runQuery<ApplicationInfoResponse>(options)).resolves.toEqual(INFO);
    expect(client.info).toHaveBeenCalledTimes(1);
  });

  it("read a workspace's artifacts under the workspace's own key", async () => {
    const client = stubClient();
    const options = workspaceArtifactsOptions(client, "w-1");

    expect(options.queryKey).toEqual(["api", "workspace", "w-1", "artifacts"]);
    await runQuery<WorkspaceDiscoveryResponse>(options);
    expect(client.listArtifacts).toHaveBeenCalledWith("w-1");
  });

  it("read one artifact under its workspace's key", async () => {
    const client = stubClient();
    const options = artifactInspectionOptions(client, "w-1", "a-1");

    expect(options.queryKey).toEqual(["api", "workspace", "w-1", "artifacts", "a-1"]);
    await runQuery<ArtifactInspectionResponse>(options);
    expect(client.getArtifact).toHaveBeenCalledWith("w-1", "a-1");
  });
});

describe("opening a workspace", () => {
  it("is a mutation that hands the request to the typed client unchanged", async () => {
    const client = stubClient();
    const options = openWorkspaceOptions(client);

    expect(options.mutationKey).toEqual(["api", "workspaces", "open"]);

    const mutationFn = options.mutationFn as (variables: {
      sourceRoot: string;
      evidenceRoot: string;
    }) => Promise<unknown>;

    await mutationFn({ sourceRoot: "C:/repo", evidenceRoot: "C:/evidence" });

    expect(client.openWorkspace).toHaveBeenCalledWith({
      sourceRoot: "C:/repo",
      evidenceRoot: "C:/evidence",
    });
  });
});

describe("the info factory", () => {
  it("is disabled without a client, and enabled with one", () => {
    expect(apiInfoOptions(null).enabled).toBe(false);
    expect(apiInfoOptions(stubClient()).enabled).toBe(true);
  });

  it("refuses to run without a client rather than inventing one", () => {
    const options = apiInfoOptions(null);
    const queryFn = options.queryFn as (context: unknown) => Promise<unknown>;

    expect(() => queryFn({})).toThrow(/no API client/);
  });
});
