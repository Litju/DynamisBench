/**
 * The application runtime: one QueryClient, one session source, one router, and the shell.
 *
 * Nothing here is conditional on being inside a desktop shell. `defaultSessionSource()` asks
 * `isTauri()` once and returns the desktop adapter or the browser source, so a normal browser
 * renders this application — with the "desktop session unavailable" state — rather than
 * failing at import or at first paint.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { createWorkbenchQueryClient } from "./query/client";
import { createAppRouter } from "./router";
import { SessionProvider } from "./session/provider";
import "./styles.css";

const container = document.getElementById("root");
if (container === null) {
  throw new Error("DynamisBench workbench root container is missing");
}

// Exactly one QueryClient and one router per application runtime, constructed here and
// shared downwards: the router's context and the session provider receive the same cache.
const queryClient = createWorkbenchQueryClient();
const router = createAppRouter(queryClient);

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <SessionProvider queryClient={queryClient}>
        <RouterProvider router={router} />
      </SessionProvider>
    </QueryClientProvider>
  </StrictMode>,
);
