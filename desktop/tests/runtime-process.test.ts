import { EventEmitter } from "node:events";
import { spawn as spawnChild } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join, relative, resolve } from "node:path";
import { test } from "node:test";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";

import {
  PythonRuntime,
  RuntimeBoundaryError,
  RuntimeRequestError,
  type SpawnLike,
  resolvePythonLaunch,
} from "../src/python-runtime";
import {
  DesktopPreferences,
  DEFAULT_DESKTOP_PREFERENCES,
} from "../src/desktop-preferences";

const REAL_USER_PROFILE = resolve("C:\\Users\\93445");
const REAL_USER_CONFIG = resolve(REAL_USER_PROFILE, ".uthcode", "config.toml");

function isWithin(candidate: string, root: string): boolean {
  const child = relative(resolve(root), resolve(candidate));
  const parentPrefix = process.platform === "win32" ? "\\" : "/";
  return child === "" || (!child.startsWith(`..${parentPrefix}`) && child !== "..");
}

function assertIsolatedTestPath(label: string, candidate: string): string {
  const resolved = resolve(candidate);
  const systemTemp = resolve(tmpdir());
  const workspace = resolve(fileURLToPath(new URL("../../", import.meta.url)));
  assert.notEqual(resolved.toLowerCase(), REAL_USER_PROFILE.toLowerCase(), `${label} must not be the real user profile`);
  assert.notEqual(resolved.toLowerCase(), REAL_USER_CONFIG.toLowerCase(), `${label} must not be the real user config`);
  assert.ok(
    !isWithin(resolved, REAL_USER_PROFILE) || isWithin(resolved, systemTemp),
    `${label} must not use real-user state outside system temp`,
  );
  assert.ok(isWithin(resolved, systemTemp) || isWithin(resolved, workspace), `${label} must be under workspace or temp`);
  return resolved;
}

test("desktop test isolation guard rejects the real user profile and config", () => {
  assert.throws(() => assertIsolatedTestPath("test HOME", REAL_USER_PROFILE), /real user profile/);
  assert.throws(() => assertIsolatedTestPath("test config", REAL_USER_CONFIG), /real user config/);
});

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

function errorResponse(id: string, kind: string, message: string): string {
  return `${JSON.stringify({ id, ok: false, error: { kind, message }, type: "response" })}\n`;
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

test("stderr UTF-8 diagnostics wait for complete characters and lines and reset between children", async () => {
  const first = new FakeChild();
  const second = new FakeChild();
  const children = [first, second];
  const diagnostics: string[] = [];
  const runtime = new PythonRuntime({
    launch: { command: "python.exe", args: [] },
    spawn: (() => children.shift() as FakeChild) as never,
    onDiagnostic: (line) => diagnostics.push(line),
  });
  await runtime.start();
  const encoded = Buffer.from("中文诊断\n", "utf8");
  for (const byte of encoded) first.stderr.emit("data", Buffer.from([byte]));
  assert.deepEqual(diagnostics, ["中文诊断"]);
  const incomplete = Buffer.from("旧", "utf8");
  first.stderr.emit("data", incomplete.subarray(0, 2));
  first.emit("close", 1, null);
  assert.equal(diagnostics.length, 2);
  await runtime.start();
  second.stderr.emit("data", Buffer.from("新进程诊断\n", "utf8"));
  assert.equal(diagnostics.at(-1), "新进程诊断");
  assert.doesNotMatch(diagnostics.at(-1) ?? "", /旧|�/u);
  second.emit("close", 0, null);
});

test("stdout UTF-8 decoder preserves Chinese reasoning assistant events and structured errors across chunks", async () => {
  const child = new FakeChild();
  const events: Array<Record<string, unknown>> = [];
  const runtime = new PythonRuntime({
    launch: { command: "python.exe", args: [] },
    spawn: (() => child) as never,
    onAgentEvent: (event) => events.push(event as Record<string, unknown>),
  });
  await runtime.start();
  const pending = runtime.request("turn.start", { prompt: "你好" });
  const id = requestId(child);
  const lines = [
    { type: "agent_event", event: { type: "reasoning_delta", text: "正在分析中文" } },
    { type: "agent_event", event: { type: "assistant_message_completed", message: { role: "assistant", parts: [{ type: "text", text: "你好，这是回答" }] } } },
    { type: "response", id, ok: false, error: { kind: "provider_error", message: "中文错误信息" } },
  ].map((value) => `${JSON.stringify(value)}\n`).join("");
  for (const byte of Buffer.from(lines, "utf8")) child.stdout.emit("data", Buffer.from([byte]));
  await assert.rejects(pending, (error: unknown) => error instanceof RuntimeRequestError && error.message === "中文错误信息");
  assert.equal(events[0]?.text, "正在分析中文");
  assert.equal((((events[1]?.message as Record<string, unknown>).parts as Array<Record<string, unknown>>)[0]?.text), "你好，这是回答");
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

test("late response for a timed-out request does not poison a live Runtime", async () => {
  const child = new FakeChild();
  const runtime = new PythonRuntime({
    launch: { command: "python.exe", args: [] },
    spawn: (() => child) as never,
    requestTimeoutMs: 15,
  });
  await runtime.start();

  const pending = runtime.request("command.execute", { text: "/status" });
  const timedOutId = requestId(child);
  await assert.rejects(pending, (error: unknown) => {
    return error instanceof RuntimeBoundaryError && error.kind === "request_timeout";
  });
  assert.equal(runtime.state, "ready");

  // The serial Bridge may finish the command after the renderer-side timeout
  // and still emit the original response id.  That stale response is not a
  // malformed protocol frame and must not destroy the live child boundary.
  child.stdout.emit("data", response(timedOutId, { state: "ready" }));
  assert.equal(runtime.state, "ready");

  const failed = runtime.request("status.get", {});
  const failedId = requestId(child);
  await assert.rejects(failed, (error: unknown) => {
    return error instanceof RuntimeBoundaryError && error.kind === "request_timeout";
  });
  child.stdout.emit("data", errorResponse(failedId, "provider_error", "late failure"));
  assert.equal(runtime.state, "ready");

  const status = runtime.request("status.get", {});
  const statusId = requestId(child);
  child.stdout.emit("data", response(statusId, { state: "ready", active_turn: false }));
  assert.deepEqual(await status, { state: "ready", active_turn: false });
  await runtime.shutdown();
});

test("canonical /compact waits beyond the client deadline while status keeps its timeout", async () => {
  const child = new FakeChild();
  const runtime = new PythonRuntime({
    launch: { command: "python.exe", args: [] },
    spawn: (() => child) as never,
    requestTimeoutMs: 15,
  });
  await runtime.start();

  let compactSettled = false;
  const compact = runtime
    .request("command.execute", { text: " \t/CoMpAcT \n" })
    .finally(() => { compactSettled = true; });
  const compactId = requestId(child);
  await new Promise((resolve) => setTimeout(resolve, 35));
  assert.equal(compactSettled, false);

  const withArgument = runtime.request("command.execute", { text: "/compact extra" });
  await assert.rejects(withArgument, (error: unknown) => {
    return error instanceof RuntimeBoundaryError && error.kind === "request_timeout";
  });
  assert.equal(compactSettled, false);

  const status = runtime.request("status.get", {});
  await assert.rejects(status, (error: unknown) => {
    return error instanceof RuntimeBoundaryError && error.kind === "request_timeout";
  });
  assert.equal(compactSettled, false);

  child.stdout.emit("data", response(compactId, { command: "compact", status: "success" }));
  assert.deepEqual(await compact, { command: "compact", status: "success" });
  assert.equal(runtime.state, "ready");
  await runtime.shutdown();
});

test("canonical /compact failure settles only when the Bridge reports failure", async () => {
  const child = new FakeChild();
  const runtime = new PythonRuntime({
    launch: { command: "python.exe", args: [] },
    spawn: (() => child) as never,
    requestTimeoutMs: 15,
  });
  await runtime.start();

  let compactSettled = false;
  const compact = runtime
    .request("command.execute", { text: "/compact" })
    .finally(() => { compactSettled = true; });
  const compactId = requestId(child);
  await new Promise((resolve) => setTimeout(resolve, 35));
  assert.equal(compactSettled, false);

  child.stdout.emit("data", errorResponse(compactId, "execution_error", "compact failed"));
  await assert.rejects(compact, (error: unknown) => {
    return error instanceof RuntimeRequestError
      && error.kind === "execution_error"
      && error.message === "compact failed";
  });
  assert.equal(runtime.state, "ready");
  await runtime.shutdown();
});

test("bounded shutdown reaps a child with an unfinished canonical /compact request", async () => {
  const child = new FakeChild();
  const runtime = new PythonRuntime({
    launch: { command: "python.exe", args: [] },
    spawn: (() => child) as never,
    requestTimeoutMs: 15,
    shutdownTimeoutMs: 20,
  });
  await runtime.start();

  const compact = runtime.request("command.execute", { text: "/compact" });
  const compactId = requestId(child);
  assert.equal(typeof compactId, "string");

  const shutdown = runtime.shutdown();
  assert.equal(JSON.parse(child.writes.at(-1) ?? "{}").method, "runtime.shutdown");
  await shutdown;
  await assert.rejects(compact, (error: unknown) => {
    return error instanceof RuntimeBoundaryError && error.kind === "shutdown_timeout";
  });
  assert.equal(runtime.state, "stopped");
});

test("late responses remain correlated after more than 256 requests time out", async () => {
  const child = new FakeChild();
  const runtime = new PythonRuntime({
    launch: { command: "python.exe", args: [] },
    spawn: (() => child) as never,
    requestTimeoutMs: 2,
  });
  await runtime.start();

  const requests = Array.from({ length: 257 }, () => runtime.request("status.get", {}));
  const ids = child.writes.map((line) => (JSON.parse(line) as { id: string }).id);
  assert.equal(ids.length, 257);
  await Promise.all(requests.map((request) => assert.rejects(request, (error: unknown) => {
    return error instanceof RuntimeBoundaryError && error.kind === "request_timeout";
  })));

  child.stdout.emit("data", response(ids[0]!, { state: "ready" }));
  assert.equal(runtime.state, "ready");
  const status = runtime.request("status.get", {});
  const statusId = requestId(child);
  child.stdout.emit("data", response(statusId, { state: "ready", active_turn: false }));
  assert.deepEqual(await status, { state: "ready", active_turn: false });
  await runtime.shutdown();
});

test("an actually unknown response id still fails the Runtime boundary", async () => {
  const child = new FakeChild();
  const runtime = new PythonRuntime({
    launch: { command: "python.exe", args: [] },
    spawn: (() => child) as never,
  });
  await runtime.start();

  const pending = runtime.request("status.get", {});
  child.stdout.emit("data", response("unknown-response-id", { state: "ready" }));
  assert.equal(runtime.state, "failed");
  await assert.rejects(pending, (error: unknown) => {
    return error instanceof RuntimeBoundaryError && error.kind === "malformed_response";
  });
  child.emit("close", 1, null);
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

test("runtime shutdown request waits for close/reap before replacing the child PID", async () => {
  const bridgeScript = [
    "const readline = require('node:readline');",
    "const input = readline.createInterface({ input: process.stdin });",
    "input.on('line', (line) => {",
    "  const request = JSON.parse(line);",
    "  const result = { state: request.method === 'runtime.shutdown' ? 'stopped' : 'ready', method: request.method };",
    "  process.stdout.write(JSON.stringify({ type: 'response', id: request.id, ok: true, result }) + '\\n');",
    "  if (request.method === 'runtime.shutdown') setTimeout(() => process.exit(0), 15);",
    "});",
  ].join("\n");
  const runtime = new PythonRuntime({
    launch: { command: process.execPath, args: ["-e", bridgeScript] },
    spawn: spawnChild as never,
    requestTimeoutMs: 500,
    shutdownTimeoutMs: 500,
  });

  await runtime.start();
  const firstPid = runtime.pid;
  assert.ok(firstPid);
  assert.deepEqual(await runtime.request("runtime.initialize", { workdir: process.cwd() }), {
    state: "ready",
    method: "runtime.initialize",
  });
  assert.deepEqual(await runtime.request("project.open", { path: process.cwd() }), {
    state: "ready",
    method: "project.open",
  });
  assert.deepEqual(await runtime.request("session.resume", { session_id: "durable-session" }), {
    state: "ready",
    method: "session.resume",
  });
  assert.deepEqual(await runtime.request("runtime.shutdown", {}), {
    state: "stopped",
    method: "runtime.shutdown",
  });
  assert.equal(runtime.pid, firstPid, "response completion alone must retain child ownership");

  await runtime.shutdownAfterRequest();
  assert.equal(runtime.pid, undefined);
  assert.equal(runtime.state, "stopped");

  await runtime.start();
  const replacementPid = runtime.pid;
  assert.ok(replacementPid);
  assert.notEqual(replacementPid, firstPid);
  await runtime.shutdown();
});

function reUthcodePythonExecutable(): string {
  const configured = process.env.UTHCODE_PYTHON?.trim();
  if (configured && existsSync(configured)) return configured;

  const condaExecutable = process.env.CONDA_EXE?.trim();
  if (condaExecutable) {
    const condaRoot = dirname(dirname(condaExecutable));
    const executable = process.platform === "win32"
      ? join(condaRoot, "envs", "re-uthcode", "python.exe")
      : join(condaRoot, "envs", "re-uthcode", "bin", "python");
    if (existsSync(executable)) return executable;
  }

  const activePrefix = process.env.CONDA_PREFIX?.trim();
  if (activePrefix && basename(activePrefix) === "re-uthcode") {
    const executable = process.platform === "win32"
      ? join(activePrefix, "python.exe")
      : join(activePrefix, "bin", "python");
    if (existsSync(executable)) return executable;
  }
  throw new Error("re-uthcode Python executable is required for the offline Desktop integration test");
}

async function waitForAgentEvent(
  events: Array<Record<string, unknown>>,
  type: string,
  timeoutMs = 10_000,
): Promise<Record<string, unknown>> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const event = events.find((candidate) => candidate.type === type);
    if (event) return event;
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  throw new Error(`Timed out waiting for Desktop AgentEvent ${type}`);
}

test("offline Desktop Runtime traverses Bridge, Application, Core, events, and paged history", async () => {
  const home = await mkdtemp(join(tmpdir(), "uthcode-desktop-e2e-home-"));
  const project = await mkdtemp(join(tmpdir(), "uthcode-desktop-e2e-project-"));
  const configDirectory = join(home, ".uthcode");
  assertIsolatedTestPath("Desktop test HOME", home);
  assertIsolatedTestPath("Desktop test project", project);
  assertIsolatedTestPath("Desktop test config", join(configDirectory, "config.toml"));
  await mkdir(configDirectory, { recursive: true });
  await writeFile(
    join(configDirectory, "config.toml"),
    [
      'default_model = "offline/model"',
      "",
      "[providers.offline]",
      'kind = "fake"',
      "",
      '[models."offline/model"]',
      'provider = "offline"',
      'remote_id = "offline-model"',
      'display_name = "Offline integration model"',
      "context_window = 4096",
      "max_output_tokens = 256",
      "",
    ].join("\n"),
    "utf8",
  );

  const events: Array<Record<string, unknown>> = [];
  const diagnostics: string[] = [];
  const runtime = new PythonRuntime({
    launch: resolvePythonLaunch({
      mode: "development",
      pythonExecutable: reUthcodePythonExecutable(),
    }),
    spawn: ((
      command: string,
      args: string[],
      options: Parameters<SpawnLike>[2],
    ) => spawnChild(command, args, {
      ...options,
      cwd: join(process.cwd(), ".."),
      env: {
        ...process.env,
        HOME: home,
        USERPROFILE: home,
        APPDATA: join(home, "AppData", "Roaming"),
        LOCALAPPDATA: join(home, "AppData", "Local"),
        HOMEDRIVE: "",
        HOMEPATH: "",
      },
    })) as SpawnLike,
    requestTimeoutMs: 15_000,
    shutdownTimeoutMs: 5_000,
    onAgentEvent: (event) => events.push(event as Record<string, unknown>),
    onDiagnostic: (line) => diagnostics.push(line),
  });

  try {
    await runtime.start();
    const initialized = await runtime.request("runtime.initialize", { workdir: project });
    assert.equal((initialized as Record<string, unknown>).application, true);

    const opened = await runtime.request("project.open", { path: project });
    assert.equal((opened as Record<string, unknown>).project !== undefined, true);

    const created = await runtime.request("session.new", {});
    const sessionId = (created as Record<string, unknown>).session_id;
    assert.equal(typeof sessionId, "string");
    assert.deepEqual((created as Record<string, unknown>).replay, []);

    const chinesePrompt = "你好，请保留推理、回答与会话预览中的中文。";
    const started = await runtime.request("turn.start", { prompt: chinesePrompt });
    const runId = (started as Record<string, unknown>).run_id;
    const turnId = (started as Record<string, unknown>).turn_id;
    assert.equal(typeof runId, "string");
    assert.equal(typeof turnId, "string");

    const completed = await waitForAgentEvent(events, "turn_completed");
    assert.equal(completed.run_id, runId);
    assert.equal(completed.turn_id, turnId);
    assert.ok(
      events.find((event) => event.type === "assistant_message_completed" && event.run_id === runId),
      JSON.stringify(events),
    );

    const resumed = await runtime.request("session.resume", { session_id: sessionId as string });
    const replay = (resumed as Record<string, unknown>).replay;
    assert.equal((resumed as Record<string, unknown>).restored, true);
    assert.deepEqual(replay, [], "resume establishes runtime ownership; history.page owns durable replay");
    assert.equal((resumed as Record<string, unknown>).preparing, false);
    const history = await runtime.request("history.page", { session_id: sessionId as string });
    const records = (history as Record<string, unknown>).records;
    assert.ok(Array.isArray(records));
    assert.ok((records as Array<Record<string, unknown>>).some((entry) => entry.kind === "user"));
    assert.ok((records as Array<Record<string, unknown>>).some((entry) => entry.kind === "assistant"));
    assert.ok((records as Array<Record<string, unknown>>).some((entry) => entry.kind === "user" && entry.text === chinesePrompt));
    assert.doesNotMatch(JSON.stringify({ events, history }), /�|浣犲ソ|璇蜂繚鐣/u);
    assert.deepEqual(diagnostics, []);
  } finally {
    await runtime.shutdown();
    await rm(home, { recursive: true, force: true });
    await rm(project, { recursive: true, force: true });
  }
  assert.equal(runtime.state, "stopped");
  assert.equal(runtime.pid, undefined);
});

test("desktop preferences persist only allowlisted UI metadata", async () => {
  const root = await mkdtemp(join(tmpdir(), "uthcode-preferences-"));
  const file = join(root, "preferences.json");
  try {
    const preferences = new DesktopPreferences(file);
    assert.deepEqual(await preferences.read(), DEFAULT_DESKTOP_PREFERENCES);
    await writeFile(file, JSON.stringify({ theme: "dark" }), "utf8");
    assert.equal((await preferences.read()).language, "zh-CN");
    assert.deepEqual((await preferences.read()).expandedProjects, {});
    assert.equal((await preferences.read()).sidebarWidth, 286, "legacy documents migrate the new sidebar width to its default");
    assert.equal((await preferences.read()).runtimePanelWidth, 318, "legacy documents migrate the new Runtime width to its default");
    await preferences.write("theme", "dark");
    await preferences.write("language", "en");
    await preferences.write("sidebarWidth", 376);
    await preferences.write("runtimePanelWidth", 412);
    const reloaded = new DesktopPreferences(file);
    assert.equal((await reloaded.read()).sidebarWidth, 376);
    assert.equal((await reloaded.read()).runtimePanelWidth, 412);
    await reloaded.write("sidebarWidth", 999);
    await reloaded.write("runtimePanelWidth", 1);
    assert.equal((await reloaded.read()).sidebarWidth, 420, "oversized sidebar width clamps to the durable maximum");
    assert.equal((await reloaded.read()).runtimePanelWidth, 260, "undersized Runtime width clamps to the durable minimum");
    await assert.rejects(reloaded.write("sidebarWidth", 12.5 as never), /finite integer/);
    await preferences.write("selectedProjectKey", "C:\\Projects\\UthCode");
    await preferences.write("recentProjects", [
      { path: "C:\\Projects\\UthCode", alias: "Work", pinned: true },
    ]);
    await preferences.write("pinnedSessions", [
      { projectKey: "C:\\Projects\\UthCode", sessionId: "session-1" },
      { projectKey: "C:\\Projects\\UthCode", sessionId: "session-1" },
    ]);
    await preferences.write("expandedProjects", { "C:\\Projects\\UthCode": true });
    const raw = await readFile(file, "utf8");
    assert.equal(raw.includes("api-key"), false);
    assert.deepEqual((await preferences.read()).theme, "dark");
    assert.deepEqual((await preferences.read()).language, "en");
    await assert.rejects(preferences.write("language", "fr" as never), /language must be/);
    assert.deepEqual((await preferences.read()).pinnedSessions, [{ projectKey: "C:\\Projects\\UthCode", sessionId: "session-1" }]);
    assert.deepEqual((await preferences.read()).expandedProjects, { "C:\\Projects\\UthCode": true });
    await assert.rejects(preferences.write("expandedProjects", { "C:\\Projects\\UthCode": "yes" } as never), /must be boolean/);
    await assert.rejects(preferences.write("pinnedSessions", [{ projectKey: "", sessionId: "session-1" }]), /non-empty string/);
    await assert.rejects(preferences.write("pinnedSessions", [{ projectKey: "project", sessionId: "session", extra: true } as never]), /unknown fields/);
    await assert.rejects(
      preferences.write("apiKey" as never, "fake-key" as never),
      /unknown preference/,
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
