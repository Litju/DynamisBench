/**
 * The workspace route: the typed location a workspace will be inspected at, and nothing yet.
 *
 * The parameter is the opaque identifier the application minted in an
 * `OpenWorkspaceResponse` — never a path, a name, or anything a client constructed — which is
 * why it is safe to have in a URL at all. The explorer and the inspector that will use it
 * arrive with the next milestone; what this route establishes is that a workspace has an
 * address the application can navigate to and reload at.
 */

import { createRoute } from "@tanstack/react-router";

import { rootRoute } from "./root";

export const workspaceRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/workspace/$workspaceId",
  component: WorkspacePage,
});

function WorkspacePage() {
  const { workspaceId } = workspaceRoute.useParams();

  return (
    <section className="mx-auto flex w-full max-w-3xl flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h1 className="text-lg font-semibold tracking-tight">Workspace</h1>
        <p className="text-sm text-slate-600">
          Identifier:{" "}
          <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs">{workspaceId}</code>
        </p>
      </div>

      <p className="text-sm text-slate-500">
        This workspace's source authority is not displayed yet. Discovery, inspection and the
        three-pane explorer arrive with the next milestone.
      </p>
    </section>
  );
}
