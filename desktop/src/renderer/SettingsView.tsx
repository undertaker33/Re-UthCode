import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { LanguagePreference, ThemePreference } from "../desktop-api";
import type { ConfigurationView, RendererState } from "./state";
import { CustomSelect } from "./CustomSelect";
import { useTranslation } from "./i18n";
import { UiIcon } from "./UiIcon";

export interface SettingsViewProps {
  state: Pick<RendererState, "configuration" | "settingsError" | "settingsSaving" | "settingsLoaded" | "activeTurn" | "runtimeError" | "runtimeState" | "theme" | "language">;
  /** Narrow secret-reveal command; Settings never receives the full Desktop API. */
  onRevealApiKey?: (providerId: string) => Promise<string | null>;
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
}

export function configurationRequest(value: ConfigurationWrite): ConfigurationWrite {
  const request: ConfigurationWrite = {};
  if (value.default_model !== undefined) request.default_model = value.default_model;
  if (value.default_permission_mode !== undefined) request.default_permission_mode = value.default_permission_mode;
  if (value.providers) request.providers = Object.fromEntries(Object.entries(value.providers).map(([key, profile]) => [key, { ...profile }]));
  if (value.models) request.models = Object.fromEntries(Object.entries(value.models).map(([key, profile]) => [key, { ...profile }]));
  return request;
}

function normalizeOptionalText(value: unknown): unknown {
  if (typeof value !== "string") return value;
  const normalized = value.trim();
  return normalized || null;
}

/** Build the only settings write shape that can carry a candidate API key. */
export function settingsSaveRequest(draft: ConfigurationWrite, replacementKeys: Record<string, string>, touchedKeys: Record<string, boolean>): ConfigurationWrite {
  return configurationRequest({
    ...draft,
    providers: Object.fromEntries(Object.entries(draft.providers ?? {}).map(([id, profile]) => {
      const next = { ...profile };
      if (Object.prototype.hasOwnProperty.call(next, "base_url")) next.base_url = normalizeOptionalText(next.base_url);
      if (Object.prototype.hasOwnProperty.call(next, "display_name")) next.display_name = normalizeOptionalText(next.display_name);
      delete next.api_key_configured;
      // A saved/revealed value is never part of the draft.  Only an explicit
      // replacement edit may add a key-bearing field to this write request.
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

function stringValue(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function sourceConfig(value: ConfigurationView | null): ConfigurationWrite {
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

function updateRecord(record: Record<string, Record<string, unknown>> | undefined, key: string, field: string, value: unknown): Record<string, Record<string, unknown>> {
  return { ...(record ?? {}), [key]: { ...(record?.[key] ?? {}), [field]: value } };
}

interface ModelEditorSnapshot {
  profile: Record<string, unknown> | null;
  defaultModel: string;
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

let generatedModelSerial = 0;
function createInternalModelRef(existing: Record<string, Record<string, unknown>>): string {
  let ref = "";
  do {
    generatedModelSerial += 1;
    ref = `__uthcode_model_${generatedModelSerial}`;
  } while (existing[ref] !== undefined);
  return ref;
}

function modelLabel(model: Record<string, unknown> | undefined, unnamed: string): string {
  const displayName = stringValue(model?.display_name).trim();
  const remoteId = stringValue(model?.remote_id).trim();
  return displayName || remoteId || unnamed;
}

function modelRemoteLabel(model: Record<string, unknown> | undefined, unnamed: string): string {
  const remoteId = stringValue(model?.remote_id).trim();
  return remoteId || unnamed;
}

function providerLabel(providerId: string, provider: Record<string, unknown> | undefined): string {
  return stringValue(provider?.display_name).trim() || providerId;
}

export function SettingsView({ state, onRevealApiKey, onBack, onSave, onThemeChange, onLanguageChange }: SettingsViewProps) {
  const [draft, setDraft] = useState<ConfigurationWrite>(() => sourceConfig(state.configuration));
  const [replacementKeys, setReplacementKeys] = useState<Record<string, string>>({});
  const [touchedKeys, setTouchedKeys] = useState<Record<string, boolean>>({});
  const [revealedKeys, setRevealedKeys] = useState<Record<string, string>>({});
  const [visibleKeys, setVisibleKeys] = useState<Record<string, boolean>>({});
  const [revealPending, setRevealPending] = useState<Record<string, boolean>>({});
  const [revealError, setRevealError] = useState<Record<string, boolean>>({});
  const [editingProvider, setEditingProvider] = useState<string | null>(null);
  const [editingModel, setEditingModel] = useState<{ providerId: string; modelRef: string } | null>(null);
  const [providerDeletePending, setProviderDeletePending] = useState(false);
  const [activeCategory, setActiveCategory] = useState<"providers" | "defaults" | "interface" | "about">("providers");
  const [modelSnapshot, setModelSnapshot] = useState<ModelEditorSnapshot | null>(null);
  const providerModalClose = useRef<HTMLButtonElement>(null);
  const modelModalClose = useRef<HTMLButtonElement>(null);
  const providerModalRoot = useRef<HTMLElement>(null);
  const modelModalRoot = useRef<HTMLElement>(null);
  const settingsNav = useRef<HTMLElement>(null);
  const settingsContent = useRef<HTMLDivElement>(null);
  const settingsBusyStatus = useRef<HTMLParagraphElement>(null);
  const saveButton = useRef<HTMLButtonElement>(null);
  const fieldPrefix = useId().replace(/:/gu, "");
  const returnFocus = useRef<HTMLElement | null>(null);
  const modelReturnFocus = useRef<HTMLElement | null>(null);
  const editorSnapshot = useRef<{ draft: ConfigurationWrite; replacementKeys: Record<string, string>; touchedKeys: Record<string, boolean> } | null>(null);
  const revealedKeysRef = useRef<Record<string, string>>({});
  const visibleKeysRef = useRef<Record<string, boolean>>({});
  const revealGeneration = useRef(0);
  const settingsSavingPrevious = useRef(state.settingsSaving);
  const settingsSaveStartedRef = useRef(false);
  const { t } = useTranslation();
  const settingsBusy = state.settingsSaving;
  const settingsInteractionLocked = () => state.settingsSaving || settingsSaveStartedRef.current;

  useEffect(() => { revealedKeysRef.current = revealedKeys; }, [revealedKeys]);
  useEffect(() => { visibleKeysRef.current = visibleKeys; }, [visibleKeys]);
  useEffect(() => () => {
    // The cache is intentionally renderer-local. Clear the refs on unmount so
    // an async reveal completion cannot leave a recoverable value behind.
    revealGeneration.current += 1;
    revealedKeysRef.current = {};
    visibleKeysRef.current = {};
  }, []);
  useEffect(() => {
    if (state.configuration) {
      revealGeneration.current += 1;
      revealedKeysRef.current = {};
      visibleKeysRef.current = {};
      setDraft(sourceConfig(state.configuration));
      setRevealedKeys({});
      setVisibleKeys({});
      setRevealPending({});
      setRevealError({});
    }
  }, [state.configuration]);

  const providers = useMemo(() => Object.entries(draft.providers ?? {}), [draft.providers]);
  const models = useMemo(() => Object.entries(draft.models ?? {}), [draft.models]);
  const modelsFor = (id: string) => providerModels(draft, id);

  const clearRevealCache = (providerId?: string) => {
    revealGeneration.current += 1;
    const filter = (current: Record<string, unknown>) => providerId === undefined
      ? {}
      : Object.fromEntries(Object.entries(current).filter(([key]) => key !== providerId));
    setRevealedKeys((current) => filter(current) as Record<string, string>);
    setVisibleKeys((current) => filter(current) as Record<string, boolean>);
    setRevealPending((current) => filter(current) as Record<string, boolean>);
    setRevealError((current) => filter(current) as Record<string, boolean>);
    if (providerId === undefined) {
      revealedKeysRef.current = {};
      visibleKeysRef.current = {};
    } else {
      delete revealedKeysRef.current[providerId];
      delete visibleKeysRef.current[providerId];
    }
  };

  useEffect(() => {
    const wasSaving = settingsSavingPrevious.current;
    settingsSavingPrevious.current = state.settingsSaving;
    if (!state.settingsSaving && wasSaving) {
      // Restore focus to the action that owns the Save lifecycle once the
      // durable boundary has settled, whether it succeeded or failed.
      queueMicrotask(() => saveButton.current?.focus());
      return;
    }
    if (!state.settingsSaving || wasSaving) return;

    // A Save can be triggered programmatically while a modal is open. Close
    // it at the same state boundary instead of leaving a focused disabled
    // control behind. Preserve draft/replacement state so a failed Save keeps
    // the existing A draft editable after the request settles.
    const providerId = editingProvider;
    if (providerId) clearRevealCache(providerId);
    editorSnapshot.current = null;
    setProviderDeletePending(false);
    setEditingModel(null);
    setModelSnapshot(null);
    setEditingProvider(null);
    queueMicrotask(() => settingsBusyStatus.current?.focus());
  }, [editingProvider, state.settingsSaving]);

  const snapshotEditor = () => {
    if (settingsInteractionLocked()) return;
    editorSnapshot.current = { draft: structuredClone(draft), replacementKeys: { ...replacementKeys }, touchedKeys: { ...touchedKeys } };
  };
  const openEditor = (id: string, source?: HTMLElement) => {
    if (settingsInteractionLocked()) return;
    snapshotEditor();
    returnFocus.current = source ?? document.activeElement as HTMLElement;
    setProviderDeletePending(false);
    setEditingModel(null);
    setModelSnapshot(null);
    setEditingProvider(id);
  };
  const finishEditor = (normalize = false) => {
    if (settingsInteractionLocked()) return;
    const providerId = editingProvider;
    if (normalize && providerId) setDraft((current) => {
      const profile = current.providers?.[providerId];
      if (!profile || !Object.prototype.hasOwnProperty.call(profile, "base_url")) return current;
      return { ...current, providers: { ...current.providers, [providerId]: { ...profile, base_url: normalizeOptionalText(profile.base_url), display_name: normalizeOptionalText(profile.display_name) } } };
    });
    clearRevealCache(providerId ?? undefined);
    editorSnapshot.current = null;
    setEditingModel(null);
    setModelSnapshot(null);
    setEditingProvider(null);
    queueMicrotask(() => returnFocus.current?.focus());
  };
  const cancelEditor = () => {
    if (settingsInteractionLocked()) return;
    const snapshot = editorSnapshot.current;
    if (snapshot) {
      setDraft(snapshot.draft);
      setReplacementKeys(snapshot.replacementKeys);
      setTouchedKeys(snapshot.touchedKeys);
    }
    finishEditor();
  };

  const cancelModel = () => {
    if (settingsInteractionLocked()) return;
    const current = editingModel;
    if (current) setDraft((value) => {
      const models = { ...(value.models ?? {}) };
      if (modelSnapshot?.profile) models[current.modelRef] = { ...modelSnapshot.profile };
      else delete models[current.modelRef];
      return { ...value, models, ...(modelSnapshot ? { default_model: modelSnapshot.defaultModel } : {}) };
    });
    setEditingModel(null);
    setModelSnapshot(null);
    const target = modelReturnFocus.current;
    setTimeout(() => target?.focus(), 0);
  };
  const applyModel = () => {
    if (settingsInteractionLocked()) return;
    const current = editingModel;
    if (current) setDraft((value) => {
      const profile = value.models?.[current.modelRef];
      if (!profile || !Object.prototype.hasOwnProperty.call(profile, "display_name")) return value;
      return { ...value, models: { ...value.models, [current.modelRef]: { ...profile, display_name: normalizeOptionalText(profile.display_name) } } };
    });
    setEditingModel(null);
    setModelSnapshot(null);
    const target = modelReturnFocus.current;
    setTimeout(() => target?.focus(), 0);
  };

  useEffect(() => {
    if (!editingProvider) return;
    const root = editingModel ? modelModalRoot.current : providerModalRoot.current;
    if (!root) return;
    const close = editingModel ? modelModalClose.current : providerModalClose.current;
    queueMicrotask(() => (modalFocusableElements(root).find((element) => element !== close) ?? close)?.focus());
  }, [editingProvider, editingModel]);
  useEffect(() => {
    if (!editingProvider) return undefined;
    const backgrounds = [settingsNav.current, settingsContent.current].filter((item): item is HTMLElement => item !== null);
    const previous = backgrounds.map((item) => ({ item, inert: item.inert, ariaHidden: item.getAttribute("aria-hidden") }));
    for (const item of backgrounds) { item.inert = true; item.setAttribute("aria-hidden", "true"); }
    return () => { for (const value of previous) { value.item.inert = value.inert; if (value.ariaHidden === null) value.item.removeAttribute("aria-hidden"); else value.item.setAttribute("aria-hidden", value.ariaHidden); } };
  }, [editingProvider]);
  useEffect(() => {
    const root = providerModalRoot.current;
    if (!root) return undefined;
    const wasInert = root.inert;
    const previousAriaHidden = root.getAttribute("aria-hidden");
    if (editingModel) {
      root.inert = true;
      root.setAttribute("aria-hidden", "true");
    } else {
      root.inert = false;
      root.removeAttribute("aria-hidden");
    }
    return () => {
      root.inert = wasInert;
      if (previousAriaHidden === null) root.removeAttribute("aria-hidden");
      else root.setAttribute("aria-hidden", previousAriaHidden);
    };
  }, [editingModel]);
  useEffect(() => {
    if (!editingProvider) return undefined;
    const handleKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return;
      if (event.key === "Escape") {
        event.preventDefault();
        if (editingModel) cancelModel();
        else cancelEditor();
        return;
      }
      const activeModalRoot = editingModel ? modelModalRoot.current : providerModalRoot.current;
      if (event.key !== "Tab" || !activeModalRoot) return;
      const focusable = modalFocusableElements(activeModalRoot);
      if (!focusable.length) return;
      const first = focusable[0]; const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [editingProvider, editingModel]);

  const revealApiKey = async (providerId: string) => {
    if (settingsInteractionLocked()) return;
    if (visibleKeysRef.current[providerId]) {
      setVisibleKeys((current) => ({ ...current, [providerId]: false }));
      visibleKeysRef.current[providerId] = false;
      return;
    }
    if (revealedKeysRef.current[providerId] !== undefined) {
      setVisibleKeys((current) => ({ ...current, [providerId]: true }));
      visibleKeysRef.current[providerId] = true;
      return;
    }
    const generation = revealGeneration.current;
    setRevealPending((current) => ({ ...current, [providerId]: true }));
    setRevealError((current) => withoutRecordKey(current, providerId));
    try {
      if (!onRevealApiKey) throw new Error("Desktop API unavailable");
      const value = await onRevealApiKey(providerId);
      if (generation !== revealGeneration.current) return;
      if (value !== null && typeof value !== "string") throw new Error("Invalid reveal response");
      const revealed = value ?? "";
      revealedKeysRef.current[providerId] = revealed;
      visibleKeysRef.current[providerId] = true;
      setRevealedKeys((current) => ({ ...current, [providerId]: revealed }));
      setVisibleKeys((current) => ({ ...current, [providerId]: true }));
    } catch {
      // Bridge errors are deliberately not copied into the Settings UI: a
      // provider error may contain sensitive implementation details.
      if (generation === revealGeneration.current) setRevealError((current) => ({ ...current, [providerId]: true }));
    } finally {
      if (generation === revealGeneration.current) setRevealPending((current) => withoutRecordKey(current, providerId));
    }
  };

  const save = async () => {
    if (settingsInteractionLocked()) return;
    settingsSaveStartedRef.current = true;
    const request = settingsSaveRequest(draft, replacementKeys, touchedKeys);
    try {
      await onSave(request);
      setReplacementKeys({});
      setTouchedKeys({});
      clearRevealCache();
    } catch {
      // Keep a replacement key in the transient input when the Application
      // rejects the candidate; it is never written to Desktop preferences.
    } finally {
      settingsSaveStartedRef.current = false;
    }
  };

  const addProvider = () => {
    if (settingsInteractionLocked()) return;
    let id = "protocol";
    let index = 1;
    while (draft.providers?.[id]) id = `protocol_${index++}`;
    setDraft((current) => ({
      ...current,
      providers: { ...(current.providers ?? {}), [id]: { kind: "openai_compat", base_url: null, display_name: null, api_key_configured: false } },
      models: current.models ?? {},
    }));
    openEditor(id);
  };
  const removeProvider = (id: string) => {
    if (settingsInteractionLocked()) return;
    clearRevealCache(id);
    setReplacementKeys((current) => withoutRecordKey(current, id));
    setTouchedKeys((current) => withoutRecordKey(current, id));
    setDraft((current) => {
      const retainedModels = Object.fromEntries(Object.entries(current.models ?? {}).filter(([, model]) => model.provider_profile_id !== id));
      return {
        ...current,
        providers: Object.fromEntries(Object.entries(current.providers ?? {}).filter(([key]) => key !== id)),
        models: retainedModels,
        default_model: current.default_model && retainedModels[current.default_model] ? current.default_model : Object.keys(retainedModels)[0] ?? "",
      };
    });
  };
  const addModel = (providerId: string) => {
    if (settingsInteractionLocked()) return;
    const ref = createInternalModelRef(draft.models ?? {});
    setDraft((current) => ({
      ...current,
      default_model: current.default_model || ref,
      models: {
        ...(current.models ?? {}),
        [ref]: { provider_profile_id: providerId, remote_id: "", display_name: null, context_window: null, max_output_tokens: null, reasoning_effort: null },
      },
    }));
    modelReturnFocus.current = document.activeElement as HTMLElement;
    setModelSnapshot({ profile: null, defaultModel: draft.default_model ?? "" });
    setEditingModel({ providerId, modelRef: ref });
  };
  const editModel = (providerId: string, modelRef: string, source: HTMLElement) => {
    if (settingsInteractionLocked()) return;
    modelReturnFocus.current = source;
    setModelSnapshot({ profile: structuredClone(draft.models?.[modelRef] ?? null), defaultModel: draft.default_model ?? "" });
    setEditingModel({ providerId, modelRef });
  };
  const removeModel = (ref: string, providerId: string) => {
    if (settingsInteractionLocked()) return;
    if (editingModel?.modelRef === ref) { setEditingModel(null); setModelSnapshot(null); }
    setDraft((current) => {
      const models = Object.fromEntries(Object.entries(current.models ?? {}).filter(([key]) => key !== ref));
      if (current.default_model !== ref) return { ...current, models };
      const providerReplacement = Object.entries(models).find(([, model]) => model.provider_profile_id === providerId)?.[0];
      return { ...current, models, default_model: providerReplacement ?? Object.keys(models)[0] ?? "" };
    });
  };
  const setModelField = (modelRef: string, field: string, value: unknown) => {
    if (settingsInteractionLocked()) return;
    setDraft((current) => ({ ...current, models: updateRecord(current.models, modelRef, field, value) }));
  };
  const beginProviderDelete = () => {
    if (settingsInteractionLocked()) return;
    setProviderDeletePending(true);
  };
  const cancelProviderDelete = () => {
    if (settingsInteractionLocked()) return;
    setProviderDeletePending(false);
  };

  const edited = editingProvider ? draft.providers?.[editingProvider] : undefined;
  const editedModels = editingProvider ? modelsFor(editingProvider) : [];
  const editedModel = editingModel ? draft.models?.[editingModel.modelRef] : undefined;
  const onBackWithCleanup = () => {
    if (settingsInteractionLocked()) return;
    clearRevealCache();
    onBack();
  };
  const modalTitleId = `${fieldPrefix}-protocol-title`;
  const modelTitleId = `${fieldPrefix}-model-title`;

  return (
    <section className="settings-view" aria-label={t("settings")} aria-busy={settingsBusy} aria-describedby={settingsBusy ? "settings-busy-status" : undefined}>
      <aside ref={settingsNav} className="settings-nav" aria-label={t("settings")}>
        <button type="button" className="settings-view__back" title={t("back")} onClick={onBackWithCleanup} disabled={settingsBusy}>← {t("back")}</button>
        <div><p className="eyebrow">UthCode Desktop</p><h1>{t("settings")}</h1></div>
        <nav aria-label={t("settingsCategories")}>
          {(["providers", "defaults", "interface", "about"] as const).map((category) => <a key={category} className={activeCategory === category ? "is-active" : ""} href={`#settings-${category}`} onClick={(event) => { event.preventDefault(); setActiveCategory(category); settingsContent.current?.scrollTo({ top: 0, behavior: "smooth" }); }}>{t(category)}</a>)}
        </nav>
      </aside>
      <div ref={settingsContent} className="settings-content" aria-disabled={settingsBusy}>
        <header><div><p className="eyebrow">UthCode Desktop</p><h1>{t("settings")}</h1></div></header>
        {state.settingsError && <p className="settings-view__error" role="alert">{state.settingsError}</p>}
        {settingsBusy && <p ref={settingsBusyStatus} id="settings-busy-status" className="settings-view__busy-status" role="status" aria-live="polite" tabIndex={-1}>{t("settingsSaving")}</p>}
        {state.runtimeState === "restarting" && <p className="settings-view__runtime-status" role="status">{t("runtimeRestarting")}</p>}
        {state.runtimeError && <p className="settings-view__runtime-error" role="alert">{state.runtimeError}</p>}
        <section className={`settings-section${activeCategory === "providers" ? "" : " settings-section--inactive"}`} id="settings-providers" aria-labelledby="settings-providers-title" aria-hidden={activeCategory !== "providers" || undefined}>
          <div className="settings-section__heading"><div><p className="eyebrow">01</p><h2 id="settings-providers-title">{t("providers")}</h2></div><button type="button" className="row-add row-add--inline" title={t("addProvider")} onClick={addProvider} disabled={settingsBusy}>＋ {t("addProvider")}</button></div>
          {providers.length > 0 ? <div className="provider-list">{providers.map(([id, profile]) => {
            const linked = modelsFor(id);
            const main = linked.find(([ref]) => ref === draft.default_model) ?? linked[0];
            const label = main ? modelLabel(main[1], t("unnamedModel")) : t("noModels");
            const providerName = providerLabel(id, profile);
            return <button type="button" className="provider-row" title={`${t("editProvider")} ${providerName}`} key={id} onClick={(event) => openEditor(id, event.currentTarget)} disabled={settingsBusy}>
              <span><strong>{providerName}</strong><small>{t("protocol")} · {stringValue(profile.kind, "openai_compat")}</small></span>
              <span><small>{t("baseUrl")}</small>{stringValue(profile.base_url, "—") || "—"}</span>
              <span><small>{t("model")}</small>{label}{linked.length > 1 ? ` +${linked.length - 1}` : ""}</span>
              <span className={`provider-key-state${profile.api_key_configured === true ? " has-api-key" : ""}`} aria-label={profile.api_key_configured === true ? t("apiKeySaved") : t("apiKeyUnavailable")}><UiIcon name={profile.api_key_configured === true ? "check" : "warning"} /><small>{profile.api_key_configured === true ? t("apiKeySaved") : t("apiKeyUnavailable")}</small></span>
            </button>;
          })}</div> : <div className="settings-empty" role="status"><strong>{t("noProviders")}</strong><p>{t("emptySettings")}</p></div>}
        </section>
        <section className={`settings-section${activeCategory === "defaults" ? "" : " settings-section--inactive"}`} id="settings-defaults" aria-labelledby="settings-defaults-title" aria-hidden={activeCategory !== "defaults" || undefined}><div className="settings-section__heading"><div><p className="eyebrow">02</p><h2 id="settings-defaults-title">{t("defaults")}</h2></div></div>
          <div className="settings-row"><span className="settings-row__label">{t("permission")}</span><CustomSelect label={t("permission")} value={draft.default_permission_mode ?? "default"} options={[{ value: "default", label: t("default") }, { value: "auto", label: t("auto") }]} onChange={(value) => { if (!settingsInteractionLocked()) setDraft((current) => ({ ...current, default_permission_mode: value === "auto" ? "auto" : "default" })); }} disabled={settingsBusy} /></div>
          <div className="settings-row"><span className="settings-row__label">{t("defaultModel")}</span><CustomSelect label={t("defaultModel")} value={draft.default_model ?? ""} options={[{ value: "", label: "—" }, ...models.map(([ref, model]) => ({ value: ref, label: modelLabel(model, t("unnamedModel")) }))]} onChange={(value) => { if (!settingsInteractionLocked()) setDraft((current) => ({ ...current, default_model: value })); }} disabled={settingsBusy} /></div>
        </section>
        <section className={`settings-section${activeCategory === "interface" ? "" : " settings-section--inactive"}`} id="settings-interface" aria-labelledby="settings-interface-title" aria-hidden={activeCategory !== "interface" || undefined}><div className="settings-section__heading"><div><p className="eyebrow">03</p><h2 id="settings-interface-title">{t("interface")}</h2></div></div>
          <div className="settings-row"><span className="settings-row__label">{t("theme")}</span><CustomSelect label={t("theme")} value={state.theme} options={[{ value: "system", label: t("system") }, { value: "dark", label: t("dark") }, { value: "light", label: t("light") }]} onChange={(value) => { if (!settingsInteractionLocked()) onThemeChange(value as ThemePreference); }} disabled={settingsBusy} /></div>
          <div className="settings-row"><span className="settings-row__label">{t("language")}</span><CustomSelect label={t("language")} value={state.language} options={[{ value: "zh-CN", label: t("chinese") }, { value: "en", label: t("english") }]} onChange={(value) => { if (!settingsInteractionLocked()) onLanguageChange(value as LanguagePreference); }} disabled={settingsBusy} /></div>
        </section>
        <section className={`settings-section${activeCategory === "about" ? "" : " settings-section--inactive"}`} id="settings-about" aria-labelledby="settings-about-title" aria-hidden={activeCategory !== "about" || undefined}><div className="settings-section__heading"><div><p className="eyebrow">04</p><h2 id="settings-about-title">{t("about")}</h2></div></div><div className="settings-row"><span className="settings-row__label">{t("product")}</span><span className="settings-row__value">UthCode Desktop</span></div></section>
        <div className="settings-actions"><button type="button" title={t("cancel")} onClick={onBackWithCleanup} disabled={settingsBusy}>{t("cancel")}</button><button ref={saveButton} type="button" className="save-button" title={t("save")} onClick={() => void save()} disabled={settingsBusy || state.activeTurn}>{t("save")}</button></div>
      </div>

      {editingProvider && edited && <div className="provider-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) cancelEditor(); }}>
        <section ref={providerModalRoot} className="provider-modal" role="dialog" aria-modal={editingModel ? undefined : "true"} aria-hidden={editingModel ? "true" : undefined} aria-disabled={settingsBusy} aria-labelledby={modalTitleId}>
          <header><div><p className="eyebrow">{t("protocol")}</p><h2 id={modalTitleId}>{providerLabel(editingProvider, edited)}</h2></div><button ref={providerModalClose} type="button" title={t("cancel")} aria-label={t("cancel")} onClick={cancelEditor} disabled={settingsBusy}>×</button></header>
          <div className="provider-modal__body">
            <div className="settings-row"><label htmlFor="modal-provider-display-name">{t("providerDisplayName")}</label><input id="modal-provider-display-name" value={stringValue(edited.display_name)} placeholder={t("providerDisplayNameFallback")} onChange={(event) => { if (!settingsInteractionLocked()) setDraft((current) => ({ ...current, providers: updateRecord(current.providers, editingProvider, "display_name", event.target.value || null) })); }} disabled={settingsBusy} /></div>
            <div className="settings-row"><label htmlFor="modal-protocol">{t("protocol")}</label><CustomSelect id="modal-protocol" label={t("protocol")} value={stringValue(edited.kind, "openai_compat")} options={[{ value: "openai_compat", label: "OpenAI-compatible" }, { value: "openai_responses", label: "OpenAI" }, { value: "anthropic", label: "Anthropic" }, { value: "fake", label: t("localTestProvider") }]} onChange={(value) => { if (!settingsInteractionLocked()) setDraft((current) => ({ ...current, providers: updateRecord(current.providers, editingProvider, "kind", value) })); }} disabled={settingsBusy} /></div>
            <div className="settings-row"><label htmlFor="modal-base-url">{t("baseUrl")}</label><input id="modal-base-url" value={stringValue(edited.base_url)} onChange={(event) => { if (!settingsInteractionLocked()) setDraft((current) => ({ ...current, providers: updateRecord(current.providers, editingProvider, "base_url", event.target.value || null) })); }} disabled={settingsBusy} /></div>
            <div className="settings-row settings-row--secret"><label htmlFor="modal-api-key">{t("apiKey")}</label><div>
              <div className="api-key-control"><input id="modal-api-key" type={visibleKeys[editingProvider] ? "text" : "password"} autoComplete="new-password" placeholder={edited.api_key_configured === true ? t("replaceKey") : t("enterKey")} value={touchedKeys[editingProvider] ? replacementKeys[editingProvider] ?? "" : visibleKeys[editingProvider] ? revealedKeys[editingProvider] ?? "" : ""} onChange={(event) => { if (settingsInteractionLocked()) return; setReplacementKeys((current) => ({ ...current, [editingProvider]: event.target.value })); setTouchedKeys((current) => ({ ...current, [editingProvider]: true })); setRevealError((current) => withoutRecordKey(current, editingProvider)); }} aria-describedby="modal-api-key-help" disabled={settingsBusy} />
                <button type="button" className="api-key-toggle" title={visibleKeys[editingProvider] ? t("hideApiKey") : t("showApiKey")} aria-label={visibleKeys[editingProvider] ? t("hideApiKey") : t("showApiKey")} aria-pressed={visibleKeys[editingProvider] === true} disabled={settingsBusy || edited.api_key_configured !== true || revealPending[editingProvider] === true} onClick={() => void revealApiKey(editingProvider)}><UiIcon name={visibleKeys[editingProvider] ? "eye-off" : "eye"} /></button>
              </div>
              <p id="modal-api-key-help" className="sr-only">{edited.api_key_configured === true ? t("apiKeySaved") : t("apiKeyUnavailable")}</p>
              {revealPending[editingProvider] && <p className="settings-row__hint" role="status">{t("revealingApiKey")}</p>}
              {revealError[editingProvider] && <p className="settings-row__hint settings-row__hint--error" role="alert">{t("revealKeyFailed")}</p>}
            </div></div>
            <section className="settings-models" aria-labelledby={`${modalTitleId}-models`}><div className="settings-subsection__heading"><div><p className="eyebrow">{t("models")}</p><h3 id={`${modalTitleId}-models`}>{t("models")}</h3></div><button type="button" className="icon-button" title={t("addModel")} aria-label={t("addModel")} onClick={() => addModel(editingProvider)} disabled={settingsBusy}><UiIcon name="plus" /></button></div>
              {editedModels.length > 0 ? <div className="settings-model-list">{editedModels.map(([ref, model]) => { const label = modelLabel(model, t("unnamedModel")); return <article className="settings-model-row" key={ref}><div><strong>{label}</strong><small>{modelRemoteLabel(model, t("modelNotConfigured"))}{draft.default_model === ref ? ` · ${t("defaultMarker")}` : ""}</small></div><div className="settings-model-row__actions"><button type="button" title={`${t("editModel")} ${label}`} aria-label={`${t("editModel")} ${label}`} onClick={(event) => editModel(editingProvider, ref, event.currentTarget)} disabled={settingsBusy}><UiIcon name="edit" /></button><button type="button" title={`${t("removeModel")} ${label}`} aria-label={`${t("removeModel")} ${label}`} onClick={() => removeModel(ref, editingProvider)} disabled={settingsBusy}><UiIcon name="trash" /></button></div></article>; })}</div> : <p className="settings-empty settings-empty--compact">{t("noModels")}</p>}
            </section>
            {providerDeletePending && <div className="settings-confirm" role="alert"><p>{t("removeProviderQuestion")}</p><div><button type="button" onClick={() => { removeProvider(editingProvider); finishEditor(); }} disabled={settingsBusy}>{t("remove")}</button><button type="button" onClick={cancelProviderDelete} disabled={settingsBusy}>{t("cancel")}</button></div></div>}
          </div>
          <footer>{!providerDeletePending && <button type="button" className="danger" title={t("removeProvider")} onClick={beginProviderDelete} disabled={settingsBusy}>{t("removeProvider")}</button>}<button type="button" title={t("cancel")} onClick={cancelEditor} disabled={settingsBusy}>{t("cancel")}</button><button type="button" title={t("apply")} onClick={() => finishEditor(true)} disabled={settingsBusy}>{t("apply")}</button></footer>
        </section>
      </div>}

      {editingProvider && editingModel && editedModel && <div className="provider-modal-backdrop provider-modal-backdrop--nested" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) cancelModel(); }}>
        <section ref={modelModalRoot} className="provider-modal model-modal" role="dialog" aria-modal="true" aria-disabled={settingsBusy} aria-labelledby={modelTitleId}>
          <header><div><p className="eyebrow">{t("model")}</p><h2 id={modelTitleId}>{modelLabel(editedModel, t("unnamedModel"))}</h2></div><button ref={modelModalClose} type="button" title={t("cancel")} aria-label={t("cancel")} onClick={cancelModel} disabled={settingsBusy}>×</button></header>
          <div className="provider-modal__body">
            <div className="settings-row"><label htmlFor={modelFieldId(fieldPrefix, editingModel.modelRef, "remote")}>{t("remoteModelId")}</label><input id={modelFieldId(fieldPrefix, editingModel.modelRef, "remote")} value={stringValue(editedModel.remote_id)} onChange={(event) => setModelField(editingModel.modelRef, "remote_id", event.target.value)} disabled={settingsBusy} /></div>
            <div className="settings-row"><label htmlFor={modelFieldId(fieldPrefix, editingModel.modelRef, "display")}>{t("displayName")}</label><input id={modelFieldId(fieldPrefix, editingModel.modelRef, "display")} value={stringValue(editedModel.display_name)} placeholder={t("displayNameFallback")} onChange={(event) => setModelField(editingModel.modelRef, "display_name", event.target.value || null)} disabled={settingsBusy} /></div>
            <div className="settings-row"><label htmlFor={modelFieldId(fieldPrefix, editingModel.modelRef, "context")}>{t("contextWindow")}</label><input id={modelFieldId(fieldPrefix, editingModel.modelRef, "context")} type="number" min="1" value={editedModel.context_window == null ? "" : String(editedModel.context_window)} onChange={(event) => setModelField(editingModel.modelRef, "context_window", parseOptionalPositiveInteger(event.target.value))} disabled={settingsBusy} /></div>
            <div className="settings-row"><label htmlFor={modelFieldId(fieldPrefix, editingModel.modelRef, "output")}>{t("maxOutput")}</label><input id={modelFieldId(fieldPrefix, editingModel.modelRef, "output")} type="number" min="1" value={editedModel.max_output_tokens == null ? "" : String(editedModel.max_output_tokens)} onChange={(event) => setModelField(editingModel.modelRef, "max_output_tokens", parseOptionalPositiveInteger(event.target.value))} disabled={settingsBusy} /></div>
            <div className="settings-row"><span className="settings-row__label">{t("reasoning")}</span><CustomSelect id={modelFieldId(fieldPrefix, editingModel.modelRef, "reasoning")} label={t("reasoning")} value={stringValue(editedModel.reasoning_effort)} options={reasoningEffortOptions.map((value) => ({ value, label: value || "—" }))} onChange={(value) => setModelField(editingModel.modelRef, "reasoning_effort", value || null)} disabled={settingsBusy} /></div>
            <label className="settings-default-toggle"><input type="checkbox" checked={draft.default_model === editingModel.modelRef} onChange={(event) => { if (!settingsInteractionLocked() && event.target.checked) setDraft((current) => ({ ...current, default_model: editingModel.modelRef })); }} disabled={settingsBusy} />{t("makeDefault")}</label>
          </div>
          <footer><button type="button" title={t("cancel")} onClick={cancelModel} disabled={settingsBusy}>{t("cancel")}</button><button type="button" title={t("apply")} onClick={applyModel} disabled={settingsBusy}>{t("apply")}</button></footer>
        </section>
      </div>}
    </section>
  );
}
