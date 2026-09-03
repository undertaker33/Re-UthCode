import { app, BrowserWindow, clipboard, dialog, ipcMain, Menu, nativeTheme, shell } from "electron";
import type { IpcMainInvokeEvent } from "electron";
import squirrelStartup from "electron-squirrel-startup";
import { stat } from "node:fs/promises";
import { isAbsolute, resolve, join } from "node:path";

// Squirrel.Windows starts the app with a short-lived lifecycle argument while
// installing, updating, or uninstalling.  Handle it before registering the
// normal window/runtime lifecycle so those helper launches never spawn Python.
const isSquirrelLifecycleLaunch = squirrelStartup;
if (isSquirrelLifecycleLaunch) app.quit();

import {
  isJsonObject,
  isJsonValue,
  isPreferenceKey,
  isRuntimeMethod,
  type AgentEvent,
  type DesktopPreferences,
  type PreferenceKey,
} from "./desktop-api";
import {
  DesktopPreferencesStore,
} from "./desktop-preferences";
import {
  PythonRuntime,
  type PythonRuntimeOptions,
  resolvePythonLaunch,
  RuntimeBoundaryError,
  RuntimeRequestError,
} from "./python-runtime";

declare const MAIN_WINDOW_WEBPACK_ENTRY: string;
declare const MAIN_WINDOW_PRELOAD_WEBPACK_ENTRY: string;
declare const UTHCODE_DESKTOP_MAIN_BUNDLE: boolean;

const RENDERER_ENTRY = () =>
  typeof MAIN_WINDOW_WEBPACK_ENTRY === "undefined" ? "" : MAIN_WINDOW_WEBPACK_ENTRY;
const PRELOAD_ENTRY = () =>
  typeof MAIN_WINDOW_PRELOAD_WEBPACK_ENTRY === "undefined"
    ? ""
    : MAIN_WINDOW_PRELOAD_WEBPACK_ENTRY;

export const IPC_CHANNELS = Object.freeze({
  pickProject: "desktop.project.pick",
  openProjectInExplorer: "desktop.project.explorer",
  copyText: "desktop.clipboard.copy-text",
  closeShell: "desktop.shell.close",
  runtimeRequest: "desktop.runtime.request",
  runtimeEvent: "desktop.runtime.event",
  preferenceRead: "desktop.preference.read",
  preferenceWrite: "desktop.preference.write",
});

export class MainBoundaryError extends Error {
  readonly kind: string;

  constructor(kind: string, message: string) {
    super(message);
    this.name = "MainBoundaryError";
    this.kind = kind;
  }
}

export function isAllowedRendererUrl(url: string, rendererEntry: string, isPackaged: boolean): boolean {
  if (typeof url !== "string" || typeof rendererEntry !== "string" || !rendererEntry) return false;
  try {
    const candidate = new URL(url);
    const expected = new URL(rendererEntry);
    if (candidate.protocol !== expected.protocol) return false;
    if (candidate.host !== expected.host) return false;
    if (isPackaged || expected.protocol === "file:") {
      return candidate.protocol === "file:" && candidate.pathname === expected.pathname;
    }
    return candidate.origin === expected.origin;
  } catch {
    return false;
  }
}

export function getSecureWebPreferences(preload: string) {
  return {
    preload,
    nodeIntegration: false,
    contextIsolation: true,
    sandbox: true,
    webviewTag: false,
    webSecurity: true,
    allowRunningInsecureContent: false,
  } as const;
}

function assertTrustedRenderer(
  event: IpcMainInvokeEvent,
  window: BrowserWindow,
  rendererEntry: string,
  isPackaged: boolean,
): void {
  if (event.sender !== window.webContents) {
    throw new MainBoundaryError("untrusted_sender", "Desktop IPC sender is not trusted");
  }
  const frame = event.senderFrame;
  if (!frame || frame !== event.sender.mainFrame) {
    throw new MainBoundaryError("untrusted_frame", "Desktop IPC frame is not trusted");
  }
  if (!isAllowedRendererUrl(frame.url, rendererEntry, isPackaged)) {
    throw new MainBoundaryError("untrusted_origin", "Desktop IPC origin is not trusted");
  }
}

function canonicalProjectPath(value: unknown): string {
  if (typeof value !== "string" || !value.trim() || !isAbsolute(value)) {
    throw new MainBoundaryError("invalid_project_path", "Project path must be absolute");
  }
  return resolve(value);
}

function registeredProjectPath(value: unknown, registeredProjects: Set<string>): string {
  const path = canonicalProjectPath(value);
  if (!registeredProjects.has(path)) {
    throw new MainBoundaryError(
      "project_not_registered",
      "Project must be selected or restored from trusted Desktop history before use",
    );
  }
  return path;
}

function canonicalizeRecentProjects(
  value: unknown,
  registeredProjects: Set<string>,
): unknown {
  if (!Array.isArray(value)) return value;
  return value.map((entry) => {
    if (typeof entry !== "object" || entry === null || Array.isArray(entry)) return entry;
    const source = entry as Record<string, unknown>;
    if (typeof source.path !== "string") return entry;
    const path = registeredProjectPath(source.path, registeredProjects);
    return { ...source, path };
  });
}

/** Restore only persisted, existing project directories into Main authority. */
export async function hydrateRegisteredProjectsFromPreferences(
  preferences: Pick<DesktopPreferences, "recentProjects">,
  registeredProjects: Set<string>,
): Promise<void> {
  registeredProjects.clear();
  for (const recent of preferences.recentProjects) {
    try {
      const path = canonicalProjectPath(recent.path);
      if ((await stat(path)).isDirectory()) registeredProjects.add(path);
    } catch {
      // Stale, malformed, or deleted recent entries are advisory metadata;
      // they never become trusted project identities.
    }
  }
}

function assertPreferenceKey(value: unknown): asserts value is PreferenceKey {
  if (!isPreferenceKey(value)) {
    throw new MainBoundaryError("invalid_preference", "Desktop preference key is not supported");
  }
}

interface MainIpcOptions {
  window: BrowserWindow;
  runtime: PythonRuntime;
  preferences: DesktopPreferencesStore;
  rendererEntry: string;
  isPackaged: boolean;
  showOpenDialog?: typeof dialog.showOpenDialog;
  openPath?: typeof shell.openPath;
  registeredProjects?: Set<string>;
  closeShell?: () => void;
  ipc?: Pick<typeof ipcMain, "handle" | "removeHandler">;
  setNativeTheme?: (theme: DesktopPreferences["theme"]) => void;
  writeClipboard?: (value: string) => void;
}

export function registerIpcHandlers(options: MainIpcOptions): () => void {
  const registeredProjects = options.registeredProjects ?? new Set<string>();
  const assertSender = (event: IpcMainInvokeEvent) =>
    assertTrustedRenderer(event, options.window, options.rendererEntry, options.isPackaged);
  const showOpenDialog = options.showOpenDialog ?? dialog.showOpenDialog;
  const openPath = options.openPath ?? shell.openPath;
  const ipc = options.ipc ?? ipcMain;
  const closeShell = options.closeShell ?? beginApplicationShutdown;
  const setNativeTheme = options.setNativeTheme ?? ((theme: DesktopPreferences["theme"]) => { nativeTheme.themeSource = theme; });
  const writeClipboard = options.writeClipboard ?? ((value: string) => clipboard.writeText(value));

  const onPickProject = async (event: IpcMainInvokeEvent): Promise<string | null> => {
    assertSender(event);
    const result = await showOpenDialog(options.window, {
      properties: ["openDirectory"],
      title: "Open UthCode project",
    });
    if (result.canceled || result.filePaths.length === 0) return null;
    const selected = canonicalProjectPath(result.filePaths[0]);
    registeredProjects.add(selected);
    return selected;
  };

  const onOpenProjectInExplorer = async (event: IpcMainInvokeEvent, value: unknown): Promise<void> => {
    assertSender(event);
    const selected = canonicalProjectPath(value);
    if (!registeredProjects.has(selected)) {
      throw new MainBoundaryError("project_not_registered", "Project must be selected before opening Explorer");
    }
    const failure = await openPath(selected);
    if (failure) throw new MainBoundaryError("explorer_open_failed", "Project Explorer action failed");
  };

  const onCopyText = async (event: IpcMainInvokeEvent, value: unknown): Promise<void> => {
    assertSender(event);
    if (typeof value !== "string" || value.length > 1_000_000) {
      throw new MainBoundaryError("invalid_copy_text", "Clipboard text is invalid");
    }
    try {
      writeClipboard(value);
    } catch {
      throw new MainBoundaryError("clipboard_write_failed", "Clipboard text could not be copied");
    }
  };

  const onCloseShell = async (event: IpcMainInvokeEvent): Promise<void> => {
    assertSender(event);
    closeShell();
  };

  const onRuntimeRequest = async (
    event: IpcMainInvokeEvent,
    payload: unknown,
  ): Promise<unknown> => {
    assertSender(event);
    if (!isJsonObject(payload) || Object.keys(payload).some((key) => key !== "method" && key !== "params")) {
      throw new MainBoundaryError("invalid_runtime_request", "Runtime request must contain method and params");
    }
    if (!isRuntimeMethod(payload.method) || !isJsonObject(payload.params)) {
      throw new MainBoundaryError("invalid_runtime_request", "Runtime request is invalid");
    }
    let requestParams = payload.params;
    if (payload.method === "session.move") {
      const targetProject = registeredProjectPath(payload.params.target_project_key, registeredProjects);
      // Pass the same canonical identity that was checked against Main's
      // registration set.  The Python Bridge still repeats its own path
      // validation as a defense-in-depth boundary.
      requestParams = { ...payload.params, target_project_key: targetProject };
    } else if (payload.method === "runtime.initialize") {
      const field = "workdir" in payload.params
        ? "workdir"
        : "cwd" in payload.params
          ? "cwd"
          : undefined;
      if (field === undefined) {
        throw new MainBoundaryError(
          "invalid_project_path",
          "Runtime initialization requires a registered Project",
        );
      }
      const projectPath = registeredProjectPath(payload.params[field], registeredProjects);
      requestParams = { ...payload.params, [field]: projectPath };
    } else if (payload.method === "project.open") {
      const projectPath = registeredProjectPath(payload.params.path, registeredProjects);
      // Opening is a consumer of Main authority.  It never creates trust;
      // new projects must first pass through the Main folder picker.
      requestParams = { ...payload.params, path: projectPath };
    }
    try {
      await options.runtime.start();
      const request = options.runtime.request(payload.method, requestParams);
      if (payload.method === "runtime.shutdown") {
        let result;
        try {
          result = await request;
        } finally {
          // The Bridge response only acknowledges its close request. Keep
          // the child owned until its close/reap event is observed so a
          // following initialize cannot race a still-live process.
          await options.runtime.shutdownAfterRequest();
        }
        return result;
      }
      return await request;
    } catch (error) {
      if (error instanceof RuntimeBoundaryError || error instanceof RuntimeRequestError) throw error;
      throw new MainBoundaryError("runtime_error", "Desktop Runtime request failed");
    }
  };

  const onReadPreference = async (event: IpcMainInvokeEvent, key: unknown): Promise<unknown> => {
    assertSender(event);
    assertPreferenceKey(key);
    const preferences = await options.preferences.read();
    return preferences[key];
  };

  const onWritePreference = async (
    event: IpcMainInvokeEvent,
    key: unknown,
    value: unknown,
  ): Promise<DesktopPreferences> => {
    assertSender(event);
    assertPreferenceKey(key);
    if (!isJsonValue(value)) throw new MainBoundaryError("invalid_preference", "Desktop preference value is invalid");
    const safeValue = key === "recentProjects"
      ? canonicalizeRecentProjects(value, registeredProjects)
      : value;
    const written = await options.preferences.write(key, safeValue as never);
    if (key === "theme") setNativeTheme(written.theme);
    return written;
  };

  ipc.handle(IPC_CHANNELS.pickProject, onPickProject);
  ipc.handle(IPC_CHANNELS.openProjectInExplorer, onOpenProjectInExplorer);
  ipc.handle(IPC_CHANNELS.copyText, onCopyText);
  ipc.handle(IPC_CHANNELS.closeShell, onCloseShell);
  ipc.handle(IPC_CHANNELS.runtimeRequest, onRuntimeRequest);
  ipc.handle(IPC_CHANNELS.preferenceRead, onReadPreference);
  ipc.handle(IPC_CHANNELS.preferenceWrite, onWritePreference);

  return () => {
    for (const channel of Object.values(IPC_CHANNELS)) {
      if (channel !== IPC_CHANNELS.runtimeEvent) ipc.removeHandler(channel);
    }
  };
}

let mainWindow: BrowserWindow | undefined;
let runtime: PythonRuntime | undefined;
let preferences: DesktopPreferencesStore | undefined;
let removeIpcHandlers: (() => void) | undefined;
let closing = false;
let closeRequested = false;
const registeredProjects = new Set<string>();

interface RuntimeApplicationLike {
  readonly isPackaged: boolean;
}

interface RuntimeWindowLike {
  isDestroyed(): boolean;
  webContents: Pick<BrowserWindow["webContents"], "send">;
}

interface CreateRuntimeOptions {
  application?: RuntimeApplicationLike;
  window?: RuntimeWindowLike;
  pythonExecutable?: string;
  resourcesPath?: string;
  platform?: NodeJS.Platform;
  runtimeFactory?: (options: PythonRuntimeOptions) => PythonRuntime;
}

function safeRuntimeDiagnostic(_line: string): AgentEvent {
  // Bridge stderr is a diagnostic channel, not a renderer data channel. Keep
  // its occurrence observable while never copying arbitrary exception text,
  // credentials, or other native process data into the renderer.
  return {
    type: "runtime_diagnostic",
    message: "Python Runtime emitted a diagnostic",
  };
}

export function createRuntime(options: CreateRuntimeOptions = {}): PythonRuntime {
  const application = options.application ?? app;
  const getTargetWindow = () => options.window ?? mainWindow;
  const launch = resolvePythonLaunch({
    mode: application.isPackaged ? "production" : "development",
    pythonExecutable: options.pythonExecutable ?? process.env.UTHCODE_PYTHON,
    resourcesPath: options.resourcesPath ?? process.resourcesPath,
    platform: options.platform ?? process.platform,
  });
  const runtimeOptions: PythonRuntimeOptions = {
    launch,
    onAgentEvent: (event) => {
      const targetWindow = getTargetWindow();
      if (targetWindow && !targetWindow.isDestroyed()) {
        targetWindow.webContents.send(IPC_CHANNELS.runtimeEvent, event);
      }
    },
    onRuntimeState: (state) => {
      const targetWindow = getTargetWindow();
      if (targetWindow && !targetWindow.isDestroyed()) {
        targetWindow.webContents.send(IPC_CHANNELS.runtimeEvent, {
          type: "runtime_state",
          state,
        });
      }
    },
    onDiagnostic: (line) => {
      const targetWindow = getTargetWindow();
      if (targetWindow && !targetWindow.isDestroyed()) {
        targetWindow.webContents.send(IPC_CHANNELS.runtimeEvent, safeRuntimeDiagnostic(line));
      }
    },
  };
  return options.runtimeFactory?.(runtimeOptions) ?? new PythonRuntime(runtimeOptions);
}

async function closeRuntime(): Promise<void> {
  if (runtime) await runtime.shutdown();
}

function beginApplicationShutdown(): void {
  if (closeRequested) return;
  closeRequested = true;
  void closeRuntime()
    .then(() => {
      closing = true;
      if (mainWindow && !mainWindow.isDestroyed()) mainWindow.close();
      else app.quit();
    })
    .catch(() => {
      // PythonRuntime keeps ownership when close/reap is unconfirmed. Keep
      // the window open and allow a later bounded retry instead of quitting
      // Electron with an unknown child still attached.
      closeRequested = false;
    });
}

function createMainWindow(): BrowserWindow {
  const window = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    backgroundColor: nativeTheme.shouldUseDarkColors ? "#1d1d1f" : "#f5f5f7",
    autoHideMenuBar: true,
    webPreferences: getSecureWebPreferences(PRELOAD_ENTRY()),
  });
  const rendererEntry = RENDERER_ENTRY();
  window.webContents.on("will-navigate", (event, url) => {
    if (!isAllowedRendererUrl(url, rendererEntry, app.isPackaged)) event.preventDefault();
  });
  window.webContents.on("will-frame-navigate", (details) => {
    if (
      !details.isMainFrame ||
      !isAllowedRendererUrl(details.url, rendererEntry, app.isPackaged)
    ) {
      details.preventDefault();
    }
  });
  window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  window.webContents.on("will-attach-webview", (event) => event.preventDefault());
  window.on("close", (event) => {
    if (closing) return;
    event.preventDefault();
    beginApplicationShutdown();
  });
  window.loadURL(rendererEntry);
  return window;
}

export function bootstrapMain(): void {
  app.whenReady().then(async () => {
    preferences = new DesktopPreferencesStore(join(app.getPath("userData"), "desktop-preferences.json"));
    runtime = createRuntime();
    const initialPreferences = await preferences.read();
    await hydrateRegisteredProjectsFromPreferences(initialPreferences, registeredProjects);
    nativeTheme.themeSource = initialPreferences.theme;
    Menu.setApplicationMenu(null);
    mainWindow = createMainWindow();
    removeIpcHandlers = registerIpcHandlers({
      window: mainWindow,
      runtime,
      preferences,
      rendererEntry: RENDERER_ENTRY(),
      isPackaged: app.isPackaged,
      registeredProjects,
    });
  });

  app.on("before-quit", (event) => {
    if (!closeRequested && !closing) {
      event.preventDefault();
      beginApplicationShutdown();
    }
  });
  app.on("will-quit", () => removeIpcHandlers?.());
  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") app.quit();
  });
}

// Webpack's Electron main bundle is the process entry point, but its generated
// module wrapper does not provide a stable Node entry identity. The explicit
// DefinePlugin flag is replaced with `true` only in the production/main
// bundle; importing helpers in unit tests remains inert.
if (
  typeof UTHCODE_DESKTOP_MAIN_BUNDLE !== "undefined" &&
  UTHCODE_DESKTOP_MAIN_BUNDLE &&
  !isSquirrelLifecycleLaunch
) {
  bootstrapMain();
}
