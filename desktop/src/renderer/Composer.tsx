import type { KeyboardEvent } from "react";
import type { PermissionModeProjection, RendererState } from "./state";

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
    <section className={`composer-area${pending ? " is-blocked" : ""}`} aria-label="Composer">
      {candidates.length > 0 && <div className="command-completion" role="listbox" aria-label="Command completion">
        {candidates.map((candidate, index) => <button type="button" key={`${candidate.value}-${index}`} role="option" onClick={() => onChange(applyCompletion(state.composerText, candidate.value))}><span>{candidate.display || candidate.value}</span>{candidate.description && <small>{candidate.description}</small>}</button>)}
        {(state.commandUsage || state.commandArgumentPrompt) && <p>{state.commandUsage || state.commandArgumentPrompt}</p>}
      </div>}
      <div className="composer-toolbar">
        <div className="composer-selectors">
          <button type="button" className={`mode-button mode-button--${state.run?.behavior_mode === "plan" ? "plan" : "default"}`} onClick={() => void onCommand(state.run?.behavior_mode === "plan" ? "/do" : "/plan")} disabled={pending || state.activeTurn}>{state.run?.behavior_mode === "plan" ? "PLAN" : "DEFAULT"}</button>
          <label className="permission-selector"><span>Permission</span><select value={permissionSelectValue(state.permissionMode)} disabled={pending || state.activeTurn} onChange={(event) => void onCommand(`/permission ${event.target.value}`)}><option value="" disabled>Unavailable</option><option value="default">default</option><option value="auto">auto</option><option value="full_access">full_access</option></select></label>
          {state.modelPickerOpen ? <label className="model-selector"><span className="sr-only">Model</span><select autoFocus value="" onChange={(event) => void onCommand(`/model ${event.target.value}`)} disabled={pending || state.activeTurn}><option value="">Choose model</option>{state.modelCandidates.map((model) => <option value={model} key={model}>{model}</option>)}</select></label> : <button type="button" className="model-button" onClick={() => void onCommand("/model")} disabled={pending || state.activeTurn}>Model</button>}
        </div>
        <div className="composer-status">{pending ? "Interaction required" : state.activeTurn ? state.turnStatus : "Ready"}</div>
      </div>
      <div className="composer-input-row">
        <textarea value={state.composerText} onChange={(event) => onChange(event.target.value)} onKeyDown={handleKeyDown} placeholder={pending ? "Complete the interaction above" : state.activeTurn ? "Send steering to the active Turn" : "Message UthCode"} disabled={pending} rows={3} aria-label="Message UthCode" />
        <div className="composer-actions">
          {state.activeTurn && !pending && <button type="button" className="pause-button" onClick={() => void onPause()} disabled={state.turnStatus === "pausing"}>Pause</button>}
          {state.activeTurn && <button type="button" className="cancel-button" onClick={() => void onCancel()}>Cancel</button>}
          <button type="button" className="send-button" onClick={submit} disabled={pending || !hasText}>{pending ? "Waiting" : state.activeTurn ? "Steer" : "Send"}</button>
        </div>
      </div>
      <p className="composer-hint">Enter to send · Shift+Enter for a new line</p>
    </section>
  );
}
