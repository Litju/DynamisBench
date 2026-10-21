/**
 * The workspace workbench: discovery, selection, inspection, stale identifiers, and session
 * generations, driven through the production route and the production typed client.
 *
 * Every response is the API's own read model. The gates below are about what the UI does with
 * it: group deterministically, select by button, render validated content read-only, withhold
 * content for invalid authority, keep a late answer out of a newer selection, and forget
 * selection-derived state when the session changes.
 */

import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { ArtifactInspectionResponse } from "../api/types";
import {
  APPLICATION_INFO,
  ARTIFACT,
  DISCOVERY_WITH_INVALID,
  INVALID_INSPECTION,
  INSPECTION,
  VERSIONLESS_FACTOR,
} from "../test/api-fixtures";
import { controlledSource } from "../test/controlled-source";
import { errorResponse, stubFetch, unavailableEvents } from "../test/fetch-stub";
import { jsonResponse, streamResponse } from "../test/http-fixtures";
import { renderApplication } from "../test/render-app";
import { FIXTURE_CREDENTIAL, readyApiSession } from "../test/session-fixtures";

const FACTOR_INSPECTION: ArtifactInspectionResponse = {
  ...VERSIONLESS_FACTOR,
  content: { factor_id: "load", levels: [1, 2, 3], note: null },
};

const FACTOR_ARTIFACT_PATH = `/artifacts/${VERSIONLESS_FACTOR.artifact_id}`;
const BENCHMARK_ARTIFACT_PATH = `/artifacts/${ARTIFACT.artifact_id}`;
const INVALID_ARTIFACT_PATH = `/artifacts/${INVALID_INSPECTION.artifact_id}`;

function eventLine(event: unknown): string {
  return `data: ${JSON.stringify(event)}\n\n`;
}

function readySource() {
  const controlled = controlledSource();
  return {
    ...controlled,
    async publishReady(credential = FIXTURE_CREDENTIAL) {
      await waitFor(() => expect(controlled.listening).toBe(true));
      act(() =>
        controlled.publish({ phase: "ready", api: readyApiSession({ credential }) }),
      );
    },
  };
}

async function renderWorkspace(
  handler: Parameters<typeof stubFetch>[0],
  source: ReturnType<typeof readySource>,
) {
  const recorder = stubFetch(handler);
  const view = renderApplication("/workspace/workspace-1", { source: source.source });
  await source.publishReady();
  await screen.findByRole("heading", { name: "Explorer" }, { timeout: 5_000 });
  return { ...view, calls: recorder.calls };
}

function discoveryHandler(overrides: Record<string, () => Response | Promise<Response>> = {}) {
  return ({ url }: { url: string }) => {
    for (const [suffix, respond] of Object.entries(overrides)) {
      if (url.endsWith(suffix)) {
        return respond();
      }
    }
    if (url.endsWith("/artifacts")) {
      return jsonResponse(DISCOVERY_WITH_INVALID);
    }
    if (url.endsWith("/info")) {
      return jsonResponse(APPLICATION_INFO);
    }
    if (url.endsWith(BENCHMARK_ARTIFACT_PATH)) {
      return jsonResponse(INSPECTION);
    }
    if (url.endsWith(FACTOR_ARTIFACT_PATH)) {
      return jsonResponse(FACTOR_INSPECTION);
    }
    if (url.endsWith(INVALID_ARTIFACT_PATH)) {
      return jsonResponse(INVALID_INSPECTION);
    }
    return unavailableEvents();
  };
}

describe("the workspace workbench", () => {
  it("groups discovered authority and reports category, kind and truncation", async () => {
    const source = readySource();
    await renderWorkspace(discoveryHandler(), source);

    expect(screen.getByRole("heading", { name: "benchmarks / benchmark" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "studies / factor" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "benchmarks / scenario" })).toBeInTheDocument();
    expect(screen.getByText(/structural issue.*list truncated/i)).toBeInTheDocument();
    expect(screen.getByText("3 artifacts")).toBeInTheDocument();
    expect(screen.getByText("2 valid")).toBeInTheDocument();
    expect(screen.getByText("1 invalid")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Activity" })).toBeInTheDocument();
    expect(await screen.findByText("Events: refused")).toBeInTheDocument();
    expect(
      screen.getByText(/refused the event stream for this session/i),
    ).toBeInTheDocument();
  });

  it("renders validated content as structure and the documented inspector facts", async () => {
    const user = userEvent.setup();
    const source = readySource();
    await renderWorkspace(discoveryHandler(), source);

    await user.click(screen.getByRole("option", { name: /example/ }));

    const content = await screen.findByTestId("artifact-content");
    expect(within(content).getByText("schema_version")).toBeInTheDocument();
    expect(within(content).getByText("example")).toBeInTheDocument();

    const inspector = screen.getByRole("region", { name: "Inspector" });
    expect(within(inspector).getByText("benchmarks/benchmark/example.json")).toBeInTheDocument();
    expect(within(inspector).getByText("benchmarks")).toBeInTheDocument();
    expect(within(inspector).getByText("benchmark")).toBeInTheDocument();
    expect(within(inspector).getByText("json")).toBeInTheDocument();
    expect(within(inspector).getByText("1.0.0")).toBeInTheDocument();
    expect(
      within(inspector).getByText(
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      ),
    ).toBeInTheDocument();
    // There is no provenance, timestamp, seal or source-path row to mistake for evidence.
    expect(within(inspector).queryByText(/provenance|timestamp|sealed|source path/i)).toBeNull();
  });

  it("renders diagnostics and no validated content for invalid authority", async () => {
    const user = userEvent.setup();
    const source = readySource();
    await renderWorkspace(discoveryHandler(), source);

    await user.click(screen.getByRole("option", { name: /broken/ }));

    expect(
      await screen.findByText("No validated content is published for this artifact."),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("artifact-content")).not.toBeInTheDocument();

    const inspector = screen.getByRole("region", { name: "Inspector" });
    expect(
      within(inspector).getByText("The document did not satisfy its declared model."),
    ).toBeInTheDocument();
    expect(within(inspector).getByText("schema_validation")).toBeInTheDocument();
    expect(within(inspector).getAllByText("none published")).toHaveLength(3);
  });

  it("does not let a late answer for a previous selection become the current one", async () => {
    const user = userEvent.setup();
    const source = readySource();
    let releaseBenchmark: ((response: Response) => void) | null = null;
    let releaseFactor: ((response: Response) => void) | null = null;

    const { calls } = await renderWorkspace(({ url }) => {
      if (url.endsWith(BENCHMARK_ARTIFACT_PATH)) {
        return new Promise<Response>((resolve) => {
          releaseBenchmark = resolve;
        });
      }
      if (url.endsWith(FACTOR_ARTIFACT_PATH)) {
        return new Promise<Response>((resolve) => {
          releaseFactor = resolve;
        });
      }
      if (url.endsWith("/artifacts")) {
        return jsonResponse(DISCOVERY_WITH_INVALID);
      }
      if (url.endsWith("/info")) {
        return jsonResponse(APPLICATION_INFO);
      }
      return unavailableEvents();
    }, source);

    await user.click(screen.getByRole("option", { name: /example/ }));
    await user.click(screen.getByRole("option", { name: /load/ }));

    await waitFor(() => {
      expect(calls.some((call) => call.url.endsWith(BENCHMARK_ARTIFACT_PATH))).toBe(true);
      expect(calls.some((call) => call.url.endsWith(FACTOR_ARTIFACT_PATH))).toBe(true);
    });

    await act(async () => {
      releaseFactor?.(jsonResponse(FACTOR_INSPECTION));
      await Promise.resolve();
    });
    expect(await screen.findByText("factor_id")).toBeInTheDocument();

    await act(async () => {
      releaseBenchmark?.(jsonResponse(INSPECTION));
      await Promise.resolve();
    });

    // The benchmark's answer is in the cache under its own key; the selected artifact is
    // still the factor, and that is what the Workspace pane shows.
    expect(screen.getByText("factor_id")).toBeInTheDocument();
    expect(screen.queryByText("schema_version")).not.toBeInTheDocument();
    expect(screen.getByRole("option", { name: /load/ })).toHaveAttribute("aria-selected", "true");
  });

  it("reports a stale workspace identifier and offers the explicit open flow", async () => {
    const source = readySource();
    stubFetch(({ url }) => {
      if (url.endsWith("/artifacts")) {
        return errorResponse(404, "not_found", "No workspace is registered under that identifier.");
      }
      if (url.endsWith("/info")) {
        return jsonResponse(APPLICATION_INFO);
      }
      return unavailableEvents();
    });
    renderApplication("/workspace/stale-workspace", { source: source.source });
    await source.publishReady();

    expect(
      await screen.findByText("This workspace is no longer registered"),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open a workspace again" })).toHaveAttribute(
      "href",
      "/#open-workspace",
    );
  });

  it("reports a stale artifact identifier without reopening anything", async () => {
    const user = userEvent.setup();
    const source = readySource();
    await renderWorkspace(
      discoveryHandler({
        [BENCHMARK_ARTIFACT_PATH]: () =>
          errorResponse(404, "not_found", "No artifact is registered under that identifier."),
      }),
      source,
    );

    await user.click(screen.getByRole("option", { name: /example/ }));

    expect(
      await screen.findByText("This artifact is no longer registered"),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open a workspace again" })).toBeInTheDocument();
  });

  it("forgets selection-derived state when the session generation changes", async () => {
    const user = userEvent.setup();
    const source = readySource();
    await renderWorkspace(discoveryHandler(), source);

    await user.click(screen.getByRole("option", { name: /example/ }));
    expect(await screen.findByTestId("artifact-content")).toBeInTheDocument();

    await source.publishReady("a-second-session-credential");

    await waitFor(() => expect(screen.queryByTestId("artifact-content")).not.toBeInTheDocument());
    expect(await screen.findByText(/select an artifact in the explorer/i)).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /example/ })).toHaveAttribute(
      "aria-selected",
      "false",
    );
  });

  it("keeps selection independent of the open request's roots", async () => {
    const user = userEvent.setup();
    const source = readySource();
    const { calls } = await renderWorkspace(discoveryHandler(), source);

    await user.click(screen.getByRole("option", { name: /example/ }));
    await screen.findByTestId("artifact-content");

    expect(calls.some((call) => call.url.endsWith("/workspaces/open"))).toBe(false);
    for (const call of calls) {
      expect(call.url).not.toContain("source_root");
      expect(call.url).not.toContain("evidence_root");
    }
  });

  it("re-reads an externally edited artifact on demand", async () => {
    const user = userEvent.setup();
    const source = readySource();
    let reads = 0;
    await renderWorkspace(discoveryHandler({
      [BENCHMARK_ARTIFACT_PATH]: () => {
        reads += 1;
        return jsonResponse(
          reads === 1
            ? INSPECTION
            : {
                ...INSPECTION,
                content: { schema_version: "1", id: "edited-after-first-read" },
              },
        );
      },
    }), source);

    await user.click(screen.getByRole("option", { name: /example/ }));
    const content = await screen.findByTestId("artifact-content");
    expect(within(content).getByText("example")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Re-read" }));

    await waitFor(() =>
      expect(within(screen.getByTestId("artifact-content")).getByText(
        "edited-after-first-read",
      )).toBeInTheDocument(),
    );
    expect(reads).toBe(2);
  });

  it("shows a live event stream and bounded activity lines", async () => {
    const source = readySource();
    await renderWorkspace(({ url }) => {
      if (url.endsWith("/events")) {
        return streamResponse([
          eventLine({
            schema_version: 1,
            event: "stream.ready",
            data: { heartbeat_seconds: 15, queue_capacity: 32 },
          }),
          eventLine({
            schema_version: 1,
            event: "workspace.opened",
            data: { workspace_id: "workspace-1", categories_present: 3 },
          }),
          eventLine({
            schema_version: 1,
            event: "workspace.discovered",
            data: {
              workspace_id: "workspace-1",
              artifact_count: 3,
              valid_count: 2,
              invalid_count: 1,
              issue_count: 1,
              issues_truncated: true,
            },
          }),
        ]);
      }
      if (url.endsWith("/artifacts")) {
        return jsonResponse(DISCOVERY_WITH_INVALID);
      }
      if (url.endsWith("/info")) {
        return jsonResponse(APPLICATION_INFO);
      }
      return unavailableEvents();
    }, source);

    expect(await screen.findByText("Events: live")).toBeInTheDocument();
    expect(await screen.findAllByText("Workspace opened")).not.toHaveLength(0);
    const activity = screen.getByRole("region", { name: "Activity" });
    expect(activity.textContent).toContain("Discovery completed");
  });
});
