import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";

import { installPreload } from "../src/preload";
import type { DesktopApi } from "../src/desktop-api";
import { DesktopPreferencesStore } from "../src/desktop-preferences";
import {
  createRuntime,
  getSecureWebPreferences,
  hydrateRegisteredProjectsFromPreferences,
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
    "closeShell",
    "copySessionId",
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
  await api.copySessionId("session-1");
  await api.closeShell();
  await api.requestRuntime("status.get", {});
  await api.readPreference("theme");
  await api.writePreference("theme", "dark");
  await api.writePreference("pinnedSessions", [{ projectKey: "C:\\Projects\\UthCode", sessionId: "session-1" }]);

  assert.deepEqual(calls, [
    { channel: "desktop.project.pick", args: [] },
    { channel: "desktop.project.explorer", args: ["C:\\Projects\\UthCode"] },
    { channel: "desktop.session.copy-id", args: ["session-1"] },
    { channel: "desktop.shell.close", args: [] },
    { channel: "desktop.runtime.request", args: [{ method: "status.get", params: {} }] },
    { channel: "desktop.preference.read", args: ["theme"] },
    { channel: "desktop.preference.write", args: ["theme", "dark"] },
    { channel: "desktop.preference.write", args: ["pinnedSessions", [{ projectKey: "C:\\Projects\\UthCode", sessionId: "session-1" }]] },
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
  const copied: string[] = [];
  let shellCloseCount = 0;
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
    writeClipboard: (value) => { copied.push(value); },
    closeShell: () => { shellCloseCount += 1; },
  });

  const pick = handlers.get(IPC_CHANNELS.pickProject);
  const explorer = handlers.get(IPC_CHANNELS.openProjectInExplorer);
  const copySessionId = handlers.get(IPC_CHANNELS.copySessionId);
  const closeShell = handlers.get(IPC_CHANNELS.closeShell);
  const runtimeRequest = handlers.get(IPC_CHANNELS.runtimeRequest);
  assert.ok(pick && explorer && copySessionId && closeShell && runtimeRequest);
  await assert.rejects(closeShell?.({ sender: {}, senderFrame: mainFrame }), /not trusted/);
  await assert.rejects(
    runtimeRequest?.({ sender: {}, senderFrame: mainFrame }, { method: "status.get", params: {} }),
    /not trusted/,
  );
  await assert.rejects(copySessionId?.({ sender: {}, senderFrame: mainFrame }, "session-1"), /not trusted/);
  await copySessionId?.(trustedEvent, "session-1");
  await assert.rejects(copySessionId?.(trustedEvent, "  "), /Session ID is invalid/);
  await assert.rejects(explorer?.(trustedEvent, "C:\\Projects\\Other"), /selected before/);
  assert.equal(await pick?.(trustedEvent), "C:\\Projects\\UthCode");
  await explorer?.(trustedEvent, "C:\\Projects\\UthCode");
  await closeShell?.(trustedEvent);
  assert.deepEqual(opened, ["C:\\Projects\\UthCode"]);
  assert.deepEqual(copied, ["session-1"]);
  assert.equal(shellCloseCount, 1);
  removeHandlers();
  assert.equal(handlers.size, 0);
});

test("Main gates project use to picker or persisted recent registrations", async () => {
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
  const trustedEvent = { sender: webContents, senderFrame: mainFrame };
  const calls: Array<{ method: string; params: Record<string, unknown> }> = [];
  const runtime = {
    start: async () => undefined,
    request: async (method: string, params: Record<string, unknown>) => {
      calls.push({ method, params });
      return { ok: true };
    },
  };
  const preferenceWrites: Array<{ key: string; value: unknown }> = [];
  const preferences = {
    read: async () => ({}),
    write: async (key: string, value: unknown) => {
      preferenceWrites.push({ key, value });
      return {};
    },
  };
  const registeredProjects = new Set<string>();
  const target = await mkdtemp(join(tmpdir(), "uthcode-registered-project-"));
  const persisted = await mkdtemp(join(tmpdir(), "uthcode-persisted-project-"));
  const removeHandlers = registerIpcHandlers({
    window: { webContents } as never,
    runtime: runtime as never,
    preferences: preferences as never,
    rendererEntry: mainFrame.url,
    isPackaged: true,
    ipc: fakeIpc as never,
    registeredProjects,
    showOpenDialog: (async () => ({ canceled: false, filePaths: [target] })) as never,
    openPath: (async () => "") as never,
  });
  const runtimeRequest = handlers.get(IPC_CHANNELS.runtimeRequest);
  assert.ok(runtimeRequest);
  try {
    await assert.rejects(
      runtimeRequest?.(
        trustedEvent,
        { method: "project.open", params: { path: target } },
      ),
      /trusted Desktop history/,
    );
    await assert.rejects(
      runtimeRequest?.(
        trustedEvent,
        { method: "runtime.initialize", params: { workdir: target } },
      ),
      /trusted Desktop history/,
    );
    assert.deepEqual(calls, []);
    assert.equal(registeredProjects.has(target), false);

    const writePreference = handlers.get(IPC_CHANNELS.preferenceWrite);
    assert.ok(writePreference);
    await assert.rejects(
      writePreference(
        trustedEvent,
        "recentProjects",
        [{ path: persisted }],
      ),
      /trusted Desktop history/,
    );
    assert.deepEqual(preferenceWrites, []);

    const pick = handlers.get(IPC_CHANNELS.pickProject);
    assert.equal(await pick?.(trustedEvent), target);
    assert.equal(registeredProjects.has(target), true);
    await runtimeRequest?.(
      trustedEvent,
      { method: "project.open", params: { path: `${target}/.` } },
    );
    await runtimeRequest?.(
      trustedEvent,
      { method: "session.move", params: { session_id: "s", target_project_key: `${target}/.` } },
    );
    assert.deepEqual(calls.slice(0, 2), [
      { method: "project.open", params: { path: target } },
      { method: "session.move", params: { session_id: "s", target_project_key: target } },
    ]);

    const injectedRegistered = await writePreference(
      trustedEvent,
      "recentProjects",
      [{ path: `${target}/.` }],
    );
    assert.deepEqual(injectedRegistered, {});
    assert.deepEqual(preferenceWrites, [
      { key: "recentProjects", value: [{ path: target }] },
    ]);

    const restartedProjects = new Set<string>();
    const persistedStore = new DesktopPreferencesStore(join(persisted, "desktop-preferences.json"));
    await persistedStore.write("recentProjects", [{ path: `${persisted}/.` }]);
    await hydrateRegisteredProjectsFromPreferences(
      await persistedStore.read(),
      restartedProjects,
    );
    assert.deepEqual([...restartedProjects], [persisted]);
    const expansionOnlyStore = new DesktopPreferencesStore(join(persisted, "desktop-expansion-only.json"));
    await expansionOnlyStore.write("expandedProjects", { [persisted]: true });
    const expansionOnlyProjects = new Set<string>();
    await hydrateRegisteredProjectsFromPreferences(await expansionOnlyStore.read(), expansionOnlyProjects);
    assert.deepEqual([...expansionOnlyProjects], [], "session tree UI expansion must not register a trusted project");
    registeredProjects.clear();
    for (const project of restartedProjects) registeredProjects.add(project);
    await runtimeRequest?.(
      trustedEvent,
      { method: "runtime.initialize", params: { workdir: `${persisted}/.` } },
    );
    await runtimeRequest?.(
      trustedEvent,
      { method: "project.open", params: { path: persisted } },
    );
    assert.deepEqual(calls.slice(-2), [
      { method: "runtime.initialize", params: { workdir: persisted } },
      { method: "project.open", params: { path: persisted } },
    ]);
    assert.equal(registeredProjects.has(persisted), true);
  } finally {
    removeHandlers();
    await rm(target, { recursive: true, force: true });
    await rm(persisted, { recursive: true, force: true });
  }
});

test("main runtime shutdown handler waits for the Runtime child reap boundary", async () => {
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
  const calls: string[] = [];
  const runtime = {
    start: async () => { calls.push("start"); },
    request: async (method: string) => { calls.push(`request:${method}`); return { state: "stopped" }; },
    shutdownAfterRequest: async () => { calls.push("reap"); },
  };
  const preferences = { read: async () => ({}), write: async () => ({}) };
  const removeHandlers = registerIpcHandlers({
    window: { webContents } as never,
    runtime: runtime as never,
    preferences: preferences as never,
    rendererEntry: mainFrame.url,
    isPackaged: true,
    ipc: fakeIpc as never,
    showOpenDialog: (async () => ({ canceled: true, filePaths: [] })) as never,
    openPath: (async () => "") as never,
  });
  const runtimeRequest = handlers.get(IPC_CHANNELS.runtimeRequest);
  assert.ok(runtimeRequest);
  const result = await runtimeRequest?.({ sender: webContents, senderFrame: mainFrame }, { method: "runtime.shutdown", params: {} });
  assert.deepEqual(result, { state: "stopped" });
  assert.deepEqual(calls, ["start", "request:runtime.shutdown", "reap"]);
  removeHandlers();
});

test("theme preference writes update the native Electron chrome for dark light and system", async () => {
  const handlers = new Map<string, (...args: any[]) => Promise<unknown>>();
  const ipc = { handle: (channel: string, handler: (...args: any[]) => Promise<unknown>) => handlers.set(channel, handler), removeHandler: (channel: string) => { handlers.delete(channel); } };
  const mainFrame = { url: "file:///C:/UthCode/main_window/index.html" };
  const webContents = { mainFrame };
  const applied: string[] = [];
  let theme: "system" | "dark" | "light" = "system";
  const remove = registerIpcHandlers({
    window: { webContents } as never,
    runtime: { start: async () => undefined, request: async () => ({}), shutdownAfterRequest: async () => undefined } as never,
    preferences: { read: async () => ({ theme }), write: async (_key: string, value: typeof theme) => ({ theme: (theme = value) }) } as never,
    rendererEntry: mainFrame.url, isPackaged: true, ipc: ipc as never,
    showOpenDialog: (async () => ({ canceled: true, filePaths: [] })) as never,
    openPath: (async () => "") as never,
    setNativeTheme: (value) => applied.push(value),
  });
  const write = handlers.get(IPC_CHANNELS.preferenceWrite);
  for (const value of ["dark", "light", "system"] as const) await write?.({ sender: webContents, senderFrame: mainFrame }, "theme", value);
  assert.deepEqual(applied, ["dark", "light", "system"]);
  remove();
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
