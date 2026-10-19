/**
 * The router context: what every route may read besides its own parameters.
 *
 * One thing, and deliberately not more. The shared `QueryClient` is here so a route loader
 * can populate the same cache the components read from — the future workspace route will
 * `ensureQueryData` its discovery read without a second client or a second cache.
 *
 * **What is not here.** No credential, no session state, no scientific content, no absolute
 * root. Router context is reachable from every route and is part of how a location is
 * described; anything session-scoped belongs in the session provider, which is above the
 * router for exactly this reason.
 */

import type { QueryClient } from "@tanstack/react-query";

export type RouterContext = {
  readonly queryClient: QueryClient;
};
