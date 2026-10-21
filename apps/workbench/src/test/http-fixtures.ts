/**
 * Response stubs for the client tests.
 *
 * The client reads exactly three things from a response — `ok`, `status` and `json()` — so a
 * stub is exactly that surface. Using a real `Response` would test the environment's
 * implementation of a class the client does not depend on, and would make the error paths (a
 * body that is not JSON at all) harder to state than the paths that work.
 */

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

/** A `Response` whose body is a stream of the supplied UTF-8 chunks. */
export function streamResponse(chunks: readonly string[]): Response {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) {
          controller.enqueue(encoder.encode(chunk));
        }
        controller.close();
      },
    }),
    { status: 200, headers: { "Content-Type": "text/event-stream" } },
  );
}

/** A stream a test can feed after the request has been made. */
export function controlledStreamResponse(): {
  readonly response: Response;
  push(chunk: string): void;
  close(): void;
} {
  const encoder = new TextEncoder();
  let streamController: ReadableStreamDefaultController<Uint8Array> | null = null;
  const response = new Response(
    new ReadableStream<Uint8Array>({
      start(controller) {
        streamController = controller;
      },
    }),
    { status: 200, headers: { "Content-Type": "text/event-stream" } },
  );

  return {
    response,
    push(chunk) {
      streamController?.enqueue(encoder.encode(chunk));
    },
    close() {
      streamController?.close();
    },
  };
}

/** A `Response` whose body yields exactly these bytes. */
export function bytesResponse(bytes: Uint8Array, status = 200): Response {
  return new Response(bytes as BodyInit, { status });
}
