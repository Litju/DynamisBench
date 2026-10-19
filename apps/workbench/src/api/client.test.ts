/**
 * The typed client's contract with `/api/v1`.
 *
 * The five accepted endpoints, the four request invariants, and the bounded failure taxonomy
 * — asserted against a recording `fetch`, so what is checked is the request the client
 * actually builds and the error it actually throws.
 */

import { describe, expect, it } from "vitest";

import { FIXTURE_CREDENTIAL, FIXTURE_ORIGIN, readyApiSession } from "../test/session-fixtures";
import {
  jsonResponse,
  recordingFetch,
  unreadableResponse,
  type RecordedCall,
} from "../test/http-fixtures";
import { ApiClientError } from "./errors";
import { createApiClient, type ApiClientConnection } from "./client";
import type { ApplicationInfoResponse, WorkspaceDiscoveryResponse } from "./types";

const CONNECTION: ApiClientConnection = readyApiSession();

const INFO: ApplicationInfoResponse = {
  application: "DynamisBench",
  version: "0.0.0",
  api_version: "v1",
};

/** A client wired to a recording fetch that answers with `body`. */
function clientAnswering(body: unknown, status = 200) {
  const recorder = recordingFetch(() => jsonResponse(body, status));
  return { client: createApiClient(CONNECTION, { fetch: recorder.fetch }), calls: recorder.calls };
}

describe("createApiClient", () => {
  it("refuses an incompatible session before making a request", () => {
    const recorder = recordingFetch(() => jsonResponse(INFO));

    expect(() =>
      createApiClient({ ...CONNECTION, apiVersion: "v2" }, { fetch: recorder.fetch }),
    ).toThrow(ApiClientError);
    expect(() =>
      createApiClient({ ...CONNECTION, protocolVersion: 2 }, { fetch: recorder.fetch }),
    ).toThrow(ApiClientError);
    expect(recorder.calls).toEqual([]);
  });

  it("reports an incompatible session as its own kind", () => {
    const recorder = recordingFetch(() => jsonResponse(INFO));

    try {
      createApiClient({ ...CONNECTION, apiVersion: "v2" }, { fetch: recorder.fetch });
      expect.unreachable("an incompatible session must be refused");
    } catch (error) {
      expect(error).toBeInstanceOf(ApiClientError);
      expect((error as ApiClientError).kind).toBe("incompatible_session");
      expect((error as ApiClientError).status).toBeNull();
      expect((error as ApiClientError).code).toBeNull();
    }
  });
});

describe("the five accepted endpoints", () => {
  it("builds GET /api/v1/health", async () => {
    const { client, calls } = clientAnswering({
      status: "ok",
      application: "DynamisBench",
      version: "0.0.0",
      api_version: "v1",
    });

    await expect(client.health()).resolves.toEqual({
      status: "ok",
      application: "DynamisBench",
      version: "0.0.0",
      api_version: "v1",
    });
    expect(calls[0]?.url).toBe(`${FIXTURE_ORIGIN}/api/v1/health`);
    expect(calls[0]?.init.method).toBe("GET");
  });

  it("builds GET /api/v1/info", async () => {
    const { client, calls } = clientAnswering(INFO);

    await expect(client.info()).resolves.toEqual(INFO);
    expect(calls[0]?.url).toBe(`${FIXTURE_ORIGIN}/api/v1/info`);
    expect(calls[0]?.init.method).toBe("GET");
  });

  it("builds POST /api/v1/workspaces/open with a JSON body", async () => {
    const opened = {
      workspace_id: "w-1",
      evidence_inside_source: false,
      source_categories: [],
    };
    const { client, calls } = clientAnswering(opened);

    await expect(
      client.openWorkspace({ source_root: "C:/repo", evidence_root: "C:/evidence" }),
    ).resolves.toEqual(opened);

    const call = calls[0];
    expect(call?.url).toBe(`${FIXTURE_ORIGIN}/api/v1/workspaces/open`);
    expect(call?.init.method).toBe("POST");
    expect(headersOf(call)).toMatchObject({ "Content-Type": "application/json" });
    expect(JSON.parse(String(call?.init.body))).toEqual({
      source_root: "C:/repo",
      evidence_root: "C:/evidence",
    });
  });

  it("builds GET /api/v1/workspaces/{workspaceId}/artifacts", async () => {
    const discovery: WorkspaceDiscoveryResponse = {
      workspace_id: "w-1",
      categories: [],
      artifacts: { artifacts: [] },
      issues: [],
      issues_truncated: false,
    };
    const { client, calls } = clientAnswering(discovery);

    await expect(client.listArtifacts("w-1")).resolves.toEqual(discovery);
    expect(calls[0]?.url).toBe(`${FIXTURE_ORIGIN}/api/v1/workspaces/w-1/artifacts`);
    expect(calls[0]?.init.method).toBe("GET");
  });

  it("builds GET /api/v1/workspaces/{workspaceId}/artifacts/{artifactId}", async () => {
    const { client, calls } = clientAnswering({});

    await client.getArtifact("w-1", "a-1");

    expect(calls[0]?.url).toBe(`${FIXTURE_ORIGIN}/api/v1/workspaces/w-1/artifacts/a-1`);
    expect(calls[0]?.init.method).toBe("GET");
  });

  it("URL-encodes opaque identifiers instead of trusting their spelling", async () => {
    const { client, calls } = clientAnswering({});

    await client.getArtifact("w/1 x", "a?b#c");

    expect(calls[0]?.url).toBe(`${FIXTURE_ORIGIN}/api/v1/workspaces/w%2F1%20x/artifacts/a%3Fb%23c`);
  });

  it("tolerates an origin written with a trailing slash", async () => {
    const recorder = recordingFetch(() => jsonResponse(INFO));
    const client = createApiClient({ ...CONNECTION, origin: `${FIXTURE_ORIGIN}/` }, {
      fetch: recorder.fetch,
    });

    await client.info();

    expect(recorder.calls[0]?.url).toBe(`${FIXTURE_ORIGIN}/api/v1/info`);
  });
});

describe("what every request carries", () => {
  it("presents the session credential as a bearer header", async () => {
    const { client, calls } = clientAnswering(INFO);

    await client.info();

    expect(headersOf(calls[0])).toMatchObject({
      Authorization: `Bearer ${FIXTURE_CREDENTIAL}`,
      Accept: "application/json",
    });
  });

  it("omits credentials and bypasses every cache", async () => {
    const { client, calls } = clientAnswering(INFO);

    await client.info();
    await client.openWorkspace({ source_root: "C:/repo", evidence_root: "C:/evidence" });

    expect(calls).toHaveLength(2);
    for (const call of calls) {
      expect(call.init.credentials).toBe("omit");
      expect(call.init.cache).toBe("no-store");
    }
  });
});

describe("refusals", () => {
  const refusals: Array<{ status: number; code: string; message: string }> = [
    { status: 400, code: "http_error", message: "The declared workspace roots could not be opened." },
    { status: 401, code: "unauthorized", message: "Authentication required." },
    { status: 404, code: "not_found", message: "No workspace is registered under that identifier." },
    { status: 500, code: "internal_error", message: "The application could not complete the request." },
  ];

  for (const refusal of refusals) {
    it(`maps a ${refusal.status} envelope to a bounded http error`, async () => {
      const { client } = clientAnswering(
        { error: { code: refusal.code, message: refusal.message } },
        refusal.status,
      );

      await expect(client.info()).rejects.toMatchObject({
        kind: "http",
        status: refusal.status,
        code: refusal.code,
        apiMessage: refusal.message,
      });
    });
  }

  it("keeps the status when a refusal carries no readable envelope", async () => {
    const recorder = recordingFetch(() => unreadableResponse(503));
    const client = createApiClient(CONNECTION, { fetch: recorder.fetch });

    await expect(client.info()).rejects.toMatchObject({
      kind: "http",
      status: 503,
      code: null,
      apiMessage: null,
    });
  });

  it("does not adopt an error code it does not know", async () => {
    const { client } = clientAnswering(
      { error: { code: "invented_code", message: "no" } },
      400,
    );

    await expect(client.info()).rejects.toMatchObject({ kind: "http", code: null });
  });

  it("reports an unreachable API as a network error", async () => {
    const recorder = recordingFetch(() => {
      throw new TypeError("Failed to fetch");
    });
    const client = createApiClient(CONNECTION, { fetch: recorder.fetch });

    await expect(client.info()).rejects.toMatchObject({
      kind: "network",
      status: null,
      code: null,
    });
  });

  it("reports a body that is not JSON as an unreadable response", async () => {
    const recorder = recordingFetch(() => unreadableResponse(200));
    const client = createApiClient(CONNECTION, { fetch: recorder.fetch });

    await expect(client.info()).rejects.toMatchObject({ kind: "invalid_response", status: 200 });
  });

  it("reports a JSON body that is not an object as an unreadable response", async () => {
    const { client } = clientAnswering(["not", "a", "read model"]);

    await expect(client.info()).rejects.toMatchObject({ kind: "invalid_response" });
  });
});

describe("what an error may carry", () => {
  /** A refusal whose own message quotes the credential, as a compromised server might. */
  const hostile = {
    error: {
      code: "internal_error",
      message: `the token was ${FIXTURE_CREDENTIAL} and it leaked`,
    },
  };

  it("composes its own text from bounded facts and never from the server's", async () => {
    const { client } = clientAnswering(hostile, 500);

    try {
      await client.info();
      expect.unreachable("a 500 must be refused");
    } catch (error) {
      const parsed = error as ApiClientError;

      expect(parsed.kind).toBe("http");
      expect(parsed.status).toBe(500);
      expect(parsed.code).toBe("internal_error");
      // The message is composed from the status and the code. The envelope's own message is
      // preserved as a bounded field, and never spliced into the text this client throws.
      expect(parsed.message).toBe(
        "The DynamisBench application API refused the request (500 internal_error).",
      );
      expect(parsed.message).not.toContain(FIXTURE_CREDENTIAL);
      expect(`${parsed.name} ${parsed.stack ?? ""}`).not.toContain(FIXTURE_CREDENTIAL);
    }
  });

  it("does not attach the underlying failure as a cause", async () => {
    const recorder = recordingFetch(() => {
      throw new Error(`request to ${FIXTURE_ORIGIN} failed while sending Bearer ${FIXTURE_CREDENTIAL}`);
    });
    const client = createApiClient(CONNECTION, { fetch: recorder.fetch });

    try {
      await client.info();
      expect.unreachable("an unreachable API must be refused");
    } catch (error) {
      const parsed = error as ApiClientError;
      expect(parsed.cause).toBeUndefined();
      expect(`${parsed.message} ${JSON.stringify(parsed)}`).not.toContain(FIXTURE_CREDENTIAL);
    }
  });

  it("keeps the bounded envelope facts when the envelope was readable", async () => {
    const { client } = clientAnswering(
      { error: { code: "not_found", message: "No artifact is registered under that identifier." } },
      404,
    );

    try {
      await client.getArtifact("w-1", "a-1");
      expect.unreachable("a 404 must be refused");
    } catch (error) {
      const parsed = error as ApiClientError;
      expect(parsed.status).toBe(404);
      expect(parsed.code).toBe("not_found");
      expect(parsed.apiMessage).toBe("No artifact is registered under that identifier.");
      expect(parsed.message).not.toContain("No artifact is registered");
    }
  });
});

/** The headers of a recorded call, lower-cased keys and all. */
function headersOf(call: RecordedCall | undefined): Record<string, string> {
  const headers = (call?.init.headers ?? {}) as Record<string, string>;
  return Object.fromEntries(Object.entries(headers).map(([name, value]) => [name, value]));
}
