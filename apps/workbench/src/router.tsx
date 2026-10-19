/**
 * The application's router: a code-based route tree over two locations.
 *
 * ```text
 * /                        the workbench overview and its runtime status
 * /workspace/$workspaceId  a workspace identified by the opaque handle the API minted
 * ```
 *
 * No file-route generator and no plugin: this foundation's route tree is small enough to
 * read, and a generator would add a build step and a convention before there is anything to
 * generate. The context carries the runtime's one `QueryClient`, so a loader and a component
 * read one cache rather than two.
 *
 * **What never enters a URL, a search parameter or this context**: the session credential,
 * scientific content, and absolute filesystem roots. A workspace is addressed by the opaque
 * identifier the application returned for it; the two declared roots appear once, in the
 * `open` request, and never again.
 */

import type { QueryClient } from "@tanstack/react-query";
import {
  createRouter,
  type RouterHistory,
} from "@tanstack/react-router";

import { landingRoute } from "./routes/landing";
import { rootRoute } from "./routes/root";
import { workspaceRoute } from "./routes/workspace";
import type { RouterContext } from "./routes/context";

export const routeTree = rootRoute.addChildren([landingRoute, workspaceRoute]);

/**
 * Build the application's router from the runtime's own `QueryClient`.
 *
 * Exactly one router per runtime, created where the runtime is. `history` is injectable so a
 * test can render the same tree at a chosen location without a browser's location — the
 * routes are the production ones either way.
 */
export function createAppRouter(queryClient: QueryClient, history?: RouterHistory) {
  return createRouter({
    routeTree,
    context: { queryClient } satisfies RouterContext,
    ...(history === undefined ? {} : { history }),
  });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}
