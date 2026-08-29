import { randomUUID } from "node:crypto";
import { mkdir, open, readFile, rename, rm } from "node:fs/promises";
import { dirname } from "node:path";

import type {
  DesktopPreferences as ApiDesktopPreferences,
  PanelModePreference,
  PreferenceKey,
  RecentProjectPreference,
  ThemePreference,
  WindowBoundsPreference,
} from "./desktop-api";
import { PREFERENCE_KEYS, isPreferenceKey } from "./desktop-api";

type DesktopPreferences = ApiDesktopPreferences;

export const DEFAULT_DESKTOP_PREFERENCES: DesktopPreferences = {
  theme: "system",
  windowBounds: { width: 1280, height: 800, maximized: false },
  panelMode: "docked",
  recentProjects: [],
  projectAliases: {},
  pinnedProjectKeys: [],
  selectedProjectKey: null,
  selectedSessionId: null,
};

const MAX_STRING_LENGTH = 4096;
const MAX_RECENT_PROJECTS = 50;
const MAX_PINNED_PROJECTS = 200;

export class PreferenceValidationError extends Error {
  readonly kind = "invalid_preference";

  constructor(message = "Desktop preference is invalid") {
    super(message);
    this.name = "PreferenceValidationError";
  }
}

function clonePreferences(value: DesktopPreferences): DesktopPreferences {
  return {
    theme: value.theme,
    windowBounds: { ...value.windowBounds },
    panelMode: value.panelMode,
    recentProjects: value.recentProjects.map((item) => ({ ...item })),
    projectAliases: { ...value.projectAliases },
    pinnedProjectKeys: [...value.pinnedProjectKeys],
    selectedProjectKey: value.selectedProjectKey,
    selectedSessionId: value.selectedSessionId,
  };
}

function requireString(value: unknown, field: string, max = MAX_STRING_LENGTH): string {
  if (typeof value !== "string" || value.length === 0 || value.length > max) {
    throw new PreferenceValidationError(`${field} must be a non-empty string`);
  }
  return value;
}

function optionalString(value: unknown, field: string): string | undefined {
  if (value === undefined) return undefined;
  return requireString(value, field);
}

function validateTheme(value: unknown): ThemePreference {
  if (value !== "system" && value !== "dark" && value !== "light") {
    throw new PreferenceValidationError("theme must be system, dark, or light");
  }
  return value;
}

function validatePanelMode(value: unknown): PanelModePreference {
  if (value !== "hidden" && value !== "docked" && value !== "floating") {
    throw new PreferenceValidationError("panelMode is invalid");
  }
  return value;
}

function validateWindowBounds(value: unknown, current?: WindowBoundsPreference): WindowBoundsPreference {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new PreferenceValidationError("windowBounds must be an object");
  }
  const source = value as Record<string, unknown>;
  const allowed = new Set(["x", "y", "width", "height", "maximized"]);
  if (Object.keys(source).some((key) => !allowed.has(key))) {
    throw new PreferenceValidationError("windowBounds has unknown fields");
  }
  const result = { ...(current ?? DEFAULT_DESKTOP_PREFERENCES.windowBounds) };
  for (const field of ["x", "y"] as const) {
    if (source[field] !== undefined) {
      if (typeof source[field] !== "number" || !Number.isFinite(source[field])) {
        throw new PreferenceValidationError(`windowBounds.${field} must be finite`);
      }
      result[field] = source[field];
    }
  }
  for (const field of ["width", "height"] as const) {
    if (source[field] !== undefined) {
      if (
        typeof source[field] !== "number" ||
        !Number.isInteger(source[field]) ||
        source[field] < 200 ||
        source[field] > 10000
      ) {
        throw new PreferenceValidationError(`windowBounds.${field} is out of range`);
      }
      result[field] = source[field];
    }
  }
  if (source.maximized !== undefined) {
    if (typeof source.maximized !== "boolean") {
      throw new PreferenceValidationError("windowBounds.maximized must be boolean");
    }
    result.maximized = source.maximized;
  }
  if (!Number.isInteger(result.width) || !Number.isInteger(result.height)) {
    throw new PreferenceValidationError("windowBounds requires width and height");
  }
  return result;
}

function validateRecentProjects(value: unknown): RecentProjectPreference[] {
  if (!Array.isArray(value) || value.length > MAX_RECENT_PROJECTS) {
    throw new PreferenceValidationError("recentProjects must be a bounded array");
  }
  return value.map((entry, index) => {
    if (typeof entry !== "object" || entry === null || Array.isArray(entry)) {
      throw new PreferenceValidationError(`recentProjects[${index}] must be an object`);
    }
    const source = entry as Record<string, unknown>;
    const allowed = new Set(["path", "alias", "pinned", "lastOpenedAt"]);
    if (Object.keys(source).some((key) => !allowed.has(key))) {
      throw new PreferenceValidationError(`recentProjects[${index}] has unknown fields`);
    }
    const result: RecentProjectPreference = { path: requireString(source.path, `recentProjects[${index}].path`) };
    const alias = optionalString(source.alias, `recentProjects[${index}].alias`);
    const lastOpenedAt = optionalString(source.lastOpenedAt, `recentProjects[${index}].lastOpenedAt`);
    if (alias !== undefined) result.alias = alias;
    if (lastOpenedAt !== undefined) result.lastOpenedAt = lastOpenedAt;
    if (source.pinned !== undefined) {
      if (typeof source.pinned !== "boolean") {
        throw new PreferenceValidationError(`recentProjects[${index}].pinned must be boolean`);
      }
      result.pinned = source.pinned;
    }
    return result;
  });
}

function validateStringMap(value: unknown, field: string): Record<string, string> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new PreferenceValidationError(`${field} must be an object`);
  }
  const result: Record<string, string> = {};
  for (const [key, item] of Object.entries(value)) {
    requireString(key, `${field} key`, 4096);
    result[key] = requireString(item, `${field}.${key}`);
  }
  return result;
}

function validateStringList(value: unknown, field: string): string[] {
  if (!Array.isArray(value) || value.length > MAX_PINNED_PROJECTS) {
    throw new PreferenceValidationError(`${field} must be a bounded array`);
  }
  return value.map((item, index) => requireString(item, `${field}[${index}]`));
}

function validateNullableString(value: unknown, field: string): string | null {
  if (value === null) return null;
  return requireString(value, field);
}

function validateDocument(value: unknown): DesktopPreferences {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new PreferenceValidationError("Desktop preferences must be an object");
  }
  const source = value as Record<string, unknown>;
  if (Object.keys(source).some((key) => !isPreferenceKey(key))) {
    throw new PreferenceValidationError("Desktop preferences contain unknown preference");
  }
  const result = clonePreferences(DEFAULT_DESKTOP_PREFERENCES);
  if (source.theme !== undefined) result.theme = validateTheme(source.theme);
  if (source.windowBounds !== undefined) result.windowBounds = validateWindowBounds(source.windowBounds);
  if (source.panelMode !== undefined) result.panelMode = validatePanelMode(source.panelMode);
  if (source.recentProjects !== undefined) result.recentProjects = validateRecentProjects(source.recentProjects);
  if (source.projectAliases !== undefined) result.projectAliases = validateStringMap(source.projectAliases, "projectAliases");
  if (source.pinnedProjectKeys !== undefined) result.pinnedProjectKeys = validateStringList(source.pinnedProjectKeys, "pinnedProjectKeys");
  if (source.selectedProjectKey !== undefined) result.selectedProjectKey = validateNullableString(source.selectedProjectKey, "selectedProjectKey");
  if (source.selectedSessionId !== undefined) result.selectedSessionId = validateNullableString(source.selectedSessionId, "selectedSessionId");
  return result;
}

export class DesktopPreferencesStore {
  readonly filePath: string;

  constructor(filePath: string) {
    this.filePath = filePath;
  }

  async read(): Promise<DesktopPreferences> {
    let raw: string;
    try {
      raw = await readFile(this.filePath, "utf8");
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") {
        return clonePreferences(DEFAULT_DESKTOP_PREFERENCES);
      }
      return clonePreferences(DEFAULT_DESKTOP_PREFERENCES);
    }
    try {
      return validateDocument(JSON.parse(raw));
    } catch {
      return clonePreferences(DEFAULT_DESKTOP_PREFERENCES);
    }
  }

  async write<K extends PreferenceKey>(key: K, value: DesktopPreferences[K]): Promise<DesktopPreferences> {
    if (!isPreferenceKey(key)) {
      throw new PreferenceValidationError("unknown preference");
    }
    const current = await this.read();
    let normalized: unknown;
    switch (key) {
      case "theme": normalized = validateTheme(value); break;
      case "windowBounds": normalized = validateWindowBounds(value, current.windowBounds); break;
      case "panelMode": normalized = validatePanelMode(value); break;
      case "recentProjects": normalized = validateRecentProjects(value); break;
      case "projectAliases": normalized = validateStringMap(value, key); break;
      case "pinnedProjectKeys": normalized = validateStringList(value, key); break;
      case "selectedProjectKey": normalized = validateNullableString(value, key); break;
      case "selectedSessionId": normalized = validateNullableString(value, key); break;
    }
    const next = { ...current, [key]: normalized } as DesktopPreferences;
    await this.writeDocument(next);
    return clonePreferences(next);
  }

  private async writeDocument(value: DesktopPreferences): Promise<void> {
    const validated = validateDocument(value);
    await mkdir(dirname(this.filePath), { recursive: true });
    const temporaryPath = `${this.filePath}.${process.pid}.${randomUUID()}.tmp`;
    try {
      const handle = await open(temporaryPath, "w");
      try {
        await handle.writeFile(`${JSON.stringify(validated, null, 2)}\n`, "utf8");
        await handle.sync();
      } finally {
        await handle.close();
      }
      await rename(temporaryPath, this.filePath);
    } finally {
      // A failed write/rename must not leave an unbounded collection of
      // preference temp files beside the authoritative document.
      await rm(temporaryPath, { force: true }).catch(() => undefined);
    }
  }
}

export { DesktopPreferencesStore as DesktopPreferences };

export { PREFERENCE_KEYS };
