import type { PanelModePreference } from "../desktop-api";
import type { RendererState } from "./state";

export interface RuntimePanelProps {
  state: Pick<RendererState, "runtimeState" | "runtimeError" | "run" | "activeTurn" | "turnStatus" | "completionBlocked" | "diagnostics" | "selectedProjectKey" | "selectedSessionId" | "panelMode">;
  onPanelModeChange: (mode: PanelModePreference) => void;
}
function usageLabel(usage: Record<string, unknown> | undefined): string {
  if (!usage) return "unavailable";
  const used = typeof usage.used_tokens === "number" ? usage.used_tokens : null;
  const budget = typeof usage.budget_tokens === "number" ? usage.budget_tokens : null;
  if (used === null || budget === null) return "unavailable";
  return `${used.toLocaleString()} / ${budget.toLocaleString()}`;
}

export function RuntimePanel({ state, onPanelModeChange }: RuntimePanelProps) {
  return (
    <aside className={`runtime-panel runtime-panel--${state.panelMode}`} aria-label="Runtime information">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Runtime</p>
          <h2>{state.runtimeState === "ready" ? "Ready" : state.runtimeState.replace(/_/gu, " ")}</h2>
        </div>
        <label className="panel-mode-control">
          <span className="sr-only">Runtime panel layout</span>
          <select value={state.panelMode} onChange={(event) => onPanelModeChange(event.target.value as PanelModePreference)} aria-label="Runtime panel layout">
            <option value="docked">Docked</option>
            <option value="floating">Floating</option>
            <option value="hidden">Hidden</option>
          </select>
        </label>
      </div>
      <dl className="runtime-facts">
        <div><dt>Turn</dt><dd>{state.activeTurn ? state.turnStatus : "idle"}</dd></div>
        <div><dt>Model run</dt><dd>{state.run?.run_id ? state.run.run_id.slice(0, 8) : "—"}</dd></div>
        <div><dt>Context</dt><dd>{usageLabel(state.run?.usage)}</dd></div>
        <div><dt>Mode</dt><dd>{state.run?.behavior_mode ?? "default"}</dd></div>
        <div><dt>Project</dt><dd title={state.selectedProjectKey ?? undefined}>{state.selectedProjectKey ? state.selectedProjectKey.split(/[\\/]/u).filter(Boolean).pop() : "—"}</dd></div>
        <div><dt>Session</dt><dd>{state.selectedSessionId ? state.selectedSessionId.slice(0, 8) : "—"}</dd></div>
      </dl>
      {state.completionBlocked && <p className="runtime-alert runtime-alert--warning">{state.completionBlocked}</p>}
      {state.runtimeError && <p className="runtime-alert runtime-alert--error" role="alert">{state.runtimeError}</p>}
      {state.diagnostics.length > 0 && <p className="runtime-note">Runtime diagnostics available ({state.diagnostics.length})</p>}
    </aside>
  );
}
