import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import { installPreload } from "../src/preload";
import type { DesktopApi } from "../src/desktop-api";
import {
  createRuntime,
  getSecureWebPreferences,
  IPC_CHANNELS,
  isAllowedRendererUrl,
  registerIpcHandlers,
} from "../src/main";
import type { PythonRuntimeOptions } from "../src/python-runtime";

type Listener = (...args: unknown[]) => void;

test("preload exposes only the narrow typed API and never the raw IPC event", async () => {
  const listeners = new Map<string, Listener>();
  const calls: Array<{ channel: string; args: unknown[] }> = [];
  const exposed: { name?: string; api?: DesktopApi } = {};
  const contextBridge = {
    exposeInMainWorld(name: string, api: DesktopApi) {
      exposed.name = name;
      exposed.api = api;
    },
  };
  const ipcRenderer = {
    invoke(channel: string, ...args: unknown[]) {
      calls.push({ channel, args });
      if (channel === "desktop.project.pick") return Promise.resolve("C:\\Projects\\UthCode");
      if (channel === "desktop.preference.read") return Promise.resolve({ theme: "system" });
      return Promise.resolve({ ok: true });
    },
    on(channel: string, listener: Listener) {
      listeners.set(channel, listener);
      return this;
    },
    removeListener(channel: string, listener: Listener) {
      if (listeners.get(channel) === listener) listeners.delete(channel);
      return this;
    },
  };

  const api = installPreload(contextBridge, ipcRenderer);

  assert.equal(exposed.name, "uthcode");
  assert.equal(exposed.api, api);
  assert.deepEqual(Object.keys(api).sort(), [
    "openProject",
    "openProjectInExplorer",
    "readPreference",
    "requestRuntime",
    "subscribeAgentEvents",
    "writePreference",
  ]);
  assert.equal("ipcRenderer" in api, false);
  assert.equal("shell" in api, false);
  assert.equal("fs" in api, false);

  assert.equal(await api.openProject(), "C:\\Projects\\UthCode");
  await api.openProjectInExplorer("C:\\Projects\\UthCode");
  await api.requestRuntime("status.get", {});
  await api.readPreference("theme");
  await api.writePreference("theme", "dark");

  assert.deepEqual(calls, [
    { channel: "desktop.project.pick", args: [] },
    { channel: "desktop.project.explorer", args: ["C:\\Projects\\UthCode"] },
    { channel: "desktop.runtime.request", args: [{ method: "status.get", params: {} }] },
    { channel: "desktop.preference.read", args: ["theme"] },
    { channel: "desktop.preference.write", args: ["theme", "dark"] },
  ]);

  const events: unknown[] = [];
  const unsubscribe = api.subscribeAgentEvents((event) => events.push(event));
  const listener = listeners.get("desktop.runtime.event");
  assert.ok(listener);
  listener?.({ sender: "untrusted" }, { type: "agent_delta", text: "hello" });
  assert.deepEqual(events, [{ type: "agent_delta", text: "hello" }]);
  unsubscribe();
  assert.equal(listeners.has("desktop.runtime.event"), false);
});

test("preload rejects non-JSON runtime arguments before crossing IPC", async () => {
  const contextBridge = { exposeInMainWorld() {} };
  const ipcRenderer = {
    invoke() {
      throw new Error("invoke must not run");
    },
    on() {
      return this;
    },
    removeListener() {
      return this;
    },
  };
  const api = installPreload(contextBridge, ipcRenderer);

  await assert.rejects(
    api.requestRuntime("status.get", { callback: () => undefined } as never),
    /JSON-safe/,
  );
});

test("main window policy keeps Node disabled and renderer navigation local", () => {
  const webPreferences = getSecureWebPreferences("preload.js");
  assert.equal(webPreferences.nodeIntegration, false);
  assert.equal(webPreferences.contextIsolation, true);
  assert.equal(webPreferences.sandbox, true);
  assert.equal(webPreferences.webviewTag, false);
  assert.equal(webPreferences.webSecurity, true);

  assert.equal(
    isAllowedRendererUrl("http://127.0.0.1:3000/other", "http://127.0.0.1:3000/", false),
    true,
  );
  assert.equal(
    isAllowedRendererUrl("https://127.0.0.1:3000/other", "http://127.0.0.1:3000/", false),
    false,
  );
  assert.equal(
    isAllowedRendererUrl("file:///C:/UthCode/main_window/index.html", "file:///C:/UthCode/main_window/index.html", true),
    true,
  );
  assert.equal(
    isAllowedRendererUrl("file:///C:/UthCode/other.html", "file:///C:/UthCode/main_window/index.html", true),
    false,
  );
});

test("packaged renderer HTML has restrictive CSP and no Node entry points", async () => {
  const html = await readFile(new URL("../src/renderer/index.html", import.meta.url), "utf8");
  const renderer = await readFile(new URL("../src/renderer/main.tsx", import.meta.url), "utf8");
  const main = await readFile(new URL("../src/main.ts", import.meta.url), "utf8");
  assert.match(html, /script-src 'self'/);
  assert.match(html, /object-src 'none'/);
  assert.match(html, /frame-src 'none'/);
  assert.doesNotMatch(renderer, /\b(require|process|fs|child_process)\b/u);
  assert.match(main, /setWindowOpenHandler\(\(\) => \(\{ action: "deny" \}\)\)/u);
  assert.match(main, /will-attach-webview/u);
  assert.match(main, /senderFrame/u);
});

test("main IPC handlers validate the sender and gate Explorer to picker-registered paths", async () => {
  const handlers = new Map<string, (...args: any[]) => Promise<unknown>>();
  const fakeIpc = {
    handle(channel: string, handler: (...args: any[]) => Promise<unknown>) {
      handlers.set(channel, handler);
    },
    removeHandler(channel: string) {
      handlers.delete(channel);
    },
  };
  const mainFrame = { url: "file:///C:/UthCode/main_window/index.html" };
  const webContents = { mainFrame };
  const window = { webContents };
  const trustedEvent = { sender: webContents, senderFrame: mainFrame };
  const runtime = {
    start: async () => undefined,
    request: async () => ({ state: "ready" }),
  };
  const preferences = {
    read: async () => ({ theme: "system" }),
    write: async () => ({ theme: "dark" }),
  };
  const opened: string[] = [];
  const removeHandlers = registerIpcHandlers({
    window: window as never,
    runtime: runtime as never,
    preferences: preferences as never,
    rendererEntry: mainFrame.url,
    isPackaged: true,
    ipc: fakeIpc as never,
    showOpenDialog: (async () => ({
      canceled: false,
      filePaths: ["C:\\Projects\\UthCode"],
    })) as never,
    openPath: (async (path: string) => {
      opened.push(path);
      return "";
    }) as never,
  });

  const pick = handlers.get(IPC_CHANNELS.pickProject);
  const explorer = handlers.get(IPC_CHANNELS.openProjectInExplorer);
  const runtimeRequest = handlers.get(IPC_CHANNELS.runtimeRequest);
  assert.ok(pick && explorer && runtimeRequest);
  await assert.rejects(
    runtimeRequest?.({ sender: {}, senderFrame: mainFrame }, { method: "status.get", params: {} }),
    /not trusted/,
  );
  await assert.rejects(explorer?.(trustedEvent, "C:\\Projects\\Other"), /selected before/);
  assert.equal(await pick?.(trustedEvent), "C:\\Projects\\UthCode");
  await explorer?.(trustedEvent, "C:\\Projects\\UthCode");
  assert.deepEqual(opened, ["C:\\Projects\\UthCode"]);
  removeHandlers();
  assert.equal(handlers.size, 0);
});

test("production Runtime wiring projects diagnostics and idle failures without native details", () => {
  const sent: unknown[] = [];
  const targetWindow = {
    isDestroyed: () => false,
    webContents: {
      send: (_channel: string, payload: unknown) => sent.push(payload),
    },
  };
  let runtimeOptions: PythonRuntimeOptions | undefined;
  createRuntime({
    application: { isPackaged: false },
    pythonExecutable: "python.exe",
    window: targetWindow,
    runtimeFactory: (options) => {
      runtimeOptions = options;
      return {} as never;
    },
  });

  runtimeOptions?.onDiagnostic?.("api_key=raw-native-secret");
  runtimeOptions?.onRuntimeState?.("failed");
  assert.deepEqual(sent, [
    {
      type: "runtime_diagnostic",
      message: "Python Runtime emitted a diagnostic",
    },
    { type: "runtime_state", state: "failed" },
  ]);
  assert.equal(JSON.stringify(sent).includes("raw-native-secret"), false);
});
