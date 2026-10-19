/**
 * The refinement of the desktop bridge's response into the workbench's own vocabulary.
 *
 * These are the client-side half of the bridge contract: whatever the shell publishes, this
 * is what the frontend may conclude from it, and "a ready session that is not usable" is the
 * failure mode every case here is written against.
 */

import { describe, expect, it } from "vitest";

import { FIXTURE_CREDENTIAL, FIXTURE_ORIGIN, readySessionWire, snapshot } from "../test/session-fixtures";
import {
  refineDesktopSession,
  refineDesktopSnapshot,
  sessionsMatch,
  type WorkbenchSession,
} from "./types";

describe("refineDesktopSession", () => {
  it("turns a complete ready response into a usable session", () => {
    expect(refineDesktopSession(readySessionWire())).toEqual({
      phase: "ready",
      api: {
        origin: FIXTURE_ORIGIN,
        apiVersion: "v1",
        protocolVersion: 1,
        credential: FIXTURE_CREDENTIAL,
      },
    });
  });

  it("keeps the shell's lifecycle states", () => {
    expect(refineDesktopSession(snapshot({ status: "starting" }))).toEqual({ phase: "starting" });
    expect(refineDesktopSession(snapshot({ status: "stopped" }))).toEqual({ phase: "stopped" });
    expect(
      refineDesktopSession(
        snapshot({ status: "failed", failure: "unexpected_exit", restart_required: true }),
      ),
    ).toEqual({ phase: "failed", failure: "unexpected_exit", restartRequired: true });
  });

  it("reports a failure code this workbench does not know as no code at all", () => {
    const refined = refineDesktopSession(
      snapshot({ status: "failed", failure: "invented_failure" as never }),
    );

    expect(refined).toEqual({ phase: "failed", failure: null, restartRequired: false });
  });

  it("reports version mismatches as incompatible instead of using them", () => {
    expect(
      refineDesktopSession(readySessionWire({ api_version: "v2", protocol_version: 1 })),
    ).toEqual({ phase: "incompatible", apiVersion: "v2", protocolVersion: 1 });

    expect(
      refineDesktopSession(readySessionWire({ api_version: "v1", protocol_version: 2 })),
    ).toEqual({ phase: "incompatible", apiVersion: "v1", protocolVersion: 2 });
  });

  it("never invents a ready session from a ready record missing a fact", () => {
    const incomplete: Array<Partial<ReturnType<typeof readySessionWire>>> = [
      { origin: null },
      { credential: null },
      { api_version: null },
      { protocol_version: null },
      { origin: "" },
      { credential: "" },
    ];

    for (const overrides of incomplete) {
      const refined = refineDesktopSession(readySessionWire(overrides));

      expect(refined.phase).not.toBe("ready");
      expect(refined).toEqual({ phase: "failed", failure: null, restartRequired: false });
    }
  });

  it("reports a response it cannot read as a failure with no claimed code", () => {
    const unreadable: unknown[] = [null, undefined, "ready", 42, [], {}, { status: "ready!" }];

    for (const value of unreadable) {
      const refined = refineDesktopSession(value);

      expect(refined).toEqual({ phase: "failed", failure: null, restartRequired: false });
    }
  });
});

describe("refineDesktopSnapshot", () => {
  it("announces the non-ready states an event can carry", () => {
    expect(refineDesktopSnapshot(snapshot({ status: "starting" }))).toEqual({ phase: "starting" });
    expect(refineDesktopSnapshot(snapshot({ status: "stopped" }))).toEqual({ phase: "stopped" });
    expect(
      refineDesktopSnapshot(
        snapshot({ status: "failed", failure: "startup_timeout", restart_required: false }),
      ),
    ).toEqual({ phase: "failed", failure: "startup_timeout", restartRequired: false });
  });

  it("refuses to promote a ready event into a session", () => {
    const ready = snapshot({
      status: "ready",
      origin: FIXTURE_ORIGIN,
      api_version: "v1",
      protocol_version: 1,
    });

    expect(refineDesktopSnapshot(ready)).toBeNull();
  });

  it("returns nothing for a payload it cannot read", () => {
    expect(refineDesktopSnapshot(undefined)).toBeNull();
    expect(refineDesktopSnapshot({})).toBeNull();
  });
});

describe("sessionsMatch", () => {
  const ready: WorkbenchSession = {
    phase: "ready",
    api: {
      origin: FIXTURE_ORIGIN,
      apiVersion: "v1",
      protocolVersion: 1,
      credential: FIXTURE_CREDENTIAL,
    },
  };

  it("treats a re-read of the same session as the same state", () => {
    expect(sessionsMatch(ready, { ...ready, api: { ...ready.api } })).toBe(true);
  });

  it("treats a new credential on the same address as a new session generation", () => {
    const replaced: WorkbenchSession = {
      phase: "ready",
      api: { ...ready.api, credential: "another-fixture-credential" },
    };

    expect(sessionsMatch(ready, replaced)).toBe(false);
  });

  it("never treats a phase change as the same state", () => {
    expect(sessionsMatch(ready, { phase: "starting" })).toBe(false);
    expect(sessionsMatch({ phase: "stopped" }, { phase: "starting" })).toBe(false);
  });
});
