/**
 * The session vocabulary the workbench speaks, and the refinement of the desktop bridge's
 * own response into it.
 *
 * Two vocabularies, deliberately different. The desktop shell publishes a *lifecycle* — the
 * four states its sidecar supervisor can be in, plus the closed set of ways a session can
 * fail — and this module restates that as [`WorkbenchSession`]: a state a React tree can
 * branch on, in which "there is no desktop shell at all" and "the versions do not match" are
 * named states rather than absent ones.
 *
 * The refinement is where the accepted invariant is enforced on the client side:
 *
 * ```text
 * ready      => origin + api_version + protocol_version + credential
 * non-ready  => no usable API session
 * ```
 *
 * A response that breaks it is not repaired into a usable session. A `ready` record with a
 * missing field is reported as a desktop failure with no bounded code, and a `ready` record
 * whose versions are not this workbench's is reported as `incompatible`; neither produces an
 * HTTP client, so no request is ever made against an address the frontend cannot
 * authenticate against or cannot understand.
 *
 * Nothing here holds a credential beyond the one a ready session carries, and nothing here
 * writes, logs, serialises or renders it. The credential is a plain field of an in-memory
 * record, which is all it is allowed to be.
 */

/** The four lifecycle states the desktop shell publishes. */
export const DESKTOP_STATUSES = ["starting", "ready", "failed", "stopped"] as const;

export type DesktopSessionStatus = (typeof DESKTOP_STATUSES)[number];

/**
 * The closed set of ways a desktop session can fail.
 *
 * Restated from the shell rather than imported: the frontend cannot import Rust, and this
 * list is a reviewed copy of a contract that is itself a closed vocabulary. A code this
 * list does not know is not invented into it — it degrades to `null`, which the UI reads as
 * "the desktop reported a failure without one of its named reasons".
 */
export const DESKTOP_FAILURE_CODES = [
  "spawn_failed",
  "credential_unavailable",
  "startup_timeout",
  "readiness_protocol_error",
  "sidecar_startup_exit",
  "protocol_violation",
  "unexpected_exit",
  "shutdown_timeout",
] as const;

export type DesktopFailureCode = (typeof DESKTOP_FAILURE_CODES)[number];

/**
 * The non-secret lifecycle snapshot the `dynamisbench-api-status` event carries.
 *
 * Structurally incapable of carrying a credential: the shell has no such field in the
 * payload type. `origin`, `api_version` and `protocol_version` are present exactly when the
 * session is ready, so a snapshot alone can be published as a state but never promoted to a
 * usable session.
 */
export type DesktopSessionSnapshot = {
  status: DesktopSessionStatus;
  origin: string | null;
  api_version: string | null;
  protocol_version: number | null;
  restart_required: boolean;
  failure: DesktopFailureCode | null;
};

/**
 * The full `get_api_session` response: the snapshot plus, only while ready, the credential.
 *
 * The one shape in which a credential crosses the process boundary, and the only shape this
 * module accepts one from. Modelled as the wire writes it — snake_case, exactly the
 * published fields — so the frontend type is the accepted contract rather than a
 * translation of it.
 */
export type DesktopApiSession = DesktopSessionSnapshot & {
  credential: string | null;
};

/** The API version this workbench speaks. */
export const EXPECTED_API_VERSION = "v1";

/** The sidecar protocol version this workbench speaks. */
export const EXPECTED_PROTOCOL_VERSION = 1;

/**
 * A refined, usable session: everything an HTTP client needs and nothing else.
 *
 * Constructed only by [`refineDesktopSession`], and only from a `ready` record that carried
 * all four facts. The versions are the literals this workbench expects, because a session
 * with any other versions never reaches this type.
 */
export type ReadyApiSession = {
  readonly origin: string;
  readonly apiVersion: typeof EXPECTED_API_VERSION;
  readonly protocolVersion: typeof EXPECTED_PROTOCOL_VERSION;
  readonly credential: string;
};

/**
 * What the workbench knows about its desktop session at one instant.
 *
 * `unavailable` is the ordinary browser: no Tauri runtime, so no session to report and no
 * IPC to attempt. `starting`, `failed` and `stopped` mirror the shell's own lifecycle.
 * `incompatible` says the shell is serving a session this workbench cannot speak to.
 */
export type WorkbenchSession =
  | { readonly phase: "unavailable" }
  | { readonly phase: "starting" }
  | { readonly phase: "ready"; readonly api: ReadyApiSession }
  | {
      readonly phase: "incompatible";
      readonly apiVersion: string | null;
      readonly protocolVersion: number | null;
    }
  | {
      readonly phase: "failed";
      readonly failure: DesktopFailureCode | null;
      readonly restartRequired: boolean;
    }
  | { readonly phase: "stopped" };

/**
 * A desktop failure this shell can report without a code from the shell's vocabulary.
 *
 * Used when the bridge answered something unreadable or a `ready` record was missing a fact
 * a ready session must carry. A bounded code would attribute a diagnosis the desktop never
 * made, so no code is claimed.
 */
const UNCLASSIFIED_FAILURE: WorkbenchSession = {
  phase: "failed",
  failure: null,
  restartRequired: false,
};
function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function isStatus(value: unknown): value is DesktopSessionStatus {
  return DESKTOP_STATUSES.some((status) => status === value);
}

function failureCodeOf(value: unknown): DesktopFailureCode | null {
  return DESKTOP_FAILURE_CODES.find((code) => code === value) ?? null;
}

function nonEmpty(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function nonNegativeInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;
}

/**
 * Refine a full `get_api_session` response into a session the workbench can act on.
 *
 * Total: any input produces a state. Everything that is not a readable `ready` record
 * carrying all four facts and this workbench's versions ends as a non-ready state, which is
 * the only conservative direction — a session that cannot be used is reported, never
 * guessed at.
 */
export function refineDesktopSession(value: unknown): WorkbenchSession {
  const record = asRecord(value);
  if (record === null || !isStatus(record.status)) {
    return UNCLASSIFIED_FAILURE;
  }

  if (record.status === "starting") {
    return { phase: "starting" };
  }

  if (record.status === "stopped") {
    return { phase: "stopped" };
  }

  if (record.status === "failed") {
    return {
      phase: "failed",
      failure: failureCodeOf(record.failure),
      restartRequired: record.restart_required === true,
    };
  }

  const apiVersion = nonEmpty(record.api_version);
  const protocolVersion = nonNegativeInteger(record.protocol_version);

  if (apiVersion === null || protocolVersion === null) {
    return UNCLASSIFIED_FAILURE;
  }

  if (apiVersion !== EXPECTED_API_VERSION || protocolVersion !== EXPECTED_PROTOCOL_VERSION) {
    return { phase: "incompatible", apiVersion, protocolVersion };
  }

  const origin = nonEmpty(record.origin);
  const credential = nonEmpty(record.credential);

  if (origin === null || credential === null) {
    return UNCLASSIFIED_FAILURE;
  }

  return {
    phase: "ready",
    api: {
      origin,
      apiVersion: EXPECTED_API_VERSION,
      protocolVersion: EXPECTED_PROTOCOL_VERSION,
      credential,
    },
  };
}

/**
 * Refine a lifecycle event payload into the state it announces, or `null` when the event
 * cannot announce one.
 *
 * A lifecycle event carries no credential, so this function never returns a ready session:
 * a `ready` event is a statement that a bootstrap read should follow, not a session in
 * itself. Anything unreadable returns `null` so the caller reconciles through the bridge
 * rather than publishing a guess.
 */
export function refineDesktopSnapshot(value: unknown): WorkbenchSession | null {
  const record = asRecord(value);
  if (record === null || !isStatus(record.status)) {
    return null;
  }

  if (record.status === "starting") {
    return { phase: "starting" };
  }

  if (record.status === "stopped") {
    return { phase: "stopped" };
  }

  if (record.status === "failed") {
    return {
      phase: "failed",
      failure: failureCodeOf(record.failure),
      restartRequired: record.restart_required === true,
    };
  }

  return null;
}

/**
 * Whether two sessions describe the same state.
 *
 * Used to keep React state identity stable when a re-read returns what the workbench already
 * holds. Two ready sessions are the same only when all four facts agree — a new credential
 * on the same address is a new session generation, not the same one.
 */
export function sessionsMatch(previous: WorkbenchSession, next: WorkbenchSession): boolean {
  if (previous.phase !== next.phase) {
    return false;
  }

  if (previous.phase === "ready" && next.phase === "ready") {
    return (
      previous.api.origin === next.api.origin &&
      previous.api.apiVersion === next.api.apiVersion &&
      previous.api.protocolVersion === next.api.protocolVersion &&
      previous.api.credential === next.api.credential
    );
  }

  if (previous.phase === "failed" && next.phase === "failed") {
    return (
      previous.failure === next.failure && previous.restartRequired === next.restartRequired
    );
  }

  if (previous.phase === "incompatible" && next.phase === "incompatible") {
    return (
      previous.apiVersion === next.apiVersion && previous.protocolVersion === next.protocolVersion
    );
  }

  return true;
}
