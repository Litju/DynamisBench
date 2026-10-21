/**
 * A controlled `fetch` for the workbench's rendered integration tests.
 *
 * The production client calls the runtime's own `fetch`; replacing the global is therefore
 * the smallest seam that keeps the real client, the real Query client and the real routes in
 * the test. The handler sees the URL and the request init, and returns whatever the test
 * decides, including a deferred response for race gates.
 */

import { vi } from "vitest";

import { jsonResponse } from "./http-fixtures";

export type FetchRequest = {
  readonly url: string;
  readonly init: RequestInit;
};

export type FetchHandler = (request: FetchRequest) => Response | Promise<Response>;

export function stubFetch(handler: FetchHandler): {
  readonly calls: FetchRequest[];
  readonly fetch: ReturnType<typeof vi.fn>;
} {
  const calls: FetchRequest[] = [];
  const fetch = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const request = { url: String(input), init: init ?? {} };
    calls.push(request);
    return await handler(request);
  });
  vi.stubGlobal("fetch", fetch);
  return { calls, fetch };
}

/** The application's error envelope, for a refusal the client should read as `http`. */
export function errorResponse(
  status: number,
  code: string,
  message: string,
): Response {
  return jsonResponse({ error: { code, message } }, status);
}

/** A successful SSE refusal for tests that do not exercise the stream. */
export function unavailableEvents(): Response {
  return errorResponse(401, "unauthorized", "Authentication required.");
}
