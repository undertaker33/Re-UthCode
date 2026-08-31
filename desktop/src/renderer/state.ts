import type { AgentEvent, DesktopPreferences, DesktopApi, JsonObject, JsonValue, LanguagePreference, PanelModePreference, ThemePreference } from "../desktop-api";

export type RuntimeStateName = "booting" | "ready" | "configuration_required" | "failed" | "stopping" | "stopped";
export type TimelineKind = "user" | "steering" | "reasoning" | "assistant" | "tool" | "plan" | "status";
export type TimelineStatus = "streaming" | "running" | "completed" | "failed" | "cancelled" | "info";
export type PermissionModeProjection = "unknown" | "default" | "auto" | "full_access";

export interface SessionSummary {
  session_id: string;
  project_key?: string;
  last_used_at?: string;
  title?: string | null;
  preview?: string;
  timeline_checkpoint_id?: string | null;
  transcript_entries?: number;
  corrupt?: boolean;
  pinned?: boolean;
}

export interface ProjectState {
  path: string;
  projectKey: string;
  alias: string;
  pinned: boolean;
  lastOpenedAt?: string;
  sessions: SessionSummary[];
  catalogFresh: boolean;
}

export interface RunProjection {
  run_id?: string;
  turn_id?: string;
  iteration_count?: number;
  tool_call_count?: number;
  behavior_mode?: string;
  permission_mode?: PermissionModeProjection;
  status?: string;
  termination_reason?: string | null;
  usage?: Record<string, JsonValue>;
}

export interface TimelineEntry {
  id: string;
  kind: TimelineKind;
  text: string;
  turnId?: string;
  messageId?: string;
  toolCallId?: string;
  toolName?: string;
  command?: string;
  status?: TimelineStatus;
  isError?: boolean;
  sequence?: number;
  streaming?: boolean;
}

export interface TodoItem {
  content: string;
  status: "pending" | "in_progress" | "completed";
}

export type InteractionKind =
  | "user_requested"
  | "user_input_required"
  | "provider_unavailable"
  | "permission_required"
  | "plan_review_required";

export interface PendingInteraction {
  kind: InteractionKind;
  pauseId: string;
  runId: string;
  turnId: string;
  toolCallId?: string;
  request?: Record<string, JsonValue>;
  reason?: string;
  iteration?: number;
  submitting?: boolean;
}

export interface CommandCandidate {
  value: string;
  canonical?: string;
  display?: string;
  description?: string;
  aliases?: string[];
  usage?: string;
  argument_prompt?: string;
  matched_alias?: string | null;
}

export interface ConfigurationView {
  default_model?: string;
  default_permission_mode?: string;
  providers?: Record<string, Record<string, JsonValue>>;
  models?: Record<string, Record<string, JsonValue>>;
}

export interface RendererState {
  runtimeState: RuntimeStateName;
  runtimeError: string | null;
  projects: ProjectState[];
  selectedProjectKey: string | null;
  selectedSessionId: string | null;
  timeline: TimelineEntry[];
  todo: TodoItem[];
  run: RunProjection | null;
  permissionMode: PermissionModeProjection;
  pinnedSessions: DesktopPreferences["pinnedSessions"];
  expandedProjects: DesktopPreferences["expandedProjects"];
  currentModelRef: string | null;
  modelCandidates: string[];
  modelPickerOpen: boolean;
  activeTurn: boolean;
  turnStatus: "idle" | "running" | "pausing" | "paused" | "completed" | "failed" | "cancelled";
  pendingInteraction: PendingInteraction | null;
  completionBlocked: string | null;
  commandCandidates: CommandCandidate[];
  argumentCandidates: string[];
  commandUsage: string | null;
  commandArgumentPrompt: string | null;
  commandOutput: string | null;
  notice: string | null;
  diagnostics: string[];
  composerText: string;
  panelMode: PanelModePreference;
  theme: ThemePreference;
  language: LanguagePreference;
  view: "chat" | "settings";
  configuration: ConfigurationView | null;
  settingsError: string | null;
  settingsSaving: boolean;
  settingsLoaded: boolean;
  ignoredRunIds: string[];
  nextStatusId: number;
}

export const DEFAULT_RENDERER_STATE: RendererState = {
  runtimeState: "booting",
  runtimeError: null,
  projects: [],
  selectedProjectKey: null,
  selectedSessionId: null,
  timeline: [],
  todo: [],
  run: null,
  permissionMode: "unknown",
  pinnedSessions: [],
  expandedProjects: {},
  currentModelRef: null,
  modelCandidates: [],
  modelPickerOpen: false,
  activeTurn: false,
  turnStatus: "idle",
  pendingInteraction: null,
  completionBlocked: null,
  commandCandidates: [],
  argumentCandidates: [],
  commandUsage: null,
  commandArgumentPrompt: null,
  commandOutput: null,
  notice: null,
  diagnostics: [],
  composerText: "",
  panelMode: "docked",
  theme: "system",
  language: "zh-CN",
  view: "chat",
  configuration: null,
  settingsError: null,
  settingsSaving: false,
  settingsLoaded: false,
  ignoredRunIds: [],
  nextStatusId: 1,
};

export function createInitialState(overrides: Partial<RendererState> = {}): RendererState {
  return {
    ...DEFAULT_RENDERER_STATE,
    ...overrides,
    projects: overrides.projects?.map((project) => ({ ...project, sessions: [...project.sessions] })) ?? [],
    expandedProjects: overrides.expandedProjects ? { ...overrides.expandedProjects } : {},
    timeline: overrides.timeline?.map((entry) => ({ ...entry })) ?? [],
    todo: overrides.todo?.map((item) => ({ ...item })) ?? [],
    diagnostics: overrides.diagnostics ? [...overrides.diagnostics] : [],
    ignoredRunIds: overrides.ignoredRunIds ? [...overrides.ignoredRunIds] : [],
  };
}

function asRecord(value: unknown): Record<string, JsonValue> | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, JsonValue>;
}

function textValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function numberText(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : "";
}

function nonEmptyText(value: unknown): string | null {
  const text = textValue(value).trim();
  return text ? text : null;
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
  return {
    session_id: sessionId,
    project_key: nonEmptyText(source?.project_key) ?? fallbackProjectKey,
    last_used_at: textValue(source?.last_used_at),
    title: source?.title === null ? null : textValue(source?.title) || null,
    preview: textValue(source?.preview),
    timeline_checkpoint_id: typeof source?.timeline_checkpoint_id === "string" ? source.timeline_checkpoint_id : null,
    transcript_entries: typeof source?.transcript_entries === "number" ? source.transcript_entries : 0,
    corrupt: source?.corrupt === true,
  };
}

function applySessionPins(sessions: SessionSummary[], projectKey: string, pinnedSessions: DesktopPreferences["pinnedSessions"]): SessionSummary[] {
  const pinned = new Set(pinnedSessions.filter((item) => item.projectKey === projectKey).map((item) => item.sessionId));
  return sessions.map((session) => ({ ...session, pinned: pinned.has(session.session_id) }));
}

/**
 * Catalog authority may order metadata by last-used time.  That is useful for
 * a cold project open, but a refresh must not make selecting or resuming an
 * existing row move it to another position in the navigation.  Reconcile
 * known rows in their existing order and append only genuinely new rows.
 */
function preserveSessionOrder(previous: readonly SessionSummary[], incoming: readonly SessionSummary[]): SessionSummary[] {
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
  return [...kept, ...added];
}

function normalizeProjectPath(value: unknown): string | null {
  return nonEmptyText(value);
}

function normalizeRun(value: unknown): RunProjection | null {
  const source = asRecord(value);
  if (!source) return null;
  const permissionMode = permissionModeOf(source);
  return {
    ...source,
    ...(permissionMode === "unknown" ? {} : { permission_mode: permissionMode }),
  } as RunProjection;
}

function permissionModeOf(value: unknown): PermissionModeProjection {
  const source = asRecord(value);
  const mode = source?.permission_mode;
  return mode === "default" || mode === "auto" || mode === "full_access" ? mode : "unknown";
}

function runIdOf(value: unknown): string | null {
  const source = asRecord(value);
  return nonEmptyText(source?.run_id);
}

function rememberRunBoundary(state: RendererState, nextRun: unknown): string[] {
  const previous = runIdOf(state.run);
  const next = runIdOf(nextRun);
  if (!previous || previous === next || state.ignoredRunIds.includes(previous)) return state.ignoredRunIds;
  return [...state.ignoredRunIds, previous].slice(-20);
}

function permissionUnknownAtRunBoundary(state: RendererState, run: unknown): RendererState {
  const normalized = normalizeRun(run);
  return {
    ...state,
    run: normalized,
    permissionMode: permissionModeOf(normalized),
    ignoredRunIds: rememberRunBoundary(state, run),
  };
}

export function replayToTimeline(records: readonly unknown[]): TimelineEntry[] {
  return records
    .map((value, index) => ({ value: asRecord(value), index }))
    .filter(({ value }) => value !== null)
    .sort((left, right) => {
      const a = left.value?.sequence;
      const b = right.value?.sequence;
      const aSequence = typeof a === "number" ? a : Number.MAX_SAFE_INTEGER;
      const bSequence = typeof b === "number" ? b : Number.MAX_SAFE_INTEGER;
      return aSequence - bSequence || left.index - right.index;
    })
    .map(({ value }, index) => {
      const source = value as Record<string, JsonValue>;
      const kind = source.kind;
      const normalizedKind: TimelineKind =
        kind === "user" || kind === "steering" || kind === "reasoning" || kind === "assistant" || kind === "tool"
          ? kind
          : "status";
      const sequence = typeof source.sequence === "number" ? source.sequence : index + 1;
      return {
        id: `replay:${sequence}:${index}`,
        kind: normalizedKind,
        text: textValue(source.text),
        turnId: nonEmptyText(source.turn_id) ?? undefined,
        toolCallId: nonEmptyText(source.tool_call_id) ?? undefined,
        toolName: nonEmptyText(source.tool_name) ?? undefined,
        status: normalizedKind === "tool" ? (source.status === "failed" || source.status === "error" || source.status === "cancelled" ? "failed" : "completed") : "completed",
        isError: source.is_error === true,
        sequence,
      };
    });
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

function resultRecord(value: unknown): Record<string, JsonValue> {
  return asRecord(value) ?? {};
}

export function applyProjectOpened(state: RendererState, result: unknown): RendererState {
  const source = resultRecord(result);
  const project = resultRecord(source.project);
  const path = normalizeProjectPath(project.path);
  if (!path) return { ...state, runtimeError: "Project path is unavailable" };
  const existing = state.projects.find((item) => item.projectKey === path);
  const incomingSessions = Array.isArray(source.sessions)
    ? source.sessions.map((item) => normalizeSession(item, path)).filter((item): item is SessionSummary => item !== null)
    : [];
  const sessions = preserveSessionOrder(existing?.sessions ?? [], incomingSessions);
  const nextRun = normalizeRun(source.run);
  return {
    ...permissionUnknownAtRunBoundary(replaceProject(state, { ...projectFromPath(path, existing), sessions: applySessionPins(sessions, path, state.pinnedSessions), catalogFresh: true }), nextRun),
    selectedProjectKey: path,
    selectedSessionId: null,
    timeline: [],
    todo: [],
    activeTurn: false,
    turnStatus: "idle",
    pendingInteraction: null,
    runtimeState: "ready",
    runtimeError: null,
    view: "chat",
  };
}

export function applyCatalogRefreshed(state: RendererState, projectKey: string, values: readonly unknown[]): RendererState {
  const previous = state.projects.find((item) => item.projectKey === projectKey)?.sessions ?? [];
  const incoming = values.map((item) => normalizeSession(item, projectKey)).filter((item): item is SessionSummary => item !== null);
  const sessions = applySessionPins(preserveSessionOrder(previous, incoming), projectKey, state.pinnedSessions);
  const replaced = replaceProject(state, projectFromPath(projectKey, state.projects.find((item) => item.projectKey === projectKey)));
  return {
    ...replaced,
    projects: replaced.projects.map((item) => item.projectKey === projectKey ? { ...item, sessions, catalogFresh: true } : item),
  };
}

export function applySessionResumed(state: RendererState, result: unknown): RendererState {
  const source = resultRecord(result);
  const sessionId = nonEmptyText(source.session_id);
  if (!sessionId) return { ...state, runtimeError: "Session identity is unavailable" };
  const projectKey = state.selectedProjectKey;
  const boundary = permissionUnknownAtRunBoundary(state, source.run);
  return {
    ...boundary,
    selectedSessionId: sessionId,
    timeline: replayToTimeline(Array.isArray(source.replay) ? source.replay : []),
    todo: [],
    activeTurn: false,
    turnStatus: "idle",
    pendingInteraction: null,
    runtimeError: null,
    notice: "Session resumed",
    ...(projectKey ? { projects: state.projects.map((project) => project.projectKey === projectKey ? { ...project, sessions: project.sessions.map((session) => session.session_id === sessionId ? { ...session } : session) } : project) } : {}),
  };
}

/**
 * Apply the minimal SessionMutation projection without sorting either the
 * source or destination catalog.  Session selection and mutation responses
 * must never make an ordinary row jump to the head of a list.
 */
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
  // Mutation responses are intentionally minimal.  Merge them onto the
  // catalog row so a rename/move cannot erase the preview, checkpoint, or
  // transcript metadata that the catalog already supplied.
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
  return { ...state, projects, pinnedSessions };
}

function appendStatus(state: RendererState, text: string, status: TimelineStatus = "info"): RendererState {
  const id = `status:${state.nextStatusId}`;
  return {
    ...state,
    timeline: [...state.timeline, { id, kind: "status", text, status }],
    nextStatusId: state.nextStatusId + 1,
  };
}

function eventId(prefix: string, event: Record<string, JsonValue>): string {
  return `${prefix}:${textValue(event.run_id)}:${textValue(event.turn_id)}:${textValue(event.message_id) || textValue(event.tool_call_id) || textValue(event.batch_id)}`;
}

function messageText(value: unknown): string {
  const source = asRecord(value);
  const parts = source?.parts;
  if (!Array.isArray(parts)) return textValue(source?.text);
  return parts
    .map((part) => {
      const item = asRecord(part);
      return item?.type === "text" ? textValue(item.text) : "";
    })
    .join("");
}

function messageReasoning(value: unknown): string {
  const source = asRecord(value);
  const parts = source?.parts;
  if (!Array.isArray(parts)) return "";
  return parts
    .map((part) => {
      const item = asRecord(part);
      return item?.type === "reasoning" ? textValue(item.text) : "";
    })
    .join("");
}

function updateTimelineEntry(state: RendererState, id: string, update: (entry: TimelineEntry) => TimelineEntry): RendererState {
  const index = state.timeline.findIndex((entry) => entry.id === id);
  if (index < 0) return state;
  const timeline = [...state.timeline];
  timeline[index] = update(timeline[index]);
  return { ...state, timeline };
}

function settleTerminalTurn(state: RendererState, turnId: string): RendererState {
  return {
    ...state,
    timeline: state.timeline
      .map((entry) => entry.turnId === turnId && entry.kind === "reasoning" && entry.streaming
        ? { ...entry, streaming: false, status: "completed" as TimelineStatus }
        : entry)
      .filter((entry) => !(entry.turnId === turnId && entry.kind === "assistant" && entry.streaming)),
  };
}

function updateAssistantFinal(state: RendererState, event: Record<string, JsonValue>, text: string): RendererState {
  const messageId = textValue(event.message_id);
  const id = eventId("assistant", event);
  const current = state.timeline.findIndex((entry) => entry.id === id);
  if (current >= 0) {
    return updateTimelineEntry(state, id, (entry) => ({ ...entry, text, status: "completed", streaming: false }));
  }
  const previousAssistant = [...state.timeline].reverse().find((entry) => entry.kind === "assistant" && entry.turnId === textValue(event.turn_id) && entry.streaming);
  if (previousAssistant) {
    return updateTimelineEntry(state, previousAssistant.id, (entry) => ({ ...entry, text, messageId: messageId || entry.messageId, status: "completed", streaming: false }));
  }
  return {
    ...state,
    timeline: [...state.timeline, { id, kind: "assistant", text, turnId: textValue(event.turn_id), messageId: messageId || undefined, status: "completed", streaming: false }],
  };
}

function reduceAgentEvent(state: RendererState, event: AgentEvent): RendererState {
  const payload = event as Record<string, JsonValue>;
  const type = textValue(payload.type);
  const turnId = textValue(payload.turn_id);
  const eventRunId = nonEmptyText(payload.run_id);
  if (eventRunId && state.ignoredRunIds.includes(eventRunId)) return state;
  if (eventRunId && state.run?.run_id && eventRunId !== state.run.run_id) return state;
  if (type === "runtime_state") {
    const runtimeState = payload.state;
    const allowed: RuntimeStateName[] = ["booting", "ready", "configuration_required", "failed", "stopping", "stopped"];
    return { ...state, runtimeState: allowed.includes(runtimeState as RuntimeStateName) ? runtimeState as RuntimeStateName : state.runtimeState };
  }
  if (type === "runtime_diagnostic") return { ...state, diagnostics: [...state.diagnostics, "Python Runtime emitted a diagnostic"].slice(-10) };
  if (type === "turn_started") {
    const text = messageText(payload.message);
    const next: RendererState = {
      ...state,
      activeTurn: true,
      turnStatus: "running",
      run: { ...(state.run ?? {}), run_id: textValue(payload.run_id), turn_id: turnId, status: "running" },
      runtimeError: null,
      completionBlocked: null,
      notice: null,
      pendingInteraction: null,
    };
    if (!text) return next;
    const id = `user:${textValue(payload.message_id) || turnId}`;
    return next.timeline.some((entry) => entry.id === id) ? next : { ...next, timeline: [...next.timeline, { id, kind: "user", text, turnId, messageId: textValue(payload.message_id) || undefined, status: "completed" }] };
  }
  if (type === "reasoning_started") {
    const id = eventId("reasoning", payload);
    if (state.timeline.some((entry) => entry.id === id)) return state;
    return { ...state, timeline: [...state.timeline, { id, kind: "reasoning", text: "", turnId, messageId: textValue(payload.message_id) || undefined, status: "streaming", streaming: true }] };
  }
  if (type === "reasoning_delta") {
    const id = eventId("reasoning", payload);
    const existing = state.timeline.find((entry) => entry.id === id);
    if (existing) return updateTimelineEntry(state, id, (entry) => ({ ...entry, text: entry.text + textValue(payload.text), streaming: true }));
    return { ...state, timeline: [...state.timeline, { id, kind: "reasoning", text: textValue(payload.text), turnId, messageId: textValue(payload.message_id) || undefined, status: "streaming", streaming: true }] };
  }
  if (type === "reasoning_finished") {
    const id = eventId("reasoning", payload);
    return updateTimelineEntry(state, id, (entry) => ({ ...entry, streaming: false, status: "completed" }));
  }
  if (type === "assistant_message_delta") {
    const id = eventId("assistant", payload);
    const text = textValue(payload.text);
    const reasoningClosed = { ...state, timeline: state.timeline.map((entry) => entry.turnId === turnId && entry.kind === "reasoning" ? { ...entry, streaming: false, status: "completed" as TimelineStatus } : entry) };
    const existing = reasoningClosed.timeline.find((entry) => entry.id === id);
    if (existing) return updateTimelineEntry(reasoningClosed, id, (entry) => ({ ...entry, text: entry.text + text, status: "streaming", streaming: true }));
    return { ...reasoningClosed, timeline: [...reasoningClosed.timeline, { id, kind: "assistant", text, turnId, messageId: textValue(payload.message_id) || undefined, status: "streaming", streaming: true }] };
  }
  if (type === "assistant_message_completed") {
    let next = { ...state, timeline: state.timeline.map((entry) => entry.turnId === turnId && entry.kind === "reasoning" ? { ...entry, streaming: false, status: "completed" as TimelineStatus } : entry) };
    const text = messageText(payload.message);
    const reasoning = messageReasoning(payload.message);
    if (reasoning && !next.timeline.some((entry) => entry.turnId === turnId && entry.kind === "reasoning" && entry.text === reasoning)) {
      next = { ...next, timeline: [...next.timeline, { id: `reasoning:${textValue(payload.run_id)}:${turnId}:${textValue(payload.message_id)}:complete`, kind: "reasoning", text: reasoning, turnId, messageId: textValue(payload.message_id) || undefined, status: "completed", streaming: false }] };
    }
    return updateAssistantFinal(next, payload, text);
  }
  if (type === "tool_started") {
    const id = eventId("tool", payload);
    const closedReasoning = { ...state, timeline: state.timeline.map((entry) => entry.turnId === turnId && entry.kind === "reasoning" ? { ...entry, streaming: false, status: "completed" as TimelineStatus } : entry) };
    if (closedReasoning.timeline.some((entry) => entry.id === id)) return closedReasoning;
    return { ...closedReasoning, timeline: [...closedReasoning.timeline, { id, kind: "tool", text: textValue(payload.tool_name), turnId, toolCallId: textValue(payload.tool_call_id) || undefined, toolName: textValue(payload.tool_name) || undefined, command: textValue(payload.command) || undefined, status: "running", streaming: false }] };
  }
  if (type === "tool_finished") {
    const id = eventId("tool", payload);
    const isError = payload.is_error === true;
    const status = isError ? "failed" : "completed";
    const existing = state.timeline.find((entry) => entry.id === id);
    if (existing) return updateTimelineEntry(state, id, (entry) => ({ ...entry, text: entry.text || textValue(payload.tool_name), status, isError }));
    return { ...state, timeline: [...state.timeline, { id, kind: "tool", text: textValue(payload.tool_name), turnId, toolCallId: textValue(payload.tool_call_id) || undefined, toolName: textValue(payload.tool_name) || undefined, command: textValue(payload.command) || undefined, status, isError }] };
  }
  if (type === "task_state_changed") {
    const taskState = asRecord(payload.task_state);
    const items: TodoItem[] = Array.isArray(taskState?.items)
      ? taskState.items
        .map((item) => asRecord(item))
        .filter((item): item is Record<string, JsonValue> => item !== null)
        .map((item) => {
          const status: TodoItem["status"] = item.status === "completed" || item.status === "in_progress" ? item.status : "pending";
          return { content: textValue(item.content), status };
        })
      : [];
    return { ...state, todo: items };
  }
  if (type === "plan_proposed") {
    return { ...state, timeline: [...state.timeline, { id: `plan:${textValue(payload.run_id)}:${turnId}:${textValue(payload.revision)}`, kind: "plan", text: textValue(payload.plan_text), turnId, status: "completed" }] };
  }
  if (type === "completion_blocked") {
    const reason = `Completion blocked: ${numberText(payload.unfinished_count)} unfinished task(s)`;
    return appendStatus({ ...state, completionBlocked: reason }, reason);
  }
  if (type === "user_steering_requested") return appendStatus(state, "Steering requested", "info");
  if (type === "user_steering_applied") return appendStatus(state, "Steering applied", "completed");
  if (type === "turn_pausing") return appendStatus({ ...state, turnStatus: "pausing" }, "Pausing…", "info");
  if (type === "user_input_requested") {
    return { ...state, pendingInteraction: { kind: "user_input_required", pauseId: textValue(payload.pause_id), runId: textValue(payload.run_id), turnId, toolCallId: textValue(payload.tool_call_id) || undefined, request: asRecord(payload.request) ?? undefined, reason: "user_input_required" }, turnStatus: "paused", activeTurn: true };
  }
  if (type === "turn_paused") {
    const pause = asRecord(payload.pause);
    if (!pause) return state;
    const kind = pause.kind;
    const interactionKind: InteractionKind = kind === "user_input_required" || kind === "provider_unavailable" || kind === "permission_required" || kind === "plan_review_required" ? kind : "user_requested";
    const request = asRecord(pause.user_input_request ?? pause.permission_request ?? pause.plan_review_request);
    const next = { ...state, pendingInteraction: { kind: interactionKind, pauseId: textValue(pause.pause_id), runId: textValue(pause.run_id), turnId: textValue(pause.turn_id), toolCallId: textValue(pause.tool_call_id) || undefined, request: request ?? undefined, reason: textValue(pause.reason), iteration: typeof pause.iteration === "number" ? pause.iteration : undefined }, turnStatus: "paused" as const, activeTurn: true };
    const label = interactionKind === "permission_required" ? "permission" : interactionKind === "plan_review_required" ? "plan review" : interactionKind === "provider_unavailable" ? "provider retry" : interactionKind === "user_input_required" ? "user input" : "turn pause";
    return appendStatus(next, `Waiting for ${label}`, "info");
  }
  if (type === "turn_resumed") return appendStatus({ ...state, pendingInteraction: null, turnStatus: "running", activeTurn: true }, "Interaction answered", "info");
  if (type === "usage_updated") return { ...state, run: { ...(state.run ?? {}), usage: asRecord(payload.usage) ?? undefined } };
  if (type === "behavior_mode_changed") return { ...state, run: { ...(state.run ?? {}), behavior_mode: textValue(payload.behavior_mode) } };
  if (type === "turn_completed") {
    const timeline = state.timeline
      .map((entry) => entry.turnId === turnId && entry.kind === "reasoning" && entry.streaming
        ? { ...entry, streaming: false, status: "completed" as TimelineStatus }
        : entry)
      .filter((entry) => !(entry.turnId === turnId && entry.kind === "assistant" && entry.streaming));
    let next = { ...state, timeline };
    next = { ...next, activeTurn: false, turnStatus: "completed", pendingInteraction: null, completionBlocked: null, run: { ...(next.run ?? {}), run_id: textValue(payload.run_id), turn_id: turnId, status: "completed", termination_reason: "final_answer" } };
    const finalText = textValue(payload.final_text);
    if (finalText) {
      const lastAssistant = [...next.timeline].reverse().find((entry) => entry.kind === "assistant" && entry.turnId === turnId);
      if (lastAssistant) next = updateTimelineEntry(next, lastAssistant.id, (entry) => ({ ...entry, text: finalText, status: "completed", streaming: false }));
      else next = { ...next, timeline: [...next.timeline, { id: `assistant:final:${textValue(payload.run_id)}:${turnId}`, kind: "assistant", text: finalText, turnId, status: "completed", streaming: false }] };
    }
    return next;
  }
  if (type === "turn_failed" || type === "turn_cancelled") {
    const failed = type === "turn_failed";
    const next = settleTerminalTurn(state, turnId);
    const reason = failed ? `Turn failed: ${textValue(payload.failure_reason) || textValue(payload.termination_reason) || "runtime error"}` : "Turn cancelled";
    return appendStatus({ ...next, activeTurn: false, turnStatus: failed ? "failed" : "cancelled", pendingInteraction: null, run: { ...(next.run ?? {}), run_id: textValue(payload.run_id), turn_id: turnId, status: failed ? "failed" : "cancelled", termination_reason: textValue(payload.termination_reason) || (failed ? "internal_error" : "user_cancelled") } }, reason, failed ? "failed" : "cancelled");
  }
  return state;
}

export type RendererAction =
  | { type: "hydrate_preferences"; preferences: Partial<DesktopPreferences> }
  | { type: "runtime_state"; state: RuntimeStateName; error?: string | null }
  | { type: "runtime_initialized"; result: unknown }
  | { type: "status_loaded"; result: unknown }
  | { type: "runtime_error"; message: string; state?: RuntimeStateName }
  | { type: "project_opened"; result: unknown }
  | { type: "catalog_refreshed"; projectKey: string; sessions: unknown[] }
  | { type: "session_resumed"; result: unknown }
  | { type: "session_mutated"; sourceProjectKey: string; result: unknown }
  | { type: "session_new"; sessionId: string; run: unknown }
  | { type: "agent_event"; event: AgentEvent }
  | { type: "interaction_submitting"; value: boolean }
  | { type: "command_candidates"; result: unknown }
  | { type: "model_candidates"; values: string[] }
  | { type: "turn_accepted"; run: unknown; steering: boolean; text?: string }
  | { type: "command_result"; result: unknown }
  | { type: "composer_text"; text: string }
  | { type: "clear_timeline" }
  | { type: "workspace_cleared" }
  | { type: "notice"; text: string | null }
  | { type: "set_theme"; theme: ThemePreference }
  | { type: "set_panel_mode"; panelMode: PanelModePreference }
  | { type: "set_view"; view: "chat" | "settings" }
  | { type: "settings_loaded"; configuration: ConfigurationView }
  | { type: "settings_error"; message: string | null }
  | { type: "settings_saving"; value: boolean };

export function reduceRendererState(state: RendererState, action: RendererAction): RendererState {
  switch (action.type) {
    case "hydrate_preferences": {
      const preferences = action.preferences;
      const hasRecent = Array.isArray(preferences.recentProjects);
      const recent = preferences.recentProjects ?? [];
      const aliases = preferences.projectAliases ?? {};
      const hasAliases = preferences.projectAliases !== undefined;
      const hasPinned = preferences.pinnedProjectKeys !== undefined;
      const pinned = new Set(preferences.pinnedProjectKeys ?? []);
      const requestedPinnedSessions = preferences.pinnedSessions ?? state.pinnedSessions;
      const sourceProjects = hasRecent ? recent : state.projects;
      const projects = sourceProjects
        .filter((item): item is { path: string; alias?: string; pinned?: boolean; lastOpenedAt?: string } => !!item && typeof item.path === "string")
        .map((item) => {
          const existing = state.projects.find((project) => project.projectKey === item.path);
          return {
            path: item.path,
            projectKey: item.path,
            alias: hasAliases ? aliases[item.path] || item.alias || item.path.split(/[\\/]/u).filter(Boolean).pop() || item.path : existing?.alias || item.alias || item.path.split(/[\\/]/u).filter(Boolean).pop() || item.path,
            pinned: hasPinned ? pinned.has(item.path) || item.pinned === true : existing?.pinned ?? item.pinned === true,
            lastOpenedAt: item.lastOpenedAt ?? existing?.lastOpenedAt,
            sessions: applySessionPins(existing?.sessions ?? [], item.path, requestedPinnedSessions),
            catalogFresh: existing?.catalogFresh ?? false,
          };
        });
      const pinnedProjectKeys = new Set(projects.filter((project) => project.pinned).map((project) => project.projectKey));
      const pinnedSessions = requestedPinnedSessions.filter((item) => !pinnedProjectKeys.has(item.projectKey));
      const normalizedProjects = projects.map((project) => ({ ...project, sessions: applySessionPins(project.sessions, project.projectKey, pinnedSessions) }));
      return {
        ...state,
        projects: normalizedProjects,
        pinnedSessions,
        expandedProjects: preferences.expandedProjects !== undefined ? { ...preferences.expandedProjects } : state.expandedProjects,
        selectedProjectKey: preferences.selectedProjectKey !== undefined ? preferences.selectedProjectKey ?? null : state.selectedProjectKey,
        selectedSessionId: preferences.selectedSessionId !== undefined ? preferences.selectedSessionId ?? null : state.selectedSessionId,
        theme: preferences.theme !== undefined ? (preferences.theme === "dark" || preferences.theme === "light" ? preferences.theme : "system") : state.theme,
        language: preferences.language !== undefined ? (preferences.language === "en" ? "en" : "zh-CN") : state.language,
        panelMode: preferences.panelMode !== undefined ? (preferences.panelMode === "hidden" || preferences.panelMode === "floating" ? preferences.panelMode : "docked") : state.panelMode,
      };
    }
    case "runtime_state":
      return { ...state, runtimeState: action.state, runtimeError: action.error ?? state.runtimeError };
    case "runtime_initialized": {
      const source = resultRecord(action.result);
      const run = normalizeRun(source.run);
      return {
        ...state,
        runtimeState: "ready",
        runtimeError: null,
        ...(run ? { run, permissionMode: permissionModeOf(run) } : { permissionMode: "unknown" as const }),
      };
    }
    case "status_loaded": {
      const source = resultRecord(action.result);
      const application = asRecord(source.application);
      const currentModelRef = nonEmptyText(application?.current_model);
      return currentModelRef ? { ...state, currentModelRef } : state;
    }
    case "runtime_error":
      return { ...state, runtimeState: action.state ?? "failed", runtimeError: action.message };
    case "project_opened":
      return applyProjectOpened(state, action.result);
    case "catalog_refreshed":
      return applyCatalogRefreshed(state, action.projectKey, action.sessions);
    case "session_resumed":
      return applySessionResumed(state, action.result);
    case "session_mutated":
      return applySessionMutation(state, action.sourceProjectKey, action.result);
    case "session_new":
      return { ...permissionUnknownAtRunBoundary(state, action.run), selectedSessionId: action.sessionId, timeline: [], todo: [], activeTurn: false, turnStatus: "idle", pendingInteraction: null, notice: "New Session", runtimeError: null };
    case "agent_event":
      return reduceAgentEvent(state, action.event);
    case "interaction_submitting":
      return state.pendingInteraction ? { ...state, pendingInteraction: { ...state.pendingInteraction, submitting: action.value } } : state;
    case "command_candidates": {
      const source = resultRecord(action.result);
      const candidates = Array.isArray(source.candidates) ? source.candidates.map((item) => asRecord(item)).filter((item): item is Record<string, JsonValue> => item !== null).map((item) => ({ ...item, value: textValue(item.value) })) : [];
      const argumentCandidates = Array.isArray(source.argument_candidates) ? source.argument_candidates.filter((item): item is string => typeof item === "string") : [];
      return { ...state, commandCandidates: candidates, argumentCandidates, commandUsage: textValue(source.usage) || null, commandArgumentPrompt: textValue(source.argument_prompt) || null };
    }
    case "model_candidates":
      return { ...state, modelCandidates: [...action.values], modelPickerOpen: true };
    case "turn_accepted": {
      const acceptedRun = normalizeRun(action.run);
      const next = { ...state, run: acceptedRun ?? state.run, permissionMode: acceptedRun ? permissionModeOf(acceptedRun) : state.permissionMode, activeTurn: true, turnStatus: "running" as const, composerText: "", ...(action.steering ? {} : { pendingInteraction: null }) };
      if (!action.steering || !action.text?.trim()) return next;
      return { ...next, timeline: [...next.timeline, { id: `steering:${next.run?.run_id ?? "run"}:${next.run?.turn_id ?? "turn"}:${next.nextStatusId}`, kind: "steering", text: action.text, turnId: next.run?.turn_id, status: "completed" }], nextStatusId: next.nextStatusId + 1 };
    }
    case "command_result": {
      const source = resultRecord(action.result);
      const output = textValue(source.output) || textValue(source.error);
      const actionValue = asRecord(source.ui_action);
      const sessionChanged = actionValue?.type === "session_changed";
      if (sessionChanged && typeof actionValue.session_id === "string") {
        const next = actionValue.restored === true ? applySessionResumed(state, { session_id: actionValue.session_id, replay: source.replay, run: source.run }) : { ...permissionUnknownAtRunBoundary(state, source.run), selectedSessionId: actionValue.session_id, timeline: [], todo: [], activeTurn: false, turnStatus: "idle" as const, pendingInteraction: null };
        return { ...next, commandOutput: output || null, notice: output || null, composerText: "", modelPickerOpen: false };
      }
      if (actionValue?.type === "clear_transcript") return { ...state, timeline: [], commandOutput: output || null, composerText: "" };
      if (actionValue?.type === "behavior_mode_selected" || actionValue?.type === "permission_mode_selected" || actionValue?.type === "model_selected") {
        const projectedRun = normalizeRun(source.run);
        const projectedPermission = permissionModeOf(projectedRun);
        const permissionMode = projectedPermission !== "unknown"
          ? projectedPermission
          : actionValue.type === "permission_mode_selected" && (actionValue.mode === "default" || actionValue.mode === "auto" || actionValue.mode === "full_access")
            ? actionValue.mode
            : state.permissionMode;
        const run = actionValue.type === "behavior_mode_selected" && typeof actionValue.mode === "string"
          ? { ...(state.run ?? {}), behavior_mode: actionValue.mode }
          : projectedRun ?? state.run;
        const currentModelRef = actionValue.type === "model_selected" ? nonEmptyText(actionValue.model_ref) ?? state.currentModelRef : state.currentModelRef;
        return { ...state, run, permissionMode, currentModelRef, commandOutput: output || null, notice: actionValue.warning ? textValue(actionValue.warning) : output || null, composerText: "", modelPickerOpen: false };
      }
      if (actionValue?.type === "open_model_picker") return { ...state, modelPickerOpen: true, commandOutput: output || null, notice: output || null, composerText: "" };
      return { ...state, commandOutput: output || null, notice: output || null, composerText: "" };
    }
    case "composer_text":
      return { ...state, composerText: action.text };
    case "clear_timeline":
      return { ...state, timeline: [] };
    case "workspace_cleared":
      return {
        ...state,
        selectedProjectKey: null,
        selectedSessionId: null,
        timeline: [],
        todo: [],
        run: null,
        permissionMode: "unknown",
        currentModelRef: null,
        activeTurn: false,
        turnStatus: "idle",
        pendingInteraction: null,
        completionBlocked: null,
        commandCandidates: [],
        argumentCandidates: [],
        commandUsage: null,
        commandArgumentPrompt: null,
        commandOutput: null,
        composerText: "",
        modelCandidates: [],
        modelPickerOpen: false,
        notice: null,
        runtimeError: null,
        runtimeState: "stopped",
        ignoredRunIds: state.run?.run_id
          ? [...state.ignoredRunIds, state.run.run_id].slice(-20)
          : state.ignoredRunIds,
      };
    case "notice":
      return { ...state, notice: action.text };
    case "set_theme":
      return { ...state, theme: action.theme };
    case "set_panel_mode":
      return { ...state, panelMode: action.panelMode };
    case "set_view":
      return { ...state, view: action.view };
    case "settings_loaded":
      return { ...state, configuration: action.configuration, permissionMode: state.run ? state.permissionMode : "unknown", settingsLoaded: true, settingsError: null };
    case "settings_error":
      return { ...state, settingsError: action.message };
    case "settings_saving":
      return { ...state, settingsSaving: action.value };
  }
}

// Stable aliases keep reducer-oriented tests and future renderer composition
// code independent from the action/event implementation names.
export const rendererReducer = reduceRendererState;
export const reduceEvent = reduceAgentEvent;

export type { DesktopApi, DesktopPreferences, JsonObject };
