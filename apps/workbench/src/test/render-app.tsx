/**
 * Render the application the way its runtime does.
 *
 * Test-only, and complete on purpose: one QueryClient, the session provider, and the
 * production route tree at an injected location. Browser-only — no Tauri runtime exists in
 * this environment, which is exactly the condition the shell has to survive.
 */

import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory } from "@tanstack/react-router";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";

import { createWorkbenchQueryClient } from "../query/client";
import { createAppRouter } from "../router";
import { SessionProvider } from "../session/provider";
import type { SessionSource } from "../session/source";

export function renderApplication(
  path: string,
  options: { queryClient?: QueryClient; source?: SessionSource } = {},
) {
  const queryClient = options.queryClient ?? createWorkbenchQueryClient();
  const router = createAppRouter(queryClient, createMemoryHistory({ initialEntries: [path] }));

  const view = render(
    <Application queryClient={queryClient} source={options.source}>
      <RouterProvider router={router} />
    </Application>,
  );

  return { ...view, router, queryClient };
}

/** The provider stack every rendering of the application shares. */
function Application({
  queryClient,
  source,
  children,
}: {
  queryClient: QueryClient;
  source?: SessionSource;
  children: ReactNode;
}) {
  return (
    <QueryClientProvider client={queryClient}>
      <SessionProvider queryClient={queryClient} source={source}>
        {children}
      </SessionProvider>
    </QueryClientProvider>
  );
}
