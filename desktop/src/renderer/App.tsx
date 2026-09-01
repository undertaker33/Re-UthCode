import { useCallback, useEffect, useLayoutEffect, useReducer, useRef, useState } from "react";
import { isDesktopCommandResult } from "../desktop-api";
import type { AgentEvent, DesktopApi, DesktopPreferences, JsonObject, JsonValue, LanguagePreference, PanelModePreference, ThemePreference } from "../desktop-api";
import { ChatTimeline } from "./ChatTimeline";
import { Composer } from "./Composer";
import { RuntimePanel } from "./RuntimePanel";
import { Sidebar } from "./Sidebar";
import { InteractionSurface, interactionSurfaceKey } from "./InteractionSurface";
import { SettingsView, type ConfigurationWrite } from "./SettingsView";
import { createInitialState, reduceRendererState, type RendererAction, type RendererState, type ProjectState, type SessionSummary, type ConfigurationView, type SessionOrderReason, type RuntimeStateName } from "./state";
import { UiIcon } from "./UiIcon";
import { LanguageProvider, translate } from "./i18n";

export interface AppProps {
  api?: DesktopApi;
  initialState?: RendererState;
}

const RUNTIME_PANEL_ID = "runtime-panel";

function runtimeApi(explicit?: DesktopApi): DesktopApi | undefined {
  if (explicit) return explicit;
  if (typeof window !== "undefined" && window.uthcode) return window.uthcode;
  return undefined;
}

function asObject(value: unknown): JsonObject {
  if (value && typeof value === "object" && !Array.isArray(value)) return value as JsonObject;
  return {};
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function knownIdentityMatches(currentRunId: string, currentTurnId: string, runId: string, turnId: string): boolean {
  return (!runId || !currentRunId || currentRunId === runId)
    && (!turnId || !currentTurnId || currentTurnId === turnId);
}

function hasTurnIdentity(runId: string, turnId: string): boolean {
  return Boolean(runId || turnId);
}

function hasCompleteTurnIdentity(identity: { runId: string; turnId: string }): boolean {
  return identity.runId.trim().length > 0 && identity.turnId.trim().length > 0;
}

function identityFromRun(value: unknown): { runId: string; turnId: string } {
  const run = asObject(value);
  return { runId: stringValue(run.run_id), turnId: stringValue(run.turn_id) };
}

function eventIdentity(event: AgentEvent): { runId: string; turnId: string } {
  return { runId: stringValue(event.run_id), turnId: stringValue(event.turn_id) };
}

function eventMatchesIdentity(event: AgentEvent, identity: { runId: string; turnId: string }): boolean {
  const current = eventIdentity(event);
  return current.runId === identity.runId && current.turnId === identity.turnId;
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

export type AuthoritativeIdleResult =
  | { state: "idle"; result: JsonValue }
  | { state: "cancelled" };

export interface AuthoritativeIdleOptions {
  signal: AbortSignal;
  initialDelayMs?: number;
  maxDelayMs?: number;
}

type StatusRequestOutcome =
  | { state: "result"; result: JsonValue }
  | { state: "error" }
  | { state: "cancelled" };

function requestStatusWithCancellation(api: DesktopApi, signal: AbortSignal): Promise<StatusRequestOutcome> {
  if (signal.aborted) return Promise.resolve({ state: "cancelled" });
  return new Promise((resolve) => {
    let settled = false;
    const finish = (outcome: StatusRequestOutcome) => {
      if (settled) return;
      settled = true;
      signal.removeEventListener("abort", onAbort);
      resolve(outcome);
    };
    const onAbort = () => finish({ state: "cancelled" });
    signal.addEventListener("abort", onAbort, { once: true });
    // Start through a microtask so a test double or an adapter that throws
    // before returning its Promise is handled like any other transient RPC
    // failure, without rejecting the long-lived convergence loop.
    void Promise.resolve().then(() => api.requestRuntime("status.get", {})).then(
      (result) => finish({ state: "result", result }),
      () => finish({ state: "error" }),
    );
  });
}

function delayWithCancellation(milliseconds: number, signal: AbortSignal): Promise<boolean> {
  if (signal.aborted) return Promise.resolve(false);
  return new Promise((resolve) => {
    let settled = false;
    const timer = setTimeout(() => finish(true), Math.max(0, milliseconds));
    const finish = (completed: boolean) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal.removeEventListener("abort", onAbort);
      resolve(completed);
    };
    const onAbort = () => finish(false);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

/** Keep checking the authoritative Bridge boundary until idle or cancellation. */
export async function waitForAuthoritativeIdle(api: DesktopApi, options: AuthoritativeIdleOptions): Promise<AuthoritativeIdleResult> {
  let delay = Math.max(0, options.initialDelayMs ?? 25);
  const maxDelay = Math.max(delay, options.maxDelayMs ?? 1000);
  while (!options.signal.aborted) {
    const response = await requestStatusWithCancellation(api, options.signal);
    if (response.state === "cancelled") return { state: "cancelled" };
    if (response.state === "result" && asObject(response.result).active_turn === false) return { state: "idle", result: response.result };
    if (!(await delayWithCancellation(delay, options.signal))) return { state: "cancelled" };
    delay = Math.min(maxDelay, delay > 0 ? delay * 2 : 1);
  }
  return { state: "cancelled" };
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

type RuntimeRequest = (method: Parameters<DesktopApi["requestRuntime"]>[0], params: JsonObject) => Promise<JsonValue>;
type RuntimeOwnershipCheck = () => boolean;
type RuntimeOperationKind = "startup" | "recovery" | "navigation";

/** An older Runtime lifecycle must stop before it can publish another projection. */
export class StaleRuntimeOperation extends Error {
  constructor() {
    super("Runtime operation is no longer current");
    this.name = "StaleRuntimeOperation";
  }
}

/** A user transition was declined because the active Turn is not yet idle. */
class RuntimeOperationCancelled extends Error {
  constructor() {
    super("Runtime operation was cancelled");
    this.name = "RuntimeOperationCancelled";
  }
}

interface RuntimeOperationOwner {
  generation: number;
  kind: RuntimeOperationKind;
  promise: Promise<void>;
}

interface TerminalStatusPoll {
  controller: AbortController;
  runId: string;
  turnId: string;
  promise: Promise<AuthoritativeIdleResult>;
}

interface PendingTurnStart {
  id: number;
  events: AgentEvent[];
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

/** Recreate the Application/Run owner after configuration changes. */
export async function rebootstrapProject(
  request: RuntimeRequest,
  projectPath: string,
  sessionId: string | null,
  onProjectOpened: (result: JsonValue) => void,
  onSessionResumed: (result: JsonValue) => void,
  isOwned?: RuntimeOwnershipCheck,
): Promise<void> {
  const ensureOwned = () => {
    if (isOwned && !isOwned()) throw new StaleRuntimeOperation();
  };
  ensureOwned();
  await request("runtime.shutdown", {});
  ensureOwned();
  await request("runtime.initialize", { workdir: projectPath });
  ensureOwned();
  const opened = await request("project.open", { path: projectPath });
  ensureOwned();
  onProjectOpened(opened);
  if (sessionId) {
    ensureOwned();
    const resumed = await request("session.resume", { session_id: sessionId });
    ensureOwned();
    onSessionResumed(resumed);
  }
}

export function App({ api: explicitApi, initialState }: AppProps) {
  const [state, dispatch] = useReducer(reduceRendererState, initialState ?? createInitialState());
  const stateRef = useRef(state);
  stateRef.current = state;
  const api = runtimeApi(explicitApi);
  const [narrowViewport, setNarrowViewport] = useState(() => typeof window !== "undefined" && window.innerWidth <= 680);
  const narrowViewportRef = useRef(narrowViewport);
  const runtimeToggleRef = useRef<HTMLButtonElement>(null);
  const runtimeFocusHandoffRef = useRef(false);
  const latestTurnRef = useRef({ runId: state.run?.run_id ?? "", turnId: state.run?.turn_id ?? "" });
  const pendingTurnStartRef = useRef<PendingTurnStart | null>(null);
  const pendingTurnStartSequenceRef = useRef(0);
  const mountedRef = useRef(false);
  const runtimeGenerationRef = useRef(0);
  const runtimeOwnerRef = useRef<RuntimeOperationOwner | null>(null);
  const runtimeOperationTailRef = useRef<Promise<void>>(Promise.resolve());
  const settingsSaveInFlightRef = useRef(false);
  const sessionMutationGenerationRef = useRef(0);
  const sessionMutationSequenceRef = useRef(0);
  const sessionMutationInFlightRef = useRef<number | null>(null);
  const commandInFlightRef = useRef(false);
  const interactionSubmitRef = useRef<string | null>(null);
  const cancelInFlightRef = useRef(false);
  const t = useCallback((key: Parameters<typeof translate>[1]) => translate(stateRef.current.language, key), []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      runtimeGenerationRef.current += 1;
      runtimeOwnerRef.current = null;
      pendingTurnStartRef.current = null;
    };
  }, []);

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
      setNarrowViewport(nextNarrow);
    };
    updateViewport();
    window.addEventListener("resize", updateViewport);
    return () => window.removeEventListener("resize", updateViewport);
  }, []);

  const send = useCallback(async (method: Parameters<DesktopApi["requestRuntime"]>[0], params: JsonObject = {}) => {
    if (!api) throw new Error(t("desktopApiUnavailable"));
    return api.requestRuntime(method, params);
  }, [api]);

  const persist = useCallback(async (key: "theme" | "language" | "panelMode" | "recentProjects" | "projectAliases" | "pinnedProjectKeys" | "pinnedSessions" | "expandedProjects" | "selectedProjectKey" | "selectedSessionId", value: unknown) => {
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

  const waitForRuntimeLifecycleIdle = useCallback(async (): Promise<boolean> => {
    while (mountedRef.current) {
      const owner = runtimeOwnerRef.current;
      if (!owner) return true;
      await owner.promise;
      // A newer generation may have taken ownership while the previous
      // promise was settling. Observe the newer owner instead of granting a
      // user request access in the middle of its lifecycle operation.
      if (runtimeOwnerRef.current === owner) return false;
    }
    return false;
  }, []);

  const waitForRuntimeUserAccess = useCallback(async (): Promise<boolean> => {
    return await waitForRuntimeLifecycleIdle()
      && mountedRef.current
      && runtimeOwnerRef.current === null
      && stateRef.current.runtimeState !== "restarting";
  }, [waitForRuntimeLifecycleIdle]);

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
    if (mountedRef.current) dispatch({ type: "session_mutation_busy", value: false });
  }, []);

  const refreshCatalog = useCallback(async (projectKey: string, reason: SessionOrderReason = "catalog_refresh", focusSessionId?: string, reportFailure = true, isOwned?: RuntimeOwnershipCheck): Promise<boolean> => {
    if (isOwned) {
      if (!isOwned()) return false;
    } else if (!(await waitForRuntimeLifecycleIdle()) || runtimeOwnerRef.current || stateRef.current.runtimeState === "restarting") return false;
    try {
      const result = asObject(await send("project.sessions", {}));
      if (isOwned && !isOwned()) return false;
      if (!isOwned && (runtimeOwnerRef.current || stateRef.current.runtimeState === "restarting")) return false;
      const sessions = Array.isArray(result.sessions) ? result.sessions : [];
      dispatch({ type: "catalog_refreshed", projectKey, sessions, reason, focusSessionId });
      return true;
    } catch (error) {
      if ((!isOwned || isOwned()) && reportFailure) dispatch({ type: "notice", text: safeErrorMessage(error, t("sessionCatalogUnavailable")) });
      return false;
    }
  }, [send, t, waitForRuntimeLifecycleIdle]);

  const reconcileSessionMutation = useCallback(async (projectKey: string, sequence: number): Promise<void> => {
    // ``project.sessions`` is authoritative only for the Application's
    // current project. Never apply that response to a different project after
    // navigation; the next explicit project.open will reload its catalog.
    if (!mountedRef.current || sessionMutationInFlightRef.current !== sequence) return;
    if (stateRef.current.selectedProjectKey !== projectKey) return;
    await refreshCatalog(projectKey, "catalog_refresh", undefined, false);
  }, [refreshCatalog]);

  const refreshRuntimeStatus = useCallback(async (isOwned?: RuntimeOwnershipCheck): Promise<boolean> => {
    if (isOwned) {
      if (!isOwned()) return false;
    } else if (!(await waitForRuntimeLifecycleIdle()) || runtimeOwnerRef.current || stateRef.current.runtimeState === "restarting") return false;
    try {
      const result = await send("status.get", {});
      if (isOwned && !isOwned()) return false;
      if (!isOwned && (runtimeOwnerRef.current || stateRef.current.runtimeState === "restarting")) return false;
      dispatch({ type: "status_loaded", result });
      return true;
    } catch {
      // Runtime status is supplementary safe projection; command and Run
      // authority remain usable when it is temporarily unavailable.
      return false;
    }
  }, [send, waitForRuntimeLifecycleIdle]);

  const terminalStatusPollRef = useRef<TerminalStatusPoll | null>(null);
  const cancelTerminalStatusPoll = useCallback(() => {
    const current = terminalStatusPollRef.current;
    if (!current) return;
    terminalStatusPollRef.current = null;
    current.controller.abort();
  }, []);

  const startTerminalStatusConvergence = useCallback((runId: string, turnId: string, allowLifecycleOwner = false): Promise<AuthoritativeIdleResult> => {
    if (!api) return Promise.resolve({ state: "cancelled" });
    if (!knownIdentityMatches(latestTurnRef.current.runId, latestTurnRef.current.turnId, runId, turnId)) return Promise.resolve({ state: "cancelled" });
    // A terminal event from the transport must not start a supplementary
    // status RPC while a lifecycle owner is shutting down/rebootstrapping the
    // Runtime. Navigation's own closeActiveTurn poll is the one intentional
    // exception: it is part of that owner and must converge before replacing
    // the Session/Application.
    if (runtimeOwnerRef.current && !allowLifecycleOwner) return Promise.resolve({ state: "cancelled" });
    const existing = terminalStatusPollRef.current;
    if (existing && existing.runId === runId && existing.turnId === turnId) return existing.promise;
    cancelTerminalStatusPoll();
    const controller = new AbortController();
    const poll: TerminalStatusPoll = {
      controller,
      runId,
      turnId,
      promise: Promise.resolve({ state: "cancelled" }),
    };
    poll.promise = waitForAuthoritativeIdle(api, { signal: controller.signal });
    terminalStatusPollRef.current = poll;
    void poll.promise.then(async (idle) => {
      if (controller.signal.aborted || terminalStatusPollRef.current !== poll) return;
      if (!knownIdentityMatches(latestTurnRef.current.runId, latestTurnRef.current.turnId, runId, turnId)) {
        terminalStatusPollRef.current = null;
        return;
      }
      terminalStatusPollRef.current = null;
      if (idle.state !== "idle") return;
      dispatch({ type: "status_loaded", result: idle.result });
      const current = stateRef.current;
      if (knownIdentityMatches(latestTurnRef.current.runId, latestTurnRef.current.turnId, runId, turnId) && current.selectedProjectKey) await refreshCatalog(current.selectedProjectKey, "message", current.selectedSessionId ?? undefined);
    });
    return poll.promise;
  }, [api, cancelTerminalStatusPoll, refreshCatalog]);

  const processAgentEvent = useCallback((event: AgentEvent) => {
    // Runtime lifecycle envelopes are transport-level facts. While an App
    // operation owns a restart, its explicit terminal state must not be
    // replaced by the shutdown/initialization envelopes emitted by the old
    // owner (notably `stopping`/`stopped`).
    if (event.type === "runtime_state" && runtimeOwnerRef.current) return;
    const { runId: eventRunId, turnId: eventTurnId } = eventIdentity(event);
    const latestMatches = () => {
      const latest = latestTurnRef.current;
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
      latestTurnRef.current = { runId: eventRunId, turnId: eventTurnId };
      cancelTerminalStatusPoll();
    }
    const terminal = event.type === "turn_completed" || event.type === "turn_failed" || event.type === "turn_cancelled";
    if (terminal && (!hasCompleteTurnIdentity({ runId: eventRunId, turnId: eventTurnId }) || !latestMatches())) return;
    dispatch({ type: "agent_event", event });
    if (terminal) {
      // The terminal event is published before the Bridge releases its
      // active handle. Keep one cancellable, backoff poll alive until the
      // Application status explicitly reports active_turn=false.
      void startTerminalStatusConvergence(eventRunId, eventTurnId);
    }
  }, [cancelTerminalStatusPoll, startTerminalStatusConvergence]);

  const refreshConfiguration = useCallback(async (isOwned?: RuntimeOwnershipCheck) => {
    if (isOwned) {
      if (!isOwned()) return;
    } else if (!(await waitForRuntimeLifecycleIdle()) || runtimeOwnerRef.current || stateRef.current.runtimeState === "restarting") return;
    try {
      const result = asObject(await send("settings.get", {}));
      if (isOwned && !isOwned()) return;
      if (!isOwned && (runtimeOwnerRef.current || stateRef.current.runtimeState === "restarting")) return;
      dispatch({ type: "settings_loaded", configuration: asObject(result.configuration) as ConfigurationView });
    } catch {
      // An unconfigured Runtime is expected to reject this supplementary read;
      // the explicit Settings flow still reports the actionable error.
    }
  }, [send, waitForRuntimeLifecycleIdle]);

  /**
   * Serialize lifecycle-changing Runtime calls inside this App instance.
   * Each newer save/navigation owns a new generation; an older operation may
   * finish its already-issued RPC, but it cannot issue the next lifecycle
   * call or publish a late reducer action.  Keeping the tail local avoids a
   * second cross-cutting manager while still preventing Runtime races.
   */
  const enqueueRuntimeOperation = useCallback((
    kind: RuntimeOperationKind,
    work: (isOwned: RuntimeOwnershipCheck) => Promise<void>,
    onFailure: (error: unknown, isOwned: RuntimeOwnershipCheck) => void | Promise<void>,
    terminalState: RuntimeStateName = "ready",
  ): Promise<void> => {
    const generation = runtimeGenerationRef.current + 1;
    runtimeGenerationRef.current = generation;
    dispatch({ type: "runtime_state", state: "restarting", error: null });
    const predecessor = runtimeOperationTailRef.current;
    const owner: RuntimeOperationOwner = { generation, kind, promise: Promise.resolve() };
    const isOwned: RuntimeOwnershipCheck = () => mountedRef.current
      && runtimeGenerationRef.current === generation
      && runtimeOwnerRef.current === owner;
    let failed = false;
    const operation = predecessor.then(async () => {
      if (!isOwned()) return;
      try {
        await work(isOwned);
      } catch (error) {
        if (!isOwned() || error instanceof StaleRuntimeOperation || error instanceof RuntimeOperationCancelled) return;
        failed = true;
        try {
          await onFailure(error, isOwned);
        } catch {
          // A failure presenter must not break the serialized Runtime tail.
        }
      }
    }).finally(() => {
      // Completion belongs to the exact owner that started this operation.
      // A stale operation must never clear a newer generation's owner.
      if (runtimeGenerationRef.current !== generation
        || runtimeOwnerRef.current !== owner
        || runtimeOwnerRef.current?.promise !== owner.promise) return;
      if (!failed) dispatch({ type: "runtime_state", state: terminalState, error: null });
      runtimeOwnerRef.current = null;
    });
    const safeOperation = operation.catch(() => {
      // Keep later lifecycle operations runnable even if an unexpected
      // presenter/adapter error escapes the guarded work above.
    });
    owner.promise = safeOperation;
    runtimeOwnerRef.current = owner;
    runtimeOperationTailRef.current = safeOperation;
    return safeOperation;
  }, []);

  const revealSettingsApiKey = useCallback(async (providerId: string): Promise<string | null> => {
    if (!(await waitForRuntimeUserAccess()) || runtimeOwnerRef.current || stateRef.current.runtimeState === "restarting") return null;
    const result = asObject(await send("settings.reveal_api_key", { provider_profile_id: providerId }));
    const value = result.api_key;
    if (value === null || typeof value === "string") return value;
    throw new Error("Invalid API key reveal response");
  }, [send, waitForRuntimeUserAccess]);

  const openProjectPath = useCallback(async (path: string) => {
    if (!api) return;
    await enqueueRuntimeOperation("navigation", async (isOwned) => {
      const result = await send("project.open", { path });
      if (!isOwned()) throw new StaleRuntimeOperation();
      dispatch({ type: "project_opened", result, preserveRuntimeState: true });
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
      const pendingStart = pendingTurnStartRef.current;
      const pendingEventIdentity = eventIdentity(event);
      if (pendingStart && hasTurnIdentity(pendingEventIdentity.runId, pendingEventIdentity.turnId)) {
        // Python Runtime can resolve turn.start and synchronously deliver the
        // following stdout events before the Promise continuation records the
        // accepted flat identity. Hold scoped events until that boundary is
        // known; unrelated identities are filtered when the response arrives.
        pendingStart.events.push(event);
        return;
      }
      processAgentEvent(event);
    });
    void Promise.all([
      api.readPreference("theme"),
      api.readPreference("language"),
      api.readPreference("panelMode"),
      api.readPreference("recentProjects"),
      api.readPreference("projectAliases"),
      api.readPreference("pinnedProjectKeys"),
      api.readPreference("pinnedSessions"),
      api.readPreference("expandedProjects"),
      api.readPreference("selectedProjectKey"),
      api.readPreference("selectedSessionId"),
    ]).then(([theme, language, panelMode, recentProjects, projectAliases, pinnedProjectKeys, pinnedSessions, expandedProjects, selectedProjectKey, selectedSessionId]) => {
      // A user save/navigation may have become the current lifecycle owner
      // while Desktop preferences were still loading. Do not let this late
      // bootstrap callback supersede that newer generation.
      if (cancelled || runtimeOwnerRef.current) return;
      dispatch({ type: "hydrate_preferences", preferences: { theme, language, panelMode, recentProjects, projectAliases, pinnedProjectKeys, pinnedSessions, expandedProjects, selectedProjectKey, selectedSessionId } });
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
            const resumed = await send("session.resume", { session_id: selectedSessionId });
            if (cancelled || !isOwned()) throw new StaleRuntimeOperation();
            dispatch({ type: "session_resumed", result: resumed, preserveRuntimeState: true });
            await refreshRuntimeStatus(isOwned);
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
      pendingTurnStartRef.current = null;
      cancelTerminalStatusPoll();
      unsubscribe();
    };
  }, [api, cancelTerminalStatusPoll, enqueueRuntimeOperation, processAgentEvent, refreshCatalog, refreshConfiguration, refreshRuntimeStatus, send, t]);

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
    if (pendingTurnStartRef.current) return false;
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
    if (beforeCancel.terminalStatusPending && !terminalStatusPollRef.current) {
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
    const currentPoll = terminalStatusPollRef.current;
    const ownedPoll = currentPoll
      && currentPoll.runId === beforeRunId
      && currentPoll.turnId === beforeTurnId
      ? currentPoll
      : null;
    if (!ownedPoll && currentPoll) return false;
    const idle = await (ownedPoll?.promise
      ?? startTerminalStatusConvergence(beforeRunId, beforeTurnId, true));
    if (!stillOwnsTurn()) return false;
    if (idle.state !== "idle") {
      dispatch({ type: "notice", text: t("terminalStatusPending") });
      return false;
    }
    return true;
  }, [api, send, startTerminalStatusConvergence, t]);

  const resumeSession = useCallback(async (project: ProjectState, sessionId: string) => {
    if (!api) return;
    await enqueueRuntimeOperation("navigation", async (isOwned) => {
      if (!(await closeActiveTurn())) throw new RuntimeOperationCancelled();
      if (!isOwned()) throw new StaleRuntimeOperation();
      if (stateRef.current.selectedProjectKey !== project.projectKey) {
        const opened = await send("project.open", { path: project.path });
        if (!isOwned()) throw new StaleRuntimeOperation();
        dispatch({ type: "project_opened", result: opened, preserveRuntimeState: true });
        await persist("selectedProjectKey", project.projectKey);
      }
      if (sessionId) {
        const result = await send("session.resume", { session_id: sessionId });
        if (!isOwned()) throw new StaleRuntimeOperation();
        dispatch({ type: "session_resumed", result, preserveRuntimeState: true });
        await persist("selectedSessionId", sessionId);
      } else {
        const result = await send("session.new", {});
        if (!isOwned()) throw new StaleRuntimeOperation();
        const source = asObject(result);
        const nextId = typeof source.session_id === "string" ? source.session_id : "";
        if (nextId) {
          dispatch({ type: "session_new", sessionId: nextId, run: source.run });
          await persist("selectedSessionId", nextId);
        }
      }
      if (!isOwned()) throw new StaleRuntimeOperation();
      await refreshCatalog(project.projectKey, sessionId ? "session_resume" : "session_new", sessionId || undefined, true, isOwned);
      await refreshRuntimeStatus(isOwned);
    }, (error, isOwned) => {
      if (isOwned()) dispatch({ type: "runtime_error", message: safeErrorMessage(error, t("sessionOpenFailed")), state: "ready" });
    });
  }, [api, closeActiveTurn, enqueueRuntimeOperation, persist, refreshCatalog, refreshRuntimeStatus, send, t]);

  const newSession = useCallback(async () => {
    const project = stateRef.current.projects.find((item) => item.projectKey === stateRef.current.selectedProjectKey);
    if (project) await resumeSession(project, "");
  }, [resumeSession]);

  const executeCommand = useCallback(async (text: string) => {
    if (!text.trim() || !api || commandInFlightRef.current) return;
    if ((runtimeOwnerRef.current || stateRef.current.runtimeState === "restarting")
      && (!(await waitForRuntimeUserAccess()) || runtimeOwnerRef.current || stateRef.current.runtimeState === "restarting")) return;
    const generation = runtimeGenerationRef.current;
    const isCurrent = () => mountedRef.current && runtimeGenerationRef.current === generation && runtimeOwnerRef.current === null;
    if (!isCurrent() || commandInFlightRef.current) return;
    commandInFlightRef.current = true;
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
      if (isCurrent()) dispatch({ type: "notice", text: safeErrorMessage(error, t("commandFailed")) });
    } finally {
      commandInFlightRef.current = false;
    }
  }, [api, persist, refreshCatalog, refreshRuntimeStatus, send, waitForRuntimeUserAccess]);

  const submitComposer = useCallback(async (text: string) => {
    const isCompactionRunning = () => (stateRef.current.compactionStatus.state as string) === "running";
    if (!api || !mountedRef.current || !text.trim() || pendingTurnStartRef.current || stateRef.current.pendingInteraction || stateRef.current.terminalStatusPending || isCompactionRunning()) return;
    if ((runtimeOwnerRef.current || stateRef.current.runtimeState === "restarting")
      && (!(await waitForRuntimeUserAccess()) || runtimeOwnerRef.current || stateRef.current.runtimeState === "restarting")) return;
    if (!mountedRef.current || pendingTurnStartRef.current || stateRef.current.pendingInteraction || stateRef.current.terminalStatusPending || isCompactionRunning()) return;
    if (text.trimStart().startsWith("/")) {
      await executeCommand(text.trim());
      return;
    }
    const steering = stateRef.current.activeTurn;
    const pendingStart = steering ? null : { id: pendingTurnStartSequenceRef.current += 1, events: [] as AgentEvent[] };
    if (pendingStart) pendingTurnStartRef.current = pendingStart;
    try {
      const result = steering
        ? await send("turn.steer", { text })
        : await send("turn.start", { prompt: text });
      if (!mountedRef.current || (pendingStart && pendingTurnStartRef.current !== pendingStart)) return;
      // Bridge `turn.start` returns a flat Run DTO; only `turn.steer` wraps
      // that DTO under `run`. Keep the shapes separate and require both
      // identity components before taking poll ownership.
      const acceptedRun = steering ? asObject(result).run : result;
      const acceptedIdentity = identityFromRun(acceptedRun);
      if (!hasCompleteTurnIdentity(acceptedIdentity)) {
        if (pendingStart) pendingTurnStartRef.current = null;
        dispatch({ type: "notice", text: t("turnStartFailed") });
        return;
      }
      const bufferedEvents = pendingStart?.events.filter((event) => eventMatchesIdentity(event, acceptedIdentity)) ?? [];
      if (pendingStart) pendingTurnStartRef.current = null;
      // This is the accepted Application boundary. Establish ownership
      // before Core events arrive, then retire any poll for the replaced Run;
      // an arbitrary turn_started event cannot do this job safely.
      latestTurnRef.current = acceptedIdentity;
      cancelTerminalStatusPoll();
      dispatch({ type: "turn_accepted", run: acceptedRun, steering, text });
      // Replaying after the accepted action preserves the exact stdout order
      // while the reducer queue applies turn_accepted before its events.
      bufferedEvents.forEach(processAgentEvent);
    } catch (error) {
      if (!mountedRef.current || (pendingStart && pendingTurnStartRef.current !== pendingStart)) return;
      if (pendingStart) pendingTurnStartRef.current = null;
      dispatch({ type: "notice", text: safeErrorMessage(error, t("turnStartFailed")) });
    }
  }, [api, cancelTerminalStatusPoll, executeCommand, processAgentEvent, send, t, waitForRuntimeUserAccess]);

  const completeCommand = useCallback(async (prefix: string) => {
    if (!api || !prefix.trimStart().startsWith("/")) return;
    if ((runtimeOwnerRef.current || stateRef.current.runtimeState === "restarting")
      && (!(await waitForRuntimeUserAccess()) || runtimeOwnerRef.current || stateRef.current.runtimeState === "restarting")) return;
    const generation = runtimeGenerationRef.current;
    const isCurrent = () => mountedRef.current && runtimeGenerationRef.current === generation && runtimeOwnerRef.current === null;
    if (!isCurrent()) return;
    try {
      const result = await send("command.complete", { prefix });
      if (!isCurrent()) return;
      dispatch({ type: "command_candidates", result });
    } catch {
      if (isCurrent()) dispatch({ type: "command_candidates", result: { candidates: [], argument_candidates: [] } });
    }
  }, [api, send, waitForRuntimeUserAccess]);

  const sendInteraction = useCallback(async (response: JsonObject) => {
    const pending = stateRef.current.pendingInteraction;
    if (!api || !pending || interactionSubmitRef.current === pending.pauseId) return;
    if ((runtimeOwnerRef.current || stateRef.current.runtimeState === "restarting")
      && (!(await waitForRuntimeUserAccess()) || runtimeOwnerRef.current || stateRef.current.runtimeState === "restarting")) return;
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
  }, [api, send, waitForRuntimeUserAccess]);

  const cancelTurn = useCallback(async () => {
    if (cancelInFlightRef.current) return;
    pendingTurnStartRef.current = null;
    if (!api) return;
    if ((runtimeOwnerRef.current || stateRef.current.runtimeState === "restarting")
      && (!(await waitForRuntimeUserAccess()) || runtimeOwnerRef.current || stateRef.current.runtimeState === "restarting")) return;
    if (cancelInFlightRef.current) return;
    cancelInFlightRef.current = true;
    try {
      await send("turn.cancel", {});
    } catch (error) {
      dispatch({ type: "notice", text: safeErrorMessage(error, t("turnCancelFailed")) });
    } finally {
      cancelInFlightRef.current = false;
    }
  }, [api, send, waitForRuntimeUserAccess]);

  const pauseTurn = useCallback(async () => {
    if (!api) return;
    if ((runtimeOwnerRef.current || stateRef.current.runtimeState === "restarting")
      && (!(await waitForRuntimeUserAccess()) || runtimeOwnerRef.current || stateRef.current.runtimeState === "restarting")) return;
    try {
      await send("turn.pause", {});
    } catch (error) {
      dispatch({ type: "notice", text: safeErrorMessage(error, t("turnPauseFailed")) });
    }
  }, [api, send, waitForRuntimeUserAccess]);

  const setTheme = useCallback((theme: ThemePreference) => {
    if (stateRef.current.settingsSaving || settingsSaveInFlightRef.current) return;
    dispatch({ type: "set_theme", theme });
    void persist("theme", theme);
  }, [persist]);

  const setPanelMode = useCallback((panelMode: PanelModePreference) => {
    dispatch({ type: "set_panel_mode", panelMode });
    void persist("panelMode", panelMode);
  }, [persist]);

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
    const runtimeGeneration = runtimeGenerationRef.current;
    try {
      if ((runtimeOwnerRef.current || stateRef.current.runtimeState === "restarting")
        && (!(await waitForRuntimeUserAccess()) || runtimeOwnerRef.current || stateRef.current.runtimeState === "restarting")) return;
      if (!mountedRef.current || sessionMutationInFlightRef.current !== sequence || sessionMutationGenerationRef.current !== mutationGeneration || runtimeGenerationRef.current !== runtimeGeneration) {
        await reconcileSessionMutation(project.projectKey, sequence);
        return;
      }
      const result = await send("session.rename", { session_id: session.session_id, title });
      const current = mountedRef.current
        && sessionMutationInFlightRef.current === sequence
        && sessionMutationGenerationRef.current === mutationGeneration
        && runtimeGenerationRef.current === runtimeGeneration
        && runtimeOwnerRef.current === null;
      if (current) dispatch({ type: "session_mutated", sourceProjectKey: project.projectKey, result });
      else await reconcileSessionMutation(project.projectKey, sequence);
    } catch (error) {
      await reconcileSessionMutation(project.projectKey, sequence);
      if (mountedRef.current && sessionMutationInFlightRef.current === sequence) {
        dispatch({ type: "notice", text: safeErrorMessage(error, t("sessionRenameFailed")) });
      }
    } finally {
      endSessionMutation(sequence);
    }
  }, [beginSessionMutation, endSessionMutation, reconcileSessionMutation, send, t, waitForRuntimeUserAccess]);

  const moveSession = useCallback(async (project: ProjectState, session: SessionSummary, target: ProjectState) => {
    if (stateRef.current.activeTurn || stateRef.current.terminalStatusPending) {
      dispatch({ type: "notice", text: t("sessionMoveActive") });
      return;
    }
    const mutation = beginSessionMutation();
    if (!mutation) return;
    const { sequence, generation: mutationGeneration } = mutation;
    const runtimeGeneration = runtimeGenerationRef.current;
    try {
      if ((runtimeOwnerRef.current || stateRef.current.runtimeState === "restarting")
        && (!(await waitForRuntimeUserAccess()) || runtimeOwnerRef.current || stateRef.current.runtimeState === "restarting")) return;
      if (!mountedRef.current || sessionMutationInFlightRef.current !== sequence || sessionMutationGenerationRef.current !== mutationGeneration || runtimeGenerationRef.current !== runtimeGeneration) {
        await reconcileSessionMutation(project.projectKey, sequence);
        return;
      }
      const result = await send("session.move", { session_id: session.session_id, target_project_key: target.projectKey });
      const current = mountedRef.current
        && sessionMutationInFlightRef.current === sequence
        && sessionMutationGenerationRef.current === mutationGeneration
        && runtimeGenerationRef.current === runtimeGeneration
        && runtimeOwnerRef.current === null;
      if (!current) {
        await reconcileSessionMutation(project.projectKey, sequence);
        return;
      }
      dispatch({ type: "session_mutated", sourceProjectKey: project.projectKey, result });
      const pinnedSessions = stateRef.current.pinnedSessions.map((item) => item.projectKey === project.projectKey && item.sessionId === session.session_id ? { ...item, projectKey: target.projectKey } : item);
      await persist("pinnedSessions", pinnedSessions);
      if (!mountedRef.current || sessionMutationInFlightRef.current !== sequence || sessionMutationGenerationRef.current !== mutationGeneration || runtimeGenerationRef.current !== runtimeGeneration || runtimeOwnerRef.current) {
        await reconcileSessionMutation(project.projectKey, sequence);
        return;
      }
      if (stateRef.current.selectedProjectKey === project.projectKey) await refreshCatalog(project.projectKey);
    } catch (error) {
      await reconcileSessionMutation(project.projectKey, sequence);
      if (mountedRef.current && sessionMutationInFlightRef.current === sequence) {
        dispatch({ type: "notice", text: safeErrorMessage(error, t("sessionMoveFailed")) });
      }
    } finally {
      endSessionMutation(sequence);
    }
  }, [beginSessionMutation, endSessionMutation, persist, reconcileSessionMutation, refreshCatalog, send, t, waitForRuntimeUserAccess]);

  const copySessionId = useCallback(async (session: SessionSummary) => {
    if (!api) return;
    try {
      await api.copySessionId(session.session_id);
      dispatch({ type: "notice", text: t("copiedSessionId") });
    } catch (error) {
      dispatch({ type: "notice", text: safeErrorMessage(error, t("copySessionIdFailed")) });
    }
  }, [api]);

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
    if (!(await waitForRuntimeLifecycleIdle()) || runtimeOwnerRef.current) return;
    dispatch({ type: "set_view", view: "settings" });
    try {
      const result = asObject(await send("settings.get", {}));
      dispatch({ type: "settings_loaded", configuration: (asObject(result.configuration) as ConfigurationView) });
    } catch (error) {
      dispatch({ type: "settings_error", message: safeErrorMessage(error, t("configUnavailable")) });
    }
  }, [api, send, waitForRuntimeLifecycleIdle]);

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
        if (!mountedRef.current || !isOwned()) return;
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
      if (mountedRef.current && !(error instanceof RuntimeOperationCancelled)) {
        dispatch({ type: "settings_error", message: safeErrorMessage(error, t("settingsSaveFailed")) });
      }
      throw error;
    } finally {
      settingsSaveInFlightRef.current = false;
      if (mountedRef.current) dispatch({ type: "settings_saving", value: false });
    }
  }, [api, enqueueRuntimeOperation, refreshCatalog, refreshRuntimeStatus, send, t]);

  const backFromSettings = useCallback(() => {
    // Include the ref so a same-turn Back/Cancel event cannot slip through
    // before React commits settingsSaving=true for the durable request.
    if (stateRef.current.settingsSaving || settingsSaveInFlightRef.current) return;
    dispatch({ type: "set_view", view: "chat" });
  }, []);

  const runtimeVisible = state.panelMode !== "hidden" && !(narrowViewport && state.panelMode === "docked");
  useLayoutEffect(() => {
    if (!runtimeVisible || !runtimeFocusHandoffRef.current) return;
    runtimeFocusHandoffRef.current = false;
    runtimeToggleRef.current?.focus();
  }, [runtimeVisible]);
  const runtimeToggleLabel = runtimeVisible ? t("closeRuntime") : t("openRuntime");
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
          <button ref={runtimeToggleRef} type="button" className="icon-button" title={runtimeToggleLabel} aria-label={runtimeToggleLabel} aria-expanded={runtimeVisible} aria-controls={RUNTIME_PANEL_ID} onClick={toggleRuntime}><UiIcon name="panel" /><span className="sr-only">{runtimeVisible ? t("runtimePanelOpen") : t("runtimePanelClosed")}</span></button>
        </div>
      </header>
      <ChatTimeline
        entries={state.timeline}
        todo={state.todo}
        notice={state.notice}
        runtimeError={state.runtimeError}
        runtimeErrorVisible={runtimeVisible}
        onOpenSettings={state.runtimeError ? () => void loadSettings() : undefined}
        sessionKey={`${state.selectedProjectKey ?? ""}:${state.selectedSessionId ?? ""}:${state.sessionViewRevision}`}
      />
      {state.pendingInteraction && <InteractionSurface key={interactionSurfaceKey(state.pendingInteraction)} interaction={state.pendingInteraction} onSubmit={sendInteraction} onCancel={cancelTurn} />}
      <Composer state={state} onChange={(text) => { dispatch({ type: "composer_text", text }); void completeCommand(text); }} onDismissCompletion={() => dispatch({ type: "command_candidates", result: { candidates: [], argument_candidates: [] } })} onSubmit={submitComposer} onCommand={executeCommand} onPause={pauseTurn} onCancel={cancelTurn} />
    </>
  );

  const themeClass = `theme-${state.theme}`;
  return <LanguageProvider value={state.language}>
    <div className={`app-shell ${themeClass} panel-${state.panelMode}${state.view === "settings" ? " settings-shell" : ""}`}>
      {state.view === "chat" && <Sidebar projects={state.projects} selectedProjectKey={state.selectedProjectKey} selectedSessionId={state.selectedSessionId} activeTurn={state.activeTurn || state.terminalStatusPending} sessionMutationBusy={state.sessionMutationBusy} expandedProjects={state.expandedProjects} onProjectExpandedChange={setProjectExpanded} onNewSession={newSession} onOpenProject={openProject} onOpenProjectSession={(project) => void openProjectPath(project.path)} onResumeSession={(project, sessionId) => void resumeSession(project, sessionId)} onAliasChange={aliasChange} onTogglePin={togglePin} onToggleSessionPin={toggleSessionPin} onRenameSession={renameSession} onMoveSession={moveSession} onCopySessionId={copySessionId} onOpenExplorer={openExplorer} onRemoveProject={removeProject} onOpenSettings={() => void loadSettings()} />}
      <main aria-label={t("workspace")}>{content}</main>
      {state.view === "chat" && <RuntimePanel id={RUNTIME_PANEL_ID} state={state} visible={runtimeVisible} drawer={narrowViewport && state.panelMode === "floating"} onPanelModeChange={setPanelMode} onClose={closeRuntimeDrawer} onRestoreToggleFocus={restoreRuntimeToggleFocus} />}
    </div>
  </LanguageProvider>;
}
