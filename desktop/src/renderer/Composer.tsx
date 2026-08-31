import { useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import type { ConfigurationView, ContextUsageProjection, PermissionModeProjection, RendererState } from "./state";
import { configuredContextWindow, DEFAULT_CONTEXT_WINDOW } from "./state";
import { CustomSelect } from "./CustomSelect";
import { useTranslation } from "./i18n";
import { stateLabel } from "./RuntimePanel";

/** Replace only the token currently being completed, preserving slash aliases. */
export function applyCompletion(prefix: string, completion: string): string {
  const tokenStart = prefix.search(/[^\s]*$/u);
  const start = tokenStart < 0 ? prefix.length : tokenStart;
  return `${prefix.slice(0, start)}${completion} `;
}

export function permissionSelectValue(mode: PermissionModeProjection): string {
  return mode === "unknown" ? "" : mode;
}

type CompletionOption = {
  value: string;
  display?: string;
  description?: string;
};

/** Move through completion options with the same cyclic model as CustomSelect. */
export function nextCompletionIndex(options: readonly CompletionOption[], current: number, step: 1 | -1): number {
  if (options.length === 0) return -1;
  if (current < 0 || current >= options.length) return step > 0 ? 0 : options.length - 1;
  return (current + step + options.length) % options.length;
}

export function edgeCompletionIndex(options: readonly CompletionOption[], last: boolean): number {
  return options.length === 0 ? -1 : last ? options.length - 1 : 0;
}

/** Resolve a display label without making the Renderer a model authority. */
export function modelDisplayName(configuration: ConfigurationView | null | undefined, modelRef: string | null | undefined): string {
  const reference = modelRef?.trim();
  if (!reference) return "";
  const profile = configuration?.models?.[reference];
  const displayName = typeof profile?.display_name === "string" ? profile.display_name.trim() : "";
  if (displayName) return displayName;
  const remoteId = typeof profile?.remote_id === "string" ? profile.remote_id.trim() : "";
  return remoteId || reference;
}

function formatTokens(value: number, language: "zh-CN" | "en"): string {
  return value.toLocaleString(language === "en" ? "en-US" : "zh-CN");
}

function normalizedContextUsage(value: ContextUsageProjection | undefined, fallbackBudget = DEFAULT_CONTEXT_WINDOW): { used: number; budget: number; available: boolean } {
  // The Application projection supplies used/available only. The configured
  // model window (or 256k fallback) remains authoritative for the total.
  const budget = typeof fallbackBudget === "number" && Number.isSafeInteger(fallbackBudget) && fallbackBudget > 0
    ? fallbackBudget
    : DEFAULT_CONTEXT_WINDOW;
  const used = typeof value?.used_tokens === "number" && Number.isSafeInteger(value.used_tokens) && value.used_tokens >= 0
    ? value.used_tokens
    : 0;
  const available = value?.available === true;
  return { used: available ? used : 0, budget, available };
}

export function contextUsagePercent(value: ContextUsageProjection | undefined, fallbackBudget = DEFAULT_CONTEXT_WINDOW): number {
  const usage = normalizedContextUsage(value, fallbackBudget);
  if (!usage.available) return 0;
  return Math.min(100, Math.round((usage.used / usage.budget) * 100));
}

export interface ContextRingProps {
  usage?: ContextUsageProjection;
  language: "zh-CN" | "en";
  translate: (key: "contextUsage" | "contextTokens" | "contextNotStarted") => string;
  fallbackBudget?: number;
}

/** Compact status indicator for the authoritative Application context usage. */
export function ContextRing({ usage, language, translate, fallbackBudget = DEFAULT_CONTEXT_WINDOW }: ContextRingProps) {
  const normalized = normalizedContextUsage(usage, fallbackBudget);
  const percentage = contextUsagePercent(usage, fallbackBudget);
  const visualRatio = normalized.available ? Math.min(1, Math.max(0, normalized.used / normalized.budget)) : 0;
  const radius = 12;
  const circumference = 2 * Math.PI * radius;
  const detail = `${percentage}% · ${formatTokens(normalized.used, language)} / ${formatTokens(normalized.budget, language)} ${translate("contextTokens")}${normalized.available ? "" : ` · ${translate("contextNotStarted")}`}`;
  const label = `${translate("contextUsage")}: ${detail}`;
  const tone = normalized.available && percentage >= 100 ? "is-critical" : normalized.available && percentage >= 80 ? "is-warning" : "";
  return (
    <div className={`context-ring ${tone}`} role="img" aria-label={label} title={label} data-used={normalized.used} data-budget={normalized.budget} data-available={normalized.available} data-percent={percentage}>
      <svg viewBox="0 0 32 32" aria-hidden="true" focusable="false">
        <circle className="context-ring__track" cx="16" cy="16" r={radius} />
        <circle className="context-ring__progress" cx="16" cy="16" r={radius} strokeDasharray={circumference} strokeDashoffset={circumference * (1 - visualRatio)} />
      </svg>
      <span aria-hidden="true">{percentage}%</span>
    </div>
  );
}

export interface ComposerProps {
  state: Pick<RendererState, "composerText" | "activeTurn" | "turnStatus" | "pendingInteraction" | "commandCandidates" | "argumentCandidates" | "commandUsage" | "commandArgumentPrompt" | "run" | "permissionMode" | "modelCandidates" | "modelPickerOpen" | "contextUsage" | "currentModelRef" | "configuration">;
  onChange: (text: string) => void;
  onSubmit: (text: string) => void | Promise<void>;
  onCommand: (text: string) => void | Promise<void>;
  onPause: () => void | Promise<void>;
  onCancel: () => void | Promise<void>;
  onDismissCompletion?: () => void;
}

export function Composer({ state, onChange, onSubmit, onCommand, onPause, onCancel, onDismissCompletion }: ComposerProps) {
  const { language, t } = useTranslation();
  const composerRef = useRef<HTMLElement>(null);
  const composing = useRef(false);
  const [completionOpen, setCompletionOpen] = useState(true);
  const [activeCompletion, setActiveCompletion] = useState(-1);
  const hasText = state.composerText.trim().length > 0;
  const slashMode = state.composerText.trimStart().startsWith("/");
  const pending = state.pendingInteraction !== null;
  const candidates = useMemo<CompletionOption[]>(() => {
    if (pending || !slashMode) return [];
    if (state.argumentCandidates.length > 0) return state.argumentCandidates.map((value) => ({ value, display: value }));
    return state.commandCandidates.map((candidate) => ({
      value: candidate.value,
      display: candidate.display,
      description: candidate.description,
    }));
  }, [pending, slashMode, state.argumentCandidates, state.commandCandidates]);
  const candidateSignature = useMemo(() => candidates.map((candidate) => `${candidate.value}\u0000${candidate.display ?? ""}\u0000${candidate.description ?? ""}`).join("\u0001"), [candidates]);

  useEffect(() => {
    setActiveCompletion(edgeCompletionIndex(candidates, false));
    setCompletionOpen(candidates.length > 0);
  }, [candidateSignature]); // candidateSignature avoids resetting keyboard focus on unrelated rerenders.

  useLayoutEffect(() => {
    const element = composerRef.current;
    const parent = element?.parentElement;
    if (!element || !parent) return undefined;
    const updateHeight = () => parent.style.setProperty("--composer-height", `${element.getBoundingClientRect().height}px`);
    updateHeight();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(updateHeight);
    observer?.observe(element);
    return () => {
      observer?.disconnect();
      parent.style.removeProperty("--composer-height");
    };
  }, []);

  const modelOptions = useMemo(() => {
    const refs = new Set<string>();
    if (state.currentModelRef) refs.add(state.currentModelRef);
    for (const model of state.modelCandidates) if (model.trim()) refs.add(model);
    for (const modelRef of Object.keys(state.configuration?.models ?? {})) refs.add(modelRef);
    return [
      { value: "", label: t("chooseModel"), disabled: true },
      ...[...refs].map((modelRef) => ({ value: modelRef, label: modelDisplayName(state.configuration, modelRef) })),
    ];
  }, [language, state.configuration, state.currentModelRef, state.modelCandidates]);

  const submit = () => {
    if (pending || !hasText) return;
    void onSubmit(state.composerText);
  };

  const chooseCompletion = (index: number) => {
    const candidate = candidates[index];
    if (!candidate) return;
    setCompletionOpen(false);
    onChange(applyCompletion(state.composerText, candidate.value));
  };

  const dismissCompletion = () => {
    setCompletionOpen(false);
    onDismissCompletion?.();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    const nativeEvent = event.nativeEvent as unknown as { isComposing?: boolean; keyCode?: number };
    if (composing.current || nativeEvent.isComposing || nativeEvent.keyCode === 229) return;
    const menuOpen = completionOpen && candidates.length > 0;
    if (menuOpen && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
      event.preventDefault();
      event.stopPropagation();
      setActiveCompletion((current) => nextCompletionIndex(candidates, current, event.key === "ArrowDown" ? 1 : -1));
      return;
    }
    if (menuOpen && (event.key === "Home" || event.key === "End")) {
      event.preventDefault();
      event.stopPropagation();
      setActiveCompletion(edgeCompletionIndex(candidates, event.key === "End"));
      return;
    }
    if (menuOpen && (event.key === "Enter" || event.key === "Tab") && !event.shiftKey) {
      const current = activeCompletion >= 0 ? candidates[activeCompletion] : undefined;
      if (current) {
        event.preventDefault();
        event.stopPropagation();
        chooseCompletion(activeCompletion);
        return;
      }
    }
    if (menuOpen && event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      dismissCompletion();
      return;
    }
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <section ref={composerRef} className="composer" aria-label={t("composer")} aria-disabled={pending || undefined}>
      {completionOpen && candidates.length > 0 && <div className="command-menu" role="listbox" aria-label={t("commandCompletion")}>
        {candidates.map((candidate, index) => <button type="button" key={`${candidate.value}-${index}`} role="option" aria-selected={index === activeCompletion} className={index === activeCompletion ? "is-active" : ""} onMouseEnter={() => setActiveCompletion(index)} onClick={() => chooseCompletion(index)}><span>{candidate.display || candidate.value}</span>{candidate.description && <small>{candidate.description}</small>}</button>)}
        {(state.commandUsage || state.commandArgumentPrompt) && <p>{state.commandUsage || state.commandArgumentPrompt}</p>}
      </div>}
      <div className="composer-input">
        <textarea value={state.composerText} onChange={(event) => onChange(event.target.value)} onKeyDown={handleKeyDown} onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }} placeholder={pending ? t("completeInteraction") : state.activeTurn ? t("steeringMessage") : t("message")} disabled={pending} rows={3} aria-label={t("message")} />
        <div className="composer-actions">
          {state.activeTurn && !pending && <button type="button" title={t("pause")} onClick={() => void onPause()} disabled={state.turnStatus === "pausing"}>{t("pause")}</button>}
          {state.activeTurn && <button type="button" title={t("cancel")} onClick={() => void onCancel()}>{t("cancel")}</button>}
          <button type="button" title={pending ? t("waiting") : state.activeTurn ? t("steer") : t("send")} onClick={submit} disabled={pending || !hasText}>{pending ? t("waiting") : state.activeTurn ? t("steer") : t("send")}</button>
        </div>
      </div>
      <div className="composer-toolbar">
        <div className="composer-selectors">
          <CustomSelect label={t("permission")} value={permissionSelectValue(state.permissionMode)} disabled={pending || state.activeTurn} onChange={(value) => void onCommand(`/permission ${value}`)} options={[{ value: "", label: t("unavailable"), disabled: true }, { value: "default", label: t("default") }, { value: "auto", label: t("auto") }, { value: "full_access", label: t("fullAccess") }]} />
        </div>
        <output className="composer-state">{pending ? t("interactionRequired") : state.activeTurn ? stateLabel(state.turnStatus, t) : t("ready")}</output>
        <div className="composer-model">
          <CustomSelect label={state.currentModelRef ? `${t("model")}: ${modelDisplayName(state.configuration, state.currentModelRef)}` : t("model")} value={state.currentModelRef ?? ""} onOpen={() => { if (!state.modelPickerOpen) void onCommand("/model"); }} onChange={(value) => void onCommand(`/model ${value}`)} disabled={pending || state.activeTurn} options={modelOptions} />
          <ContextRing usage={state.contextUsage} language={language} fallbackBudget={configuredContextWindow(state.configuration, state.currentModelRef)} translate={(key) => t(key)} />
        </div>
      </div>
      <p className="composer-hint">{t("composerHint")}</p>
    </section>
  );
}
