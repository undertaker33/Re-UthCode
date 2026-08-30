import { useEffect, useMemo, useState } from "react";
import type { DesktopApi, ThemePreference } from "../desktop-api";
import type { ConfigurationView, RendererState } from "./state";

export interface SettingsViewProps {
  state: Pick<RendererState, "configuration" | "settingsError" | "settingsSaving" | "settingsLoaded" | "runtimeState" | "activeTurn" | "theme">;
  api?: DesktopApi;
  onBack: () => void;
  onSave: (request: ConfigurationWrite) => void | Promise<void>;
  onThemeChange: (theme: ThemePreference) => void;
}

export interface ConfigurationWrite {
  default_model?: string;
  default_permission_mode?: "default" | "auto";
  providers?: Record<string, Record<string, unknown>>;
  models?: Record<string, Record<string, unknown>>;
  provider_renames?: Record<string, string>;
  /** Renderer-only source identity; stripped before the Bridge request. */
  providerOriginalIds?: Record<string, string>;
}

export function configurationRequest(value: ConfigurationWrite): ConfigurationWrite {
  const request: ConfigurationWrite = {};
  if (value.default_model !== undefined) request.default_model = value.default_model;
  if (value.default_permission_mode !== undefined) request.default_permission_mode = value.default_permission_mode;
  if (value.providers) request.providers = Object.fromEntries(Object.entries(value.providers).map(([key, profile]) => [key, { ...profile }]));
  if (value.models) request.models = Object.fromEntries(Object.entries(value.models).map(([key, profile]) => [key, { ...profile }]));
  if (value.provider_renames) request.provider_renames = { ...value.provider_renames };
  return request;
}

export function renameProviderId(value: ConfigurationWrite, oldId: string, nextId: string): ConfigurationWrite {
  const normalized = nextId.trim();
  if (!normalized || normalized === oldId || value.providers?.[oldId] === undefined || value.providers[normalized] !== undefined) return value;
  const providers = Object.fromEntries(Object.entries(value.providers ?? {}).map(([id, profile]) => [id === oldId ? normalized : id, { ...profile }]));
  const models = value.models
    ? Object.fromEntries(Object.entries(value.models).map(([ref, profile]) => [ref, profile.provider_profile_id === oldId ? { ...profile, provider_profile_id: normalized } : { ...profile }]))
    : undefined;
  const providerRenames = { ...(value.provider_renames ?? {}) };
  const originalIds = { ...(value.providerOriginalIds ?? {}) };
  const sourceId = originalIds[oldId];
  delete originalIds[oldId];

  // A provider created in this draft has no persisted source identity, so a
  // local key edit is just a key edit. Only an existing profile can produce a
  // writer rename, and the source identity is stable while the draft moves.
  if (sourceId !== undefined) {
    originalIds[normalized] = sourceId;
    delete providerRenames[sourceId];
    if (normalized !== sourceId) providerRenames[sourceId] = normalized;
  }

  const next: ConfigurationWrite = {
    ...value,
    providers,
    ...(models ? { models } : {}),
    providerOriginalIds: originalIds,
  };
  if (Object.keys(providerRenames).length > 0) next.provider_renames = providerRenames;
  else delete next.provider_renames;
  return next;
}

export function renameModelRef(value: ConfigurationWrite, oldRef: string, nextRef: string): ConfigurationWrite {
  const normalized = nextRef.trim();
  if (!normalized || normalized === oldRef || value.models?.[oldRef] === undefined || value.models[normalized] !== undefined) return value;
  const models = Object.fromEntries(Object.entries(value.models ?? {}).map(([ref, profile]) => [ref === oldRef ? normalized : ref, { ...profile }]));
  return { ...value, models, default_model: value.default_model === oldRef ? normalized : value.default_model };
}

export function parseOptionalPositiveInteger(value: string): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

function sourceConfig(value: ConfigurationView | null): ConfigurationWrite {
  const providers: Record<string, Record<string, unknown>> = {};
  const providerOriginalIds: Record<string, string> = {};
  for (const [id, raw] of Object.entries(value?.providers ?? {})) {
    const profile = raw as Record<string, unknown>;
    providers[id] = { kind: profile.kind ?? "fake", base_url: profile.base_url ?? null, api_key_configured: profile.api_key_configured === true };
    providerOriginalIds[id] = id;
  }
  const models: Record<string, Record<string, unknown>> = {};
  for (const [ref, raw] of Object.entries(value?.models ?? {})) {
    const profile = raw as Record<string, unknown>;
    models[ref] = {
      provider_profile_id: profile.provider_profile_id ?? "",
      remote_id: profile.remote_id ?? "",
      display_name: profile.display_name ?? "",
      context_window: profile.context_window ?? null,
      max_output_tokens: profile.max_output_tokens ?? null,
      reasoning_effort: profile.reasoning_effort ?? null,
    };
  }
  return {
    default_model: value?.default_model ?? "",
    default_permission_mode: value?.default_permission_mode === "auto" ? "auto" : "default",
    providers,
    models,
    providerOriginalIds,
  };
}

function updateRecord(record: Record<string, Record<string, unknown>> | undefined, key: string, field: string, value: unknown): Record<string, Record<string, unknown>> {
  return { ...(record ?? {}), [key]: { ...(record?.[key] ?? {}), [field]: value } };
}

export function SettingsView({ state, onBack, onSave, onThemeChange }: SettingsViewProps) {
  const [draft, setDraft] = useState<ConfigurationWrite>(() => sourceConfig(state.configuration));
  const [apiKeys, setApiKeys] = useState<Record<string, string>>({});
  const [touchedKeys, setTouchedKeys] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (state.configuration) setDraft(sourceConfig(state.configuration));
  }, [state.configuration]);

  const providers = useMemo(() => Object.entries(draft.providers ?? {}), [draft.providers]);
  const models = useMemo(() => Object.entries(draft.models ?? {}), [draft.models]);
  const save = async () => {
    const request = configurationRequest({
      ...draft,
      providers: Object.fromEntries(providers.map(([id, profile]) => {
        const next = { ...profile };
        delete next.api_key_configured;
        if (touchedKeys[id]) next.api_key = apiKeys[id] ?? "";
        return [id, next];
      })),
    });
    try {
      await onSave(request);
      setApiKeys({});
      setTouchedKeys({});
    } catch {
      // Keep a replacement key in the transient input when the Application
      // rejects the candidate; it is never written to Desktop preferences.
    }
  };

  const addProvider = () => {
    let id = "provider";
    let index = 1;
    while (draft.providers?.[id]) id = `provider-${index++}`;
    setDraft((current) => ({ ...current, providers: { ...(current.providers ?? {}), [id]: { kind: "fake", base_url: null } } }));
  };
  const removeProvider = (id: string) => setDraft((current) => {
    const providerOriginalIds = { ...(current.providerOriginalIds ?? {}) };
    const providerRenames = { ...(current.provider_renames ?? {}) };
    const sourceId = providerOriginalIds[id];
    if (sourceId !== undefined) delete providerRenames[sourceId];
    delete providerOriginalIds[id];
    const next: ConfigurationWrite = {
      ...current,
      providers: Object.fromEntries(Object.entries(current.providers ?? {}).filter(([key]) => key !== id)),
      providerOriginalIds,
    };
    if (Object.keys(providerRenames).length > 0) next.provider_renames = providerRenames;
    else delete next.provider_renames;
    return next;
  });
  const addModel = () => {
    let ref = "model";
    let index = 1;
    while (draft.models?.[ref]) ref = `model-${index++}`;
    setDraft((current) => ({ ...current, models: { ...(current.models ?? {}), [ref]: { provider_profile_id: providers[0]?.[0] ?? "", remote_id: ref, display_name: ref, context_window: null, max_output_tokens: null, reasoning_effort: "none" } } }));
  };
  const removeModel = (ref: string) => setDraft((current) => ({ ...current, models: Object.fromEntries(Object.entries(current.models ?? {}).filter(([key]) => key !== ref)) }));
  const commitProviderId = (oldId: string, nextId: string, input: HTMLInputElement) => {
    const normalized = nextId.trim();
    if (!normalized || normalized === oldId || draft.providers?.[normalized] !== undefined) {
      input.value = oldId;
      return;
    }
    setDraft((current) => renameProviderId(current, oldId, normalized));
    setApiKeys((current) => {
      if (current[oldId] === undefined) return current;
      const next = { ...current, [normalized]: current[oldId] };
      delete next[oldId];
      return next;
    });
    setTouchedKeys((current) => {
      if (current[oldId] === undefined) return current;
      const next = { ...current, [normalized]: current[oldId] };
      delete next[oldId];
      return next;
    });
  };
  const commitModelRef = (oldRef: string, nextRef: string, input: HTMLInputElement) => {
    const normalized = nextRef.trim();
    if (!normalized || normalized === oldRef || draft.models?.[normalized] !== undefined) {
      input.value = oldRef;
      return;
    }
    setDraft((current) => renameModelRef(current, oldRef, normalized));
  };

  return (
    <section className="settings-view" aria-label="Settings">
      <header><div><p className="eyebrow">Workspace</p><h1>Settings</h1></div><button type="button" className="settings-view__back" onClick={onBack}>Back to chat</button></header>
      {state.settingsError && <p className="settings-view__error" role="alert">{state.settingsError}</p>}
      <section className="settings-section"><h2>Providers</h2><p className="settings-section__hint">Provider profiles used by the current model catalog.</p>{providers.map(([id, profile]) => <div className="settings-row" key={id}><label htmlFor={`provider-id-${id}`}>Provider ID</label><div><div className="settings-inline"><input id={`provider-id-${id}`} aria-label={`${id} provider id`} defaultValue={id} onBlur={(event) => commitProviderId(id, event.target.value, event.currentTarget)} onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur(); }} /><select id={`provider-kind-${id}`} value={String(profile.kind ?? "fake")} onChange={(event) => setDraft((current) => ({ ...current, providers: updateRecord(current.providers, id, "kind", event.target.value) }))}><option value="fake">fake</option><option value="anthropic">anthropic</option><option value="openai_responses">openai_responses</option><option value="openai_compat">openai_compat</option></select><input aria-label={`${id} base URL`} placeholder="Base URL" value={String(profile.base_url ?? "")} onChange={(event) => setDraft((current) => ({ ...current, providers: updateRecord(current.providers, id, "base_url", event.target.value || null) }))} /><button type="button" onClick={() => removeProvider(id)}>Remove</button></div><div className="settings-secret-line"><span className="settings-row__secret">{profile.api_key_configured === true ? "configured" : "not configured"}</span><input aria-label={`${id} API key replacement`} type="password" autoComplete="new-password" placeholder={profile.api_key_configured === true ? "Replace API key" : "API key"} value={apiKeys[id] ?? ""} onChange={(event) => { setApiKeys((current) => ({ ...current, [id]: event.target.value })); setTouchedKeys((current) => ({ ...current, [id]: true })); }} />{profile.api_key_configured === true && <button type="button" onClick={() => { setApiKeys((current) => ({ ...current, [id]: "" })); setTouchedKeys((current) => ({ ...current, [id]: true })); }}>Clear key</button>}</div></div></div>)}<button type="button" className="row-add" onClick={addProvider}>＋ Add provider</button></section>
      <section className="settings-section"><h2>Models</h2><p className="settings-section__hint">Model references available to the Application.</p>{models.map(([ref, profile]) => <div className="settings-row settings-row--model" key={ref}><label htmlFor={`model-ref-${ref}`}>Model reference</label><div className="settings-model-fields"><input id={`model-ref-${ref}`} aria-label={`${ref} model ref`} defaultValue={ref} onBlur={(event) => commitModelRef(ref, event.target.value, event.currentTarget)} onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur(); }} /><input aria-label={`${ref} remote model`} placeholder="Remote model ID" value={String(profile.remote_id ?? "")} onChange={(event) => setDraft((current) => ({ ...current, models: updateRecord(current.models, ref, "remote_id", event.target.value) }))} /><select aria-label={`${ref} provider`} value={String(profile.provider_profile_id ?? "")} onChange={(event) => setDraft((current) => ({ ...current, models: updateRecord(current.models, ref, "provider_profile_id", event.target.value) }))}>{providers.map(([id]) => <option value={id} key={id}>{id}</option>)}</select><input aria-label={`${ref} display name`} placeholder="Display name" value={String(profile.display_name ?? "")} onChange={(event) => setDraft((current) => ({ ...current, models: updateRecord(current.models, ref, "display_name", event.target.value) }))} /><input aria-label={`${ref} context window`} type="number" min="1" step="1" placeholder="Context window" value={profile.context_window == null ? "" : String(profile.context_window)} onChange={(event) => setDraft((current) => ({ ...current, models: updateRecord(current.models, ref, "context_window", parseOptionalPositiveInteger(event.target.value)) }))} /><input aria-label={`${ref} max output tokens`} type="number" min="1" step="1" placeholder="Max output tokens" value={profile.max_output_tokens == null ? "" : String(profile.max_output_tokens)} onChange={(event) => setDraft((current) => ({ ...current, models: updateRecord(current.models, ref, "max_output_tokens", parseOptionalPositiveInteger(event.target.value)) }))} /><select aria-label={`${ref} reasoning effort`} value={String(profile.reasoning_effort ?? "none")} onChange={(event) => setDraft((current) => ({ ...current, models: updateRecord(current.models, ref, "reasoning_effort", event.target.value) }))}>{["none", "minimal", "low", "medium", "high", "xhigh", "max"].map((effort) => <option value={effort} key={effort}>{effort}</option>)}</select><button type="button" onClick={() => removeModel(ref)}>Remove</button></div></div>)}<button type="button" className="row-add" onClick={addModel}>＋ Add model</button></section>
      <section className="settings-section"><h2>Permissions</h2><p className="settings-section__hint">Default permission mode for new Runs.</p><div className="settings-row"><label htmlFor="default-permission">Default mode</label><select id="default-permission" value={draft.default_permission_mode ?? "default"} onChange={(event) => setDraft((current) => ({ ...current, default_permission_mode: event.target.value === "auto" ? "auto" : "default" }))}><option value="default">default</option><option value="auto">auto</option></select></div><div className="settings-row"><span className="settings-row__label">Default model</span><select value={draft.default_model ?? ""} onChange={(event) => setDraft((current) => ({ ...current, default_model: event.target.value }))}><option value="">Select a model</option>{models.map(([ref]) => <option value={ref} key={ref}>{ref}</option>)}</select></div></section>
      <section className="settings-section"><h2>Interface</h2><p className="settings-section__hint">Appearance preferences are stored on this Desktop installation.</p><div className="settings-row"><label htmlFor="theme">Theme</label><select id="theme" value={state.theme} onChange={(event) => onThemeChange(event.target.value as ThemePreference)}><option value="system">system</option><option value="dark">dark</option><option value="light">light</option></select></div></section>
      <section className="settings-section"><h2>About</h2><div className="settings-row"><span className="settings-row__label">Product</span><span className="settings-row__value">UthCode Desktop</span></div></section>
      <div className="settings-actions"><button type="button" onClick={onBack}>Cancel</button><button type="button" className="save-button" onClick={() => void save()} disabled={state.settingsSaving || state.activeTurn}>{state.settingsSaving ? "Saving…" : "Save settings"}</button></div>
    </section>
  );
}
