/** JSON values are the only values that may cross the Renderer boundary. */
export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

/**
 * Typed result of the Desktop command boundary.
 *
 * Application command handlers may keep their human-readable output for
 * CLI/TUI callers, but Desktop never receives that free-form text.  The
 * Bridge projects one canonical command, stable semantic code, narrow JSON
 * params, and an optional interface-neutral action instead.
 */
export type DesktopCommandStatus = "success" | "usage_error" | "unknown_command" | "execution_error";
export interface DesktopCommandResult {
  command: string;
  status: DesktopCommandStatus;
  code: string;
  params: JsonObject;
  ui_action: JsonObject | null;
}

export type ThemePreference = "system" | "dark" | "light";
export type LanguagePreference = "zh-CN" | "en";
export type PanelModePreference = "hidden" | "docked" | "floating";

export interface WindowBoundsPreference {
  x?: number;
  y?: number;
  width: number;
  height: number;
  maximized: boolean;
}

export interface RecentProjectPreference {
  path: string;
  alias?: string;
  pinned?: boolean;
  lastOpenedAt?: string;
}
export interface PinnedSessionPreference { projectKey: string; sessionId: string; }

export interface DesktopPreferences {
  theme: ThemePreference;
  language: LanguagePreference;
  windowBounds: WindowBoundsPreference;
  panelMode: PanelModePreference;
  recentProjects: RecentProjectPreference[];
  projectAliases: Record<string, string>;
  pinnedProjectKeys: string[];
  pinnedSessions: PinnedSessionPreference[];
  /** UI-only per-project Session tree expansion state; never a trust source. */
  expandedProjects: Record<string, boolean>;
  selectedProjectKey: string | null;
  selectedSessionId: string | null;
}

export const PREFERENCE_KEYS = [
  "theme",
  "language",
  "windowBounds",
  "panelMode",
  "recentProjects",
  "projectAliases",
  "pinnedProjectKeys",
  "pinnedSessions",
  "expandedProjects",
  "selectedProjectKey",
  "selectedSessionId",
] as const;

export type PreferenceKey = (typeof PREFERENCE_KEYS)[number];

export const RUNTIME_METHODS = [
  "runtime.initialize",
  "runtime.shutdown",
  "project.open",
  "project.sessions",
  "session.new",
  "session.resume",
  "session.rename",
  "session.move",
  "turn.start",
  "turn.steer",
  "turn.pause",
  "turn.resume",
  "turn.cancel",
  "command.complete",
  "command.execute",
  "status.get",
  "settings.get",
  "settings.reveal_api_key",
  "settings.save",
] as const;

export type RuntimeMethod = (typeof RUNTIME_METHODS)[number];

export interface AgentEvent {
  type: string;
  [key: string]: JsonValue;
}

export interface DesktopApi {
  openProject(): Promise<string | null>;
  openProjectInExplorer(projectPath: string): Promise<void>;
  copySessionId(sessionId: string): Promise<void>;
  closeShell(): Promise<void>;
  requestRuntime(method: RuntimeMethod, params: JsonObject): Promise<JsonValue>;
  subscribeAgentEvents(listener: (event: AgentEvent) => void): () => void;
  readPreference<K extends PreferenceKey>(key: K): Promise<DesktopPreferences[K]>;
  writePreference<K extends PreferenceKey>(
    key: K,
    value: DesktopPreferences[K],
  ): Promise<DesktopPreferences>;
}

export function isPreferenceKey(value: unknown): value is PreferenceKey {
  return typeof value === "string" && (PREFERENCE_KEYS as readonly string[]).includes(value);
}

export function isRuntimeMethod(value: unknown): value is RuntimeMethod {
  return typeof value === "string" && (RUNTIME_METHODS as readonly string[]).includes(value);
}

export function isJsonValue(value: unknown, seen = new Set<object>()): value is JsonValue {
  if (value === null || typeof value === "string" || typeof value === "boolean") return true;
  if (typeof value === "number") return Number.isFinite(value);
  if (typeof value !== "object") return false;
  if (seen.has(value)) return false;
  seen.add(value);
  try {
    if (Array.isArray(value)) return value.every((item) => isJsonValue(item, seen));
    const prototype = Object.getPrototypeOf(value);
    if (prototype !== Object.prototype && prototype !== null) return false;
    return Object.entries(value).every(
      ([key, item]) => typeof key === "string" && isJsonValue(item, seen),
    );
  } finally {
    // ``seen`` tracks the current recursion path, not every object visited.
    // Shared JSON sub-objects are valid; only a back-edge is a cycle.
    seen.delete(value);
  }
}

export function isJsonObject(value: unknown): value is JsonObject {
  return isJsonValue(value) && typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isDesktopCommandResult(value: unknown): value is DesktopCommandResult {
  if (!isJsonObject(value)) return false;
  const allowed = new Set(["command", "status", "code", "params", "ui_action"]);
  if (Object.keys(value).some((key) => !allowed.has(key))) return false;
  const status = value.status;
  const action = value.ui_action;
  return typeof value.command === "string"
    && value.command.length > 0
    && (status === "success" || status === "usage_error" || status === "unknown_command" || status === "execution_error")
    && typeof value.code === "string"
    && value.code.length > 0
    && isJsonObject(value.params)
    && (action === null || isJsonObject(action));
}

declare global {
  interface Window {
    uthcode: DesktopApi;
  }
}
