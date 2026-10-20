/**
 * The invariants of the bounded error type itself.
 *
 * The client is the only production constructor and it already withholds an unsafe message,
 * but the field's bound belongs to the type: a future construction site must not be able to
 * place an unbounded server string into `apiMessage` by forgetting the check.
 */

import { describe, expect, it } from "vitest";

import { ApiClientError, MAX_API_MESSAGE_LENGTH } from "./errors";

describe("ApiClientError.apiMessage", () => {
  it("keeps a message at the reviewed bound", () => {
    const message = "m".repeat(MAX_API_MESSAGE_LENGTH);

    const error = new ApiClientError("http", {
      status: 404,
      code: "not_found",
      apiMessage: message,
    });

    expect(error.apiMessage).toBe(message);
    expect(error.status).toBe(404);
    expect(error.code).toBe("not_found");
  });

  it("discards a message over the reviewed bound and keeps the other facts", () => {
    const error = new ApiClientError("http", {
      status: 500,
      code: "internal_error",
      apiMessage: "m".repeat(MAX_API_MESSAGE_LENGTH + 1),
    });

    expect(error.apiMessage).toBeNull();
    expect(error.status).toBe(500);
    expect(error.code).toBe("internal_error");
    expect(error.message).toBe(
      "The DynamisBench application API refused the request (500 internal_error).",
    );
  });
});
