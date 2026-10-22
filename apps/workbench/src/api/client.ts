/**
 * The one HTTP client boundary for the local application API.
 *
 * This is the only frontend module that calls `fetch`, and the structural gate in
 * `src/test/boundaries.test.ts` fails if a second one appears. Components never build a URL,
 * never set a header and never see a credential: they call a typed method and receive an
 * accepted read model, or a bounded [`ApiClientError`].
 *
 * **A client exists only for a refined ready session.** The connection carries the four
 * facts a ready session has — origin, credential, API version, protocol version — and the
 * versions are checked here as well as at refinement, so a mismatch is refused before any
 * request is built. Refinement already makes an incompatible session unreachable, and this
 * second check is what makes `incompatible_session` a property of the client rather than of
 * its caller.
 *
 * **Every request is the same request**: built under `/api/v1` from the session origin,
 * carrying the bearer credential, `credentials: 'omit'` so no cookie is ever sent or
 * accepted, and `cache: 'no-store'` so no browser cache stands in for the authority. POST
 * bodies are JSON. Opaque identifiers are URL-encoded, because an identifier is opaque and a
 * client that assumed it was URL-safe would be relying on a minting detail.
 *
 * **What the client refuses to do.** It never retries (the QueryClient decides retry policy,
 * and it is one decision made once), never follows the server's advice about where else to
 * look, never reads a body it did not ask for, and never puts a credential anywhere but the
 * one request header that needs it.
 */

import { EXPECTED_API_VERSION, EXPECTED_PROTOCOL_VERSION } from "../session/types";
import {
  decodeApplicationEvent,
  decodeApplicationInfoResponse,
  decodeArtifactInspectionResponse,
  decodeHealthResponse,
  decodeOpenWorkspaceResponse,
  decodeWorkspaceDiscoveryResponse,
} from "./decode";
import { ApiClientError, MAX_API_MESSAGE_LENGTH, isApiErrorCode } from "./errors";
import { SseParseError, SseParser } from "./sse";
import type {
  ApiErrorCode,
  ApplicationEvent,
  ApplicationInfoResponse,
  ArtifactInspectionResponse,
  HealthResponse,
  OpenWorkspaceRequest,
  OpenWorkspaceResponse,
  WorkspaceDiscoveryResponse,
} from "./types";

/** The versioned namespace every request is built under. */
export const API_PATH_PREFIX = "/api/v1";

/** The request shape this client needs from a `fetch` implementation. */
export type FetchLike = (input: string, init: RequestInit) => Promise<Response>;

/** Everything a client is constructed from: a refined ready session, and nothing else. */
export interface ApiClientConnection {
  readonly origin: string;
  readonly credential: string;
  readonly apiVersion: string;
  readonly protocolVersion: number;
}

export interface ApiClientOptions {
  /**
   * The `fetch` implementation, injected for deterministic tests.
   *
   * The default is the runtime's own, so production code is the browser's implementation and
   * tests are exactly as deterministic as the responses they hand it.
   */
  readonly fetch?: FetchLike;
}

export interface ApiClient {
  /** `GET /api/v1/health` */
  health(): Promise<HealthResponse>;
  /** `GET /api/v1/info` */
  info(): Promise<ApplicationInfoResponse>;
  /** `POST /api/v1/workspaces/open` */
  openWorkspace(request: OpenWorkspaceRequest): Promise<OpenWorkspaceResponse>;
  /** `GET /api/v1/workspaces/{workspaceId}/artifacts` */
  listArtifacts(workspaceId: string): Promise<WorkspaceDiscoveryResponse>;
  /** `GET /api/v1/workspaces/{workspaceId}/artifacts/{artifactId}` */
  getArtifact(workspaceId: string, artifactId: string): Promise<ArtifactInspectionResponse>;
  /**
   * `GET /api/v1/events` as a live stream.
   *
   * An async iterable rather than a callback so the consumer's loop owns cancellation: the
   * supplied signal aborts the request and the iterator ends. A refusal (401, 5xx) is thrown
   * as the client's bounded error before the first frame; a malformed frame is
   * `invalid_response` and ends the iteration.
   */
  streamEvents(options: { signal: AbortSignal }): AsyncIterable<ApplicationEvent>;
}

function defaultFetch(input: string, init: RequestInit): Promise<Response> {
  return fetch(input, init);
}

/** A request's headers, before the ones every request carries. */
type Headers = Record<string, string>;

export function createApiClient(
  connection: ApiClientConnection,
  options: ApiClientOptions = {},
): ApiClient {
  if (
    connection.apiVersion !== EXPECTED_API_VERSION ||
    connection.protocolVersion !== EXPECTED_PROTOCOL_VERSION
  ) {
    throw new ApiClientError("incompatible_session", {
      versions: {
        apiVersion: connection.apiVersion,
        protocolVersion: connection.protocolVersion,
        expectedApiVersion: EXPECTED_API_VERSION,
        expectedProtocolVersion: EXPECTED_PROTOCOL_VERSION,
      },
    });
  }

  const fetchImpl = options.fetch ?? defaultFetch;
  const origin = connection.origin.replace(/\/+$/, "");
  const authorization = `Bearer ${connection.credential}`;

  function url(path: string): string {
    return `${origin}${API_PATH_PREFIX}${path}`;
  }

  /**
   * One request, its refusal, and the runtime decoding of the read model it answered with.
   *
   * The decoder is supplied by the method because only the method knows which contract the
   * body is supposed to satisfy. A body that parses as JSON but is not that model is
   * `invalid_response`: the raw value is never attached to the failure, so a malformed
   * server answer cannot be retained through the error it produces.
   */
  async function send<T>(
    path: string,
    init: { method: string; headers?: Headers; body?: string },
    decode: (body: unknown) => T | null,
  ): Promise<T> {
    let response: Response;
    try {
      response = await fetchImpl(url(path), {
        method: init.method,
        headers: {
          Accept: "application/json",
          Authorization: authorization,
          ...init.headers,
        },
        body: init.body,
        credentials: "omit",
        cache: "no-store",
      });
    } catch {
      // The implementation's own failure is not read: its text is where a URL, a platform
      // detail or a header could reappear.
      throw new ApiClientError("network");
    }

    if (!response.ok) {
      const failure = await readEnvelope(response, connection.credential);
      throw new ApiClientError("http", {
        status: response.status,
        code: failure?.code ?? null,
        apiMessage: failure?.message ?? null,
      });
    }

    const body = await readJson(response);
    const decoded = decode(body);

    if (decoded === null) {
      throw new ApiClientError("invalid_response", { status: response.status });
    }

    return decoded;
  }

  return {
    async health(): Promise<HealthResponse> {
      return await send("/health", { method: "GET" }, decodeHealthResponse);
    },

    async info(): Promise<ApplicationInfoResponse> {
      return await send("/info", { method: "GET" }, decodeApplicationInfoResponse);
    },

    async openWorkspace(request: OpenWorkspaceRequest): Promise<OpenWorkspaceResponse> {
      // The one place the shell's names for the two roots meet the API's: everything after
      // this request identifies a workspace by the identifier the response returned.
      return await send(
        "/workspaces/open",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            source_root: request.sourceRoot,
            evidence_root: request.evidenceRoot,
          }),
        },
        decodeOpenWorkspaceResponse,
      );
    },

    async listArtifacts(workspaceId: string): Promise<WorkspaceDiscoveryResponse> {
      return await send(
        `/workspaces/${encodeURIComponent(workspaceId)}/artifacts`,
        { method: "GET" },
        decodeWorkspaceDiscoveryResponse,
      );
    },

    async getArtifact(workspaceId: string, artifactId: string): Promise<ArtifactInspectionResponse> {
      return await send(
        `/workspaces/${encodeURIComponent(workspaceId)}/artifacts/${encodeURIComponent(artifactId)}`,
        { method: "GET" },
        decodeArtifactInspectionResponse,
      );
    },

    async *streamEvents({
      signal,
    }: {
      signal: AbortSignal;
    }): AsyncIterable<ApplicationEvent> {
      let response: Response;
      try {
        response = await fetchImpl(url("/events"), {
          method: "GET",
          headers: {
            Accept: "text/event-stream",
            Authorization: authorization,
          },
          credentials: "omit",
          cache: "no-store",
          signal,
        });
      } catch {
        if (signal.aborted) {
          return;
        }
        throw new ApiClientError("network");
      }

      if (!response.ok) {
        const failure = await readEnvelope(response, connection.credential);
        throw new ApiClientError("http", {
          status: response.status,
          code: failure?.code ?? null,
          apiMessage: failure?.message ?? null,
        });
      }

      if (response.body === null) {
        throw new ApiClientError("invalid_response", { status: response.status });
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8", { fatal: true });
      const parser = new SseParser();

      // One cancellation for this response body, however many reasons arrive. `reader.cancel()`
      // is what closes the connection: an abort signal may not otherwise reach the body, and
      // releasing a lock is not cancellation. The promise is retained so the generator can
      // await it before it completes, and so a second caller joins the first rather than
      // cancelling twice.
      let completed = false;
      let cancellation: Promise<void> | null = null;

      const cancelReader = (): Promise<void> => {
        if (cancellation !== null) {
          return cancellation;
        }
        try {
          cancellation = Promise.resolve(reader.cancel()).catch(() => {});
        } catch {
          cancellation = Promise.resolve();
        }
        return cancellation;
      };

      const onAbort = () => {
        void cancelReader();
      };
      if (signal.aborted) {
        void cancelReader();
      } else {
        signal.addEventListener("abort", onAbort, { once: true });
      }

      try {
        for (;;) {
          const { done, value } = await reader.read();
          if (done) {
            break;
          }

          let text: string;
          try {
            text = decoder.decode(value, { stream: true });
          } catch {
            throw new ApiClientError("invalid_response", { status: response.status });
          }

          for (const frame of parser.push(text)) {
            yield decodeFrame(frame.data, response.status);
          }
        }

        const tail = decoder.decode();
        for (const frame of [...(tail === "" ? [] : parser.push(tail)), ...parser.end()]) {
          yield decodeFrame(frame.data, response.status);
        }
        completed = true;
      } catch (error) {
        if (signal.aborted) {
          return;
        }
        if (error instanceof ApiClientError) {
          throw error;
        }
        if (error instanceof SseParseError) {
          throw new ApiClientError("invalid_response", { status: response.status });
        }
        throw new ApiClientError("invalid_response", { status: response.status });
      } finally {
        signal.removeEventListener("abort", onAbort);
        // A natural EOF needs no cancellation. Every other exit - malformed frame, oversized
        // frame, unknown event, invalid UTF-8, an abort, or a consumer that stopped iterating
        // early - must close the body before the generator is allowed to complete. Awaiting
        // the cancellation here is what makes it settled rather than merely requested.
        if (cancellation !== null) {
          await cancellation;
        } else if (!completed) {
          await cancelReader();
        }
        try {
          reader.releaseLock();
        } catch {
          // A reader whose stream has already errored has nothing left to release.
        }
      }
    },
  };
}

/**
 * One SSE frame's JSON, decoded as the application's event contract.
 *
 * A frame that is not JSON, or JSON that is not this transport's envelope, is not skipped:
 * skipping would let one malformed frame pass as a quiet gap in an otherwise authoritative
 * feed. The iterator ends and the reconnect layer decides whether the failure is retryable.
 */
function decodeFrame(data: string, status: number): ApplicationEvent {
  let body: unknown;
  try {
    body = JSON.parse(data);
  } catch {
    throw new ApiClientError("invalid_response", { status });
  }

  const event = decodeApplicationEvent(body);
  if (event === null) {
    throw new ApiClientError("invalid_response", { status });
  }
  return event;
}

/** A JSON body, if the bytes were one; `null` otherwise. */
async function readJson(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    throw new ApiClientError("invalid_response", { status: response.status });
  }
}

/** Whether a parsed body is a JSON object rather than an array, a scalar or nothing. */
function asObject(body: unknown): Record<string, unknown> | null {
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    return null;
  }
  return body as Record<string, unknown>;
}

/**
 * The application's error envelope, if this response carried one.
 *
 * Returns `null` rather than failing: a refusal that arrived with an unreadable body is still
 * a refusal, and the status is the part of it that is always true. A code the frontend's
 * closed vocabulary does not contain is not adopted into it.
 *
 * A message is adopted only when it is a string within the reviewed bound and does not
 * contain the credential this request carried. A server that echoes the bearer token in its
 * own prose is not repaired, redacted or quoted: the whole message is discarded, and the
 * bounded status and code remain. That is the difference between holding a safe field and
 * holding a sanitised copy of an unsafe one.
 */
async function readEnvelope(
  response: Response,
  credential: string,
): Promise<{ code: ApiErrorCode | null; message: string | null } | null> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return null;
  }

  const envelope = asObject(body);
  if (envelope === null) {
    return null;
  }

  const error = asObject(envelope.error);
  if (error === null || !isApiErrorCode(error.code)) {
    return null;
  }

  return {
    code: error.code,
    message: adoptableMessage(error.message, credential) ? error.message : null,
  };
}

/** Whether a server-authored message may be held at all. */
function adoptableMessage(
  message: unknown,
  credential: string,
): message is string {
  if (typeof message !== "string" || message.length > MAX_API_MESSAGE_LENGTH) {
    return false;
  }

  // An empty credential is not a string that every message contains. A real ready session
  // never supplies one, but the type does not prevent a direct construction.
  return credential.length === 0 || !message.includes(credential);
}
