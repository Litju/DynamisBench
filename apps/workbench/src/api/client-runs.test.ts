/**
 * The typed client's run methods: workspace-scoped paths with encoded identifiers, the three
 * commands as POSTs with exactly the study/case/values body, bounded refusals, and answers about
 * another run refused as invalid.
 */

import { describe, expect, it } from "vitest";

import { recordingFetch, jsonResponse } from "../test/http-fixtures";
import { binaryResponse, frameStream } from "../test/laboratory-fixtures";
import {
  NOMINAL_RUN_ID,
  RUN_CATALOGUE,
  RUN_EVIDENCE,
  RUN_LIST,
  RUN_MODEL,
  RUN_PREFLIGHT,
  RUN_PREFLIGHT_REFUSED,
  RUN_PROGRESS_COMPLETED,
  RUN_RECORDING,
  RUN_STARTED,
} from "../test/run-fixtures";
import { errorResponse } from "../test/fetch-stub";
import { FIXTURE_CREDENTIAL, FIXTURE_ORIGIN, readyApiSession } from "../test/session-fixtures";
import { createApiClient } from "./client";
import { ApiClientError } from "./errors";

const WORKSPACE = "abc_DEF-123";
const BASE = `${FIXTURE_ORIGIN}/api/v1/workspaces/${WORKSPACE}`;

function clientWith(answer: (url: string) => Response) {
  const recorder = recordingFetch((call) => answer(call.url));
  return { client: createApiClient(readyApiSession(), { fetch: recorder.fetch }), calls: recorder.calls };
}

async function failure(promise: Promise<unknown>): Promise<ApiClientError> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof ApiClientError) return error;
    throw error;
  }
  throw new Error("the request was expected to fail");
}

const REQUEST = {
  study_id: "st.squat.configuration",
  case_id: "nominal",
  values: { "f.squat.integration-timestep": 0.001 },
};

describe("the run commands", () => {
  it("preflights with a POST of exactly the study, case and values", async () => {
    const { client, calls } = clientWith(() => jsonResponse(RUN_PREFLIGHT));

    const report = await client.preflightRun(WORKSPACE, REQUEST);

    expect(report.decision).toBe("ready");
    expect(calls[0]?.url).toBe(`${BASE}/runs/preflight`);
    expect(calls[0]?.init.method).toBe("POST");
    expect(JSON.parse(String(calls[0]?.init.body))).toEqual(REQUEST);
    const headers = calls[0]?.init.headers as Record<string, string>;
    expect(headers.Authorization).toBe(`Bearer ${FIXTURE_CREDENTIAL}`);
    expect(headers["Content-Type"]).toBe("application/json");
    expect(calls[0]?.init.credentials).toBe("omit");
  });

  it("reports a planning refusal with the service's bounded message", async () => {
    const { client } = clientWith(() =>
      errorResponse(RUN_PREFLIGHT_REFUSED.status, "http_error", RUN_PREFLIGHT_REFUSED.body.error.message),
    );

    const refused = await failure(client.preflightRun(WORKSPACE, REQUEST));

    expect(refused.kind).toBe("http");
    expect(refused.status).toBe(409);
    expect(refused.apiMessage).toMatch(/does not divide the 10 ms sample period/);
  });

  it("starts and cancels with POSTs, and refuses progress about another run", async () => {
    const { client, calls } = clientWith((url) => (url.endsWith("/runs") ? jsonResponse(RUN_STARTED, 202) : jsonResponse(RUN_PROGRESS_COMPLETED)));

    const started = await client.startRun(WORKSPACE, REQUEST);
    await client.cancelRun(WORKSPACE, started.run_id);
    const other = await failure(client.runProgress(WORKSPACE, "run-0000000000-001"));

    expect(calls[0]?.url).toBe(`${BASE}/runs`);
    expect(calls[0]?.init.method).toBe("POST");
    expect(calls[1]?.url).toBe(`${BASE}/runs/${NOMINAL_RUN_ID}/cancel`);
    expect(calls[1]?.init.method).toBe("POST");
    expect(calls[1]?.init.body).toBeUndefined();
    expect(other.kind).toBe("invalid_response");
  });

  it("encodes the workspace and run identifiers into the path", async () => {
    const { client, calls } = clientWith(() => jsonResponse(RUN_PROGRESS_COMPLETED));

    await failure(client.runProgress("a/b", "run-x/../y"));

    expect(calls[0]?.url).toBe(`${FIXTURE_ORIGIN}/api/v1/workspaces/a%2Fb/runs/run-x%2F..%2Fy/progress`);
  });
});

describe("the run reads", () => {
  it("reads the catalogue, the list and the evidence as GETs", async () => {
    const { client, calls } = clientWith((url) =>
      url.endsWith("/studies") ? jsonResponse(RUN_CATALOGUE) : url.endsWith("/runs") ? jsonResponse(RUN_LIST) : jsonResponse(RUN_EVIDENCE),
    );

    await client.studyCatalogue(WORKSPACE);
    await client.listRuns(WORKSPACE);
    const evidence = await client.runEvidence(WORKSPACE, NOMINAL_RUN_ID);

    expect(calls.map((call) => [call.init.method, call.url])).toEqual([
      ["GET", `${BASE}/studies`],
      ["GET", `${BASE}/runs`],
      ["GET", `${BASE}/runs/${NOMINAL_RUN_ID}/evidence`],
    ]);
    expect(evidence.status).toBe("verified");
  });

  it("reads a verified run as a recording of kind run, its model and its frames", async () => {
    const { client, calls } = clientWith((url) =>
      url.endsWith("/recording")
        ? jsonResponse(RUN_RECORDING)
        : url.endsWith("/model")
          ? jsonResponse(RUN_MODEL)
          : binaryResponse(frameStream(RUN_RECORDING, "kinematics")),
    );

    const recording = await client.runRecording(WORKSPACE, NOMINAL_RUN_ID);
    await client.runModel(WORKSPACE, NOMINAL_RUN_ID);
    const bytes = await client.runFrames(WORKSPACE, NOMINAL_RUN_ID, "kinematics");

    expect(recording.kind).toBe("run");
    expect(bytes.byteLength).toBeGreaterThan(1000);
    expect(calls[2]?.url).toBe(`${BASE}/runs/${NOMINAL_RUN_ID}/frames/kinematics`);
    expect((calls[2]?.init.headers as Record<string, string>).Accept).toBe("application/vnd.apache.arrow.stream");
  });

  it("refuses a recording about another run, and a packaged recording passed off as a run", async () => {
    const { client } = clientWith(() => jsonResponse(RUN_RECORDING));
    const other = await failure(client.runRecording(WORKSPACE, "run-0000000000-001"));
    expect(other.kind).toBe("invalid_response");

    const packaged = { ...(structuredClone(RUN_RECORDING) as Record<string, unknown>), kind: "nominal" };
    const { client: second } = clientWith(() => jsonResponse(packaged));
    const disguised = await failure(second.runRecording(WORKSPACE, NOMINAL_RUN_ID));
    expect(disguised.kind).toBe("invalid_response");
  });

  it("reports a rejected run as a refusal, never as data", async () => {
    const { client } = clientWith(() => errorResponse(409, "http_error", "derived bundle: payload_modified [canonical/series.parquet]"));
    const refused = await failure(client.runRecording(WORKSPACE, NOMINAL_RUN_ID));
    expect(refused.status).toBe(409);
    expect(refused.apiMessage).toMatch(/payload_modified/);
  });
});
