import { useEffect, useId, useRef, useState, type MouseEvent } from "react";
import type { ConfigurationWrite } from "./settings-draft";
import {
  createInternalModelRef,
  modalFocusableElements,
  modelFieldId,
  modelLabel,
  modelRemoteLabel,
  normalizeOptionalText,
  parseOptionalPositiveInteger,
  providerLabel,
  providerModels,
  stringValue,
  updateRecord,
} from "./settings-draft";
import { CustomSelect } from "./CustomSelect";
import { useTranslation } from "./i18n";
import { UiIcon } from "./UiIcon";

export const reasoningEffortOptions = ["", "none", "minimal", "low", "medium", "high", "xhigh", "max"] as const;

export interface SettingsEditorModalProps {
  providerId: string;
  draft: ConfigurationWrite;
  settingsBusy: boolean;
  fieldPrefix?: string;
  /** The control that opened this transaction; it owns return focus. */
  returnFocus: HTMLElement | null;
  /** The page remains the only non-secret draft owner. */
  backgroundElements?: Array<HTMLElement | null>;
  onDraftChange: (update: (current: ConfigurationWrite) => ConfigurationWrite) => void;
  onCancel: () => void;
  onApplyProvider: (providerId: string) => void;
  onRemoveProvider: (providerId: string) => void;
  onRevealApiKey?: (providerId: string) => Promise<string | null>;
  replacementKey?: string;
  replacementTouched?: boolean;
  onReplacementChange: (providerId: string, value: string) => void;
}

type EditorStep = "provider" | "model";

/**
 * One Settings editor transaction. Provider and Model are two views of the
 * same dialog element; changing the step never creates a second modal or a
 * second focus/inert lifecycle.
 */
export function SettingsEditorModal({
  providerId,
  draft,
  settingsBusy,
  fieldPrefix: providedFieldPrefix,
  returnFocus,
  backgroundElements = [],
  onDraftChange,
  onCancel,
  onApplyProvider,
  onRemoveProvider,
  onRevealApiKey,
  replacementKey = "",
  replacementTouched = false,
  onReplacementChange,
}: SettingsEditorModalProps) {
  const { t } = useTranslation();
  const generatedPrefix = useId().replace(/:/gu, "");
  const fieldPrefix = providedFieldPrefix ?? generatedPrefix;
  const [step, setStep] = useState<EditorStep>("provider");
  const [editingModelRef, setEditingModelRef] = useState<string | null>(null);
  const [providerDeletePending, setProviderDeletePending] = useState(false);
  const [replacementValue, setReplacementValue] = useState(replacementKey);
  const [replacementTouchedLocal, setReplacementTouchedLocal] = useState(replacementTouched);
  const [revealedKey, setRevealedKey] = useState<string | null>(null);
  const [visibleKey, setVisibleKey] = useState(false);
  const [revealPending, setRevealPending] = useState(false);
  const [revealError, setRevealError] = useState(false);
  const rootRef = useRef<HTMLElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const modelReturnFocus = useRef<string | null>(null);
  const revealGeneration = useRef(0);
  const mounted = useRef(true);

  const provider = draft.providers?.[providerId];
  const models = providerModels(draft, providerId);
  const editedModel = editingModelRef ? draft.models?.[editingModelRef] : undefined;
  const titleId = `${fieldPrefix}-settings-editor-title`;
  const modelTitleId = `${fieldPrefix}-settings-editor-model-title`;

  useEffect(() => {
    const backgrounds = backgroundElements.filter((element): element is HTMLElement => element !== null);
    const previous = backgrounds.map((element) => ({ element, inert: element.inert, ariaHidden: element.getAttribute("aria-hidden") }));
    for (const element of backgrounds) {
      element.inert = true;
      element.setAttribute("aria-hidden", "true");
    }
    return () => {
      for (const value of previous) {
        value.element.inert = value.inert;
        if (value.ariaHidden === null) value.element.removeAttribute("aria-hidden");
        else value.element.setAttribute("aria-hidden", value.ariaHidden);
      }
    };
  }, [backgroundElements]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      revealGeneration.current += 1;
      // React state is editor-local and is discarded with the modal. The
      // parent receives only explicit replacement text through its ref.
      queueMicrotask(() => returnFocus?.focus());
    };
  }, [returnFocus]);

  useEffect(() => {
    // A reopened provider starts a fresh reveal lifecycle. A replacement is
    // intentionally restored only when its previous Save failed.
    setReplacementValue(replacementKey);
    setReplacementTouchedLocal(replacementTouched);
    setRevealedKey(null);
    setVisibleKey(false);
    setRevealPending(false);
    setRevealError(false);
    revealGeneration.current += 1;
  }, [providerId, replacementKey, replacementTouched]);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    queueMicrotask(() => {
      const focusable = modalFocusableElements(root);
      (focusable.find((element) => element !== closeButtonRef.current) ?? closeButtonRef.current)?.focus();
    });
  }, [step, editingModelRef]);

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || !rootRef.current) return;
      if (event.key === "Escape") {
        event.preventDefault();
        onCancel();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = modalFocusableElements(rootRef.current);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleKey);
    return () => document.removeEventListener("keydown", handleKey);
  }, [onCancel]);

  if (!provider) return null;

  const updateProvider = (field: string, value: unknown) => {
    if (settingsBusy) return;
    onDraftChange((current) => ({
      ...current,
      providers: updateRecord(current.providers, providerId, field, value),
    }));
  };

  const updateModel = (modelRef: string, field: string, value: unknown) => {
    if (settingsBusy) return;
    onDraftChange((current) => ({
      ...current,
      models: updateRecord(current.models, modelRef, field, value),
    }));
  };

  const addModel = () => {
    if (settingsBusy) return;
    const ref = createInternalModelRef(draft.models ?? {});
    onDraftChange((current) => ({
      ...current,
      default_model: current.default_model || ref,
      models: {
        ...(current.models ?? {}),
        [ref]: {
          provider_profile_id: providerId,
          remote_id: "",
          display_name: null,
          context_window: null,
          max_output_tokens: null,
          reasoning_effort: null,
        },
      },
    }));
    modelReturnFocus.current = ref;
    setEditingModelRef(ref);
    setStep("model");
  };

  const editModel = (modelRef: string) => {
    if (settingsBusy) return;
    modelReturnFocus.current = modelRef;
    setEditingModelRef(modelRef);
    setStep("model");
  };

  const removeModel = (modelRef: string) => {
    if (settingsBusy) return;
    onDraftChange((current) => {
      const models = Object.fromEntries(Object.entries(current.models ?? {}).filter(([key]) => key !== modelRef));
      if (current.default_model !== modelRef) return { ...current, models };
      const replacement = Object.entries(models).find(([, model]) => model.provider_profile_id === providerId)?.[0];
      return { ...current, models, default_model: replacement ?? Object.keys(models)[0] ?? "" };
    });
    if (editingModelRef === modelRef) {
      setEditingModelRef(null);
      setStep("provider");
    }
  };

  const applyModel = () => {
    if (settingsBusy) return;
    if (editingModelRef) {
      onDraftChange((current) => {
        const profile = current.models?.[editingModelRef];
        if (!profile || !Object.prototype.hasOwnProperty.call(profile, "display_name")) return current;
        return { ...current, models: { ...current.models, [editingModelRef]: { ...profile, display_name: normalizeOptionalText(profile.display_name) } } };
      });
    }
    setEditingModelRef(null);
    setStep("provider");
    const modelRef = modelReturnFocus.current ?? editingModelRef;
    setTimeout(() => {
      if (!modelRef) return;
      Array.from(document.querySelectorAll<HTMLButtonElement>('[data-model-edit-ref]'))
        .find((element) => element.getAttribute("data-model-edit-ref") === modelRef)
        ?.focus();
    }, 0);
  };

  const goBackToProvider = () => {
    if (settingsBusy) return;
    setEditingModelRef(null);
    setStep("provider");
    const modelRef = modelReturnFocus.current ?? editingModelRef;
    setTimeout(() => {
      if (!modelRef) return;
      Array.from(document.querySelectorAll<HTMLButtonElement>('[data-model-edit-ref]'))
        .find((element) => element.getAttribute("data-model-edit-ref") === modelRef)
        ?.focus();
    }, 0);
  };

  const revealApiKey = async () => {
    if (settingsBusy || revealPending) return;
    if (visibleKey) {
      setVisibleKey(false);
      return;
    }
    if (revealedKey !== null) {
      setVisibleKey(true);
      return;
    }
    const generation = revealGeneration.current;
    setRevealPending(true);
    setRevealError(false);
    try {
      if (!onRevealApiKey) throw new Error("Desktop API unavailable");
      const value = await onRevealApiKey(providerId);
      if (!mounted.current || generation !== revealGeneration.current) return;
      if (value !== null && typeof value !== "string") throw new Error("Invalid reveal response");
      setRevealedKey(value ?? "");
      setVisibleKey(true);
    } catch {
      // Provider implementation details never enter the Settings UI.
      if (mounted.current && generation === revealGeneration.current) setRevealError(true);
    } finally {
      if (mounted.current && generation === revealGeneration.current) setRevealPending(false);
    }
  };

  const changeReplacement = (value: string) => {
    if (settingsBusy) return;
    setReplacementValue(value);
    setReplacementTouchedLocal(true);
    setVisibleKey(true);
    setRevealError(false);
    onReplacementChange(providerId, value);
  };

  const closeByBackdrop = (event: MouseEvent<HTMLDivElement>) => {
    if (event.target === event.currentTarget) onCancel();
  };

  return (
    <div className="provider-modal-backdrop" role="presentation" onMouseDown={closeByBackdrop}>
      <section
        ref={rootRef}
        className="provider-modal settings-editor-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={step === "model" ? modelTitleId : titleId}
        data-settings-editor-step={step}
      >
        {step === "provider" ? (
          <>
            <header>
              <div><p className="eyebrow">{t("protocol")}</p><h2 id={titleId}>{providerLabel(providerId, provider)}</h2></div>
              <button ref={closeButtonRef} type="button" title={t("cancel")} aria-label={t("cancel")} onClick={onCancel} disabled={settingsBusy}>×</button>
            </header>
            <div className="provider-modal__body">
              <div className="settings-row"><label htmlFor="modal-provider-display-name">{t("providerDisplayName")}</label><input id="modal-provider-display-name" value={stringValue(provider.display_name)} placeholder={t("providerDisplayNameFallback")} onChange={(event) => updateProvider("display_name", event.target.value || null)} disabled={settingsBusy} /></div>
              <div className="settings-row"><label htmlFor="modal-protocol">{t("protocol")}</label><CustomSelect id="modal-protocol" label={t("protocol")} value={stringValue(provider.kind, "openai_compat")} options={[{ value: "openai_compat", label: "OpenAI-compatible" }, { value: "openai_responses", label: "OpenAI" }, { value: "anthropic", label: "Anthropic" }, { value: "fake", label: t("localTestProvider") }]} onChange={(value) => updateProvider("kind", value)} disabled={settingsBusy} /></div>
              <div className="settings-row"><label htmlFor="modal-base-url">{t("baseUrl")}</label><input id="modal-base-url" value={stringValue(provider.base_url)} onChange={(event) => updateProvider("base_url", event.target.value || null)} disabled={settingsBusy} /></div>
              <div className="settings-row settings-row--secret"><label htmlFor="modal-api-key">{t("apiKey")}</label><div>
              <div className="api-key-control"><input id="modal-api-key" type={visibleKey ? "text" : "password"} autoComplete="new-password" placeholder={provider.api_key_configured === true ? t("replaceKey") : t("enterKey")} value={replacementTouchedLocal ? replacementValue : visibleKey ? revealedKey ?? "" : ""} onChange={(event) => changeReplacement(event.target.value)} aria-describedby="modal-api-key-help" disabled={settingsBusy} />
                  <button type="button" className="api-key-toggle" title={visibleKey ? t("hideApiKey") : t("showApiKey")} aria-label={visibleKey ? t("hideApiKey") : t("showApiKey")} aria-pressed={visibleKey} disabled={settingsBusy || provider.api_key_configured !== true || revealPending} onClick={() => void revealApiKey()}><UiIcon name={visibleKey ? "eye-off" : "eye"} /></button>
                </div>
                <p id="modal-api-key-help" className="sr-only">{provider.api_key_configured === true ? t("apiKeySaved") : t("apiKeyUnavailable")}</p>
                {revealPending && <p className="settings-row__hint" role="status">{t("revealingApiKey")}</p>}
                {revealError && <p className="settings-row__hint settings-row__hint--error" role="alert">{t("revealKeyFailed")}</p>}
              </div></div>
              <section className="settings-models" aria-labelledby={`${titleId}-models`}><div className="settings-subsection__heading"><div><p className="eyebrow">{t("models")}</p><h3 id={`${titleId}-models`}>{t("models")}</h3></div><button type="button" className="icon-button" title={t("addModel")} aria-label={t("addModel")} onClick={addModel} disabled={settingsBusy}><UiIcon name="plus" /></button></div>
                {models.length > 0 ? <div className="settings-model-list">{models.map(([ref, model]) => { const label = modelLabel(model, t("unnamedModel")); return <article className="settings-model-row" key={ref}><div><strong>{label}</strong><small>{modelRemoteLabel(model, t("modelNotConfigured"))}{draft.default_model === ref ? ` · ${t("defaultMarker")}` : ""}</small></div><div className="settings-model-row__actions"><button type="button" data-model-edit-ref={ref} title={`${t("editModel")} ${label}`} aria-label={`${t("editModel")} ${label}`} onClick={() => editModel(ref)} disabled={settingsBusy}><UiIcon name="edit" /></button><button type="button" title={`${t("removeModel")} ${label}`} aria-label={`${t("removeModel")} ${label}`} onClick={() => removeModel(ref)} disabled={settingsBusy}><UiIcon name="trash" /></button></div></article>; })}</div> : <p className="settings-empty settings-empty--compact">{t("noModels")}</p>}
              </section>
              {providerDeletePending && <div className="settings-confirm" role="alert"><p>{t("removeProviderQuestion")}</p><div><button type="button" onClick={() => { onRemoveProvider(providerId); onApplyProvider(providerId); }} disabled={settingsBusy}>{t("remove")}</button><button type="button" onClick={() => setProviderDeletePending(false)} disabled={settingsBusy}>{t("cancel")}</button></div></div>}
            </div>
            <footer>{!providerDeletePending && <button type="button" className="danger" title={t("removeProvider")} onClick={() => setProviderDeletePending(true)} disabled={settingsBusy}>{t("removeProvider")}</button>}<button type="button" title={t("cancel")} onClick={onCancel} disabled={settingsBusy}>{t("cancel")}</button><button type="button" title={t("apply")} onClick={() => { if (settingsBusy) return; onDraftChange((current) => { const profile = current.providers?.[providerId]; if (!profile) return current; return { ...current, providers: { ...current.providers, [providerId]: { ...profile, base_url: normalizeOptionalText(profile.base_url), display_name: normalizeOptionalText(profile.display_name) } } }; }); onApplyProvider(providerId); }} disabled={settingsBusy}>{t("apply")}</button></footer>
          </>
        ) : (
          <>
            <header>
              <div><p className="eyebrow">{t("model")}</p><h2 id={modelTitleId}>{modelLabel(editedModel, t("unnamedModel"))}</h2></div>
              <button ref={closeButtonRef} type="button" title={t("cancel")} aria-label={t("cancel")} onClick={onCancel} disabled={settingsBusy}>×</button>
            </header>
            <div className="provider-modal__body">
              {editedModel && editingModelRef && <>
                <div className="settings-row"><label htmlFor={modelFieldId(fieldPrefix, editingModelRef, "remote")}>{t("remoteModelId")}</label><input id={modelFieldId(fieldPrefix, editingModelRef, "remote")} value={stringValue(editedModel.remote_id)} onChange={(event) => updateModel(editingModelRef, "remote_id", event.target.value)} disabled={settingsBusy} /></div>
                <div className="settings-row"><label htmlFor={modelFieldId(fieldPrefix, editingModelRef, "display")}>{t("displayName")}</label><input id={modelFieldId(fieldPrefix, editingModelRef, "display")} value={stringValue(editedModel.display_name)} placeholder={t("displayNameFallback")} onChange={(event) => updateModel(editingModelRef, "display_name", event.target.value || null)} disabled={settingsBusy} /></div>
                <div className="settings-row"><label htmlFor={modelFieldId(fieldPrefix, editingModelRef, "context")}>{t("contextWindow")}</label><input id={modelFieldId(fieldPrefix, editingModelRef, "context")} type="number" min="1" value={editedModel.context_window == null ? "" : String(editedModel.context_window)} onChange={(event) => updateModel(editingModelRef, "context_window", parseOptionalPositiveInteger(event.target.value))} disabled={settingsBusy} /></div>
                <div className="settings-row"><label htmlFor={modelFieldId(fieldPrefix, editingModelRef, "output")}>{t("maxOutput")}</label><input id={modelFieldId(fieldPrefix, editingModelRef, "output")} type="number" min="1" value={editedModel.max_output_tokens == null ? "" : String(editedModel.max_output_tokens)} onChange={(event) => updateModel(editingModelRef, "max_output_tokens", parseOptionalPositiveInteger(event.target.value))} disabled={settingsBusy} /></div>
                <div className="settings-row"><span className="settings-row__label">{t("reasoning")}</span><CustomSelect id={modelFieldId(fieldPrefix, editingModelRef, "reasoning")} label={t("reasoning")} value={stringValue(editedModel.reasoning_effort)} options={reasoningEffortOptions.map((value) => ({ value, label: value || "—" }))} onChange={(value) => updateModel(editingModelRef, "reasoning_effort", value || null)} disabled={settingsBusy} /></div>
                <label className="settings-default-toggle"><input type="checkbox" checked={draft.default_model === editingModelRef} onChange={(event) => { if (!settingsBusy && event.target.checked) onDraftChange((current) => ({ ...current, default_model: editingModelRef })); }} disabled={settingsBusy} />{t("makeDefault")}</label>
              </>}
            </div>
            <footer><button type="button" title={t("cancel")} onClick={onCancel} disabled={settingsBusy}>{t("cancel")}</button><button type="button" title={t("back")} onClick={goBackToProvider} disabled={settingsBusy}>{t("back")}</button><button type="button" title={t("apply")} onClick={applyModel} disabled={settingsBusy}>{t("apply")}</button></footer>
          </>
        )}
      </section>
    </div>
  );
}
