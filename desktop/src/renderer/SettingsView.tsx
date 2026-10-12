import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { LanguagePreference, ThemePreference } from "../desktop-api";
import type { ConfigurationLayer, ConfigurationView, RendererState, SessionSummary } from "./state";
import { CustomSelect } from "./CustomSelect";
import { useTranslation, type TranslationKey } from "./i18n";
import { UiIcon } from "./UiIcon";
import { SettingsEditorModal } from "./SettingsEditorModal";
import {
  modelFieldId,
  modelLabel,
  providerLabel,
  providerGroupIsValid,
  providerGroupSaveRequest,
  providerModels,
  sourceConfig,
  stringValue,
  type PendingConfigurationWrite,
  type ConfigurationWrite,
  type SettingsDraft,
  type SettingsCategory,
} from "./settings-draft";

export type { ConfigurationWrite } from "./settings-draft";
export {
  modelLabel,
  normalizeOptionalText,
  modelFieldId,
  parseOptionalPositiveInteger,
  providerLabel,
  providerGroupIsValid,
  providerGroupSaveRequest,
  providerModels,
  sourceConfig,
  stringValue,
  updateRecord,
} from "./settings-draft";
export { reasoningEffortOptions } from "./SettingsEditorModal";

export interface ArchivedSettingsSession {
  projectKey: string;
  projectLabel: string;
  session: SessionSummary;
}

export type { PendingConfigurationWrite } from "./settings-draft";

export interface SettingsViewProps {
  state: Pick<RendererState, "configuration" | "settingsError" | "settingsSaving" | "settingsLoaded" | "settingsApplications" | "settingsWriteFailures" | "theme" | "language">;
  /** Narrow secret-reveal command; Settings never receives the full Desktop API. */
  onRevealApiKey?: (providerId: string) => Promise<string | null>;
  onBack: () => void;
  onSave: (request: ConfigurationWrite) => unknown | Promise<unknown>;
  onRetryApply?: () => Promise<void>;
  onRetrySave?: () => Promise<void>;
  pendingWrites?: readonly PendingConfigurationWrite[];
  onLoadArchivedSessions?: () => Promise<ArchivedSettingsSession[]>;
  onRestoreArchivedSession?: (item: ArchivedSettingsSession) => Promise<boolean>;
  onThemeChange: (theme: ThemePreference) => void;
  onLanguageChange: (language: LanguagePreference) => void;
}

const noRetryApply = async () => undefined;
const noArchivedSessions = async (): Promise<ArchivedSettingsSession[]> => [];
const doNotRestoreArchive = async () => false;
const noPendingWrites: readonly PendingConfigurationWrite[] = [];
const GENERAL_PROJECT_KEY = "uthcode:general";

interface SettingsSearchTarget {
  category: SettingsCategory;
  fieldId?: string;
  labelKey: TranslationKey;
  keywords?: readonly TranslationKey[];
  providerId?: string;
  modelRef?: string;
  editorFieldId?: string;
  resultContext?: string;
}

const SETTINGS_SEARCH_TARGETS: readonly SettingsSearchTarget[] = [
  { category: "providers", fieldId: "settings-default-model", labelKey: "defaultModel", keywords: ["providers", "model"] },
  { category: "tools", fieldId: "settings-search-enabled", labelKey: "webSearch", keywords: ["searchSettings", "effectiveSearch"] },
  { category: "tools", fieldId: "settings-search-key", labelKey: "searchApiKey", keywords: ["webSearch", "searchSettings"] },
  { category: "tools", fieldId: "settings-search-max-results", labelKey: "searchMaxResults", keywords: ["webSearch", "searchSettings"] },
  { category: "tools", fieldId: "settings-search-max-bytes", labelKey: "searchMaxBytes", keywords: ["webSearch", "searchSettings"] },
  { category: "tools", fieldId: "settings-search-timeout", labelKey: "searchTimeout", keywords: ["webSearch", "searchSettings"] },
  { category: "tools", fieldId: "settings-tool-timeout", labelKey: "toolTimeout", keywords: ["toolLimits"] },
  { category: "tools", fieldId: "settings-tool-output", labelKey: "toolOutputBytes", keywords: ["toolLimits", "effectiveToolLimits"] },
  { category: "tools", fieldId: "settings-tool-attachment", labelKey: "toolAttachmentBytes", keywords: ["toolLimits", "effectiveAttachmentLimits"] },
  { category: "general", fieldId: "settings-general-title", labelKey: "about", keywords: ["product"] },
  { category: "archive", fieldId: "settings-archive-project-filter", labelKey: "archiveProjectFilter", keywords: ["archive"] },
  { category: "archive", fieldId: "settings-archive-text-filter", labelKey: "archiveTextFilter", keywords: ["archive"] },
  { category: "appearance", fieldId: "settings-theme", labelKey: "theme", keywords: ["appearance"] },
  { category: "appearance", fieldId: "settings-language", labelKey: "language", keywords: ["appearance"] },
  { category: "security", fieldId: "settings-permission", labelKey: "permission", keywords: ["security", "effectivePermission"] },
];

function restorePendingSettingsDraft(draft: SettingsDraft, pending: readonly PendingConfigurationWrite[]): SettingsDraft {
  let next = draft;
  for (const { request } of pending) {
    if (Object.hasOwn(request, "default_model")) next = { ...next, default_model: request.default_model };
    if (Object.hasOwn(request, "default_permission_mode")) next = { ...next, default_permission_mode: request.default_permission_mode };
    const search = Object.fromEntries(Object.entries(request.search ?? {}).filter(([field]) => field !== "api_key"));
    if (Object.keys(search).length) next = { ...next, search: { ...(next.search ?? {}), ...search } };
    if (Object.keys(request.tool_limits ?? {}).length) next = { ...next, tool_limits: { ...(next.tool_limits ?? {}), ...request.tool_limits } };
  }
  return next;
}

function generatedProviderId(draft: SettingsDraft): string {
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

function SettingsSwitch({ id, checked, disabled, onChange }: { id: string; checked: boolean; disabled: boolean; onChange: (checked: boolean) => void }) {
  return <span className="settings-switch"><input id={id} type="checkbox" role="switch" checked={checked} onChange={(event) => onChange(event.currentTarget.checked)} disabled={disabled} /><span className="settings-switch__track" aria-hidden="true"><span /></span></span>;
}

function effectiveLayer(configuration: RendererState["configuration"]): ConfigurationLayer | undefined {
  return configuration?.effective ?? configuration ?? undefined;
}

function sameSettingsValue(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function isConfigurationView(value: unknown): value is ConfigurationView {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function adoptSavedProviderGroup(
  current: SettingsDraft,
  submitted: SettingsDraft,
  before: SettingsDraft,
  request: ConfigurationWrite,
  providerId: string,
  savedConfiguration: ConfigurationView,
): SettingsDraft {
  const saved = sourceConfig(savedConfiguration);
  const providers = { ...(current.providers ?? {}) };
  const currentProvider = current.providers?.[providerId];
  const submittedProvider = submitted.providers?.[providerId];
  if (sameSettingsValue(currentProvider, submittedProvider)) {
    const savedProvider = saved.providers?.[providerId];
    if (savedProvider) providers[providerId] = savedProvider;
    else delete providers[providerId];
  }

  const affectedModels = new Set<string>(Object.keys(request.models ?? {}));
  for (const source of [before.models ?? {}, submitted.models ?? {}]) {
    for (const [modelRef, model] of Object.entries(source)) {
      if (model?.provider_profile_id === providerId) affectedModels.add(modelRef);
    }
  }
  const models = { ...(current.models ?? {}) };
  for (const modelRef of affectedModels) {
    if (!sameSettingsValue(current.models?.[modelRef], submitted.models?.[modelRef])) continue;
    const savedModel = saved.models?.[modelRef];
    if (savedModel) models[modelRef] = savedModel;
    else delete models[modelRef];
  }

  return {
    ...current,
    providers,
    models,
    ...(Object.hasOwn(request, "default_model") && current.default_model === submitted.default_model
      ? { default_model: saved.default_model }
      : {}),
  };
}

export function SettingsView({ state, onRevealApiKey, onBack, onSave, onRetryApply = noRetryApply, onRetrySave, pendingWrites = noPendingWrites, onLoadArchivedSessions = noArchivedSessions, onRestoreArchivedSession = doNotRestoreArchive, onThemeChange, onLanguageChange }: SettingsViewProps) {
  const [draft, setDraft] = useState<SettingsDraft>(() => restorePendingSettingsDraft(sourceConfig(state.configuration), pendingWrites));
  const [editingProvider, setEditingProvider] = useState<string | null>(null);
  const [activeCategory, setActiveCategory] = useState<SettingsCategory>("providers");
  const settingsNav = useRef<HTMLElement>(null);
  const settingsContent = useRef<HTMLDivElement>(null);
  const fieldPrefix = useId().replace(/:/gu, "");
  const returnFocus = useRef<HTMLElement | null>(null);
  const editorSnapshot = useRef<SettingsDraft | null>(null);
  const providerDeletionPending = useRef<string | null>(null);
  const replacementKeys = useRef<Record<string, string>>({});
  const touchedKeys = useRef<Record<string, boolean>>({});
  const draftRef = useRef<SettingsDraft>(draft);
  draftRef.current = draft;
  const configurationInitialized = useRef(state.configuration !== null);
  const [searchReplacementKey, setSearchReplacementKey] = useState("");
  const [providerSaving, setProviderSaving] = useState(false);
  const [searchKeyFailed, setSearchKeyFailed] = useState(false);
  const [searchKeySaving, setSearchKeySaving] = useState(false);
  const [restoringArchiveId, setRestoringArchiveId] = useState<string | null>(null);
  const [groupError, setGroupError] = useState<string | null>(null);
  const [archiveItems, setArchiveItems] = useState<ArchivedSettingsSession[]>([]);
  const [archiveLoading, setArchiveLoading] = useState(false);
  const [archiveError, setArchiveError] = useState(false);
  const [archiveRestoreError, setArchiveRestoreError] = useState(false);
  const [archiveProjectFilter, setArchiveProjectFilter] = useState("");
  const [archiveTextFilter, setArchiveTextFilter] = useState("");
  const [settingsSearchQuery, setSettingsSearchQuery] = useState("");
  const [pendingSettingsSearchTarget, setPendingSettingsSearchTarget] = useState<{ category: SettingsCategory; fieldId: string } | null>(null);
  const [editingInitialModel, setEditingInitialModel] = useState<string | null>(null);
  const [editingInitialFocusId, setEditingInitialFocusId] = useState<string | null>(null);
  const [numericDrafts, setNumericDrafts] = useState<Record<string, string>>({});
  const [numericErrors, setNumericErrors] = useState<Record<string, boolean>>({});
  const searchKeyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const searchKeyGeneration = useRef(0);
  const { t } = useTranslation();
  const settingsInteractionLocked = () => providerSaving || searchKeySaving;
  const effective = effectiveLayer(state.configuration);
  const effectiveSearch = effective?.search ?? draft.search ?? {};
  const effectiveLimits = effective?.tool_limits ?? draft.tool_limits ?? {};
  const effectiveModelRef = typeof effective?.default_model === "string" ? effective.default_model : draft.default_model;
  const effectiveModel = effectiveModelRef ? effective?.models?.[effectiveModelRef] : undefined;
  const effectiveSource = state.configuration?.source ?? {};

  useEffect(() => {
    if (!state.configuration || configurationInitialized.current) return;
    configurationInitialized.current = true;
    const loaded = restorePendingSettingsDraft(sourceConfig(state.configuration), pendingWrites);
    draftRef.current = loaded;
    setDraft(loaded);
  }, [state.configuration]);

  useEffect(() => {
    if (activeCategory !== "archive") return;
    let current = true;
    setArchiveLoading(true);
    setArchiveError(false);
    void onLoadArchivedSessions().then((items) => {
      if (current) setArchiveItems(items);
    }).catch(() => {
      if (current) setArchiveError(true);
    }).finally(() => {
      if (current) setArchiveLoading(false);
    });
    return () => { current = false; };
  }, [activeCategory, onLoadArchivedSessions]);

  useEffect(() => {
    const pending = pendingSettingsSearchTarget;
    if (!pending || pending.category !== activeCategory) return;
    const target = document.getElementById(pending.fieldId);
    if (!target) return;
    target.scrollIntoView?.({ behavior: "smooth", block: "center" });
    const focusTarget = target.matches("input, button, [tabindex]:not([tabindex='-1'])")
      ? target as HTMLElement
      : target.closest(".settings-section")?.querySelector<HTMLElement>("input:not([type='password']), button[aria-haspopup='listbox'], button:not([disabled])");
    focusTarget?.focus({ preventScroll: true });
    setPendingSettingsSearchTarget(null);
  }, [activeCategory, pendingSettingsSearchTarget]);

  useEffect(() => () => {
    if (searchKeyTimer.current !== null) clearTimeout(searchKeyTimer.current);
  }, []);

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

  const openEditor = (providerId: string, source?: HTMLElement, initialFocusId: string | null = null) => {
    if (settingsInteractionLocked()) return;
    editorSnapshot.current = structuredClone(draftRef.current);
    providerDeletionPending.current = null;
    setEditingInitialModel(null);
    setEditingInitialFocusId(initialFocusId);
    setGroupError(null);
    returnFocus.current = source ?? (document.activeElement as HTMLElement | null);
    setEditingProvider(providerId);
  };

  const openModelEditorFromSearch = (providerId: string, modelRef: string, source: HTMLElement, initialFocusId: string | null) => {
    if (settingsInteractionLocked()) return;
    editorSnapshot.current = structuredClone(draftRef.current);
    providerDeletionPending.current = null;
    setGroupError(null);
    returnFocus.current = source;
    setEditingInitialModel(modelRef);
    setEditingInitialFocusId(initialFocusId);
    setEditingProvider(providerId);
  };

  const cancelEditor = () => {
    if (settingsInteractionLocked()) return;
    if (editorSnapshot.current) {
      const restored = structuredClone(editorSnapshot.current);
      draftRef.current = restored;
      setDraft(restored);
    }
    editorSnapshot.current = null;
    providerDeletionPending.current = null;
    clearReplacement(editingProvider ?? undefined);
    setEditingProvider(null);
    setEditingInitialModel(null);
    setEditingInitialFocusId(null);
    queueMicrotask(() => returnFocus.current?.focus());
  };

  const applyProvider = async (providerId: string): Promise<boolean> => {
    if (settingsInteractionLocked()) return false;
    const before = editorSnapshot.current ?? sourceConfig(state.configuration);
    const current = draftRef.current;
    const deleting = providerDeletionPending.current === providerId;
    let candidate = current;
    if (deleting) {
      const models = Object.fromEntries(Object.entries(current.models ?? {}).filter(([, model]) => model?.provider_profile_id !== providerId));
      candidate = {
        ...current,
        providers: Object.fromEntries(Object.entries(current.providers ?? {}).filter(([id]) => id !== providerId)),
        models,
        default_model: current.default_model && models[current.default_model]
          ? current.default_model
          : Object.keys(models)[0] ?? "",
      };
    }
    if (!providerGroupIsValid(candidate, providerId)) {
      setGroupError(t("settingsGroupInvalid"));
      return false;
    }
    const request = providerGroupSaveRequest(
      before,
      deleting ? current : candidate,
      providerId,
      replacementKeys.current[providerId] ?? "",
      touchedKeys.current[providerId] === true,
    );
    if (deleting) {
      request.providers = { [providerId]: null };
      const removedModels = Object.fromEntries(Object.entries(before.models ?? {})
        .filter(([, model]) => model?.provider_profile_id === providerId)
        .map(([modelRef]) => [modelRef, null]));
      if (Object.keys(removedModels).length) request.models = removedModels;
      else delete request.models;
      if (before.default_model !== candidate.default_model) request.default_model = candidate.default_model;
    }
    setProviderSaving(true);
    setGroupError(null);
    try {
      const saveResult = await onSave(request);
      const savedConfiguration = isConfigurationView(saveResult) ? saveResult : null;
      const currentDraft = deleting ? candidate : draftRef.current;
      const nextDraft = savedConfiguration
        ? adoptSavedProviderGroup(currentDraft, candidate, before, request, providerId, savedConfiguration)
        : currentDraft;
      if (deleting || savedConfiguration) {
        draftRef.current = nextDraft;
        setDraft(nextDraft);
      }
      editorSnapshot.current = null;
      providerDeletionPending.current = null;
      clearReplacement(providerId);
      setEditingProvider(null);
      setEditingInitialModel(null);
      setEditingInitialFocusId(null);
      queueMicrotask(() => returnFocus.current?.focus());
      return true;
    } catch {
      setGroupError(t("settingsSaveFailed"));
      return false;
    } finally {
      setProviderSaving(false);
    }
  };

  const removeProvider = (providerId: string) => {
    if (settingsInteractionLocked()) return;
    providerDeletionPending.current = providerId;
  };

  const addProvider = () => {
    if (settingsInteractionLocked()) return;
    const current = draftRef.current;
    const id = generatedProviderId(current);
    editorSnapshot.current = structuredClone(current);
    returnFocus.current = document.activeElement as HTMLElement | null;
    setEditingInitialModel(null);
    setEditingInitialFocusId(null);
    const next = {
      ...current,
      providers: { ...(current.providers ?? {}), [id]: { kind: "openai_compat", base_url: null, display_name: null, api_key_configured: false } },
      models: current.models ?? {},
    };
    draftRef.current = next;
    setDraft(next);
    setEditingProvider(id);
  };

  const savePatch = (request: ConfigurationWrite) => {
    try { void Promise.resolve(onSave(request)).catch(() => undefined); } catch { /* App owns retryable non-secret patches. */ }
  };

  const retryFailedWrites = () => onRetrySave?.();

  const updateField = (field: "default_model" | "default_permission_mode", value: string) => {
    if (settingsInteractionLocked()) return;
    const request: ConfigurationWrite = field === "default_model"
      ? { default_model: value }
      : { default_permission_mode: value === "auto" ? "auto" : "default" };
    const next: SettingsDraft = field === "default_model"
      ? { ...draftRef.current, default_model: value }
      : { ...draftRef.current, default_permission_mode: value === "auto" ? "auto" : "default" };
    draftRef.current = next;
    setDraft(next);
    savePatch(request);
  };

  const updateSearchField = (field: string, value: unknown) => {
    if (settingsInteractionLocked()) return;
    const next = { ...draftRef.current, search: { ...(draftRef.current.search ?? {}), [field]: value } };
    draftRef.current = next;
    setDraft(next);
    savePatch({ search: { [field]: value } });
  };

  const updateToolLimit = (field: string, value: unknown) => {
    if (settingsInteractionLocked()) return;
    const next = { ...draftRef.current, tool_limits: { ...(draftRef.current.tool_limits ?? {}), [field]: value } };
    draftRef.current = next;
    setDraft(next);
    savePatch({ tool_limits: { [field]: value } });
  };

  const updateNumericSetting = (
    identity: string,
    raw: string,
    minimum: number,
    maximum: number,
    integer: boolean,
    commit: (value: number | null) => void,
    emptyMeansDefault = false,
  ) => {
    setNumericDrafts((current) => ({ ...current, [identity]: raw }));
    if (emptyMeansDefault && raw.trim() === "") {
      setNumericErrors((current) => ({ ...current, [identity]: false }));
      commit(null);
      return;
    }
    const value = Number(raw);
    if (!raw.trim() || !Number.isFinite(value) || value < minimum || value > maximum || integer && !Number.isInteger(value)) {
      setNumericErrors((current) => ({ ...current, [identity]: true }));
      return;
    }
    setNumericErrors((current) => ({ ...current, [identity]: false }));
    commit(value);
  };

  const updateSearchKey = (value: string) => {
    setSearchReplacementKey(value);
    setSearchKeyFailed(false);
    const request: ConfigurationWrite = { search: { api_key: value } };
    searchKeyGeneration.current += 1;
    const generation = searchKeyGeneration.current;
    if (searchKeyTimer.current !== null) clearTimeout(searchKeyTimer.current);
    searchKeyTimer.current = setTimeout(() => {
      searchKeyTimer.current = null;
      void Promise.resolve(onSave(request)).then(() => {
        if (generation !== searchKeyGeneration.current) return;
        setSearchKeyFailed(false);
        setSearchReplacementKey("");
        const next = { ...draftRef.current, search: { ...(draftRef.current.search ?? {}), api_key_configured: Boolean(value.trim()) } };
        draftRef.current = next;
        setDraft(next);
      }).catch(() => {
        if (generation === searchKeyGeneration.current) setSearchKeyFailed(true);
      });
    }, 500);
  };

  const onBackWithCleanup = () => {
    if (settingsInteractionLocked()) return;
    if (searchKeyTimer.current !== null) clearTimeout(searchKeyTimer.current);
    searchKeyTimer.current = null;
    searchKeyGeneration.current += 1;
    setSearchReplacementKey("");
    setSearchKeyFailed(false);
    if (editingProvider) cancelEditor();
    else clearReplacement();
    onBack();
  };

  const retrySearchKey = async () => {
    if (searchKeySaving) return;
    const generation = searchKeyGeneration.current;
    const value = searchReplacementKey;
    setSearchKeySaving(true);
    try {
      await onSave({ search: { api_key: value } });
      if (generation === searchKeyGeneration.current) {
        setSearchKeyFailed(false);
        setSearchReplacementKey("");
        const next = { ...draftRef.current, search: { ...(draftRef.current.search ?? {}), api_key_configured: Boolean(value.trim()) } };
        draftRef.current = next;
        setDraft(next);
      }
    } catch {
      if (generation === searchKeyGeneration.current) setSearchKeyFailed(true);
    } finally {
      setSearchKeySaving(false);
    }
  };

  const updateDraft = (update: (current: SettingsDraft) => SettingsDraft) => {
    const next = update(draftRef.current);
    draftRef.current = next;
    setDraft(next);
  };

  const restoreArchiveItem = async (item: ArchivedSettingsSession) => {
    if (restoringArchiveId !== null) return;
    setRestoringArchiveId(item.session.session_id);
    setArchiveRestoreError(false);
    try {
      if (await onRestoreArchivedSession(item)) {
        setArchiveItems((current) => current.filter((entry) => entry.session.session_id !== item.session.session_id || entry.projectKey !== item.projectKey));
      } else {
        setArchiveRestoreError(true);
      }
    } catch {
      setArchiveRestoreError(true);
    } finally {
      setRestoringArchiveId(null);
    }
  };

  const editing = editingProvider ? draft.providers?.[editingProvider] : undefined;
  const archiveFiltered = archiveItems.filter((item) => {
    const textQuery = archiveTextFilter.trim().toLocaleLowerCase();
    const sessionText = [item.session.title, item.session.preview, item.session.session_id]
      .filter((value): value is string => typeof value === "string")
      .join(" ").toLocaleLowerCase();
    return (!archiveProjectFilter || item.projectKey === archiveProjectFilter)
      && (!textQuery || sessionText.includes(textQuery));
  });
  const archiveGroups = Array.from(archiveFiltered.reduce((groups, item) => {
    const group = groups.get(item.projectKey) ?? { label: item.projectLabel, items: [] as ArchivedSettingsSession[] };
    group.items.push(item);
    groups.set(item.projectKey, group);
    return groups;
  }, new Map<string, { label: string; items: ArchivedSettingsSession[] }>()));
  const archiveProjectLabels = new Map<string, string>(archiveItems.map((item) => [item.projectKey, item.projectLabel]));
  const archiveLabelCounts = new Map<string, number>();
  for (const [projectKey, label] of archiveProjectLabels) {
    if (projectKey === GENERAL_PROJECT_KEY) continue;
    archiveLabelCounts.set(label, (archiveLabelCounts.get(label) ?? 0) + 1);
  }
  const archiveProjectOptions = [
    { value: "", label: t("archiveAllProjects") },
    { value: GENERAL_PROJECT_KEY, label: t("generalMode") },
    ...Array.from(archiveProjectLabels.entries())
      .filter(([projectKey]) => projectKey !== GENERAL_PROJECT_KEY)
      .sort((left, right) => left[1].localeCompare(right[1]) || left[0].localeCompare(right[0]))
      .map(([projectKey, label]) => ({
        value: projectKey,
        label: (archiveLabelCounts.get(label) ?? 0) > 1 ? `${label} · ${projectKey}` : label,
      })),
  ];
  const providerSearchTargets: SettingsSearchTarget[] = providers.flatMap(([providerId], index) => {
    const resultContext = `${t("protocol")} ${index + 1}`;
    return [
      { category: "providers", labelKey: "providerDisplayName", keywords: ["providerDisplayNameFallback"], providerId, editorFieldId: "modal-provider-display-name", resultContext },
      { category: "providers", labelKey: "protocol", providerId, editorFieldId: "modal-protocol", resultContext },
      { category: "providers", labelKey: "baseUrl", providerId, editorFieldId: "modal-base-url", resultContext },
      { category: "providers", labelKey: "apiKey", keywords: ["enterKey", "replaceKey", "apiKeySaved", "apiKeyUnavailable"], providerId, editorFieldId: "modal-api-key", resultContext },
    ];
  });
  const modelSearchTargets: SettingsSearchTarget[] = models.flatMap(([modelRef, model], index) => {
    const providerId = stringValue(model.provider_profile_id);
    if (!draft.providers?.[providerId]) return [];
    const resultContext = `${t("model")} ${index + 1}`;
    return [
      { category: "providers", labelKey: "remoteModelId", keywords: ["modelNotConfigured"], providerId, modelRef, editorFieldId: modelFieldId(fieldPrefix, modelRef, "remote"), resultContext },
      { category: "providers", labelKey: "displayName", keywords: ["displayNameFallback"], providerId, modelRef, editorFieldId: modelFieldId(fieldPrefix, modelRef, "display"), resultContext },
      { category: "providers", labelKey: "contextWindow", providerId, modelRef, editorFieldId: modelFieldId(fieldPrefix, modelRef, "context"), resultContext },
      { category: "providers", labelKey: "maxOutput", providerId, modelRef, editorFieldId: modelFieldId(fieldPrefix, modelRef, "output"), resultContext },
      { category: "providers", labelKey: "reasoning", providerId, modelRef, editorFieldId: modelFieldId(fieldPrefix, modelRef, "reasoning"), resultContext },
      { category: "providers", labelKey: "supportsImages", providerId, modelRef, editorFieldId: modelFieldId(fieldPrefix, modelRef, "supports"), resultContext },
      { category: "providers", labelKey: "makeDefault", providerId, modelRef, editorFieldId: modelFieldId(fieldPrefix, modelRef, "default"), resultContext },
    ];
  });
  const settingsSearchCatalog: readonly SettingsSearchTarget[] = [
    ...SETTINGS_SEARCH_TARGETS,
    ...providerSearchTargets,
    ...modelSearchTargets,
  ];
  const searchTerm = settingsSearchQuery.trim().toLocaleLowerCase();
  const settingsSearchResults = searchTerm
    ? settingsSearchCatalog.filter((target) => [t(target.labelKey), t(target.category), ...(target.keywords ?? []).map((key) => t(key))]
      .join(" ").normalize("NFKC").toLocaleLowerCase().includes(searchTerm.normalize("NFKC")))
    : [];
  const openSettingsSearchResult = (target: typeof settingsSearchCatalog[number], source: HTMLButtonElement) => {
    if (settingsInteractionLocked()) return;
    setActiveCategory(target.category);
    if (target.providerId && target.modelRef && target.editorFieldId) {
      openModelEditorFromSearch(target.providerId, target.modelRef, source, target.editorFieldId);
      return;
    }
    if (target.providerId && target.editorFieldId) {
      openEditor(target.providerId, source, target.editorFieldId);
      return;
    }
    if (target.fieldId) setPendingSettingsSearchTarget({ category: target.category, fieldId: target.fieldId });
  };
  const showSettingsStatus = state.settingsSaving || searchKeySaving || state.settingsWriteFailures > 0 || searchKeyFailed
    || state.settingsApplications.failed > 0 || state.settingsApplications.pending > 0;

  return (
    <section className="settings-view" aria-label={t("settings")} aria-busy={state.settingsSaving}>
      <aside ref={settingsNav} className="settings-nav" aria-label={t("settings")}>
        <button type="button" className="settings-view__back" title={t("back")} onClick={onBackWithCleanup} disabled={providerSaving || searchKeySaving}>← {t("back")}</button>
        <div className="settings-nav__title"><h1>{t("settings")}</h1></div>
        <div className="settings-global-search" role="search">
          <label className="sr-only" htmlFor="settings-global-search-input">{t("settingsSearch")}</label>
          <UiIcon name="search" />
          <input id="settings-global-search-input" type="search" value={settingsSearchQuery} onChange={(event) => setSettingsSearchQuery(event.currentTarget.value)} placeholder={t("settingsSearchPlaceholder")} autoComplete="off" aria-controls="settings-global-search-results" aria-expanded={settingsSearchQuery.trim().length > 0} />
          {settingsSearchQuery && <button type="button" className="settings-global-search__clear" aria-label={t("settingsSearchClear")} title={t("settingsSearchClear")} onClick={() => setSettingsSearchQuery("")}><UiIcon name="close" /></button>}
          {settingsSearchQuery.trim() && <div className="settings-global-search__results" id="settings-global-search-results" aria-label={t("settingsSearchResults")}>
            {settingsSearchResults.length ? settingsSearchResults.map((target) => <button type="button" key={`${target.category}:${target.providerId ?? ""}:${target.modelRef ?? ""}:${target.editorFieldId ?? target.fieldId ?? target.labelKey}`} onClick={(event) => openSettingsSearchResult(target, event.currentTarget)} disabled={settingsInteractionLocked()}>
              <span>{t(target.labelKey)}</span><small>{target.resultContext ?? t(target.category)}</small>
            </button>) : <p role="status">{t("settingsSearchNoResults")}</p>}
          </div>}
        </div>
        <nav aria-label={t("settingsCategories")}>
          {(["providers", "general", "tools", "security", "appearance", "archive"] as const).map((category) => <a key={category} className={activeCategory === category ? "is-active" : ""} href={`#settings-${category}`} onClick={(event) => { if (event.defaultPrevented) return; event.preventDefault(); setActiveCategory(category); settingsContent.current?.scrollTo({ top: 0, behavior: "smooth" }); }}>{t(category)}</a>)}
        </nav>
      </aside>
      <div ref={settingsContent} className="settings-content">
        <header><div><h1>{t(activeCategory)}</h1></div></header>
        {state.settingsError && <p className="settings-view__error" role="alert">{state.settingsError}</p>}
        {showSettingsStatus && <div className="settings-autosave-status" role="status" aria-live="polite">
          <span>{state.settingsSaving || searchKeySaving ? t("settingsSaving") : state.settingsWriteFailures > 0 || searchKeyFailed ? t("settingsWriteFailed") : state.settingsApplications.failed > 0
            ? t("settingsApplyFailed") : t("settingsPending")}</span>
          {state.settingsWriteFailures > 0 && onRetrySave && <button type="button" title={t("retrySettingsSave")} onClick={() => void retryFailedWrites()}>{t("retrySettingsSave")}</button>}
          {state.settingsApplications.failed > 0 && <button type="button" onClick={() => void onRetryApply()}>{t("retrySettingsApply")}</button>}
        </div>}
        <section className={`settings-section${activeCategory === "providers" ? "" : " settings-section--inactive"}`} id="settings-providers" aria-labelledby="settings-providers-title" aria-hidden={activeCategory !== "providers" || undefined}>
          <div className="settings-section__heading"><div><p className="eyebrow">01</p><h2 id="settings-providers-title">{t("providers")}</h2></div><button type="button" className="row-add row-add--inline" title={t("addProvider")} onClick={addProvider} disabled={providerSaving}>＋ {t("addProvider")}</button></div>
          <p className="settings-row__group-label">{t("defaultModel")}</p>
          <div className="settings-row" id="settings-default-model"><span className="settings-row__label">{t("defaultModel")}</span><CustomSelect label={t("defaultModel")} value={draft.default_model ?? ""} options={models.map(([ref, model]) => ({ value: ref, label: modelLabel(model, t("unnamedModel")) }))} onChange={(value) => updateField("default_model", value)} disabled={providerSaving || models.length === 0} /></div>
          {providers.length > 0 ? <div className="provider-list">{providers.map(([id, profile]) => {
            const linked = modelsFor(id);
            const main = linked.find(([ref]) => ref === draft.default_model) ?? linked[0];
            const label = main ? modelLabel(main[1], t("unnamedModel")) : t("noModels");
            const providerName = providerLabel(id, profile);
            return <button type="button" className="provider-row" title={`${t("editProvider")} ${providerName}`} key={id} onClick={(event) => openEditor(id, event.currentTarget)} disabled={providerSaving}>
              <span><strong>{providerName}</strong><small>{t("protocol")} · {stringValue(profile.kind, "openai_compat")}</small></span>
              <span><small>{t("baseUrl")}</small>{stringValue(profile.base_url, "—") || "—"}</span>
              <span><small>{t("model")}</small>{label}{linked.length > 1 ? ` +${linked.length - 1}` : ""}</span>
              <span className={`provider-key-state${profile.api_key_configured === true ? " has-api-key" : ""}`} aria-label={profile.api_key_configured === true ? t("apiKeySaved") : t("apiKeyUnavailable")}><UiIcon name={profile.api_key_configured === true ? "check" : "warning"} /><small>{profile.api_key_configured === true ? t("apiKeySaved") : t("apiKeyUnavailable")}</small></span>
            </button>;
          })}</div> : <div className="settings-empty" role="status"><strong>{t("noProviders")}</strong><p>{t("emptySettings")}</p></div>}
        </section>
        <section className={`settings-section${activeCategory === "tools" ? "" : " settings-section--inactive"}`} id="settings-tools" aria-labelledby="settings-tools-title" aria-hidden={activeCategory !== "tools" || undefined}><div className="settings-section__heading"><div><p className="eyebrow">03</p><h2 id="settings-tools-title">{t("tools")}</h2></div></div>
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
            const limitValue = (field: string, fallback: number) => numericDrafts[`search.${field}`] ?? (typeof search[field] === "number" ? String(search[field]) : String(fallback));
            const numericError = (identity: string) => numericErrors[identity] && <small className="settings-row__hint settings-row__hint--error" role="alert">{t("settingsInvalidNumber")}</small>;
            return <div className="settings-search" aria-label={t("searchSettings")}>
              <div className="settings-row settings-row--switch"><label className="settings-row__label" htmlFor="settings-search-enabled">{t("webSearch")}</label><SettingsSwitch id="settings-search-enabled" checked={searchEnabled} onChange={(checked) => updateSearchField("enabled", checked)} disabled={providerSaving} /><span className="settings-row__value">{search.provider === "tavily" || search.provider === undefined ? "Tavily" : stringValue(search.provider)}</span></div>
              <div className="settings-row"><label className="settings-row__label" htmlFor="settings-search-key">{t("searchApiKey")}</label><div><input id="settings-search-key" type="password" value={searchReplacementKey} placeholder={search.api_key_configured === true ? t("apiKeySaved") : t("enterKey")} onChange={(event) => updateSearchKey(event.currentTarget.value)} disabled={providerSaving || searchKeySaving} autoComplete="off" />{searchKeyFailed && <><small className="settings-row__hint settings-row__hint--error" role="alert">{t("settingsWriteFailed")}</small><button type="button" onClick={() => void retrySearchKey()}>{t("retrySearchKeySave")}</button></>}</div></div>
              <div className="settings-row"><label className="settings-row__label" htmlFor="settings-search-max-results">{t("searchMaxResults")}</label><div><input id="settings-search-max-results" type="number" min={1} max={20} aria-invalid={numericErrors["search.max_results"] || undefined} value={limitValue("max_results", 5)} onChange={(event) => updateNumericSetting("search.max_results", event.currentTarget.value, 1, 20, true, (value) => { if (value !== null) updateSearchField("max_results", value); })} disabled={providerSaving} />{numericError("search.max_results")}</div></div>
              <div className="settings-row"><label className="settings-row__label" htmlFor="settings-search-max-bytes">{t("searchMaxBytes")}</label><div><input id="settings-search-max-bytes" type="number" min={1024} max={16777216} aria-invalid={numericErrors["search.max_fetch_bytes"] || undefined} value={limitValue("max_fetch_bytes", 2097152)} onChange={(event) => updateNumericSetting("search.max_fetch_bytes", event.currentTarget.value, 1024, 16777216, true, (value) => { if (value !== null) updateSearchField("max_fetch_bytes", value); })} disabled={providerSaving} />{numericError("search.max_fetch_bytes")}</div></div>
              <div className="settings-row"><label className="settings-row__label" htmlFor="settings-search-timeout">{t("searchTimeout")}</label><div><input id="settings-search-timeout" type="number" min={1} max={120} step={1} aria-invalid={numericErrors["search.timeout_seconds"] || undefined} value={limitValue("timeout_seconds", 20)} onChange={(event) => updateNumericSetting("search.timeout_seconds", event.currentTarget.value, 1, 120, true, (value) => { if (value !== null) updateSearchField("timeout_seconds", value); })} disabled={providerSaving} />{numericError("search.timeout_seconds")}</div></div>
            </div>;
          })()}
          {(() => {
            const limits = draft.tool_limits ?? {};
            const numberValue = (field: string, fallback: number | string) => numericDrafts[`tool_limits.${field}`] ?? (
              limits[field] === undefined || limits[field] === null
                ? String(fallback)
                : String(limits[field])
            );
            const numericError = (identity: string) => numericErrors[identity] && <small className="settings-row__hint settings-row__hint--error" role="alert">{t("settingsInvalidNumber")}</small>;
            return <div className="settings-search" aria-label={t("toolLimits")}>
              <p className="settings-row__group-label">{t("toolLimits")}</p>
              <div className="settings-row"><label className="settings-row__label" htmlFor="settings-tool-timeout">{t("toolTimeout")}</label><div><input id="settings-tool-timeout" type="number" min={0.1} max={600} step={0.1} placeholder="—" aria-invalid={numericErrors["tool_limits.timeout_seconds"] || undefined} value={numberValue("timeout_seconds", "")} onChange={(event) => updateNumericSetting("tool_limits.timeout_seconds", event.currentTarget.value, 0.1, 600, false, (value) => updateToolLimit("timeout_seconds", value), true)} disabled={providerSaving} />{numericError("tool_limits.timeout_seconds")}</div></div>
              <div className="settings-row"><label className="settings-row__label" htmlFor="settings-tool-output">{t("toolOutputBytes")}</label><div><input id="settings-tool-output" type="number" min={1024} max={16777216} step={1024} aria-invalid={numericErrors["tool_limits.output_bytes"] || undefined} value={numberValue("output_bytes", 2097152)} onChange={(event) => updateNumericSetting("tool_limits.output_bytes", event.currentTarget.value, 1024, 16777216, true, (value) => { if (value !== null) updateToolLimit("output_bytes", value); })} disabled={providerSaving} />{numericError("tool_limits.output_bytes")}</div></div>
              <div className="settings-row"><label className="settings-row__label" htmlFor="settings-tool-attachment">{t("toolAttachmentBytes")}</label><div><input id="settings-tool-attachment" type="number" min={1} max={67108864} step={1024} aria-invalid={numericErrors["tool_limits.attachment_bytes"] || undefined} value={numberValue("attachment_bytes", 16777216)} onChange={(event) => updateNumericSetting("tool_limits.attachment_bytes", event.currentTarget.value, 1, 67108864, true, (value) => { if (value !== null) updateToolLimit("attachment_bytes", value); })} disabled={providerSaving} />{numericError("tool_limits.attachment_bytes")}</div></div>
            </div>;
          })()}
        </section>
        <section className={`settings-section${activeCategory === "general" ? "" : " settings-section--inactive"}`} id="settings-general" aria-labelledby="settings-general-title" aria-hidden={activeCategory !== "general" || undefined}>
          <div className="settings-section__heading"><div><p className="eyebrow">02</p><h2 id="settings-general-title">{t("general")}</h2></div></div>
          <div className="settings-section__heading"><div><p className="eyebrow">{t("about")}</p><h3>{t("about")}</h3></div></div>
          <div className="settings-row"><span className="settings-row__label">{t("product")}</span><span className="settings-row__value">UthCode Desktop</span></div>
        </section>
        <section className={`settings-section settings-archive${activeCategory === "archive" ? "" : " settings-section--inactive"}`} id="settings-archive" aria-labelledby="settings-archive-title" aria-hidden={activeCategory !== "archive" || undefined}>
          <div className="settings-section__heading"><div><p className="eyebrow">06</p><h2 id="settings-archive-title">{t("archive")}</h2></div></div>
          <div className="settings-archive__filters">
            <label><span>{t("archiveProjectFilter")}</span><CustomSelect id="settings-archive-project-filter" label={t("archiveProjectFilter")} value={archiveProjectFilter} options={archiveProjectOptions} onChange={setArchiveProjectFilter} /></label>
            <label><span>{t("archiveTextFilter")}</span><input id="settings-archive-text-filter" type="search" value={archiveTextFilter} onChange={(event) => setArchiveTextFilter(event.currentTarget.value)} /></label>
          </div>
          {archiveLoading && <p className="settings-empty" role="status">{t("archiveLoading")}</p>}
          {archiveError && <p className="settings-view__error" role="alert">{t("archiveLoadFailed")}</p>}
          {archiveRestoreError && <p className="settings-view__error" role="alert">{t("sessionArchiveFailed")}</p>}
          {!archiveLoading && !archiveError && archiveGroups.length === 0 && <p className="settings-empty" role="status">{archiveItems.length ? t("archiveNoMatch") : t("archiveEmpty")}</p>}
          {archiveGroups.map(([projectKey, group]) => <section className="settings-archive__group" key={projectKey} aria-label={group.label}>
            <h3>{group.label}</h3>
            <div className="settings-archive__list">{group.items.map((item) => <article className="settings-archive__item" key={`${item.projectKey}:${item.session.session_id}`}>
              <div><strong>{item.session.title?.trim() || item.session.preview?.trim() || item.session.session_id}</strong><small>{item.session.last_used_at || item.session.created_at || item.session.session_id}</small></div>
              {item.session.preview && item.session.title && <p>{item.session.preview}</p>}
              <button type="button" title={t("restoreArchived")} onClick={() => void restoreArchiveItem(item)} disabled={providerSaving || restoringArchiveId !== null}>
                {restoringArchiveId === item.session.session_id ? t("archiveRestoring") : t("restoreArchived")}
              </button>
            </article>)}</div>
          </section>)}
        </section>
        <section className={`settings-section${activeCategory === "appearance" ? "" : " settings-section--inactive"}`} id="settings-appearance" aria-labelledby="settings-appearance-title" aria-hidden={activeCategory !== "appearance" || undefined}>
          <div className="settings-section__heading"><div><p className="eyebrow">05</p><h2 id="settings-appearance-title">{t("appearance")}</h2></div></div>
          <div className="settings-row"><span className="settings-row__label">{t("theme")}</span><CustomSelect id="settings-theme" label={t("theme")} value={state.theme} options={[{ value: "system", label: t("system") }, { value: "dark", label: t("dark") }, { value: "light", label: t("light") }]} onChange={(value) => { if (!settingsInteractionLocked()) onThemeChange(value as ThemePreference); }} disabled={providerSaving} /></div>
          <div className="settings-row"><span className="settings-row__label">{t("language")}</span><CustomSelect id="settings-language" label={t("language")} value={state.language} options={[{ value: "zh-CN", label: t("chinese") }, { value: "en", label: t("english") }]} onChange={(value) => { if (!settingsInteractionLocked()) onLanguageChange(value as LanguagePreference); }} disabled={providerSaving} /></div>
        </section>
        <section className={`settings-section${activeCategory === "security" ? "" : " settings-section--inactive"}`} id="settings-security" aria-labelledby="settings-security-title" aria-hidden={activeCategory !== "security" || undefined}>
          <div className="settings-section__heading"><div><p className="eyebrow">04</p><h2 id="settings-security-title">{t("security")}</h2></div></div>
          <div className="settings-row" id="settings-permission"><span className="settings-row__label">{t("permission")}</span><CustomSelect id="settings-permission-select" label={t("permission")} value={draft.default_permission_mode ?? "default"} options={[{ value: "default", label: t("default") }, { value: "auto", label: t("auto") }]} onChange={(value) => updateField("default_permission_mode", value)} disabled={providerSaving} /></div>
          <div className="settings-row"><span className="settings-row__label">{t("effectivePermission")}</span><span className="settings-row__value">{settingText(effective?.default_permission_mode ?? draft.default_permission_mode ?? "default")}</span></div>
        </section>
      </div>

      {editingProvider && editing && <SettingsEditorModal
        providerId={editingProvider}
        draft={draft}
        settingsBusy={providerSaving}
        fieldPrefix={fieldPrefix}
        initialModelRef={editingInitialModel}
        initialFocusId={editingInitialFocusId}
        returnFocus={returnFocus.current}
        backgroundElements={[settingsNav.current, settingsContent.current]}
        onDraftChange={updateDraft}
        onCancel={cancelEditor}
        onApplyProvider={applyProvider}
        applyError={groupError}
        onRemoveProvider={removeProvider}
        onRevealApiKey={onRevealApiKey}
        replacementKey={replacementKeys.current[editingProvider] ?? ""}
        replacementTouched={touchedKeys.current[editingProvider] === true}
        onReplacementChange={(providerId, value) => { replacementKeys.current[providerId] = value; touchedKeys.current[providerId] = true; }}
      />}
    </section>
  );
}
