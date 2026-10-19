/**
 * Wire-shape fixtures for the session tests.
 *
 * Test-only, and shaped exactly as the desktop bridge serialises: snake_case field names and
 * the credential as a plain string. The credential here is a fixture, not a secret, and the
 * tests that use it assert on it precisely so that "it never appears anywhere else" is a
 * checked property rather than an intention.
 */

import type { DesktopApiSession, DesktopSessionSnapshot, ReadyApiSession } from "../session/types";

/** A fixture credential: recognisable, and never mistaken for a real one. */
export const FIXTURE_CREDENTIAL = "fixture-credential-not-a-secret";

export const FIXTURE_ORIGIN = "http://127.0.0.1:49152";

export function snapshot(overrides: Partial<DesktopSessionSnapshot> = {}): DesktopSessionSnapshot {
  return {
    status: "starting",
    origin: null,
    api_version: null,
    protocol_version: null,
    restart_required: false,
    failure: null,
    ...overrides,
  };
}

function readySnapshot(): DesktopSessionSnapshot {
  return snapshot({
    status: "ready",
    origin: FIXTURE_ORIGIN,
    api_version: "v1",
    protocol_version: 1,
  });
}

export function readySessionWire(overrides: Partial<DesktopApiSession> = {}): DesktopApiSession {
  return {
    ...readySnapshot(),
    credential: FIXTURE_CREDENTIAL,
    ...overrides,
  };
}

export function readyApiSession(overrides: Partial<ReadyApiSession> = {}): ReadyApiSession {
  return {
    origin: FIXTURE_ORIGIN,
    apiVersion: "v1",
    protocolVersion: 1,
    credential: FIXTURE_CREDENTIAL,
    ...overrides,
  };
}
