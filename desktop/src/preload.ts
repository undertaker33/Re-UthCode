import type {
  AgentEvent,
  DesktopApi,
  DesktopPreferences,
  JsonObject,
  JsonValue,
  PreferenceKey,
  RuntimeMethod,
} from "./desktop-api";
import { isJsonObject, isJsonValue, isPreferenceKey, isRuntimeMethod } from "./desktop-api";

type IpcListener = (event: unknown, payload: unknown) => void;

export interface IpcRendererLike {
  invoke(channel: string, ...args: unknown[]): Promise<unknown>;
  on(channel: string, listener: IpcListener): this;
  removeListener(channel: string, listener: IpcListener): this;
}

export interface ContextBridgeLike {
  exposeInMainWorld(name: string, api: DesktopApi): void;
}

function requireJsonObject(value: unknown, field: string): asserts value is JsonObject {
  if (!isJsonObject(value)) throw new TypeError(`${field} must be JSON-safe`);
}

function requireMethod(value: unknown): asserts value is RuntimeMethod {
  if (!isRuntimeMethod(value)) throw new TypeError("runtime method is not supported");
}

function requirePreferenceKey(value: unknown): asserts value is PreferenceKey {
  if (!isPreferenceKey(value)) throw new TypeError("preference key is not supported");
}

function requirePath(value: unknown): asserts value is string {
  if (typeof value !== "string" || value.length === 0) throw new TypeError("project path is invalid");
}

function requireJson(value: unknown, field: string): asserts value is JsonValue {
  if (!isJsonValue(value)) throw new TypeError(`${field} must be JSON-safe`);
}

export function installPreload(
  contextBridge: ContextBridgeLike,
  ipcRenderer: IpcRendererLike,
): DesktopApi {
  const api: DesktopApi = Object.freeze({
    async openProject(): Promise<string | null> {
      const selected = await ipcRenderer.invoke("desktop.project.pick");
      if (selected !== null && typeof selected !== "string") {
        throw new TypeError("project picker returned an invalid path");
      }
      return selected;
    },
    async openProjectInExplorer(projectPath: string): Promise<void> {
      requirePath(projectPath);
      await ipcRenderer.invoke("desktop.project.explorer", projectPath);
    },
    async requestRuntime(method: RuntimeMethod, params: JsonObject): Promise<JsonValue> {
      requireMethod(method);
      requireJsonObject(params, "runtime params");
      const result = await ipcRenderer.invoke("desktop.runtime.request", { method, params });
      requireJson(result, "runtime response");
      return result;
    },
    subscribeAgentEvents: (listener: (event: AgentEvent) => void) => {
      if (typeof listener !== "function") throw new TypeError("event listener is invalid");
      const wrapped: IpcListener = (_event, payload) => {
        if (!isJsonObject(payload) || typeof payload.type !== "string") return;
        listener(payload as AgentEvent);
      };
      ipcRenderer.on("desktop.runtime.event", wrapped);
      return () => {
        ipcRenderer.removeListener("desktop.runtime.event", wrapped);
      };
    },
    async readPreference<K extends PreferenceKey>(key: K): Promise<DesktopPreferences[K]> {
      requirePreferenceKey(key);
      const value = await ipcRenderer.invoke("desktop.preference.read", key);
      requireJson(value, "preference response");
      return value as DesktopPreferences[K];
    },
    async writePreference<K extends PreferenceKey>(key: K, value: DesktopPreferences[K]): Promise<DesktopPreferences> {
      requirePreferenceKey(key);
      requireJson(value, "preference value");
      const next = await ipcRenderer.invoke("desktop.preference.write", key, value);
      requireJsonObject(next, "preference response");
      return next as unknown as DesktopPreferences;
    },
  });
  contextBridge.exposeInMainWorld("uthcode", api);
  return api;
}

interface ElectronBindings {
  contextBridge?: ContextBridgeLike;
  ipcRenderer?: IpcRendererLike;
}

function loadElectronBindings(): ElectronBindings | null {
  try {
    // Electron's sandboxed preload still provides the electron built-in. When
    // this module is imported by Node tests, require("electron") is a binary
    // path string, so it is deliberately ignored.
    const bindings = require("electron") as ElectronBindings;
    if (bindings && typeof bindings === "object" && bindings.contextBridge && bindings.ipcRenderer) {
      return bindings;
    }
  } catch {
    // The preload is also imported as a pure module by offline tests.
  }
  return null;
}

const electronBindings = loadElectronBindings();
if (electronBindings?.contextBridge && electronBindings.ipcRenderer) {
  installPreload(electronBindings.contextBridge, electronBindings.ipcRenderer);
}
