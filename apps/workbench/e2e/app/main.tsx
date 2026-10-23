/**
 * The Playwright harness runtime.
 *
 * It is the production runtime with one substitution: when a page has installed the explicitly
 * named browser-test transport, the session provider receives it; otherwise it receives the
 * production default, which in a Chromium page is the browser source that reports
 * `unavailable`. The Query client, router, route tree, provider, shell and every control are
 * the production ones.
 *
 * Nothing in `src/` imports this file, `index.html` does not load it, and `vite build` is not
 * configured with this root. The harness cannot become a production session path.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { createWorkbenchQueryClient } from "../../src/query/client";
import { createAppRouter } from "../../src/router";
import { SessionProvider } from "../../src/session/provider";
import { defaultSessionSource } from "../../src/session/source";
import "../../src/styles.css";
import { hasPlaywrightBridge, playwrightSessionSource } from "./bridge";

const container = document.getElementById("root");
if (container === null) {
  throw new Error("DynamisBench Playwright harness root container is missing");
}

const bridge = window.__dynamisbenchPlaywrightBridge;
const source = bridge !== undefined && hasPlaywrightBridge()
  ? playwrightSessionSource(bridge)
  : defaultSessionSource();

document.documentElement.dataset.dynamisbenchHarness =
  bridge !== undefined && hasPlaywrightBridge()
    ? "playwright-test-bridge"
    : "production-browser-source";

// The same construction order as `src/main.tsx`: one cache and one router per runtime,
// shared with the provider so a route loader and a component read one cache.
const queryClient = createWorkbenchQueryClient();
const router = createAppRouter(queryClient);

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <SessionProvider queryClient={queryClient} source={source}>
        <RouterProvider router={router} />
      </SessionProvider>
    </QueryClientProvider>
  </StrictMode>,
);
