import { useEffect, useRef } from "react";
import type { PanelModePreference } from "../desktop-api";
import type { ConfigurationView, ContextUsageProjection, ProviderRequestUsageProjection, RendererState } from "./state";
import { CustomSelect } from "./CustomSelect";
import { useTranslation, type TranslationKey } from "./i18n";
import { UiIcon } from "./UiIcon";

export interface RuntimePanelProps {
  state: Pick<RendererState, "runtimeState" | "runtimeError" | "run" | "contextUsage" | "lastProviderRequestUsage" | "compactionStatus" | "permissionMode" | "currentModelRef" | "activeTurn" | "terminalStatusPending" | "turnStatus" | "completionBlocked" | "diagnostics" | "selectedProjectKey" | "selectedSessionId" | "panelMode" | "configuration">;
  onPanelModeChange: (mode: PanelModePreference) => void;
  id?: string;
  visible?: boolean;
  /** Enable drawer-only dismissal and focus ownership (narrow overlay). */
  drawer?: boolean;
  onClose?: () => void;
  onRestoreToggleFocus?: () => void;
}
const RUNTIME_FOCUSABLE_SELECTOR = "button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), a[href], [tabindex]:not([tabindex='-1'])";
export function RuntimeLayoutSelect({ value, onChange, labels }: { value: PanelModePreference; onChange: (mode: PanelModePreference) => void; labels: Record<PanelModePreference, string> & { control: string } }) {
  return <CustomSelect value={value} onChange={(next) => onChange(next as PanelModePreference)} label={labels.control} options={[{ value: "docked", label: labels.docked }, { value: "floating", label: labels.floating }, { value: "hidden", label: labels.hidden }]} />;
}
function usageLabel(usage: ContextUsageProjection | undefined, t: (key: TranslationKey) => string): string {
  if (!usage) return t("unavailable");
  const budget = usage.budget_tokens > 0 ? usage.budget_tokens.toLocaleString() : t("unavailable");
  const measurement = usage.measurement === "exact" ? t("exact") : usage.measurement === "estimate" ? t("estimate") : t("unavailable");
  return usage.available
    ? `${usage.used_tokens.toLocaleString()} / ${budget} · ${measurement}`
    : `${t("unavailable")} · ${budget}`;
}
export function providerUsageLabel(usage: ProviderRequestUsageProjection | undefined, t: (key: TranslationKey) => string): string {
  if (!usage || usage.status !== "available") return t("unavailable");
  const metrics: string[] = [];
  if (usage.total_tokens !== null) metrics.push(`${t("totalTokens")}: ${usage.total_tokens.toLocaleString()}`);
  if (usage.input_tokens !== null) metrics.push(`${t("inputTokens")}: ${usage.input_tokens.toLocaleString()}`);
  if (usage.output_tokens !== null) metrics.push(`${t("outputTokens")}: ${usage.output_tokens.toLocaleString()}`);
  if (usage.cache_read.status === "available" && usage.cache_read.tokens !== null) metrics.push(`${t("cacheRead")}: ${usage.cache_read.tokens.toLocaleString()}`);
  if (usage.cache_write.status === "available" && usage.cache_write.tokens !== null) metrics.push(`${t("cacheWrite")}: ${usage.cache_write.tokens.toLocaleString()}`);
  return metrics.length ? metrics.join(" · ") : t("unavailable");
}
export function stateLabel(value: string, t: (key: TranslationKey) => string): string {
  const keys: Partial<Record<string, TranslationKey>> = { ready: "ready", idle: "idle", default: "default", auto: "auto", full_access: "fullAccess", booting: "booting", restarting: "restarting", initializing: "initializing", configuration_required: "configurationRequired", stopped: "stopped", running: "running", pausing: "pausing", paused: "paused", failed: "failed", completed: "completed", no_change: "noChange", cancelled: "cancelled", unknown: "unknown", plan: "plan", manual: "manual", overflow: "overflow", estimate: "estimate", exact: "exact" };
  return keys[value] ? t(keys[value]!) : value;
}
function modelDisplayName(configuration: ConfigurationView | null, modelRef: string | null | undefined): string {
  const reference = modelRef?.trim();
  if (!reference) return "";
  const profile = configuration?.models?.[reference];
  const display = typeof profile?.display_name === "string" ? profile.display_name.trim() : "";
  if (display) return display;
  const remote = typeof profile?.remote_id === "string" ? profile.remote_id.trim() : "";
  return remote || reference;
}
function modelTooltip(configuration: ConfigurationView | null, modelRef: string | null | undefined): string | undefined {
  const reference = modelRef?.trim();
  if (!reference) return undefined;
  const profile = configuration?.models?.[reference];
  const display = typeof profile?.display_name === "string" ? profile.display_name.trim() : "";
  if (display) return display;
  const remote = typeof profile?.remote_id === "string" ? profile.remote_id.trim() : "";
  return remote || undefined;
}

export function RuntimePanel({ state, onPanelModeChange, id = "runtime-panel", visible = state.panelMode !== "hidden", drawer = false, onClose, onRestoreToggleFocus }: RuntimePanelProps) {
  const { t } = useTranslation();
  const panelRef = useRef<HTMLElement>(null);
  const previousModeRef = useRef<PanelModePreference>(state.panelMode);
  // Start outside drawer mode so an initially-open narrow overlay receives
  // focus just like one opened by the conversation-bar toggle.
  const previousDrawerRef = useRef(false);
  const closeDrawer = onClose ?? (() => onPanelModeChange("hidden"));
  useEffect(() => {
    if (typeof document === "undefined") return undefined;
    const panel = panelRef.current;
    const previousMode = previousModeRef.current;
    const previousDrawer = previousDrawerRef.current;
    previousModeRef.current = state.panelMode;
    previousDrawerRef.current = drawer;
    if (!visible && panel?.contains(document.activeElement)) onRestoreToggleFocus?.();
    if (drawer && visible && state.panelMode === "floating" && (!previousDrawer || previousMode !== "floating")) {
      panel?.querySelector<HTMLElement>(RUNTIME_FOCUSABLE_SELECTOR)?.focus();
    }
    return undefined;
  }, [drawer, onRestoreToggleFocus, state.panelMode, visible]);
  useEffect(() => {
    if (!drawer || !visible || state.panelMode !== "floating" || typeof document === "undefined") return undefined;
    const panel = panelRef.current;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      closeDrawer();
    };
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (target instanceof Node && panel?.contains(target)) return;
      closeDrawer();
    };
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("pointerdown", onPointerDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("pointerdown", onPointerDown);
    };
  }, [closeDrawer, drawer, state.panelMode, visible]);
  return (
    <aside ref={panelRef} id={id} className={`runtime-panel runtime-panel--${state.panelMode}`} aria-label={t("runtimeInformation")} aria-hidden={!visible || undefined}>
      <header className="runtime-heading">
        <div>
          <h2><UiIcon name="runtime" />{stateLabel(state.runtimeState, t)}</h2>
        </div>
        <label>
          <span className="sr-only">{t("runtimeLayout")}</span>
          <RuntimeLayoutSelect value={state.panelMode} onChange={onPanelModeChange} labels={{ control: t("runtimeLayout"), docked: t("docked"), floating: t("floating"), hidden: t("hidden") }} />
        </label>
      </header>
      <div className="runtime-groups">
        <section className="runtime-group runtime-group--status" aria-labelledby={`${id}-status-heading`}>
          <h3 id={`${id}-status-heading`}>{t("runtimeStatusGroup")}</h3>
          <dl className="runtime-facts">
            <div><dt>{t("turn")}</dt><dd>{state.terminalStatusPending ? t("terminalStatusPending") : stateLabel(state.activeTurn ? state.turnStatus : "idle", t)}</dd></div>
            <div><dt>{t("permission")}</dt><dd>{stateLabel(state.permissionMode, t)}</dd></div>
            <div><dt>{t("compaction")}</dt><dd>{stateLabel(state.compactionStatus.state, t)}{state.compactionStatus.trigger ? ` · ${stateLabel(state.compactionStatus.trigger, t)}` : ""}</dd></div>
          </dl>
        </section>
        <section className="runtime-group runtime-group--environment" aria-labelledby={`${id}-environment-heading`}>
          <h3 id={`${id}-environment-heading`}>{t("runtimeEnvironmentGroup")}</h3>
          <dl className="runtime-facts">
            <div><dt>{t("currentContext")}</dt><dd data-runtime-usage="current-context" data-usage-status={state.contextUsage.available ? "available" : "unavailable"}>{usageLabel(state.contextUsage, t)}</dd></div>
            <div><dt>{t("lastProviderRequestUsage")}</dt><dd data-runtime-usage="last-provider-request" data-usage-status={state.lastProviderRequestUsage.status}>{providerUsageLabel(state.lastProviderRequestUsage, t)}</dd></div>
          </dl>
        </section>
        <section className="runtime-group runtime-group--identity" aria-labelledby={`${id}-identity-heading`}>
          <h3 id={`${id}-identity-heading`}>{t("runtimeIdentityGroup")}</h3>
          <dl className="runtime-facts">
            <div><dt>{t("runId")}</dt><dd className="is-technical" title={state.run?.run_id}>{state.run?.run_id ? state.run.run_id.slice(0, 8) : "—"}</dd></div>
            <div><dt>{t("model")}</dt><dd className="is-technical" title={modelTooltip(state.configuration, state.currentModelRef)}>{modelDisplayName(state.configuration, state.currentModelRef) || "—"}</dd></div>
            <div><dt>{t("mode")}</dt><dd>{stateLabel(state.run?.behavior_mode ?? "default", t)}</dd></div>
            <div><dt>{t("project")}</dt><dd className="is-technical" title={state.selectedProjectKey ?? undefined}>{state.selectedProjectKey ? state.selectedProjectKey.split(/[\\/]/u).filter(Boolean).pop() : "—"}</dd></div>
            <div><dt>{t("session")}</dt><dd className="is-technical">{state.selectedSessionId ? state.selectedSessionId.slice(0, 8) : "—"}</dd></div>
          </dl>
        </section>
      </div>
      {state.completionBlocked && <p>{state.completionBlocked.replace(/^Completion blocked: (\d+) unfinished task\(s\)$/u, (_, count: string) => `${t("completionBlockedLabel")}: ${count} ${t("unfinishedTasks")}`)}</p>}
      {visible && state.runtimeError && <p className="runtime-panel__error" data-runtime-error-owner="runtime-panel" role="alert">{state.runtimeError}</p>}
      {state.diagnostics.length > 0 && <p>{t("diagnosticsAvailable")} ({state.diagnostics.length})</p>}
    </aside>
  );
}
