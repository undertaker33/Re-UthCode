import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import type { AgentEvent, DesktopApi, DesktopPreferences, JsonObject, JsonValue, LanguagePreference, PanelModePreference, ThemePreference } from "../desktop-api";
import { ChatTimeline } from "./ChatTimeline";
import { Composer } from "./Composer";
import { RuntimePanel } from "./RuntimePanel";
import { Sidebar } from "./Sidebar";
import { InteractionSurface, interactionSurfaceKey } from "./InteractionSurface";
import { SettingsView, type ConfigurationWrite } from "./SettingsView";
import { createInitialState, reduceRendererState, type RendererAction, type RendererState, type ProjectState, type SessionSummary, type ConfigurationView, type SessionOrderReason } from "./state";
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

function errorMessage(error: unknown, fallback: string): string {
  if (error && typeof error === "object") {
    const source = error as { message?: unknown; error?: { message?: unknown } };
    if (typeof source.error?.message === "string") return source.error.message;
    if (typeof source.message === "string") return source.message;
  }
  return fallback;
}

export type IdleWaitResult =
  | { state: "idle"; result: JsonValue }
  | { state: "unavailable" | "timeout" };

export interface IdleWaitOptions {
  pollIntervalMs?: number;
  maxAttempts?: number;
  signal?: AbortSignal;
}

/** Wait only for the Bridge's explicit active_turn=false authority. */
export async function waitForIdle(api: DesktopApi, options: IdleWaitOptions = {}): Promise<IdleWaitResult> {
  const pollIntervalMs = options.pollIntervalMs ?? 25;
  const maxAttempts = options.maxAttempts ?? 20;
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    if (options.signal?.aborted) return { state: "unavailable" };
    try {
      const result = await api.requestRuntime("status.get", {});
      const value = asObject(result);
      if (value.active_turn === false) return { state: "idle", result };
      if (value.active_turn !== true) return { state: "unavailable" };
    } catch {
      return { state: "unavailable" };
    }
    if (attempt + 1 < maxAttempts) await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
  }
  return { state: "timeout" };
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
): Promise<void> {
  await request("runtime.shutdown", {});
  await request("runtime.initialize", { workdir: projectPath });
  const opened = await request("project.open", { path: projectPath });
  onProjectOpened(opened);
  if (sessionId) {
    const resumed = await request("session.resume", { session_id: sessionId });
    onSessionResumed(resumed);
  }
}

export function App({ api: explicitApi, initialState }: AppProps) {
  const [state, dispatch] = useReducer(reduceRendererState, initialState ?? createInitialState());
  const stateRef = useRef(state);
  stateRef.current = state;
  const api = runtimeApi(explicitApi);
  const [narrowViewport, setNarrowViewport] = useState(() => typeof window !== "undefined" && window.innerWidth <= 680);
  const runtimeToggleRef = useRef<HTMLButtonElement>(null);
  const latestTurnRef = useRef({ runId: state.run?.run_id ?? "", turnId: state.run?.turn_id ?? "" });
  const pendingTurnStartRef = useRef<PendingTurnStart | null>(null);
  const pendingTurnStartSequenceRef = useRef(0);
  const mountedRef = useRef(false);
  const t = useCallback((key: Parameters<typeof translate>[1]) => translate(stateRef.current.language, key), []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      pendingTurnStartRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const updateViewport = () => setNarrowViewport(window.innerWidth <= 680);
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
    } catch {
      // Desktop metadata is advisory; a temporary preference failure must not
      // replace the Application's authoritative state.
    }
  }, [api]);

  const refreshCatalog = useCallback(async (projectKey: string, reason: SessionOrderReason = "catalog_refresh", focusSessionId?: string) => {
    try {
      const result = asObject(await send("project.sessions", {}));
      const sessions = Array.isArray(result.sessions) ? result.sessions : [];
      dispatch({ type: "catalog_refreshed", projectKey, sessions, reason, focusSessionId });
    } catch (error) {
      dispatch({ type: "notice", text: errorMessage(error, t("sessionCatalogUnavailable")) });
    }
  }, [send]);

  const refreshRuntimeStatus = useCallback(async (): Promise<boolean> => {
    try {
      dispatch({ type: "status_loaded", result: await send("status.get", {}) });
      return true;
    } catch {
      // Runtime status is supplementary safe projection; command and Run
      // authority remain usable when it is temporarily unavailable.
      return false;
    }
  }, [send]);

  const terminalStatusPollRef = useRef<TerminalStatusPoll | null>(null);
  const cancelTerminalStatusPoll = useCallback(() => {
    const current = terminalStatusPollRef.current;
    if (!current) return;
    terminalStatusPollRef.current = null;
    current.controller.abort();
  }, []);

  const startTerminalStatusConvergence = useCallback((runId: string, turnId: string): Promise<AuthoritativeIdleResult> => {
    if (!api) return Promise.resolve({ state: "cancelled" });
    if (!knownIdentityMatches(latestTurnRef.current.runId, latestTurnRef.current.turnId, runId, turnId)) return Promise.resolve({ state: "cancelled" });
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
      if (!latestMatches()) return;
      latestTurnRef.current = { runId: eventRunId, turnId: eventTurnId };
      cancelTerminalStatusPoll();
    }
    const terminal = event.type === "turn_completed" || event.type === "turn_failed" || event.type === "turn_cancelled";
    if (terminal && !latestMatches()) return;
    dispatch({ type: "agent_event", event });
    if (terminal) {
      // The terminal event is published before the Bridge releases its
      // active handle. Keep one cancellable, backoff poll alive until the
      // Application status explicitly reports active_turn=false.
      void startTerminalStatusConvergence(eventRunId, eventTurnId);
    }
  }, [cancelTerminalStatusPoll, startTerminalStatusConvergence]);

  const refreshConfiguration = useCallback(async () => {
    try {
      const result = asObject(await send("settings.get", {}));
      dispatch({ type: "settings_loaded", configuration: asObject(result.configuration) as ConfigurationView });
    } catch {
      // An unconfigured Runtime is expected to reject this supplementary read;
      // the explicit Settings flow still reports the actionable error.
    }
  }, [send]);

  const openProjectPath = useCallback(async (path: string) => {
    try {
      const result = await send("project.open", { path });
      dispatch({ type: "project_opened", result });
      const next = stateRef.current.projects.some((project) => project.projectKey === path)
        ? stateRef.current.projects
        : [...stateRef.current.projects, { path, projectKey: path, alias: path.split(/[\\/]/u).filter(Boolean).pop() || path, pinned: false, sessions: [], catalogFresh: true }];
      await persist("recentProjects", projectPreferences(next));
      await persist("selectedProjectKey", path);
      await refreshCatalog(path);
      await refreshRuntimeStatus();
      await refreshConfiguration();
    } catch (error) {
      const existing = stateRef.current.projects.find((project) => project.projectKey === path);
      const project = existing ?? { path, projectKey: path, alias: path.split(/[\\/]/u).filter(Boolean).pop() || path, pinned: false, sessions: [], catalogFresh: false };
      const projects = existing ? stateRef.current.projects : [...stateRef.current.projects, project];
      dispatch({ type: "hydrate_preferences", preferences: { recentProjects: projectPreferences(projects), selectedProjectKey: path, selectedSessionId: null } });
      await persist("recentProjects", projectPreferences(projects));
      await persist("selectedProjectKey", path);
      dispatch({ type: "runtime_error", message: errorMessage(error, t("projectOpenFailed")), state: "configuration_required" });
      dispatch({ type: "set_view", view: "settings" });
    }
  }, [persist, refreshCatalog, refreshConfiguration, send]);

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
      if (cancelled) return;
      dispatch({ type: "hydrate_preferences", preferences: { theme, language, panelMode, recentProjects, projectAliases, pinnedProjectKeys, pinnedSessions, expandedProjects, selectedProjectKey, selectedSessionId } });
      const selected = (recentProjects as DesktopPreferences["recentProjects"]).find((project) => project.path === selectedProjectKey);
      if (selected) {
        void send("runtime.initialize", { workdir: selected.path }).then((result) => {
          if (cancelled) return;
          dispatch({ type: "runtime_initialized", result });
          void refreshConfiguration();
          void refreshRuntimeStatus();
          void refreshCatalog(selected.path);
          if (selectedSessionId) {
            void send("session.resume", { session_id: selectedSessionId }).then((resumed) => {
              if (!cancelled) {
                dispatch({ type: "session_resumed", result: resumed });
                void refreshRuntimeStatus();
              }
            }).catch((error) => {
              if (!cancelled) dispatch({ type: "notice", text: errorMessage(error, t("sessionResumeFailed")) });
            });
          }
        }).catch((error) => {
          if (!cancelled) dispatch({ type: "runtime_error", message: errorMessage(error, t("runtimeStartFailed")), state: "configuration_required" });
        });
      } else {
        dispatch({ type: "runtime_state", state: "ready" });
      }
    }).catch((error) => {
      if (!cancelled) dispatch({ type: "runtime_error", message: errorMessage(error, t("preferencesUnavailable")), state: "ready" });
    });
    return () => {
      cancelled = true;
      pendingTurnStartRef.current = null;
      cancelTerminalStatusPoll();
      unsubscribe();
    };
  }, [api, cancelTerminalStatusPoll, processAgentEvent, refreshCatalog, send, t]);

  const openProject = useCallback(async () => {
    if (!api) return;
    try {
      const path = await api.openProject();
      if (path) await openProjectPath(path);
    } catch (error) {
      dispatch({ type: "notice", text: errorMessage(error, t("projectPickerUnavailable")) });
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
      ?? startTerminalStatusConvergence(beforeRunId, beforeTurnId));
    if (!stillOwnsTurn()) return false;
    if (idle.state !== "idle") {
      dispatch({ type: "notice", text: t("terminalStatusPending") });
      return false;
    }
    return true;
  }, [api, send, startTerminalStatusConvergence, t]);

  const resumeSession = useCallback(async (project: ProjectState, sessionId: string) => {
    if (!api) return;
    if (!(await closeActiveTurn())) return;
    try {
      if (stateRef.current.selectedProjectKey !== project.projectKey) {
        const opened = await send("project.open", { path: project.path });
        dispatch({ type: "project_opened", result: opened });
        await persist("selectedProjectKey", project.projectKey);
      }
      if (sessionId) {
        const result = await send("session.resume", { session_id: sessionId });
        dispatch({ type: "session_resumed", result });
        await persist("selectedSessionId", sessionId);
      } else {
        const result = await send("session.new", {});
        const source = asObject(result);
        const nextId = typeof source.session_id === "string" ? source.session_id : "";
        if (nextId) {
          dispatch({ type: "session_new", sessionId: nextId, run: source.run });
          await persist("selectedSessionId", nextId);
        }
      }
      await refreshCatalog(project.projectKey, sessionId ? "session_resume" : "session_new", sessionId || undefined);
      await refreshRuntimeStatus();
    } catch (error) {
      dispatch({ type: "runtime_error", message: errorMessage(error, t("sessionOpenFailed")), state: "ready" });
    }
  }, [api, closeActiveTurn, persist, refreshCatalog, send]);

  const newSession = useCallback(async () => {
    const project = stateRef.current.projects.find((item) => item.projectKey === stateRef.current.selectedProjectKey);
    if (project) await resumeSession(project, "");
  }, [resumeSession]);

  const executeCommand = useCallback(async (text: string) => {
    if (!text.trim() || !api) return;
    try {
      const result = await send("command.execute", { text });
      dispatch({ type: "command_result", result });
      const source = asObject(result);
      const action = asObject(source.ui_action);
      // Command outcomes are explicit Application boundaries.  Refresh the
      // safe Context/Compaction projection once here; completion deltas never
      // trigger status RPCs.
      await refreshRuntimeStatus();
      if (action.type === "open_model_picker") {
        try {
          const completion = asObject(await send("command.complete", { prefix: "/model " }));
          const values = Array.isArray(completion.argument_candidates) ? completion.argument_candidates.filter((value): value is string => typeof value === "string") : [];
          dispatch({ type: "model_candidates", values });
        } catch {
          dispatch({ type: "model_candidates", values: [] });
        }
      }
      if (action.type === "session_changed" && typeof action.session_id === "string") {
        await persist("selectedSessionId", action.session_id);
        const reason: SessionOrderReason = action.restored === true ? "session_resume" : "session_new";
        await refreshCatalog(stateRef.current.selectedProjectKey ?? "", reason, action.session_id);
        await refreshRuntimeStatus();
      }
      if (action.type === "quit_interface") {
        await api.closeShell();
      }
    } catch (error) {
      dispatch({ type: "notice", text: errorMessage(error, t("commandFailed")) });
    }
  }, [api, persist, refreshCatalog, refreshRuntimeStatus, send]);

  const submitComposer = useCallback(async (text: string) => {
    if (!api || !mountedRef.current || !text.trim() || pendingTurnStartRef.current || stateRef.current.pendingInteraction || stateRef.current.terminalStatusPending || stateRef.current.compactionStatus.state === "running") return;
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
      dispatch({ type: "notice", text: errorMessage(error, t("turnStartFailed")) });
    }
  }, [api, cancelTerminalStatusPoll, executeCommand, processAgentEvent, send, t]);

  const completeCommand = useCallback(async (prefix: string) => {
    if (!api || !prefix.trimStart().startsWith("/")) return;
    try {
      const result = await send("command.complete", { prefix });
      dispatch({ type: "command_candidates", result });
    } catch {
      dispatch({ type: "command_candidates", result: { candidates: [], argument_candidates: [] } });
    }
  }, [api, send]);

  const sendInteraction = useCallback(async (response: JsonObject) => {
    if (!api || !stateRef.current.pendingInteraction) return;
    dispatch({ type: "interaction_submitting", value: true });
    try {
      await send("turn.resume", { response });
    } catch (error) {
      dispatch({ type: "interaction_submitting", value: false });
      dispatch({ type: "notice", text: errorMessage(error, t("interactionSubmitFailed")) });
    }
  }, [api, send]);

  const cancelTurn = useCallback(async () => {
    pendingTurnStartRef.current = null;
    if (!api) return;
    try {
      await send("turn.cancel", {});
    } catch (error) {
      dispatch({ type: "notice", text: errorMessage(error, t("turnCancelFailed")) });
    }
  }, [api, send]);

  const pauseTurn = useCallback(async () => {
    if (!api) return;
    try {
      await send("turn.pause", {});
    } catch (error) {
      dispatch({ type: "notice", text: errorMessage(error, t("turnPauseFailed")) });
    }
  }, [api, send]);

  const setTheme = useCallback((theme: ThemePreference) => {
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
    try {
      const result = await send("session.rename", { session_id: session.session_id, title });
      dispatch({ type: "session_mutated", sourceProjectKey: project.projectKey, result });
    } catch (error) {
      dispatch({ type: "notice", text: errorMessage(error, t("sessionRenameFailed")) });
    }
  }, [send]);

  const moveSession = useCallback(async (project: ProjectState, session: SessionSummary, target: ProjectState) => {
    if (stateRef.current.activeTurn || stateRef.current.terminalStatusPending) {
      dispatch({ type: "notice", text: t("sessionMoveActive") });
      return;
    }
    try {
      const result = await send("session.move", { session_id: session.session_id, target_project_key: target.projectKey });
      dispatch({ type: "session_mutated", sourceProjectKey: project.projectKey, result });
      const pinnedSessions = stateRef.current.pinnedSessions.map((item) => item.projectKey === project.projectKey && item.sessionId === session.session_id ? { ...item, projectKey: target.projectKey } : item);
      await persist("pinnedSessions", pinnedSessions);
      if (stateRef.current.selectedProjectKey === project.projectKey) await refreshCatalog(project.projectKey);
    } catch (error) {
      dispatch({ type: "notice", text: errorMessage(error, t("sessionMoveFailed")) });
    }
  }, [persist, refreshCatalog, send]);

  const copySessionId = useCallback(async (session: SessionSummary) => {
    if (!api) return;
    try {
      await api.copySessionId(session.session_id);
      dispatch({ type: "notice", text: t("copiedSessionId") });
    } catch (error) {
      dispatch({ type: "notice", text: errorMessage(error, t("copySessionIdFailed")) });
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

    if (!(await closeActiveTurn())) return;
    try {
      const replacement = removal.replacement;
      if (replacement) {
        const opened = await send("project.open", { path: replacement.path });
        dispatch({ type: "project_opened", result: opened });
        dispatch({ type: "hydrate_preferences", preferences: { ...navigation, selectedProjectKey: replacement.projectKey, selectedSessionId: null } });
        await persist("recentProjects", navigation.recentProjects);
        await persist("projectAliases", navigation.projectAliases);
        await persist("pinnedProjectKeys", navigation.pinnedProjectKeys);
        await persist("pinnedSessions", navigation.pinnedSessions);
        await persist("expandedProjects", navigation.expandedProjects);
        await persist("selectedProjectKey", replacement.projectKey);
        await persist("selectedSessionId", null);
        await refreshCatalog(replacement.projectKey);
      } else {
        await send("runtime.shutdown", {});
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
    } catch (error) {
      dispatch({ type: "runtime_error", message: errorMessage(error, t("projectRemoveFailed")), state: "ready" });
    }
  }, [closeActiveTurn, persist, refreshCatalog, send]);

  const openExplorer = useCallback((project: ProjectState) => {
    if (!api) return;
    void api.openProjectInExplorer(project.path).catch((error) => dispatch({ type: "notice", text: errorMessage(error, t("explorerOpenFailed")) }));
  }, [api]);

  const loadSettings = useCallback(async () => {
    if (!api) {
      dispatch({ type: "settings_loaded", configuration: {} });
      return;
    }
    dispatch({ type: "set_view", view: "settings" });
    try {
      const result = asObject(await send("settings.get", {}));
      dispatch({ type: "settings_loaded", configuration: (asObject(result.configuration) as ConfigurationView) });
    } catch (error) {
      dispatch({ type: "settings_error", message: errorMessage(error, t("configUnavailable")) });
    }
  }, [api, send]);

  const saveSettings = useCallback(async (request: ConfigurationWrite) => {
    if (!api || stateRef.current.activeTurn || stateRef.current.terminalStatusPending) {
      dispatch({ type: "settings_error", message: t("finishTurnBeforeSave") });
      throw new Error(t("finishTurnBeforeSave"));
    }
    const projectKey = stateRef.current.selectedProjectKey;
    const sessionId = stateRef.current.selectedSessionId;
    dispatch({ type: "settings_saving", value: true });
    try {
      const result = await send("settings.save", { request: request as unknown as JsonObject });
      dispatch({ type: "settings_loaded", configuration: asObject(result).configuration as ConfigurationView });
      if (projectKey) {
        await rebootstrapProject(
          send,
          projectKey,
          sessionId,
          (opened) => dispatch({ type: "project_opened", result: opened }),
          (resumed) => dispatch({ type: "session_resumed", result: resumed }),
        );
        dispatch({ type: "runtime_state", state: "ready" });
        await refreshRuntimeStatus();
        await refreshCatalog(projectKey);
      }
      dispatch({ type: "notice", text: t("settingsSaved") });
    } catch (error) {
      dispatch({ type: "settings_error", message: errorMessage(error, t("settingsSaveFailed")) });
      throw error;
    } finally {
      dispatch({ type: "settings_saving", value: false });
    }
  }, [api, refreshCatalog, refreshRuntimeStatus, send]);

  const runtimeVisible = state.panelMode !== "hidden" && !(narrowViewport && state.panelMode === "docked");
  const runtimeToggleLabel = runtimeVisible ? t("closeRuntime") : t("openRuntime");
  const content = state.view === "settings" ? (
    <SettingsView state={state} api={api} onBack={() => dispatch({ type: "set_view", view: "chat" })} onSave={saveSettings} onThemeChange={setTheme} onLanguageChange={setLanguage} />
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
      <ChatTimeline entries={state.timeline} todo={state.todo} notice={state.notice} sessionKey={`${state.selectedProjectKey ?? ""}:${state.selectedSessionId ?? ""}:${state.sessionViewRevision}`} />
      {state.pendingInteraction && <InteractionSurface key={interactionSurfaceKey(state.pendingInteraction)} interaction={state.pendingInteraction} onSubmit={sendInteraction} onCancel={cancelTurn} />}
      <Composer state={state} onChange={(text) => { dispatch({ type: "composer_text", text }); void completeCommand(text); }} onDismissCompletion={() => dispatch({ type: "command_candidates", result: { candidates: [], argument_candidates: [] } })} onSubmit={submitComposer} onCommand={executeCommand} onPause={pauseTurn} onCancel={cancelTurn} />
    </>
  );

  const themeClass = `theme-${state.theme}`;
  return <LanguageProvider value={state.language}>
    <div className={`app-shell ${themeClass} panel-${state.panelMode}${state.view === "settings" ? " settings-shell" : ""}`}>
      {state.view === "chat" && <Sidebar projects={state.projects} selectedProjectKey={state.selectedProjectKey} selectedSessionId={state.selectedSessionId} activeTurn={state.activeTurn || state.terminalStatusPending} expandedProjects={state.expandedProjects} onProjectExpandedChange={setProjectExpanded} onNewSession={newSession} onOpenProject={openProject} onOpenProjectSession={(project) => void openProjectPath(project.path)} onResumeSession={(project, sessionId) => void resumeSession(project, sessionId)} onAliasChange={aliasChange} onTogglePin={togglePin} onToggleSessionPin={toggleSessionPin} onRenameSession={renameSession} onMoveSession={moveSession} onCopySessionId={copySessionId} onOpenExplorer={openExplorer} onRemoveProject={removeProject} onOpenSettings={() => void loadSettings()} />}
      <main aria-label={t("workspace")}>{content}</main>
      {state.view === "chat" && <RuntimePanel id={RUNTIME_PANEL_ID} state={state} visible={runtimeVisible} drawer={narrowViewport && state.panelMode === "floating"} onPanelModeChange={setPanelMode} onClose={closeRuntimeDrawer} onRestoreToggleFocus={restoreRuntimeToggleFocus} />}
      {state.runtimeError && state.view !== "settings" && state.runtimeState === "configuration_required" && <button type="button" className="configuration-banner" onClick={() => void loadSettings()}>{state.runtimeError} — {t("openSettings")}</button>}
    </div>
  </LanguageProvider>;
}
