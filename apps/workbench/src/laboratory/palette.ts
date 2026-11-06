/**
 * The Codex pigments for drawing surfaces that cannot read CSS variables (the WebGL stage).
 *
 * The same values as the `--codex-*` custom properties in `styles.css` (Studiolo is the dark
 * ground, Vellum the light one); `design/DESIGN.md` §2 is the specification both follow. SVG
 * instruments use the CSS variables directly, so only the stage reads this table.
 */

export type Ground = "studiolo" | "vellum";

export interface Palette {
  readonly ground: string;
  readonly stage: string;
  readonly panel: string;
  readonly line: string;
  readonly line2: string;
  readonly ink: string;
  readonly ink3: string;
  readonly ink4: string;
  readonly bone: string;
  readonly boneShade: string;
  readonly steel: string;
  readonly sole: string;
  readonly sanguine: string;
  readonly lapis: string;
  readonly verdigris: string;
  readonly gold: string;
  readonly ochre: string;
  readonly vermilion: string;
  /** Opacity of the athlete's floor shadow on this ground. */
  readonly shadowOpacity: number;
  /** The anatomical figure: skin and its garments (presentation only). */
  readonly figure: {
    readonly skin: string;
    readonly shirt: string;
    readonly shorts: string;
    readonly shoe: string;
    readonly outsole: string;
    readonly hair: string;
  };
}

export const PALETTES: Readonly<Record<Ground, Palette>> = {
  studiolo: {
    ground: "#0E0C0A",
    stage: "#110F0C",
    panel: "#15120F",
    line: "#2C2721",
    line2: "#3D362C",
    ink: "#EEE6D6",
    ink3: "#9A8C75",
    ink4: "#6C6150",
    bone: "#D8C7A6",
    boneShade: "#8C7A5C",
    steel: "#AEB2B8",
    sole: "#5C5140",
    sanguine: "#D0603F",
    lapis: "#7393E3",
    verdigris: "#5FB39A",
    gold: "#D9AE55",
    ochre: "#D99A3E",
    vermilion: "#E2604B",
    shadowOpacity: 0.45,
    figure: {
      skin: "#C8A283",
      shirt: "#3D4A5C",
      shorts: "#24272E",
      shoe: "#55565C",
      outsole: "#DCD6C8",
      hair: "#3A2B21",
    },
  },
  vellum: {
    ground: "#EDE4D1",
    stage: "#F4EDDF",
    panel: "#F8F3E8",
    line: "#D6C8AB",
    line2: "#BFAE8C",
    ink: "#231C13",
    ink3: "#75684F",
    ink4: "#9A8C70",
    bone: "#CDB893",
    boneShade: "#8E7752",
    steel: "#7F858D",
    sole: "#8E7D62",
    sanguine: "#A4442A",
    lapis: "#2B4C9E",
    verdigris: "#2D7A63",
    gold: "#A77A1E",
    ochre: "#B2721D",
    vermilion: "#B83A27",
    shadowOpacity: 0.2,
    figure: {
      skin: "#C49C7C",
      shirt: "#34455E",
      shorts: "#262A32",
      shoe: "#4F5157",
      outsole: "#E4DED0",
      hair: "#352619",
    },
  },
};

/** The shell theme ("dark" | "light") as a Codex ground. */
export function groundOf(theme: "light" | "dark"): Ground {
  return theme === "dark" ? "studiolo" : "vellum";
}

/** Phase pigments (CSS custom properties), shared by every phase strip and wash. */
export const PHASE_VARIABLES: Readonly<Record<string, string>> = {
  standing: "var(--codex-phase-rest)",
  descent: "var(--codex-lapis)",
  bottom: "var(--codex-gold)",
  ascent: "var(--codex-verdigris)",
  return: "var(--codex-phase-rest)",
};

export function phaseVariable(phase: string): string {
  return PHASE_VARIABLES[phase] ?? "var(--codex-ink-4)";
}

/** A phase pigment thinned over the ground, for strips and washes that carry text. */
export function phaseWash(phase: string, percent: number): string {
  return `color-mix(in srgb, ${phaseVariable(phase)} ${percent}%, transparent)`;
}
