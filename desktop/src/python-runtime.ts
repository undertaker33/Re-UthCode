import { randomUUID } from "node:crypto";
import { spawn as nodeSpawn } from "node:child_process";
import { join, win32, posix } from "node:path";
import { StringDecoder } from "node:string_decoder";

import type { JsonObject, JsonValue, AgentEvent } from "./desktop-api";
import { isJsonObject, isJsonValue } from "./desktop-api";

export type RuntimeMode = "development" | "production";

export interface PythonLaunch {
  command: string;
  args: string[];
}

export interface ResolvePythonLaunchOptions {
  mode: RuntimeMode;
  pythonExecutable?: string;
  resourcesPath?: string;
  runtimeExecutable?: string;
  platform?: NodeJS.Platform;
}

export function resolvePythonLaunch(options: ResolvePythonLaunchOptions): PythonLaunch {
  const platform = options.platform ?? process.platform;
  const pathApi = platform === "win32" ? win32 : posix;
  if (options.mode === "development") {
    const executable = options.pythonExecutable ?? developmentPythonFromEnvironment(platform);
    if (!executable || !executable.trim()) {
      throw new Error("development Python executable is required");
    }
    return { command: executable, args: ["-m", "uthcode.interfaces.desktop"] };
  }

  if (!options.resourcesPath || !options.resourcesPath.trim()) {
    throw new Error("process.resourcesPath is required for bundled Runtime");
  }
  const runtimeRoot = pathApi.join(options.resourcesPath, "uthcode-runtime");
  const expectedName = platform === "win32" ? "uthcode-desktop-runtime.exe" : "uthcode-desktop-runtime";
  const expected = pathApi.join(runtimeRoot, expectedName);
  if (options.runtimeExecutable !== undefined) {
    const requested = pathApi.normalize(options.runtimeExecutable);
    if (requested !== pathApi.normalize(expected)) {
      throw new Error("production launch requires the bundled Runtime executable");
    }
  }
  return { command: expected, args: [] };
}

function developmentPythonFromEnvironment(platform: NodeJS.Platform): string | undefined {
  const configured = process.env.UTHCODE_PYTHON;
  if (configured?.trim()) return configured;
  const condaPrefix = process.env.CONDA_PREFIX;
  if (!condaPrefix?.trim()) return undefined;
  const pathApi = platform === "win32" ? win32 : posix;
  return pathApi.join(condaPrefix, platform === "win32" ? "python.exe" : "bin/python");
}

interface WritableLike {
  write(chunk: string, callback?: (error?: Error | null) => void): boolean;
  end(callback?: () => void): void;
}

interface ReadableLike {
  on(event: "data", listener: (chunk: unknown) => void): this;
}

export interface ChildProcessLike {
  readonly pid?: number;
  readonly stdin?: WritableLike | null;
  readonly stdout?: ReadableLike | null;
  readonly stderr?: ReadableLike | null;
  on(event: "error" | "exit" | "close", listener: (...args: unknown[]) => void): this;
  kill(signal?: NodeJS.Signals): boolean;
}

export type SpawnLike = (
  command: string,
  args: string[],
  options: { shell: false; stdio: ["pipe", "pipe", "pipe"]; windowsHide: true },
) => ChildProcessLike;

type PendingRequest = {
  resolve: (value: JsonValue) => void;
  reject: (reason?: unknown) => void;
  timer: ReturnType<typeof setTimeout>;
};

export class RuntimeBoundaryError extends Error {
  readonly kind:
    | "runtime_not_started"
    | "request_timeout"
    | "malformed_response"
    | "process_exit"
    | "process_error"
    | "shutdown_timeout"
    | "shutdown_failed";

  constructor(kind: RuntimeBoundaryError["kind"], message = "Desktop Runtime boundary error") {
    super(message);
    this.name = "RuntimeBoundaryError";
    this.kind = kind;
  }
}

export class RuntimeRequestError extends Error {
  readonly kind: string;

  constructor(kind: string, message: string) {
    super(message);
    this.name = "RuntimeRequestError";
    this.kind = kind;
  }
}

export interface PythonRuntimeOptions {
  launch: PythonLaunch;
  spawn?: SpawnLike;
  requestTimeoutMs?: number;
  shutdownTimeoutMs?: number;
  onAgentEvent?: (event: AgentEvent) => void;
  onRuntimeState?: (state: string) => void;
  onDiagnostic?: (line: string) => void;
}

type RuntimeState = "idle" | "starting" | "ready" | "stopping" | "stopped" | "failed";

export class PythonRuntime {
  readonly launch: PythonLaunch;
  readonly requestTimeoutMs: number;
  readonly shutdownTimeoutMs: number;

  private readonly spawnProcess: SpawnLike;
  private readonly pending = new Map<string, PendingRequest>();
  private readonly onAgentEvent?: (event: AgentEvent) => void;
  private readonly onRuntimeState?: (state: string) => void;
  private readonly onDiagnostic?: (line: string) => void;
  private readonly decoder = new StringDecoder("utf8");
  private child: ChildProcessLike | undefined;
  private outputBuffer = "";
  private exitPromise: Promise<void> | undefined;
  private resolveExit: (() => void) | undefined;
  private closeConfirmedChild: ChildProcessLike | undefined;
  private shutdownPromise: Promise<void> | undefined;
  private _state: RuntimeState = "idle";
  private _pid: number | undefined;

  constructor(options: PythonRuntimeOptions) {
    this.launch = { command: options.launch.command, args: [...options.launch.args] };
    this.spawnProcess = options.spawn ?? (nodeSpawn as unknown as SpawnLike);
    this.requestTimeoutMs = options.requestTimeoutMs ?? 30_000;
    this.shutdownTimeoutMs = options.shutdownTimeoutMs ?? 5_000;
    this.onAgentEvent = options.onAgentEvent;
    this.onRuntimeState = options.onRuntimeState;
    this.onDiagnostic = options.onDiagnostic;
  }

  get state(): RuntimeState {
    return this._state;
  }

  get pid(): number | undefined {
    return this._pid;
  }

  async start(): Promise<void> {
    if (this._state === "ready" || this._state === "starting") return;
    if (this._state === "stopping") throw new RuntimeBoundaryError("shutdown_failed", "Runtime is shutting down");
    if (this.child) {
      throw new RuntimeBoundaryError(
        "process_error",
        "Python Runtime child must be closed before it can be started again",
      );
    }
    this._state = "starting";
    try {
      const child = this.spawnProcess(this.launch.command, this.launch.args, {
        shell: false,
        stdio: ["pipe", "pipe", "pipe"],
        windowsHide: true,
      });
      this.child = child;
      this._pid = child.pid;
      this.closeConfirmedChild = undefined;
      this.exitPromise = new Promise<void>((resolve) => {
        this.resolveExit = resolve;
      });
      child.stdout?.on("data", (chunk) => this.consumeStdout(chunk));
      child.stderr?.on("data", (chunk) => this.consumeStderr(chunk));
      child.on("error", (error) => this.handleProcessError(child, error));
      child.on("exit", (code, signal) => this.handleProcessExit(child, code, signal));
      child.on("close", (code, signal) => this.handleProcessClose(child, code, signal));
      this._state = "ready";
    } catch {
      this.child = undefined;
      this._pid = undefined;
      this.markFailed();
      throw new RuntimeBoundaryError("process_error", "Python Runtime could not be started");
    }
  }

  async request(method: string, params: JsonObject): Promise<JsonValue> {
    return this.requestInternal(method, params, false);
  }

  private async requestInternal(
    method: string,
    params: JsonObject,
    allowStopping: boolean,
    timeoutMs = this.requestTimeoutMs,
  ): Promise<JsonValue> {
    if (
      this._state !== "ready" &&
      this._state !== "starting" &&
      !(allowStopping && this._state === "stopping")
    ) {
      throw new RuntimeBoundaryError("runtime_not_started", "Python Runtime is not available");
    }
    if (typeof method !== "string" || method.length === 0 || !isJsonObject(params)) {
      throw new RuntimeBoundaryError("malformed_response", "Runtime request is invalid");
    }
    const child = this.child;
    if (!child?.stdin) throw new RuntimeBoundaryError("runtime_not_started", "Python Runtime input is unavailable");
    const id = randomUUID();
    const envelope = JSON.stringify({ type: "request", id, method, params });
    return new Promise<JsonValue>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new RuntimeBoundaryError("request_timeout", "Python Runtime request timed out"));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      try {
        child.stdin?.write(`${envelope}\n`, (error) => {
          if (error) this.rejectPending(id, new RuntimeBoundaryError("process_error", "Python Runtime input failed"));
        });
      } catch {
        this.rejectPending(id, new RuntimeBoundaryError("process_error", "Python Runtime input failed"));
      }
    });
  }

  async shutdown(): Promise<void> {
    return this.closeChild(true);
  }

  /**
   * Complete the close/reap phase after a caller already received the
   * runtime.shutdown response.  The response is not the process boundary:
   * the child remains owned until its close event has been observed.
   */
  async shutdownAfterRequest(): Promise<void> {
    return this.closeChild(false);
  }

  private async closeChild(requestBridge: boolean): Promise<void> {
    if (this.shutdownPromise) return this.shutdownPromise;
    if (!this.child || this._state === "idle") {
      this._state = "stopped";
      return;
    }
    this.shutdownPromise = this.shutdownInternal(requestBridge);
    try {
      await this.shutdownPromise;
    } finally {
      this.shutdownPromise = undefined;
    }
  }

  private async shutdownInternal(requestBridge: boolean): Promise<void> {
    const child = this.child;
    if (!child) {
      this._state = "stopped";
      return;
    }
    this._state = "stopping";
    const closeWindow = Math.max(1, this.shutdownTimeoutMs);
    try {
      if (requestBridge) {
        // Do not let the normal request timeout (30s by default) extend the
        // bounded close contract. An unresponsive bridge is terminated within
        // its own bounded graceful-request window instead of holding Electron's
        // close event. Termination and close confirmation retain separate
        // bounded windows below.
        await this.requestInternal(
          "runtime.shutdown",
          {},
          true,
          Math.min(this.requestTimeoutMs, closeWindow),
        );
      }
    } catch {
      // A dead or unresponsive bridge is still reaped below. Its failure is
      // a Runtime boundary condition, never an Agent/Provider failure.
    }
    try {
      child.stdin?.end();
    } catch {
      // The bounded wait/kill path below remains authoritative.
    }
    let exited = await this.waitForExit(closeWindow);
    let terminateAccepted = false;
    let killAccepted = false;
    if (!exited && this.child === child) {
      terminateAccepted = this.terminateChild(child, "SIGTERM");
      exited = await this.waitForExit(closeWindow);
    }
    if (!exited && this.child === child) {
      // A bridge which ignores the graceful request and SIGTERM gets one
      // final bounded SIGKILL/reap window. A kill return value is observed,
      // but only a subsequent close event proves that ownership ended.
      killAccepted = this.terminateChild(child, "SIGKILL");
      exited = await this.waitForExit(closeWindow);
    }
    if (!exited || (this.child === child && this.closeConfirmedChild !== child)) {
      // Do not detach a child whose close/reap has not been observed. The
      // caller must retain ownership and decide how to recover; silently
      // starting a replacement would orphan the unknown process.
      this.markFailed();
      const detail = terminateAccepted || killAccepted
        ? "Python Runtime did not confirm child close after termination"
        : "Python Runtime could not terminate or confirm child close";
      const failure = new RuntimeBoundaryError("shutdown_timeout", detail);
      this.rejectAll(failure);
      throw failure;
    }
    this.rejectAll(new RuntimeBoundaryError("shutdown_timeout", "Python Runtime stopped"));
    this.detachChild(child);
    this._state = "stopped";
  }

  private waitForExit(timeoutMs: number): Promise<boolean> {
    if (!this.exitPromise || !this.child) return Promise.resolve(true);
    const current = this.exitPromise;
    return Promise.race([
      current.then(() => true),
      new Promise<boolean>((resolve) => setTimeout(() => resolve(false), timeoutMs)),
    ]);
  }

  private terminateChild(child: ChildProcessLike, signal: NodeJS.Signals): boolean {
    try {
      return child.kill(signal);
    } catch {
      return false;
    }
  }

  private consumeStdout(chunk: unknown): void {
    if (typeof chunk === "string") this.outputBuffer += chunk;
    else if (Buffer.isBuffer(chunk)) this.outputBuffer += this.decoder.write(chunk);
    else this.outputBuffer += String(chunk);
    let newline: number;
    while ((newline = this.outputBuffer.indexOf("\n")) >= 0) {
      const line = this.outputBuffer.slice(0, newline).replace(/\r$/, "");
      this.outputBuffer = this.outputBuffer.slice(newline + 1);
      this.consumeLine(line);
    }
  }

  private consumeLine(line: string): void {
    if (!line.trim()) {
      this.failMalformedOutput();
      return;
    }
    let value: unknown;
    try {
      value = JSON.parse(line);
    } catch {
      this.failMalformedOutput();
      return;
    }
    if (!isJsonObject(value) || typeof value.type !== "string") {
      this.failMalformedOutput();
      return;
    }
    if (value.type === "agent_event") {
      if (
        Object.keys(value).some((key) => key !== "type" && key !== "event") ||
        !isJsonObject(value.event) ||
        typeof value.event.type !== "string" ||
        value.event.type.length === 0
      ) {
        this.failMalformedOutput();
        return;
      }
      this.onAgentEvent?.(value.event as AgentEvent);
      return;
    }
    if (value.type === "runtime_state") {
      if (
        Object.keys(value).some((key) => key !== "type" && key !== "state" && key !== "error") ||
        (value.state !== "ready" &&
          value.state !== "stopping" &&
          value.state !== "stopped" &&
          value.state !== "failed") ||
        (value.error !== undefined &&
          (!isJsonObject(value.error) ||
            typeof value.error.kind !== "string" ||
            typeof value.error.message !== "string"))
      ) {
        this.failMalformedOutput();
        return;
      }
      if (value.state === "failed") this._state = "failed";
      else if (value.state === "stopped") this._state = "stopped";
      else if (value.state === "ready" && this._state === "starting") this._state = "ready";
      this.onRuntimeState?.(value.state);
      return;
    }
    if (
      value.type !== "response" ||
      (value.id !== null && typeof value.id !== "string") ||
      typeof value.ok !== "boolean"
    ) {
      this.failMalformedOutput();
      return;
    }
    if (value.id === null || !this.pending.has(value.id)) {
      this.failMalformedOutput();
      return;
    }
    if (value.ok) {
      if (
        Object.keys(value).some((key) => !["type", "id", "ok", "result"].includes(key)) ||
        !("result" in value) ||
        !isJsonValue(value.result)
      ) {
        this.failMalformedOutput();
        return;
      }
      this.resolvePending(value.id, value.result);
    } else {
      if (
        Object.keys(value).some((key) => !["type", "id", "ok", "error"].includes(key)) ||
        !isJsonObject(value.error) ||
        typeof value.error.kind !== "string" ||
        typeof value.error.message !== "string"
      ) {
        this.failMalformedOutput();
        return;
      }
      this.rejectPending(value.id, new RuntimeRequestError(value.error.kind, value.error.message));
    }
  }

  private consumeStderr(chunk: unknown): void {
    const text = Buffer.isBuffer(chunk) ? chunk.toString("utf8") : String(chunk);
    for (const line of text.split(/\r?\n/)) {
      if (line) this.onDiagnostic?.(line);
    }
  }

  private failMalformedOutput(): void {
    this.markFailed();
    this.rejectAll(new RuntimeBoundaryError("malformed_response", "Python Runtime returned malformed output"));
  }

  private handleProcessError(child: ChildProcessLike, _error: unknown): void {
    if (this.child !== child) return;
    if (this._state !== "stopping") this.markFailed();
    this.rejectAll(new RuntimeBoundaryError("process_error", "Python Runtime process failed"));
  }

  private handleProcessExit(child: ChildProcessLike, _code: unknown, _signal: unknown): void {
    if (this.child !== child) return;
    if (this._state !== "stopping") {
      this.markFailed();
      this.rejectAll(new RuntimeBoundaryError("process_exit", "Python Runtime exited unexpectedly"));
    }
  }

  private handleProcessClose(child: ChildProcessLike, _code: unknown, _signal: unknown): void {
    if (this.child !== child) return;
    this.closeConfirmedChild = child;
    if (this._state !== "stopping" && this._state !== "stopped") {
      this.markFailed();
      this.rejectAll(new RuntimeBoundaryError("process_exit", "Python Runtime closed unexpectedly"));
    }
    this.resolveExit?.();
    this.resolveExit = undefined;
    if (this._state !== "stopping") this.detachChild(child);
  }

  private markFailed(): void {
    if (this._state === "failed") return;
    this._state = "failed";
    this.onRuntimeState?.("failed");
  }

  private detachChild(child: ChildProcessLike): void {
    if (this.child !== child) return;
    this.child = undefined;
    this._pid = undefined;
    this.exitPromise = undefined;
    this.resolveExit = undefined;
    this.closeConfirmedChild = undefined;
  }

  private resolvePending(id: string, value: JsonValue): void {
    const pending = this.pending.get(id);
    if (!pending) return;
    this.pending.delete(id);
    clearTimeout(pending.timer);
    pending.resolve(value);
  }

  private rejectPending(id: string, reason: unknown): void {
    const pending = this.pending.get(id);
    if (!pending) return;
    this.pending.delete(id);
    clearTimeout(pending.timer);
    pending.reject(reason);
  }

  private rejectAll(reason: unknown): void {
    for (const [id, pending] of this.pending) {
      clearTimeout(pending.timer);
      pending.reject(reason);
      this.pending.delete(id);
    }
  }
}
