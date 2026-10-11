import type { ConfigurationView } from "./state";

/** A partial, field-owned patch accepted by the user-configuration writer. */
export interface ConfigurationWrite {
  default_model?: string;
  default_permission_mode?: "default" | "auto";
  providers?: Record<string, Record<string, unknown> | null>;
  models?: Record<string, Record<string, unknown> | null>;
  search?: Record<string, unknown>;
  tool_limits?: Record<string, unknown>;
  provider_renames?: Record<string, string>;
}

export interface PendingConfigurationWrite {
  identity: string;
  request: ConfigurationWrite;
  revision: number;
}

export function configurationWriteIdentities(request: ConfigurationWrite): string[] {
  const identities: string[] = [];
  if (Object.hasOwn(request, "default_model")) identities.push("default_model");
  if (Object.hasOwn(request, "default_permission_mode")) identities.push("default_permission_mode");
  for (const field of Object.keys(request.search ?? {})) identities.push(`search.${field}`);
  for (const field of Object.keys(request.tool_limits ?? {})) identities.push(`tool_limits.${field}`);
  for (const field of Object.keys(request.providers ?? {})) identities.push(`providers.${field}`);
  for (const field of Object.keys(request.models ?? {})) identities.push(`models.${field}`);
  for (const field of Object.keys(request.provider_renames ?? {})) identities.push(`provider_renames.${field}`);
  return identities.length ? identities : ["configuration"];
}

/** Renderer-owned values always contain profiles; null is reserved for an explicit write deletion. */
export type SettingsDraft = Omit<ConfigurationWrite, "providers" | "models"> & {
  providers?: Record<string, Record<string, unknown>>;
  models?: Record<string, Record<string, unknown>>;
};

export type SettingsCategory = "providers" | "general" | "tools" | "security" | "appearance" | "archive";

export function normalizeOptionalText(value: unknown): unknown {
  if (typeof value !== "string") return value;
  const normalized = value.trim();
  return normalized || null;
}

export function providerGroupIsValid(draft: SettingsDraft, providerId: string): boolean {
  const models = Object.entries(draft.models ?? {});
  if (models.length === 0) return false;
  if (draft.default_model && !draft.models?.[draft.default_model]) return false;
  return models.every(([, model]) => typeof model.provider_profile_id === "string"
    && Boolean(draft.providers?.[model.provider_profile_id])
    && typeof model.remote_id === "string"
    && Boolean(model.remote_id.trim())
    && (model.provider_profile_id !== providerId || Boolean(draft.providers?.[providerId])));
}

/** Build one Provider and its associated Model changes for the editor Apply. */
export function providerGroupSaveRequest(
  before: SettingsDraft,
  draft: SettingsDraft,
  providerId: string,
  replacementKey = "",
  replacementTouched = false,
): ConfigurationWrite {
  const request: ConfigurationWrite = {};
  const provider = draft.providers?.[providerId];
  if (!provider) {
    request.providers = { [providerId]: null };
  } else {
    const profile: Record<string, unknown> = {
      kind: provider.kind,
      base_url: normalizeOptionalText(provider.base_url),
      display_name: normalizeOptionalText(provider.display_name),
    };
    // Revealed credentials are never copied from the draft. Only an explicit
    // replacement field can cross the settings boundary.
    if (replacementTouched) profile.api_key = replacementKey;
    request.providers = { [providerId]: profile };
  }

  const priorRefs = Object.entries(before.models ?? {})
    .filter(([, model]) => model?.provider_profile_id === providerId)
    .map(([ref]) => ref);
  const currentModels = draft.models ?? {};
  const currentRefs = Object.entries(currentModels)
    .filter(([, model]) => model?.provider_profile_id === providerId);
  const models: Record<string, Record<string, unknown> | null> = {};
  for (const modelRef of priorRefs) {
    if (!currentModels[modelRef]) models[modelRef] = null;
  }
  for (const [modelRef, model] of currentRefs) {
    if (!model) continue;
    models[modelRef] = {
      provider_profile_id: model.provider_profile_id,
      remote_id: typeof model.remote_id === "string" ? model.remote_id.trim() : model.remote_id,
      display_name: normalizeOptionalText(model.display_name),
      context_window: model.context_window,
      max_output_tokens: model.max_output_tokens,
      reasoning_effort: model.reasoning_effort,
      supports_images: model.supports_images,
    };
  }
  if (Object.keys(models).length) request.models = models;
  if (before.default_model !== draft.default_model && draft.default_model !== undefined) {
    request.default_model = draft.default_model;
  }
  return request;
}

export function parseOptionalPositiveInteger(value: string): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

export function stringValue(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

export function sourceConfig(value: ConfigurationView | null): SettingsDraft {
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
      supports_images: profile.supports_images === true
        ? true
        : profile.supports_images === false
          ? false
          : null,
    };
  }
  const requestedDefault = stringValue(value?.default_model);
  const defaultModel = requestedDefault && models[requestedDefault] ? requestedDefault : Object.keys(models)[0] ?? "";
  const searchValue = value?.search;
  const search = searchValue && typeof searchValue === "object"
    ? { ...(searchValue as Record<string, unknown>) }
    : undefined;
  if (search) delete search.api_key;
  const toolLimitsValue = value?.tool_limits;
  const toolLimits = toolLimitsValue && typeof toolLimitsValue === "object"
    ? { ...(toolLimitsValue as Record<string, unknown>) }
    : undefined;
  return {
    default_model: defaultModel,
    default_permission_mode: value?.default_permission_mode === "auto" ? "auto" : "default",
    providers,
    models,
    ...(search ? { search } : {}),
    ...(toolLimits ? { tool_limits: toolLimits } : {}),
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

export function providerModels(draft: SettingsDraft, providerId: string): Array<[string, Record<string, unknown>]> {
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
