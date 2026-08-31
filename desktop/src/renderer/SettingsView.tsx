import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { DesktopApi, LanguagePreference, ThemePreference } from "../desktop-api";
import type { ConfigurationView, RendererState } from "./state";
import { CustomSelect } from "./CustomSelect";
import { useTranslation } from "./i18n";

export interface SettingsViewProps {
  state: Pick<RendererState, "configuration" | "settingsError" | "settingsSaving" | "settingsLoaded" | "activeTurn" | "theme" | "language">;
  api?: DesktopApi;
  onBack: () => void;
  onSave: (request: ConfigurationWrite) => void | Promise<void>;
  onThemeChange: (theme: ThemePreference) => void;
  onLanguageChange: (language: LanguagePreference) => void;
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

export function settingsSaveRequest(draft: ConfigurationWrite, apiKeys: Record<string, string>, touchedKeys: Record<string, boolean>): ConfigurationWrite {
  return configurationRequest({
    ...draft,
    providers: Object.fromEntries(Object.entries(draft.providers ?? {}).map(([id, profile]) => {
      const next = { ...profile };
      delete next.api_key_configured;
      if (touchedKeys[id]) next.api_key = apiKeys[id] ?? "";
      return [id, next];
    })),
  });
}

export function withoutRecordKey<T>(record: Record<string, T>, key: string): Record<string, T> {
  const next = { ...record };
  delete next[key];
  return next;
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
      display_name: profile.display_name ?? null,
      context_window: profile.context_window ?? null,
      max_output_tokens: profile.max_output_tokens ?? null,
      reasoning_effort: profile.reasoning_effort ?? null,
    };
  }
  if (Object.keys(providers).length === 0 && Object.keys(models).length === 0) {
    providers.provider = { kind: "openai_compat", base_url: null, api_key_configured: false };
    models.model = { provider_profile_id: "provider", remote_id: "", display_name: null, context_window: null, max_output_tokens: null, reasoning_effort: null };
  }
  return {
    default_model: value?.default_model || (models.model ? "model" : ""),
    default_permission_mode: value?.default_permission_mode === "auto" ? "auto" : "default",
    providers,
    models,
    providerOriginalIds,
  };
}

function updateRecord(record: Record<string, Record<string, unknown>> | undefined, key: string, field: string, value: unknown): Record<string, Record<string, unknown>> {
  return { ...(record ?? {}), [key]: { ...(record?.[key] ?? {}), [field]: value } };
}
export const reasoningEffortOptions = ["", "none", "minimal", "low", "medium", "high", "xhigh", "max"] as const;
export function modalFocusableElements(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), [role="button"]:not([aria-disabled="true"]), summary, [tabindex]:not([tabindex="-1"])')).filter((element) => !element.hasAttribute("hidden"));
}
export function modelFieldId(prefix: string, ref: string, field: string): string {
  const encoded = ref.length === 0 ? "empty" : ref.split("").map((unit) => unit.charCodeAt(0).toString(16).padStart(4, "0")).join("-");
  return `${prefix}-${encoded}-${field}`;
}
export function providerModels(draft: ConfigurationWrite, providerId: string) {
  return Object.entries(draft.models ?? {}).filter(([, model]) => model.provider_profile_id === providerId);
}

export function SettingsView({ state, onBack, onSave, onThemeChange, onLanguageChange }: SettingsViewProps) {
  const [draft, setDraft] = useState<ConfigurationWrite>(() => sourceConfig(state.configuration));
  const [apiKeys, setApiKeys] = useState<Record<string, string>>({});
  const [touchedKeys, setTouchedKeys] = useState<Record<string, boolean>>({});
  const [editingProvider, setEditingProvider] = useState<string | null>(null);
  const [newModelRef, setNewModelRef] = useState("");
  const [newModelRemoteId, setNewModelRemoteId] = useState("");
  const [providerDeletePending, setProviderDeletePending] = useState(false);
  const modalClose = useRef<HTMLButtonElement>(null);
  const modalRoot = useRef<HTMLElement>(null);
  const settingsNav = useRef<HTMLElement>(null);
  const settingsContent = useRef<HTMLDivElement>(null);
  const fieldPrefix = useId().replace(/:/gu, "");
  const returnFocus = useRef<HTMLElement | null>(null);
  const editorSnapshot = useRef<{ draft: ConfigurationWrite; apiKeys: Record<string, string>; touchedKeys: Record<string, boolean> } | null>(null);
  const { t } = useTranslation();

  useEffect(() => {
    if (state.configuration) setDraft(sourceConfig(state.configuration));
  }, [state.configuration]);

  const providers = useMemo(() => Object.entries(draft.providers ?? {}), [draft.providers]);
  const models = useMemo(() => Object.entries(draft.models ?? {}), [draft.models]);
  const modelsFor = (id: string) => providerModels(draft, id);
  const snapshotEditor = () => { editorSnapshot.current = { draft: structuredClone(draft), apiKeys: { ...apiKeys }, touchedKeys: { ...touchedKeys } }; };
  const openEditor = (id: string, source?: HTMLElement) => { snapshotEditor(); returnFocus.current = source ?? document.activeElement as HTMLElement; setNewModelRef(""); setNewModelRemoteId(""); setProviderDeletePending(false); setEditingProvider(id); };
  const finishEditor = () => { editorSnapshot.current = null; setEditingProvider(null); queueMicrotask(() => returnFocus.current?.focus()); };
  const cancelEditor = () => { const snapshot = editorSnapshot.current; if (snapshot) { setDraft(snapshot.draft); setApiKeys(snapshot.apiKeys); setTouchedKeys(snapshot.touchedKeys); } finishEditor(); };
  useEffect(() => { if (editingProvider && modalRoot.current) (modalFocusableElements(modalRoot.current).find((element) => element !== modalClose.current) ?? modalClose.current)?.focus(); }, [editingProvider]);
  useEffect(() => {
    if (!editingProvider) return undefined;
    const backgrounds = [settingsNav.current, settingsContent.current].filter((item): item is HTMLElement => item !== null);
    const previous = backgrounds.map((item) => ({ item, inert: item.inert, ariaHidden: item.getAttribute("aria-hidden") }));
    for (const item of backgrounds) { item.inert = true; item.setAttribute("aria-hidden", "true"); }
    return () => { for (const value of previous) { value.item.inert = value.inert; if (value.ariaHidden === null) value.item.removeAttribute("aria-hidden"); else value.item.setAttribute("aria-hidden", value.ariaHidden); } };
  }, [editingProvider]);
  useEffect(() => {
    if (!editingProvider) return undefined;
    const handleKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return;
      if (event.key === "Escape") { event.preventDefault(); cancelEditor(); return; }
      if (event.key !== "Tab" || !modalRoot.current) return;
      const focusable = modalFocusableElements(modalRoot.current);
      if (!focusable.length) return;
      const first = focusable[0]; const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [editingProvider]);
  const save = async () => {
    const request = settingsSaveRequest(draft, apiKeys, touchedKeys);
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
    let modelRef = "model"; let modelIndex = 1;
    while (draft.models?.[modelRef]) modelRef = `model-${modelIndex++}`;
    setDraft((current) => ({ ...current, default_model: current.default_model || modelRef, providers: { ...(current.providers ?? {}), [id]: { kind: "openai_compat", base_url: null } }, models: { ...(current.models ?? {}), [modelRef]: { provider_profile_id: id, remote_id: "", display_name: null, context_window: null, max_output_tokens: null, reasoning_effort: null } } }));
    openEditor(id);
  };
  const removeProvider = (id: string) => {
    setApiKeys((current) => withoutRecordKey(current, id));
    setTouchedKeys((current) => withoutRecordKey(current, id));
    setDraft((current) => {
    const retainedModels = Object.fromEntries(Object.entries(current.models ?? {}).filter(([, model]) => model.provider_profile_id !== id));
    const providerOriginalIds = { ...(current.providerOriginalIds ?? {}) };
    const providerRenames = { ...(current.provider_renames ?? {}) };
    const sourceId = providerOriginalIds[id];
    if (sourceId !== undefined) delete providerRenames[sourceId];
    delete providerOriginalIds[id];
    const next: ConfigurationWrite = {
      ...current,
      providers: Object.fromEntries(Object.entries(current.providers ?? {}).filter(([key]) => key !== id)),
      models: retainedModels,
      default_model: current.default_model && retainedModels[current.default_model] ? current.default_model : Object.keys(retainedModels)[0],
      providerOriginalIds,
    };
    if (Object.keys(providerRenames).length > 0) next.provider_renames = providerRenames;
    else delete next.provider_renames;
      return next;
    });
  };
  const addModel = (providerId: string) => {
    let ref = "model";
    let index = 1;
    while (draft.models?.[ref]) ref = `model-${index++}`;
    setDraft((current) => ({ ...current, default_model: current.default_model || ref, models: { ...(current.models ?? {}), [ref]: { provider_profile_id: providerId, remote_id: "", display_name: null, context_window: null, max_output_tokens: null, reasoning_effort: null } } }));
  };
  const removeModel = (ref: string, providerId: string) => setDraft((current) => {
    const models = Object.fromEntries(Object.entries(current.models ?? {}).filter(([key]) => key !== ref));
    if (current.default_model !== ref) return { ...current, models };
    const providerReplacement = Object.entries(models).find(([, model]) => model.provider_profile_id === providerId)?.[0];
    return { ...current, models, default_model: providerReplacement ?? Object.keys(models)[0] };
  });
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
    setEditingProvider(normalized);
  };
  const commitModelRef = (oldRef: string, nextRef: string, input: HTMLInputElement) => {
    const normalized = nextRef.trim();
    if (!normalized || normalized === oldRef || draft.models?.[normalized] !== undefined) {
      input.value = oldRef;
      return;
    }
    setDraft((current) => renameModelRef(current, oldRef, normalized));
  };

  const edited = editingProvider ? draft.providers?.[editingProvider] : undefined;
  const editedModels = editingProvider ? modelsFor(editingProvider) : [];
  const primary = editedModels[0];
  const applyEditor = () => {
    if (editingProvider && providerDeletePending) { removeProvider(editingProvider); finishEditor(); return; }
    if (editingProvider && !primary && newModelRef.trim() && newModelRemoteId.trim()) {
      const ref = newModelRef.trim();
      if (!draft.models?.[ref]) setDraft((current) => ({ ...current, default_model: current.default_model || ref, models: { ...(current.models ?? {}), [ref]: { provider_profile_id: editingProvider, remote_id: newModelRemoteId.trim(), display_name: null, context_window: null, max_output_tokens: null, reasoning_effort: null } } }));
    }
    finishEditor();
  };
  return (
    <section className="settings-view" aria-label={t("settings")}>
      <aside ref={settingsNav} className="settings-nav" aria-label={t("settings")}><button type="button" className="settings-view__back" title={t("back")} onClick={onBack}>← {t("back")}</button><div><h1>{t("settings")}</h1></div><nav><a href="#settings-providers">{t("providers")}</a><a href="#settings-defaults">{t("defaults")}</a><a href="#settings-interface">{t("interface")}</a><a href="#settings-about">{t("about")}</a></nav></aside>
      <div ref={settingsContent} className="settings-content"><header><div><h1>{t("settings")}</h1></div></header>
      {state.settingsError && <p className="settings-view__error" role="alert">{state.settingsError}</p>}
      <section className="settings-section" id="settings-providers"><h2>{t("providers")}</h2><div className="provider-list">{providers.map(([id, profile]) => { const linked = modelsFor(id); const main = linked.find(([ref]) => ref === draft.default_model) ?? linked[0]; return <button type="button" className="provider-row" title={`${t("editProvider")} ${id}`} key={id} onClick={(event) => openEditor(id, event.currentTarget)}><span><strong>{id}</strong><small>{String(profile.kind ?? "openai_compat")}</small></span><span>{String(profile.base_url ?? "—")}</span><span>{String(main?.[1].remote_id ?? "—")}{linked.length > 1 ? ` +${linked.length - 1}` : ""}</span><span className={profile.api_key_configured ? "is-configured" : ""}>{profile.api_key_configured ? t("configured") : t("notConfigured")}</span></button>; })}</div>
      <button type="button" className="row-add" title={t("addProvider")} onClick={addProvider}>＋ {t("addProvider")}</button></section>
      <section className="settings-section" id="settings-defaults"><h2>{t("defaults")}</h2><div className="settings-row"><span>{t("permission")}</span><CustomSelect label={t("permission")} value={draft.default_permission_mode ?? "default"} options={[{ value: "default", label: t("default") }, { value: "auto", label: t("auto") }]} onChange={(value) => setDraft((current) => ({ ...current, default_permission_mode: value === "auto" ? "auto" : "default" }))} /></div><div className="settings-row"><span>{t("defaultModel")}</span><CustomSelect label={t("defaultModel")} value={draft.default_model ?? ""} options={[{ value: "", label: "—" }, ...models.map(([ref]) => ({ value: ref, label: ref }))]} onChange={(value) => setDraft((current) => ({ ...current, default_model: value }))} /></div></section>
      <section className="settings-section" id="settings-interface"><h2>{t("interface")}</h2><div className="settings-row"><span>{t("theme")}</span><CustomSelect label={t("theme")} value={state.theme} options={[{ value: "system", label: t("system") }, { value: "dark", label: t("dark") }, { value: "light", label: t("light") }]} onChange={(value) => onThemeChange(value as ThemePreference)} /></div><div className="settings-row"><span>{t("language")}</span><CustomSelect label={t("language")} value={state.language} options={[{ value: "zh-CN", label: t("chinese") }, { value: "en", label: t("english") }]} onChange={(value) => onLanguageChange(value as LanguagePreference)} /></div></section>
      <section className="settings-section" id="settings-about"><h2>{t("about")}</h2><div className="settings-row"><span>{t("product")}</span><span>UthCode Desktop</span></div></section>
      <div className="settings-actions"><button type="button" title={t("cancel")} onClick={onBack}>{t("cancel")}</button><button type="button" className="save-button" title={t("save")} onClick={() => void save()} disabled={state.settingsSaving || state.activeTurn}>{t("save")}</button></div>
      </div>
      {editingProvider && edited && <div className="provider-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) cancelEditor(); }}><section ref={modalRoot} className="provider-modal" role="dialog" aria-modal="true" aria-labelledby="provider-modal-title"><header><h2 id="provider-modal-title">{t("editProvider")}</h2><button ref={modalClose} type="button" title={t("cancel")} aria-label={t("cancel")} onClick={cancelEditor}>×</button></header><div className="provider-modal__body">
        <div className="settings-row"><label htmlFor="modal-provider">{t("provider")}</label><CustomSelect id="modal-provider" label={t("provider")} value={String(edited.kind ?? "openai_compat")} options={[{ value: "openai_compat", label: "OpenAI-compatible" }, { value: "openai_responses", label: "OpenAI" }, { value: "anthropic", label: "Anthropic" }, { value: "fake", label: t("localTestProvider") }]} onChange={(value) => setDraft((current) => ({ ...current, providers: updateRecord(current.providers, editingProvider, "kind", value) }))} /></div>
        <div className="settings-row"><label htmlFor="modal-base-url">{t("baseUrl")}</label><input id="modal-base-url" value={String(edited.base_url ?? "")} onChange={(event) => setDraft((current) => ({ ...current, providers: updateRecord(current.providers, editingProvider, "base_url", event.target.value || null) }))} /></div>
        {primary ? <div className="settings-row"><label htmlFor="modal-model">{t("model")}</label><input id="modal-model" value={String(primary[1].remote_id ?? "")} onChange={(event) => setDraft((current) => ({ ...current, models: updateRecord(current.models, primary[0], "remote_id", event.target.value) }))} /></div> : <><div className="settings-row"><label htmlFor="modal-new-model-ref">{t("modelReference")}</label><input id="modal-new-model-ref" value={newModelRef} onChange={(event) => setNewModelRef(event.target.value)} /></div><div className="settings-row"><label htmlFor="modal-model">{t("model")}</label><input id="modal-model" value={newModelRemoteId} onChange={(event) => setNewModelRemoteId(event.target.value)} /></div></>}
        <div className="settings-row"><label htmlFor="modal-api-key">{t("apiKey")}</label><div className="settings-secret-line"><span>{edited.api_key_configured ? t("configured") : t("notConfigured")}</span><input id="modal-api-key" type="password" autoComplete="new-password" placeholder={edited.api_key_configured ? t("replaceKey") : t("apiKey")} value={apiKeys[editingProvider] ?? ""} onChange={(event) => { setApiKeys((current) => ({ ...current, [editingProvider]: event.target.value })); setTouchedKeys((current) => ({ ...current, [editingProvider]: true })); }} />{edited.api_key_configured === true && <button type="button" title={t("clearKey")} onClick={() => { setApiKeys((current) => ({ ...current, [editingProvider]: "" })); setTouchedKeys((current) => ({ ...current, [editingProvider]: true })); }}>{t("clearKey")}</button>}</div></div>
        <details className="settings-advanced"><summary>{t("advanced")}</summary><button type="button" title={t("extraModels")} onClick={() => addModel(editingProvider)}>＋ {t("extraModels")}</button><div className="settings-row"><label htmlFor="modal-profile-id">{t("profileId")}</label><input id="modal-profile-id" defaultValue={editingProvider} onBlur={(event) => commitProviderId(editingProvider, event.target.value, event.currentTarget)} /></div>{editedModels.map(([ref, model]) => <fieldset key={ref}><legend>{ref}</legend><div className="settings-row"><label htmlFor={modelFieldId(fieldPrefix, ref, "ref")}>{t("modelReference")}</label><input id={modelFieldId(fieldPrefix, ref, "ref")} defaultValue={ref} onBlur={(event) => commitModelRef(ref, event.target.value, event.currentTarget)} /></div><div className="settings-row"><label htmlFor={modelFieldId(fieldPrefix, ref, "remote")}>{t("model")}</label><input id={modelFieldId(fieldPrefix, ref, "remote")} value={String(model.remote_id ?? "")} onChange={(event) => setDraft((current) => ({ ...current, models: updateRecord(current.models, ref, "remote_id", event.target.value) }))} /></div><div className="settings-row"><label htmlFor={modelFieldId(fieldPrefix, ref, "display")}>{t("displayName")}</label><input id={modelFieldId(fieldPrefix, ref, "display")} value={String(model.display_name ?? "")} onChange={(event) => setDraft((current) => ({ ...current, models: updateRecord(current.models, ref, "display_name", event.target.value || null) }))} /></div><div className="settings-row"><label htmlFor={modelFieldId(fieldPrefix, ref, "context")}>{t("contextWindow")}</label><input id={modelFieldId(fieldPrefix, ref, "context")} type="number" value={model.context_window == null ? "" : String(model.context_window)} onChange={(event) => setDraft((current) => ({ ...current, models: updateRecord(current.models, ref, "context_window", parseOptionalPositiveInteger(event.target.value)) }))} /></div><div className="settings-row"><label htmlFor={modelFieldId(fieldPrefix, ref, "output")}>{t("maxOutput")}</label><input id={modelFieldId(fieldPrefix, ref, "output")} type="number" value={model.max_output_tokens == null ? "" : String(model.max_output_tokens)} onChange={(event) => setDraft((current) => ({ ...current, models: updateRecord(current.models, ref, "max_output_tokens", parseOptionalPositiveInteger(event.target.value)) }))} /></div><div className="settings-row"><label htmlFor={modelFieldId(fieldPrefix, ref, "reasoning")}>{t("reasoning")}</label><CustomSelect id={modelFieldId(fieldPrefix, ref, "reasoning")} label={`${t("reasoning")} ${ref}`} value={String(model.reasoning_effort ?? "")} options={reasoningEffortOptions.map((value) => ({ value, label: value || "—" }))} onChange={(value) => setDraft((current) => ({ ...current, models: updateRecord(current.models, ref, "reasoning_effort", value || null) }))} /></div><button type="button" title={`${t("remove")} ${ref}`} onClick={() => removeModel(ref, editingProvider)}>{t("remove")} {t("model")}</button></fieldset>)}</details>
      </div><footer><button type="button" className="danger" title={t("removeProvider")} onClick={() => setProviderDeletePending(true)}>{t("removeProvider")}</button><button type="button" title={t("apply")} onClick={applyEditor}>{t("apply")}</button></footer></section></div>}
    </section>
  );
}
