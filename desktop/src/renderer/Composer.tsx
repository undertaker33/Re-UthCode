import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ClipboardEvent as ReactClipboardEvent, type DragEvent as ReactDragEvent, type KeyboardEvent } from "react";
import type { DesktopAttachmentDraft } from "../desktop-api";
import type { ConfigurationView, ContextUsageProjection, PermissionModeProjection, RendererState } from "./state";
import { CustomSelect } from "./CustomSelect";
import { useTranslation, type TranslationKey } from "./i18n";
import { stateLabel } from "./RuntimePanel";
import { UiIcon } from "./UiIcon";

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

// Completion descriptions are presentation-only. The Application-provided
// candidate value remains the command label and execution input; this map
// only replaces registry prose with the active locale for known commands.
const localizedCommandDescriptionKeys: Partial<Record<string, TranslationKey>> = {
  "/model": "commandDescriptionModel",
  "/status": "commandDescriptionStatus",
  "/compact": "commandDescriptionCompact",
  "/plan": "commandDescriptionPlan",
  "/new": "commandDescriptionNew",
  "/do": "commandDescriptionDo",
};

function localizedCommandDescription(value: string, translate: (key: TranslationKey) => string): string | undefined {
  const command = value.trim().split(/\s+/u)[0]?.toLowerCase() ?? "";
  const key = localizedCommandDescriptionKeys[command];
  return key ? translate(key) : undefined;
}

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

function normalizedContextUsage(value: ContextUsageProjection | undefined): { used: number; budget: number; available: boolean; measurement: ContextUsageProjection["measurement"]; source: string } {
  const budget = typeof value?.budget_tokens === "number" && Number.isSafeInteger(value.budget_tokens) && value.budget_tokens > 0 ? value.budget_tokens : null;
  const used = typeof value?.used_tokens === "number" && Number.isSafeInteger(value.used_tokens) && value.used_tokens >= 0 ? value.used_tokens : null;
  const measurement = value?.measurement === "estimate" || value?.measurement === "exact" || value?.measurement === "unavailable" ? value.measurement : null;
  const source = typeof value?.source === "string" && value.source.trim().length > 0 ? value.source : null;
  const available = typeof value?.available === "boolean" ? value.available : null;
  if (budget === null || used === null || measurement === null || source === null || available === null || (measurement === "unavailable" && available) || (measurement !== "unavailable" && !available)) {
    return { used: 0, budget: 0, available: false, measurement: "unavailable", source: "unavailable" };
  }
  return { used: available ? used : 0, budget, available, measurement, source };
}

export function contextUsagePercent(value: ContextUsageProjection | undefined): number {
  const usage = normalizedContextUsage(value);
  if (!usage.available || usage.budget <= 0) return 0;
  return Math.min(100, Math.round((usage.used / usage.budget) * 100));
}

export interface ContextRingProps {
  usage?: ContextUsageProjection;
  language: "zh-CN" | "en";
  translate: (key: "contextUsage" | "contextTokens" | "contextNotStarted" | "unavailable") => string;
}

/** Compact status indicator for the authoritative Application context usage. */
export function ContextRing({ usage, language, translate }: ContextRingProps) {
  const normalized = normalizedContextUsage(usage);
  const percentage = contextUsagePercent(usage);
  const visualRatio = normalized.available && normalized.budget > 0 ? Math.min(1, Math.max(0, normalized.used / normalized.budget)) : 0;
  const radius = 12;
  const circumference = 2 * Math.PI * radius;
  const budgetLabel = normalized.budget > 0 ? `${formatTokens(normalized.used, language)} / ${formatTokens(normalized.budget, language)} ${translate("contextTokens")}` : translate("unavailable");
  const detail = `${percentage}% · ${budgetLabel}${normalized.available ? "" : ` · ${translate("contextNotStarted")}`}`;
  const label = `${translate("contextUsage")}: ${detail}`;
  const tone = normalized.available && percentage >= 100 ? "is-critical" : normalized.available && percentage >= 80 ? "is-warning" : "";
  return (
    <div className={`context-ring ${tone}`} role="img" aria-label={label} title={label} data-used={normalized.used} data-budget={normalized.budget} data-available={normalized.available} data-measurement={normalized.measurement} data-source={normalized.source} data-percent={percentage}>
      <svg viewBox="0 0 32 32" aria-hidden="true" focusable="false">
        <circle className="context-ring__track" cx="16" cy="16" r={radius} />
        <circle className="context-ring__progress" cx="16" cy="16" r={radius} strokeDasharray={circumference} strokeDashoffset={circumference * (1 - visualRatio)} />
      </svg>
      <span aria-hidden="true">{percentage}%</span>
    </div>
  );
}

export interface ComposerProps {
  state: Pick<RendererState, "runtimeState" | "composerText" | "composerAttachments" | "activeTurn" | "terminalStatusPending" | "turnStatus" | "pendingInteraction" | "commandCandidates" | "argumentCandidates" | "commandUsage" | "commandArgumentPrompt" | "run" | "permissionMode" | "modelCandidates" | "modelPickerOpen" | "contextUsage" | "compactionStatus" | "currentModelRef" | "configuration" | "todo" | "todoIteration">;
  sessionPreparationStatus?: "preparing" | "ready" | "failed";
  onChange: (text: string) => void;
  onSubmit: (text: string, attachments: readonly DesktopAttachmentDraft[]) => void | Promise<void>;
  onCommand: (text: string) => void | Promise<void>;
  onPause: () => void | Promise<void>;
  onCancel: () => void | Promise<void>;
  onCompactCancel?: () => void | Promise<void>;
  onDismissCompletion?: () => void;
  onChooseAttachment: () => void | Promise<void>;
  onPasteAttachment: () => void | Promise<void>;
  onImportFile: (file: File) => void | Promise<void>;
  onRemoveAttachment: (ref: string) => void | Promise<void>;
}

function attachmentSizeLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function Composer({ state, sessionPreparationStatus, onChange, onSubmit, onCommand, onPause, onCancel, onCompactCancel, onDismissCompletion, onChooseAttachment, onPasteAttachment, onImportFile, onRemoveAttachment }: ComposerProps) {
  const { language, t } = useTranslation();
  const composerRef = useRef<HTMLElement>(null);
  const composing = useRef(false);
  const [completionOpen, setCompletionOpen] = useState(true);
  const [activeCompletion, setActiveCompletion] = useState(-1);
  const completionOptionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const hasText = state.composerText.trim().length > 0;
  const slashMode = state.composerText.trimStart().startsWith("/");
  const pending = state.pendingInteraction !== null;
  const terminalStatusPending = state.terminalStatusPending;
  const compactionRunning = state.compactionStatus.state === "running";
  const runtimeRestarting = state.runtimeState === "restarting";
  const inputLocked = pending || terminalStatusPending || compactionRunning || runtimeRestarting
    || (sessionPreparationStatus !== undefined && sessionPreparationStatus !== "ready");
  const wasBusy = useRef(state.activeTurn || inputLocked);
  useEffect(() => {
    const busy = state.activeTurn || inputLocked;
    if (wasBusy.current && !busy && document.hasFocus()) {
      const focused = document.activeElement;
      if (focused === document.body || focused === null || composerRef.current?.contains(focused)) {
        composerRef.current?.querySelector<HTMLTextAreaElement>("textarea")?.focus({ preventScroll: true });
      }
    }
    wasBusy.current = busy;
  }, [state.activeTurn, inputLocked]);
  const hiddenCommands = new Set(["/clear", "/quit", "/resume", "/permission", "/help"]);
  const candidates = useMemo<CompletionOption[]>(() => {
    if (pending || terminalStatusPending || runtimeRestarting || !slashMode) return [];
    if (state.argumentCandidates.length > 0) {
      const command = state.composerText.trimStart().split(/\s+/u)[0]?.toLowerCase() ?? "";
      return state.argumentCandidates.map((value) => ({
        value,
        // The wire value remains the canonical model ref used by onCommand;
        // only the visible completion label is user-facing.
        display: command === "/model" ? modelDisplayName(state.configuration, value) : value,
      }));
    }
    return state.commandCandidates
      .filter((candidate) => {
        const value = candidate.value.trim().split(/\s+/u)[0] ?? "";
        return !hiddenCommands.has(value.startsWith("/") ? value : `/${value}`);
      })
      .map((candidate) => ({
        value: candidate.value,
        description: localizedCommandDescription(candidate.value, t),
      }));
  }, [language, pending, runtimeRestarting, slashMode, state.argumentCandidates, state.commandCandidates, state.composerText, state.configuration, terminalStatusPending]);
  const candidateSignature = useMemo(() => candidates.map((candidate) => `${candidate.value}\u0000${candidate.display ?? ""}\u0000${candidate.description ?? ""}`).join("\u0001"), [candidates]);

  useEffect(() => {
    setActiveCompletion(edgeCompletionIndex(candidates, false));
    setCompletionOpen(candidates.length > 0);
  }, [candidateSignature]); // candidateSignature avoids resetting keyboard focus on unrelated rerenders.

  useEffect(() => {
    if (completionOpen && activeCompletion >= 0) completionOptionRefs.current[activeCompletion]?.scrollIntoView?.({ block: "nearest" });
  }, [activeCompletion, completionOpen]);

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
    return [
      { value: "", label: t("chooseModel"), disabled: true },
      ...[...refs].map((modelRef) => ({ value: modelRef, label: modelDisplayName(state.configuration, modelRef) })),
    ];
  }, [language, state.configuration, state.currentModelRef, state.modelCandidates]);

  const submit = () => {
    const hasAttachmentOnlyPayload = !state.activeTurn && state.composerAttachments.length > 0;
    if (inputLocked || (!hasText && !hasAttachmentOnlyPayload)) return;
    void onSubmit(state.composerText, state.composerAttachments);
  };

  const handleDrop = (event: ReactDragEvent<HTMLElement>) => {
    if (inputLocked || state.activeTurn || event.dataTransfer.files.length === 0) return;
    event.preventDefault();
    Array.from(event.dataTransfer.files).forEach((file) => { void onImportFile(file); });
  };

  const handlePaste = (event: ReactClipboardEvent<HTMLElement>) => {
    if (inputLocked || state.activeTurn || event.clipboardData.files.length === 0) return;
    event.preventDefault();
    Array.from(event.clipboardData.files).forEach((file) => { void onImportFile(file); });
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
    <section ref={composerRef} className="composer" aria-label={t("composer")} aria-disabled={inputLocked || undefined} onDragOver={(event) => { if (!inputLocked && !state.activeTurn && event.dataTransfer.types.includes("Files")) event.preventDefault(); }} onDrop={handleDrop} onPaste={handlePaste}>
      {state.todo.length > 0 && <section className="composer-todo todo-strip" tabIndex={0} aria-label={t("tasks")} data-iteration={state.todoIteration}>
        <header><h2><UiIcon name="todo" />{t("tasks")}</h2><span className="todo-strip__count">{state.todo.length}</span></header>
        <ul>{state.todo.map((item, index) => <li key={`${item.content}-${index}`} data-status={item.status}>
          <span className="todo-status-icon" title={stateLabel(item.status, t)}><UiIcon name={item.status === "completed" ? "check" : item.status === "in_progress" ? "status" : "todo"} /></span>
          <span>{item.content}</span>
        </li>)}</ul>
      </section>}
      {completionOpen && candidates.length > 0 && <div className="command-menu" role="listbox" aria-label={t("commandCompletion")}>
        {candidates.map((candidate, index) => <button ref={(element) => { completionOptionRefs.current[index] = element; }} type="button" key={`${candidate.value}-${index}`} role="option" aria-selected={index === activeCompletion} className={index === activeCompletion ? "is-active" : ""} onMouseEnter={() => setActiveCompletion(index)} onClick={() => chooseCompletion(index)}><span>{candidate.display ?? candidate.value}</span>{candidate.description && <small>{candidate.description}</small>}</button>)}
        {(state.commandUsage || state.commandArgumentPrompt) && <p>{state.commandUsage || state.commandArgumentPrompt}</p>}
      </div>}
      <div className="composer-input">
        <textarea value={state.composerText} onChange={(event) => onChange(event.target.value)} onKeyDown={handleKeyDown} onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }} placeholder={runtimeRestarting ? t("runtimeRestarting") : pending ? t("completeInteraction") : terminalStatusPending ? t("terminalStatusPending") : state.activeTurn ? t("steeringMessage") : t("message")} disabled={inputLocked} rows={3} aria-label={t("message")} aria-describedby={runtimeRestarting ? "composer-state" : undefined} />
        <div className="composer-actions">
          {compactionRunning && <button type="button" title={t("cancel")} aria-label={t("cancel")} onClick={() => void onCompactCancel?.()} disabled={!onCompactCancel || runtimeRestarting}><UiIcon name="stop" />{t("cancel")}</button>}
          {state.activeTurn && !pending && !terminalStatusPending && <button type="button" title={t("pause")} aria-label={t("pause")} onClick={() => void onPause()} disabled={inputLocked || state.turnStatus === "pausing"}><UiIcon name="pause" />{t("pause")}</button>}
          {state.activeTurn && !terminalStatusPending && <button type="button" title={t("cancel")} aria-label={t("cancel")} onClick={() => void onCancel()} disabled={inputLocked}><UiIcon name="stop" />{t("cancel")}</button>}
          {/* Keep the historical action hook for integrations that locate the submit
              control from the input action group. The visible control lives in the
              bottom toolbar; this zero-area proxy preserves that DOM contract while
              avoiding a second tab stop or accessible name. */}
          <button className="composer-submit-proxy" type="button" tabIndex={-1} aria-hidden="true" onClick={submit} disabled={inputLocked || (!hasText && (!state.activeTurn && state.composerAttachments.length === 0))} />
        </div>
      </div>
      {state.composerAttachments.length > 0 && <div className="composer-attachments" aria-label={t("attachments")}>
        {state.composerAttachments.map((attachment) => <article className="composer-attachment" key={attachment.ref}>
          {attachment.data_url && attachment.mime_type.startsWith("image/")
            ? <img src={attachment.data_url} alt={attachment.display_name} />
            : <span className="composer-attachment__fallback" aria-hidden="true">{attachment.mime_type.startsWith("image/") ? "IMG" : "FILE"}</span>}
          <span className="composer-attachment__meta"><strong>{attachment.display_name}</strong><small>{attachmentSizeLabel(attachment.size_bytes)}</small></span>
          <button type="button" title={t("attachmentRemove")} aria-label={`${t("attachmentRemove")}: ${attachment.display_name}`} onClick={() => void onRemoveAttachment(attachment.ref)} disabled={inputLocked || state.activeTurn}><UiIcon name="trash" /></button>
        </article>)}
      </div>}
      <div className="composer-toolbar">
        <div className="composer-selectors">
          <div className="composer-attachment-actions">
            <button type="button" title={t("attachmentChoose")} aria-label={t("attachmentChoose")} onClick={() => void onChooseAttachment()} disabled={inputLocked || state.activeTurn}><UiIcon name="plus" />{t("attachmentChoose")}</button>
            <button type="button" title={t("attachmentPaste")} aria-label={t("attachmentPaste")} onClick={() => void onPasteAttachment()} disabled={inputLocked || state.activeTurn}><UiIcon name="copy" />{t("attachmentPaste")}</button>
          </div>
          <CustomSelect label={t("permission")} value={permissionSelectValue(state.permissionMode)} disabled={inputLocked || state.activeTurn} onChange={(value) => void onCommand(`/permission ${value}`)} options={[{ value: "", label: t("unavailable"), disabled: true }, { value: "default", label: t("default") }, { value: "auto", label: t("auto") }, { value: "full_access", label: t("fullAccess") }]} />
        </div>
        <div className="composer-model">
          <CustomSelect label={state.currentModelRef ? `${t("model")}: ${modelDisplayName(state.configuration, state.currentModelRef)}` : t("model")} value={state.currentModelRef ?? ""} onOpen={() => { if (!state.modelPickerOpen) void onCommand("/model"); }} onChange={(value) => void onCommand(`/model ${value}`)} disabled={inputLocked || state.activeTurn} options={modelOptions} />
          <ContextRing usage={state.contextUsage} language={language} translate={(key) => t(key)} />
        </div>
        <button className="composer-send" type="button" title={runtimeRestarting || pending || terminalStatusPending ? (runtimeRestarting ? t("runtimeRestarting") : t("waiting")) : state.activeTurn ? t("steer") : t("send")} aria-label={runtimeRestarting || pending || terminalStatusPending ? (runtimeRestarting ? t("runtimeRestarting") : t("waiting")) : state.activeTurn ? t("steer") : t("send")} onClick={submit} disabled={inputLocked || (!hasText && (!state.activeTurn && state.composerAttachments.length === 0))}><UiIcon name="send" />{runtimeRestarting ? t("runtimeRestarting") : pending || terminalStatusPending ? t("waiting") : state.activeTurn ? t("steer") : t("send")}</button>
      </div>
    </section>
  );
}
