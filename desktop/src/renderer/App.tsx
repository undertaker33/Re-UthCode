import { useCallback, useEffect, useReducer, useRef } from "react";
import type { DesktopApi, DesktopPreferences, JsonObject, JsonValue, LanguagePreference, PanelModePreference, ThemePreference } from "../desktop-api";
import { ChatTimeline } from "./ChatTimeline";
import { Composer } from "./Composer";
import { RuntimePanel } from "./RuntimePanel";
import { Sidebar } from "./Sidebar";
import { InteractionSurface, interactionSurfaceKey } from "./InteractionSurface";
import { SettingsView, type ConfigurationWrite } from "./SettingsView";
import { createInitialState, reduceRendererState, type RendererAction, type RendererState, type ProjectState, type SessionSummary, type ConfigurationView } from "./state";
import { UiIcon } from "./UiIcon";
import { LanguageProvider, translate } from "./i18n";

export interface AppProps {
  api?: DesktopApi;
  initialState?: RendererState;
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

function errorMessage(error: unknown, fallback: string): string {
  if (error && typeof error === "object") {
    const source = error as { message?: unknown; error?: { message?: unknown } };
    if (typeof source.error?.message === "string") return source.error.message;
    if (typeof source.message === "string") return source.message;
  }
  return fallback;
}

async function waitForIdle(api: DesktopApi): Promise<void> {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      const value = asObject(await api.requestRuntime("status.get", {}));
      if (value.active_turn !== true) return;
    } catch {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 25));
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

type RuntimeRequest = (method: Parameters<DesktopApi["requestRuntime"]>[0], params: JsonObject) => Promise<JsonValue>;

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
  const t = useCallback((key: Parameters<typeof translate>[1]) => translate(stateRef.current.language, key), []);

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

  const refreshCatalog = useCallback(async (projectKey: string) => {
    try {
      const result = asObject(await send("project.sessions", {}));
      const sessions = Array.isArray(result.sessions) ? result.sessions : [];
      dispatch({ type: "catalog_refreshed", projectKey, sessions });
    } catch (error) {
      dispatch({ type: "notice", text: errorMessage(error, t("sessionCatalogUnavailable")) });
    }
  }, [send]);

  const refreshRuntimeStatus = useCallback(async () => {
    try {
      dispatch({ type: "status_loaded", result: await send("status.get", {}) });
    } catch {
      // Runtime status is supplementary safe projection; command and Run
      // authority remain usable when it is temporarily unavailable.
    }
  }, [send]);

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
      dispatch({ type: "agent_event", event });
      if (event.type === "turn_completed" || event.type === "turn_failed" || event.type === "turn_cancelled") void refreshRuntimeStatus();
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
      unsubscribe();
    };
  }, [api, refreshRuntimeStatus, send]);

  const openProject = useCallback(async () => {
    if (!api) return;
    try {
      const path = await api.openProject();
      if (path) await openProjectPath(path);
    } catch (error) {
      dispatch({ type: "notice", text: errorMessage(error, t("projectPickerUnavailable")) });
    }
  }, [api, openProjectPath]);

  const closeActiveTurn = useCallback(async () => {
    if (!api || !stateRef.current.activeTurn) return;
    try {
      await send("turn.cancel", {});
    } catch {
      // The Bridge owns the terminal error. We still wait for its state before
      // asking it to replace a Session/Application.
    }
    await waitForIdle(api);
  }, [api, send]);

  const resumeSession = useCallback(async (project: ProjectState, sessionId: string) => {
    if (!api) return;
    await closeActiveTurn();
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
      await refreshCatalog(project.projectKey);
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
      if (action.type === "model_selected") void refreshRuntimeStatus();
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
        await refreshCatalog(stateRef.current.selectedProjectKey ?? "");
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
    if (!api || !text.trim() || stateRef.current.pendingInteraction) return;
    if (text.trimStart().startsWith("/")) {
      await executeCommand(text.trim());
      return;
    }
    const steering = stateRef.current.activeTurn;
    try {
      const result = steering
        ? await send("turn.steer", { text })
        : await send("turn.start", { prompt: text });
      dispatch({ type: "turn_accepted", run: asObject(result).run, steering, text });
    } catch (error) {
      dispatch({ type: "notice", text: errorMessage(error, t("turnStartFailed")) });
    }
  }, [api, executeCommand, send]);

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

  const setProjectExpanded = useCallback((projectKey: string, expanded: boolean) => {
    // Expansion is navigation metadata only.  Accept updates from rendered
    // Project rows, but never let an arbitrary key become a trusted Project.
    if (!stateRef.current.projects.some((project) => project.projectKey === projectKey)) return;
    const expandedProjects = { ...stateRef.current.expandedProjects, [projectKey]: expanded };
    dispatch({ type: "hydrate_preferences", preferences: { expandedProjects } });
    void persist("expandedProjects", expandedProjects);
  }, [persist]);

  const toggleRuntime = useCallback(() => {
    setPanelMode(stateRef.current.panelMode === "hidden" ? "floating" : "hidden");
  }, [setPanelMode]);

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
    if (stateRef.current.activeTurn) {
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
    if (stateRef.current.activeTurn || stateRef.current.selectedSessionId === session.session_id) {
      dispatch({ type: "notice", text: stateRef.current.activeTurn ? t("sessionMoveActive") : t("sessionMoveBusy") });
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

    await closeActiveTurn();
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
    if (!api || stateRef.current.activeTurn) {
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
          <button type="button" className="icon-button" title={t("toggleRuntime")} aria-label={t("toggleRuntime")} onClick={toggleRuntime}><UiIcon name="panel" /></button>
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
      {state.view === "chat" && <Sidebar projects={state.projects} selectedProjectKey={state.selectedProjectKey} selectedSessionId={state.selectedSessionId} activeTurn={state.activeTurn} expandedProjects={state.expandedProjects} onProjectExpandedChange={setProjectExpanded} onNewSession={newSession} onOpenProject={openProject} onOpenProjectSession={(project) => void openProjectPath(project.path)} onResumeSession={(project, sessionId) => void resumeSession(project, sessionId)} onAliasChange={aliasChange} onTogglePin={togglePin} onToggleSessionPin={toggleSessionPin} onRenameSession={renameSession} onMoveSession={moveSession} onCopySessionId={copySessionId} onOpenExplorer={openExplorer} onRemoveProject={removeProject} onOpenSettings={() => void loadSettings()} />}
      <main aria-label={t("workspace")}>{content}</main>
      {state.view === "chat" && <RuntimePanel state={state} onPanelModeChange={setPanelMode} />}
      {state.runtimeError && state.view !== "settings" && state.runtimeState === "configuration_required" && <button type="button" className="configuration-banner" onClick={() => void loadSettings()}>{state.runtimeError} — {t("openSettings")}</button>}
    </div>
  </LanguageProvider>;
}
