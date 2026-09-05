import { useCallback, useEffect, useLayoutEffect, useReducer, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { isDesktopCommandResult } from "../desktop-api";
import {
  DEFAULT_RUNTIME_PANEL_WIDTH,
  DEFAULT_SIDEBAR_WIDTH,
  RUNTIME_PANEL_WIDTH_MAX,
  RUNTIME_PANEL_WIDTH_MIN,
  SIDEBAR_WIDTH_MAX,
  SIDEBAR_WIDTH_MIN,
} from "../desktop-api";
import type { AgentEvent, DesktopApi, DesktopPreferences, JsonObject, JsonValue, LanguagePreference, PanelModePreference, ThemePreference } from "../desktop-api";
import { ChatTimeline } from "./ChatTimeline";
import { Composer } from "./Composer";
import { RuntimePanel } from "./RuntimePanel";
import { Sidebar } from "./Sidebar";
import { InteractionSurface, interactionSurfaceKey } from "./InteractionSurface";
import { SettingsView, type ConfigurationWrite } from "./SettingsView";
import { createInitialState, reduceRendererState, type RendererAction, type RendererState, type ProjectState, type SessionSummary, type ConfigurationView } from "./state";
import {
  eventIdentity,
  hasCompleteTurnIdentity,
  hasTurnIdentity,
  identityFromRun,
  knownIdentityMatches,
  rebootstrapProject,
  RuntimeOperationCancelled,
  StaleRuntimeOperation,
  stringValue,
  useRuntimeLifecycle,
  type RuntimeOwnershipCheck,
} from "./useRuntimeLifecycle";
import { sessionRuntimeKey, type SessionOrderReason } from "./state-session";
import { UiIcon } from "./UiIcon";
import { LanguageProvider, translate } from "./i18n";

export interface AppProps {
  api?: DesktopApi;
  initialState?: RendererState;
}

const RUNTIME_PANEL_ID = "runtime-panel";
export const CONVERSATION_MIN_WIDTH = 240;

export interface LayoutWidthBounds {
  sidebar: { min: number; max: number };
  runtime: { min: number; max: number };
}

export function clampLayoutWidth(value: number, bounds: { min: number; max: number }): number {
  if (!Number.isFinite(value)) return bounds.min;
  return Math.round(Math.min(bounds.max, Math.max(bounds.min, value)));
}

/** Calculate CSS-pixel limits while leaving a readable Conversation column. */
export function layoutWidthBounds(
  viewportWidth: number,
  panelMode: PanelModePreference,
  sidebarWidth = DEFAULT_SIDEBAR_WIDTH,
  runtimePanelWidth = DEFAULT_RUNTIME_PANEL_WIDTH,
): LayoutWidthBounds {
  const viewport = Number.isFinite(viewportWidth) ? Math.max(0, viewportWidth) : 1280;
  const runtimeBudget = panelMode === "docked"
    ? viewport - SIDEBAR_WIDTH_MIN - CONVERSATION_MIN_WIDTH
    : viewport - 16;
  const runtimeMax = Math.min(RUNTIME_PANEL_WIDTH_MAX, Math.max(RUNTIME_PANEL_WIDTH_MIN, runtimeBudget));
  const runtime = clampLayoutWidth(runtimePanelWidth, { min: RUNTIME_PANEL_WIDTH_MIN, max: runtimeMax });
  const sidebarBudget = viewport - CONVERSATION_MIN_WIDTH - (panelMode === "docked" ? runtime : 0);
  const sidebarMax = Math.min(SIDEBAR_WIDTH_MAX, Math.max(SIDEBAR_WIDTH_MIN, sidebarBudget));
  const sidebar = clampLayoutWidth(sidebarWidth, { min: SIDEBAR_WIDTH_MIN, max: sidebarMax });
  // A very narrow wide-mode viewport may leave no room for both minimums. In
  // that case the explicit narrow media query takes over at 680 CSS pixels;
  // keeping the bounded values here prevents a negative grid track.
  const finalRuntimeBudget = panelMode === "docked"
    ? viewport - sidebar - CONVERSATION_MIN_WIDTH
    : viewport - 16;
  const finalRuntimeMax = Math.min(RUNTIME_PANEL_WIDTH_MAX, Math.max(RUNTIME_PANEL_WIDTH_MIN, finalRuntimeBudget));
  return {
    sidebar: { min: SIDEBAR_WIDTH_MIN, max: sidebarMax },
    runtime: { min: RUNTIME_PANEL_WIDTH_MIN, max: finalRuntimeMax },
  };
}

export function clampedLayoutWidths(
  viewportWidth: number,
  panelMode: PanelModePreference,
  sidebarWidth: number,
  runtimePanelWidth: number,
): { sidebarWidth: number; runtimePanelWidth: number } {
  const bounds = layoutWidthBounds(viewportWidth, panelMode, sidebarWidth, runtimePanelWidth);
  const nextSidebar = clampLayoutWidth(sidebarWidth, bounds.sidebar);
  const nextRuntime = clampLayoutWidth(runtimePanelWidth, bounds.runtime);
  return { sidebarWidth: nextSidebar, runtimePanelWidth: nextRuntime };
}

interface ResizeSeparatorProps {
  side: "sidebar" | "runtime";
  value: number;
  bounds: { min: number; max: number };
  label: string;
  disabled?: boolean;
  onPreview: (value: number) => void;
  onCommit: (value: number) => void;
}

function ResizeSeparator({ side, value, bounds, label, disabled = false, onPreview, onCommit }: ResizeSeparatorProps) {
  const drag = useRef<{ pointerId: number; origin: number; originValue: number; lastValue: number } | null>(null);
  const valueForPointer = (clientX: number) => clampLayoutWidth(side === "sidebar"
    ? (drag.current?.originValue ?? value) + (clientX - (drag.current?.origin ?? clientX))
    : (drag.current?.originValue ?? value) - (clientX - (drag.current?.origin ?? clientX)), bounds);
  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (disabled || event.button !== 0) return;
    event.preventDefault();
    drag.current = { pointerId: event.pointerId, origin: event.clientX, originValue: value, lastValue: value };
    try { event.currentTarget.setPointerCapture(event.pointerId); } catch { /* jsdom and older WebViews may not implement capture */ }
  };
  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!drag.current || drag.current.pointerId !== event.pointerId) return;
    const next = valueForPointer(event.clientX);
    drag.current.lastValue = next;
    onPreview(next);
  };
  const finishPointer = (event: ReactPointerEvent<HTMLDivElement>, commit: boolean) => {
    if (!drag.current || drag.current.pointerId !== event.pointerId) return;
    const current = drag.current;
    drag.current = null;
    try { event.currentTarget.releasePointerCapture(event.pointerId); } catch { /* capture is optional */ }
    if (commit) onCommit(current.lastValue);
  };
  const onKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (disabled) return;
    const step = event.shiftKey ? 48 : 16;
    let next: number | null = null;
    if (event.key === "Home") next = bounds.min;
    else if (event.key === "End") next = bounds.max;
    else if (side === "sidebar" && event.key === "ArrowLeft") next = value - step;
    else if (side === "sidebar" && event.key === "ArrowRight") next = value + step;
    else if (side === "runtime" && event.key === "ArrowLeft") next = value + step;
    else if (side === "runtime" && event.key === "ArrowRight") next = value - step;
    if (next === null) return;
    event.preventDefault();
    const clamped = clampLayoutWidth(next, bounds);
    onPreview(clamped);
    onCommit(clamped);
  };
  return <div
    className={`layout-separator layout-separator--${side}`}
    role="separator"
    aria-orientation="vertical"
    aria-label={label}
    aria-valuemin={bounds.min}
    aria-valuemax={bounds.max}
    aria-valuenow={value}
    aria-controls="workspace-main"
    aria-disabled={disabled || undefined}
    data-resize-side={side}
    tabIndex={disabled ? -1 : 0}
    onPointerDown={onPointerDown}
    onPointerMove={onPointerMove}
    onPointerUp={(event) => finishPointer(event, true)}
    onPointerCancel={(event) => finishPointer(event, false)}
    onKeyDown={onKeyDown}
  />;
}

function runtimeApi(explicit?: DesktopApi): DesktopApi | undefined {
  if (explicit) return explicit;
  if (typeof window !== "undefined" && window.uthcode) return window.uthcode;
  return undefined;
}

function asObject(value: unknown): JsonObject {
  if (value && typeof value === "object" && !Array.isArray(value)) return value as JsonObject;
  return {};
}

/**
 * Project every failed Desktop call to a renderer-owned localized message.
 *
 * Main/transport errors deliberately retain their internal kind and message
 * for diagnostics, and a RuntimeRequestError may include an IPC method,
 * native exception class, or filesystem detail.  None of those values are a
 * renderer contract.  Call sites already provide the action-specific,
 * localized fallback, so an unknown failure must never be promoted to UI.
 */
export function safeErrorMessage(_error: unknown, fallback: string): string {
  return fallback;
}

/**
 * Translate the Bridge's semantic command result without ever consuming
 * Application output/error text.  Params are used only as typed flags; the
 * visible copy remains owned by the current Renderer locale.
 */
export function commandResultNotice(
  value: unknown,
  localize: (key: Parameters<typeof translate>[1]) => string,
): string | null {
  const source = asObject(value);
  const code = stringValue(source.code);
  switch (code) {
    case "status_ready":
      return localize("runtimeInformation");
    case "help_ready":
      return localize("commandHelp");
    case "compact_completed":
      return `${localize("compaction")} · ${localize("completed")}`;
    case "compact_no_change":
      return `${localize("compaction")} · ${localize("noChange")}`;
    case "compact_cancelled":
      return `${localize("compaction")} · ${localize("cancelled")}`;
    case "compact_failed":
      return `${localize("compaction")} · ${localize("failed")}`;
    case "session_created":
      return localize("newSessionNotice");
    case "session_resumed":
      return localize("sessionResumed");
    case "model_selected":
      return localize("commandModelSelected");
    case "behavior_mode_selected":
      return localize("commandModeSelected");
    case "permission_mode_selected": {
      const params = asObject(source.params);
      return params.warning === true
        ? localize("commandPermissionWarning")
        : localize("commandPermissionSelected");
    }
    case "model_picker_opened":
      return localize("chooseModel");
    case "permission_picker_opened":
      return localize("permission");
    case "session_picker_opened":
      return localize("session");
    case "transcript_cleared":
      return null;
    case "command_unavailable":
    case "command_usage_error":
    case "command_failed":
      return localize("commandFailed");
    case "interface_quit":
      return null;
    case "command_completed":
      return localize("commandCompleted");
    default:
      // A future Bridge code must remain safe and localized even before this
      // Renderer version learns its detailed presentation.
      return source.status === "success" ? localize("commandCompleted") : localize("commandFailed");
  }
}

function projectPreferences(projects: ProjectState[]): DesktopPreferences["recentProjects"] {
  return projects.map((project) => ({
    path: project.path,
    alias: project.alias,
    pinned: project.pinned,
    ...(project.lastOpenedAt ? { lastOpenedAt: project.lastOpenedAt } : {}),
  }));
}

/** Remove every Desktop-local reference to a project without touching disk. */
export function projectNavigationPreferences(
  projects: readonly ProjectState[],
  pinnedSessions: DesktopPreferences["pinnedSessions"],
  expandedProjects: DesktopPreferences["expandedProjects"] = {},
): Pick<DesktopPreferences, "recentProjects" | "projectAliases" | "pinnedProjectKeys" | "pinnedSessions" | "expandedProjects"> {
  const projectKeys = new Set(projects.map((project) => project.projectKey));
  return {
    recentProjects: projectPreferences([...projects]),
    projectAliases: Object.fromEntries(projects.map((project) => [project.projectKey, project.alias])),
    pinnedProjectKeys: projects.filter((project) => project.pinned).map((project) => project.projectKey),
    pinnedSessions: pinnedSessions.filter((item) => projectKeys.has(item.projectKey)),
    expandedProjects: Object.fromEntries(Object.entries(expandedProjects).filter(([projectKey]) => projectKeys.has(projectKey))),
  };
}

export function projectRemovalPlan(projects: readonly ProjectState[], selectedProjectKey: string | null, removedProjectKey: string): {
  remaining: ProjectState[];
  current: boolean;
  replacement: ProjectState | null;
} {
  const remaining = projects.filter((project) => project.projectKey !== removedProjectKey);
  return {
    remaining,
    current: selectedProjectKey === removedProjectKey,
    replacement: remaining[0] ?? null,
  };
}

export function projectPinPlan(projects: readonly ProjectState[], pinnedSessions: DesktopPreferences["pinnedSessions"], projectKey: string) {
  const projectsNext = projects.map((item) => item.projectKey === projectKey ? { ...item, pinned: !item.pinned } : item);
  const pinned = projectsNext.find((item) => item.projectKey === projectKey)?.pinned === true;
  return { projects: projectsNext, pinnedSessions: pinned ? pinnedSessions.filter((item) => item.projectKey !== projectKey) : [...pinnedSessions] };
}

export function App({ api: explicitApi, initialState }: AppProps) {
  const [state, dispatch] = useReducer(reduceRendererState, initialState ?? createInitialState());
  const stateRef = useRef(state);
  stateRef.current = state;
  const api = runtimeApi(explicitApi);
  const [narrowViewport, setNarrowViewport] = useState(() => typeof window !== "undefined" && window.innerWidth <= 680);
  const [viewportWidth, setViewportWidth] = useState(() => typeof window !== "undefined" ? window.innerWidth : 1280);
  const narrowViewportRef = useRef(narrowViewport);
  const runtimeToggleRef = useRef<HTMLButtonElement>(null);
  const focusModeToggleRef = useRef<HTMLButtonElement>(null);
  const runtimeFocusHandoffRef = useRef(false);
  const settingsSaveInFlightRef = useRef(false);
  const sessionMutationGenerationRef = useRef(0);
  const sessionMutationSequenceRef = useRef(0);
  const sessionMutationInFlightRef = useRef<number | null>(null);
  const commandInFlightRef = useRef(false);
  const interactionSubmitRef = useRef<string | null>(null);
  const cancelInFlightRef = useRef(false);
  const runtimeStatusPollRef = useRef<Promise<boolean> | null>(null);
  const historyRequestsRef = useRef<Map<string, { token: symbol; promise: Promise<void> }>>(new Map());
  const preparationPollSequenceRef = useRef(0);
  const preparationPollRef = useRef<Map<string, number>>(new Map());
  const t = useCallback((key: Parameters<typeof translate>[1]) => translate(stateRef.current.language, key), []);

  const send = useCallback(async (method: Parameters<DesktopApi["requestRuntime"]>[0], params: JsonObject = {}) => {
    if (!api) throw new Error(t("desktopApiUnavailable"));
    return api.requestRuntime(method, params);
  }, [api, t]);
  const lifecycle = useRuntimeLifecycle({ api, stateRef, dispatch });
  const {
    isMounted,
    hasOwner,
    runtimeGeneration,
    waitForRuntimeLifecycleIdle,
    waitForRuntimeUserAccess,
    enqueueRuntimeOperation,
    cancelTerminalStatusPoll,
    startTerminalStatusConvergence,
    hasTerminalStatusPoll,
    terminalStatusPollFor,
    latestTurnIdentity,
    setLatestTurnIdentity,
    beginPendingTurnStart,
    pendingTurnStart,
    bufferPendingTurnEvent,
    finishPendingTurnStart,
    clearPendingTurnStart,
  } = lifecycle;

  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const updateViewport = () => {
      const nextNarrow = window.innerWidth <= 680;
      const wasNarrow = narrowViewportRef.current;
      const activeElement = document.activeElement;
      if (wasNarrow && !nextNarrow && activeElement?.closest("[data-runtime-error-owner='timeline']")) {
        // The Timeline owner is removed in the same commit that reveals a
        // docked RuntimePanel.  Preserve an explicit user focus boundary so
        // that the DOM mutation cannot strand focus on <body>.
        runtimeFocusHandoffRef.current = true;
      }
      narrowViewportRef.current = nextNarrow;
      setViewportWidth(window.innerWidth);
      setNarrowViewport(nextNarrow);
    };
    updateViewport();
    window.addEventListener("resize", updateViewport);
    return () => window.removeEventListener("resize", updateViewport);
  }, []);

  // Keep the rendered tracks inside the current CSS-pixel viewport. This is
  // a presentation clamp only: the stable user-selected width is persisted
  // by the separator's commit callback, never by resize/zoom churn.
  useEffect(() => {
    if (typeof window === "undefined" || narrowViewport) return;
    const next = clampedLayoutWidths(viewportWidth, state.panelMode, state.sidebarWidth, state.runtimePanelWidth);
    if (next.sidebarWidth !== state.sidebarWidth) dispatch({ type: "set_sidebar_width", width: next.sidebarWidth });
    if (next.runtimePanelWidth !== state.runtimePanelWidth) dispatch({ type: "set_runtime_panel_width", width: next.runtimePanelWidth });
  }, [narrowViewport, viewportWidth, state.panelMode, state.runtimePanelWidth, state.sidebarWidth]);

  const persist = useCallback(async (key: "theme" | "language" | "panelMode" | "sidebarWidth" | "runtimePanelWidth" | "recentProjects" | "projectAliases" | "pinnedProjectKeys" | "pinnedSessions" | "expandedProjects" | "selectedProjectKey" | "selectedSessionId", value: unknown) => {
    if (!api) return;
    try {
      await api.writePreference(key as never, value as never);
    } catch (error) {
      // Desktop metadata is advisory; a temporary preference failure must not
      // replace the Application's authoritative state.  It may still be
      // actionable for the user, but only through the localized renderer
      // fallback; native EPERM/path details stay outside the UI boundary.
      dispatch({ type: "notice", text: safeErrorMessage(error, t("preferencesUnavailable")) });
    }
  }, [api, t]);

  const beginSessionMutation = useCallback((): { sequence: number; generation: number } | null => {
    if (sessionMutationInFlightRef.current !== null) {
      dispatch({ type: "notice", text: t("sessionMutationBusy") });
      return null;
    }
    const generation = sessionMutationGenerationRef.current + 1;
    sessionMutationGenerationRef.current = generation;
    const sequence = sessionMutationSequenceRef.current + 1;
    sessionMutationSequenceRef.current = sequence;
    sessionMutationInFlightRef.current = sequence;
    // One gate covers both durable Session mutation methods.
    dispatch({ type: "session_mutation_busy", value: true });
    return { sequence, generation };
  }, [t]);

  const endSessionMutation = useCallback((sequence: number) => {
    if (sessionMutationInFlightRef.current !== sequence) return;
    sessionMutationInFlightRef.current = null;
    if (isMounted()) dispatch({ type: "session_mutation_busy", value: false });
  }, [isMounted]);

  const refreshCatalog = useCallback(async (projectKey: string, reason: SessionOrderReason = "catalog_refresh", focusSessionId?: string, reportFailure = true, isOwned?: RuntimeOwnershipCheck): Promise<boolean> => {
    if (isOwned) {
      if (!isOwned()) return false;
    } else if (!(await waitForRuntimeLifecycleIdle()) || hasOwner() || stateRef.current.runtimeState === "restarting") return false;
    try {
      const result = asObject(await send("project.sessions", {}));
      if (isOwned && !isOwned()) return false;
      if (!isOwned && (hasOwner() || stateRef.current.runtimeState === "restarting")) return false;
      const sessions = Array.isArray(result.sessions) ? result.sessions : [];
      dispatch({ type: "catalog_refreshed", projectKey, sessions, reason, focusSessionId });
      return true;
    } catch (error) {
      if ((!isOwned || isOwned()) && reportFailure) dispatch({ type: "notice", text: safeErrorMessage(error, t("sessionCatalogUnavailable")) });
      return false;
    }
  }, [hasOwner, send, t, waitForRuntimeLifecycleIdle]);

  const reconcileSessionMutation = useCallback(async (projectKey: string, sequence: number): Promise<void> => {
    // ``project.sessions`` is authoritative only for the Application's
    // current project. Never apply that response to a different project after
    // navigation; the next explicit project.open will reload its catalog.
    if (!isMounted() || sessionMutationInFlightRef.current !== sequence) return;
    if (stateRef.current.selectedProjectKey !== projectKey) return;
    await refreshCatalog(projectKey, "catalog_refresh", undefined, false);
  }, [isMounted, refreshCatalog]);

  const refreshRuntimeStatus = useCallback(async (isOwned?: RuntimeOwnershipCheck, skipIfOwned = false): Promise<boolean> => {
    if (isOwned) {
      if (!isOwned()) return false;
    } else {
      if (skipIfOwned && (hasOwner() || stateRef.current.runtimeState === "restarting")) return false;
      if (!(await waitForRuntimeLifecycleIdle())) return false;
      if (hasOwner() || stateRef.current.runtimeState === "restarting") return false;
    }
    try {
      const result = await send("status.get", {});
      if (isOwned && !isOwned()) return false;
      if (!isOwned && (hasOwner() || stateRef.current.runtimeState === "restarting")) return false;
      dispatch({ type: "status_loaded", result });
      return true;
    } catch {
      // Runtime status is supplementary safe projection; command and Run
      // authority remain usable when it is temporarily unavailable.
      return false;
    }
  }, [hasOwner, send, waitForRuntimeLifecycleIdle]);

  const loadHistoryPage = useCallback((projectKey: string, sessionId: string, cursor: string | null, replace: boolean): Promise<void> => {
    const key = sessionRuntimeKey(projectKey, sessionId);
    const existing = historyRequestsRef.current.get(key);
    if (existing) return existing.promise;
    dispatch({ type: "history_page_loading", projectKey, sessionId });
    const token = Symbol("history-page");
    const request = (async () => {
      try {
        const params: JsonObject = { session_id: sessionId, page_size: 30 };
        if (cursor !== null) params.cursor = cursor;
        const result = await send("history.page", params);
        if (historyRequestsRef.current.get(key)?.token !== token) return;
        dispatch({ type: "history_page_loaded", projectKey, sessionId, result, replace });
      } catch (error) {
        if (historyRequestsRef.current.get(key)?.token !== token) return;
        dispatch({ type: "history_page_error", projectKey, sessionId, message: safeErrorMessage(error, t("sessionCatalogUnavailable")) });
      } finally {
        if (historyRequestsRef.current.get(key)?.token === token) historyRequestsRef.current.delete(key);
      }
    })();
    historyRequestsRef.current.set(key, { token, promise: request });
    return request;
  }, [send, t]);

  const beginSessionPresentation = useCallback((projectKey: string, sessionId: string) => {
    const previousProjectKey = stateRef.current.selectedProjectKey;
    const previousSessionId = stateRef.current.selectedSessionId;
    if (previousSessionId && (previousProjectKey !== projectKey || previousSessionId !== sessionId)) {
      preparationPollRef.current.delete(sessionRuntimeKey(previousProjectKey, previousSessionId));
    }
    dispatch({ type: "history_page_started", projectKey, sessionId });
    const key = sessionRuntimeKey(projectKey, sessionId);
    const history = stateRef.current.sessionHistory[key];
    // A cached first page is already sufficient for immediate display.  An
    // error starts a local retry, while a missing key starts the first page
    // without waiting for the cold runtime preparation below.
    if (!history || history.error) void loadHistoryPage(projectKey, sessionId, null, true);
  }, [loadHistoryPage]);

  const pollSessionPreparation = useCallback((projectKey: string, sessionId: string) => {
    const key = sessionRuntimeKey(projectKey, sessionId);
    const token = preparationPollSequenceRef.current + 1;
    preparationPollSequenceRef.current = token;
    preparationPollRef.current.set(key, token);
    let initialPresentationCheck = true;
    const schedule = () => {
      if (typeof window === "undefined") return;
      window.setTimeout(() => { void poll(); }, 100);
    };
    const poll = async (): Promise<void> => {
      const current = stateRef.current;
      if (!isMounted() || preparationPollRef.current.get(key) !== token) return;
      // The selected Session dispatch and this observer are started in the
      // same React turn. A synchronous bridge response can reach here before
      // stateRef observes that commit; keep the keyed observer alive for the
      // next presentation tick. A later navigation removes the old key, so a
      // stale observer cannot poll forever.
      if (current.selectedProjectKey !== projectKey || current.selectedSessionId !== sessionId) {
        // The first poll is deferred until the navigation dispatch commits,
        // but React may still be between the dispatch and its state commit.
        // Allow exactly one bounded retry for that presentation race; any
        // later mismatch is a real stale observer (for example a project-only
        // open) and must terminate rather than retry forever.
        if (initialPresentationCheck) {
          initialPresentationCheck = false;
          schedule();
        } else if (preparationPollRef.current.get(key) === token) {
          preparationPollRef.current.delete(key);
        }
        return;
      }
      initialPresentationCheck = false;
      if (hasOwner() || current.runtimeState === "restarting") {
        schedule();
        return;
      }
      const generation = runtimeGeneration();
      try {
        const result = asObject(await send("session.resume", { session_id: sessionId }));
        const after = stateRef.current;
        if (preparationPollRef.current.get(key) !== token) return;
        if (!isMounted() || runtimeGeneration() !== generation || hasOwner()
          || after.selectedProjectKey !== projectKey || after.selectedSessionId !== sessionId) {
          // Keep polling only when this is still the selected target. A new
          // navigation removes its token; an unrelated lifecycle owner merely
          // asks us to try again after that owner releases the Runtime.
          if (preparationPollRef.current.get(key) === token
            && after.selectedProjectKey === projectKey && after.selectedSessionId === sessionId) schedule();
          return;
        }
        if (result.preparing === true || asObject(result.session_state).status === "preparing") {
          schedule();
          return;
        }
        preparationPollRef.current.delete(key);
        if (result.preparation_failed === true || result.session_id !== sessionId) {
          dispatch({ type: "session_preparation", projectKey, sessionId, status: "failed" });
          return;
        }
        dispatch({ type: "session_resumed", result, preserveRuntimeState: true, preserveSessionRuntime: true, preserveTimeline: true });
        await refreshRuntimeStatus();
      } catch (error) {
        const after = stateRef.current;
        if (preparationPollRef.current.get(key) !== token) return;
        if (!isMounted() || runtimeGeneration() !== generation || hasOwner()
          || after.selectedProjectKey !== projectKey || after.selectedSessionId !== sessionId) {
          if (preparationPollRef.current.get(key) === token
            && after.selectedProjectKey === projectKey && after.selectedSessionId === sessionId) schedule();
          return;
        }
        preparationPollRef.current.delete(key);
        dispatch({ type: "session_preparation", projectKey, sessionId, status: "failed" });
        dispatch({ type: "notice", text: safeErrorMessage(error, t("sessionResumeFailed")) });
      }
    };
    // Navigation dispatches the selected Session and preparation marker in
    // the same React turn that starts this observer.  Defer the first check
    // until that presentation commit is visible through stateRef; otherwise
    // the observer would mistake the previous Session for a stale target and
    // exit before the background preparation can be polled.
    if (typeof window !== "undefined") window.setTimeout(() => { void poll(); }, 0);
  }, [hasOwner, isMounted, refreshRuntimeStatus, runtimeGeneration, send, t]);

  const publishTerminalStatus = useCallback((result: JsonValue) => {
    dispatch({ type: "status_loaded", result });
  }, []);

  // Context and compaction are live Run facts, not just terminal summaries.
  // Poll at a modest cadence while work is active so provider usage and the
  // lock state stay visible even when no semantic AgentEvent is emitted.
  useEffect(() => {
    // Terminal convergence already owns the short active->idle polling loop.
    // Keep this supplementary cadence for live Turns/compaction only, so a
    // terminal event cannot race a convergence response with a second status
    // writer.
    if (!api || (!state.activeTurn && state.compactionStatus.state !== "running")) return undefined;
    let cancelled = false;
    const refresh = () => {
      if (cancelled || runtimeStatusPollRef.current) return;
      const pending = refreshRuntimeStatus(undefined, true);
      runtimeStatusPollRef.current = pending;
      void pending.then(
        () => {
          if (runtimeStatusPollRef.current === pending) runtimeStatusPollRef.current = null;
        },
        () => {
          if (runtimeStatusPollRef.current === pending) runtimeStatusPollRef.current = null;
        },
      );
    };
    const timer = window.setInterval(refresh, 1000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [api, refreshRuntimeStatus, state.activeTurn, state.compactionStatus.state]);

  const processAgentEvent = useCallback((event: AgentEvent) => {
    // Runtime lifecycle envelopes are transport-level facts. While an App
    // operation owns a restart, its explicit terminal state must not be
    // replaced by the shutdown/initialization envelopes emitted by the old
    // owner (notably `stopping`/`stopped`).
    if (event.type === "runtime_state" && hasOwner()) return;
    const eventSessionId = stringValue(event.session_id);
    const eventProjectKey = stringValue(event.project_key);
    const currentState = stateRef.current;
    const backgroundSession = Boolean(eventSessionId && (
      !currentState.selectedSessionId
      || eventSessionId !== currentState.selectedSessionId
      || Boolean(eventProjectKey && eventProjectKey !== currentState.selectedProjectKey)
    ));
    // A background runtime has its own Run/Turn identity.  The reducer keeps
    // that projection in the per-session cache; it must not be filtered by the
    // visible session's latest identity or start a visible terminal poll.
    if (backgroundSession) {
      dispatch({ type: "agent_event", event });
      return;
    }
    const { runId: eventRunId, turnId: eventTurnId } = eventIdentity(event);
    const latestMatches = () => {
      const latest = latestTurnIdentity();
      if (hasTurnIdentity(latest.runId, latest.turnId)) return knownIdentityMatches(latest.runId, latest.turnId, eventRunId, eventTurnId);
      const current = stateRef.current.run;
      const currentRunId = current?.run_id ?? "";
      const currentTurnId = current?.turn_id ?? "";
      return hasTurnIdentity(currentRunId, currentTurnId) && knownIdentityMatches(currentRunId, currentTurnId, eventRunId, eventTurnId);
    };
    if (event.type === "turn_started") {
      // A Core turn_started event is not itself an accepted boundary. Only
      // an already accepted run/turn (or the current known Run) may replace
      // poll ownership; a mismatched event must not cancel a live poll.
      if (!hasCompleteTurnIdentity({ runId: eventRunId, turnId: eventTurnId }) || !latestMatches()) return;
      setLatestTurnIdentity({ runId: eventRunId, turnId: eventTurnId });
      cancelTerminalStatusPoll();
    }
    const terminal = event.type === "turn_completed" || event.type === "turn_failed" || event.type === "turn_cancelled";
    if (terminal && (!hasCompleteTurnIdentity({ runId: eventRunId, turnId: eventTurnId }) || !latestMatches())) return;
    dispatch({ type: "agent_event", event });
    if (terminal) {
      // The terminal event is published before the Bridge releases its
      // active handle. Keep one cancellable, backoff poll alive until the
      // Application status explicitly reports active_turn=false.
      void startTerminalStatusConvergence(eventRunId, eventTurnId, false, async (result) => {
        publishTerminalStatus(result);
        const current = stateRef.current;
        const latest = latestTurnIdentity();
        if (knownIdentityMatches(latest.runId, latest.turnId, eventRunId, eventTurnId) && current.selectedProjectKey) {
          await refreshCatalog(current.selectedProjectKey, "message", current.selectedSessionId ?? undefined);
        }
      });
    }
  }, [cancelTerminalStatusPoll, hasOwner, latestTurnIdentity, publishTerminalStatus, refreshCatalog, setLatestTurnIdentity, startTerminalStatusConvergence]);

  const refreshConfiguration = useCallback(async (isOwned?: RuntimeOwnershipCheck) => {
    if (isOwned) {
      if (!isOwned()) return;
    } else if (!(await waitForRuntimeLifecycleIdle()) || hasOwner() || stateRef.current.runtimeState === "restarting") return;
    try {
      const result = asObject(await send("settings.get", {}));
      if (isOwned && !isOwned()) return;
      if (!isOwned && (hasOwner() || stateRef.current.runtimeState === "restarting")) return;
      dispatch({ type: "settings_loaded", configuration: asObject(result.configuration) as ConfigurationView });
    } catch {
      // An unconfigured Runtime is expected to reject this supplementary read;
      // the explicit Settings flow still reports the actionable error.
    }
  }, [hasOwner, send, waitForRuntimeLifecycleIdle]);

  const revealSettingsApiKey = useCallback(async (providerId: string): Promise<string | null> => {
    if (!(await waitForRuntimeUserAccess()) || hasOwner() || stateRef.current.runtimeState === "restarting") return null;
    const result = asObject(await send("settings.reveal_api_key", { provider_profile_id: providerId }));
    const value = result.api_key;
    if (value === null || typeof value === "string") return value;
    throw new Error("Invalid API key reveal response");
  }, [hasOwner, send, waitForRuntimeUserAccess]);

  const openProjectPath = useCallback(async (path: string) => {
    if (!api) return;
    // Project-only navigation clears the selected Session, so every pending
    // preparation observer belongs to an obsolete visible target.  Remove
    // their tokens before the asynchronous project.open boundary can return.
    preparationPollRef.current.clear();
    await enqueueRuntimeOperation("navigation", async (isOwned) => {
      const result = await send("project.open", { path });
      if (!isOwned()) throw new StaleRuntimeOperation();
      dispatch({ type: "project_opened", result, preserveRuntimeState: true, preserveSessionRuntime: true });
      const next = stateRef.current.projects.some((project) => project.projectKey === path)
        ? stateRef.current.projects
        : [...stateRef.current.projects, { path, projectKey: path, alias: path.split(/[\\/]/u).filter(Boolean).pop() || path, pinned: false, sessions: [], catalogFresh: true }];
      await persist("recentProjects", projectPreferences(next));
      await persist("selectedProjectKey", path);
      if (!isOwned()) throw new StaleRuntimeOperation();
      await refreshCatalog(path, "project_open", undefined, true, isOwned);
      if (!isOwned()) throw new StaleRuntimeOperation();
      await refreshRuntimeStatus(isOwned);
      await refreshConfiguration(isOwned);
    }, async (error, isOwned) => {
      if (!isOwned()) return;
      const existing = stateRef.current.projects.find((project) => project.projectKey === path);
      const project = existing ?? { path, projectKey: path, alias: path.split(/[\\/]/u).filter(Boolean).pop() || path, pinned: false, sessions: [], catalogFresh: false };
      const projects = existing ? stateRef.current.projects : [...stateRef.current.projects, project];
      dispatch({ type: "hydrate_preferences", preferences: { recentProjects: projectPreferences(projects), selectedProjectKey: path, selectedSessionId: null } });
      await persist("recentProjects", projectPreferences(projects));
      await persist("selectedProjectKey", path);
      if (!isOwned()) return;
      dispatch({ type: "runtime_error", message: safeErrorMessage(error, t("projectOpenFailed")), state: "configuration_required" });
      dispatch({ type: "set_view", view: "settings" });
    });
  }, [api, enqueueRuntimeOperation, persist, refreshCatalog, refreshConfiguration, refreshRuntimeStatus, send, t]);

  useEffect(() => {
    if (!api) {
      dispatch({ type: "runtime_state", state: "ready" });
      return undefined;
    }
    let cancelled = false;
    const unsubscribe = api.subscribeAgentEvents((event) => {
      if (cancelled) return;
      const pendingStart = pendingTurnStart();
      const pendingEventIdentity = eventIdentity(event);
      if (pendingStart && hasTurnIdentity(pendingEventIdentity.runId, pendingEventIdentity.turnId)) {
        // Python Runtime can resolve turn.start and synchronously deliver the
        // following stdout events before the Promise continuation records the
        // accepted flat identity. Hold scoped events until that boundary is
        // known; unrelated identities are filtered when the response arrives.
        bufferPendingTurnEvent(event);
        return;
      }
      processAgentEvent(event);
    });
    void Promise.all([
      api.readPreference("theme"),
      api.readPreference("language"),
      api.readPreference("panelMode"),
      api.readPreference("sidebarWidth"),
      api.readPreference("runtimePanelWidth"),
      api.readPreference("recentProjects"),
      api.readPreference("projectAliases"),
      api.readPreference("pinnedProjectKeys"),
      api.readPreference("pinnedSessions"),
      api.readPreference("expandedProjects"),
      api.readPreference("selectedProjectKey"),
      api.readPreference("selectedSessionId"),
    ]).then(([theme, language, panelMode, sidebarWidth, runtimePanelWidth, recentProjects, projectAliases, pinnedProjectKeys, pinnedSessions, expandedProjects, selectedProjectKey, selectedSessionId]) => {
      // A user save/navigation may have become the current lifecycle owner
      // while Desktop preferences were still loading. Do not let this late
      // bootstrap callback supersede that newer generation.
      if (cancelled || hasOwner()) return;
      dispatch({ type: "hydrate_preferences", preferences: { theme, language, panelMode, sidebarWidth, runtimePanelWidth, recentProjects, projectAliases, pinnedProjectKeys, pinnedSessions, expandedProjects, selectedProjectKey, selectedSessionId } });
      const selected = (recentProjects as DesktopPreferences["recentProjects"]).find((project) => project.path === selectedProjectKey);
      if (selected) {
        void enqueueRuntimeOperation("startup", async (isOwned) => {
          const result = await send("runtime.initialize", { workdir: selected.path });
          if (cancelled || !isOwned()) throw new StaleRuntimeOperation();
          dispatch({ type: "runtime_initialized", result, preserveRuntimeState: true });
          await refreshConfiguration(isOwned);
          await refreshRuntimeStatus(isOwned);
          await refreshCatalog(selected.path, "catalog_refresh", undefined, true, isOwned);
          if (selectedSessionId) {
            beginSessionPresentation(selected.path, selectedSessionId);
            const resumed = await send("session.resume", { session_id: selectedSessionId });
            if (cancelled || !isOwned()) throw new StaleRuntimeOperation();
            const source = asObject(resumed);
            const preparing = source.preparing === true || asObject(source.session_state).status === "preparing";
            if (preparing) {
              dispatch({ type: "session_preparation", projectKey: selected.path, sessionId: selectedSessionId, status: "preparing" });
              pollSessionPreparation(selected.path, selectedSessionId);
            } else if (source.preparation_failed === true) {
              dispatch({ type: "session_preparation", projectKey: selected.path, sessionId: selectedSessionId, status: "failed" });
            } else {
              dispatch({ type: "session_resumed", result: resumed, preserveRuntimeState: true, preserveSessionRuntime: true, preserveTimeline: true });
              await refreshRuntimeStatus(isOwned);
            }
          }
        }, (error, isOwned) => {
          if (!cancelled && isOwned()) dispatch({ type: "runtime_error", message: safeErrorMessage(error, t("runtimeStartFailed")), state: "configuration_required" });
        });
      } else {
        dispatch({ type: "runtime_state", state: "ready" });
      }
    }).catch((error) => {
      if (!cancelled) dispatch({ type: "runtime_error", message: safeErrorMessage(error, t("preferencesUnavailable")), state: "ready" });
    });
    return () => {
      cancelled = true;
      clearPendingTurnStart();
      cancelTerminalStatusPoll();
      unsubscribe();
    };
  }, [api, beginSessionPresentation, bufferPendingTurnEvent, cancelTerminalStatusPoll, clearPendingTurnStart, enqueueRuntimeOperation, hasOwner, pendingTurnStart, pollSessionPreparation, processAgentEvent, refreshCatalog, refreshConfiguration, refreshRuntimeStatus, send, t]);

  const openProject = useCallback(async () => {
    if (!api) return;
    try {
      const path = await api.openProject();
      if (path) await openProjectPath(path);
    } catch (error) {
      dispatch({ type: "notice", text: safeErrorMessage(error, t("projectPickerUnavailable")) });
    }
  }, [api, openProjectPath]);

  const closeActiveTurn = useCallback(async (): Promise<boolean> => {
    if (!api) return false;
    if (pendingTurnStart()) return false;
    const beforeCancel = stateRef.current;
    const beforeRunId = beforeCancel.run?.run_id ?? "";
    const beforeTurnId = beforeCancel.run?.turn_id ?? "";
    const stillOwnsTurn = () => {
      const current = stateRef.current;
      if (beforeRunId || beforeTurnId) {
        return (!beforeRunId || current.run?.run_id === beforeRunId)
          && (!beforeTurnId || current.run?.turn_id === beforeTurnId);
      }
      // An active state without identity is not expected from the Application
      // DTO, but if it appears, object identity still prevents an old wait
      // from authorizing a newly started Run.
      return current.run === beforeCancel.run;
    };
    if (!beforeCancel.activeTurn && !beforeCancel.terminalStatusPending) return true;
    if (beforeCancel.terminalStatusPending && !hasTerminalStatusPoll()) {
      dispatch({ type: "notice", text: t("terminalStatusPending") });
      return false;
    }
    try {
      if (beforeCancel.activeTurn && !beforeCancel.terminalStatusPending) await send("turn.cancel", {});
    } catch {
      // The Bridge owns the terminal error. We still wait for its state before
      // asking it to replace a Session/Application.
    }
    if (!stillOwnsTurn()) return false;
    const ownedPoll = terminalStatusPollFor(beforeRunId, beforeTurnId);
    if (!ownedPoll && hasTerminalStatusPoll()) return false;
    const idle = await (ownedPoll
      ?? startTerminalStatusConvergence(beforeRunId, beforeTurnId, true, publishTerminalStatus));
    if (!stillOwnsTurn()) return false;
    if (idle.state !== "idle") {
      dispatch({ type: "notice", text: t("terminalStatusPending") });
      return false;
    }
    return true;
  }, [api, hasTerminalStatusPoll, pendingTurnStart, publishTerminalStatus, send, startTerminalStatusConvergence, t, terminalStatusPollFor]);

  const resumeSession = useCallback(async (project: ProjectState, sessionId: string) => {
    if (!api) return;
    // Clicking the already-visible row is a presentation no-op.  In
    // particular, never enqueue a lifecycle operation that waits for its own
    // active Turn to become idle.
    if (sessionId
      && stateRef.current.selectedProjectKey === project.projectKey
      && stateRef.current.selectedSessionId === sessionId
      && stateRef.current.sessionPreparation[sessionRuntimeKey(project.projectKey, sessionId)] !== "failed") return;
    await enqueueRuntimeOperation("navigation", async (isOwned) => {
      // The bridge keeps an independent runtime per durable Session. Project
      // navigation also preserves the old runtime, so switching rows/projects
      // never cancels a background Turn.
      if (!isOwned()) throw new StaleRuntimeOperation();
      if (stateRef.current.selectedProjectKey !== project.projectKey) {
        const opened = await send("project.open", { path: project.path });
        if (!isOwned()) throw new StaleRuntimeOperation();
        dispatch({ type: "project_opened", result: opened, preserveRuntimeState: true, preserveSessionRuntime: true });
        await persist("selectedProjectKey", project.projectKey);
      }
      let preparing = false;
      if (sessionId) {
        beginSessionPresentation(project.projectKey, sessionId);
        const result = await send("session.resume", { session_id: sessionId });
        if (!isOwned()) throw new StaleRuntimeOperation();
        const source = asObject(result);
        preparing = source.preparing === true || asObject(source.session_state).status === "preparing";
        if (source.preparation_failed === true) {
          dispatch({ type: "session_preparation", projectKey: project.projectKey, sessionId, status: "failed" });
        } else if (preparing) {
          dispatch({ type: "session_preparation", projectKey: project.projectKey, sessionId, status: "preparing" });
          pollSessionPreparation(project.projectKey, sessionId);
        } else {
          setLatestTurnIdentity(identityFromRun(source.run));
          cancelTerminalStatusPoll();
          dispatch({ type: "session_resumed", result, preserveRuntimeState: true, preserveSessionRuntime: true, preserveTimeline: true });
        }
        await persist("selectedSessionId", sessionId);
      } else {
        const result = await send("session.new", {});
        if (!isOwned()) throw new StaleRuntimeOperation();
        const source = asObject(result);
        const nextId = typeof source.session_id === "string" ? source.session_id : "";
        if (nextId) {
          setLatestTurnIdentity(identityFromRun(source.run));
          cancelTerminalStatusPoll();
          dispatch({ type: "session_new", sessionId: nextId, run: source.run, modelRef: typeof source.model_ref === "string" ? source.model_ref : null, preserveSessionRuntime: true });
          await persist("selectedSessionId", nextId);
        }
      }
      if (!isOwned()) throw new StaleRuntimeOperation();
      await refreshCatalog(project.projectKey, sessionId ? "session_resume" : "session_new", sessionId || undefined, true, isOwned);
      if (!sessionId || !preparing) {
        await refreshRuntimeStatus(isOwned);
      }
    }, (error, isOwned) => {
      if (isOwned()) dispatch({ type: "runtime_error", message: safeErrorMessage(error, t("sessionOpenFailed")), state: "ready" });
    });
  }, [api, beginSessionPresentation, cancelTerminalStatusPoll, enqueueRuntimeOperation, persist, pollSessionPreparation, refreshCatalog, refreshRuntimeStatus, send, setLatestTurnIdentity, t]);

  const newSession = useCallback(async () => {
    const project = stateRef.current.projects.find((item) => item.projectKey === stateRef.current.selectedProjectKey);
    if (project) await resumeSession(project, "");
  }, [resumeSession]);

  const loadOlderHistory = useCallback(() => {
    const current = stateRef.current;
    if (!current.selectedProjectKey || !current.selectedSessionId) return;
    const key = sessionRuntimeKey(current.selectedProjectKey, current.selectedSessionId);
    const history = current.sessionHistory[key];
    if (!history || history.loading || !history.hasMore || !history.nextCursor) return;
    void loadHistoryPage(current.selectedProjectKey, current.selectedSessionId, history.nextCursor, false);
  }, [loadHistoryPage]);

  const retryHistory = useCallback(() => {
    const current = stateRef.current;
    if (!current.selectedProjectKey || !current.selectedSessionId) return;
    const key = sessionRuntimeKey(current.selectedProjectKey, current.selectedSessionId);
    const history = current.sessionHistory[key];
    if (!history || history.loading || !history.error) return;
    const replace = history.records.length === 0;
    const cursor = replace ? null : history.nextCursor;
    if (!replace && !cursor) return;
    void loadHistoryPage(current.selectedProjectKey, current.selectedSessionId, cursor, replace);
  }, [loadHistoryPage]);

  const executeCommand = useCallback(async (text: string) => {
    if (!text.trim() || !api || commandInFlightRef.current) return;
    if ((hasOwner() || stateRef.current.runtimeState === "restarting")
      && (!(await waitForRuntimeUserAccess()) || hasOwner() || stateRef.current.runtimeState === "restarting")) return;
    const generation = runtimeGeneration();
    const isCurrent = () => isMounted() && runtimeGeneration() === generation && !hasOwner();
    if (!isCurrent() || commandInFlightRef.current) return;
    commandInFlightRef.current = true;
    const commandName = text.trimStart().slice(1).split(/\s+/u, 1)[0]?.toLowerCase();
    if (commandName === "compact") dispatch({ type: "compaction_started", trigger: "manual" });
    try {
      const result = await send("command.execute", { text });
      if (!isCurrent()) return;
      if (!isDesktopCommandResult(result)) {
        dispatch({ type: "notice", text: t("commandFailed") });
        return;
      }
      dispatch({ type: "command_result", result, notice: commandResultNotice(result, t) });
      const source = asObject(result);
      // `/status` is a read-only query, but its typed facts must be visible
      // even when the user previously hid the optional Runtime panel.  Open
      // only the existing panel for this response and do not persist the
      // temporary presentation choice.
      if (source.code === "status_ready" && stateRef.current.panelMode === "hidden") {
        dispatch({ type: "set_panel_mode", panelMode: narrowViewportRef.current ? "floating" : "docked" });
      }
      const action = asObject(source.ui_action);
      // Command outcomes are explicit Application boundaries.  Refresh the
      // safe Context/Compaction projection once here; completion deltas never
      // trigger status RPCs.
      // `/status` already carries the exact same safe projection as
      // `status.get`; avoid a second request that could replace the freshly
      // rendered facts with an empty/late response.
      if (source.code !== "status_ready") await refreshRuntimeStatus();
      if (!isCurrent()) return;
      if (action.type === "open_model_picker") {
        try {
          const completion = asObject(await send("command.complete", { prefix: "/model " }));
          if (!isCurrent()) return;
          const values = Array.isArray(completion.argument_candidates) ? completion.argument_candidates.filter((value): value is string => typeof value === "string") : [];
          dispatch({ type: "model_candidates", values });
        } catch {
          dispatch({ type: "model_candidates", values: [] });
        }
      }
      if (action.type === "session_changed" && typeof action.session_id === "string") {
        await persist("selectedSessionId", action.session_id);
        if (!isCurrent()) return;
        const reason: SessionOrderReason = action.restored === true ? "session_resume" : "session_new";
        await refreshCatalog(stateRef.current.selectedProjectKey ?? "", reason, action.session_id);
        if (!isCurrent()) return;
        await refreshRuntimeStatus();
      }
      if (action.type === "quit_interface") {
        if (!isCurrent()) return;
        await api.closeShell();
      }
    } catch (error) {
      if (commandName === "compact") dispatch({ type: "command_result", result: { command: "compact", status: "execution_error", code: "compact_failed", params: {}, ui_action: null }, notice: t("commandFailed") });
      if (isCurrent()) dispatch({ type: "notice", text: safeErrorMessage(error, t("commandFailed")) });
    } finally {
      commandInFlightRef.current = false;
    }
  }, [api, hasOwner, isMounted, persist, refreshCatalog, refreshRuntimeStatus, runtimeGeneration, send, t, waitForRuntimeUserAccess]);

  const submitComposer = useCallback(async (text: string) => {
    const isCompactionRunning = () => (stateRef.current.compactionStatus.state as string) === "running";
    if (!api || !isMounted() || !text.trim() || pendingTurnStart() || stateRef.current.pendingInteraction || stateRef.current.terminalStatusPending || isCompactionRunning()) return;
    const selectedProjectKey = stateRef.current.selectedProjectKey;
    const selectedSessionId = stateRef.current.selectedSessionId;
    const preparation = selectedProjectKey && selectedSessionId
      ? stateRef.current.sessionPreparation[sessionRuntimeKey(selectedProjectKey, selectedSessionId)]
      : undefined;
    // Slash commands remain available for status/recovery while a cold
    // Session is preparing. Ordinary Turns must wait for its Application/Run
    // owner to finish recovery so they cannot race a second writer.
    if (!text.trimStart().startsWith("/") && preparation !== undefined && preparation !== "ready") return;
    if ((hasOwner() || stateRef.current.runtimeState === "restarting")
      && (!(await waitForRuntimeUserAccess()) || hasOwner() || stateRef.current.runtimeState === "restarting")) return;
    if (!isMounted() || pendingTurnStart() || stateRef.current.pendingInteraction || stateRef.current.terminalStatusPending || isCompactionRunning()) return;
    if (text.trimStart().startsWith("/")) {
      await executeCommand(text.trim());
      return;
    }
    const steering = stateRef.current.activeTurn;
    const pendingStart = steering ? null : beginPendingTurnStart();
    try {
      const result = steering
        ? await send("turn.steer", { text })
        : await send("turn.start", { prompt: text });
      if (!isMounted() || (pendingStart && pendingTurnStart() !== pendingStart)) return;
      // Bridge `turn.start` returns a flat Run DTO; only `turn.steer` wraps
      // that DTO under `run`. Keep the shapes separate and require both
      // identity components before taking poll ownership.
      const acceptedRun = steering ? asObject(result).run : result;
      const acceptedIdentity = identityFromRun(acceptedRun);
      if (!hasCompleteTurnIdentity(acceptedIdentity)) {
        if (pendingStart) clearPendingTurnStart();
        dispatch({ type: "notice", text: t("turnStartFailed") });
        return;
      }
      const bufferedEvents = pendingStart ? finishPendingTurnStart(pendingStart, acceptedIdentity) : [];
      // This is the accepted Application boundary. Establish ownership
      // before Core events arrive, then retire any poll for the replaced Run;
      // an arbitrary turn_started event cannot do this job safely.
      setLatestTurnIdentity(acceptedIdentity);
      cancelTerminalStatusPoll();
      dispatch({ type: "turn_accepted", run: acceptedRun, steering, text });
      // Replaying after the accepted action preserves the exact stdout order
      // while the reducer queue applies turn_accepted before its events.
      bufferedEvents.forEach(processAgentEvent);
    } catch (error) {
      if (!isMounted() || (pendingStart && pendingTurnStart() !== pendingStart)) return;
      if (pendingStart) clearPendingTurnStart();
      dispatch({ type: "notice", text: safeErrorMessage(error, t("turnStartFailed")) });
    }
  }, [api, beginPendingTurnStart, cancelTerminalStatusPoll, clearPendingTurnStart, executeCommand, finishPendingTurnStart, hasOwner, isMounted, pendingTurnStart, processAgentEvent, send, setLatestTurnIdentity, t, waitForRuntimeUserAccess]);

  const completeCommand = useCallback(async (prefix: string) => {
    if (!api || !prefix.trimStart().startsWith("/")) return;
    if ((hasOwner() || stateRef.current.runtimeState === "restarting")
      && (!(await waitForRuntimeUserAccess()) || hasOwner() || stateRef.current.runtimeState === "restarting")) return;
    const generation = runtimeGeneration();
    const isCurrent = () => isMounted() && runtimeGeneration() === generation && !hasOwner();
    if (!isCurrent()) return;
    try {
      const result = await send("command.complete", { prefix });
      if (!isCurrent()) return;
      dispatch({ type: "command_candidates", result });
    } catch {
      if (isCurrent()) dispatch({ type: "command_candidates", result: { candidates: [], argument_candidates: [] } });
    }
  }, [api, hasOwner, isMounted, runtimeGeneration, send, waitForRuntimeUserAccess]);

  const sendInteraction = useCallback(async (response: JsonObject) => {
    const pending = stateRef.current.pendingInteraction;
    if (!api || !pending || interactionSubmitRef.current === pending.pauseId) return;
    if ((hasOwner() || stateRef.current.runtimeState === "restarting")
      && (!(await waitForRuntimeUserAccess()) || hasOwner() || stateRef.current.runtimeState === "restarting")) return;
    if (!stateRef.current.pendingInteraction || stateRef.current.pendingInteraction.pauseId !== pending.pauseId) return;
    interactionSubmitRef.current = pending.pauseId;
    dispatch({ type: "interaction_submitting", value: true });
    try {
      await send("turn.resume", { response });
    } catch (error) {
      dispatch({ type: "interaction_submitting", value: false });
      dispatch({ type: "notice", text: safeErrorMessage(error, t("interactionSubmitFailed")) });
    } finally {
      if (interactionSubmitRef.current === pending.pauseId) interactionSubmitRef.current = null;
    }
  }, [api, hasOwner, send, waitForRuntimeUserAccess]);

  const cancelTurn = useCallback(async () => {
    if (cancelInFlightRef.current) return;
    clearPendingTurnStart();
    if (!api) return;
    if ((hasOwner() || stateRef.current.runtimeState === "restarting")
      && (!(await waitForRuntimeUserAccess()) || hasOwner() || stateRef.current.runtimeState === "restarting")) return;
    if (cancelInFlightRef.current) return;
    cancelInFlightRef.current = true;
    try {
      await send("turn.cancel", {});
    } catch (error) {
      dispatch({ type: "notice", text: safeErrorMessage(error, t("turnCancelFailed")) });
    } finally {
      cancelInFlightRef.current = false;
    }
  }, [api, clearPendingTurnStart, hasOwner, send, waitForRuntimeUserAccess]);

  const pauseTurn = useCallback(async () => {
    if (!api) return;
    if ((hasOwner() || stateRef.current.runtimeState === "restarting")
      && (!(await waitForRuntimeUserAccess()) || hasOwner() || stateRef.current.runtimeState === "restarting")) return;
    try {
      await send("turn.pause", {});
    } catch (error) {
      dispatch({ type: "notice", text: safeErrorMessage(error, t("turnPauseFailed")) });
    }
  }, [api, hasOwner, send, waitForRuntimeUserAccess]);

  const setTheme = useCallback((theme: ThemePreference) => {
    if (stateRef.current.settingsSaving || settingsSaveInFlightRef.current) return;
    dispatch({ type: "set_theme", theme });
    void persist("theme", theme);
  }, [persist]);

  const setPanelMode = useCallback((panelMode: PanelModePreference) => {
    dispatch({ type: "set_panel_mode", panelMode });
    // Focus Mode is transient. Any defensive presentation callback that
    // arrives while it is active must not turn that transient state into a
    // durable panel preference.
    if (!stateRef.current.focusMode) void persist("panelMode", panelMode);
  }, [persist]);

  const setSidebarWidth = useCallback((width: number, commit = false) => {
    const bounds = typeof window === "undefined"
      ? { min: SIDEBAR_WIDTH_MIN, max: SIDEBAR_WIDTH_MAX }
      : layoutWidthBounds(window.innerWidth, stateRef.current.panelMode, stateRef.current.sidebarWidth, stateRef.current.runtimePanelWidth).sidebar;
    const next = clampLayoutWidth(width, bounds);
    dispatch({ type: "set_sidebar_width", width: next });
    if (commit && !stateRef.current.focusMode) void persist("sidebarWidth", next);
  }, [persist]);

  const setRuntimePanelWidth = useCallback((width: number, commit = false) => {
    const bounds = typeof window === "undefined"
      ? { min: RUNTIME_PANEL_WIDTH_MIN, max: RUNTIME_PANEL_WIDTH_MAX }
      : layoutWidthBounds(window.innerWidth, stateRef.current.panelMode, stateRef.current.sidebarWidth, stateRef.current.runtimePanelWidth).runtime;
    const next = clampLayoutWidth(width, bounds);
    dispatch({ type: "set_runtime_panel_width", width: next });
    if (commit && !stateRef.current.focusMode) void persist("runtimePanelWidth", next);
  }, [persist]);

  const setFocusMode = useCallback((value: boolean) => {
    dispatch({ type: "set_focus_mode", value });
  }, []);

  const restoreRuntimeToggleFocus = useCallback(() => {
    runtimeToggleRef.current?.focus();
  }, []);

  const closeRuntimeDrawer = useCallback(() => {
    setPanelMode("hidden");
    restoreRuntimeToggleFocus();
  }, [restoreRuntimeToggleFocus, setPanelMode]);

  const setProjectExpanded = useCallback((projectKey: string, expanded: boolean) => {
    // Expansion is navigation metadata only.  Accept updates from rendered
    // Project rows, but never let an arbitrary key become a trusted Project.
    if (!stateRef.current.projects.some((project) => project.projectKey === projectKey)) return;
    const expandedProjects = { ...stateRef.current.expandedProjects, [projectKey]: expanded };
    dispatch({ type: "hydrate_preferences", preferences: { expandedProjects } });
    void persist("expandedProjects", expandedProjects);
  }, [persist]);

  const toggleRuntime = useCallback(() => {
    if (stateRef.current.focusMode) return;
    const current = stateRef.current.panelMode;
    setPanelMode(current === "hidden" || (current === "docked" && narrowViewport) ? "floating" : "hidden");
  }, [narrowViewport, setPanelMode]);

  const aliasChange = useCallback((projectKey: string, alias: string) => {
    const projects = stateRef.current.projects.map((project) => project.projectKey === projectKey ? { ...project, alias } : project);
    dispatch({ type: "hydrate_preferences", preferences: { recentProjects: projectPreferences(projects), projectAliases: Object.fromEntries(projects.map((project) => [project.projectKey, project.alias])) } });
    void persist("recentProjects", projectPreferences(projects));
    void persist("projectAliases", Object.fromEntries(projects.map((project) => [project.projectKey, project.alias])));
  }, [persist]);

  const togglePin = useCallback((project: ProjectState) => {
    const { projects, pinnedSessions } = projectPinPlan(stateRef.current.projects, stateRef.current.pinnedSessions, project.projectKey);
    dispatch({ type: "hydrate_preferences", preferences: { recentProjects: projectPreferences(projects), pinnedProjectKeys: projects.filter((item) => item.pinned).map((item) => item.projectKey), pinnedSessions } });
    void persist("recentProjects", projectPreferences(projects));
    void persist("pinnedProjectKeys", projects.filter((item) => item.pinned).map((item) => item.projectKey));
    void persist("pinnedSessions", pinnedSessions);
  }, [persist]);
  const setLanguage = useCallback((language: LanguagePreference) => {
    if (stateRef.current.settingsSaving || settingsSaveInFlightRef.current) return;
    dispatch({ type: "hydrate_preferences", preferences: { language } });
    void persist("language", language);
  }, [persist]);

  const toggleSessionPin = useCallback((project: ProjectState, session: SessionSummary) => {
    // A pinned Project is the sole navigation owner of its child Sessions;
    // keep the preference invariant even if a caller bypasses the menu.
    if (project.pinned) return;
    const current = stateRef.current.pinnedSessions;
    const exists = current.some((item) => item.projectKey === project.projectKey && item.sessionId === session.session_id);
    const pinnedSessions = exists
      ? current.filter((item) => item.projectKey !== project.projectKey || item.sessionId !== session.session_id)
      : [...current, { projectKey: project.projectKey, sessionId: session.session_id }];
    dispatch({ type: "hydrate_preferences", preferences: { pinnedSessions } });
    void persist("pinnedSessions", pinnedSessions);
  }, [persist]);

  const renameSession = useCallback(async (project: ProjectState, session: SessionSummary, title: string) => {
    if (stateRef.current.activeTurn || stateRef.current.terminalStatusPending) {
      dispatch({ type: "notice", text: t("sessionRenameActive") });
      return;
    }
    const mutation = beginSessionMutation();
    if (!mutation) return;
    const { sequence, generation: mutationGeneration } = mutation;
    const runtimeGenerationAtStart = runtimeGeneration();
    try {
      if ((hasOwner() || stateRef.current.runtimeState === "restarting")
        && (!(await waitForRuntimeUserAccess()) || hasOwner() || stateRef.current.runtimeState === "restarting")) return;
      if (!isMounted() || sessionMutationInFlightRef.current !== sequence || sessionMutationGenerationRef.current !== mutationGeneration || runtimeGeneration() !== runtimeGenerationAtStart) {
        await reconcileSessionMutation(project.projectKey, sequence);
        return;
      }
      const result = await send("session.rename", { session_id: session.session_id, title });
      const current = isMounted()
        && sessionMutationInFlightRef.current === sequence
        && sessionMutationGenerationRef.current === mutationGeneration
        && runtimeGeneration() === runtimeGenerationAtStart
        && !hasOwner();
      if (current) dispatch({ type: "session_mutated", sourceProjectKey: project.projectKey, result });
      else await reconcileSessionMutation(project.projectKey, sequence);
    } catch (error) {
      await reconcileSessionMutation(project.projectKey, sequence);
      if (isMounted() && sessionMutationInFlightRef.current === sequence) {
        dispatch({ type: "notice", text: safeErrorMessage(error, t("sessionRenameFailed")) });
      }
    } finally {
      endSessionMutation(sequence);
    }
  }, [beginSessionMutation, endSessionMutation, hasOwner, isMounted, reconcileSessionMutation, runtimeGeneration, send, t, waitForRuntimeUserAccess]);

  const moveSession = useCallback(async (project: ProjectState, session: SessionSummary, target: ProjectState) => {
    if (stateRef.current.activeTurn || stateRef.current.terminalStatusPending) {
      dispatch({ type: "notice", text: t("sessionMoveActive") });
      return;
    }
    const mutation = beginSessionMutation();
    if (!mutation) return;
    const { sequence, generation: mutationGeneration } = mutation;
    const runtimeGenerationAtStart = runtimeGeneration();
    try {
      if ((hasOwner() || stateRef.current.runtimeState === "restarting")
        && (!(await waitForRuntimeUserAccess()) || hasOwner() || stateRef.current.runtimeState === "restarting")) return;
      if (!isMounted() || sessionMutationInFlightRef.current !== sequence || sessionMutationGenerationRef.current !== mutationGeneration || runtimeGeneration() !== runtimeGenerationAtStart) {
        await reconcileSessionMutation(project.projectKey, sequence);
        return;
      }
      const result = await send("session.move", { session_id: session.session_id, target_project_key: target.projectKey });
      const current = isMounted()
        && sessionMutationInFlightRef.current === sequence
        && sessionMutationGenerationRef.current === mutationGeneration
        && runtimeGeneration() === runtimeGenerationAtStart
        && !hasOwner();
      if (!current) {
        await reconcileSessionMutation(project.projectKey, sequence);
        return;
      }
      dispatch({ type: "session_mutated", sourceProjectKey: project.projectKey, result });
      const pinnedSessions = stateRef.current.pinnedSessions.map((item) => item.projectKey === project.projectKey && item.sessionId === session.session_id ? { ...item, projectKey: target.projectKey } : item);
      await persist("pinnedSessions", pinnedSessions);
      if (!isMounted() || sessionMutationInFlightRef.current !== sequence || sessionMutationGenerationRef.current !== mutationGeneration || runtimeGeneration() !== runtimeGenerationAtStart || hasOwner()) {
        await reconcileSessionMutation(project.projectKey, sequence);
        return;
      }
      if (stateRef.current.selectedProjectKey === project.projectKey) await refreshCatalog(project.projectKey);
    } catch (error) {
      await reconcileSessionMutation(project.projectKey, sequence);
      if (isMounted() && sessionMutationInFlightRef.current === sequence) {
        dispatch({ type: "notice", text: safeErrorMessage(error, t("sessionMoveFailed")) });
      }
    } finally {
      endSessionMutation(sequence);
    }
  }, [beginSessionMutation, endSessionMutation, hasOwner, isMounted, persist, reconcileSessionMutation, refreshCatalog, runtimeGeneration, send, t, waitForRuntimeUserAccess]);

  const copyText = useCallback(async (text: string) => {
    if (!api) throw new Error("Desktop API is unavailable");
    await api.copyText(text);
  }, [api]);

  const copySessionId = useCallback(async (session: SessionSummary) => {
    try {
      await copyText(session.session_id);
      dispatch({ type: "notice", text: t("copiedSessionId") });
    } catch (error) {
      dispatch({ type: "notice", text: safeErrorMessage(error, t("copySessionIdFailed")) });
    }
  }, [copyText, t]);

  const removeProject = useCallback(async (project: ProjectState) => {
    const current = stateRef.current;
    const removal = projectRemovalPlan(current.projects, current.selectedProjectKey, project.projectKey);
    const navigation = projectNavigationPreferences(removal.remaining, current.pinnedSessions, current.expandedProjects);
    if (!removal.current) {
      dispatch({ type: "hydrate_preferences", preferences: navigation });
      await persist("recentProjects", navigation.recentProjects);
      await persist("projectAliases", navigation.projectAliases);
      await persist("pinnedProjectKeys", navigation.pinnedProjectKeys);
      await persist("pinnedSessions", navigation.pinnedSessions);
      await persist("expandedProjects", navigation.expandedProjects);
      return;
    }

    await enqueueRuntimeOperation("navigation", async (isOwned) => {
      if (!(await closeActiveTurn())) throw new RuntimeOperationCancelled();
      if (!isOwned()) throw new StaleRuntimeOperation();
      const replacement = removal.replacement;
      if (replacement) {
        const opened = await send("project.open", { path: replacement.path });
        if (!isOwned()) throw new StaleRuntimeOperation();
        dispatch({ type: "project_opened", result: opened, preserveRuntimeState: true });
        dispatch({ type: "hydrate_preferences", preferences: { ...navigation, selectedProjectKey: replacement.projectKey, selectedSessionId: null } });
        await persist("recentProjects", navigation.recentProjects);
        await persist("projectAliases", navigation.projectAliases);
        await persist("pinnedProjectKeys", navigation.pinnedProjectKeys);
        await persist("pinnedSessions", navigation.pinnedSessions);
        await persist("expandedProjects", navigation.expandedProjects);
        await persist("selectedProjectKey", replacement.projectKey);
        await persist("selectedSessionId", null);
        if (!isOwned()) throw new StaleRuntimeOperation();
        await refreshCatalog(replacement.projectKey, "project_open", undefined, true, isOwned);
      } else {
        await send("runtime.shutdown", {});
        if (!isOwned()) throw new StaleRuntimeOperation();
        dispatch({ type: "workspace_cleared" });
        dispatch({ type: "hydrate_preferences", preferences: { ...navigation, selectedProjectKey: null, selectedSessionId: null } });
        await persist("recentProjects", []);
        await persist("projectAliases", {});
        await persist("pinnedProjectKeys", []);
        await persist("pinnedSessions", []);
        await persist("expandedProjects", {});
        await persist("selectedProjectKey", null);
        await persist("selectedSessionId", null);
      }
    }, (error, isOwned) => {
      if (isOwned()) dispatch({ type: "runtime_error", message: safeErrorMessage(error, t("projectRemoveFailed")), state: "ready" });
    }, removal.replacement ? "ready" : "stopped");
  }, [closeActiveTurn, enqueueRuntimeOperation, persist, refreshCatalog, send, t]);

  const openExplorer = useCallback((project: ProjectState) => {
    if (!api) return;
    void api.openProjectInExplorer(project.path).catch((error) => dispatch({ type: "notice", text: safeErrorMessage(error, t("explorerOpenFailed")) }));
  }, [api]);

  const loadSettings = useCallback(async () => {
    if (!api) {
      dispatch({ type: "settings_loaded", configuration: {} });
      return;
    }
    if (!(await waitForRuntimeLifecycleIdle()) || hasOwner()) return;
    dispatch({ type: "set_focus_mode", value: false });
    dispatch({ type: "set_view", view: "settings" });
    try {
      const result = asObject(await send("settings.get", {}));
      dispatch({ type: "settings_loaded", configuration: (asObject(result.configuration) as ConfigurationView) });
    } catch (error) {
      dispatch({ type: "settings_error", message: safeErrorMessage(error, t("configUnavailable")) });
    }
  }, [api, hasOwner, send, waitForRuntimeLifecycleIdle]);

  const saveSettings = useCallback(async (request: ConfigurationWrite) => {
    if (!api || stateRef.current.activeTurn || stateRef.current.terminalStatusPending) {
      dispatch({ type: "settings_error", message: t("finishTurnBeforeSave") });
      throw new Error(t("finishTurnBeforeSave"));
    }
    // React state updates are asynchronous; this ref closes the small window
    // in which two rapid clicks could otherwise issue duplicate durable saves.
    if (settingsSaveInFlightRef.current) throw new Error("Settings save is already in progress");
    settingsSaveInFlightRef.current = true;
    const projectKey = stateRef.current.selectedProjectKey;
    const sessionId = stateRef.current.selectedSessionId;
    dispatch({ type: "settings_saving", value: true });
    // The durable write is itself a lifecycle operation.  Its request must be
    // issued only after this generation owns the Runtime, and any following
    // project/session recovery must remain on the same serialized owner.  A
    // separate promise lets Settings clear transient secrets at the durable
    // response boundary without waiting for best-effort Runtime projection
    // recovery to finish.
    let durableSettled = false;
    let durableSucceeded = false;
    let resolveDurable!: () => void;
    let rejectDurable!: (reason?: unknown) => void;
    const durable = new Promise<void>((resolve, reject) => {
      resolveDurable = resolve;
      rejectDurable = reject;
    });
    const settleDurableSuccess = () => {
      durableSucceeded = true;
      if (durableSettled) return;
      durableSettled = true;
      resolveDurable();
    };
    const settleDurableFailure = (error: unknown, stillOwned: boolean) => {
      if (durableSettled) return;
      durableSettled = true;
      // A stale response is not retried and must not publish an old Save
      // error over a newer navigation/save owner.  It only settles this
      // caller's local promise as cancelled.
      rejectDurable(stillOwned ? error : new RuntimeOperationCancelled());
    };
    const lifecycle = enqueueRuntimeOperation("recovery", async (isOwned) => {
      try {
        const result = await send("settings.save", { request: request as unknown as JsonObject });
        // A successful durable response is safe to consume even if a newer
        // owner took over while this request was in flight.  Do not, however,
        // let that stale response publish settings_loaded or start recovery.
        settleDurableSuccess();
        if (!isMounted() || !isOwned()) return;
        dispatch({ type: "settings_loaded", configuration: asObject(result).configuration as ConfigurationView });
        if (projectKey) {
          await rebootstrapProject(
            send,
            projectKey,
            sessionId,
            (opened) => dispatch({ type: "project_opened", result: opened, preserveRuntimeState: true }),
            (resumed) => dispatch({ type: "session_resumed", result: resumed, preserveRuntimeState: true }),
            isOwned,
          );
          const statusReady = await refreshRuntimeStatus(isOwned);
          const catalogReady = await refreshCatalog(projectKey, "catalog_refresh", undefined, false, isOwned);
          if (!isOwned()) throw new StaleRuntimeOperation();
          if (!statusReady || !catalogReady) throw new Error("Runtime projections were not restored");
        }
        if (!isOwned()) throw new StaleRuntimeOperation();
        dispatch({ type: "notice", text: t("settingsSaved") });
      } catch (error) {
        settleDurableFailure(error, isOwned());
        throw error;
      }
    }, (_error, isOwned) => {
      if (!isOwned()) return;
      if (durableSucceeded) {
        dispatch({ type: "runtime_error", message: t("settingsRuntimeRecoveryFailed"), state: "failed" });
      } else {
        // settings.save failed before the durable boundary; this is not a
        // Runtime recovery failure and leaves the owner in a usable state.
        dispatch({ type: "runtime_state", state: "ready", error: null });
      }
    });
    // If the queued operation was superseded before its work began, or the
    // component unmounted, the safe lifecycle tail still has to release the
    // caller waiting at the durable boundary.
    void lifecycle.then(() => {
      settleDurableFailure(new RuntimeOperationCancelled(), false);
    }, (error) => {
      settleDurableFailure(error, false);
    });
    try {
      await durable;
    } catch (error) {
      if (isMounted() && !(error instanceof RuntimeOperationCancelled)) {
        dispatch({ type: "settings_error", message: safeErrorMessage(error, t("settingsSaveFailed")) });
      }
      throw error;
    } finally {
      settingsSaveInFlightRef.current = false;
      if (isMounted()) dispatch({ type: "settings_saving", value: false });
    }
  }, [api, enqueueRuntimeOperation, isMounted, refreshCatalog, refreshRuntimeStatus, send, t]);

  const backFromSettings = useCallback(() => {
    // Include the ref so a same-turn Back/Cancel event cannot slip through
    // before React commits settingsSaving=true for the durable request.
    if (stateRef.current.settingsSaving || settingsSaveInFlightRef.current) return;
    dispatch({ type: "set_view", view: "chat" });
  }, []);

  useEffect(() => {
    if (!state.focusMode || typeof document === "undefined") return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setFocusMode(false);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [setFocusMode, state.focusMode]);
  useLayoutEffect(() => {
    if (state.focusMode || typeof document === "undefined") return;
    if (document.activeElement === document.body) focusModeToggleRef.current?.focus();
  }, [state.focusMode]);

  const runtimeVisible = !state.focusMode && state.panelMode !== "hidden" && !(narrowViewport && state.panelMode === "docked");
  useLayoutEffect(() => {
    if (!runtimeVisible || !runtimeFocusHandoffRef.current) return;
    runtimeFocusHandoffRef.current = false;
    runtimeToggleRef.current?.focus();
  }, [runtimeVisible]);
  const runtimeToggleLabel = runtimeVisible ? t("closeRuntime") : t("openRuntime");
  const visibleHistory = state.selectedProjectKey && state.selectedSessionId
    ? state.sessionHistory[sessionRuntimeKey(state.selectedProjectKey, state.selectedSessionId)]
    : undefined;
  const visiblePreparation = state.selectedProjectKey && state.selectedSessionId
    ? state.sessionPreparation[sessionRuntimeKey(state.selectedProjectKey, state.selectedSessionId)]
    : undefined;
  const content = state.view === "settings" ? (
    <SettingsView state={state} onRevealApiKey={revealSettingsApiKey} onBack={backFromSettings} onSave={saveSettings} onThemeChange={setTheme} onLanguageChange={setLanguage} />
  ) : (
    <>
      <header className="conversation-bar">
        <div className="conversation-title">
          <span className="conversation-presence" aria-hidden="true" />
          <h1>{state.selectedSessionId ? `${t("session")} ${state.selectedSessionId.slice(0, 8)}` : t("newConversation")}</h1>
        </div>
        <div className="conversation-actions">
          {!state.focusMode && <button ref={runtimeToggleRef} type="button" className="icon-button" title={runtimeToggleLabel} aria-label={runtimeToggleLabel} aria-expanded={runtimeVisible} aria-controls={RUNTIME_PANEL_ID} onClick={toggleRuntime}><UiIcon name="panel" /><span className="sr-only">{runtimeVisible ? t("runtimePanelOpen") : t("runtimePanelClosed")}</span></button>}
          <button ref={focusModeToggleRef} type="button" className="icon-button focus-mode-toggle" title={state.focusMode ? t("exitFocusMode") : t("enterFocusMode")} aria-label={state.focusMode ? t("exitFocusMode") : t("enterFocusMode")} aria-pressed={state.focusMode} onClick={() => setFocusMode(!state.focusMode)}><UiIcon name="panel" /><span className="sr-only">{state.focusMode ? t("exitFocusMode") : t("enterFocusMode")}</span></button>
        </div>
      </header>
      <ChatTimeline
        entries={state.timeline}
        // TodoWrite is anchored to the composer; keep the timeline focused on
        // conversation and durable replay records.
        todo={[]}
        notice={state.notice}
        runtimeError={state.runtimeError}
        runtimeErrorVisible={runtimeVisible}
        onOpenSettings={state.runtimeError ? () => void loadSettings() : undefined}
        onCopyText={copyText}
        onLoadOlder={loadOlderHistory}
        onRetryOlder={retryHistory}
        historyHasMore={visibleHistory?.hasMore ?? false}
        historyLoading={visibleHistory?.loading ?? false}
        historyError={visibleHistory?.error ?? null}
        historyRevision={visibleHistory?.revision ?? 0}
        preparationStatus={visiblePreparation}
        sessionKey={`${state.selectedProjectKey ?? ""}:${state.selectedSessionId ?? ""}:${state.sessionViewRevision}`}
      />
      {state.pendingInteraction && <InteractionSurface key={interactionSurfaceKey(state.pendingInteraction)} interaction={state.pendingInteraction} onSubmit={sendInteraction} onCancel={cancelTurn} />}
      <Composer state={state} sessionPreparationStatus={visiblePreparation} onChange={(text) => { dispatch({ type: "composer_text", text }); void completeCommand(text); }} onDismissCompletion={() => dispatch({ type: "command_candidates", result: { candidates: [], argument_candidates: [] } })} onSubmit={submitComposer} onCommand={executeCommand} onPause={pauseTurn} onCancel={cancelTurn} />
    </>
  );

  const themeClass = `theme-${state.theme}`;
  const wideLayout = !narrowViewport && state.view === "chat" && !state.focusMode;
  const widthBounds = layoutWidthBounds(
    typeof window === "undefined" ? 1280 : window.innerWidth,
    state.panelMode,
    state.sidebarWidth,
    state.runtimePanelWidth,
  );
  const shellStyle = {
    "--sidebar-width": narrowViewport ? "clamp(112px, 30vw, 154px)" : `${state.sidebarWidth}px`,
    "--runtime-width": narrowViewport ? "0px" : `${state.runtimePanelWidth}px`,
  } as CSSProperties;
  return <LanguageProvider value={state.language}>
    <div className={`app-shell ${themeClass} panel-${state.panelMode}${state.focusMode ? " focus-mode" : ""}${state.view === "settings" ? " settings-shell" : ""}`} style={shellStyle}>
      {state.view === "chat" && !state.focusMode && <Sidebar projects={state.projects} selectedProjectKey={state.selectedProjectKey} selectedSessionId={state.selectedSessionId} activeTurn={state.activeTurn || state.terminalStatusPending} sessionMutationBusy={state.sessionMutationBusy} expandedProjects={state.expandedProjects} onProjectExpandedChange={setProjectExpanded} onNewSession={newSession} onOpenProject={openProject} onOpenProjectSession={(project) => void openProjectPath(project.path)} onResumeSession={(project, sessionId) => void resumeSession(project, sessionId)} onAliasChange={aliasChange} onTogglePin={togglePin} onToggleSessionPin={toggleSessionPin} onRenameSession={renameSession} onMoveSession={moveSession} onCopySessionId={copySessionId} onOpenExplorer={openExplorer} onRemoveProject={removeProject} onOpenSettings={() => void loadSettings()} />}
      <main id="workspace-main" aria-label={t("workspace")}>{content}</main>
      {state.view === "chat" && !state.focusMode && <RuntimePanel id={RUNTIME_PANEL_ID} state={state} visible={runtimeVisible} drawer={narrowViewport && state.panelMode === "floating"} onPanelModeChange={setPanelMode} onClose={closeRuntimeDrawer} onRestoreToggleFocus={restoreRuntimeToggleFocus} />}
      {wideLayout && <ResizeSeparator side="sidebar" value={state.sidebarWidth} bounds={widthBounds.sidebar} label={t("resizeSidebar")} onPreview={(value) => setSidebarWidth(value)} onCommit={(value) => setSidebarWidth(value, true)} />}
      {wideLayout && state.panelMode === "docked" && <ResizeSeparator side="runtime" value={state.runtimePanelWidth} bounds={widthBounds.runtime} label={t("resizeRuntimePanel")} onPreview={(value) => setRuntimePanelWidth(value)} onCommit={(value) => setRuntimePanelWidth(value, true)} />}
    </div>
  </LanguageProvider>;
}
