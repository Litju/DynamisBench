/**
 * Bounded reconnect policy for the authenticated event stream.
 *
 * The client supplies one stream per attempt; this module decides whether to ask again and
 * how long to wait. It never calls `fetch`, never constructs a URL and never sees a
 * credential — it is policy over an `AsyncIterable`, which is what makes it testable with a
 * controlled clock instead of a sleep.
 *
 * **What is never retried.** An authentication refusal (`401`/`403`), any other `4xx`, an
 * incompatible envelope (`invalid_response`) and a session this client cannot speak are
 * terminal for the stream generation: repeating them would turn a decision into a loop. A
 * `5xx` or a network failure is transient and is retried with exponential backoff.
 *
 * **What is bounded.** Consecutive failures without a received event stop after
 * `maxConsecutiveFailures`; total reconnect cycles stop after `maxReconnects`. A successful
 * event resets the consecutive-failure count but not the cycle budget. The UI therefore
 * ends in `unavailable` rather than retrying forever.
 */

import type { ApiClient } from "./client";
import { ApiClientError } from "./errors";
import type { ApplicationEvent } from "./types";

export const DEFAULT_MAX_CONSECUTIVE_FAILURES = 5;
export const DEFAULT_MAX_RECONNECTS = 20;
export const DEFAULT_BASE_DELAY_MS = 250;
export const DEFAULT_MAX_DELAY_MS = 4_000;

/** What the Activity surface may say about the stream itself. */
export type EventStreamState =
  | "connecting"
  | "live"
  | "reconnecting"
  | "refused"
  | "unavailable";

export interface RetryPolicy {
  readonly maxConsecutiveFailures: number;
  readonly maxReconnects: number;
  readonly baseDelayMs: number;
  readonly maxDelayMs: number;
  /** Injectable wait, so a test controls the clock and an abort still resolves promptly. */
  readonly wait: (milliseconds: number, signal: AbortSignal) => Promise<void>;
}

/** Exponential, deterministic backoff with a ceiling. No jitter: the sequence is a contract. */
export function reconnectDelay(
  attempt: number,
  policy: Pick<RetryPolicy, "baseDelayMs" | "maxDelayMs"> = {
    baseDelayMs: DEFAULT_BASE_DELAY_MS,
    maxDelayMs: DEFAULT_MAX_DELAY_MS,
  },
): number {
  if (attempt <= 0) {
    return 0;
  }
  return Math.min(policy.maxDelayMs, policy.baseDelayMs * 2 ** (attempt - 1));
}

function defaultWait(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) {
      resolve();
      return;
    }
    const timer = setTimeout(finish, milliseconds);

    function finish() {
      clearTimeout(timer);
      signal.removeEventListener("abort", finish);
      resolve();
    }

    signal.addEventListener("abort", finish, { once: true });
  });
}

export interface EventStreamOptions {
  readonly client: Pick<ApiClient, "streamEvents">;
  readonly signal: AbortSignal;
  readonly onEvent: (event: ApplicationEvent) => void;
  readonly onState: (state: EventStreamState) => void;
  readonly policy?: Partial<Omit<RetryPolicy, "wait">> & {
    readonly wait?: RetryPolicy["wait"];
  };
}

export interface EventStreamHandle {
  /** Stop the loop and abort any wait. Idempotent. */
  stop(): void;
  /** Settles when the loop has stopped, for deterministic tests. */
  readonly done: Promise<void>;
}

export function startEventStream(options: EventStreamOptions): EventStreamHandle {
  const policy: RetryPolicy = {
    maxConsecutiveFailures:
      options.policy?.maxConsecutiveFailures ?? DEFAULT_MAX_CONSECUTIVE_FAILURES,
    maxReconnects: options.policy?.maxReconnects ?? DEFAULT_MAX_RECONNECTS,
    baseDelayMs: options.policy?.baseDelayMs ?? DEFAULT_BASE_DELAY_MS,
    maxDelayMs: options.policy?.maxDelayMs ?? DEFAULT_MAX_DELAY_MS,
    wait: options.policy?.wait ?? defaultWait,
  };

  const controller = new AbortController();
  const stop = () => controller.abort();
  const signal = controller.signal;

  const forwardAbort = () => controller.abort();
  if (options.signal.aborted) {
    controller.abort();
  } else {
    options.signal.addEventListener("abort", forwardAbort, { once: true });
  }

  const done = run();

  async function run(): Promise<void> {
    let attempts = 0;
    let failuresWithoutEvent = 0;
    let firstAttempt = true;

    try {
      while (!signal.aborted) {
        options.onState(firstAttempt ? "connecting" : "reconnecting");
        firstAttempt = false;

        let received = false;
        try {
          for await (const event of options.client.streamEvents({ signal })) {
            if (signal.aborted) {
              return;
            }
            received = true;
            failuresWithoutEvent = 0;
            options.onState("live");
            options.onEvent(event);
          }
        } catch (error) {
          if (signal.aborted) {
            return;
          }
          if (isTerminal(error)) {
            options.onState("refused");
            return;
          }
        }

        if (signal.aborted) {
          return;
        }

        attempts += 1;
        if (received) {
          failuresWithoutEvent = 0;
        } else {
          failuresWithoutEvent += 1;
        }

        if (
          attempts > policy.maxReconnects ||
          failuresWithoutEvent > policy.maxConsecutiveFailures
        ) {
          options.onState("unavailable");
          return;
        }

        await policy.wait(reconnectDelay(attempts, policy), signal);
      }
    } finally {
      options.signal.removeEventListener("abort", forwardAbort);
    }
  }

  return {
    stop,
    done,
  };
}

/** Whether retrying this failure could ever produce a different answer. */
function isTerminal(error: unknown): boolean {
  if (!(error instanceof ApiClientError)) {
    return false;
  }

  if (error.kind === "invalid_response" || error.kind === "incompatible_session") {
    return true;
  }

  if (error.kind === "http" && error.status !== null) {
    return error.status >= 400 && error.status < 500;
  }

  return false;
}
