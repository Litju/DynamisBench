/**
 * The runtime status the shell displays: one state, derived from the session and the API.
 *
 * A pure function rather than a component's conditional tree, because these states are the
 * workbench's answer to "can I use this?" and each of them has to be reachable, reviewable
 * and testable on its own. The session decides most of them; the `info` read decides the two
 * that only exist once there is an API to ask — connecting, and ready.
 *
 * Every state says what is true and nothing more. A failure names its bounded code; a state
 * that is merely unavailable says so instead of implying a failure; and no state carries a
 * path, a credential, or a scientific claim.
 */

import { ApiClientError } from "../api/errors";
import type { DesktopFailureCode, WorkbenchSession } from "../session/types";

/** How a state is rendered: not a colour, a meaning. */
export type RuntimeTone = "neutral" | "pending" | "ready" | "danger";

export type RuntimeStateId =
  | "browser_unavailable"
  | "starting"
  | "stopped"
  | "failed"
  | "incompatible"
  | "connecting"
  | "ready"
  | "api_error";

export type RuntimeState = {
  readonly id: RuntimeStateId;
  readonly tone: RuntimeTone;
  /** The short status a badge carries. */
  readonly label: string;
  /** The sentence that says what the label means. */
  readonly detail: string;
};

/** The `info` read, reduced to what the status needs. */
export type InfoState =
  | { readonly status: "pending" }
  | { readonly status: "error"; readonly error: unknown }
  | {
      readonly status: "success";
      readonly application: string;
      readonly version: string;
      readonly apiVersion: string;
    };

/** One sentence per bounded failure code, so a diagnosis is readable without a lookup. */
const FAILURE_DETAILS: Record<DesktopFailureCode, string> = {
  spawn_failed: "the local API process could not be started",
  credential_unavailable: "a session credential could not be produced",
  startup_timeout: "the local API did not report readiness in time",
  readiness_protocol_error: "the local API answered readiness in a form the shell does not speak",
  sidecar_startup_exit: "the local API exited before it became ready",
  protocol_violation: "the local API wrote to the protocol channel after readiness",
  unexpected_exit: "the local API exited after readiness without being asked to stop",
  shutdown_timeout: "the local API did not stop within the shutdown deadline",
};

export function runtimeState(session: WorkbenchSession, info: InfoState): RuntimeState {
  switch (session.phase) {
    case "unavailable":
      return {
        id: "browser_unavailable",
        tone: "neutral",
        label: "Desktop session unavailable",
        detail:
          "This browser is not running inside the DynamisBench desktop shell, so there is no local API session.",
      };

    case "starting":
      return {
        id: "starting",
        tone: "pending",
        label: "Starting",
        detail: "Waiting for the local application API to report readiness.",
      };

    case "stopped":
      return {
        id: "stopped",
        tone: "neutral",
        label: "Stopped",
        detail: "The local application API is not running.",
      };

    case "failed":
      return {
        id: "failed",
        tone: "danger",
        label: "Desktop session failed",
        detail: failureDetail(session.failure, session.restartRequired),
      };

    case "incompatible":
      return {
        id: "incompatible",
        tone: "danger",
        label: "Incompatible API",
        detail:
          `The desktop session speaks ${session.apiVersion ?? "an unknown API version"} / ` +
          `protocol ${session.protocolVersion ?? "an unknown protocol version"}; this workbench ` +
          "requires v1 / protocol 1. No request was made.",
      };

    case "ready":
      return readyState(info);
  }
}

function readyState(info: InfoState): RuntimeState {
  switch (info.status) {
    case "pending":
      return {
        id: "connecting",
        tone: "pending",
        label: "Connecting",
        detail: "Reading the application's build identity from the local API.",
      };

    case "error":
      return {
        id: "api_error",
        tone: "danger",
        label: "API error",
        detail: apiErrorDetail(info.error),
      };

    case "success":
      return {
        id: "ready",
        tone: "ready",
        label: "Ready",
        detail: `${info.application} ${info.version}, API ${info.apiVersion}.`,
      };
  }
}

function failureDetail(failure: DesktopFailureCode | null, restartRequired: boolean): string {
  const reason =
    failure === null
      ? "the desktop shell reported a failure it did not name"
      : FAILURE_DETAILS[failure];

  return restartRequired
    ? `The local API session ended: ${reason}. Restart the desktop shell to start a new session.`
    : `The local API session could not start: ${reason}.`;
}

/**
 * The detail for a failed read.
 *
 * A bounded client error carries the application's own message when the envelope had one —
 * that message is the API's explanation of its own refusal, which is exactly the text a user
 * should see — and never a body, a header or a URL.
 */
function apiErrorDetail(error: unknown): string {
  if (error instanceof ApiClientError) {
    return error.apiMessage ?? error.message;
  }

  return "The local application API could not be read.";
}
