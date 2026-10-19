/**
 * Response stubs for the client tests.
 *
 * The client reads exactly three things from a response — `ok`, `status` and `json()` — so a
 * stub is exactly that surface. Using a real `Response` would test the environment's
 * implementation of a class the client does not depend on, and would make the error paths
 * (a body that is not JSON at all) harder to state than the paths that work.
 */

import type { ApiClientErrorFacts } from "../api/errors";

/** A response the client can read, with a JSON body. */
export function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

/** A response whose body is not JSON, however valid its status line was. */
export function unreadableResponse(status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => {
      throw new SyntaxError("Unexpected token < in JSON at position 0");
    },
  } as unknown as Response;
}

/** A response that resolves to no body at all. */
export function emptyResponse(status: number): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => {
      throw new SyntaxError("Unexpected end of JSON input");
    },
  } as unknown as Response;
}

/** One recorded call, as the client made it. */
export type RecordedCall = {
  readonly url: string;
  readonly init: RequestInit;
};

/**
 * A `fetch` that records every call and answers with what the test decides.
 *
 * Injected through `createApiClient`'s own option, so the client under test is the production
 * client and the only thing replaced is the network.
 */
export function recordingFetch(
  responder: (call: RecordedCall) => Response | Promise<Response>,
): { fetch: (input: string, init: RequestInit) => Promise<Response>; calls: RecordedCall[] } {
  const calls: RecordedCall[] = [];
  return {
    calls,
    async fetch(input, init) {
      const call = { url: input, init };
      calls.push(call);
      return responder(call);
    },
  };
}

/** The facts an error should have, written the way the tests read them. */
export const errorFacts = {
  code: null,
  apiMessage: null,
} satisfies ApiClientErrorFacts;
