/**
 * The root route: the workbench shell, and the region every other route renders into.
 *
 * The shell is here rather than in each route so a route cannot accidentally render without
 * the application's chrome, and so the runtime status stays mounted while routes change —
 * which is the behaviour a status surface has to have to be useful.
 */

import { createRootRouteWithContext, Outlet } from "@tanstack/react-router";

import { AppShell } from "../shell/app-shell";
import type { RouterContext } from "./context";

export const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: RootLayout,
});

function RootLayout() {
  return (
    <AppShell>
      <Outlet />
    </AppShell>
  );
}
