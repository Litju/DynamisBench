/**
 * The application's one QueryClient, and the policy it is built with.
 *
 * Exactly one client per mounted runtime, constructed where the runtime is: the same object
 * is handed to the router's context and to the session provider, so a route loader and a
 * component see one cache rather than two.
 *
 * The defaults are the local API's:
 *
 * * `retry: false` — this is a loopback sidecar with an explicit lifecycle. A retry loop
 *   would turn "the session is not ready" into a spinner and delay the state the user needs
 *   to see, so a failure is reported once and the session's own transitions drive recovery.
 * * no persistence — nothing serialises this cache. There is no `persistQueryClient`, no
 *   storage adapter, and no hydration: a reload starts empty, which is what keeps
 *   server-derived data out of every storage the credential is also forbidden from.
 */

import { QueryClient } from "@tanstack/react-query";

export function createWorkbenchQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
      mutations: {
        retry: false,
      },
    },
  });
}
