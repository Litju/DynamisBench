/**
 * The typed client's laboratory methods: the same request invariants as every other read,
 * plus the binary read's own bounds (media type, size) for Arrow frame streams.
 */

import { describe, expect, it } from "vitest";

import { recordingFetch, jsonResponse } from "../test/http-fixtures";
import {
  LABORATORY_INDEX,
  LABORATORY_NOMINAL,
  binaryResponse,
  frameStream,
} from "../test/laboratory-fixtures";
import { FIXTURE_CREDENTIAL, FIXTURE_ORIGIN, readyApiSession } from "../test/session-fixtures";
import { MAX_FRAME_STREAM_BYTES, createApiClient } from "./client";
import { ApiClientError } from "./errors";

function clientWith(answer: (url: string) => Response) {
  const recorder = recordingFetch((call) => answer(call.url));
  return { client: createApiClient(readyApiSession(), { fetch: recorder.fetch }), calls: recorder.calls };
}

async function failure(promise: Promise<unknown>): Promise<ApiClientError> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof ApiClientError) {
      return error;
    }
    throw error;
  }
  throw new Error("the request was expected to fail");
}

describe("the laboratory reads", () => {
  it("reads the index under the versioned namespace with the session's one credential", async () => {
    const { client, calls } = clientWith(() => jsonResponse(LABORATORY_INDEX));

    const index = await client.laboratoryIndex();

    expect(index.dataset_id).toBe("laboratory/1");
    expect(calls).toHaveLength(1);
    expect(calls[0]?.url).toBe(`${FIXTURE_ORIGIN}/api/v1/laboratory`);
    expect(calls[0]?.init.method).toBe("GET");
    expect(calls[0]?.init.credentials).toBe("omit");
    expect(calls[0]?.init.cache).toBe("no-store");
    expect((calls[0]?.init.headers as Record<string, string>).Authorization).toBe(`Bearer ${FIXTURE_CREDENTIAL}`);
  });

  it("encodes a recording identifier and refuses an answer about another recording", async () => {
    const { client, calls } = clientWith(() => jsonResponse(LABORATORY_NOMINAL));

    await expect(client.laboratoryRecording("repetition")).resolves.toMatchObject({ recording_id: "repetition" });
    const refused = await failure(client.laboratoryRecording("ablation soft/friction"));

    expect(calls[1]?.url).toBe(`${FIXTURE_ORIGIN}/api/v1/laboratory/recordings/ablation%20soft%2Ffriction`);
    expect(refused.kind).toBe("invalid_response");
  });

  it("refuses a body that is not the read model", async () => {
    const { client } = clientWith(() => jsonResponse({ recordings: "all of them" }));

    expect((await failure(client.laboratoryIndex())).kind).toBe("invalid_response");
  });
});

describe("the laboratory frame stream", () => {
  it("asks for Arrow and answers with the stream's bytes", async () => {
    const stream = frameStream(LABORATORY_NOMINAL, "kinetics");
    const { client, calls } = clientWith(() => binaryResponse(stream));

    const bytes = await client.laboratoryFrames("repetition", "kinetics");

    expect(bytes).toEqual(stream);
    expect(calls[0]?.url).toBe(`${FIXTURE_ORIGIN}/api/v1/laboratory/recordings/repetition/frames/kinetics`);
    expect((calls[0]?.init.headers as Record<string, string>).Accept).toBe("application/vnd.apache.arrow.stream");
    expect(calls[0]?.init.credentials).toBe("omit");
  });

  it("refuses a stream of another media type", async () => {
    const { client } = clientWith(() => binaryResponse(new Uint8Array([1, 2, 3]), "application/octet-stream"));

    expect((await failure(client.laboratoryFrames("repetition", "pose"))).kind).toBe("invalid_response");
  });

  it("refuses an empty stream and one above the bound", async () => {
    const empty = clientWith(() => binaryResponse(new Uint8Array()));
    const large = clientWith(() => binaryResponse(new Uint8Array(MAX_FRAME_STREAM_BYTES + 1)));

    expect((await failure(empty.client.laboratoryFrames("repetition", "pose"))).kind).toBe("invalid_response");
    expect((await failure(large.client.laboratoryFrames("repetition", "pose"))).kind).toBe("invalid_response");
  });

  it("reports a refusal with its status and code, as every read does", async () => {
    const { client } = clientWith(() =>
      jsonResponse({ error: { code: "not_found", message: "The laboratory has no such recording or frame group." } }, 404),
    );

    const refused = await failure(client.laboratoryFrames("absent", "pose"));

    expect(refused.kind).toBe("http");
    expect(refused.status).toBe(404);
    expect(refused.code).toBe("not_found");
  });
});
