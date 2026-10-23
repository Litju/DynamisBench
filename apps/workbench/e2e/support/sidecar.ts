/**
 * Real process support for the browser-qualification gates.
 *
 * Every claim these helpers enable is about a process this module really started: the locked
 * Python environment's `python -m dynamisbench api serve`, a generated session credential in
 * its environment, its announced loopback origin, and its own stdin control channel. Nothing
 * here proxies the API or answers on its behalf.
 *
 * Diagnostics stay local. A failure message names the stage that failed and at most a bounded
 * excerpt of stderr; it never prints the credential or an absolute path. Workspace roots are
 * created under the operating system's temporary directory and removed by `dispose`.
 */

import { spawn, spawnSync, type ChildProcess } from "node:child_process";
import { randomBytes } from "node:crypto";
import { existsSync } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { request as httpRequest } from "node:http";
import { tmpdir } from "node:os";
import path from "node:path";

import { e2eOrigin, e2eWorkspaceTool, pythonExecutable, repositoryRoot } from "./paths";

const READINESS_TIMEOUT_MS = 60_000;
const SHUTDOWN_TIMEOUT_MS = 30_000;
const FORCED_SHUTDOWN_TIMEOUT_MS = 5_000;
const LISTENER_CHECK_TIMEOUT_MS = 2_000;
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

/** Test-only launch and observation seams; the fixture defaults remain the development launch. */
export interface SidecarStartOptions {
  readonly launch?: {
    readonly executable: string;
    readonly args: readonly string[];
  };
  readonly credential?: string;
  readonly readinessTimeoutMs?: number;
  readonly onSpawn?: (child: ChildProcess) => void;
}

interface Readiness {
  readonly kind: string;
  readonly protocol_version: number;
  readonly api_version: string;
  readonly host: string;
  readonly port: number;
}

function boundedDiagnostic(value: string, credentials: readonly string[] = []): string {
  let safe = value;
  for (const credential of credentials) {
    if (credential.length > 0) {
      safe = safe.split(credential).join("[redacted-credential]");
    }
  }
  safe = safe.replace(/Bearer\s+[^\s,;]+/gi, "Bearer [redacted-credential]");
  // Do not echo host paths through child or browser errors. The Windows expression consumes
  // the rest of that line so paths containing spaces cannot leak a partially absolute suffix.
  safe = safe.replace(/(?:[A-Za-z]:[\\/]|\\\\)[^\r\n"'<>|]*/g, "[redacted-path]");
  safe = safe.replace(/(?<![:/\\])\/[^\s"'<>]*/g, "[redacted-path]");
  const trimmed = safe.trim();
  return trimmed.length <= MAX_DIAGNOSTIC_CHARS
    ? trimmed
    : `${trimmed.slice(0, MAX_DIAGNOSTIC_CHARS)}…`;
}

/** A bounded, credential- and host-path-safe message for any harness failure. */
export function diagnosticMessage(
  error: unknown,
  credentials: readonly string[] = [],
): string {
  return boundedDiagnostic(error instanceof Error ? error.message : String(error), credentials);
}

/** Keep the original failure first, and append independent containment failures if any. */
export function containedError(
  primary: unknown,
  cleanupFailures: readonly unknown[] = [],
  credentials: readonly string[] = [],
): Error {
  const messages = [diagnosticMessage(primary, credentials)];
  for (const failure of cleanupFailures) {
    messages.push(`containment also failed: ${diagnosticMessage(failure, credentials)}`);
  }
  const error = new Error(messages.join("\n"));
  // A stack contains checkout and temporary paths. The safe stage/message is the diagnostic.
  error.stack = undefined;
  return error;
}

function hasExited(child: ChildProcess): boolean {
  return child.exitCode !== null || child.signalCode !== null;
}

function closeStdio(child: ChildProcess): void {
  child.stdin?.destroy();
  child.stdout?.destroy();
  child.stderr?.destroy();
}

/** The first line on the child's stdout, or a bounded failure after the deadline. */
function firstLine(
  child: ChildProcess,
  timeoutMs: number,
  credential: string,
): Promise<string> {
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
        stderr = (stderr + chunk.toString("utf8")).slice(0, MAX_DIAGNOSTIC_CHARS);
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
      child.off("error", onError);
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
          `the sidecar exited before readiness (code ${String(code)}): ${boundedDiagnostic(stderr, [credential])}`,
        ),
      );
    };
    const onError = (error: Error) => {
      finish(new Error(`the sidecar could not be spawned: ${diagnosticMessage(error, [credential])}`));
    };
    const timer = setTimeout(() => {
      finish(
        new Error(
          `the sidecar announced no readiness within ${timeoutMs} ms: ${boundedDiagnostic(stderr, [credential])}`,
        ),
      );
    }, timeoutMs);

    stdout.on("data", onData);
    child.once("exit", onExit);
    child.once("error", onError);
    if (hasExited(child)) {
      onExit(child.exitCode);
    }
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
    if (hasExited(child)) {
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

function processExists(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function taskkillTree(pid: number): void {
  const terminated = spawnSync("taskkill", ["/PID", String(pid), "/T", "/F"], {
    stdio: "ignore",
    timeout: FORCED_SHUTDOWN_TIMEOUT_MS,
    windowsHide: true,
  });
  if ((terminated.error !== undefined || terminated.status !== 0) && processExists(pid)) {
    throw new Error("the Windows sidecar process tree could not be terminated");
  }
}

/** Find descendants by their recorded parent IDs even when the root has already exited. */
function windowsDescendants(rootPid: number): number[] {
  const script = [
    `$processes = @(Get-CimInstance Win32_Process);`,
    `$found = @();`,
    `$parents = @(${rootPid});`,
    `while ($parents.Count -gt 0) {`,
    `  $next = @();`,
    `  foreach ($parent in $parents) {`,
    `    foreach ($child in @($processes | Where-Object { $_.ParentProcessId -eq $parent })) {`,
    `      if ($found -notcontains $child.ProcessId) {`,
    `        $found += $child.ProcessId; $next += $child.ProcessId;`,
    `      }`,
    `    }`,
    `  }`,
    `  $parents = @($next);`,
    `}`,
    `[Console]::Out.Write($found -join ',');`,
  ].join(" ");
  const listed = spawnSync(
    "powershell.exe",
    ["-NoProfile", "-NonInteractive", "-Command", script],
    { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"], timeout: FORCED_SHUTDOWN_TIMEOUT_MS, windowsHide: true },
  );
  if (listed.error !== undefined || listed.status !== 0) {
    throw new Error("the exited Windows sidecar's descendants could not be inspected");
  }
  return listed.stdout
    .split(",")
    .filter((value) => /^\d+$/.test(value))
    .map((value) => Number(value));
}

/** Force the whole spawned tree, not only a Windows venv launcher or POSIX direct child. */
function terminateProcessTree(child: ChildProcess): void {
  if (child.pid === undefined) {
    return;
  }
  const pid = child.pid;
  if (process.platform === "win32") {
    if (processExists(pid)) {
      taskkillTree(pid);
    } else {
      // taskkill /T needs a living root. ParentProcessId still names the exited launcher, so
      // an early root exit cannot strand the real Python server (or a test's grandchild).
      for (const descendant of windowsDescendants(pid)) {
        taskkillTree(descendant);
      }
    }
    return;
  }

  try {
    // Non-Windows children are spawned as process-group leaders, so descendants are contained
    // even when the direct child has already exited but its group still has members.
    process.kill(-pid, "SIGKILL");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ESRCH") {
      return;
    }
    if (!hasExited(child)) {
      child.kill("SIGKILL");
    }
    if (processExists(pid)) {
      throw new Error("the sidecar process group could not be terminated");
    }
  }
}

/** Terminate and boundedly reap, always closing every stdio handle. */
async function terminateAndReap(child: ChildProcess): Promise<number> {
  if (child.pid === undefined) {
    closeStdio(child);
    return -1;
  }

  const failures: unknown[] = [];
  let code = -1;
  try {
    terminateProcessTree(child);
  } catch (error) {
    failures.push(error);
  }
  try {
    code = await waitForExit(child, FORCED_SHUTDOWN_TIMEOUT_MS);
  } catch (error) {
    failures.push(error);
  } finally {
    closeStdio(child);
  }
  if (failures.length > 0) {
    throw containedError(new Error("the sidecar could not be terminated and reaped"), failures);
  }
  return code;
}

/** Whether a real HTTP server still answers, rather than whether TCP merely connects. */
export async function apiIsServing(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (serving: boolean) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      resolve(serving);
    };
    const request = httpRequest(
      {
        host: "127.0.0.1",
        port,
        path: "/api/v1/health",
        method: "GET",
        agent: false,
        headers: { Connection: "close" },
      },
      (response) => {
        response.destroy();
        finish(true);
      },
    );
    const timer = setTimeout(() => {
      request.destroy();
      finish(false);
    }, LISTENER_CHECK_TIMEOUT_MS);
    request.on("error", () => finish(false));
    request.end();
  });
}

async function assertPortNotServing(port: number): Promise<void> {
  if (await apiIsServing(port)) {
    throw new Error("the sidecar API listener is still serving");
  }
}

/** Independently verify the listener after graceful or forced session cleanup. */
export async function assertSidecarNotServing(
  session: Pick<SidecarSession, "port">,
): Promise<void> {
  await assertPortNotServing(session.port);
}

async function forceContainment(
  child: ChildProcess,
  port: number | undefined,
): Promise<{ readonly code: number; readonly failures: readonly unknown[] }> {
  const failures: unknown[] = [];
  let code = -1;
  try {
    code = await terminateAndReap(child);
  } catch (error) {
    failures.push(error);
  }
  if (port !== undefined) {
    try {
      await assertPortNotServing(port);
    } catch (error) {
      failures.push(error);
    }
  }
  return { code, failures };
}

function parseReadiness(line: string): Readiness {
  let value: unknown;
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

/** Recover only a loopback port from an otherwise invalid record; never contact another host. */
function announcedLoopbackPort(line: string | undefined): number | undefined {
  if (line === undefined) {
    return undefined;
  }
  try {
    const value = JSON.parse(line) as Partial<Readiness> | null;
    if (
      value !== null &&
      value.host === "127.0.0.1" &&
      typeof value.port === "number" &&
      Number.isInteger(value.port) &&
      value.port > 0 &&
      value.port <= 65535
    ) {
      return value.port;
    }
  } catch {
    // Malformed JSON announces no address the harness can safely verify.
  }
  return undefined;
}

/** Start one real secured sidecar and wait for the port it actually bound. */
export async function startSidecar(options: SidecarStartOptions = {}): Promise<SidecarSession> {
  const executable = options.launch?.executable ?? pythonExecutable();
  if (!existsSync(executable)) {
    throw new Error(
      "the locked Python environment is missing; run `uv sync --frozen` in python/ first",
    );
  }

  const credential = options.credential ?? randomBytes(32).toString("base64url");
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
    [...(options.launch?.args ?? ["-m", "dynamisbench", "api", "serve"])],
    {
      cwd: repositoryRoot(),
      env: environment,
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
      detached: process.platform !== "win32",
    },
  );

  // A child can exit between the state check and a shutdown write. Keep that late EPIPE from
  // becoming an uncaught stream error; stop still waits or force-contains within its deadline.
  child.stdin?.on("error", () => undefined);

  let line: string | undefined;
  let readiness: Readiness | undefined;
  try {
    options.onSpawn?.(child);
    line = await firstLine(child, options.readinessTimeoutMs ?? READINESS_TIMEOUT_MS, credential);
    readiness = parseReadiness(line);
  } catch (error) {
    const port = readiness?.port ?? announcedLoopbackPort(line);
    const contained = await forceContainment(child, port);
    throw containedError(error, contained.failures, [credential]);
  }

  const origin = `http://${readiness.host}:${readiness.port}`;
  const port = readiness.port;
  return {
    origin,
    port,
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
      try {
        const stdin = child.stdin;
        if (!hasExited(child) && stdin !== null) {
          stdin.write(`${SHUTDOWN_RECORD}\n`);
          stdin.end();
        }
        const code = await waitForExit(child, SHUTDOWN_TIMEOUT_MS);
        closeStdio(child);
        await assertPortNotServing(port);
        return code;
      } catch (error) {
        const contained = await forceContainment(child, port);
        throw containedError(error, contained.failures, [credential]);
      }
    },
    async kill() {
      const contained = await forceContainment(child, port);
      if (contained.failures.length > 0) {
        throw containedError(new Error("the sidecar could not be contained"), contained.failures, [credential]);
      }
      return contained.code;
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
