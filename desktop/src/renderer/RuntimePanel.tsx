import type { PanelModePreference } from "../desktop-api";
import type { ContextUsageProjection, RendererState } from "./state";
import { CustomSelect } from "./CustomSelect";
import { useTranslation, type TranslationKey } from "./i18n";

export interface RuntimePanelProps {
  state: Pick<RendererState, "runtimeState" | "runtimeError" | "run" | "contextUsage" | "permissionMode" | "currentModelRef" | "activeTurn" | "turnStatus" | "completionBlocked" | "diagnostics" | "selectedProjectKey" | "selectedSessionId" | "panelMode">;
  onPanelModeChange: (mode: PanelModePreference) => void;
}
export function RuntimeLayoutSelect({ value, onChange, labels }: { value: PanelModePreference; onChange: (mode: PanelModePreference) => void; labels: Record<PanelModePreference, string> & { control: string } }) {
  return <CustomSelect value={value} onChange={(next) => onChange(next as PanelModePreference)} label={labels.control} options={[{ value: "docked", label: labels.docked }, { value: "floating", label: labels.floating }, { value: "hidden", label: labels.hidden }]} />;
}
function usageLabel(usage: ContextUsageProjection | undefined, unavailable: string): string {
  if (!usage?.available) return unavailable;
  return `${usage.used_tokens.toLocaleString()} / ${usage.budget_tokens.toLocaleString()}`;
}
export function stateLabel(value: string, t: (key: TranslationKey) => string): string {
  const keys: Partial<Record<string, TranslationKey>> = { ready: "ready", idle: "idle", default: "default", auto: "auto", full_access: "fullAccess", booting: "booting", initializing: "initializing", configuration_required: "configurationRequired", stopped: "stopped", running: "running", pausing: "pausing", paused: "paused", failed: "failed", completed: "completed", cancelled: "cancelled", unknown: "unknown", plan: "plan" };
  return keys[value] ? t(keys[value]!) : value;
}

export function RuntimePanel({ state, onPanelModeChange }: RuntimePanelProps) {
  const { t } = useTranslation();
  return (
    <aside className={`runtime-panel runtime-panel--${state.panelMode}`} aria-label={t("runtimeInformation")} aria-hidden={state.panelMode === "hidden" || undefined}>
      <header className="runtime-heading">
        <div>
          <h2>{stateLabel(state.runtimeState, t)}</h2>
        </div>
        <label>
          <span className="sr-only">{t("runtimeLayout")}</span>
          <RuntimeLayoutSelect value={state.panelMode} onChange={onPanelModeChange} labels={{ control: t("runtimeLayout"), docked: t("docked"), floating: t("floating"), hidden: t("hidden") }} />
        </label>
      </header>
      <dl className="runtime-facts">
        <div><dt>{t("turn")}</dt><dd>{stateLabel(state.activeTurn ? state.turnStatus : "idle", t)}</dd></div>
        <div><dt>{t("runId")}</dt><dd title={state.run?.run_id}>{state.run?.run_id ? state.run.run_id.slice(0, 8) : "—"}</dd></div>
        <div><dt>{t("model")}</dt><dd title={state.currentModelRef ?? undefined}>{state.currentModelRef ?? "—"}</dd></div>
        <div><dt>{t("permission")}</dt><dd>{stateLabel(state.permissionMode, t)}</dd></div>
        <div><dt>{t("context")}</dt><dd>{usageLabel(state.contextUsage, t("unavailable"))}</dd></div>
        <div><dt>{t("mode")}</dt><dd>{stateLabel(state.run?.behavior_mode ?? "default", t)}</dd></div>
        <div><dt>{t("project")}</dt><dd title={state.selectedProjectKey ?? undefined}>{state.selectedProjectKey ? state.selectedProjectKey.split(/[\\/]/u).filter(Boolean).pop() : "—"}</dd></div>
        <div><dt>{t("session")}</dt><dd>{state.selectedSessionId ? state.selectedSessionId.slice(0, 8) : "—"}</dd></div>
      </dl>
      {state.completionBlocked && <p>{state.completionBlocked.replace(/^Completion blocked: (\d+) unfinished task\(s\)$/u, (_, count: string) => `${t("completionBlockedLabel")}: ${count} ${t("unfinishedTasks")}`)}</p>}
      {state.runtimeError && <p role="alert">{state.runtimeError}</p>}
      {state.diagnostics.length > 0 && <p>{t("diagnosticsAvailable")} ({state.diagnostics.length})</p>}
    </aside>
  );
}
