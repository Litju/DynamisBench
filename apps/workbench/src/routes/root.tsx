/**
 * The root route: the workbench shell, and the region every other route renders into.
 *
 * The shell is here rather than in each route so a route cannot accidentally render without
 * the application's chrome, and so the runtime status stays mounted while routes change —
 * which is the behaviour a status surface has to have to be useful.
 *
 * **The Activity panel is here for the same reason, and one more.** It subscribes to the
 * session's event stream, and the first operation a person performs — opening a workspace —
 * publishes its `workspace.opened` event during the POST made from the landing route. A
 * panel mounted only on the workspace route would therefore start listening after the event
 * it exists to show. At the root it is mounted while the landing form is usable, survives
 * navigation unchanged, and owns the session's one subscription. On the laboratory route it
 * stays mounted (and subscribed) but is not drawn: the laboratory uses the whole window and
 * has its own status bar.
 */

import { createRootRouteWithContext, Outlet, useRouterState } from "@tanstack/react-router";

import { AppShell } from "../shell/app-shell";
import { ActivityPanel } from "../workbench/activity";
import type { RouterContext } from "./context";

export const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: RootLayout,
});

function RootLayout() {
  const onLaboratory = useRouterState({
    select: (state) => state.location.pathname === "/laboratory",
  });
  return (
    <AppShell>
      <div className="flex min-h-0 flex-1 flex-col">
        <Outlet />
        <div className="wb-activity-slot" hidden={onLaboratory}>
          <ActivityPanel />
        </div>
      </div>
    </AppShell>
  );
}
