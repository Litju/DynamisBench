/**
 * The laboratory route: the biomechanics laboratory over the packaged squat recordings and,
 * when bound to an open workspace, that workspace's studies and runs.
 *
 * Lazily loaded: the stage's WebGL renderer and the laboratory's panes are a separate chunk,
 * so the overview and the workspace routes never pay for them. The one search parameter is the
 * opaque workspace identifier the API minted when the workspace was opened — never a path —
 * so `/laboratory?workspace=<id>` is the laboratory of that workspace in this session. Which
 * recording is on show is presentation state, not an address.
 */

import { createRoute, lazyRouteComponent } from "@tanstack/react-router";

import { rootRoute } from "./root";

/** The opaque identifiers the API mints are URL-safe tokens; anything else is dropped. */
const WORKSPACE_TOKEN = /^[A-Za-z0-9_-]{1,128}$/;

export interface LaboratorySearch {
  readonly workspace?: string;
}

export function validateLaboratorySearch(search: Record<string, unknown>): LaboratorySearch {
  const workspace = search.workspace;
  return typeof workspace === "string" && WORKSPACE_TOKEN.test(workspace) ? { workspace } : {};
}

export const laboratoryRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/laboratory",
  validateSearch: validateLaboratorySearch,
  component: lazyRouteComponent(() => import("../laboratory/laboratory-page"), "LaboratoryPage"),
});
