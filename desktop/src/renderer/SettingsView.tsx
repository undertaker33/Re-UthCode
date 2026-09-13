import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { LanguagePreference, ThemePreference } from "../desktop-api";
import type { ConfigurationLayer, RendererState } from "./state";
import { CustomSelect } from "./CustomSelect";
import { useTranslation } from "./i18n";
import { UiIcon } from "./UiIcon";
import { SettingsEditorModal } from "./SettingsEditorModal";
import {
  modelLabel,
  providerLabel,
  providerModels,
  settingsSaveRequest,
  sourceConfig,
  stringValue,
  type ConfigurationWrite,
  type SettingsCategory,
} from "./settings-draft";

export type { ConfigurationWrite } from "./settings-draft";
export {
  configurationRequest,
  modelLabel,
  normalizeOptionalText,
  modelFieldId,
  parseOptionalPositiveInteger,
  providerLabel,
  providerModels,
  settingsSaveRequest,
  sourceConfig,
  stringValue,
  updateRecord,
  withoutRecordKey,
} from "./settings-draft";
export { reasoningEffortOptions } from "./SettingsEditorModal";

export interface SettingsViewProps {
  state: Pick<RendererState, "configuration" | "settingsError" | "settingsSaving" | "settingsLoaded" | "activeTurn" | "runtimeError" | "runtimeState" | "theme" | "language">;
  /** Narrow secret-reveal command; Settings never receives the full Desktop API. */
  onRevealApiKey?: (providerId: string) => Promise<string | null>;
  onBack: () => void;
  onSave: (request: ConfigurationWrite) => void | Promise<void>;
  onThemeChange: (theme: ThemePreference) => void;
  onLanguageChange: (language: LanguagePreference) => void;
}

function generatedProviderId(draft: ConfigurationWrite): string {
  let id = "protocol";
  let index = 1;
  while (draft.providers?.[id]) id = `protocol_${index++}`;
  return id;
}

function settingText(value: unknown): string {
  if (value === undefined || value === null) return "—";
  if (typeof value === "boolean") return value ? "on" : "off";
  if (typeof value === "string" || typeof value === "number") return String(value);
  return "—";
}

function effectiveLayer(configuration: RendererState["configuration"]): ConfigurationLayer | undefined {
  return configuration?.effective ?? configuration ?? undefined;
}

export function SettingsView({ state, onRevealApiKey, onBack, onSave, onThemeChange, onLanguageChange }: SettingsViewProps) {
  const [draft, setDraft] = useState<ConfigurationWrite>(() => sourceConfig(state.configuration));
  const [editingProvider, setEditingProvider] = useState<string | null>(null);
  const [activeCategory, setActiveCategory] = useState<SettingsCategory>("providers");
  const settingsNav = useRef<HTMLElement>(null);
  const settingsContent = useRef<HTMLDivElement>(null);
  const settingsBusyStatus = useRef<HTMLParagraphElement>(null);
  const saveButton = useRef<HTMLButtonElement>(null);
  const fieldPrefix = useId().replace(/:/gu, "");
  const returnFocus = useRef<HTMLElement | null>(null);
  const editorSnapshot = useRef<ConfigurationWrite | null>(null);
  const replacementKeys = useRef<Record<string, string>>({});
  const touchedKeys = useRef<Record<string, boolean>>({});
  const [searchReplacementKey, setSearchReplacementKey] = useState("");
  const [searchKeyTouched, setSearchKeyTouched] = useState(false);
  const settingsSavingPrevious = useRef(state.settingsSaving);
  const settingsSaveStarted = useRef(false);
  const { t } = useTranslation();
  const settingsBusy = state.settingsSaving;
  const settingsInteractionLocked = () => state.settingsSaving || settingsSaveStarted.current;
  const effective = effectiveLayer(state.configuration);
  const effectiveSearch = effective?.search ?? draft.search ?? {};
  const effectiveLimits = effective?.tool_limits ?? draft.tool_limits ?? {};
  const effectiveModelRef = typeof effective?.default_model === "string" ? effective.default_model : draft.default_model;
  const effectiveModel = effectiveModelRef ? effective?.models?.[effectiveModelRef] : undefined;
  const effectiveSource = state.configuration?.source ?? {};

  useEffect(() => {
    if (!state.configuration) return;
    setDraft(sourceConfig(state.configuration));
    replacementKeys.current = {};
    touchedKeys.current = {};
    setSearchReplacementKey("");
    setSearchKeyTouched(false);
    editorSnapshot.current = null;
  }, [state.configuration]);

  useEffect(() => {
    const wasSaving = settingsSavingPrevious.current;
    settingsSavingPrevious.current = state.settingsSaving;
    if (!state.settingsSaving && wasSaving) {
      queueMicrotask(() => saveButton.current?.focus());
      return;
    }
    if (!state.settingsSaving || wasSaving) return;
    // The Application owns the durable Save boundary. Close only the editor
    // surface when that boundary starts; preserve replacement refs until the
    // caller resolves so a failed write can be retried without retyping.
    editorSnapshot.current = null;
    setEditingProvider(null);
    queueMicrotask(() => settingsBusyStatus.current?.focus());
  }, [state.settingsSaving]);

  const providers = useMemo(() => Object.entries(draft.providers ?? {}), [draft.providers]);
  const models = useMemo(() => Object.entries(draft.models ?? {}), [draft.models]);
  const modelsFor = (id: string) => providerModels(draft, id);

  const clearReplacement = (providerId?: string) => {
    if (providerId === undefined) {
      replacementKeys.current = {};
      touchedKeys.current = {};
      return;
    }
    delete replacementKeys.current[providerId];
    delete touchedKeys.current[providerId];
  };

  const openEditor = (providerId: string, source?: HTMLElement) => {
    if (settingsInteractionLocked()) return;
    editorSnapshot.current = structuredClone(draft);
    returnFocus.current = source ?? (document.activeElement as HTMLElement | null);
    setEditingProvider(providerId);
  };

  const cancelEditor = () => {
    if (settingsInteractionLocked()) return;
    if (editorSnapshot.current) setDraft(editorSnapshot.current);
    editorSnapshot.current = null;
    clearReplacement(editingProvider ?? undefined);
    setEditingProvider(null);
    queueMicrotask(() => returnFocus.current?.focus());
  };

  const applyProvider = (_providerId: string) => {
    if (settingsInteractionLocked()) return;
    editorSnapshot.current = null;
    setEditingProvider(null);
    queueMicrotask(() => returnFocus.current?.focus());
    // Secret replacement is intentionally retained until the global Save
    // settles. The editor-local revealed value never reaches this callback.
  };

  const removeProvider = (providerId: string) => {
    if (settingsInteractionLocked()) return;
    clearReplacement(providerId);
    setDraft((current) => {
      const retainedModels = Object.fromEntries(Object.entries(current.models ?? {}).filter(([, model]) => model.provider_profile_id !== providerId));
      return {
        ...current,
        providers: Object.fromEntries(Object.entries(current.providers ?? {}).filter(([key]) => key !== providerId)),
        models: retainedModels,
        default_model: current.default_model && retainedModels[current.default_model] ? current.default_model : Object.keys(retainedModels)[0] ?? "",
      };
    });
  };

  const addProvider = () => {
    if (settingsInteractionLocked()) return;
    const id = generatedProviderId(draft);
    editorSnapshot.current = structuredClone(draft);
    returnFocus.current = document.activeElement as HTMLElement | null;
    setDraft((current) => ({
      ...current,
      providers: { ...(current.providers ?? {}), [id]: { kind: "openai_compat", base_url: null, display_name: null, api_key_configured: false } },
      models: current.models ?? {},
    }));
    setEditingProvider(id);
  };

  const save = async () => {
    if (settingsInteractionLocked()) return;
    settingsSaveStarted.current = true;
    const request = settingsSaveRequest(
      draft,
      replacementKeys.current,
      touchedKeys.current,
      searchReplacementKey,
      searchKeyTouched,
    );
    try {
      await onSave(request);
      clearReplacement();
      setSearchReplacementKey("");
      setSearchKeyTouched(false);
    } catch {
      // Preserve only the explicit replacement ref so a rejected Save can be
      // retried. Revealed values live solely inside the unmounted modal.
    } finally {
      settingsSaveStarted.current = false;
    }
  };

  const onBackWithCleanup = () => {
    if (settingsInteractionLocked()) return;
    if (editingProvider) cancelEditor();
    else clearReplacement();
    onBack();
  };

  const editing = editingProvider ? draft.providers?.[editingProvider] : undefined;

  return (
    <section className="settings-view" aria-label={t("settings")} aria-busy={settingsBusy} aria-describedby={settingsBusy ? "settings-busy-status" : undefined}>
      <aside ref={settingsNav} className="settings-nav" aria-label={t("settings")}>
        <button type="button" className="settings-view__back" title={t("back")} onClick={onBackWithCleanup} disabled={settingsBusy}>← {t("back")}</button>
        <div><p className="eyebrow">UthCode Desktop</p><h1>{t("settings")}</h1></div>
        <nav aria-label={t("settingsCategories")}>
          {(["providers", "defaults", "interface", "about"] as const).map((category) => <a key={category} className={activeCategory === category ? "is-active" : ""} href={`#settings-${category}`} onClick={(event) => { if (event.defaultPrevented) return; event.preventDefault(); setActiveCategory(category); settingsContent.current?.scrollTo({ top: 0, behavior: "smooth" }); }}>{t(category)}</a>)}
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
          <div className="settings-effective" aria-label={t("effectiveSettings")}>
            <p className="settings-row__group-label">{t("effectiveSettings")}</p>
            <div className="settings-row"><span className="settings-row__label">{t("effectiveSearch")}</span><span className="settings-row__value">{t("webSearch")}: {settingText(effectiveSearch.enabled)} · {t("searchMaxResults")}: {settingText(effectiveSearch.max_results)} · {t("searchMaxBytes")}: {settingText(effectiveSearch.max_fetch_bytes)}<small className="settings-row__hint">{t("effectiveSource")}: {effectiveSource.search ?? "default"}</small></span></div>
            <div className="settings-row"><span className="settings-row__label">{t("effectiveVision")}</span><span className="settings-row__value">{settingText(effectiveModel?.supports_images)}<small className="settings-row__hint">{t("effectiveSource")}: {effectiveSource.vision ?? "default"}</small></span></div>
            <div className="settings-row"><span className="settings-row__label">{t("effectiveToolLimits")}</span><span className="settings-row__value">{t("toolOutputBytes")}: {settingText(effectiveLimits.output_bytes)}<small className="settings-row__hint">{t("effectiveSource")}: {effectiveSource.tool_limits ?? "default"}</small></span></div>
            <div className="settings-row"><span className="settings-row__label">{t("effectiveAttachmentLimits")}</span><span className="settings-row__value">{t("toolAttachmentBytes")}: {settingText(effectiveLimits.attachment_bytes)}<small className="settings-row__hint">{t("effectiveSource")}: {effectiveSource.attachment_limits ?? "default"}</small></span></div>
          </div>
          {(() => {
            const search = draft.search ?? {};
            const searchEnabled = search.enabled === true;
            const updateSearch = (field: string, value: unknown) => {
              if (settingsInteractionLocked() || state.activeTurn) return;
              setDraft((current) => ({ ...current, search: { ...(current.search ?? {}), [field]: value } }));
            };
            const limitValue = (field: string, fallback: number) => typeof search[field] === "number" ? String(search[field]) : String(fallback);
            return <div className="settings-search" aria-label={t("searchSettings")}>
              <div className="settings-row settings-row--checkbox"><label className="settings-row__label" htmlFor="settings-search-enabled">{t("webSearch")}</label><input id="settings-search-enabled" type="checkbox" checked={searchEnabled} onChange={(event) => updateSearch("enabled", event.currentTarget.checked)} disabled={settingsBusy || state.activeTurn} /><span className="settings-row__value">{search.provider === "tavily" || search.provider === undefined ? "Tavily" : stringValue(search.provider)}</span></div>
              <div className="settings-row"><label className="settings-row__label" htmlFor="settings-search-key">{t("searchApiKey")}</label><input id="settings-search-key" type="password" value={searchReplacementKey} placeholder={search.api_key_configured === true ? t("apiKeySaved") : t("enterKey")} onChange={(event) => { setSearchReplacementKey(event.currentTarget.value); setSearchKeyTouched(true); }} disabled={settingsBusy || state.activeTurn} autoComplete="off" /></div>
              <div className="settings-row"><label className="settings-row__label" htmlFor="settings-search-max-results">{t("searchMaxResults")}</label><input id="settings-search-max-results" type="number" min={1} max={20} value={limitValue("max_results", 5)} onChange={(event) => { const value = Number(event.currentTarget.value); if (Number.isInteger(value) && value >= 1 && value <= 20) updateSearch("max_results", value); }} disabled={settingsBusy || state.activeTurn} /></div>
              <div className="settings-row"><label className="settings-row__label" htmlFor="settings-search-max-bytes">{t("searchMaxBytes")}</label><input id="settings-search-max-bytes" type="number" min={1024} max={16777216} value={limitValue("max_fetch_bytes", 2097152)} onChange={(event) => { const value = Number(event.currentTarget.value); if (Number.isInteger(value) && value >= 1024 && value <= 16777216) updateSearch("max_fetch_bytes", value); }} disabled={settingsBusy || state.activeTurn} /></div>
              <div className="settings-row"><label className="settings-row__label" htmlFor="settings-search-timeout">{t("searchTimeout")}</label><input id="settings-search-timeout" type="number" min={1} max={120} step={1} value={limitValue("timeout_seconds", 20)} onChange={(event) => { const value = Number(event.currentTarget.value); if (Number.isInteger(value) && value >= 1 && value <= 120) updateSearch("timeout_seconds", value); }} disabled={settingsBusy || state.activeTurn} /></div>
            </div>;
          })()}
          {(() => {
            const limits = draft.tool_limits ?? {};
            const updateLimit = (field: string, value: unknown) => {
              if (settingsInteractionLocked() || state.activeTurn) return;
              setDraft((current) => ({
                ...current,
                tool_limits: { ...(current.tool_limits ?? {}), [field]: value },
              }));
            };
            const numberValue = (field: string, fallback: number | string) => (
              limits[field] === undefined || limits[field] === null
                ? String(fallback)
                : String(limits[field])
            );
            return <div className="settings-search" aria-label={t("toolLimits")}>
              <p className="settings-row__group-label">{t("toolLimits")}</p>
              <div className="settings-row"><label className="settings-row__label" htmlFor="settings-tool-timeout">{t("toolTimeout")}</label><input id="settings-tool-timeout" type="number" min={0.1} max={600} step={0.1} value={numberValue("timeout_seconds", "")} placeholder="—" onChange={(event) => { const raw = event.currentTarget.value; if (!raw.trim()) updateLimit("timeout_seconds", null); else { const value = Number(raw); if (Number.isFinite(value) && value > 0 && value <= 600) updateLimit("timeout_seconds", value); } }} disabled={settingsBusy || state.activeTurn} /></div>
              <div className="settings-row"><label className="settings-row__label" htmlFor="settings-tool-output">{t("toolOutputBytes")}</label><input id="settings-tool-output" type="number" min={1024} max={16777216} step={1024} value={numberValue("output_bytes", 2097152)} onChange={(event) => { const value = Number(event.currentTarget.value); if (Number.isInteger(value) && value >= 1024 && value <= 16777216) updateLimit("output_bytes", value); }} disabled={settingsBusy || state.activeTurn} /></div>
              <div className="settings-row"><label className="settings-row__label" htmlFor="settings-tool-attachment">{t("toolAttachmentBytes")}</label><input id="settings-tool-attachment" type="number" min={1} max={67108864} step={1024} value={numberValue("attachment_bytes", 16777216)} onChange={(event) => { const value = Number(event.currentTarget.value); if (Number.isInteger(value) && value > 0 && value <= 67108864) updateLimit("attachment_bytes", value); }} disabled={settingsBusy || state.activeTurn} /></div>
            </div>;
          })()}
        </section>
        <section className={`settings-section${activeCategory === "interface" ? "" : " settings-section--inactive"}`} id="settings-interface" aria-labelledby="settings-interface-title" aria-hidden={activeCategory !== "interface" || undefined}>
          <div className="settings-section__heading"><div><p className="eyebrow">03</p><h2 id="settings-interface-title">{t("interface")}</h2></div></div>
          <div className="settings-row"><span className="settings-row__label">{t("theme")}</span><CustomSelect label={t("theme")} value={state.theme} options={[{ value: "system", label: t("system") }, { value: "dark", label: t("dark") }, { value: "light", label: t("light") }]} onChange={(value) => { if (!settingsInteractionLocked()) onThemeChange(value as ThemePreference); }} disabled={settingsBusy} /></div>
          <div className="settings-row"><span className="settings-row__label">{t("language")}</span><CustomSelect label={t("language")} value={state.language} options={[{ value: "zh-CN", label: t("chinese") }, { value: "en", label: t("english") }]} onChange={(value) => { if (!settingsInteractionLocked()) onLanguageChange(value as LanguagePreference); }} disabled={settingsBusy} /></div>
        </section>
        <section className={`settings-section${activeCategory === "about" ? "" : " settings-section--inactive"}`} id="settings-about" aria-labelledby="settings-about-title" aria-hidden={activeCategory !== "about" || undefined}><div className="settings-section__heading"><div><p className="eyebrow">04</p><h2 id="settings-about-title">{t("about")}</h2></div></div><div className="settings-row"><span className="settings-row__label">{t("product")}</span><span className="settings-row__value">UthCode Desktop</span></div></section>
        <div className="settings-actions"><button type="button" title={t("cancel")} onClick={onBackWithCleanup} disabled={settingsBusy}>{t("cancel")}</button><button ref={saveButton} type="button" className="save-button" title={t("save")} onClick={() => void save()} disabled={settingsBusy || state.activeTurn}>{t("save")}</button></div>
      </div>

      {editingProvider && editing && <SettingsEditorModal
        providerId={editingProvider}
        draft={draft}
        settingsBusy={settingsBusy}
        fieldPrefix={fieldPrefix}
        returnFocus={returnFocus.current}
        backgroundElements={[settingsNav.current, settingsContent.current]}
        onDraftChange={(update) => setDraft(update)}
        onCancel={cancelEditor}
        onApplyProvider={applyProvider}
        onRemoveProvider={removeProvider}
        onRevealApiKey={onRevealApiKey}
        replacementKey={replacementKeys.current[editingProvider] ?? ""}
        replacementTouched={touchedKeys.current[editingProvider] === true}
        onReplacementChange={(providerId, value) => { replacementKeys.current[providerId] = value; touchedKeys.current[providerId] = true; }}
      />}
    </section>
  );
}
