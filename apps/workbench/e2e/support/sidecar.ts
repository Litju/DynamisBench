/**
 * Real process support for the browser-qualification gates.
 *
 * Every claim these helpers enable is about a process this module really started: the locked
 * Python environment's `python -m dynamisbench api serve`, a generated session credential in
 * its environment, its announced loopback origin, and its own stdin control channel. Nothing
 * here proxies the API or answers on its behalf.
 *
 * Diagnostics stay local. A failure message names the stage that failed and at most a bounded
 * excerpt of stderr; it never prints the credential. Workspace roots are created under the
 * operating system's temporary directory and removed by `dispose`.
 */

import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { randomBytes } from "node:crypto";
import { existsSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { e2eOrigin, e2eWorkspaceTool, pythonExecutable, repositoryRoot } from "./paths";

const READINESS_TIMEOUT_MS = 60_000;
const SHUTDOWN_TIMEOUT_MS = 30_000;
const MAX_DIAGNOSTIC_CHARS = 400;

/** The one record the sidecar accepts on its private control channel. */
const SHUTDOWN_RECORD = JSON.stringify({
  kind: "dynamisbench.api.shutdown",
  protocol_version: 1,
});

export interface ReadyBootstrap {
  readonly status: "ready";
  readonly origin: string;
  readonly api_version: "v1";
  readonly protocol_version: 1;
  readonly credential: string;
  readonly restart_required: false;
  readonly failure: null;
}

export interface FailedBootstrap {
  readonly status: "failed";
  readonly origin: null;
  readonly api_version: null;
  readonly protocol_version: null;
  readonly credential: null;
  readonly restart_required: true;
  readonly failure: "unexpected_exit";
}

/** The shell's announcement after the supervised child died without being asked to stop. */
export function failedBootstrap(): FailedBootstrap {
  return {
    status: "failed",
    origin: null,
    api_version: null,
    protocol_version: null,
    credential: null,
    restart_required: true,
    failure: "unexpected_exit",
  };
}

export interface SidecarSession {
  readonly origin: string;
  readonly port: number;
  readonly credential: string;
  readonly process: ChildProcess;
  /** A full `get_api_session` response for the ready sidecar, for the test bridge. */
  bootstrap(): ReadyBootstrap;
  /** Ask through stdin and wait for the real exit; force-kill only after the deadline. */
  stop(): Promise<number>;
  /** Terminate the real child without asking, as an unexpected loss would. */
  kill(): Promise<number>;
}

interface Readiness {
  readonly kind: string;
  readonly protocol_version: number;
  readonly api_version: string;
  readonly host: string;
  readonly port: number;
}

function boundedDiagnostic(value: string): string {
  const trimmed = value.trim();
  return trimmed.length <= MAX_DIAGNOSTIC_CHARS
    ? trimmed
    : `${trimmed.slice(0, MAX_DIAGNOSTIC_CHARS)}…`;
}

/** The first line on the child's stdout, or a bounded failure after the deadline. */
function firstLine(child: ChildProcess): Promise<string> {
  return new Promise((resolve, reject) => {
    if (child.stdout === null) {
      reject(new Error("the sidecar has no stdout"));
      return;
    }

    let buffer = "";
    let settled = false;
    const stdout = child.stdout;
    let stderr = "";
    child.stderr?.on("data", (chunk: Buffer) => {
      if (stderr.length < MAX_DIAGNOSTIC_CHARS) {
        stderr += chunk.toString("utf8");
      }
    });

    const finish = (error: Error | null, line?: string) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      stdout.off("data", onData);
      child.off("exit", onExit);
      if (error !== null) {
        reject(error);
        return;
      }
      resolve(line ?? "");
    };

    const onData = (chunk: Buffer) => {
      buffer += chunk.toString("utf8");
      const newline = buffer.indexOf("\n");
      if (newline !== -1) {
        finish(null, buffer.slice(0, newline));
      }
    };
    const onExit = (code: number | null) => {
      finish(
        new Error(
          `the sidecar exited before readiness (code ${String(code)}): ${boundedDiagnostic(stderr)}`,
        ),
      );
    };
    const timer = setTimeout(() => {
      child.kill();
      finish(
        new Error(
          `the sidecar announced no readiness within ${READINESS_TIMEOUT_MS} ms: ${boundedDiagnostic(stderr)}`,
        ),
      );
    }, READINESS_TIMEOUT_MS);

    stdout.on("data", onData);
    child.once("exit", onExit);
  });
}

/** Resolve with the child's exit code, or reject when the deadline passes. */
function waitForExit(child: ChildProcess, timeoutMs: number): Promise<number> {
  return new Promise((resolve, reject) => {
    let timer: NodeJS.Timeout | undefined;
    const onExit = (exitCode: number | null) => {
      if (timer !== undefined) {
        clearTimeout(timer);
      }
      resolve(exitCode ?? -1);
    };

    // Register before reading the exit state: an exit between the two would otherwise be
    // observed by neither this listener nor the check, and teardown would wait for a deadline
    // that has already passed. A process terminated by a signal reports `exitCode === null`
    // and `signalCode !== null`, so both have to be read.
    child.once("exit", onExit);
    if (child.exitCode !== null || child.signalCode !== null) {
      child.off("exit", onExit);
      resolve(child.exitCode ?? -1);
      return;
    }

    timer = setTimeout(() => {
      child.off("exit", onExit);
      reject(new Error("the sidecar did not stop within the shutdown deadline"));
    }, timeoutMs);
  });
}

function parseReadiness(line: string): Readiness {  let value: unknown;
  try {
    value = JSON.parse(line);
  } catch {
    throw new Error("the sidecar's readiness record was not JSON");
  }
  if (typeof value !== "object" || value === null) {
    throw new Error("the sidecar's readiness record was not an object");
  }
  const record = value as Partial<Readiness>;
  if (
    record.kind !== "dynamisbench.api.ready" ||
    record.protocol_version !== 1 ||
    record.api_version !== "v1" ||
    record.host !== "127.0.0.1" ||
    typeof record.port !== "number" ||
    !Number.isInteger(record.port) ||
    record.port <= 0 ||
    record.port > 65535
  ) {
    throw new Error("the sidecar's readiness record did not match protocol v1");
  }
  return record as Readiness;
}

/** Start one real secured sidecar and wait for the port it actually bound. */
export async function startSidecar(): Promise<SidecarSession> {
  const executable = pythonExecutable();
  if (!existsSync(executable)) {
    throw new Error(
      "the locked Python environment is missing; run `uv sync --frozen` in python/ first",
    );
  }

  const credential = randomBytes(32).toString("base64url");
  const environment: NodeJS.ProcessEnv = { ...process.env };
  for (const name of Object.keys(environment)) {
    if (name.startsWith("DYNAMISBENCH_")) {
      delete environment[name];
    }
  }
  environment.DYNAMISBENCH_SESSION_TOKEN = credential;
  environment.DYNAMISBENCH_ALLOWED_ORIGINS = JSON.stringify([e2eOrigin()]);

  const child = spawn(
    executable,
    ["-m", "dynamisbench", "api", "serve"],
    {
      cwd: repositoryRoot(),
      env: environment,
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    },
  );

  const line = await firstLine(child);
  const readiness = parseReadiness(line);
  const origin = `http://${readiness.host}:${readiness.port}`;

  return {
    origin,
    port: readiness.port,
    credential,
    process: child,
    bootstrap: () => ({
      status: "ready",
      origin,
      api_version: "v1",
      protocol_version: 1,
      credential,
      restart_required: false,
      failure: null,
    }),
    async stop() {
      const stdin = child.stdin;
      if (child.exitCode === null && child.signalCode === null && stdin !== null) {
        stdin.write(`${SHUTDOWN_RECORD}\n`);
        stdin.end();
      }
      const code = await waitForExit(child, SHUTDOWN_TIMEOUT_MS);
      child.stdout?.destroy();
      child.stderr?.destroy();
      return code;
    },
    async kill() {
      if (child.exitCode === null && child.signalCode === null) {
        child.kill();
      }
      const code = await waitForExit(child, SHUTDOWN_TIMEOUT_MS);
      child.stdout?.destroy();
      child.stderr?.destroy();
      return code;
    },
  };
}

export interface WorkspaceFixture {
  readonly sourceRoot: string;
  readonly evidenceRoot: string;
  readonly validReference: string;
  readonly invalidReference: string;
  readonly validDigest: string;
  dispose(): Promise<void>;
}

interface WorkspaceDescription {
  readonly source_root: string;
  readonly evidence_root: string;
  readonly valid_reference: string;
  readonly invalid_reference: string;
  readonly valid_digest: string;
}

/** Create two real temporary roots with one valid and one invalid authority document. */
export async function createWorkspaceFixture(): Promise<WorkspaceFixture> {
  const root = await mkdtemp(path.join(tmpdir(), "dynamisbench-e2e-"));
  const created = spawnSync(pythonExecutable(), [e2eWorkspaceTool(), "--root", root], {
    cwd: repositoryRoot(),
    encoding: "utf8",
    timeout: 60_000,
  });
  if (created.status !== 0) {
    await rm(root, { recursive: true, force: true });
    throw new Error(
      `the workspace fixture could not be created: ${boundedDiagnostic(created.stderr)}`,
    );
  }

  let value: unknown;
  try {
    value = JSON.parse(created.stdout);
  } catch {
    await rm(root, { recursive: true, force: true });
    throw new Error("the workspace fixture did not publish a JSON description");
  }
  const description = value as Partial<WorkspaceDescription>;
  if (
    typeof description.source_root !== "string" ||
    typeof description.evidence_root !== "string" ||
    typeof description.valid_reference !== "string" ||
    typeof description.invalid_reference !== "string" ||
    typeof description.valid_digest !== "string"
  ) {
    await rm(root, { recursive: true, force: true });
    throw new Error("the workspace fixture description was incomplete");
  }

  return {
    sourceRoot: description.source_root,
    evidenceRoot: description.evidence_root,
    validReference: description.valid_reference,
    invalidReference: description.invalid_reference,
    validDigest: description.valid_digest,
    dispose: async () => {
      await rm(root, { recursive: true, force: true });
    },
  };
}

export interface ArrowFixture {
  /** The bytes every language must agree on, as the committed fixture spells them. */
  readonly bytes: Buffer;
  readonly sha256: string;
}

/** The Python encoder's output for the frozen Arrow qualification fixture. */
export function pythonArrowFixture(): ArrowFixture {
  const executable = pythonExecutable();
  const encoded = spawnSync(
    executable,
    [
      "-c",
      [
        "import base64, hashlib, sys",
        "from dynamisbench.transport.arrow import encode_qualification_stream",
        "payload = encode_qualification_stream()",
        "sys.stdout.write(base64.b64encode(payload).decode('ascii'))",
        "sys.stdout.write('\\n')",
        "sys.stdout.write(hashlib.sha256(payload).hexdigest())",
      ].join("\n"),
    ],
    { cwd: repositoryRoot(), encoding: "utf8", timeout: 60_000 },
  );
  if (encoded.status !== 0) {
    throw new Error(
      `the Python Arrow fixture could not be produced: ${boundedDiagnostic(encoded.stderr)}`,
    );
  }
  const [base64, sha256] = encoded.stdout.trim().split("\n");
  if (base64 === undefined || sha256 === undefined) {
    throw new Error("the Python Arrow fixture published no payload");
  }
  return { bytes: Buffer.from(base64, "base64"), sha256 };
}
