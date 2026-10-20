/**
 * The typed client's contract with `/api/v1`.
 *
 * The five accepted endpoints, the four request invariants, and the bounded failure taxonomy
 * — asserted against a recording `fetch`, so what is checked is the request the client
 * actually builds and the error it actually throws.
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
  VERSIONLESS_FACTOR,
} from "../test/api-fixtures";
import { FIXTURE_CREDENTIAL, FIXTURE_ORIGIN, readyApiSession } from "../test/session-fixtures";
import {
  jsonResponse,
  recordingFetch,
  unreadableResponse,
  type RecordedCall,
} from "../test/http-fixtures";
import { ApiClientError } from "./errors";
import { createApiClient, type ApiClientConnection } from "./client";

const CONNECTION: ApiClientConnection = readyApiSession();

const INFO = APPLICATION_INFO;

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
    const { client, calls } = clientAnswering(HEALTH);

    await expect(client.health()).resolves.toEqual(HEALTH);
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
    const { client, calls } = clientAnswering(OPEN_WORKSPACE);

    await expect(
      client.openWorkspace({ sourceRoot: "C:/repo", evidenceRoot: "C:/evidence" }),
    ).resolves.toEqual(OPEN_WORKSPACE);

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
    const { client, calls } = clientAnswering(DISCOVERY);

    await expect(client.listArtifacts("workspace-1")).resolves.toEqual(DISCOVERY);
    expect(calls[0]?.url).toBe(`${FIXTURE_ORIGIN}/api/v1/workspaces/workspace-1/artifacts`);
    expect(calls[0]?.init.method).toBe("GET");
  });

  it("builds GET /api/v1/workspaces/{workspaceId}/artifacts/{artifactId}", async () => {
    const { client, calls } = clientAnswering(INSPECTION);

    await expect(client.getArtifact("workspace-1", "artifact-1")).resolves.toEqual(INSPECTION);

    expect(calls[0]?.url).toBe(
      `${FIXTURE_ORIGIN}/api/v1/workspaces/workspace-1/artifacts/artifact-1`,
    );
    expect(calls[0]?.init.method).toBe("GET");
  });

  it("URL-encodes opaque identifiers instead of trusting their spelling", async () => {
    const { client, calls } = clientAnswering(INSPECTION);

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
    const recorder = recordingFetch((call) =>
      jsonResponse(call.url.endsWith("/info") ? INFO : OPEN_WORKSPACE),
    );
    const client = createApiClient(CONNECTION, { fetch: recorder.fetch });
    const calls = recorder.calls;

    await client.info();
    await client.openWorkspace({ sourceRoot: "C:/repo", evidenceRoot: "C:/evidence" });

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

describe("malformed read models", () => {
  /**
   * The five regressions acceptance named: each is a syntactically valid 200 whose body is
   * not the read model its route publishes. The client must report `invalid_response` and
   * must not retain the rejected body.
   */
  const cases: Array<[string, () => Record<string, unknown>, (client: ReturnType<typeof createApiClient>) => Promise<unknown>]> = [
    ["info with no fields", () => ({}), (client) => client.info()],
    [
      "health with an unknown status",
      () => ({ ...HEALTH, status: "degraded" }),
      (client) => client.health(),
    ],
    [
      "an opened workspace with no identifier",
      () => {
        const { workspace_id: _omitted, ...rest } = OPEN_WORKSPACE;
        return rest;
      },
      (client) => client.openWorkspace({ sourceRoot: "C:/repo", evidenceRoot: "C:/evidence" }),
    ],
    [
      "discovery with an unknown diagnostic code",
      () => ({
        ...DISCOVERY,
        issues: [{ ...DIAGNOSTIC, code: "invented_code" }],
      }),
      (client) => client.listArtifacts("workspace-1"),
    ],
    [
      "inspection with a malformed nested digest",
      () => ({
        ...INSPECTION,
        semantic_digest: { algorithm: "sha256", hex: "not-a-digest" },
      }),
      (client) => client.getArtifact("workspace-1", "artifact-1"),
    ],
    [
      "a valid artifact without an identifier",
      () => ({
        ...DISCOVERY,
        artifacts: { artifacts: [{ ...ARTIFACT, identifier: null }] },
      }),
      (client) => client.listArtifacts("workspace-1"),
    ],
    [
      "a valid artifact without a semantic digest",
      () => ({
        ...DISCOVERY,
        artifacts: { artifacts: [{ ...ARTIFACT, semantic_digest: null }] },
      }),
      (client) => client.listArtifacts("workspace-1"),
    ],
    [
      "an invalid artifact retaining an identifier",
      () => ({
        ...DISCOVERY,
        artifacts: {
          artifacts: [
            {
              ...ARTIFACT,
              validation_status: "invalid",
              version: null,
              semantic_digest: null,
            },
          ],
        },
      }),
      (client) => client.listArtifacts("workspace-1"),
    ],
    [
      "an invalid artifact retaining a version",
      () => ({
        ...DISCOVERY,
        artifacts: {
          artifacts: [
            {
              ...ARTIFACT,
              validation_status: "invalid",
              identifier: null,
              semantic_digest: null,
            },
          ],
        },
      }),
      (client) => client.listArtifacts("workspace-1"),
    ],
    [
      "an invalid artifact retaining a semantic digest",
      () => ({
        ...DISCOVERY,
        artifacts: {
          artifacts: [
            {
              ...ARTIFACT,
              validation_status: "invalid",
              identifier: null,
              version: null,
            },
          ],
        },
      }),
      (client) => client.listArtifacts("workspace-1"),
    ],
    [
      "a valid inspection whose content is null",
      () => ({ ...INSPECTION, content: null }),
      (client) => client.getArtifact("workspace-1", "artifact-1"),
    ],
    [
      "an invalid inspection whose content is an object",
      () => ({
        ...INSPECTION,
        validation_status: "invalid",
        identifier: null,
        version: null,
        semantic_digest: null,
        content: { schema_version: "1" },
      }),
      (client) => client.getArtifact("workspace-1", "artifact-1"),
    ],
  ];

  it.each(cases)("reports %s as an unreadable response", async (_label, body, call) => {
    const { client } = clientAnswering(body());

    await expect(call(client)).rejects.toMatchObject({
      kind: "invalid_response",
      status: 200,
      code: null,
      apiMessage: null,
    });
  });

  it("does not retain the rejected body anywhere on the error", async () => {
    const rejected = { ...APPLICATION_INFO, private_detail: "must not be retained" };
    const { client } = clientAnswering({ ...rejected, application: 7 });

    try {
      await client.info();
      expect.unreachable("a malformed read model must be refused");
    } catch (error) {
      const parsed = error as ApiClientError;

      expect(parsed).toBeInstanceOf(ApiClientError);
      expect(JSON.stringify(parsed)).not.toContain("must not be retained");
      expect(Object.keys(parsed)).not.toContain("body");
      expect((parsed as unknown as { body?: unknown }).body).toBeUndefined();
    }
  });

  it("does not retain a rejected authority-inconsistent inspection body", async () => {
    const rejected = { ...INSPECTION, content: null, private_detail: "must not be retained" };
    const { client } = clientAnswering(rejected);

    try {
      await client.getArtifact("workspace-1", "artifact-1");
      expect.unreachable("a valid inspection with null content must be refused");
    } catch (error) {
      const parsed = error as ApiClientError;

      expect(parsed).toBeInstanceOf(ApiClientError);
      expect(parsed.kind).toBe("invalid_response");
      expect(JSON.stringify(parsed)).not.toContain("must not be retained");
      expect(publicSurface(parsed)).not.toContain("must not be retained");
      expect(Object.keys(parsed)).not.toContain("body");
      expect((parsed as unknown as { body?: unknown }).body).toBeUndefined();
    }
  });

  it("keeps accepting a digest with the announced algorithm and lowercase hex", async () => {
    const digest = {
      ...INSPECTION,
      semantic_digest: { ...SEMANTIC_DIGEST, hex: "f".repeat(64) },
    };
    const { client } = clientAnswering(digest);

    await expect(client.getArtifact("workspace-1", "artifact-1")).resolves.toEqual(digest);
  });

  it("keeps accepting a valid versionless factor with an identifier and digest", async () => {
    const body = { ...DISCOVERY, artifacts: { artifacts: [VERSIONLESS_FACTOR] } };
    const { client } = clientAnswering(body);

    await expect(client.listArtifacts("workspace-1")).resolves.toEqual(body);
  });

  it("keeps accepting a valid inspection whose content is an object", async () => {
    const { client } = clientAnswering(INSPECTION);

    await expect(client.getArtifact("workspace-1", "artifact-1")).resolves.toEqual(INSPECTION);
  });

  it("keeps accepting an invalid inspection whose content is null", async () => {
    const invalid = {
      ...INSPECTION,
      validation_status: "invalid",
      identifier: null,
      version: null,
      semantic_digest: null,
      diagnostics: [DIAGNOSTIC],
      content: null,
    };
    const { client } = clientAnswering(invalid);

    await expect(client.getArtifact("workspace-1", "artifact-1")).resolves.toEqual(invalid);
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
      // The message is composed from the status and the code, and the envelope's own message
      // carried the credential, so it is not retained in any field at all.
      expect(parsed.message).toBe(
        "The DynamisBench application API refused the request (500 internal_error).",
      );
      expect(parsed.apiMessage).toBeNull();
      expect(parsed.message).not.toContain(FIXTURE_CREDENTIAL);
      expect(parsed.stack ?? "").not.toContain(FIXTURE_CREDENTIAL);
      expect(JSON.stringify(parsed)).not.toContain(FIXTURE_CREDENTIAL);
      expect(publicSurface(parsed)).not.toContain(FIXTURE_CREDENTIAL);
    }
  });

  it("does not adopt an oversized message but keeps the status and code", async () => {
    const { client } = clientAnswering(
      { error: { code: "not_found", message: "m".repeat(257) } },
      404,
    );

    try {
      await client.getArtifact("workspace-1", "artifact-1");
      expect.unreachable("a 404 must be refused");
    } catch (error) {
      const parsed = error as ApiClientError;

      expect(parsed.kind).toBe("http");
      expect(parsed.status).toBe(404);
      expect(parsed.code).toBe("not_found");
      expect(parsed.apiMessage).toBeNull();
    }
  });

  it("adopts a message at the reviewed 256-character bound", async () => {
    const message = "m".repeat(256);
    const { client } = clientAnswering(
      { error: { code: "invalid_request", message } },
      400,
    );

    await expect(client.info()).rejects.toMatchObject({
      kind: "http",
      status: 400,
      code: "invalid_request",
      apiMessage: message,
    });
  });

  it("does not adopt a message that is not a string", async () => {
    const { client } = clientAnswering(
      { error: { code: "http_error", message: { detail: "no" } } },
      400,
    );

    await expect(client.info()).rejects.toMatchObject({
      kind: "http",
      status: 400,
      code: "http_error",
      apiMessage: null,
    });
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

/**
 * Every publicly reachable field of an error, including inherited and non-enumerable ones.
 *
 * `JSON.stringify` sees own enumerable properties only, so it would miss `message` and
 * `stack`. This walk reads the instance and its prototypes, skips methods, and renders each
 * value — which is what makes "the credential is absent from every field" a statement about
 * the whole object rather than about the six fields the test remembered to name.
 */
function publicSurface(value: unknown): string {
  const rendered: string[] = [];
  const seen = new Set<string>();
  let current: object | null = typeof value === "object" && value !== null ? value : null;

  while (current !== null && current !== Object.prototype) {
    for (const name of Object.getOwnPropertyNames(current)) {
      if (seen.has(name)) {
        continue;
      }
      seen.add(name);

      const field = (current as Record<string, unknown>)[name];
      if (typeof field === "function") {
        continue;
      }

      rendered.push(`${name}: ${typeof field === "string" ? field : JSON.stringify(field)}`);
    }
    current = Object.getPrototypeOf(current) as object | null;
  }

  return rendered.join("\n");
}
