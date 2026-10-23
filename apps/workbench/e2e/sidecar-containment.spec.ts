/**
 * Failure-injection gates for the real-process Playwright sidecar harness.
 *
 * The launch override is test-only. The processes, pipes, exits and (where applicable) HTTP
 * listeners are real, so a rejected startup must still prove OS-level containment.
 */

import { spawnSync, type ChildProcess } from "node:child_process";
import { once } from "node:events";

import { expect, test } from "@playwright/test";

import { repositoryRoot } from "./support/paths";
import { apiIsServing, startSidecar, type SidecarStartOptions } from "./support/sidecar";

function startScript(
  script: string,
  options: Omit<SidecarStartOptions, "launch"> = {},
): ReturnType<typeof startSidecar> {
  return startSidecar({
    ...options,
    launch: { executable: process.execPath, args: ["-e", script] },
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

function processExists(pid: number | undefined): boolean {
  if (pid === undefined) {
    return false;
  }
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

function expectReaped(child: ChildProcess | undefined): void {
  expect(child).toBeDefined();
  expect(processExists(child?.pid)).toBe(false);
  expect(child?.stdin?.destroyed ?? true).toBe(true);
  expect(child?.stdout?.destroyed ?? true).toBe(true);
  expect(child?.stderr?.destroyed ?? true).toBe(true);
}

/** A test-last safety net; assertions above must prove that the harness already did this. */
function forceCleanup(child: ChildProcess | undefined): void {
  if (child?.pid === undefined) {
    return;
  }
  if (process.platform === "win32") {
    if (processExists(child.pid)) {
      spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" });
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
    expect(processExists(descendantPid)).toBe(false);
    expect(port).toBeDefined();
    expect(await apiIsServing(port ?? 0)).toBe(false);
  } finally {
    forceCleanup(child);
    if (descendantPid !== undefined && processExists(descendantPid)) {
      if (process.platform === "win32") {
        spawnSync("taskkill", ["/PID", String(descendantPid), "/T", "/F"], { stdio: "ignore" });
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
    expect(processExists(descendantPid)).toBe(false);
    expect(await apiIsServing(record.port)).toBe(false);
  } finally {
    forceCleanup(child);
    if (descendantPid !== undefined && processExists(descendantPid)) {
      if (process.platform === "win32") {
        spawnSync("taskkill", ["/PID", String(descendantPid), "/T", "/F"], { stdio: "ignore" });
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
