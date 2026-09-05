import type { DesktopPreferences, JsonValue } from "../desktop-api";
import {
  asRecord,
  contextUsageAtBoundary,
  normalizeProjectPath,
  normalizeRun,
  replayToTimeline,
  resultRecord,
  runIdOf,
  sessionRuntimeFromSource,
} from "./state-normalization";
import { nonEmptyText, textValue } from "./text-normalization";
import type {
  PermissionModeProjection,
  ProjectState,
  ProviderRequestUsageProjection,
  RendererState,
  RunProjection,
  SessionRuntimeSnapshot,
  SessionSummary,
  TimelineEntry,
} from "./state";
import { permissionModeOf } from "./state-normalization";

function providerRequestUsageAtBoundary(): ProviderRequestUsageProjection {
  return {
    status: "not_available",
    input_tokens: null,
    output_tokens: null,
    total_tokens: null,
    cache_read: { status: "not_available", tokens: null, provenance: null },
    cache_write: { status: "not_available", tokens: null, provenance: null },
  };
}

function cloneProviderRequestUsage(value: ProviderRequestUsageProjection): ProviderRequestUsageProjection {
  return {
    ...value,
    cache_read: { ...value.cache_read },
    cache_write: { ...value.cache_write },
  };
}

export function sessionRuntimeKey(projectKey: string | null | undefined, sessionId: string): string {
  return `${projectKey ?? ""}\u0000${sessionId}`;
}

export function cloneSessionRuntime(snapshot: SessionRuntimeSnapshot): SessionRuntimeSnapshot {
  return {
    ...snapshot,
    timeline: snapshot.timeline.map((entry) => ({ ...entry })),
    todo: snapshot.todo.map((item) => ({ ...item })),
    run: snapshot.run ? { ...snapshot.run, usage: snapshot.run.usage ? { ...snapshot.run.usage } : undefined } : null,
    contextUsage: { ...snapshot.contextUsage },
    ...(snapshot.lastProviderRequestUsage ? { lastProviderRequestUsage: cloneProviderRequestUsage(snapshot.lastProviderRequestUsage) } : {}),
    compactionStatus: { ...snapshot.compactionStatus },
    pendingInteraction: snapshot.pendingInteraction
      ? { ...snapshot.pendingInteraction, request: snapshot.pendingInteraction.request ? { ...snapshot.pendingInteraction.request } : undefined }
      : null,
  };
}

export function runtimeSnapshotFromState(state: RendererState): SessionRuntimeSnapshot {
  return cloneSessionRuntime({
    timeline: state.timeline,
    todo: state.todo,
    todoIteration: state.todoIteration,
    run: state.run,
    contextUsage: state.contextUsage,
    lastProviderRequestUsage: state.lastProviderRequestUsage,
    compactionStatus: state.compactionStatus,
    permissionMode: state.permissionMode,
    activeTurn: state.activeTurn,
    terminalStatusPending: state.terminalStatusPending,
    turnStatus: state.turnStatus,
    pendingInteraction: state.pendingInteraction,
    completionBlocked: state.completionBlocked,
  });
}

export function applyRuntimeSnapshot(state: RendererState, snapshot: SessionRuntimeSnapshot): RendererState {
  return {
    ...state,
    timeline: snapshot.timeline.map((entry) => ({ ...entry })),
    todo: snapshot.todo.map((item) => ({ ...item })),
    todoIteration: snapshot.todoIteration,
    run: snapshot.run ? { ...snapshot.run, usage: snapshot.run.usage ? { ...snapshot.run.usage } : undefined } : null,
    contextUsage: { ...snapshot.contextUsage },
    lastProviderRequestUsage: snapshot.lastProviderRequestUsage
      ? cloneProviderRequestUsage(snapshot.lastProviderRequestUsage)
      : providerRequestUsageAtBoundary(),
    compactionStatus: { ...snapshot.compactionStatus },
    permissionMode: snapshot.permissionMode,
    activeTurn: snapshot.activeTurn,
    terminalStatusPending: snapshot.terminalStatusPending,
    turnStatus: snapshot.turnStatus,
    pendingInteraction: snapshot.pendingInteraction
      ? { ...snapshot.pendingInteraction, request: snapshot.pendingInteraction.request ? { ...snapshot.pendingInteraction.request } : undefined }
      : null,
    completionBlocked: snapshot.completionBlocked,
  };
}

export function emptyRuntimeBoundary(state: RendererState): RendererState {
  return {
    ...state,
    timeline: [],
    todo: [],
    todoIteration: 0,
    run: null,
    contextUsage: contextUsageAtBoundary(),
    lastProviderRequestUsage: providerRequestUsageAtBoundary(),
    compactionStatus: { state: "idle", trigger: null, changed: null },
    permissionMode: "unknown",
    activeTurn: false,
    terminalStatusPending: false,
    turnStatus: "idle",
    pendingInteraction: null,
    completionBlocked: null,
  };
}

export function runtimeStatus(snapshot: SessionRuntimeSnapshot): SessionSummary["runtime_status"] {
  if (snapshot.pendingInteraction || snapshot.turnStatus === "paused" || snapshot.turnStatus === "pausing") return "waiting";
  if (snapshot.activeTurn && snapshot.turnStatus === "running") return "running";
  if (snapshot.turnStatus === "failed") return "failed";
  if (snapshot.turnStatus === "cancelled") return "cancelled";
  if (snapshot.turnStatus === "completed" || snapshot.terminalStatusPending) return "completed";
  return "idle";
}

export function updateSessionRuntimeStatus(
  state: RendererState,
  projectKey: string | null | undefined,
  sessionId: string,
  status: SessionSummary["runtime_status"],
): RendererState {
  if (!projectKey) return state;
  return {
    ...state,
    projects: state.projects.map((project) => project.projectKey === projectKey
      ? { ...project, sessions: project.sessions.map((session) => session.session_id === sessionId ? { ...session, runtime_status: status } : session) }
      : project),
  };
}

export function cacheVisibleRuntime(state: RendererState, projectKey: string | null, sessionId: string | null): RendererState {
  if (!projectKey || !sessionId) return state;
  const snapshot = runtimeSnapshotFromState(state);
  return {
    ...state,
    sessionRuntime: { ...state.sessionRuntime, [sessionRuntimeKey(projectKey, sessionId)]: snapshot },
  };
}

function shortId(value: string): string {
  return value.length > 8 ? value.slice(0, 8) : value;
}

export function sessionLabel(session: Pick<SessionSummary, "session_id" | "preview" | "title">): string {
  const title = nonEmptyText(session.title);
  if (title) return title;
  const preview = nonEmptyText(session.preview);
  return preview ?? shortId(session.session_id);
}

function normalizeSession(value: unknown, fallbackProjectKey?: string): SessionSummary | null {
  const source = asRecord(value);
  const sessionId = nonEmptyText(source?.session_id);
  if (!sessionId) return null;
  const runtimeStatus = source?.runtime_status === "idle" || source?.runtime_status === "running" || source?.runtime_status === "waiting" || source?.runtime_status === "completed" || source?.runtime_status === "failed" || source?.runtime_status === "cancelled"
    ? source.runtime_status
    : undefined;
  return {
    session_id: sessionId,
    project_key: nonEmptyText(source?.project_key) ?? fallbackProjectKey,
    last_used_at: textValue(source?.last_used_at),
    title: source?.title === null ? null : textValue(source?.title) || null,
    preview: textValue(source?.preview),
    timeline_checkpoint_id: typeof source?.timeline_checkpoint_id === "string" ? source.timeline_checkpoint_id : null,
    transcript_entries: typeof source?.transcript_entries === "number" ? source.transcript_entries : 0,
    corrupt: source?.corrupt === true,
    model_ref: source?.model_ref === null ? null : nonEmptyText(source?.model_ref),
    ...(runtimeStatus ? { runtime_status: runtimeStatus } : {}),
  };
}

function preserveRuntimeStatuses(previous: readonly SessionSummary[], incoming: readonly SessionSummary[]): SessionSummary[] {
  const previousById = new Map(previous.map((session) => [session.session_id, session]));
  return incoming.map((session) => {
    if (session.runtime_status !== undefined) return session;
    const status = previousById.get(session.session_id)?.runtime_status;
    return status === undefined ? session : { ...session, runtime_status: status };
  });
}

export function applySessionPins(sessions: SessionSummary[], projectKey: string, pinnedSessions: DesktopPreferences["pinnedSessions"]): SessionSummary[] {
  const pinned = new Set(pinnedSessions.filter((item) => item.projectKey === projectKey).map((item) => item.sessionId));
  return sessions.map((session) => ({ ...session, pinned: pinned.has(session.session_id) }));
}

export function mergeSessionModels(
  existing: Record<string, string>,
  sessions: readonly SessionSummary[],
): Record<string, string> {
  const next = { ...existing };
  sessions.forEach((session) => {
    const model = nonEmptyText(session.model_ref);
    if (model) next[session.session_id] = model;
  });
  return next;
}

export type SessionOrderReason = "project_open" | "catalog_refresh" | "message" | "session_resume" | "session_new" | "session_pin" | "session_rename";

/** Keep catalog presentation stable while applying authoritative row updates. */
export function preserveSessionOrder(previous: readonly SessionSummary[], incoming: readonly SessionSummary[], reason: SessionOrderReason, focusSessionId?: string): SessionSummary[] {
  const incomingById = new Map(incoming.map((session) => [session.session_id, session]));
  const existingIds = new Set<string>();
  const kept = previous.flatMap((session) => {
    const next = incomingById.get(session.session_id);
    if (!next) return [];
    existingIds.add(session.session_id);
    return [next];
  });
  const added = incoming.filter((session) => {
    if (existingIds.has(session.session_id)) return false;
    existingIds.add(session.session_id);
    return true;
  });
  const stable = [...kept, ...added];
  if (reason === "session_new") {
    const addedIds = new Set(added.map((session) => session.session_id));
    return [...stable.filter((session) => addedIds.has(session.session_id)), ...stable.filter((session) => !addedIds.has(session.session_id))];
  }
  if (reason === "message" && focusSessionId) {
    const focused = stable.find((session) => session.session_id === focusSessionId);
    if (focused) return [focused, ...stable.filter((session) => session.session_id !== focusSessionId)];
  }
  return stable;
}

function projectFromPath(path: string, existing?: ProjectState): ProjectState {
  return {
    path,
    projectKey: path,
    alias: existing?.alias || path.split(/[\\/]/u).filter(Boolean).pop() || path,
    pinned: existing?.pinned ?? false,
    lastOpenedAt: new Date().toISOString(),
    sessions: existing?.sessions ?? [],
    catalogFresh: existing?.catalogFresh ?? false,
  };
}

function replaceProject(state: RendererState, project: ProjectState): RendererState {
  const projects = state.projects.some((item) => item.projectKey === project.projectKey)
    ? state.projects.map((item) => (item.projectKey === project.projectKey ? project : item))
    : [...state.projects, project];
  return { ...state, projects };
}

function rememberRunBoundary(state: RendererState, nextRun: unknown): string[] {
  const previous = runIdOf(state.run);
  const next = runIdOf(nextRun);
  if (!previous || previous === next || state.ignoredRunIds.includes(previous)) return state.ignoredRunIds;
  return [...state.ignoredRunIds, previous].slice(-20);
}

export function permissionUnknownAtRunBoundary(state: RendererState, run: unknown, ignorePreviousRun = true): RendererState {
  const normalized = normalizeRun(run);
  return {
    ...state,
    run: normalized,
    permissionMode: permissionModeOf(normalized),
    ignoredRunIds: ignorePreviousRun ? rememberRunBoundary(state, run) : state.ignoredRunIds,
  };
}

export function applyProjectOpened(
  state: RendererState,
  result: unknown,
  preserveRuntimeState = false,
  preserveSessionRuntime = false,
): RendererState {
  const stateWithCache = cacheVisibleRuntime(state, state.selectedProjectKey, state.selectedSessionId);
  const source = resultRecord(result);
  const project = resultRecord(source.project);
  const path = normalizeProjectPath(project.path);
  if (!path) return { ...state, runtimeError: "Project path is unavailable" };
  const existing = stateWithCache.projects.find((item) => item.projectKey === path);
  const incomingSessions = Array.isArray(source.sessions)
    ? source.sessions.map((item) => normalizeSession(item, path)).filter((item): item is SessionSummary => item !== null)
    : [];
  const sessions = preserveSessionOrder(existing?.sessions ?? [], preserveRuntimeStatuses(existing?.sessions ?? [], incomingSessions), "project_open");
  const nextRun = normalizeRun(source.run);
  return {
    ...permissionUnknownAtRunBoundary(
      replaceProject(stateWithCache, { ...projectFromPath(path, existing), sessions: applySessionPins(sessions, path, stateWithCache.pinnedSessions), catalogFresh: true }),
      nextRun,
      !preserveSessionRuntime,
    ),
    selectedProjectKey: path,
    selectedSessionId: null,
    timeline: [],
    todo: [],
    todoIteration: 0,
    activeTurn: false,
    terminalStatusPending: false,
    turnStatus: "idle",
    pendingInteraction: null,
    contextUsage: contextUsageAtBoundary(),
    lastProviderRequestUsage: providerRequestUsageAtBoundary(),
    sessionModels: mergeSessionModels(stateWithCache.sessionModels, sessions),
    sessionViewRevision: stateWithCache.sessionViewRevision + 1,
    runtimeState: preserveRuntimeState ? stateWithCache.runtimeState : "ready",
    runtimeError: null,
    view: "chat",
  };
}

export function applyCatalogRefreshed(state: RendererState, projectKey: string, values: readonly unknown[], reason: SessionOrderReason = "catalog_refresh", focusSessionId?: string): RendererState {
  const previous = state.projects.find((item) => item.projectKey === projectKey)?.sessions ?? [];
  const incoming = values.map((item) => normalizeSession(item, projectKey)).filter((item): item is SessionSummary => item !== null);
  const sessions = applySessionPins(preserveSessionOrder(previous, preserveRuntimeStatuses(previous, incoming), reason, focusSessionId), projectKey, state.pinnedSessions);
  const replaced = replaceProject(state, projectFromPath(projectKey, state.projects.find((item) => item.projectKey === projectKey)));
  return {
    ...replaced,
    projects: replaced.projects.map((item) => item.projectKey === projectKey ? { ...item, sessions, catalogFresh: true } : item),
    sessionModels: mergeSessionModels(state.sessionModels, sessions),
  };
}

export function applySessionResumed(
  state: RendererState,
  result: unknown,
  preserveRuntimeState = false,
  providerRequestUsage?: ProviderRequestUsageProjection,
  preserveSessionRuntime = false,
): RendererState {
  const stateWithCache = cacheVisibleRuntime(state, state.selectedProjectKey, state.selectedSessionId);
  const source = resultRecord(result);
  const sessionId = nonEmptyText(source.session_id);
  if (!sessionId) return { ...state, runtimeError: "Session identity is unavailable" };
  const projectKey = state.selectedProjectKey;
  const key = sessionRuntimeKey(projectKey, sessionId);
  const cached = stateWithCache.sessionRuntime[key] ?? null;
  const replay = replayToTimeline(Array.isArray(source.replay) ? source.replay : []);
  const replayRecords = Array.isArray(source.replay) ? source.replay : [];
  const replayEndsInFailure = [...replayRecords]
    .map((value) => asRecord(value))
    .filter((value): value is Record<string, JsonValue> => value !== null)
    .sort((left, right) => (typeof left.sequence === "number" ? left.sequence : 0) - (typeof right.sequence === "number" ? right.sequence : 0))
    .at(-1)?.kind === "failure";
  const sourceSessionState = asRecord(source.session_state);
  const sourceRun = normalizeRun(sourceSessionState?.run ?? source.run);
  const sourceRunStatus = textValue(sourceRun?.status).toLowerCase();
  const canRestoreLiveCache = sourceSessionState !== null
    || source.active_turn === true
    || sourceRunStatus === "running" || sourceRunStatus === "paused" || sourceRunStatus === "pausing";
  const runtime = sessionRuntimeFromSource(source, replay, canRestoreLiveCache ? cached : null, providerRequestUsage);
  const restoredRuntime = runtime && replayEndsInFailure && !runtime.activeTurn
    ? { ...runtime, turnStatus: "failed" as const, terminalStatusPending: false }
    : runtime;
  const boundary = permissionUnknownAtRunBoundary(
    stateWithCache,
    restoredRuntime?.run ?? source.run,
    !preserveSessionRuntime,
  );
  const currentModel = nonEmptyText(source.model_ref);
  const catalogModel = projectKey
    ? stateWithCache.projects.find((project) => project.projectKey === projectKey)?.sessions.find((session) => session.session_id === sessionId)?.model_ref
    : null;
  const sessionModel = currentModel ?? nonEmptyText(catalogModel);
  const next: RendererState = {
    ...boundary,
    selectedSessionId: sessionId,
    timeline: restoredRuntime?.timeline ?? replay,
    todo: restoredRuntime?.todo ?? [],
    todoIteration: restoredRuntime?.todoIteration ?? 0,
    activeTurn: restoredRuntime?.activeTurn ?? false,
    terminalStatusPending: restoredRuntime?.terminalStatusPending ?? false,
    turnStatus: restoredRuntime?.turnStatus ?? (replayEndsInFailure ? "failed" : "idle"),
    pendingInteraction: restoredRuntime?.pendingInteraction ?? null,
    contextUsage: restoredRuntime?.contextUsage ?? contextUsageAtBoundary(),
    lastProviderRequestUsage: restoredRuntime?.lastProviderRequestUsage
      ? cloneProviderRequestUsage(restoredRuntime.lastProviderRequestUsage)
      : providerRequestUsageAtBoundary(),
    compactionStatus: restoredRuntime?.compactionStatus ?? { state: "idle", trigger: null, changed: null },
    completionBlocked: restoredRuntime?.completionBlocked ?? null,
    ...(sessionModel ? { currentModelRef: sessionModel, sessionModels: { ...stateWithCache.sessionModels, [sessionId]: sessionModel } } : {}),
    sessionViewRevision: stateWithCache.sessionViewRevision + 1,
    runtimeError: null,
    runtimeState: preserveRuntimeState ? stateWithCache.runtimeState : "ready",
    notice: "Session resumed",
    ...(restoredRuntime ? { sessionRuntime: { ...stateWithCache.sessionRuntime, [key]: restoredRuntime } } : {}),
    ...(projectKey ? { projects: stateWithCache.projects.map((project) => project.projectKey === projectKey ? { ...project, sessions: project.sessions.map((session) => session.session_id === sessionId ? { ...session } : session) } : project) } : {}),
  };
  return updateSessionRuntimeStatus(next, projectKey, sessionId, restoredRuntime ? runtimeStatus(restoredRuntime) : replayEndsInFailure ? "failed" : "idle");
}

export function applySessionMutation(
  state: RendererState,
  sourceProjectKey: string,
  result: unknown,
): RendererState {
  const source = resultRecord(result);
  const sessionId = nonEmptyText(source.session_id);
  if (!sessionId) return state;
  const destinationProjectKey = nonEmptyText(source.project_key) ?? sourceProjectKey;
  const sourceProject = state.projects.find((project) => project.projectKey === sourceProjectKey);
  const sourceSession = sourceProject?.sessions.find((session) => session.session_id === sessionId);
  const response = asRecord(source.session);
  const responseSession = normalizeSession(response, destinationProjectKey);
  const titleProvided = Object.prototype.hasOwnProperty.call(source, "title");
  const session = sourceSession
    ? {
      ...sourceSession,
      project_key: destinationProjectKey,
      ...(response && Object.prototype.hasOwnProperty.call(response, "last_used_at") ? { last_used_at: textValue(response.last_used_at) } : {}),
      ...(response && Object.prototype.hasOwnProperty.call(response, "title") ? { title: response.title === null ? null : textValue(response.title) || null } : {}),
      ...(response && Object.prototype.hasOwnProperty.call(response, "preview") ? { preview: textValue(response.preview) } : {}),
      ...(response && Object.prototype.hasOwnProperty.call(response, "timeline_checkpoint_id") ? { timeline_checkpoint_id: typeof response.timeline_checkpoint_id === "string" ? response.timeline_checkpoint_id : null } : {}),
      ...(response && Object.prototype.hasOwnProperty.call(response, "transcript_entries") ? { transcript_entries: typeof response.transcript_entries === "number" ? response.transcript_entries : 0 } : {}),
      ...(response && Object.prototype.hasOwnProperty.call(response, "corrupt") ? { corrupt: response.corrupt === true } : {}),
      ...(titleProvided && !response ? { title: source.title === null ? null : textValue(source.title) || null } : {}),
    }
    : responseSession;
  if (!session) return state;
  const existingPinned = sourceSession?.pinned === true || state.pinnedSessions.some((item) => item.projectKey === sourceProjectKey && item.sessionId === sessionId);
  const pinnedSessions = destinationProjectKey === sourceProjectKey
    ? state.pinnedSessions
    : state.pinnedSessions.map((item) => item.projectKey === sourceProjectKey && item.sessionId === sessionId
      ? { ...item, projectKey: destinationProjectKey }
      : item);
  const projects = state.projects.map((project) => {
    if (project.projectKey === sourceProjectKey && destinationProjectKey !== sourceProjectKey) {
      return { ...project, sessions: project.sessions.filter((item) => item.session_id !== sessionId) };
    }
    if (project.projectKey !== destinationProjectKey) return project;
    if (destinationProjectKey === sourceProjectKey) {
      return {
        ...project,
        sessions: project.sessions.map((item) => item.session_id === sessionId
          ? { ...item, ...session, pinned: existingPinned }
          : item),
      };
    }
    const withoutMoved = project.sessions.filter((item) => item.session_id !== sessionId);
    return { ...project, sessions: [...withoutMoved, { ...session, pinned: existingPinned }] };
  });
  const selectedSourceSession = destinationProjectKey !== sourceProjectKey
    && state.selectedProjectKey === sourceProjectKey
    && state.selectedSessionId === sessionId;
  return {
    ...state,
    projects,
    pinnedSessions,
    ...(selectedSourceSession
      ? {
         selectedSessionId: null,
         timeline: [],
         todo: [],
         todoIteration: 0,
         activeTurn: false,
         terminalStatusPending: false,
         turnStatus: "idle" as const,
         pendingInteraction: null,
         contextUsage: contextUsageAtBoundary(),
         lastProviderRequestUsage: providerRequestUsageAtBoundary(),
         sessionViewRevision: state.sessionViewRevision + 1,
       }
      : {}),
  };
}

export type { PermissionModeProjection, RunProjection, TimelineEntry };
