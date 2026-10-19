/**
 * The landing route: where the workbench says whether it has a running local API.
 *
 * The runtime status is the substance of this route in this milestone, and it is the *same*
 * surface the header carries — the header is the glance, this is the explanation.
 */

import { createRoute } from "@tanstack/react-router";

import { RuntimeStatus } from "../shell/runtime-status";
import { rootRoute } from "./root";

export const landingRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: LandingPage,
});

function LandingPage() {
  return (
    <section className="mx-auto flex w-full max-w-3xl flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h1 className="text-lg font-semibold tracking-tight">Workbench overview</h1>
        <p className="text-sm text-slate-600">
          Local-first verification, validation, uncertainty quantification and benchmarking of
          computational human-movement models.
        </p>
      </div>

      <section
        aria-label="Runtime status"
        className="flex flex-col gap-2 rounded-lg border border-slate-200 bg-white p-4"
      >
        <h2 className="text-sm font-medium text-slate-700">Local API session</h2>
        <RuntimeStatus />
      </section>

      <p className="text-sm text-slate-500">
        Workspace exploration and artifact inspection are not part of this milestone.
      </p>
    </section>
  );
}
