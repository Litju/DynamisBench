import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// The suite runs without Vitest's global `afterEach`, so Testing Library cannot register its
// own automatic cleanup. Rendering two trees in one file would otherwise leave the first in
// the document, and every `getBy...` query would start reporting duplicates instead of the
// one node a test is about.
afterEach(() => {
  cleanup();
});
