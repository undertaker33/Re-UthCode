import type { KeyboardEvent } from "react";
import type { PermissionModeProjection, RendererState } from "./state";
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

export interface ComposerProps {
  state: Pick<RendererState, "composerText" | "activeTurn" | "turnStatus" | "pendingInteraction" | "commandCandidates" | "argumentCandidates" | "commandUsage" | "commandArgumentPrompt" | "run" | "permissionMode" | "modelCandidates" | "modelPickerOpen">;
  onChange: (text: string) => void;
  onSubmit: (text: string) => void | Promise<void>;
  onCommand: (text: string) => void | Promise<void>;
  onPause: () => void | Promise<void>;
  onCancel: () => void | Promise<void>;
}

export function Composer({ state, onChange, onSubmit, onCommand, onPause, onCancel }: ComposerProps) {
  const { t } = useTranslation();
  const hasText = state.composerText.trim().length > 0;
  const slashMode = state.composerText.trimStart().startsWith("/");
  const pending = state.pendingInteraction !== null;
  const candidates: Array<{ value: string; display?: string; description?: string }> = !pending && slashMode ? (state.argumentCandidates.length > 0 ? state.argumentCandidates.map((value) => ({ value, display: value })) : state.commandCandidates) : [];

  const submit = () => {
    if (pending || !hasText) return;
    void onSubmit(state.composerText);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
    if (event.key === "Tab" && candidates[0]) {
      event.preventDefault();
      onChange(applyCompletion(state.composerText, candidates[0].value));
    }
  };

  return (
    <section className="composer" aria-label={t("composer")} aria-disabled={pending || undefined}>
      {candidates.length > 0 && <div className="command-menu" role="listbox" aria-label={t("commandCompletion")}>
        {candidates.map((candidate, index) => <button type="button" key={`${candidate.value}-${index}`} role="option" onClick={() => onChange(applyCompletion(state.composerText, candidate.value))}><span>{candidate.display || candidate.value}</span>{candidate.description && <small>{candidate.description}</small>}</button>)}
        {(state.commandUsage || state.commandArgumentPrompt) && <p>{state.commandUsage || state.commandArgumentPrompt}</p>}
      </div>}
      <div className="composer-toolbar">
        <div className="composer-selectors">
          <button type="button" title={state.run?.behavior_mode === "plan" ? t("plan") : t("default")} className={state.run?.behavior_mode === "plan" ? "is-plan" : ""} onClick={() => void onCommand(state.run?.behavior_mode === "plan" ? "/do" : "/plan")} disabled={pending || state.activeTurn}>{state.run?.behavior_mode === "plan" ? t("plan") : t("default")}</button>
          <CustomSelect label={t("permission")} value={permissionSelectValue(state.permissionMode)} disabled={pending || state.activeTurn} onChange={(value) => void onCommand(`/permission ${value}`)} options={[{ value: "", label: t("unavailable"), disabled: true }, { value: "default", label: t("default") }, { value: "auto", label: t("auto") }, { value: "full_access", label: t("fullAccess") }]} />
          {state.modelPickerOpen ? <CustomSelect label={t("model")} value="" onChange={(value) => void onCommand(`/model ${value}`)} disabled={pending || state.activeTurn} options={[{ value: "", label: t("chooseModel"), disabled: true }, ...state.modelCandidates.map((model) => ({ value: model, label: model }))]} /> : <button type="button" title={t("model")} onClick={() => void onCommand("/model")} disabled={pending || state.activeTurn}>{t("model")}</button>}
        </div>
        <output className="composer-state">{pending ? t("interactionRequired") : state.activeTurn ? stateLabel(state.turnStatus, t) : t("ready")}</output>
      </div>
      <div className="composer-input">
        <textarea value={state.composerText} onChange={(event) => onChange(event.target.value)} onKeyDown={handleKeyDown} placeholder={pending ? t("completeInteraction") : state.activeTurn ? t("steeringMessage") : t("message")} disabled={pending} rows={3} aria-label={t("message")} />
        <div className="composer-actions">
          {state.activeTurn && !pending && <button type="button" title={t("pause")} onClick={() => void onPause()} disabled={state.turnStatus === "pausing"}>{t("pause")}</button>}
          {state.activeTurn && <button type="button" title={t("cancel")} onClick={() => void onCancel()}>{t("cancel")}</button>}
          <button type="button" title={pending ? t("waiting") : state.activeTurn ? t("steer") : t("send")} onClick={submit} disabled={pending || !hasText}>{pending ? t("waiting") : state.activeTurn ? t("steer") : t("send")}</button>
        </div>
      </div>
      <p className="composer-hint">{t("composerHint")}</p>
    </section>
  );
}
