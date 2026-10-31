/**
 * The landing route: runtime status, and the explicit open-workspace flow.
 *
 * Opening is the first operation a person performs, so it lives here rather than behind a
 * menu. The form is the only place roots are entered; once the application answers, the
 * workspace is addressed by the opaque identifier it minted and this route is no longer part
 * of the address.
 */

import { createRoute } from "@tanstack/react-router";

import { useApiClient } from "../session/provider";
import { RuntimeStatus } from "../shell/runtime-status";
import { OpenWorkspaceForm } from "../workbench/open-workspace";
import { rootRoute } from "./root";

export const landingRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: LandingPage,
});

function LandingPage() {
  const client = useApiClient();

  return (
    <section className="wb-landing mx-auto flex w-full max-w-3xl flex-col gap-6">
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

      <section
        id="open-workspace"
        aria-labelledby="open-workspace-heading"
        className="flex scroll-mt-4 flex-col gap-3 rounded-lg border border-slate-200 bg-white p-4"
      >
        <div className="flex flex-col gap-0.5">
          <h2 id="open-workspace-heading" className="text-sm font-medium text-slate-700">
            Open workspace
          </h2>
          <p className="text-xs text-slate-500">
            Reading a workspace is an explicit operation over two existing directories.
          </p>
        </div>
        {client === null ? (
          <p className="text-sm text-slate-500">
            A ready local API session is required to open a workspace. This is unavailable in an
            ordinary browser.
          </p>
        ) : (
          <OpenWorkspaceForm client={client} />
        )}
      </section>
    </section>
  );
}
