import { EventEmitter } from "node:events";
import { spawn as spawnChild } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  PythonRuntime,
  RuntimeBoundaryError,
  resolvePythonLaunch,
} from "../src/python-runtime";
import {
  DesktopPreferences,
  DEFAULT_DESKTOP_PREFERENCES,
} from "../src/desktop-preferences";

class FakeChild extends EventEmitter {
  readonly pid = 4242;
  readonly writes: string[] = [];
  killed = false;
  killResult = true;
  emitCloseOnKill = true;
  killCloseDelayMs = 0;
  readonly killSignals: Array<NodeJS.Signals | undefined> = [];
  private closed = false;
  readonly stdin = {
    write: (value: string) => {
      this.writes.push(value);
      return true;
    },
    end: () => {
      this.emitClose(0, null);
    },
    once: () => this.stdin,
  };
  readonly stdout = new EventEmitter();
  readonly stderr = new EventEmitter();

  kill(signal?: NodeJS.Signals) {
    this.killSignals.push(signal);
    this.killed = true;
    if (!this.killResult) return false;
    if (this.emitCloseOnKill) {
      const close = () => {
        this.emit("exit", null, signal ?? "SIGTERM");
        this.emitClose(null, signal ?? "SIGTERM");
      };
      if (this.killCloseDelayMs > 0) setTimeout(close, this.killCloseDelayMs);
      else close();
    }
    return true;
  }

  private emitClose(code: number | null, signal: NodeJS.Signals | null): void {
    if (this.closed) return;
    this.closed = true;
    this.emit("close", code, signal);
  }
}

function response(id: string, result: unknown): string {
  return `${JSON.stringify({ id, ok: true, result, type: "response" })}\n`;
}

function requestId(child: FakeChild): string {
  const envelope = JSON.parse(child.writes.at(-1) ?? "{}");
  return envelope.id;
}

test("development and production launches have explicit, non-shell commands", () => {
  assert.deepEqual(
    resolvePythonLaunch({ mode: "development", pythonExecutable: "C:\\conda\\envs\\re-uthcode\\python.exe" }),
    {
      command: "C:\\conda\\envs\\re-uthcode\\python.exe",
      args: ["-m", "uthcode.interfaces.desktop"],
    },
  );
  assert.deepEqual(
    resolvePythonLaunch({ mode: "production", resourcesPath: "C:\\Program Files\\UthCode\\resources" }),
    {
      command: "C:\\Program Files\\UthCode\\resources\\uthcode-runtime\\uthcode-desktop-runtime.exe",
      args: [],
    },
  );
  assert.throws(
    () => resolvePythonLaunch({ mode: "production", resourcesPath: "C:\\resources", platform: "win32", runtimeExecutable: "python.exe" }),
    /bundled Runtime/,
  );
});

test("Python child uses piped stdio and correlates responses and events", async () => {
  const child = new FakeChild();
  const spawnCalls: unknown[] = [];
  const events: unknown[] = [];
  const diagnostics: string[] = [];
  const runtime = new PythonRuntime({
    launch: { command: "C:\\conda\\python.exe", args: ["-m", "uthcode.interfaces.desktop"] },
    spawn: ((...args: unknown[]) => {
      spawnCalls.push(args);
      return child;
    }) as never,
    requestTimeoutMs: 100,
    onAgentEvent: (event) => events.push(event),
    onDiagnostic: (line) => diagnostics.push(line),
  });

  await runtime.start();
  assert.equal(child.pid, runtime.pid);
  assert.deepEqual(spawnCalls[0], [
    "C:\\conda\\python.exe",
    ["-m", "uthcode.interfaces.desktop"],
    { shell: false, stdio: ["pipe", "pipe", "pipe"], windowsHide: true },
  ]);

  const resultPromise = runtime.request("status.get", {});
  const id = requestId(child);
  child.stdout.emit("data", `${JSON.stringify({ type: "agent_event", event: { type: "agent_delta", text: "hi" } })}\n`);
  child.stderr.emit("data", "bridge diagnostic\n");
  child.stdout.emit("data", response(id, { state: "ready" }));
  assert.deepEqual(await resultPromise, { state: "ready" });
  assert.deepEqual(events, [{ type: "agent_delta", text: "hi" }]);
  assert.deepEqual(diagnostics, ["bridge diagnostic"]);
});

test("timeout, malformed output, and unexpected exit reject pending requests as runtime errors", async () => {
  const child = new FakeChild();
  const runtime = new PythonRuntime({
    launch: { command: "python.exe", args: [] },
    spawn: (() => child) as never,
    requestTimeoutMs: 15,
  });
  await runtime.start();

  await assert.rejects(runtime.request("status.get", {}), (error: unknown) => {
    return error instanceof RuntimeBoundaryError && error.kind === "request_timeout";
  });

  const malformed = runtime.request("status.get", {});
  child.stdout.emit("data", "not-json\n");
  await assert.rejects(malformed, (error: unknown) => {
    return error instanceof RuntimeBoundaryError && error.kind === "malformed_response";
  });

  const exitChild = new FakeChild();
  const exitRuntime = new PythonRuntime({
    launch: { command: "python.exe", args: [] },
    spawn: (() => exitChild) as never,
  });
  await exitRuntime.start();
  const exited = exitRuntime.request("status.get", {});
  exitChild.emit("exit", 17, null);
  await assert.rejects(exited, (error: unknown) => {
    return error instanceof RuntimeBoundaryError && error.kind === "process_exit";
  });
});

test("malformed output and process error cannot replace a still-live child", async () => {
  const malformedChild = new FakeChild();
  const malformedReplacement = new FakeChild();
  let malformedSpawns = 0;
  const malformedRuntime = new PythonRuntime({
    launch: { command: "python.exe", args: [] },
    spawn: (() => malformedSpawns++ === 0 ? malformedChild : malformedReplacement) as never,
  });
  await malformedRuntime.start();
  const malformedRequest = malformedRuntime.request("status.get", {});
  malformedChild.stdout.emit("data", "not-json\n");
  await assert.rejects(malformedRequest, (error: unknown) => {
    return error instanceof RuntimeBoundaryError && error.kind === "malformed_response";
  });
  assert.equal(malformedRuntime.state, "failed");
  await assert.rejects(malformedRuntime.start(), (error: unknown) => {
    return error instanceof RuntimeBoundaryError && error.kind === "process_error";
  });
  assert.equal(malformedSpawns, 1);
  malformedChild.emit("close", null, null);
  await malformedRuntime.start();
  assert.equal(malformedSpawns, 2);

  const errorChild = new FakeChild();
  const errorReplacement = new FakeChild();
  let errorSpawns = 0;
  const errorStates: string[] = [];
  const errorRuntime = new PythonRuntime({
    launch: { command: "python.exe", args: [] },
    spawn: (() => errorSpawns++ === 0 ? errorChild : errorReplacement) as never,
    onRuntimeState: (state) => errorStates.push(state),
  });
  await errorRuntime.start();
  errorChild.emit("error", new Error("native process detail"));
  assert.equal(errorRuntime.state, "failed");
  assert.deepEqual(errorStates, ["failed"]);
  await assert.rejects(errorRuntime.start(), (error: unknown) => {
    return error instanceof RuntimeBoundaryError && error.kind === "process_error";
  });
  assert.equal(errorSpawns, 1);
  errorChild.emit("close", null, null);
  await errorRuntime.start();
  assert.equal(errorSpawns, 2);

  const stateChild = new FakeChild();
  const stateReplacement = new FakeChild();
  let stateSpawns = 0;
  const stateRuntime = new PythonRuntime({
    launch: { command: "python.exe", args: [] },
    spawn: (() => stateSpawns++ === 0 ? stateChild : stateReplacement) as never,
  });
  await stateRuntime.start();
  stateChild.stdout.emit(
    "data",
    `${JSON.stringify({ type: "runtime_state", state: "failed", error: { kind: "runtime", message: "failed" } })}\n`,
  );
  assert.equal(stateRuntime.state, "failed");
  await assert.rejects(stateRuntime.start(), /child must be closed/);
  assert.equal(stateSpawns, 1);
  stateChild.emit("close", null, null);
  await stateRuntime.start();
  assert.equal(stateSpawns, 2);
});

test("shutdown requests the Bridge, closes stdin, and force-reaps a stuck child", async () => {
  const child = new FakeChild();
  const runtime = new PythonRuntime({
    launch: { command: "python.exe", args: [] },
    spawn: (() => child) as never,
    requestTimeoutMs: 100,
    shutdownTimeoutMs: 20,
  });
  await runtime.start();

  const shutdown = runtime.shutdown();
  const id = requestId(child);
  child.stdout.emit("data", response(id, { state: "stopped" }));
  await shutdown;
  assert.equal(child.writes.some((line) => JSON.parse(line).method === "runtime.shutdown"), true);
  assert.equal(child.killed, false);
  assert.equal(runtime.state, "stopped");

  const stuck = new FakeChild();
  stuck.stdin.end = () => undefined;
  const stuckRuntime = new PythonRuntime({
    launch: { command: "python.exe", args: [] },
    spawn: (() => stuck) as never,
    requestTimeoutMs: 1_000,
    shutdownTimeoutMs: 10,
  });
  await stuckRuntime.start();
  const startedAt = Date.now();
  const stuckShutdown = stuckRuntime.shutdown();
  await stuckShutdown;
  assert.ok(Date.now() - startedAt < 500);
  assert.equal(stuck.killed, true);
  assert.deepEqual(stuck.killSignals, ["SIGTERM"]);
  assert.equal(stuckRuntime.state, "stopped");
});

test("shutdown reports an unconfirmed kill and retains child ownership", async () => {
  const child = new FakeChild();
  child.stdin.end = () => undefined;
  child.killResult = false;
  child.emitCloseOnKill = false;
  const runtime = new PythonRuntime({
    launch: { command: "python.exe", args: [] },
    spawn: (() => child) as never,
    requestTimeoutMs: 10,
    shutdownTimeoutMs: 10,
  });
  await runtime.start();
  const startedAt = Date.now();
  await assert.rejects(runtime.shutdown(), (error: unknown) => {
    return error instanceof RuntimeBoundaryError && error.kind === "shutdown_timeout";
  });
  assert.ok(Date.now() - startedAt < 250);
  assert.equal(runtime.state, "failed");
  assert.equal(runtime.pid, child.pid);
  assert.deepEqual(child.killSignals, ["SIGTERM", "SIGKILL"]);
  await assert.rejects(runtime.start(), /child must be closed/);
});

test("shutdown accepts a delayed close only after the bounded terminate window", async () => {
  const child = new FakeChild();
  child.stdin.end = () => undefined;
  child.killCloseDelayMs = 5;
  const runtime = new PythonRuntime({
    launch: { command: "python.exe", args: [] },
    spawn: (() => child) as never,
    requestTimeoutMs: 10,
    shutdownTimeoutMs: 20,
  });
  await runtime.start();
  await runtime.shutdown();
  assert.deepEqual(child.killSignals, ["SIGTERM"]);
  assert.equal(runtime.pid, undefined);
  assert.equal(runtime.state, "stopped");
});

test("forced shutdown removes the PID of an actual child process", async () => {
  const runtime = new PythonRuntime({
    launch: {
      command: process.execPath,
      args: ["-e", "setInterval(() => {}, 60000)"],
    },
    spawn: spawnChild as never,
    requestTimeoutMs: 20,
    shutdownTimeoutMs: 20,
  });
  await runtime.start();
  const pid = runtime.pid;
  assert.ok(pid);
  await runtime.shutdown();
  let alive = true;
  try {
    process.kill(pid, 0);
  } catch {
    alive = false;
  }
  assert.equal(alive, false);
  assert.equal(runtime.state, "stopped");
});

test("desktop preferences persist only allowlisted UI metadata", async () => {
  const root = await mkdtemp(join(tmpdir(), "uthcode-preferences-"));
  const file = join(root, "preferences.json");
  try {
    const preferences = new DesktopPreferences(file);
    assert.deepEqual(await preferences.read(), DEFAULT_DESKTOP_PREFERENCES);
    await preferences.write("theme", "dark");
    await preferences.write("selectedProjectKey", "C:\\Projects\\UthCode");
    await preferences.write("recentProjects", [
      { path: "C:\\Projects\\UthCode", alias: "Work", pinned: true },
    ]);
    const raw = await readFile(file, "utf8");
    assert.equal(raw.includes("api-key"), false);
    assert.deepEqual((await preferences.read()).theme, "dark");
    await assert.rejects(
      preferences.write("apiKey" as never, "fake-key" as never),
      /unknown preference/,
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
