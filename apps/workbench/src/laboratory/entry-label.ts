import type { CatalogueEntry } from "./sources";

/** What a catalogue entry is called in a selector, with its source stated. */
export function entryOptionLabel(entry: CatalogueEntry): string {
  if (entry.ref.source === "dataset") {
    return entry.label;
  }
  return entry.playable ? `Run · ${entry.label}` : `Run · ${entry.label} (${entry.status})`;
}
