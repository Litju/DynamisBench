/**
 * Failure-injection gates for the real-process Playwright sidecar harness.
 *
 * The launch override is test-only. The processes, pipes, exits and (where applicable) HTTP
 * listeners are real, so a rejected startup must still prove OS-level containment.
 */

import { spawnSync, type ChildProcess } from "node:child_process";
import { once } from "node:events";
import { readFileSync } from "node:fs";
import { createServer, type AddressInfo, type Socket } from "node:net";

import { expect, test } from "@playwright/test";

import { pythonExecutable, repositoryRoot } from "./support/paths";
import {
  apiIsServing,
  processExists,
  startSidecar,
  type SidecarStartOptions,
} from "./support/sidecar";

function startScript(
  script: string,
  options: Omit<SidecarStartOptions, "launch"> = {},
): ReturnType<typeof startSidecar> {
  return startSidecar({
    ...options,
    launch: { executable: process.execPath, args: ["-e", script] },
  });
}

function startPythonScript(
  script: string,
  options: Omit<SidecarStartOptions, "launch"> = {},
): ReturnType<typeof startSidecar> {
  return startSidecar({
    ...options,
    launch: { executable: pythonExecutable(), args: ["-c", script] },
  });
}

async function rejectionOf(promise: Promise<unknown>): Promise<Error> {
  try {
    await promise;
  } catch (error) {
    expect(error).toBeInstanceOf(Error);
    return error as Error;
  }
  throw new Error("the operation was expected to reject");
}

const PROCESS_GONE_TIMEOUT_MS = 5_000;
const LIVENESS_PROBE_INTERVAL_MS = 25;

/**
 * The `/proc/<pid>/stat` state, or undefined when there is no such task.
 *
 * The command field may contain spaces and parentheses, so the state follows the last `)`.
 */
function linuxProcessState(pid: number): string | undefined {
  let stat: string;
  try {
    stat = readFileSync(`/proc/${pid}/stat`, "utf8");
  } catch {
    return undefined;
  }
  const commandEnd = stat.lastIndexOf(")");
  if (commandEnd === -1) {
    return undefined;
  }
  return stat.slice(commandEnd + 2, commandEnd + 3) || undefined;
}

/**
 * Whether the PID still names a task that can run.
 *
 * A killed Linux orphan stays visible to `kill(pid, 0)` as a `Z`/`X` task until it is reaped.
 * It has already released the listener and can never run again, so it is not a live descendant.
 * Everything else delegates to the fail-closed probe: only `ESRCH` proves absence.
 */
function processIsAlive(pid: number | undefined): boolean {
  if (pid === undefined) {
    return false;
  }
  if (process.platform === "linux") {
    const state = linuxProcessState(pid);
    if (state !== undefined) {
      return state !== "Z" && state !== "X" && state !== "x";
    }
  }
  return processExists(pid);
}

/** Allow Linux signal delivery and reparenting to settle, but fail if the task can still run. */
async function expectProcessGone(pid: number | undefined): Promise<void> {
  expect(pid).toBeDefined();
  if (pid === undefined) {
    return;
  }
  if (process.platform !== "linux") {
    expect(processIsAlive(pid)).toBe(false);
    return;
  }
  await expect
    .poll(() => processIsAlive(pid), {
      message: `PID ${pid} is still a live process`,
      timeout: PROCESS_GONE_TIMEOUT_MS,
      intervals: [LIVENESS_PROBE_INTERVAL_MS],
    })
    .toBe(false);
}

function probeError(code: string): NodeJS.ErrnoException {
  const error = new Error(`injected ${code}`) as NodeJS.ErrnoException;
  error.code = code;
  return error;
}

test("harness: only an ESRCH probe proves that a PID is gone", () => {
  const pid = 424_242;
  const probed: number[] = [];

  // A successful probe, including a negative PID that names a POSIX process group, is present.
  expect(processExists(pid, (candidate) => { probed.push(candidate); })).toBe(true);
  expect(processExists(-pid, (candidate) => { probed.push(candidate); })).toBe(true);
  expect(probed).toEqual([pid, -pid]);

  // ESRCH is the only error that proves absence.
  expect(processExists(pid, () => { throw probeError("ESRCH"); })).toBe(false);

  // An uncertain probe must never be mistaken for a dead process.
  expect(processExists(pid, () => { throw probeError("EPERM"); })).toBe(true);
  expect(processExists(pid, () => { throw probeError("EINVAL"); })).toBe(true);
});

function expectReaped(child: ChildProcess | undefined): void {
  expect(child).toBeDefined();
  expect(processIsAlive(child?.pid)).toBe(false);
  expect(child?.stdin?.destroyed ?? true).toBe(true);
  expect(child?.stdout?.destroyed ?? true).toBe(true);
  expect(child?.stderr?.destroyed ?? true).toBe(true);
}

const TEST_TASKKILL_TIMEOUT_MS = 5_000;

function taskkillTree(pid: number): void {
  spawnSync("taskkill", ["/PID", String(pid), "/T", "/F"], {
    stdio: "ignore",
    timeout: TEST_TASKKILL_TIMEOUT_MS,
    windowsHide: true,
  });
}

/** A test-last safety net; assertions above must prove that the harness already did this. */
function forceCleanup(child: ChildProcess | undefined): void {
  if (child?.pid === undefined) {
    return;
  }
  if (process.platform === "win32") {
    if (processIsAlive(child.pid)) {
      taskkillTree(child.pid);
    }
  } else {
    try {
      process.kill(-child.pid, "SIGKILL");
    } catch {
      // The process group is already gone.
    }
  }
  child.stdin?.destroy();
  child.stdout?.destroy();
  child.stderr?.destroy();
}

test("harness: a hanging non-HTTP loopback listener still counts as serving", async () => {
  const connections = new Set<Socket>();
  const server = createServer((socket) => {
    connections.add(socket);
    socket.once("close", () => connections.delete(socket));
  });
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => resolve());
  });
  const address = server.address() as AddressInfo;
  try {
    expect(await apiIsServing(address.port)).toBe(true);
  } finally {
    for (const connection of connections) {
      connection.destroy();
    }
    await new Promise<void>((resolve) => { server.close(() => resolve()); });
  }
});

test("harness: an early child exit is reaped and its diagnostics are safe", async () => {
  const credential = "S".repeat(43);
  let child: ChildProcess | undefined;
  const error = await rejectionOf(
    startScript(
      [
        `process.stderr.write(process.env.DYNAMISBENCH_SESSION_TOKEN + "\\n" + process.cwd() + "\\n",`,
        `  () => process.exit(23));`,
      ].join("\n"),
      { credential, onSpawn: (spawned) => { child = spawned; } },
    ),
  );

  expect(error.message).toContain("exited before readiness (code 23)");
  expect(error.message).not.toContain(credential);
  expect(error.message).not.toContain(repositoryRoot());
  expect(error.message.length).toBeLessThanOrEqual(500);
  expectReaped(child);
});

test("harness: malformed readiness after spawn terminates and reaps the child", async () => {
  let child: ChildProcess | undefined;
  try {
    const error = await rejectionOf(
      startScript(`console.log("not-json"); setInterval(() => {}, 1000);`, {
        onSpawn: (spawned) => { child = spawned; },
      }),
    );

    expect(error.message).toContain("readiness record was not JSON");
    expectReaped(child);
  } finally {
    forceCleanup(child);
  }
});

test("harness: an unterminated oversized readiness line is bounded and contained", async () => {
  let child: ChildProcess | undefined;
  try {
    const error = await rejectionOf(
      startScript(`process.stdout.write("x".repeat(16384)); setInterval(() => {}, 1000);`, {
        readinessTimeoutMs: 5_000,
        onSpawn: (spawned) => { child = spawned; },
      }),
    );

    expect(error.message).toContain("readiness line exceeded");
    expectReaped(child);
  } finally {
    forceCleanup(child);
  }
});

test("harness: early root exit cannot strand a descendant listener", async () => {
  const grandchildScript = [
    `const server = require("node:http").createServer((request, response) => {`,
    `  response.writeHead(200); response.end("serving");`,
    `});`,
    `server.listen(0, "127.0.0.1", () => process.send({ port: server.address().port, pid: process.pid }));`,
  ].join("\n");
  const parentScript = [
    `const { spawn } = require("node:child_process");`,
    `const descendant = spawn(process.execPath, ["-e", ${JSON.stringify(grandchildScript)}], { stdio: ["ignore", "ignore", "ignore", "ipc"] });`,
    `descendant.once("message", ({ port, pid }) => {`,
    `  process.stderr.write("descendant=" + pid + ",port=" + port + "\\n", () => process.exit(24));`,
    `});`,
  ].join("\n");

  let child: ChildProcess | undefined;
  let descendantPid: number | undefined;
  let port: number | undefined;
  let stderr = "";
  let described!: () => void;
  const description = new Promise<void>((resolve) => { described = resolve; });
  try {
    const error = await rejectionOf(
      startScript(parentScript, {
        onSpawn: (spawned) => {
          child = spawned;
          spawned.stderr?.on("data", (chunk: Buffer) => {
            stderr += chunk.toString("utf8");
            const match = /descendant=(\d+),port=(\d+)/.exec(stderr);
            if (match !== null) {
              descendantPid = Number(match[1]);
              port = Number(match[2]);
              described();
            }
          });
        },
      }),
    );
    await description;

    expect(error.message).toContain("exited before readiness (code 24)");
    expectReaped(child);
    await expectProcessGone(descendantPid);
    expect(port).toBeDefined();
    expect(await apiIsServing(port ?? 0)).toBe(false);
  } finally {
    forceCleanup(child);
    if (descendantPid !== undefined && processIsAlive(descendantPid)) {
      if (process.platform === "win32") {
        taskkillTree(descendantPid);
      } else {
        try { process.kill(descendantPid, "SIGKILL"); } catch { /* already gone */ }
      }
    }
  }
});

test("harness: forced kill contains the whole tree and waits for it to exit", async () => {
  const grandchildScript = [
    `const server = require("node:http").createServer((request, response) => {`,
    `  response.writeHead(200); response.end("serving");`,
    `});`,
    `server.listen(0, "127.0.0.1", () => process.send({ port: server.address().port, pid: process.pid }));`,
  ].join("\n");
  const parentScript = [
    `const { spawn } = require("node:child_process");`,
    `const descendant = spawn(process.execPath, ["-e", ${JSON.stringify(grandchildScript)}], { stdio: ["ignore", "ignore", "ignore", "ipc"] });`,
    `descendant.once("message", ({ port, pid }) => {`,
    `  console.log(JSON.stringify({ kind: "dynamisbench.api.ready", protocol_version: 1, api_version: "v1", host: "127.0.0.1", port, descendant: pid }));`,
    `});`,
    `setInterval(() => {}, 1000);`,
  ].join("\n");

  let descendantPid: number | undefined;
  let announced = "";
  const session = await startScript(parentScript, {
    onSpawn: (spawned) => {
      spawned.stdout?.on("data", (chunk: Buffer) => { announced += chunk.toString("utf8"); });
    },
  });
  try {
    const record = JSON.parse(announced.split("\n")[0] ?? "") as {
      port: number;
      descendant: number;
    };
    descendantPid = record.descendant;
    expect(await apiIsServing(record.port)).toBe(true);
    expect(processIsAlive(descendantPid)).toBe(true);

    // kill resolves only after the tree is verified gone; a descendant the signal had not
    // reached yet would make this a containment failure, not a silent success.
    await session.kill();

    expectReaped(session.process);
    await expectProcessGone(descendantPid);
    expect(await apiIsServing(record.port)).toBe(false);
  } finally {
    await session.kill().catch(() => undefined);
    forceCleanup(session.process);
    if (descendantPid !== undefined && processIsAlive(descendantPid)) {
      if (process.platform === "win32") {
        taskkillTree(descendantPid);
      } else {
        try { process.kill(descendantPid, "SIGKILL"); } catch { /* already gone */ }
      }
    }
  }
});

test("harness: a readiness timeout terminates and reaps the child", async () => {
  let child: ChildProcess | undefined;
  try {
    const error = await rejectionOf(
      startScript(`setInterval(() => {}, 1000);`, {
        readinessTimeoutMs: 100,
        onSpawn: (spawned) => { child = spawned; },
      }),
    );

    expect(error.message).toContain("announced no readiness within 100 ms");
    expectReaped(child);
  } finally {
    forceCleanup(child);
  }
});

test("harness: invalid readiness contains the spawned tree and its real listener", async () => {
  const grandchildScript = [
    `const server = require("node:http").createServer((request, response) => {`,
    `  response.writeHead(200); response.end("serving");`,
    `});`,
    `server.listen(0, "127.0.0.1", () => process.send({ port: server.address().port, pid: process.pid }));`,
  ].join("\n");
  const parentScript = [
    `const { spawn } = require("node:child_process");`,
    `const descendant = spawn(process.execPath, ["-e", ${JSON.stringify(grandchildScript)}], { stdio: ["ignore", "ignore", "ignore", "ipc"] });`,
    `descendant.once("message", ({ port, pid }) => {`,
    `  console.log(JSON.stringify({ kind: "dynamisbench.api.ready", protocol_version: 2, api_version: "v1", host: "127.0.0.1", port, descendant: pid }));`,
    `});`,
  ].join("\n");

  let child: ChildProcess | undefined;
  let descendantPid: number | undefined;
  let announced = "";
  try {
    const error = await rejectionOf(
      startScript(parentScript, {
        onSpawn: (spawned) => {
          child = spawned;
          spawned.stdout?.on("data", (chunk: Buffer) => { announced += chunk.toString("utf8"); });
        },
      }),
    );

    expect(error.message).toContain("readiness record did not match protocol v1");
    const record = JSON.parse(announced.split("\n")[0] ?? "") as {
      port: number;
      descendant: number;
    };
    descendantPid = record.descendant;
    expectReaped(child);
    await expectProcessGone(descendantPid);
    expect(await apiIsServing(record.port)).toBe(false);
  } finally {
    forceCleanup(child);
    if (descendantPid !== undefined && processIsAlive(descendantPid)) {
      if (process.platform === "win32") {
        taskkillTree(descendantPid);
      } else {
        try { process.kill(descendantPid, "SIGKILL"); } catch { /* already gone */ }
      }
    }
  }
});

test("harness: malformed Python readiness recovers its port and contains the child listener", async () => {
  const grandchildScript = [
    "import json, os, socket, sys, time",
    "server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)",
    "server.bind(('127.0.0.1', 0))",
    "server.listen()",
    "print(json.dumps({'port': server.getsockname()[1], 'pid': os.getpid()}), flush=True)",
    "while True:",
    "    time.sleep(3600)",
  ].join("\n");
  const parentScript = [
    "import json, socket, subprocess, sys, time",
    `child = subprocess.Popen([sys.executable, "-c", ${JSON.stringify(grandchildScript)}], stdout=subprocess.PIPE, text=True)`,
    "record = json.loads(child.stdout.readline())",
    "with socket.create_connection(('127.0.0.1', record['port']), timeout=2):",
    "    pass",
    `sys.stdout.write('{"host":"127.0.0.1","port":' + str(record['port']) + ',"descendant":' + str(record['pid']) + ',"kind":\\n')`,
    "sys.stdout.flush()",
    "while True:",
    "    time.sleep(3600)",
  ].join("\n");

  let child: ChildProcess | undefined;
  let descendantPid: number | undefined;
  let announced = "";
  try {
    const error = await rejectionOf(
      startPythonScript(parentScript, {
        onSpawn: (spawned) => {
          child = spawned;
          spawned.stdout?.on("data", (chunk: Buffer) => { announced += chunk.toString("utf8"); });
        },
      }),
    );

    expect(error.message).toContain("readiness record was not JSON");
    const match = /"port":(\d+),"descendant":(\d+)/.exec(announced);
    expect(match).not.toBeNull();
    if (match === null) {
      return;
    }
    const port = Number(match[1]);
    descendantPid = Number(match[2]);
    expectReaped(child);
    await expectProcessGone(descendantPid);
    expect(await apiIsServing(port)).toBe(false);
  } finally {
    forceCleanup(child);
    if (descendantPid !== undefined && processIsAlive(descendantPid)) {
      if (process.platform === "win32") {
        taskkillTree(descendantPid);
      } else {
        try { process.kill(descendantPid, "SIGKILL"); } catch { /* already gone */ }
      }
    }
  }
});

test("harness: unexpected child termination and repeated cleanup leave no listener", async () => {
  const script = [
    `const server = require("node:http").createServer((request, response) => {`,
    `  response.writeHead(200); response.end("serving");`,
    `});`,
    `server.listen(0, "127.0.0.1", () => console.log(JSON.stringify({`,
    `  kind: "dynamisbench.api.ready", protocol_version: 1, api_version: "v1",`,
    `  host: "127.0.0.1", port: server.address().port`,
    `})));`,
  ].join("\n");
  const session = await startScript(script);
  try {
    expect(session.process.stderr?.listenerCount("data")).toBe(0);
    expect(await apiIsServing(session.port)).toBe(true);
    const exited = once(session.process, "exit");
    session.process.kill("SIGKILL");
    await exited;

    await session.stop();
    await session.stop();
    await session.kill();
    await session.kill();

    expectReaped(session.process);
    expect(await apiIsServing(session.port)).toBe(false);
  } finally {
    await session.kill().catch(() => undefined);
  }
});
