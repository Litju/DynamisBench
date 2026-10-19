/**
 * The class-name helper the primitives are built on.
 *
 * `clsx` composes the conditional classes a variant needs, and `tailwind-merge` resolves the
 * result so a caller's `className` overrides a variant's own utilities instead of racing
 * them in the stylesheet. One function, used by every primitive, so "the last class wins" is
 * a property of the component rather than of the order a stylesheet happened to be emitted in.
 */

import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
