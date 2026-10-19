/**
 * The bounded failure taxonomy of the typed client.
 *
 * Four kinds, and each says what the workbench may conclude:
 *
 * ```text
 * network               the address did not answer at all
 * http                  it answered with a refusal, in the application's envelope
 * invalid_response      it answered with something this client cannot read
 * incompatible_session  no request was made: the session's versions are not this client's
 * ```
 *
 * **What an error may carry.** The status, the application's own closed error code when the
 * envelope named one, and the application's own bounded message when the envelope carried
 * one. Nothing else. The rejected value, the raw body, the response headers, the request
 * URL's query, and the credential are not fields here and are not composed into the
 * message — and the underlying failure is deliberately not attached as a `cause`, because an
 * exception's text is exactly where a request URL or a platform detail reappears. A client
 * that needs to explain a refusal has the four bounded facts and the code that produced it;
 * the operator's copy of a failure is the server log.
 */

import { API_ERROR_CODES, type ApiErrorCode } from "./types";

export type ApiClientErrorKind =
  | "network"
  | "http"
  | "invalid_response"
  | "incompatible_session";

/** What an error is allowed to be built from. */
export type ApiClientErrorFacts = {
  /** The HTTP status, when a response existed. */
  readonly status?: number | null;
  /** The application's own bounded code, when the envelope named a known one. */
  readonly code?: ApiErrorCode | null;
  /** The application's own bounded message, when the envelope carried one. */
  readonly apiMessage?: string | null;
  /** The versions involved in an incompatible session, for the message only. */
  readonly versions?: {
    readonly apiVersion: string | null;
    readonly protocolVersion: number | null;
    readonly expectedApiVersion: string;
    readonly expectedProtocolVersion: number;
  };
};

export class ApiClientError extends Error {
  readonly kind: ApiClientErrorKind;

  /** The HTTP status, or `null` when no response was read. */
  readonly status: number | null;

  /** The bounded application error code, or `null` when the envelope named none. */
  readonly code: ApiErrorCode | null;

  /** The bounded application message, or `null` when the envelope carried none. */
  readonly apiMessage: string | null;

  constructor(kind: ApiClientErrorKind, facts: ApiClientErrorFacts = {}) {
    super(describe(kind, facts));
    this.name = "ApiClientError";
    this.kind = kind;
    this.status = facts.status ?? null;
    this.code = facts.code ?? null;
    this.apiMessage = facts.apiMessage ?? null;
  }
}

/**
 * The message of an error, built only from bounded facts.
 *
 * Composition rather than pass-through: nothing here interpolates a body, a header, a URL or
 * a platform error, which is what makes "the credential never appears in an error string" a
 * property of the type rather than of every call site.
 */
function describe(kind: ApiClientErrorKind, facts: ApiClientErrorFacts): string {
  switch (kind) {
    case "network":
      return "The DynamisBench application API could not be reached.";
    case "http": {
      const status = facts.status ?? null;
      const code = facts.code ?? null;
      if (status !== null && code !== null) {
        return `The DynamisBench application API refused the request (${status} ${code}).`;
      }
      if (status !== null) {
        return `The DynamisBench application API refused the request (${status}).`;
      }
      return "The DynamisBench application API refused the request.";
    }
    case "invalid_response":
      return "The DynamisBench application API answered with a response this client could not read.";
    case "incompatible_session": {
      const versions = facts.versions;
      if (versions === undefined) {
        return "The desktop session speaks a version this workbench cannot use.";
      }
      const apiVersion = versions.apiVersion ?? "an unknown API version";
      const protocolVersion =
        versions.protocolVersion === null ? "an unknown protocol version" : String(versions.protocolVersion);
      return (
        `The desktop session speaks ${apiVersion} / protocol ${protocolVersion}; this ` +
        `workbench requires ${versions.expectedApiVersion} / protocol ${versions.expectedProtocolVersion}.`
      );
    }
  }
}

/** Whether `value` is one of the application's own error codes. */
export function isApiErrorCode(value: unknown): value is ApiErrorCode {
  return API_ERROR_CODES.some((code) => code === value);
}
