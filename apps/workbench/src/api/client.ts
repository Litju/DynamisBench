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
import { ApiClientError, isApiErrorCode } from "./errors";
import type {
  ApiErrorCode,
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

  /** One request, and the three failures it can end in that are not a typed response. */
  async function send(path: string, init: { method: string; headers?: Headers; body?: string }): Promise<unknown> {
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
      const failure = await readEnvelope(response);
      throw new ApiClientError("http", {
        status: response.status,
        code: failure?.code ?? null,
        apiMessage: failure?.message ?? null,
      });
    }

    return await readObject(response);
  }

  return {
    async health(): Promise<HealthResponse> {
      const body = await send("/health", { method: "GET" });
      return body as HealthResponse;
    },

    async info(): Promise<ApplicationInfoResponse> {
      const body = await send("/info", { method: "GET" });
      return body as ApplicationInfoResponse;
    },

    async openWorkspace(request: OpenWorkspaceRequest): Promise<OpenWorkspaceResponse> {
      const body = await send("/workspaces/open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_root: request.source_root,
          evidence_root: request.evidence_root,
        }),
      });
      return body as OpenWorkspaceResponse;
    },

    async listArtifacts(workspaceId: string): Promise<WorkspaceDiscoveryResponse> {
      const body = await send(`/workspaces/${encodeURIComponent(workspaceId)}/artifacts`, {
        method: "GET",
      });
      return body as WorkspaceDiscoveryResponse;
    },

    async getArtifact(workspaceId: string, artifactId: string): Promise<ArtifactInspectionResponse> {
      const body = await send(
        `/workspaces/${encodeURIComponent(workspaceId)}/artifacts/${encodeURIComponent(artifactId)}`,
        { method: "GET" },
      );
      return body as ArtifactInspectionResponse;
    },
  };
}

/** A read model: a JSON object, or a response this client cannot use. */
async function readObject(response: Response): Promise<Record<string, unknown>> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new ApiClientError("invalid_response", { status: response.status });
  }

  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    throw new ApiClientError("invalid_response", { status: response.status });
  }

  return body as Record<string, unknown>;
}

/**
 * The application's error envelope, if this response carried one.
 *
 * Returns `null` rather than failing: a refusal that arrived with an unreadable body is still
 * a refusal, and the status is the part of it that is always true. A code the frontend's
 * closed vocabulary does not contain is not adopted into it.
 */
async function readEnvelope(
  response: Response,
): Promise<{ code: ApiErrorCode | null; message: string | null } | null> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return null;
  }

  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    return null;
  }

  const error = (body as Record<string, unknown>).error;
  if (typeof error !== "object" || error === null || Array.isArray(error)) {
    return null;
  }

  const { code, message } = error as Record<string, unknown>;
  if (!isApiErrorCode(code)) {
    return null;
  }

  return { code, message: typeof message === "string" ? message : null };
}
