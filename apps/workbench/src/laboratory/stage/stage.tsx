/**
 * The stage pane: the WebGL scene, its instruments and the DOM overlays that annotate it.
 *
 * The scene is driven imperatively from the laboratory store (frame, layers, selection, view)
 * so playback never re-renders React per frame; overlays (marginalia, force labels, ring
 * graduations, orientation instrument, scale bar) are positioned from the same camera after
 * each render. In a runtime without WebGL2 the pane says so and every other pane still works.
 */

import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import * as THREE from "three";

import { useUiStore } from "../../store/ui";
import { jointName, marginaliaFor } from "../anatomy";
import { intersects, stackNotes, type Rect } from "./layout";
import { useLabData } from "../data";
import { figureMismatch, type FigureAsset } from "../figure/figure";
import { laboratoryFigureOptions } from "../figure/query";
import { PALETTES, groundOf } from "../palette";
import { at, column, formatNumber, phaseAt } from "../series";
import { FIGURE_MODES, VIEW_PRESETS, useLaboratoryStore, type FigureMode, type ViewPreset } from "../store";
import { orbitDrag, orbitPan, orbitZoom, presetOrbit, type Orbit } from "./camera";
import {
  FIELD_OF_VIEW_DEG,
  FLOOR_RINGS_M,
  LaboratoryScene,
  stageFailureReason,
  webglAvailable,
} from "./scene";

/**
 * What the stage can do right now. `unavailable` is a runtime without WebGL2; `failed` is a
 * renderer that could not be built or threw while drawing; `lost` is a context the browser
 * took away (GPU reset, driver update, too many contexts) and may give back.
 */
export type StageStatus =
  | { readonly kind: "ready" }
  | { readonly kind: "unavailable" }
  | { readonly kind: "failed"; readonly reason: string }
  | { readonly kind: "lost" };

const FIGURE_LABELS: Record<FigureMode, string> = {
  anatomical: "Anatomical",
  scientific: "Scientific",
};

/**
 * The anatomical figure for the model on show, or why there is none. The figure is a pinned
 * presentation asset derived from the model; it is drawn only for the model it was derived from.
 */
export function useFigure(enabled: boolean): { figure: FigureAsset | null; reason: string | null } {
  const { client, model } = useLabData();
  // Read only where a stage can draw it: a runtime without WebGL2 never fetches the figure.
  const query = useQuery({ ...laboratoryFigureOptions(client), enabled });
  if (!enabled) {
    return { figure: null, reason: "the stage cannot draw in this runtime" };
  }
  if (query.isError) {
    return { figure: null, reason: query.error instanceof Error ? query.error.message : "the figure could not be read" };
  }
  if (query.data === undefined) {
    return { figure: null, reason: "reading the anatomical figure…" };
  }
  const mismatch = figureMismatch(query.data, model);
  return mismatch === null ? { figure: query.data, reason: null } : { figure: null, reason: mismatch };
}

const PRESET_LABELS: Record<ViewPreset, string> = {
  oblique: "Oblique",
  sagittal: "Sagittal",
  frontal: "Frontal",
  plan: "Plan",
};

/** Default joint selected when a body is picked: its primary (sagittal) hinge, if it has one. */
export function primaryJointOf(
  joints: readonly { name: string; body: string }[],
  body: string,
): string | null {
  const own = joints.filter((joint) => joint.body === body);
  return (
    own.find((joint) => /(?:^|_)(?:flexion|dorsiflexion)(?:_|$)/.test(joint.name))?.name ??
    own[0]?.name ??
    null
  );
}

export function Stage() {
  const data = useLabData();
  const theme = useUiStore((state) => state.theme);
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const leadersRef = useRef<SVGSVGElement>(null);
  const compassRef = useRef<SVGSVGElement>(null);
  const scaleRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<LaboratoryScene | null>(null);
  const orbitRef = useRef<Orbit | null>(null);
  const sizeRef = useRef({ width: 800, height: 500 });
  const drawRef = useRef<() => void>(() => {});
  const [status, setStatus] = useState<StageStatus>(() =>
    webglAvailable() ? { kind: "ready" } : { kind: "unavailable" },
  );
  const [scene, setScene] = useState<LaboratoryScene | null>(null);
  const [generation, setGeneration] = useState(0);
  const [fps, setFps] = useState<number | null>(null);
  const setRenderer = useLaboratoryStore((state) => state.setRenderer);
  const canDraw = status.kind === "ready";
  useEffect(() => {
    setRenderer({
      kind: status.kind === "ready" ? "webgl2" : status.kind,
      fps: status.kind === "ready" ? fps : null,
    });
  }, [status.kind, fps, setRenderer]);
  useEffect(() => () => setRenderer(null), [setRenderer]);
  const view = useLaboratoryStore((state) => state.view);
  const follow = useLaboratoryStore((state) => state.follow);
  const figureMode = useLaboratoryStore((state) => state.figureMode);
  const setFigureMode = useLaboratoryStore((state) => state.setFigureMode);
  const { figure, reason: figureReason } = useFigure(status.kind !== "unavailable");
  const setView = useLaboratoryStore((state) => state.setView);
  const toggleFollow = useLaboratoryStore((state) => state.toggleFollow);

  // The browser may take the context away and give it back; the stage follows it.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas === null) {
      return;
    }
    const onLost = (event: Event) => {
      // Asking for restoration is what preventDefault means here.
      event.preventDefault();
      setStatus({ kind: "lost" });
    };
    const onRestored = () => {
      setStatus({ kind: "ready" });
      setGeneration((value) => value + 1);
    };
    canvas.addEventListener("webglcontextlost", onLost);
    canvas.addEventListener("webglcontextrestored", onRestored);
    return () => {
      canvas.removeEventListener("webglcontextlost", onLost);
      canvas.removeEventListener("webglcontextrestored", onRestored);
    };
  }, [status.kind === "unavailable"]);

  // Build the scene once per model, canvas and context generation.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canDraw || canvas === null) {
      return;
    }
    let built: LaboratoryScene;
    try {
      built = new LaboratoryScene(canvas, data.model, PALETTES[groundOf(useUiStore.getState().theme)]);
    } catch (error) {
      setStatus({ kind: "failed", reason: stageFailureReason(error) });
      return;
    }
    sceneRef.current = built;
    setScene(built);
    return () => {
      built.dispose();
      sceneRef.current = null;
      setScene(null);
    };
  }, [canDraw, data.model, generation]);

  // Recording frames, store subscription, overlays and the render loop.
  useEffect(() => {
    const container = containerRef.current;
    if (scene === null || container === null) {
      return;
    }
    scene.setFrames(data.frames);
    const kinematics = data.frames.kinematics;
    const standingCom: [number, number, number] = [
      at(column(kinematics, "com.x"), 0),
      at(column(kinematics, "com.y"), 0),
      0.92,
    ];

    let frames = 0;
    let windowStart = performance.now();

    let broken = false;
    const draw = () => {
      if (broken) {
        return;
      }
      try {
        drawFrame();
      } catch (error) {
        // A renderer that throws mid-draw is not retried in a loop: the stage says so and
        // every other pane keeps working.
        broken = true;
        setStatus({ kind: "failed", reason: stageFailureReason(error) });
      }
    };
    const drawFrame = () => {
      const state = useLaboratoryStore.getState();
      let orbit = orbitRef.current ?? presetOrbit(state.view, standingCom);
      if (state.follow) {
        const com = scene.centreOfMass();
        orbit = { ...orbit, target: [com.x, com.y, Math.max(0.55, com.z)] };
      }
      orbitRef.current = orbit;
      scene.setOrbit(orbit);
      scene.render();
      placeOverlays(scene);
      // The render rate is measured while playing; at rest the stage draws on demand.
      const now = performance.now();
      if (!state.playing) {
        frames = 0;
        windowStart = now;
        setFps(null);
      } else {
        frames += 1;
        if (now - windowStart > 1000) {
          setFps(Math.round((frames * 1000) / (now - windowStart)));
          frames = 0;
          windowStart = now;
        }
      }
    };
    drawRef.current = draw;

    const placeOverlays = (current: LaboratoryScene) => {
      const { width, height } = sizeRef.current;
      const overlay = overlayRef.current;
      const leaders = leadersRef.current;
      if (overlay === null || leaders === null) {
        return;
      }
      const state = useLaboratoryStore.getState();
      const frame = state.frame;
      // The HUD is an instrument too: nothing placed on the stage may be hidden under it.
      const hudElement = container.querySelector<HTMLElement>('[data-testid="stage-hud"]');
      const containerBox = container.getBoundingClientRect();
      const hudBox = hudElement?.getBoundingClientRect();
      const hud =
        hudBox === undefined
          ? null
          : {
              left: hudBox.left - containerBox.left - 6,
              top: hudBox.top - containerBox.top - 6,
              right: hudBox.right - containerBox.left + 6,
              bottom: hudBox.bottom - containerBox.top + 6,
            };
      const underHud = (left: number, top: number, right: number, bottom: number) =>
        hud !== null && left < hud.right && right > hud.left && top < hud.bottom && bottom > hud.top;

      // Marginalia: the selected joint's sagittal chain, with angle and velocity. Each note is
      // measured where it wants to be, then the notes are stacked so that none covers another
      // or the HUD (deep flexion seen obliquely projects the hip and ankle close together).
      const names = marginaliaFor(state.selectedJoint);
      const leaderLines = leaders.querySelectorAll("line");
      const leaderDots = leaders.querySelectorAll("circle");
      const occupied: Rect[] = [];
      interface NotePlan {
        readonly element: HTMLElement;
        readonly slot: number;
        readonly name: string;
        readonly point: { x: number; y: number; visible: boolean };
        readonly left: boolean;
        readonly anchorX: number;
        readonly boxLeft: number;
        readonly boxWidth: number;
        readonly boxHeight: number;
        readonly top: number;
      }
      const plans: NotePlan[] = [];
      overlay.querySelectorAll<HTMLElement>("[data-marginalia]").forEach((element, slot) => {
        const name = names[slot];
        const joint = data.model.joints.find((entry) => entry.name === name);
        const position = joint === undefined ? null : current.jointPosition(joint);
        leaderLines[slot]?.setAttribute("visibility", "hidden");
        leaderDots[slot]?.setAttribute("visibility", "hidden");
        if (name === undefined || joint === undefined || position === null || !state.layers.athlete) {
          element.hidden = true;
          return;
        }
        const point = current.project(position, width, height);
        element.hidden = !point.visible;
        if (!point.visible) {
          return;
        }
        const left = slot !== 1;
        const anchorX = point.x + (left ? -150 : 150);
        const boxWidth = element.offsetWidth || 120;
        const boxHeight = element.offsetHeight || 48;
        // Inside the stage, whatever its width.
        const boxLeft = Math.min(Math.max(4, anchorX + (left ? -118 : 6)), Math.max(4, width - boxWidth - 4));
        const top = point.y + (slot === 0 ? -28 : slot === 1 ? 8 : 30) - 20;
        plans.push({ element, slot, name, point, left, anchorX, boxLeft, boxWidth, boxHeight, top });
      });
      const tops = stackNotes(
        plans.map((plan) => {
          const overHud = hud !== null && plan.boxLeft < hud.right && plan.boxLeft + plan.boxWidth > hud.left;
          return {
            key: plan.slot,
            side: plan.left ? ("left" as const) : ("right" as const),
            top: plan.top,
            height: plan.boxHeight,
            floor: overHud && hud !== null ? hud.top : height - 4,
          };
        }),
        4,
      );
      for (const plan of plans) {
        const { element, slot, name, point } = plan;
        const boxTop = tops.get(slot) ?? plan.top;
        const anchorY = boxTop + 20;
        occupied.push({ left: plan.boxLeft, top: boxTop, right: plan.boxLeft + plan.boxWidth, bottom: boxTop + plan.boxHeight });
        element.style.transform = `translate(${Math.round(plan.boxLeft)}px, ${Math.round(boxTop)}px)`;
        element.dataset.side = plan.left ? "left" : "right";
        element.dataset.selected = String(name === state.selectedJoint);
        const label = jointName(name);
        const angle = at(column(kinematics, `${name}.angle_deg`), frame);
        const velocity = at(column(kinematics, `${name}.velocity_deg_s`), frame);
        const reference = at(column(kinematics, `${name}.reference_deg`), frame);
        const title = element.querySelector("[data-part=title]");
        const value = element.querySelector("[data-part=value]");
        const detail = element.querySelector("[data-part=detail]");
        if (title !== null) title.textContent = `${label.latin} · ${label.region.toLowerCase()}`;
        if (value !== null) value.textContent = `${formatNumber(angle, 1)}°`;
        if (detail !== null) {
          detail.textContent = `${formatNumber(velocity, 0, true)}°/s${name === state.selectedJoint ? ` · ref ${formatNumber(reference, 1)}°` : ""}`;
        }
        const leader = leaderLines[slot];
        const dot = leaderDots[slot];
        if (leader !== undefined && dot !== undefined) {
          leader.setAttribute("x1", point.x.toFixed(1));
          leader.setAttribute("y1", point.y.toFixed(1));
          leader.setAttribute("x2", plan.anchorX.toFixed(1));
          leader.setAttribute("y2", anchorY.toFixed(1));
          dot.setAttribute("cx", point.x.toFixed(1));
          dot.setAttribute("cy", point.y.toFixed(1));
          leader.setAttribute("visibility", "visible");
          dot.setAttribute("visibility", "visible");
        }
      }

      // Force labels at the tips of the ground-reaction vectors.
      overlay.querySelectorAll<HTMLElement>("[data-force]").forEach((element) => {
        const side = element.dataset.force === "r" ? "r" : "l";
        const force = current.footForce(side);
        if (force === null || !state.layers.grf) {
          element.hidden = true;
          return;
        }
        const point = current.project(force.tip, width, height);
        const labelLeft = point.x + (side === "l" ? 8 : -52);
        const box = { left: labelLeft, top: point.y - 6, right: labelLeft + 48, bottom: point.y + 8 };
        element.hidden =
          !point.visible || underHud(box.left, box.top, box.right, box.bottom) || occupied.some((taken) => intersects(taken, box));
        if (!element.hidden) {
          occupied.push(box);
        }
        element.style.transform = `translate(${Math.round(labelLeft)}px, ${Math.round(point.y - 6)}px)`;
        element.textContent = `${formatNumber(force.newtons, 0)} N`;
      });

      // Graduation labels around the outer floor ring.
      const [cx, cy] = current.balancePoint();
      const outer = FLOOR_RINGS_M[FLOOR_RINGS_M.length - 1] ?? 1;
      overlay.querySelectorAll<HTMLElement>("[data-degree]").forEach((element) => {
        const degree = Number(element.dataset.degree);
        const angle = (degree * Math.PI) / 180;
        const point = current.project(
          new THREE.Vector3(cx + outer * 1.09 * Math.cos(angle), cy + outer * 1.09 * Math.sin(angle), 0),
          width,
          height,
        );
        const box = { left: point.x - 12, top: point.y - 7, right: point.x + 16, bottom: point.y + 7 };
        // The graduations are the least important text on the stage: they give way to the HUD,
        // the notes and the force labels rather than being drawn under or over them.
        element.hidden =
          !point.visible ||
          !state.layers.floor ||
          underHud(box.left, box.top, box.right, box.bottom) ||
          occupied.some((taken) => intersects(taken, box));
        element.style.transform = `translate(${Math.round(point.x - 12)}px, ${Math.round(point.y - 7)}px)`;
      });

      // Orientation instrument and scale bar.
      const compass = compassRef.current;
      if (compass !== null) {
        const axes = current.worldAxes();
        for (const name of ["x", "y", "z"] as const) {
          const [dx, dy] = axes[name];
          const line = compass.querySelector(`[data-axis=${name}]`);
          const text = compass.querySelector(`[data-axis-label=${name}]`);
          line?.setAttribute("x2", String(40 + dx * 28));
          line?.setAttribute("y2", String(40 + dy * 28));
          text?.setAttribute("x", String(40 + dx * 35));
          text?.setAttribute("y", String(43 + dy * 35));
        }
        const orbit = orbitRef.current;
        const caption = compass.querySelector("[data-part=caption]");
        if (caption !== null && orbit !== null) {
          caption.textContent = `az ${formatNumber(orbit.azimuth, 0)}° · el ${formatNumber(orbit.elevation, 0)}°`;
        }
      }
      const scale = scaleRef.current;
      if (scale !== null) {
        scale.style.width = `${Math.round(current.pixelsPerMetre(height) * 0.5)}px`;
      }
    };

    const resize = () => {
      const rect = container.getBoundingClientRect();
      const width = Math.max(1, Math.round(rect.width));
      const height = Math.max(1, Math.round(rect.height));
      sizeRef.current = { width, height };
      scene.resize(width, height);
      draw();
    };
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(resize);
    observer?.observe(container);
    resize();

    const unsubscribe = useLaboratoryStore.subscribe((state, previous) => {
      if (state.view !== previous.view || state.viewRevision !== previous.viewRevision) {
        orbitRef.current = presetOrbit(state.view, standingCom);
      }
      if (state.layers !== previous.layers) {
        scene.setLayers(state.layers);
      }
      if (state.selectedBody !== previous.selectedBody || state.selectedJoint !== previous.selectedJoint) {
        scene.setSelection(state.selectedBody, state.selectedJoint);
      }
      if (state.frame !== previous.frame) {
        scene.setFrame(state.frame);
      }
      draw();
    });
    const state = useLaboratoryStore.getState();
    scene.setLayers(state.layers);
    scene.setSelection(state.selectedBody, state.selectedJoint);
    scene.setFrame(state.frame);
    draw();

    return () => {
      unsubscribe();
      observer?.disconnect();
      drawRef.current = () => {};
    };
  }, [scene, data.frames, data.model]);

  // The anatomical figure, and which figure is drawn.
  useEffect(() => {
    if (scene === null) {
      return;
    }
    scene.setFigure(figure);
    drawRef.current();
  }, [scene, figure]);
  useEffect(() => {
    if (scene === null) {
      return;
    }
    scene.setFigureMode(figureMode);
    drawRef.current();
  }, [scene, figureMode]);

  // Re-colour on a change of ground.
  useEffect(() => {
    if (scene !== null) {
      scene.setPalette(PALETTES[groundOf(theme)]);
      drawRef.current();
    }
  }, [theme, scene]);

  // Pointer: drag orbits, shift-drag pans, wheel zooms, a click without a drag selects.
  const drag = useRef<{ x: number; y: number; moved: boolean; pan: boolean } | null>(null);
  const onPointerDown = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    drag.current = { x: event.clientX, y: event.clientY, moved: false, pan: event.shiftKey || event.button === 2 };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const onPointerMove = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    const current = drag.current;
    const orbit = orbitRef.current;
    if (current === null || orbit === null) {
      return;
    }
    const dx = event.clientX - current.x;
    const dy = event.clientY - current.y;
    if (!current.moved && Math.hypot(dx, dy) < 3) {
      return;
    }
    current.moved = true;
    current.x = event.clientX;
    current.y = event.clientY;
    orbitRef.current = current.pan
      ? orbitPan(orbit, dx, dy, sizeRef.current.height, FIELD_OF_VIEW_DEG)
      : orbitDrag(orbit, dx, dy);
    drawRef.current();
  };
  const onPointerUp = (event: ReactPointerEvent<HTMLCanvasElement>) => {
    const current = drag.current;
    drag.current = null;
    if (current === null || current.moved) {
      return;
    }
    const scene = sceneRef.current;
    const rect = event.currentTarget.getBoundingClientRect();
    const body = scene?.pick(event.clientX - rect.left, event.clientY - rect.top, rect.width, rect.height) ?? null;
    if (body !== null) {
      useLaboratoryStore.getState().select(body, primaryJointOf(data.model.joints, body));
    }
  };
  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas === null) {
      return;
    }
    const onWheel = (event: WheelEvent) => {
      const orbit = orbitRef.current;
      if (orbit === null) {
        return;
      }
      event.preventDefault();
      orbitRef.current = orbitZoom(orbit, event.deltaY);
      drawRef.current();
    };
    canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", onWheel);
  }, [status.kind === "unavailable"]);

  const hasCanvas = status.kind !== "unavailable";

  return (
    <section
      className="lab-stage"
      aria-label="Stage"
      data-webgl={status.kind === "ready" ? "webgl2" : status.kind}
      data-figure={figureMode === "anatomical" && figure !== null ? "anatomical" : "scientific"}
    >
      <div className="lab-stage-tools" role="toolbar" aria-label="View">
        {VIEW_PRESETS.map((preset, i) => (
          <button
            key={preset}
            type="button"
            aria-pressed={view === preset}
            onClick={() => setView(preset)}
            title={`${PRESET_LABELS[preset]} view (${i + 1})`}
          >
            {PRESET_LABELS[preset]}
          </button>
        ))}
        <button type="button" aria-pressed={follow} onClick={toggleFollow} title="Keep the centre of mass in view">
          Follow · {follow ? "on" : "off"}
        </button>
        <div className="lab-figure-mode" role="group" aria-label="Figure">
          {FIGURE_MODES.map((mode) => (
            <button
              key={mode}
              type="button"
              aria-pressed={figureMode === mode}
              disabled={mode === "anatomical" && figure === null}
              title={
                mode === "anatomical"
                  ? figure === null
                    ? (figureReason ?? "the anatomical figure is unavailable")
                    : "A skinned surface derived from the model, deformed by the recorded body poses (presentation only)"
                  : "The model's own segment geometry, exactly as it is simulated"
              }
              onClick={() => setFigureMode(mode)}
            >
              {FIGURE_LABELS[mode]}
            </button>
          ))}
        </div>
      </div>

      <div ref={containerRef} className="lab-stage-canvas">
        {hasCanvas && (
          // The canvas stays mounted while a context is lost, so the browser can restore it.
          <canvas
            ref={canvasRef}
            hidden={status.kind === "failed"}
            aria-label="Three-dimensional view of the athlete and barbell at the current frame"
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onContextMenu={(event) => event.preventDefault()}
          />
        )}
        {status.kind !== "ready" && <StageFallback status={status} />}
        <svg ref={leadersRef} className="lab-leaders" aria-hidden="true">
          {[0, 1, 2].map((slot) => (
            <line key={`line-${slot}`} visibility="hidden" />
          ))}
          {[0, 1, 2].map((slot) => (
            <circle key={`dot-${slot}`} r={3} visibility="hidden" />
          ))}
        </svg>
        <div ref={overlayRef} className="lab-overlay" aria-hidden="true">
          {[0, 1, 2].map((slot) => (
            <div key={slot} className="lab-marginalia" data-marginalia={slot} hidden>
              <span data-part="title" />
              <strong data-part="value" />
              <small data-part="detail" />
            </div>
          ))}
          <span className="lab-force" data-force="l" hidden />
          <span className="lab-force" data-force="r" hidden />
          {Array.from({ length: 12 }, (_, k) => k * 30).map((degree) => (
            <span key={degree} className="lab-degree" data-degree={degree} hidden>
              {degree}°
            </span>
          ))}
        </div>
        {status.kind === "ready" && (
          <>
            <svg ref={compassRef} className="lab-compass" viewBox="0 0 80 96" aria-hidden="true">
              <circle cx="40" cy="40" r="34" className="lab-compass-ring" />
              <line data-axis="x" x1="40" y1="40" x2="40" y2="40" className="axis-x" />
              <line data-axis="y" x1="40" y1="40" x2="40" y2="40" className="axis-y" />
              <line data-axis="z" x1="40" y1="40" x2="40" y2="40" className="axis-z" />
              <text data-axis-label="x" className="axis-x">X</text>
              <text data-axis-label="y" className="axis-y">Y</text>
              <text data-axis-label="z" className="axis-z">Z</text>
              <text data-part="caption" x="40" y="92" textAnchor="middle" className="lab-compass-caption" />
            </svg>
            <div className="lab-scale" aria-hidden="true">
              <span>0.5 m</span>
              <div ref={scaleRef} />
            </div>
          </>
        )}
        <Hud fps={fps} />
      </div>
    </section>
  );
}

/** What the stage says when it cannot draw; every other pane keeps working. */
function StageFallback({ status }: { status: Exclude<StageStatus, { kind: "ready" }> }) {
  const role = status.kind === "failed" ? "alert" : "status";
  return (
    <div className="lab-stage-fallback" role={role} data-stage-status={status.kind}>
      {status.kind === "unavailable" && (
        <>
          <strong>Stage unavailable</strong>
          <span>
            This runtime provides no WebGL2 context, so the three-dimensional stage is not drawn. Every recorded value
            remains available in the plots, inspector and folios.
          </span>
        </>
      )}
      {status.kind === "lost" && (
        <>
          <strong>Graphics context lost</strong>
          <span>
            The browser took the stage's WebGL context away (a GPU reset or too many contexts). The stage is redrawn if
            the browser restores it; plots, inspector and folios are unaffected.
          </span>
        </>
      )}
      {status.kind === "failed" && (
        <>
          <strong>The stage could not draw</strong>
          <span>
            The WebGL renderer failed ({status.reason}). The stage is not drawn; every recorded value remains available
            in the plots, inspector and folios.
          </span>
        </>
      )}
    </div>
  );
}

/** The stage's heads-up readout: time, phase and the balance facts of this frame. */
function Hud({ fps }: { fps: number | null }) {
  const { recording, frames, weightN, model } = useLabData();
  const frame = useLaboratoryStore((state) => state.frame);
  const time = at(frames.kinematics.t, frame);
  const kinetics = frames.kinetics;
  const phase = phaseAt(recording.phase_spans, time);
  const vertical = at(column(kinetics, "grf_left.z"), frame) + at(column(kinetics, "grf_right.z"), frame);
  const loaded = at(column(kinetics, "loaded_contacts"), frame);
  const total = 2 * model.sole_points.length;
  return (
    <div className="lab-hud" data-testid="stage-hud" data-fps={fps ?? ""}>
      <div className="lab-hud-head">
        <strong>t {formatNumber(time, 3)} s</strong>
        <span data-phase={phase?.phase ?? "none"}>{phase?.phase ?? "—"}</span>
      </div>
      <dl>
        <div className="sanguine">
          <dt>GRF</dt>
          <dd>{formatNumber(vertical / weightN, 3)} × weight</dd>
        </div>
        <div className="gold">
          <dt>CoM z</dt>
          <dd>{formatNumber(at(column(frames.kinematics, "com.z"), frame), 3)} m</dd>
        </div>
        <div className="verdigris">
          <dt>CoP margin</dt>
          <dd>{formatNumber(at(column(kinetics, "cop_margin_m"), frame) * 1000, 0)} mm</dd>
        </div>
        <div className="verdigris">
          <dt>loaded</dt>
          <dd>
            {formatNumber(loaded, 0)}/{total}
          </dd>
        </div>
      </dl>
    </div>
  );
}
