/**
 * Plot layout: the legend is part of the plot's flow (never drawn over the curves), and the
 * drawing is exactly the box it was given, however small — never negative, never larger.
 */

import { act, render } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Plot } from "./plot";
import { resetLaboratoryStore } from "./store";

afterEach(() => resetLaboratoryStore());

const t = Float64Array.from({ length: 101 }, (_, i) => i * 0.01);
const values = Float64Array.from({ length: 101 }, (_, i) => Math.sin(i / 10));

function observeWith(width: number, height: number) {
  const callbacks: ResizeObserverCallback[] = [];
  class FakeObserver {
    constructor(callback: ResizeObserverCallback) {
      callbacks.push(callback);
    }
    observe() {}
    disconnect() {}
    unobserve() {}
  }
  vi.stubGlobal("ResizeObserver", FakeObserver);
  return () =>
    act(() => {
      for (const callback of callbacks) {
        callback([{ contentRect: { width, height } } as ResizeObserverEntry], {} as ResizeObserver);
      }
    });
}

function renderPlot() {
  return render(
    <Plot
      title="Kinematics"
      unit="deg"
      t={t}
      series={[
        { key: "a", label: "left knee", values, color: "red" },
        { key: "b", label: "right knee", values, color: "blue", dashed: true },
      ]}
      spans={[{ phase: "descent", start_s: 0, end_s: 1 }]}
      duration={1}
    />,
  );
}

describe("the plot", () => {
  it("puts the legend in the plot's flow, between the caption and the drawing", () => {
    const { container } = renderPlot();
    const figure = container.querySelector("figure.lab-plot") as HTMLElement;
    const children = [...figure.children].map((child) => child.className || child.tagName.toLowerCase());
    const legend = children.findIndex((name) => String(name).includes("lab-plot-legend"));
    const frame = children.findIndex((name) => String(name).includes("lab-plot-frame"));
    expect(children[0]).toBe("figcaption");
    expect(legend).toBeGreaterThan(0);
    expect(frame).toBeGreaterThan(legend);
    expect(figure.querySelector(".lab-plot-frame .lab-plot-legend")).toBeNull();
  });

  it("draws exactly the box it is given, and never a negative one", () => {
    const resize = observeWith(0, 0);
    const { container } = renderPlot();
    resize();
    const svg = container.querySelector(".lab-plot-frame > svg") as SVGSVGElement;
    expect(Number(svg.getAttribute("width"))).toBe(1);
    expect(Number(svg.getAttribute("height"))).toBe(1);
    for (const rect of container.querySelectorAll("rect")) {
      expect(Number(rect.getAttribute("width") ?? "0")).toBeGreaterThanOrEqual(0);
      expect(Number(rect.getAttribute("height") ?? "0")).toBeGreaterThanOrEqual(0);
    }
  });

  it("follows its frame's size exactly", () => {
    const resize = observeWith(377.4, 201.6);
    const { container } = renderPlot();
    resize();
    const svg = container.querySelector(".lab-plot-frame > svg") as SVGSVGElement;
    expect(svg.getAttribute("viewBox")).toBe("0 0 377 202");
  });

  it("is styled with the legend in flow and the drawing confined to its frame", () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const css = readFileSync(resolve(here, "../styles.css"), "utf8");
    const rule = (selector: string) => {
      const start = css.indexOf(`${selector} {`);
      return start < 0 ? "" : css.slice(start, css.indexOf("}", start));
    };
    expect(rule(".lab-plot-legend")).not.toMatch(/position:\s*absolute/);
    expect(rule(".lab-plot")).toMatch(/grid-template-rows: auto auto minmax\(0, 1fr\) auto/);
    // the plot's one column may be narrower than a long title or legend: nothing overflows
    // into the neighbouring plot at narrow windows
    expect(rule(".lab-plot")).toMatch(/grid-template-columns: minmax\(0, 1fr\)/);
    expect(rule(".lab-plot-title")).toMatch(/min-width: 0/);
    expect(rule(".lab-plot-frame")).toMatch(/min-width: 0/);
    expect(rule(".lab-plot-frame > svg")).toMatch(/inset: 0/);
  });
});
