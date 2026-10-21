import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// The suite runs without Vitest's global `afterEach`, so Testing Library cannot register its
// own automatic cleanup. Rendering two trees in one file would otherwise leave the first in
// the document, and every `getBy...` query would start reporting duplicates instead of the
// one node a test is about.
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

// jsdom implements no layout, so the router's scroll-on-navigation has nowhere to go and
// reports "Not implemented" for every test that renders a route. The shell has no opinion
// about scrolling, so the missing implementation is stated here instead of being logged.
Object.defineProperty(window, "scrollTo", {
  value: () => {},
  writable: true,
});
