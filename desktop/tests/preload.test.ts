import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
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
import { RuntimeRequestError, type PythonRuntimeOptions } from "../src/python-runtime";

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
      if (channel === "desktop.attachment.pick" || channel === "desktop.attachment.clipboard") return Promise.resolve(null);
      if (channel === "desktop.artifact.authorize-external") return Promise.resolve(null);
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
    "authorizeExternalArtifact",
    "chooseAttachment",
    "closeShell",
    "copyText",
    "openProject",
    "openProjectInExplorer",
    "pasteAttachment",
    "readPreference",
    "reportRendererDiagnostic",
    "requestRuntime",
    "subscribeAgentEvents",
    "writePreference",
  ]);
  assert.equal("ipcRenderer" in api, false);
  assert.equal("shell" in api, false);
  assert.equal("fs" in api, false);

  assert.equal(await api.openProject(), "C:\\Projects\\UthCode");
  await api.openProjectInExplorer("C:\\Projects\\UthCode");
  await api.copyText("session-1");
  await api.closeShell();
  await api.requestRuntime("status.get", {});
  await api.readPreference("theme");
  await api.writePreference("theme", "dark");
  await api.writePreference("pinnedSessions", [{ projectKey: "C:\\Projects\\UthCode", sessionId: "session-1" }]);
  assert.equal(await api.chooseAttachment(), null);
  assert.equal(await api.pasteAttachment(), null);
  assert.equal(await api.authorizeExternalArtifact?.(), null);
  await api.reportRendererDiagnostic?.("timeline");

  assert.deepEqual(calls, [
    { channel: "desktop.project.pick", args: [] },
    { channel: "desktop.project.explorer", args: ["C:\\Projects\\UthCode"] },
    { channel: "desktop.clipboard.copy-text", args: ["session-1"] },
    { channel: "desktop.shell.close", args: [] },
    { channel: "desktop.runtime.request", args: [{ method: "status.get", params: {} }] },
    { channel: "desktop.preference.read", args: ["theme"] },
    { channel: "desktop.preference.write", args: ["theme", "dark"] },
    { channel: "desktop.preference.write", args: ["pinnedSessions", [{ projectKey: "C:\\Projects\\UthCode", sessionId: "session-1" }]] },
    { channel: "desktop.attachment.pick", args: [] },
    { channel: "desktop.attachment.clipboard", args: [] },
    { channel: "desktop.artifact.authorize-external", args: [] },
    { channel: "desktop.renderer.diagnostic", args: ["timeline"] },
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
  const diagnosticEvents: unknown[][] = [];
  const webContents = {
    mainFrame,
    send: (...args: unknown[]) => { diagnosticEvents.push(args); },
  };
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
  const copyText = handlers.get(IPC_CHANNELS.copyText);
  const closeShell = handlers.get(IPC_CHANNELS.closeShell);
  const rendererDiagnostic = handlers.get(IPC_CHANNELS.rendererDiagnostic);
  const runtimeRequest = handlers.get(IPC_CHANNELS.runtimeRequest);
  assert.ok(pick && explorer && copyText && closeShell && rendererDiagnostic && runtimeRequest);
  await assert.rejects(closeShell?.({ sender: {}, senderFrame: mainFrame }), /not trusted/);
  await assert.rejects(
    runtimeRequest?.({ sender: {}, senderFrame: mainFrame }, { method: "status.get", params: {} }),
    /not trusted/,
  );
  await assert.rejects(copyText?.({ sender: {}, senderFrame: mainFrame }, "session-1"), /not trusted/);
  await copyText?.(trustedEvent, "session-1");
  await assert.rejects(copyText?.(trustedEvent, 1), /Clipboard text is invalid/);
  await rendererDiagnostic?.(trustedEvent, "timeline");
  await assert.rejects(rendererDiagnostic?.(trustedEvent, "unknown-area"), /diagnostic is invalid/);
  await assert.rejects(explorer?.(trustedEvent, "C:\\Projects\\Other"), /selected before/);
  assert.equal(await pick?.(trustedEvent), "C:\\Projects\\UthCode");
  await explorer?.(trustedEvent, "C:\\Projects\\UthCode");
  await closeShell?.(trustedEvent);
  assert.deepEqual(opened, ["C:\\Projects\\UthCode"]);
  assert.deepEqual(copied, ["session-1"]);
  assert.deepEqual(diagnosticEvents, [[
    IPC_CHANNELS.runtimeEvent,
    { type: "runtime_diagnostic", code: "renderer_boundary", boundary: "timeline" },
  ]]);
  assert.equal(shellCloseCount, 1);
  removeHandlers();
  assert.equal(handlers.size, 0);
});

test("Main projects only the turn image refusal as a JSON business result", async () => {
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
  const runtime = {
    start: async () => undefined,
    request: async (method: string) => {
      throw new RuntimeRequestError(
        method === "turn.start" ? "image_input_unsupported" : "turn_error",
        "The selected model does not support image input",
      );
    },
  };
  const removeHandlers = registerIpcHandlers({
    window: { webContents } as never,
    runtime: runtime as never,
    preferences: { read: async () => ({}), write: async () => ({}) } as never,
    rendererEntry: mainFrame.url,
    isPackaged: true,
    ipc: fakeIpc as never,
    showOpenDialog: (async () => ({ canceled: true, filePaths: [] })) as never,
    openPath: (async () => "") as never,
  });
  const runtimeRequest = handlers.get(IPC_CHANNELS.runtimeRequest);
  assert.ok(runtimeRequest);
  try {
    const result = await runtimeRequest?.(
      trustedEvent,
      { method: "turn.start", params: { prompt: "look", attachments: [{ ref: "asset-1", kind: "image" }] } },
    );
    assert.deepEqual(result, {
      __uthcode_runtime_error: {
        kind: "image_input_unsupported",
        message: "The selected model does not support image input",
      },
    });
    await assert.rejects(
      runtimeRequest?.(trustedEvent, { method: "status.get", params: {} }),
      RuntimeRequestError,
    );
  } finally {
    removeHandlers();
  }
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

test("preload keeps the known turn image refusal as JSON for the Renderer", async () => {
  const exposed: { api?: DesktopApi } = {};
  const contextBridge = {
    exposeInMainWorld(_name: string, api: DesktopApi) {
      exposed.api = api;
    },
  };
  const ipcRenderer = {
    invoke(channel: string) {
      assert.equal(channel, "desktop.runtime.request");
      return Promise.resolve({
        __uthcode_runtime_error: {
          kind: "image_input_unsupported",
          message: "The selected model does not support image input",
        },
      });
    },
    on() {
      return this;
    },
    removeListener() {
      return this;
    },
  };

  installPreload(contextBridge, ipcRenderer);
  const result = await exposed.api?.requestRuntime("turn.start", {
    prompt: "look at this",
    attachments: [{ ref: "asset-1", kind: "image" }],
  });
  assert.deepEqual(result, {
    __uthcode_runtime_error: {
      kind: "image_input_unsupported",
      message: "The selected model does not support image input",
    },
  });
});

test("preload keeps structured file action failures JSON-safe for the Renderer", async () => {
  const exposed: { api?: DesktopApi } = {};
  const contextBridge = {
    exposeInMainWorld(_name: string, api: DesktopApi) {
      exposed.api = api;
    },
  };
  const ipcRenderer = {
    invoke(channel: string) {
      assert.equal(channel, "desktop.runtime.request");
      return Promise.resolve({
        __uthcode_runtime_error: {
          kind: "attachment_not_found",
          message: "Attachment file is unavailable",
        },
      });
    },
    on() {
      return this;
    },
    removeListener() {
      return this;
    },
  };

  installPreload(contextBridge, ipcRenderer);
  const result = await exposed.api?.requestRuntime("attachment.open", { ref: "0123456789abcdef" });
  assert.deepEqual(result, {
    __uthcode_runtime_error: {
      kind: "attachment_not_found",
      message: "Attachment file is unavailable",
    },
  });
});

test("Main routes authorized artifacts to open/reveal and rejects URI execution", async () => {
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
  const project = await mkdtemp(join(tmpdir(), "uthcode-artifact-main-"));
  const image = join(project, "preview.png");
  const html = join(project, "unsafe.html");
  const invalid = join(project, "invalid.dat");
  await writeFile(image, "png-bytes");
  await writeFile(html, "<script>throw new Error('should not run')</script>");
  await writeFile(invalid, "invalid descriptor fixture");
  const opened: string[] = [];
  const revealed: string[] = [];
  const copied: string[] = [];
  const calls: string[] = [];
  const runtime = {
    start: async () => undefined,
    request: async (method: string, params: Record<string, unknown>) => {
      calls.push(method);
      const path = String(params.path);
      if (path === invalid) return {};
      const unsupported = path.endsWith(".html");
      return {
        artifact: {
          path,
          name: path.split(/[\\/]/u).pop() ?? path,
          kind: unsupported ? "unsupported" : "image",
          mime_type: unsupported ? "text/html" : "image/png",
          size_bytes: 10,
          default_action: unsupported ? "reveal" : "open",
          preview_supported: !unsupported,
        },
        action: method.slice("artifact.".length),
      };
    },
  };
  const registeredProjects = new Set([project]);
  const removeHandlers = registerIpcHandlers({
    window: { webContents } as never,
    runtime: runtime as never,
    preferences: { read: async () => ({}), write: async () => ({}) } as never,
    rendererEntry: mainFrame.url,
    isPackaged: true,
    ipc: fakeIpc as never,
    registeredProjects,
    showOpenDialog: (async () => ({ canceled: true, filePaths: [] })) as never,
    openPath: (async (path: string) => { opened.push(path); return ""; }) as never,
    showItemInFolder: ((path: string) => { revealed.push(path); }) as never,
    writeClipboard: (path: string) => { copied.push(path); },
  });
  const runtimeRequest = handlers.get(IPC_CHANNELS.runtimeRequest);
  assert.ok(runtimeRequest);
  try {
    const described = await runtimeRequest?.(trustedEvent, { method: "artifact.describe", params: { path: image } });
    assert.equal((described as { artifact: { path: string } }).artifact.path, image);
    await runtimeRequest?.(trustedEvent, { method: "artifact.open", params: { path: image } });
    await runtimeRequest?.(trustedEvent, { method: "artifact.open", params: { path: html } });
    assert.deepEqual(
      await runtimeRequest?.(trustedEvent, { method: "artifact.open", params: { path: join(project, "missing.png") } }),
      { __uthcode_runtime_error: { kind: "artifact_not_found", message: "Artifact file is unavailable" } },
    );
    assert.deepEqual(
      await runtimeRequest?.(trustedEvent, { method: "artifact.open", params: { path: invalid } }),
      { __uthcode_runtime_error: { kind: "artifact_unavailable", message: "Artifact descriptor is invalid" } },
    );
    assert.deepEqual(
      await runtimeRequest?.(trustedEvent, { method: "artifact.open", params: { path: "https://example.test/evil" } }),
      { __uthcode_runtime_error: { kind: "artifact_invalid", message: "Artifact descriptor is invalid" } },
    );
    assert.deepEqual(opened, [image]);
    assert.deepEqual(revealed, [html]);
    assert.deepEqual(calls, ["artifact.describe", "artifact.open", "artifact.open", "artifact.open", "artifact.open"]);
  } finally {
    removeHandlers();
    await rm(project, { recursive: true, force: true });
  }
});

test("Main routes ref-only Session attachments through the trusted derived DTO", async () => {
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
  const root = await mkdtemp(join(tmpdir(), "uthcode-attachment-main-"));
  const sessionId = "session-attachment-1";
  const ref = "0123456789abcdef";
  const derived = join(root, sessionId, "attachments", ref, "derived", "open");
  const target = join(derived, "report.final.PDF");
  await mkdir(derived, { recursive: true });
  await writeFile(target, "%PDF-1.7\n");
  const opened: string[] = [];
  const revealed: string[] = [];
  const copied: string[] = [];
  const calls: Array<{ method: string; params: Record<string, unknown> }> = [];
  let dto: Record<string, unknown> = {
    source: "session_attachment",
    session_id: sessionId,
    ref,
    asset_ref: `attachment:${sessionId}:${ref}`,
    path: target,
    display_name: "report.final.PDF",
    mime_type: "application/pdf",
    size_bytes: 9,
    kind: "office",
    default_action: "open",
  };
  const runtime = {
    start: async () => undefined,
    request: async (method: string, params: Record<string, unknown>) => {
      calls.push({ method, params });
      return { attachment: dto };
    },
  };
  const removeHandlers = registerIpcHandlers({
    window: { webContents } as never,
    runtime: runtime as never,
    preferences: { read: async () => ({}), write: async () => ({}) } as never,
    rendererEntry: mainFrame.url,
    isPackaged: true,
    ipc: fakeIpc as never,
    showOpenDialog: (async () => ({ canceled: true, filePaths: [] })) as never,
    openPath: (async (path: string) => { opened.push(path); return ""; }) as never,
    showItemInFolder: ((path: string) => { revealed.push(path); }) as never,
    writeClipboard: (path: string) => { copied.push(path); },
  });
  const runtimeRequest = handlers.get(IPC_CHANNELS.runtimeRequest);
  assert.ok(runtimeRequest);
  try {
    const openedResult = await runtimeRequest?.(trustedEvent, { method: "attachment.open", params: { ref } });
    const revealedResult = await runtimeRequest?.(trustedEvent, { method: "attachment.reveal", params: { ref } });
    const copiedResult = await runtimeRequest?.(trustedEvent, { method: "attachment.copy_path", params: { ref } });
    assert.equal((openedResult as { attachment: { ref: string } }).attachment.ref, ref);
    assert.equal((revealedResult as { attachment: { asset_ref: string } }).attachment.asset_ref, `attachment:${sessionId}:${ref}`);
    assert.equal((copiedResult as { attachment: { path: string } }).attachment.path, target);
    assert.deepEqual(opened, [target]);
    assert.deepEqual(revealed, [target]);
    assert.deepEqual(copied, [target]);
    assert.deepEqual(calls.map((call) => call.params), [{ ref }, { ref }, { ref }], "Renderer sends only the opaque ref");

    assert.deepEqual(
      await runtimeRequest?.(trustedEvent, { method: "attachment.open", params: { ref, path: target, authorized: true } }),
      { __uthcode_runtime_error: { kind: "attachment_invalid", message: "Attachment descriptor is invalid" } },
    );

    dto = { ...dto, source: "renderer_path" };
    assert.deepEqual(
      await runtimeRequest?.(trustedEvent, { method: "attachment.open", params: { ref } }),
      { __uthcode_runtime_error: { kind: "attachment_invalid", message: "Attachment descriptor is invalid" } },
    );
    dto = { ...dto, source: "session_attachment", asset_ref: "attachment:wrong:wrong" };
    assert.deepEqual(
      await runtimeRequest?.(trustedEvent, { method: "attachment.open", params: { ref } }),
      { __uthcode_runtime_error: { kind: "attachment_invalid", message: "Attachment descriptor is invalid" } },
    );
    dto = { ...dto, asset_ref: `attachment:${sessionId}:${ref}`, path: join(root, "outside.txt") };
    assert.deepEqual(
      await runtimeRequest?.(trustedEvent, { method: "attachment.open", params: { ref } }),
      { __uthcode_runtime_error: { kind: "attachment_not_authorized", message: "Attachment is not authorized by Desktop" } },
    );

    dto = { ...dto, path: join(derived, "missing.pdf") };
    assert.deepEqual(
      await runtimeRequest?.(trustedEvent, { method: "attachment.open", params: { ref } }),
      { __uthcode_runtime_error: { kind: "attachment_not_found", message: "Attachment file is unavailable" } },
    );

    dto = { ...dto, path: target, kind: "executable", default_action: "reveal" };
    await runtimeRequest?.(trustedEvent, { method: "attachment.open", params: { ref } });
    assert.deepEqual(opened, [target], "executables never invoke the system open action");
    assert.deepEqual(revealed, [target, target]);
  } finally {
    removeHandlers();
    await rm(root, { recursive: true, force: true });
  }
});

test("Main registers one picker-selected external artifact in its production-owned grant", async () => {
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
  const root = await mkdtemp(join(tmpdir(), "uthcode-external-artifact-main-"));
  const external = join(root, "selected.txt");
  const replacement = join(root, "replacement.txt");
  await writeFile(external, "selected");
  await writeFile(replacement, "replacement");
  const opened: string[] = [];
  const runtime = {
    start: async () => undefined,
    request: async (method: string, params: Record<string, unknown>) => ({
      artifact: {
        path: String(params.path),
        name: "selected.txt",
        kind: "file",
        mime_type: "text/plain",
        size_bytes: 8,
        default_action: "open",
        preview_supported: method === "artifact.preview",
      },
    }),
  };
  const removeHandlers = registerIpcHandlers({
    window: { webContents } as never,
    runtime: runtime as never,
    preferences: { read: async () => ({}), write: async () => ({}) } as never,
    rendererEntry: mainFrame.url,
    isPackaged: true,
    ipc: fakeIpc as never,
    showOpenDialog: (async () => ({ canceled: false, filePaths: [external] })) as never,
    openPath: (async (path: string) => { opened.push(path); return ""; }) as never,
  });
  const authorize = handlers.get(IPC_CHANNELS.authorizeExternalArtifact);
  const runtimeRequest = handlers.get(IPC_CHANNELS.runtimeRequest);
  assert.ok(authorize && runtimeRequest);
  try {
    assert.deepEqual(
      await runtimeRequest?.(trustedEvent, { method: "artifact.describe", params: { path: external } }),
      { __uthcode_runtime_error: { kind: "artifact_not_authorized", message: "Artifact is not authorized by Desktop" } },
    );
    assert.deepEqual(
      await runtimeRequest?.(trustedEvent, { method: "artifact.describe", params: { path: "https://example.test/file.txt" } }),
      { __uthcode_runtime_error: { kind: "artifact_invalid", message: "Artifact descriptor is invalid" } },
    );
    assert.equal(await authorize?.(trustedEvent), external);
    const described = await runtimeRequest?.(trustedEvent, { method: "artifact.describe", params: { path: external } });
    assert.equal((described as { artifact: { path: string } }).artifact.path, external);
    await runtimeRequest?.(trustedEvent, { method: "artifact.preview", params: { path: external } });
    await runtimeRequest?.(trustedEvent, { method: "artifact.open", params: { path: external } });
    assert.deepEqual(opened, [external]);
    assert.deepEqual(
      await runtimeRequest?.(trustedEvent, { method: "artifact.open", params: { path: replacement } }),
      { __uthcode_runtime_error: { kind: "artifact_not_authorized", message: "Artifact is not authorized by Desktop" } },
    );
  } finally {
    removeHandlers();
    await rm(root, { recursive: true, force: true });
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

test("desktop preference persistence accepts only UI metadata and never stores a secret sentinel", async () => {
  const directory = await mkdtemp(join(tmpdir(), "uthcode-preference-secret-boundary-"));
  const sentinel = "w04-secret-sentinel";
  const store = new DesktopPreferencesStore(join(directory, "desktop-preferences.json"));
  try {
    await store.write("theme", "dark");
    const content = await readFile(store.filePath, "utf8");
    assert.equal(content.includes(sentinel), false);
    await assert.rejects(
      store.write("api_key" as never, sentinel as never),
      /unknown preference/u,
    );
    assert.equal((await readFile(store.filePath, "utf8")).includes(sentinel), false);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
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
