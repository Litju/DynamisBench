/**
 * The laboratory route, rendered the way the application renders it: the production route
 * tree, session provider, typed client and Query cache, over a stubbed network that answers
 * with the real published read models and catalogued Arrow frames.
 *
 * jsdom has no WebGL, so the stage reports itself unavailable and every other pane must still
 * work — which is the degraded state a host without WebGL2 would see.
 */

import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { APPLICATION_INFO } from "../test/api-fixtures";
import { controlledSource } from "../test/controlled-source";
import { stubFetch, unavailableEvents } from "../test/fetch-stub";
import { jsonResponse } from "../test/http-fixtures";
import { laboratoryAnswer } from "../test/laboratory-fixtures";
import { renderApplication } from "../test/render-app";
import { FIXTURE_CREDENTIAL, readyApiSession } from "../test/session-fixtures";
import { useUiStore } from "../store/ui";
import { resetLaboratoryStore, useLaboratoryStore } from "./store";

afterEach(() => {
  resetLaboratoryStore();
  useUiStore.setState({ theme: "dark" });
});

async function renderLaboratory(workspaceId?: string) {
  const recorder = stubFetch(({ url }) => {
    const answer = laboratoryAnswer(url);
    if (answer !== null) return answer;
    if (url.endsWith("/info")) return jsonResponse(APPLICATION_INFO);
    return unavailableEvents();
  });
  const controlled = controlledSource();
  const location = workspaceId === undefined ? "/laboratory" : `/laboratory?workspace=${workspaceId}`;
  const view = renderApplication(location, { source: controlled.source });
  await waitFor(() => expect(controlled.listening).toBe(true));
  act(() => controlled.publish({ phase: "ready", api: readyApiSession() }));
  await screen.findByRole("heading", { name: "Biomechanics Laboratory" }, { timeout: 10_000 });
  await screen.findByTestId("stage-hud", {}, { timeout: 10_000 });
  return { ...view, calls: recorder.calls };
}

describe("the laboratory route", () => {
  it("says what it needs in a runtime with no ready session", async () => {
    renderApplication("/laboratory");

    expect(
      await screen.findByText(
        /A ready local API session is required to read the laboratory dataset/,
        {},
        // The first render loads the route's lazy chunk.
        { timeout: 10_000 },
      ),
    ).toBeInTheDocument();
  });

  it("waits for a desktop session that is still starting, and reports one that failed or stopped", async () => {
    const recorder = stubFetch(() => unavailableEvents());
    const controlled = controlledSource();
    renderApplication("/laboratory", { source: controlled.source });
    await waitFor(() => expect(controlled.listening).toBe(true));

    act(() => controlled.publish({ phase: "starting" }));
    const waiting = await screen.findByText(/Waiting for the local API session/, {}, { timeout: 10_000 });
    expect(waiting.closest("section")).toHaveAttribute("data-session-phase", "starting");
    expect(waiting.closest("section")).toHaveAttribute("aria-busy", "true");
    expect(screen.queryByText(/ordinary browser/)).toBeNull();

    act(() => controlled.publish({ phase: "failed", failure: "unexpected_exit", restartRequired: true }));
    const failed = await screen.findByRole("alert");
    expect(failed.closest("section")).toHaveAttribute("data-session-phase", "failed");
    expect(failed).toHaveTextContent(/read once the session is ready again/);

    act(() => controlled.publish({ phase: "stopped" }));
    await waitFor(() => expect(document.querySelector("[data-session-phase]")).toHaveAttribute("data-session-phase", "stopped"));
    expect(screen.getByRole("alert")).toBeInTheDocument();

    act(() => controlled.publish({ phase: "incompatible", apiVersion: "v2", protocolVersion: 3 }));
    await waitFor(() => expect(document.querySelector("[data-session-phase]")).toHaveAttribute("data-session-phase", "incompatible"));
    // No laboratory read was attempted without a ready session.
    expect(recorder.calls.some((call) => call.url.includes("/laboratory"))).toBe(false);
  });

  it("reads the dataset over the typed client and states its provenance", async () => {
    const { calls } = await renderLaboratory();
    const laboratory = calls.filter((call) => call.url.includes("/laboratory"));

    expect(laboratory.map((call) => new URL(call.url).pathname).sort()).toEqual([
      "/api/v1/laboratory",
      "/api/v1/laboratory/model",
      "/api/v1/laboratory/recordings/repetition",
      "/api/v1/laboratory/recordings/repetition/frames/kinematics",
      "/api/v1/laboratory/recordings/repetition/frames/kinetics",
      "/api/v1/laboratory/recordings/repetition/frames/pose",
    ]);
    for (const call of laboratory) {
      expect(call.init.method).toBe("GET");
      expect((call.init.headers as Record<string, string>).Authorization).toBe(`Bearer ${FIXTURE_CREDENTIAL}`);
    }
    const provenance = screen.getByLabelText("Provenance");
    expect(provenance).toHaveTextContent("d3b4edafc090");
    expect(provenance).toHaveTextContent("c91b2fa2ca1e");
    expect(provenance).toHaveTextContent(/not sealed DynamisBench evidence/i);
    expect(document.body).not.toHaveTextContent(FIXTURE_CREDENTIAL);
  });

  it("keeps workspace live-run actions unavailable while the M1 read-only laboratory remains usable", async () => {
    const { calls } = await renderLaboratory("opaque-workspace-id");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /Study & Runs/ }));

    expect(
      await screen.findByRole("heading", {
        name: "Workspace execution is not enabled in this integration phase",
      }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /preflight|execute run|cancel/i })).toBeNull();
    expect(calls.some((call) => /\/studies(?:\?|$)|\/runs(?:\/|\?|$)/.test(call.url))).toBe(false);
    expect(screen.getByRole("button", { name: /Open the packaged Laboratory recordings/ })).toBeInTheDocument();
  });

  it("keeps every pane working when the runtime has no WebGL", async () => {
    await renderLaboratory();

    expect(screen.getByText("Stage unavailable")).toBeInTheDocument();
    expect(screen.getByTestId("stage-hud")).toHaveTextContent("t 0.000 s");
    expect(screen.getByRole("slider", { name: "Playback position" })).toHaveAttribute("aria-valuemax", "5.5");
    expect(screen.getAllByRole("img", { name: /Click to seek/ })).toHaveLength(3);
    expect(within(screen.getByLabelText("Inspector")).getByText("Knee · left")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Back squat — nominal/ })).toHaveAttribute("aria-pressed", "true");
  });

  it("moves one clock from the keyboard and the track", async () => {
    const user = userEvent.setup();
    await renderLaboratory();

    await user.keyboard("{ArrowRight}{ArrowRight}");
    expect(screen.getByTestId("playback-frame")).toHaveTextContent("3");
    expect(screen.getByTestId("stage-hud")).toHaveTextContent("t 0.020 s");

    await user.keyboard("{Shift>}{ArrowRight}{/Shift}");
    expect(screen.getByTestId("playback-frame")).toHaveTextContent("13");

    const track = screen.getByRole("slider", { name: "Playback position" });
    track.focus();
    await user.keyboard("{End}");
    expect(screen.getByTestId("playback-frame")).toHaveTextContent("551");
    await user.keyboard("{Home}");
    expect(screen.getByTestId("playback-time")).toHaveTextContent("0.000");

    await user.click(document.body);
    await user.keyboard("]");
    expect(useLaboratoryStore.getState().time).toBeCloseTo(1.0, 6);
    expect(screen.getByTestId("stage-hud")).toHaveTextContent(/descent/i);
  });

  it("plays and pauses", async () => {
    const user = userEvent.setup();
    await renderLaboratory();

    await user.click(screen.getByRole("button", { name: "Play" }));
    expect(screen.getByRole("button", { name: "Pause" })).toHaveAttribute("aria-pressed", "true");
    await waitFor(() => expect(useLaboratoryStore.getState().frame).toBeGreaterThan(0), { timeout: 5_000 });
    await user.click(screen.getByRole("button", { name: "Pause" }));
    expect(useLaboratoryStore.getState().playing).toBe(false);
  });

  it("selects one joint everywhere from the model tree", async () => {
    const user = userEvent.setup();
    await renderLaboratory();

    await user.click(screen.getByRole("button", { name: /Thigh L/ }));

    const inspector = screen.getByLabelText("Inspector");
    expect(within(inspector).getByText("Hip · left")).toBeInTheDocument();
    expect(within(inspector).getByText(/hip_flexion_l · hinge about −y · thigh_l/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "hip_adduction_l" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "hip_adduction_l" }));
    expect(within(inspector).getByText("Hip adduction · left")).toBeInTheDocument();
    expect(useLaboratoryStore.getState().selectedJoint).toBe("hip_adduction_l");
  });

  it("turns the folios: Model Atlas, Analysis and Evidence", async () => {
    const user = userEvent.setup();
    await renderLaboratory();
    const folios = screen.getByRole("navigation", { name: "Folios" });

    await user.click(within(folios).getByRole("button", { name: /Model Atlas/ }));
    expect(screen.getByRole("heading", { name: "The athlete and the bar, in the standing keyframe" })).toBeInTheDocument();
    expect(screen.getByText(/Total 95.0000 kg/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Select Thigh" }));
    expect(useLaboratoryStore.getState().selectedBody).toBe("thigh_l");

    await user.click(within(folios).getByRole("button", { name: /Analysis/ }));
    expect(screen.getByRole("heading", { name: "Ledger of work and energy" })).toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: "Summa" })).toBeInTheDocument();
    expect(screen.getByText(/Work–energy ledger residual: .* — balances/)).toBeInTheDocument();

    await user.click(within(folios).getByRole("button", { name: /Evidence/ }));
    expect(screen.getByTestId("check-tally")).toHaveTextContent("22 pass · 0 fail");
    expect(screen.getByRole("table", { name: "Contact checks" })).toBeInTheDocument();
    expect(
      screen.getByText(/The MuJoCo worker that generated them is not run by this read-only integration\./),
    ).toBeInTheDocument();
  });

  it("shows what the checks reject in an ablation", async () => {
    const user = userEvent.setup();
    await renderLaboratory();

    await user.selectOptions(screen.getByRole("combobox", { name: "Recording" }), "dataset:ablation-no-internal-model");
    await waitFor(() => expect(screen.getByLabelText("Provenance")).toHaveTextContent("6d34a139189a"), { timeout: 10_000 });
    await user.click(within(screen.getByRole("navigation", { name: "Folios" })).getByRole("button", { name: /Evidence/ }));

    expect(screen.getByTestId("check-tally")).toHaveTextContent("13 pass · 6 fail · 3 not evaluated");
    const heel = document.querySelector('tr[data-criterion="heel"]');
    expect(heel).toHaveAttribute("data-status", "fail");
    expect(within(heel as HTMLElement).getByText("FAIL")).toBeInTheDocument();
  });

  it("switches the ground between Studiolo and Vellum", async () => {
    const user = userEvent.setup();
    const { container } = await renderLaboratory();
    const shell = container.querySelector(".wb-shell");

    expect(shell).toHaveAttribute("data-theme", "dark");
    await user.click(screen.getByRole("button", { name: "Toggle color theme" }));
    expect(shell).toHaveAttribute("data-theme", "light");
  });

  it("uses the packaged dataset for a workspace route without calling live run APIs in M1", async () => {
    const { calls } = await renderLaboratory("opaque-workspace-id");
    const user = userEvent.setup();
    const folios = screen.getByRole("navigation", { name: "Folios" });

    await user.click(within(folios).getByRole("button", { name: /Study & Runs/ }));
    expect(
      await screen.findByRole("heading", {
        name: "Workspace execution is not enabled in this integration phase",
      }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Preflight|Execute run|Cancel/i })).toBeNull();
    expect(calls.some((call) => /\/studies(?:\?|$)|\/runs(?:\/|\?|$)/.test(call.url))).toBe(false);
    expect(screen.getByRole("button", { name: /Open the packaged Laboratory recordings/ })).toBeInTheDocument();
  });
});
