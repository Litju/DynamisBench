/**
 * The frontend's structural gates: what the production workbench source is allowed to contain.
 *
 * Behaviour tests see what the code does; these read the files that *give* the frontend its
 * powers and assert the dangerous ones are absent. The failures they prevent are silent until
 * used: a second module reaching for Tauri IPC, a `fetch` call in a component, a cache warmed
 * into `localStorage`, a credential entering a query key, a scientific layer imported into
 * the browser.
 *
 * The scan is deliberately simple and is label-led: comments are removed first, so a
 * docstring cannot satisfy a gate and prose cannot fail one, and every assertion names the
 * files it is about. It is a tripwire, not a parser — a new occurrence is a reviewed change.
 */

import { describe, expect, it } from "vitest";

/** Every frontend source file, as text, read at test time by Vite itself. */
const RAW_SOURCES = import.meta.glob("../**/*.{ts,tsx,css}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

/** The capability file the desktop shell grants itself, read from the repository. */
const CAPABILITIES = import.meta.glob("../../../desktop/src-tauri/capabilities/default.json", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

type Source = { readonly path: string; readonly source: string };

/** The source tree, as the gates name it. */
const SRC_ROOT = "/src";

/**
 * The source file's path relative to `src/`, which is how the gates name files.
 *
 * Glob keys are relative to *this* file, so a sibling is `./x.ts` and a file above it is
 * `../api/x.ts`. Resolving against the directory instead of trimming prefixes is what keeps
 * a test file from being mistaken for production source.
 */
function relativeToSource(key: string): string {
  const resolved = new URL(key, `https://workbench.invalid${SRC_ROOT}/test/`).pathname;

  if (!resolved.startsWith(`${SRC_ROOT}/`)) {
    throw new Error(`${key} is outside the frontend source tree`);
  }

  return resolved.slice(SRC_ROOT.length + 1);
}

/** Remove line and block comments, so prose neither satisfies nor fails a gate. */
function withoutComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
}

const SOURCES: readonly Source[] = Object.entries(RAW_SOURCES)
  .map(([key, source]) => ({ path: relativeToSource(key), source }))
  .map((entry) => ({ path: entry.path, source: withoutComments(entry.source) }));

/**
 * The production frontend: everything the build ships, and nothing that tests it.
 *
 * A test is allowed to import what a component may not — that is how a boundary is observed
 * — so the test tree and every `*.test.*` file are out of scope for every gate below.
 */
const PRODUCTION: readonly Source[] = SOURCES.filter(
  (source) =>
    !source.path.startsWith("test/") &&
    !source.path.includes(".test.") &&
    source.path !== "vite.config.ts",
);

function filesMatching(predicate: (source: string) => boolean): string[] {
  return PRODUCTION.filter((source) => predicate(source.source))
    .map((source) => source.path)
    .sort();
}

function sourceOf(path: string): string {
  const found = PRODUCTION.find((source) => source.path === path);
  if (found === undefined) {
    throw new Error(`${path} must be part of the production frontend`);
  }
  return found.source;
}

/**
 * Every import specifier in a file.
 *
 * Static imports, side-effect imports, dynamic imports and re-exports, because the rule is
 * about the dependency and not about the syntax that reaches for it.
 */
function importSpecifiers(source: string): string[] {
  const patterns = [
    /import\s+[^"'();]*?from\s*["']([^"']+)["']/g,
    /import\s*["']([^"']+)["']/g,
    /import\s*\(\s*["']([^"']+)["']\s*\)/g,
    /export\s+[^"'();]*?from\s*["']([^"']+)["']/g,
  ];

  const specifiers: string[] = [];
  for (const pattern of patterns) {
    for (const match of source.matchAll(pattern)) {
      const specifier = match[1];
      if (specifier !== undefined) {
        specifiers.push(specifier);
      }
    }
  }
  return specifiers;
}

describe("the production frontend", () => {
  it("is what the gates below are scanning", () => {
    expect(PRODUCTION.length).toBeGreaterThan(10);
    expect(PRODUCTION.map((source) => source.path)).toContain("main.tsx");
    expect(PRODUCTION.map((source) => source.path)).not.toContain("test/setup.ts");
  });
});

describe("Tauri IPC is one adapter", () => {
  const TAURI_ADAPTER = "session/tauri-source.ts";

  it("is imported by exactly one frontend module", () => {
    const importers = filesMatching((source) =>
      importSpecifiers(source).some((specifier) => specifier.startsWith("@tauri-apps/")),
    );

    expect(importers).toEqual([TAURI_ADAPTER]);
  });

  it("is named by no other frontend module, however it were reached", () => {
    // The literal scan catches what the specifier scan cannot: a computed import, a string
    // path, or a package re-exported under another name.
    const namers = filesMatching((source) => source.includes("@tauri-apps/"));

    expect(namers).toEqual([TAURI_ADAPTER]);
  });

  it("is the only module that speaks the desktop shell's command and event", () => {
    const namers = filesMatching(
      (source) => source.includes("get_api_session") || source.includes("dynamisbench-api-status"),
    );

    expect(namers).toEqual([TAURI_ADAPTER]);
  });

  it("is asked exactly once, where the runtime's source is chosen", () => {
    const callers = filesMatching((source) => source.includes("isTauri("));

    expect(callers).toEqual(["session/source.ts"]);
  });
});

describe("HTTP is one client", () => {
  const API_CLIENT = "api/client.ts";

  it("calls fetch in exactly one module", () => {
    const callers = filesMatching((source) => /\bfetch\s*\(/.test(source));

    expect(callers).toEqual([API_CLIENT]);
  });

  it("builds the versioned namespace in exactly one module", () => {
    const builders = filesMatching((source) => source.includes("/api/v1"));

    expect(builders).toEqual([API_CLIENT]);
  });

  it("sends the credential header in exactly one module", () => {
    const senders = filesMatching(
      (source) => source.includes("Authorization") || source.includes("Bearer"),
    );

    expect(senders).toEqual([API_CLIENT]);
  });
});

describe("nothing is persisted", () => {
  const STORAGE = ["localStorage", "sessionStorage", "indexedDB", "document.cookie"];

  for (const mechanism of STORAGE) {
    it(`never reaches for ${mechanism}`, () => {
      expect(filesMatching((source) => source.includes(mechanism))).toEqual([]);
    });
  }

  it("does not import Zustand's persistence middleware", () => {
    const importers = filesMatching((source) =>
      importSpecifiers(source).some((specifier) => specifier.startsWith("zustand/middleware")),
    );
    const callers = filesMatching((source) => /\bpersist\s*\(/.test(source));

    expect(importers).toEqual([]);
    expect(callers).toEqual([]);
  });

  it("does not use a query-cache persistence plugin", () => {
    const persistQueryCache = filesMatching((source) =>
      /persistQueryClient|createSyncStoragePersister|createAsyncStoragePersister/.test(source),
    );

    expect(persistQueryCache).toEqual([]);
  });
});

describe("the credential stays in the session and the client", () => {
  /**
   * The only production modules that may mention the word at all.
   *
   * `api/client.ts` presents it; `shell/runtime-state.ts` renders the desktop shell's own
   * `credential_unavailable` failure code and says what it means. Neither holds one, and the
   * assertion below pins the second to exactly that.
   */
  const MAY_MENTION = ["api/client.ts", "shell/runtime-state.ts"];

  it("is named only where it is held, presented, or reported as missing", () => {
    const namers = filesMatching((source) => /\bcredential\b/.test(source)).filter(
      (path) => !path.startsWith("session/") && !MAY_MENTION.includes(path),
    );

    expect(namers).toEqual([]);
  });

  it("is otherwise only the desktop shell's own failure code", () => {
    const shell = sourceOf("shell/runtime-state.ts");
    const withoutTheCode = shell
      .replaceAll("credential_unavailable", "")
      .replaceAll("a session credential could not be produced", "");

    expect(withoutTheCode).not.toMatch(/credential/i);
  });

  it("is absent from the module that owns query keys", () => {
    const keys = sourceOf("api/queries.ts");

    for (const forbidden of ["credential", "Authorization", "Bearer", "token", "origin"]) {
      expect(keys).not.toContain(forbidden);
    }
  });

  it("is absent from router context and route parameters", () => {
    for (const path of ["routes/context.ts", "router.tsx", "routes/root.tsx", "routes/landing.tsx", "routes/workspace.tsx"]) {
      for (const forbidden of ["credential", "Authorization", "Bearer"]) {
        expect(sourceOf(path)).not.toContain(forbidden);
      }
    }
  });
});

describe("the event stream is fetch-based and transient", () => {
  it("never uses the browser's EventSource or a WebSocket", () => {
    const users = filesMatching(
      (source) => /\bEventSource\b/.test(source) || /\bWebSocket\b/.test(source),
    );

    expect(users).toEqual([]);
  });

  it("keeps the reconnect loop out of the HTTP client module", () => {
    // One module decides how to ask again, and one module decides how to ask at all.
    expect(sourceOf("api/client.ts")).not.toContain("maxConsecutiveFailures");
    expect(sourceOf("api/event-stream.ts")).not.toContain("/api/v1");
  });

  it("does not persist activity", () => {
    for (const path of ["workbench/activity.tsx", "workbench/activity-feed.ts"]) {
      const source = sourceOf(path);
      expect(source).not.toMatch(/localStorage|sessionStorage|indexedDB|document\.cookie/);
    }
  });
});

describe("the browser depends on nothing scientific", () => {
  /** The runtime dependencies the workbench is allowed to import, and nothing else. */
  const ALLOWED_SPECIFIERS = new Set([
    "react",
    "react-dom/client",
    "@tanstack/react-query",
    "@tanstack/react-router",
    "@tauri-apps/api/core",
    "@tauri-apps/api/event",
    "lucide-react",
    "zustand",
    "@radix-ui/react-slot",
    "apache-arrow",
    "class-variance-authority",
    "clsx",
    "tailwind-merge",
    "./styles.css",
  ]);

  const SCIENTIFIC = /dynamisbench|python|simulator|execution|evidence|mujoco|opensim|duckdb/i;

  it("imports only the workbench's own modules and its declared dependencies", () => {
    const unexpected: string[] = [];

    for (const source of PRODUCTION) {
      for (const specifier of importSpecifiers(source.source)) {
        const relative = specifier.startsWith("./") || specifier.startsWith("../");
        if (!relative && !ALLOWED_SPECIFIERS.has(specifier)) {
          unexpected.push(`${source.path} -> ${specifier}`);
        }
      }
    }

    expect(unexpected).toEqual([]);
  });

  it("imports no simulator, Python, execution or evidence module by any name", () => {
    const imports = PRODUCTION.flatMap((source) =>
      importSpecifiers(source.source)
        .filter((specifier) => SCIENTIFIC.test(specifier))
        .map((specifier) => `${source.path} -> ${specifier}`),
    );

    expect(imports).toEqual([]);
  });

  it("reads no application or scientific data other than over HTTP", () => {
    // The one frontend module that may name the application's own surfaces is the client,
    // and it names them as URLs.
    const namers = filesMatching((source) => source.includes("application/json")).filter(
      (path) => path !== "api/client.ts",
    );

    expect(namers).toEqual([]);
  });
});

describe("the workbench cannot mutate authority", () => {
  it("has no editable surface in the authority panes", () => {
    for (const path of [
      "workbench/artifact-tree.tsx",
      "workbench/explorer.tsx",
      "workbench/inspector.tsx",
      "routes/workspace.tsx",
    ]) {
      const source = sourceOf(path);
      expect(source).not.toMatch(/contentEditable|dangerouslySetInnerHTML|<textarea|<input/);
    }
  });

  it("has no write verb in the HTTP client except the root-selection command", () => {
    const client = sourceOf("api/client.ts");

    expect(client).not.toMatch(/method:\s*["'](?:PUT|PATCH|DELETE)["']/i);
    expect([...client.matchAll(/method:\s*["']POST["']/g)]).toHaveLength(1);
    expect(client).toContain('"/workspaces/open"');
  });

  it("keeps operational roots out of routes, query keys and activity", () => {
    for (const path of [
      "api/queries.ts",
      "router.tsx",
      "routes/workspace.tsx",
      "workbench/activity.tsx",
      "workbench/activity-feed.ts",
    ]) {
      for (const forbidden of ["sourceRoot", "evidenceRoot", "source_root", "evidence_root"]) {
        expect(sourceOf(path)).not.toContain(forbidden);
      }
    }
  });

  it("does not retain any read model in the activity feed", () => {
    const feed = sourceOf("workbench/activity-feed.ts");

    for (const forbidden of [
      "logical_reference",
      "semantic_digest",
      "artifact_id",
      "content",
    ]) {
      expect(feed).not.toContain(forbidden);
    }
  });
});

describe("Arrow is a lazy transport utility", () => {
  const ARROW = "arrow/arrow.ts";

  it("is the only production module that names the Arrow package", () => {
    const namers = filesMatching((source) => source.includes("apache-arrow"));

    expect(namers).toEqual([ARROW]);
  });

  it("imports the package dynamically, never into the initial module graph", () => {
    const source = sourceOf(ARROW);

    expect(source).toMatch(/import\s*\(\s*["']apache-arrow["']\s*\)/);
    expect(source).not.toMatch(/^\s*import\s+[^;]*from\s*["']apache-arrow["']/m);
    expect(source).not.toMatch(/^\s*import\s*["']apache-arrow["']/m);
  });

  it("is not imported by the route tree, the client or the shell", () => {
    const importers = filesMatching((source) =>
      importSpecifiers(source).some((specifier) => specifier.includes("arrow/arrow")),
    );

    expect(importers).toEqual([]);
  });
});

describe("the desktop shell's capability grant is exactly the listener's", () => {
  /**
   * The two permissions a WebView needs to hear the sidecar's lifecycle, and the reason they
   * are not an empty list: in Tauri v2 a listener is the core event plugin's
   * `plugin:event|listen` command, and the ACL refuses plugin invokes without a grant
   * (tauri 2.12.1, `src/webview/mod.rs`). With no grant the workbench could never learn that
   * its API session became ready — a failure no browser-mode test can observe.
   */
  const GRANTED = ["core:event:allow-listen", "core:event:allow-unlisten"];

  it("grants the two core-event permissions, and nothing else", () => {
    const contents = Object.values(CAPABILITIES);
    expect(contents).toHaveLength(1);

    const parsed = JSON.parse(contents[0] ?? "{}") as { permissions?: unknown };
    expect(parsed.permissions).toEqual(GRANTED);
  });

  it("grants no filesystem, shell, process, dialog or emit permission", () => {
    const parsed = JSON.parse(Object.values(CAPABILITIES)[0] ?? "{}") as {
      permissions?: unknown;
    };
    const serialized = JSON.stringify(parsed.permissions ?? []);

    for (const banned of ["shell", "fs", "process", "spawn", "execute", "dialog", "emit"]) {
      expect(serialized).not.toContain(banned);
    }
  });

  it("adds no Tauri plugin to the workbench", () => {
    const dependencies = import.meta.glob("../../package.json", {
      query: "?raw",
      import: "default",
      eager: true,
    }) as Record<string, string>;

    const manifest = Object.values(dependencies)[0] ?? "{}";
    expect(manifest).not.toMatch(/@tauri-apps\/plugin-/);
  });
});

describe("the frontend restates the servers' vocabularies, exactly", () => {
  /**
   * The closure of a set of values this frontend keeps its own copy of, checked against the
   * source of truth rather than against a second copy of itself.
   *
   * A restated vocabulary is a contract, and a contract that drifts silently is worse than
   * no contract at all: a diagnostic code added to the reader, or a third lifecycle state,
   * would reach this tree as a value the frontend's types claim cannot happen. These gates
   * read the Python and Rust sources that own each vocabulary and compare the *sets* — order
   * is not part of the contract, membership is.
   */
  const SERVER_SOURCES = import.meta.glob(
    [
      // The Python distribution and the Rust shell are both above the frontend's own root:
      // `apps/workbench/src/test` reaches `apps/` in three steps and the repository in four.
      "../../../../python/src/dynamisbench/workspace/authority.py",
      "../../../../python/src/dynamisbench/workspace/source_authority.py",
      "../../../../python/src/dynamisbench/api/errors.py",
      "../../../desktop/src-tauri/src/sidecar/state.rs",
    ],
    { query: "?raw", import: "default", eager: true },
  ) as Record<string, string>;

  function serverSource(name: string): string {
    const found = Object.entries(SERVER_SOURCES).find(([key]) => key.endsWith(name));

    if (found === undefined) {
      throw new Error(`${name} must be readable: the vocabulary it owns is restated here`);
    }
    return found[1];
  }

  /** The string values of one Python `StrEnum`, in the order the source declares them. */
  function pythonEnumValues(source: string, className: string): string[] {
    const declaration = `class ${className}(`;
    const start = source.indexOf(declaration);
    if (start === -1) {
      throw new Error(`${className} must be declared`);
    }

    const body = source.slice(start);
    const end = body.slice(1).search(/\n[^\s]/);
    const block = end === -1 ? body : body.slice(0, end + 1);

    return [...block.matchAll(/^\s{4}[A-Z][A-Z0-9_]* = "([a-z0-9_]+)"/gm)]
      .map((match) => match[1] ?? "")
      .sort();
  }

  /** The snake_case names of one Rust unit enum's variants. */
  function rustEnumVariants(source: string, enumName: string): string[] {
    const declaration = `pub enum ${enumName} {`;
    const start = source.indexOf(declaration);
    if (start === -1) {
      throw new Error(`${enumName} must be declared`);
    }

    const block = source.slice(start).split("}")[0] ?? "";

    return [...block.matchAll(/^\s{4}([A-Z][A-Za-z0-9]*),$/gm)]
      .map((match) => (match[1] ?? "").replace(/([a-z0-9])([A-Z])/g, "$1_$2").toLowerCase())
      .sort();
  }

  it("matches the desktop shell's lifecycle and failure vocabulary", async () => {
    const { DESKTOP_FAILURE_CODES, DESKTOP_STATUSES } = await import("../session/types");
    const state = serverSource("sidecar/state.rs");

    expect([...DESKTOP_STATUSES].sort()).toEqual(rustEnumVariants(state, "SessionStatus"));
    expect([...DESKTOP_FAILURE_CODES].sort()).toEqual(rustEnumVariants(state, "FailureCode"));
  });

  it("matches the application's source categories and authoring vocabularies", async () => {
    const { AUTHORING_FORMATS, DIAGNOSTIC_CODES, SOURCE_CATEGORIES, VALIDATION_STATUSES } =
      await import("../api/types");

    expect([...SOURCE_CATEGORIES].sort()).toEqual(
      pythonEnumValues(serverSource("workspace/authority.py"), "SourceCategory"),
    );
    const sourceAuthority = serverSource("workspace/source_authority.py");
    expect([...AUTHORING_FORMATS].sort()).toEqual(
      pythonEnumValues(sourceAuthority, "AuthoringFormat"),
    );
    expect([...VALIDATION_STATUSES].sort()).toEqual(
      pythonEnumValues(sourceAuthority, "ValidationStatus"),
    );
    expect([...DIAGNOSTIC_CODES].sort()).toEqual(
      pythonEnumValues(sourceAuthority, "DiagnosticCode"),
    );
  });

  it("matches the application's error vocabulary", async () => {
    const { API_ERROR_CODES } = await import("../api/types");

    expect([...API_ERROR_CODES].sort()).toEqual(
      pythonEnumValues(serverSource("api/errors.py"), "ErrorCode"),
    );
  });

  it("reads every server file it is about", () => {
    expect(Object.keys(SERVER_SOURCES)).toHaveLength(4);
  });
});

describe("the scan itself", () => {
  it("finds the files it claims to be about", () => {
    // A glob that silently matched nothing would make every gate above pass for the wrong
    // reason, so the paths the gates name are asserted to exist.
    const expected = [
      "main.tsx",
      "api/client.ts",
      "api/queries.ts",
      "api/sse.ts",
      "api/event-stream.ts",
      "router.tsx",
      "session/tauri-source.ts",
      "session/source.ts",
      "store/ui.ts",
      "ui/button.tsx",
      "shell/app-shell.tsx",
      "workbench/activity.tsx",
      "workbench/activity-feed.ts",
    ];

    for (const path of expected) {
      expect(() => sourceOf(path)).not.toThrow();
    }
  });

  it("reads the capability file it is about", () => {
    expect(Object.values(CAPABILITIES)).toHaveLength(1);
  });

  it("is a tripwire that fails when a gate would", () => {
    // The negative control: the same predicate the Tauri gate uses, pointed at a file that
    // *does* reach for Tauri. If this did not match, the gate above would be vacuous.
    const adapter = sourceOf("session/tauri-source.ts");

    expect(importSpecifiers(adapter).some((specifier) => specifier.startsWith("@tauri-apps/"))).toBe(
      true,
    );
    expect(importSpecifiers(adapter)).toContain("@tauri-apps/api/core");
  });
});
