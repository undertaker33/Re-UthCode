import type { LanguagePreference, ThemePreference } from "../desktop-api";
import type { ConfigurationView } from "./state";

/** The JSON-shaped candidate accepted by the existing Configuration write. */
export interface ConfigurationWrite {
  default_model?: string;
  default_permission_mode?: "default" | "auto";
  providers?: Record<string, Record<string, unknown>>;
  models?: Record<string, Record<string, unknown>>;
}

export type SettingsCategory = "providers" | "defaults" | "interface" | "about";

export function configurationRequest(value: ConfigurationWrite): ConfigurationWrite {
  const request: ConfigurationWrite = {};
  if (value.default_model !== undefined) request.default_model = value.default_model;
  if (value.default_permission_mode !== undefined) request.default_permission_mode = value.default_permission_mode;
  if (value.providers) request.providers = Object.fromEntries(Object.entries(value.providers).map(([key, profile]) => [key, { ...profile }]));
  if (value.models) request.models = Object.fromEntries(Object.entries(value.models).map(([key, profile]) => [key, { ...profile }]));
  return request;
}

export function normalizeOptionalText(value: unknown): unknown {
  if (typeof value !== "string") return value;
  const normalized = value.trim();
  return normalized || null;
}

/**
 * Build the only settings write shape that can carry a candidate API key.
 *
 * Secret values are supplied separately from the non-secret draft. This
 * helper deliberately never copies a revealed value from a provider profile;
 * only an explicit touched replacement can add `api_key` to the request.
 */
export function settingsSaveRequest(
  draft: ConfigurationWrite,
  replacementKeys: Record<string, string>,
  touchedKeys: Record<string, boolean>,
): ConfigurationWrite {
  return configurationRequest({
    ...draft,
    providers: Object.fromEntries(Object.entries(draft.providers ?? {}).map(([id, profile]) => {
      const next = { ...profile };
      if (Object.prototype.hasOwnProperty.call(next, "base_url")) next.base_url = normalizeOptionalText(next.base_url);
      if (Object.prototype.hasOwnProperty.call(next, "display_name")) next.display_name = normalizeOptionalText(next.display_name);
      delete next.api_key_configured;
      delete next.api_key;
      if (touchedKeys[id]) next.api_key = replacementKeys[id] ?? "";
      return [id, next];
    })),
    models: draft.models
      ? Object.fromEntries(Object.entries(draft.models).map(([ref, profile]) => {
        const next = { ...profile };
        if (Object.prototype.hasOwnProperty.call(next, "display_name")) next.display_name = normalizeOptionalText(next.display_name);
        return [ref, next];
      }))
      : draft.models,
  });
}

export function withoutRecordKey<T>(record: Record<string, T>, key: string): Record<string, T> {
  const next = { ...record };
  delete next[key];
  return next;
}

export function parseOptionalPositiveInteger(value: string): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

export function stringValue(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

export function sourceConfig(value: ConfigurationView | null): ConfigurationWrite {
  const providers: Record<string, Record<string, unknown>> = {};
  for (const [id, raw] of Object.entries(value?.providers ?? {})) {
    const profile = raw as Record<string, unknown>;
    providers[id] = {
      kind: stringValue(profile.kind, "openai_compat"),
      base_url: typeof profile.base_url === "string" && profile.base_url ? profile.base_url : null,
      display_name: typeof profile.display_name === "string" && profile.display_name ? profile.display_name : null,
      api_key_configured: profile.api_key_configured === true,
    };
  }
  const models: Record<string, Record<string, unknown>> = {};
  for (const [ref, raw] of Object.entries(value?.models ?? {})) {
    const profile = raw as Record<string, unknown>;
    models[ref] = {
      provider_profile_id: stringValue(profile.provider_profile_id),
      remote_id: stringValue(profile.remote_id),
      display_name: typeof profile.display_name === "string" && profile.display_name ? profile.display_name : null,
      context_window: profile.context_window ?? null,
      max_output_tokens: profile.max_output_tokens ?? null,
      reasoning_effort: profile.reasoning_effort ?? null,
    };
  }
  const requestedDefault = stringValue(value?.default_model);
  const defaultModel = requestedDefault && models[requestedDefault] ? requestedDefault : Object.keys(models)[0] ?? "";
  return {
    default_model: defaultModel,
    default_permission_mode: value?.default_permission_mode === "auto" ? "auto" : "default",
    providers,
    models,
  };
}

export function updateRecord(
  record: Record<string, Record<string, unknown>> | undefined,
  key: string,
  field: string,
  value: unknown,
): Record<string, Record<string, unknown>> {
  return { ...(record ?? {}), [key]: { ...(record?.[key] ?? {}), [field]: value } };
}

export function modalFocusableElements(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), [role="button"]:not([aria-disabled="true"]), summary, [tabindex]:not([tabindex="-1"])')).filter((element) => !element.hasAttribute("hidden"));
}

export function modelFieldId(prefix: string, ref: string, field: string): string {
  const encoded = ref.length === 0 ? "empty" : ref.split("").map((unit) => unit.charCodeAt(0).toString(16).padStart(4, "0")).join("-");
  return `${prefix}-${encoded}-${field}`;
}

export function providerModels(draft: ConfigurationWrite, providerId: string): Array<[string, Record<string, unknown>]> {
  return Object.entries(draft.models ?? {}).filter(([, model]) => model.provider_profile_id === providerId);
}

let generatedModelSerial = 0;
export function createInternalModelRef(existing: Record<string, Record<string, unknown>>): string {
  let ref = "";
  do {
    generatedModelSerial += 1;
    ref = `__uthcode_model_${generatedModelSerial}`;
  } while (existing[ref] !== undefined);
  return ref;
}

export function modelLabel(model: Record<string, unknown> | undefined, unnamed: string): string {
  const displayName = stringValue(model?.display_name).trim();
  const remoteId = stringValue(model?.remote_id).trim();
  return displayName || remoteId || unnamed;
}

export function modelRemoteLabel(model: Record<string, unknown> | undefined, unnamed: string): string {
  const remoteId = stringValue(model?.remote_id).trim();
  return remoteId || unnamed;
}

export function providerLabel(providerId: string, provider: Record<string, unknown> | undefined): string {
  return stringValue(provider?.display_name).trim() || providerId;
}

// Keep the imports used by SettingsView's public callback contract in one
// small, dependency-free module. These aliases are types only and disappear
// from the renderer bundle.
export type SettingsTheme = ThemePreference;
export type SettingsLanguage = LanguagePreference;
