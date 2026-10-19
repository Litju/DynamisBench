/**
 * The cache's lifetime is the session's lifetime.
 *
 * Data read from a sidecar session must not survive that session: a restart that mints a new
 * credential, or a session that ends, invalidates everything the cache holds. These tests
 * drive a real `QueryClient` and a controlled `SessionSource` through the provider, so what
 * is asserted is what a running workbench does.
 */

import { QueryClientProvider, useQuery, type QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { apiQueryKeys } from "../api/queries";
import { createWorkbenchQueryClient } from "../query/client";
import { SessionProvider, useApiClient } from "../session/provider";
import { controlledSource, type ControlledSource } from "../test/controlled-source";
import { FIXTURE_CREDENTIAL, FIXTURE_ORIGIN, readyApiSession } from "../test/session-fixtures";

const INFO = { application: "DynamisBench", version: "0.0.0", api_version: "v1" };

/** A component that reads `info` through whatever client the session provides. */
function InfoReader() {
  const client = useApiClient();
  const query = useQuery({
    queryKey: apiQueryKeys.info(),
    queryFn: () => {
      if (client === null) {
        throw new Error("the session provides no client");
      }
      return client.info();
    },
    enabled: client !== null,
  });

  return <span data-testid="info">{query.data?.application ?? "no-data"}</span>;
}

function mount(
  controlled: ControlledSource,
  children: React.ReactNode = null,
  queryClient: QueryClient = createWorkbenchQueryClient(),
) {
  render(
    <QueryClientProvider client={queryClient}>
      <SessionProvider queryClient={queryClient} source={controlled.source}>
        {children}
      </SessionProvider>
    </QueryClientProvider>,
  );

  return queryClient;
}

/** Answer every request with the application's own info read model. */
function stubInfoFetch() {
  const fetchMock = vi.fn(
    async () =>
      ({
        ok: true,
        status: 200,
        json: async () => INFO,
      }) as unknown as Response,
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("server state follows the session", () => {
  it("is read through the session's client and keyed without its credential", async () => {
    const fetchMock = stubInfoFetch();
    const controlled = controlledSource();

    const queryClient = mount(controlled, <InfoReader />);
    controlled.publish({ phase: "ready", api: readyApiSession() });

    await waitFor(() => expect(screen.getByTestId("info")).toHaveTextContent("DynamisBench"));

    expect(fetchMock).toHaveBeenCalledWith(
      `${FIXTURE_ORIGIN}/api/v1/info`,
      expect.objectContaining({ credentials: "omit", cache: "no-store" }),
    );

    const keys = queryClient
      .getQueryCache()
      .getAll()
      .map((query) => JSON.stringify(query.queryKey))
      .join(" ");
    expect(keys).not.toContain(FIXTURE_CREDENTIAL);
    expect(keys).not.toContain("127.0.0.1");
  });

  it("is discarded when the session is replaced by a new generation", () => {
    const controlled = controlledSource();
    const queryClient = mount(controlled);

    controlled.publish({ phase: "ready", api: readyApiSession() });
    queryClient.setQueryData(apiQueryKeys.info(), { application: "read by the first session" });

    controlled.publish({
      phase: "ready",
      api: readyApiSession({ credential: "a-different-fixture-credential" }),
    });

    expect(queryClient.getQueryData(apiQueryKeys.info())).toBeUndefined();
  });

  it("is discarded when the session becomes non-ready", () => {
    const controlled = controlledSource();
    const queryClient = mount(controlled);

    controlled.publish({ phase: "ready", api: readyApiSession() });
    queryClient.setQueryData(apiQueryKeys.info(), { application: "read by a session that ended" });

    controlled.publish({ phase: "failed", failure: "unexpected_exit", restartRequired: true });

    expect(queryClient.getQueryData(apiQueryKeys.info())).toBeUndefined();
  });

  it("is discarded when a starting session replaces a stopped one", () => {
    const controlled = controlledSource();
    const queryClient = mount(controlled);

    controlled.publish({ phase: "stopped" });
    queryClient.setQueryData(apiQueryKeys.info(), { application: "read by the previous session" });

    controlled.publish({ phase: "starting" });

    expect(queryClient.getQueryData(apiQueryKeys.info())).toBeUndefined();
  });

  it("is left alone when the source republishes the same session", () => {
    const controlled = controlledSource();
    const queryClient = mount(controlled);

    controlled.publish({ phase: "ready", api: readyApiSession() });
    queryClient.setQueryData(apiQueryKeys.info(), { application: "read by this session" });

    controlled.publish({ phase: "ready", api: readyApiSession() });

    expect(queryClient.getQueryData(apiQueryKeys.info())).toEqual({
      application: "read by this session",
    });
  });

  it("leaves nothing readable once the session that read it is gone", async () => {
    stubInfoFetch();
    const controlled = controlledSource();

    mount(controlled, <InfoReader />);
    controlled.publish({ phase: "ready", api: readyApiSession() });
    await waitFor(() => expect(screen.getByTestId("info")).toHaveTextContent("DynamisBench"));

    controlled.publish({ phase: "stopped" });

    expect(screen.getByTestId("info")).toHaveTextContent("no-data");
  });
});
