/** JSON values are the only values that may cross the Renderer boundary. */
export type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = { [key: string]: JsonValue };

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
  "turn.start",
  "turn.steer",
  "turn.pause",
  "turn.resume",
  "turn.cancel",
  "command.complete",
  "command.execute",
  "status.get",
  "settings.get",
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
  if (Array.isArray(value)) return value.every((item) => isJsonValue(item, seen));
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) return false;
  return Object.entries(value).every(
    ([key, item]) => typeof key === "string" && isJsonValue(item, seen),
  );
}

export function isJsonObject(value: unknown): value is JsonObject {
  return isJsonValue(value) && typeof value === "object" && value !== null && !Array.isArray(value);
}

declare global {
  interface Window {
    uthcode: DesktopApi;
  }
}
