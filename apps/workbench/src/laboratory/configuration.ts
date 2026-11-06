/**
 * Presenting a study's configuration factors, and turning what a researcher typed back into
 * canonical values — exactly, or not at all.
 *
 * A factor travels in its canonical unit (radians, seconds, a gain); the workbench shows it in
 * the unit the catalogue names for display. The two conversions below are the ones the run
 * service's own arithmetic uses (`math.radians` is `x * (pi / 180)`), so a typed 120° is the
 * same double the catalogue's upper bound is. Values are never clipped or snapped: a value out
 * of range is reported and left for preflight to refuse, and a discrete factor is chosen from
 * its published list, which is sent exactly as published.
 */

import type { CatalogueFactor, CatalogueStudy, FactorDisplay } from "../api/run-types";
import type { RunDraft } from "./store";

const DEGREES_PER_RADIAN = 180 / Math.PI;
const RADIANS_PER_DEGREE = Math.PI / 180;

export const DISPLAY_UNITS: Record<FactorDisplay, string> = {
  degree: "°",
  millisecond: "ms",
  second: "s",
  unitless: "",
};

/** The canonical value in its display unit. */
export function toDisplay(display: FactorDisplay, value: number): number {
  switch (display) {
    case "degree":
      return value * DEGREES_PER_RADIAN;
    case "millisecond":
      return value * 1000;
    case "second":
    case "unitless":
      return value;
  }
}

/** A display value back in the canonical unit. */
export function fromDisplay(display: FactorDisplay, value: number): number {
  switch (display) {
    case "degree":
      return value * RADIANS_PER_DEGREE;
    case "millisecond":
      return value / 1000;
    case "second":
    case "unitless":
      return value;
  }
}

/** Display digits that show a value of this factor without noise. */
export function displayDigits(display: FactorDisplay): number {
  return display === "degree" ? 1 : display === "millisecond" ? 3 : 2;
}

/** A display value as text: rounded for reading, never for sending. */
export function formatDisplay(factor: CatalogueFactor, value: number): string {
  const shown = toDisplay(factor.display, value);
  const digits = displayDigits(factor.display);
  return String(Number(shown.toFixed(digits)));
}

/** Parse what was typed: a finite number in the display unit, or `null`. */
export function parseDisplay(text: string): number | null {
  const trimmed = text.trim().replace("−", "-");
  if (trimmed === "" || !/^[-+]?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?$/i.test(trimmed)) {
    return null;
  }
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : null;
}

/** Why a canonical value is not admissible for a factor, or `null` when it is. */
export function factorProblem(factor: CatalogueFactor, value: number | undefined): string | null {
  if (value === undefined || !Number.isFinite(value)) {
    return "a number is required";
  }
  if (factor.choices.length > 0 && !factor.choices.includes(value)) {
    return "choose one of the admissible values";
  }
  if (value < factor.lower || value > factor.upper) {
    const unit = DISPLAY_UNITS[factor.display];
    return `outside the qualified range ${formatDisplay(factor, factor.lower)}–${formatDisplay(factor, factor.upper)}${unit === "" ? "" : ` ${unit}`}`;
  }
  return null;
}

/** The nominal configuration of a study with a preset applied. */
export function presetValues(study: CatalogueStudy, preset: string): Record<string, number> {
  const values: Record<string, number> = {};
  for (const factor of study.factors) {
    values[factor.factor_id] = factor.nominal;
  }
  return { ...values, ...(study.presets[preset] ?? {}) };
}

/** The preset a configuration is exactly equal to, or `custom`. */
export function matchingPreset(study: CatalogueStudy, values: Readonly<Record<string, number>>): string {
  for (const name of Object.keys(study.presets)) {
    const preset = presetValues(study, name);
    if (study.factors.every((factor) => preset[factor.factor_id] === values[factor.factor_id])) {
      return name;
    }
  }
  return "custom";
}

/** A fresh draft of a study at its nominal configuration. */
export function nominalDraft(study: CatalogueStudy): RunDraft {
  return { studyId: study.study_id, caseId: "nominal", values: presetValues(study, "nominal") };
}

/** Whether two configurations are the same request (same factors, the same doubles). */
export function sameConfiguration(
  a: Readonly<Record<string, number>>,
  b: Readonly<Record<string, number>>,
): boolean {
  const keys = Object.keys(a);
  return keys.length === Object.keys(b).length && keys.every((key) => a[key] === b[key]);
}

/** A one-line description of a configuration in display units. */
export function describeConfiguration(
  factors: readonly CatalogueFactor[],
  values: Readonly<Record<string, number>>,
): string {
  return factors
    .map((factor) => {
      const value = values[factor.factor_id];
      const unit = DISPLAY_UNITS[factor.display];
      return `${shortFactorName(factor)} ${value === undefined ? "—" : formatDisplay(factor, value)}${unit === "" ? "" : unit === "°" ? "°" : ` ${unit}`}`;
    })
    .join(" · ");
}

/** The last segment of a factor id, e.g. `bottom-knee-flexion`. */
export function shortFactorName(factor: Pick<CatalogueFactor, "factor_id">): string {
  const parts = factor.factor_id.split(".");
  return parts[parts.length - 1] ?? factor.factor_id;
}
