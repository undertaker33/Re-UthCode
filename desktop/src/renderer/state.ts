import type { AgentEvent, DesktopPreferences, DesktopApi, JsonObject, JsonValue, LanguagePreference, PanelModePreference, ThemePreference } from "../desktop-api";
import {
  DEFAULT_RUNTIME_PANEL_WIDTH,
  DEFAULT_SIDEBAR_WIDTH,
  RUNTIME_PANEL_WIDTH_MAX,
  RUNTIME_PANEL_WIDTH_MIN,
  SIDEBAR_WIDTH_MAX,
  SIDEBAR_WIDTH_MIN,
} from "../desktop-api";
import {
  asRecord,
  contextUsageAtBoundary,
  messageReasoning,
  messageText,
  normalizeCompactionStatus,
  normalizeContextUsage,
  normalizePendingInteraction,
  normalizeRun,
  normalizeTodo,
  permissionModeOf,
  replayToTimeline,
  resultRecord,
  runtimeStateFromProjection,
  sessionRuntimeFromSource,
} from "./state-normalization";
import { nonEmptyText, numberText, positiveInteger, textValue } from "./text-normalization";
import {
  applyProjectOpened,
  applySessionPins,
  applyCatalogRefreshed,
  applyRuntimeSnapshot,
  applySessionMutation,
  applySessionResumed,
  cacheVisibleRuntime,
  cloneSessionRuntime,
  emptyRuntimeBoundary,
  runtimeSnapshotFromState,
  runtimeStatus,
  sessionRuntimeKey,
  updateSessionRuntimeStatus,
  permissionUnknownAtRunBoundary,
  type SessionOrderReason,
} from "./state-session";

export type RuntimeStateName = "booting" | "restarting" | "ready" | "configuration_required" | "failed" | "stopping" | "stopped";
export type TimelineKind = "user" | "steering" | "reasoning" | "assistant" | "tool" | "plan" | "status";
export type TimelineStatus = "streaming" | "running" | "completed" | "failed" | "cancelled" | "info";
export type PermissionModeProjection = "unknown" | "default" | "auto" | "full_access";
export type ContextMeasurement = "estimate" | "exact" | "unavailable";
export type CompactionState = "idle" | "running" | "completed" | "no_change" | "failed" | "cancelled";
export type CompactionTrigger = "manual" | "auto" | "overflow";

/** Safe context usage projection returned by Application.status(). */
export interface ContextUsageProjection {
  used_tokens: number;
  budget_tokens: number;
  available: boolean;
  measurement: ContextMeasurement;
  source: string;
}

export type ProviderUsageStatus = "available" | "not_available";

export interface ProviderCacheUsageProjection {
  status: ProviderUsageStatus;
  tokens: number | null;
  provenance: string | null;
}

/** Safe terminal usage projection for the most recent Provider request. */
export interface ProviderRequestUsageProjection {
  status: ProviderUsageStatus;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  cache_read: ProviderCacheUsageProjection;
  cache_write: ProviderCacheUsageProjection;
}

function nonNegativeToken(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : null;
}

function normalizeProviderCacheUsage(value: unknown): ProviderCacheUsageProjection | null {
  const source = asRecord(value);
  if (!source || (source.status !== "available" && source.status !== "not_available")) return null;
  const tokens = source.tokens === null ? null : nonNegativeToken(source.tokens);
  const provenance = source.provenance === null ? null : nonEmptyText(source.provenance);
  if (source.status === "available" && (tokens === null || provenance === null)) return null;
  if (source.status === "not_available" && (tokens !== null || provenance !== null)) return null;
  return { status: source.status, tokens, provenance };
}

export function providerRequestUsageAtBoundary(): ProviderRequestUsageProjection {
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

/** Normalize only the safe usage fields exposed by Application.status(). */
export function normalizeProviderRequestUsage(value: unknown): ProviderRequestUsageProjection {
  const source = asRecord(value);
  if (!source || (source.status !== "available" && source.status !== "not_available")) return providerRequestUsageAtBoundary();
  const fields = ["input_tokens", "output_tokens", "total_tokens"] as const;
  const values = fields.map((field) => source[field] === null ? null : nonNegativeToken(source[field]));
  if (values.some((value, index) => value === null && source[fields[index]] !== null)) return providerRequestUsageAtBoundary();
  const cacheRead = normalizeProviderCacheUsage(source.cache_read);
  const cacheWrite = normalizeProviderCacheUsage(source.cache_write);
  if (!cacheRead || !cacheWrite) return providerRequestUsageAtBoundary();
  const available = source.status === "available";
  if (available && values.every((value) => value === null) && cacheRead.status === "not_available" && cacheWrite.status === "not_available") return providerRequestUsageAtBoundary();
  if (!available && (values.some((value) => value !== null) || cacheRead.status === "available" || cacheWrite.status === "available")) return providerRequestUsageAtBoundary();
  return {
    status: source.status,
    input_tokens: values[0],
    output_tokens: values[1],
    total_tokens: values[2],
    cache_read: cacheRead,
    cache_write: cacheWrite,
  };
}

function providerRequestUsageFromResult(value: unknown): ProviderRequestUsageProjection | undefined {
  const source = resultRecord(value);
  const application = asRecord(source.application);
  if (!application || !Object.prototype.hasOwnProperty.call(application, "last_provider_request_usage")) return undefined;
  return normalizeProviderRequestUsage(application.last_provider_request_usage);
}

export interface CompactionStatusProjection {
  state: CompactionState;
  trigger: CompactionTrigger | null;
  changed: boolean | null;
}

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
  model_ref?: string | null;
  /** Live status supplied by the bridge without changing catalog order. */
  runtime_status?: "idle" | "running" | "waiting" | "completed" | "failed" | "cancelled";
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
  runId?: string;
  turnId?: string;
  iteration?: number;
  messageId?: string;
  toolCallId?: string;
  toolName?: string;
  command?: string;
  status?: TimelineStatus;
  isError?: boolean;
  sequence?: number;
  streaming?: boolean;
  startedAt?: number;
  endedAt?: number;
  planRevision?: number;
  planState?: "draft" | "final" | "failed" | "cancelled";
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
  /** Latest TaskState iteration applied for the visible Turn. */
  todoIteration: number;
  run: RunProjection | null;
  contextUsage: ContextUsageProjection;
  lastProviderRequestUsage: ProviderRequestUsageProjection;
  compactionStatus: CompactionStatusProjection;
  permissionMode: PermissionModeProjection;
  pinnedSessions: DesktopPreferences["pinnedSessions"];
  expandedProjects: DesktopPreferences["expandedProjects"];
  currentModelRef: string | null;
  /** Durable model identity keyed by Session; never inferred from row order. */
  sessionModels: Record<string, string>;
  /** Per-session live projection.  Events are authoritative even off-screen. */
  sessionRuntime: Record<string, SessionRuntimeSnapshot>;
  modelCandidates: string[];
  modelPickerOpen: boolean;
  activeTurn: boolean;
  /** A terminal event was rendered, but Application has not released its active handle yet. */
  terminalStatusPending: boolean;
  /** A Session rename/move RPC is the single in-flight mutation authority. */
  sessionMutationBusy: boolean;
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
  sidebarWidth: number;
  runtimePanelWidth: number;
  /** Renderer-only presentation state; never loaded from or written to preferences. */
  focusMode: boolean;
  theme: ThemePreference;
  language: LanguagePreference;
  view: "chat" | "settings";
  configuration: ConfigurationView | null;
  settingsError: string | null;
  settingsSaving: boolean;
  settingsLoaded: boolean;
  ignoredRunIds: string[];
  /** Increments only when the visible Session/Project timeline is replaced. */
  sessionViewRevision: number;
  nextStatusId: number;
}

export interface SessionRuntimeSnapshot {
  timeline: TimelineEntry[];
  todo: TodoItem[];
  todoIteration: number;
  run: RunProjection | null;
  contextUsage: ContextUsageProjection;
  /** The latest Provider usage belongs to this Session projection. */
  lastProviderRequestUsage?: ProviderRequestUsageProjection;
  compactionStatus: CompactionStatusProjection;
  permissionMode: PermissionModeProjection;
  activeTurn: boolean;
  terminalStatusPending: boolean;
  turnStatus: RendererState["turnStatus"];
  pendingInteraction: PendingInteraction | null;
  completionBlocked: string | null;
}

export const DEFAULT_RENDERER_STATE: RendererState = {
  runtimeState: "booting",
  runtimeError: null,
  projects: [],
  selectedProjectKey: null,
  selectedSessionId: null,
  timeline: [],
  todo: [],
  todoIteration: 0,
  run: null,
  contextUsage: { used_tokens: 0, budget_tokens: 0, available: false, measurement: "unavailable", source: "unavailable" },
  lastProviderRequestUsage: providerRequestUsageAtBoundary(),
  compactionStatus: { state: "idle", trigger: null, changed: null },
  permissionMode: "unknown",
  pinnedSessions: [],
  expandedProjects: {},
  currentModelRef: null,
  sessionModels: {},
  sessionRuntime: {},
  modelCandidates: [],
  modelPickerOpen: false,
  activeTurn: false,
  terminalStatusPending: false,
  sessionMutationBusy: false,
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
  sidebarWidth: DEFAULT_SIDEBAR_WIDTH,
  runtimePanelWidth: DEFAULT_RUNTIME_PANEL_WIDTH,
  focusMode: false,
  theme: "system",
  language: "zh-CN",
  view: "chat",
  configuration: null,
  settingsError: null,
  settingsSaving: false,
  settingsLoaded: false,
  ignoredRunIds: [],
  sessionViewRevision: 0,
  nextStatusId: 1,
};

export function createInitialState(overrides: Partial<RendererState> = {}): RendererState {
  return {
    ...DEFAULT_RENDERER_STATE,
    ...overrides,
    lastProviderRequestUsage: cloneProviderRequestUsage(overrides.lastProviderRequestUsage ?? DEFAULT_RENDERER_STATE.lastProviderRequestUsage),
    projects: overrides.projects?.map((project) => ({ ...project, sessions: [...project.sessions] })) ?? [],
    expandedProjects: overrides.expandedProjects ? { ...overrides.expandedProjects } : {},
    timeline: overrides.timeline?.map((entry) => ({ ...entry })) ?? [],
    todo: overrides.todo?.map((item) => ({ ...item })) ?? [],
    diagnostics: overrides.diagnostics ? [...overrides.diagnostics] : [],
    ignoredRunIds: overrides.ignoredRunIds ? [...overrides.ignoredRunIds] : [],
    sessionModels: overrides.sessionModels ? { ...overrides.sessionModels } : {},
    sessionRuntime: overrides.sessionRuntime
      ? Object.fromEntries(Object.entries(overrides.sessionRuntime).map(([key, snapshot]) => [key, cloneSessionRuntime(snapshot)]))
      : {},
  };
}

function appendStatus(state: RendererState, text: string, status: TimelineStatus = "info"): RendererState {
  const id = `status:${state.nextStatusId}`;
  return {
    ...state,
    timeline: [...state.timeline, { id, kind: "status", text, status }],
    nextStatusId: state.nextStatusId + 1,
  };
}

/**
 * Keep the visible Context ring moving between throttled status snapshots.
 * The Application remains authoritative; this small projection is replaced
 * by the next provider-counted status and is never used as a hard gate.
 */
function applyLiveContextDelta(state: RendererState, text: string): RendererState {
  const usage = state.contextUsage;
  if (!usage.available || usage.budget_tokens <= 0 || !text) return state;
  const delta = Math.max(1, Math.ceil([...text].length / 4));
  return {
    ...state,
    contextUsage: {
      ...usage,
      used_tokens: Math.min(usage.budget_tokens, usage.used_tokens + delta),
      measurement: "estimate",
      source: "turn",
    },
  };
}

function eventId(prefix: string, event: Record<string, JsonValue>): string {
  return `${prefix}:${textValue(event.run_id)}:${textValue(event.turn_id)}:${textValue(event.message_id) || textValue(event.tool_call_id) || textValue(event.batch_id)}`;
}

function updateTimelineEntry(state: RendererState, id: string, update: (entry: TimelineEntry) => TimelineEntry): RendererState {
  const index = state.timeline.findIndex((entry) => entry.id === id);
  if (index < 0) return state;
  const timeline = [...state.timeline];
  timeline[index] = update(timeline[index]);
  return { ...state, timeline };
}

function settlePlanEntries(state: RendererState, runId: string, turnId: string, status: "completed" | "failed" | "cancelled"): RendererState {
  return {
    ...state,
    timeline: state.timeline.map((entry) => {
      if (entry.kind !== "plan" || entry.turnId !== turnId || (entry.runId && entry.runId !== runId) || !entry.streaming) return entry;
      return {
        ...entry,
        streaming: false,
        status,
        planState: status === "failed" ? "failed" : status === "cancelled" ? "cancelled" : "final",
      };
    }),
  };
}

function settleTerminalTurn(state: RendererState, runId: string, turnId: string, planStatus: "completed" | "failed" | "cancelled" = "completed"): RendererState {
  const settledPlans = settlePlanEntries(state, runId, turnId, planStatus);
  const retainFailedAssistant = planStatus === "failed";
  return {
    ...settledPlans,
    timeline: settledPlans.timeline
      .map((entry) => entry.turnId === turnId && (!entry.runId || entry.runId === runId) && (entry.kind === "reasoning" || (retainFailedAssistant && entry.kind === "assistant")) && entry.streaming
        ? { ...entry, streaming: false, status: "completed" as TimelineStatus }
        : entry)
      .filter((entry) => !(entry.turnId === turnId && (!entry.runId || entry.runId === runId) && entry.kind === "assistant" && entry.streaming)),
  };
}

function planEntriesForIdentity(state: RendererState, runId: string, turnId: string, iteration: number): TimelineEntry[] {
  return state.timeline.filter((entry) => entry.kind === "plan" && entry.runId === runId && entry.turnId === turnId && entry.iteration === iteration);
}

function planTerminalForTool(state: RendererState, runId: string, turnId: string, iteration: number, toolCallId: string, status: "failed" | "cancelled"): RendererState {
  return {
    ...state,
    timeline: state.timeline.map((entry) => entry.kind === "plan" && entry.runId === runId && entry.turnId === turnId && entry.iteration === iteration && entry.toolCallId === toolCallId && entry.streaming
      ? { ...entry, streaming: false, status, planState: status === "failed" ? "failed" : "cancelled" }
      : entry),
  };
}

function updateAssistantFinal(state: RendererState, event: Record<string, JsonValue>, text: string): RendererState {
  const messageId = textValue(event.message_id);
  const id = eventId("assistant", event);
  const current = state.timeline.findIndex((entry) => entry.id === id);
  if (current >= 0) {
    if (state.timeline[current]?.status === "completed" && !state.timeline[current]?.streaming) return state;
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

function isSettledTurn(state: RendererState): boolean {
  return state.terminalStatusPending || state.turnStatus === "completed" || state.turnStatus === "failed" || state.turnStatus === "cancelled";
}

const IDENTITY_REQUIRED_EVENT_TYPES = new Set([
  "turn_started",
  "reasoning_started",
  "reasoning_delta",
  "reasoning_finished",
  "assistant_message_delta",
  "assistant_message_completed",
  "tool_started",
  "tool_finished",
  "task_state_changed",
  "plan_content_delta",
  "plan_proposed",
  "completion_blocked",
  "user_steering_requested",
  "user_steering_applied",
  "turn_pausing",
  "user_input_requested",
  "turn_paused",
  "turn_resumed",
  "turn_completed",
  "turn_failed",
  "turn_cancelled",
]);

const SETTLED_TURN_EVENT_TYPES = new Set([
  "reasoning_started",
  "reasoning_delta",
  "reasoning_finished",
  "assistant_message_delta",
  "assistant_message_completed",
  "tool_started",
  "tool_finished",
  "task_state_changed",
  "plan_content_delta",
  "plan_proposed",
  "completion_blocked",
  "user_steering_requested",
  "user_steering_applied",
  "turn_pausing",
  "user_input_requested",
  "turn_paused",
  "turn_resumed",
]);

function reduceAgentEvent(state: RendererState, event: AgentEvent): RendererState {
  const payload = event as Record<string, JsonValue>;
  const type = textValue(payload.type);
  const turnId = nonEmptyText(payload.turn_id) ?? "";
  const eventRunId = nonEmptyText(payload.run_id);
  const currentRunId = nonEmptyText(state.run?.run_id);
  const currentTurnId = nonEmptyText(state.run?.turn_id);
  if (eventRunId && state.ignoredRunIds.includes(eventRunId)) return state;
  if (eventRunId && currentRunId && eventRunId !== currentRunId) return state;
  // Agent events are scoped to a complete Run/Turn identity. Runtime-only
  // diagnostics are the sole unscoped events. Once the Application has
  // established the visible Turn, a missing or mismatched identity must not
  // mutate that Turn's projection.
  if (currentRunId && currentTurnId && IDENTITY_REQUIRED_EVENT_TYPES.has(type) && (!eventRunId || !turnId || eventRunId !== currentRunId || turnId !== currentTurnId)) return state;
  if (currentTurnId && IDENTITY_REQUIRED_EVENT_TYPES.has(type) && turnId !== currentTurnId) return state;
  if (isSettledTurn(state) && SETTLED_TURN_EVENT_TYPES.has(type)) return state;
  if (type === "runtime_state") {
    const runtimeState = payload.state;
    const allowed: RuntimeStateName[] = ["booting", "restarting", "ready", "configuration_required", "failed", "stopping", "stopped"];
    return { ...state, runtimeState: allowed.includes(runtimeState as RuntimeStateName) ? runtimeState as RuntimeStateName : state.runtimeState };
  }
  if (type === "runtime_diagnostic") return { ...state, diagnostics: [...state.diagnostics, "Python Runtime emitted a diagnostic"].slice(-10) };
  if (type === "turn_started") {
    const text = messageText(payload.message);
    const next: RendererState = {
      ...state,
      activeTurn: true,
      terminalStatusPending: false,
      turnStatus: "running",
      run: { ...(state.run ?? {}), run_id: textValue(payload.run_id), turn_id: turnId, status: "running" },
      ...(currentRunId !== eventRunId || currentTurnId !== turnId ? { todo: [], todoIteration: 0 } : {}),
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
    const text = textValue(payload.text);
    const withEstimate = applyLiveContextDelta(state, text);
    const existing = withEstimate.timeline.find((entry) => entry.id === id);
    if (existing) {
      if (!existing.streaming) return state;
      return updateTimelineEntry(withEstimate, id, (entry) => ({ ...entry, text: entry.text + text, streaming: true }));
    }
    return { ...withEstimate, timeline: [...withEstimate.timeline, { id, kind: "reasoning", text, turnId, messageId: textValue(payload.message_id) || undefined, status: "streaming", streaming: true }] };
  }
  if (type === "reasoning_finished") {
    const id = eventId("reasoning", payload);
    return updateTimelineEntry(state, id, (entry) => ({ ...entry, streaming: false, status: "completed" }));
  }
  if (type === "assistant_message_delta") {
    const id = eventId("assistant", payload);
    const text = textValue(payload.text);
    const estimated = applyLiveContextDelta(state, text);
    const reasoningClosed = { ...estimated, timeline: estimated.timeline.map((entry) => entry.turnId === turnId && entry.kind === "reasoning" ? { ...entry, streaming: false, status: "completed" as TimelineStatus } : entry) };
    const existing = reasoningClosed.timeline.find((entry) => entry.id === id);
    if (existing) {
      if (!existing.streaming) return state;
      return updateTimelineEntry(reasoningClosed, id, (entry) => ({ ...entry, text: entry.text + text, status: "streaming", streaming: true }));
    }
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
    return { ...closedReasoning, timeline: [...closedReasoning.timeline, { id, kind: "tool", text: textValue(payload.tool_name), turnId, toolCallId: textValue(payload.tool_call_id) || undefined, toolName: textValue(payload.tool_name) || undefined, command: textValue(payload.command) || undefined, status: "running", streaming: false, startedAt: Date.now() }] };
  }
  if (type === "tool_finished") {
    const id = eventId("tool", payload);
    const rawStatus = textValue(payload.status).toLowerCase();
    const cancelled = rawStatus === "cancelled" || rawStatus === "canceled" || textValue(payload.termination_reason) === "user_cancelled";
    const failed = payload.is_error === true || rawStatus === "failed" || rawStatus === "error" || rawStatus === "rejected";
    const isError = failed;
    const status: TimelineStatus = cancelled ? "cancelled" : failed ? "failed" : "completed";
    const endedAt = Date.now();
    const existing = state.timeline.find((entry) => entry.id === id);
    if (existing && existing.status !== "running") return state;
    let next = existing
      ? updateTimelineEntry(state, id, (entry) => ({ ...entry, text: entry.text || textValue(payload.tool_name), status, isError, endedAt, startedAt: entry.startedAt ?? endedAt }))
      : { ...state, timeline: [...state.timeline, { id, kind: "tool" as const, text: textValue(payload.tool_name), turnId, toolCallId: textValue(payload.tool_call_id) || undefined, toolName: textValue(payload.tool_name) || undefined, command: textValue(payload.command) || undefined, status, isError, startedAt: endedAt, endedAt }] };
    const iteration = positiveInteger(payload.iteration);
    const toolCallId = nonEmptyText(payload.tool_call_id);
    if ((cancelled || failed) && eventRunId && iteration !== null && toolCallId) next = planTerminalForTool(next, eventRunId, turnId, iteration, toolCallId, cancelled ? "cancelled" : "failed");
    return applyLiveContextDelta(next, `${textValue(payload.tool_name)} ${textValue(payload.status)}`.trim());
  }
  if (type === "task_state_changed") {
    const iteration = positiveInteger(payload.iteration);
    if (state.todoIteration > 0 && iteration === null) return state;
    if (iteration !== null && iteration < state.todoIteration) return state;
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
    return applyLiveContextDelta(
      { ...state, todo: items, ...(iteration !== null ? { todoIteration: iteration } : {}) },
      JSON.stringify(taskState ?? {}),
    );
  }
  if (type === "plan_content_delta") {
    const runId = eventRunId;
    const iteration = positiveInteger(payload.iteration);
    const toolCallId = nonEmptyText(payload.tool_call_id);
    if (!runId || !turnId || iteration === null || !toolCallId) return state;
    const identityEntries = planEntriesForIdentity(state, runId, turnId, iteration);
    const finalized = identityEntries.find((entry) => !entry.streaming && entry.planState === "final");
    if (finalized) return state;
    const existing = identityEntries.find((entry) => entry.streaming && entry.toolCallId === toolCallId);
    if (existing) return applyLiveContextDelta(updateTimelineEntry(state, existing.id, (entry) => ({ ...entry, text: entry.text + textValue(payload.text), status: "streaming", streaming: true, planState: "draft" })), textValue(payload.text));
    const id = `plan-draft:${runId}:${turnId}:${iteration}:${toolCallId}`;
    if (state.timeline.some((entry) => entry.id === id)) return state;
    return applyLiveContextDelta({ ...state, timeline: [...state.timeline, { id, kind: "plan", text: textValue(payload.text), runId, turnId, iteration, toolCallId, status: "streaming", streaming: true, planState: "draft" }] }, textValue(payload.text));
  }
  if (type === "plan_proposed") {
    const runId = eventRunId;
    const iteration = positiveInteger(payload.iteration);
    const revision = positiveInteger(payload.revision);
    if (!runId || !turnId || iteration === null || revision === null) return state;
    const identityEntries = planEntriesForIdentity(state, runId, turnId, iteration);
    const drafts = identityEntries.filter((entry) => entry.streaming);
    const finalized = identityEntries.filter((entry) => !entry.streaming && entry.planState === "final");
    // PlanProposed has no tool_call_id in the public event contract.  If an
    // invalid stream presents two drafts for one identity, do not guess which
    // one it closes; leave both observable until a disambiguating event.
    if (drafts.length > 1 || (drafts.length > 0 && finalized.length > 0)) return state;
    const existing = drafts[0];
    if (existing) return updateTimelineEntry(state, existing.id, (entry) => ({ ...entry, text: textValue(payload.plan_text), status: "completed", streaming: false, planState: "final", planRevision: revision }));
    if (finalized.length > 1) return state;
    if (finalized[0]) {
      // A later authoritative revision for the same run/turn/iteration keeps one
      // visual Plan block; equal or older proposals cannot reopen it.
      if (finalized[0].planRevision === undefined || revision <= finalized[0].planRevision) return state;
      return updateTimelineEntry(state, finalized[0].id, (entry) => ({ ...entry, text: textValue(payload.plan_text), status: "completed", streaming: false, planState: "final", planRevision: revision }));
    }
    const id = `plan:${runId}:${turnId}:${iteration}`;
    if (state.timeline.some((entry) => entry.id === id)) return state;
    return { ...state, timeline: [...state.timeline, { id, kind: "plan", text: textValue(payload.plan_text), runId, turnId, iteration, status: "completed", streaming: false, planState: "final", planRevision: revision }] };
  }
  if (type === "completion_blocked") {
    const reason = `Completion blocked: ${numberText(payload.unfinished_count)} unfinished task(s)`;
    return appendStatus({ ...state, completionBlocked: reason }, reason);
  }
  if (type === "user_steering_requested") return appendStatus(state, "Steering requested", "info");
  if (type === "user_steering_applied") return appendStatus(state, "Steering applied", "completed");
  if (type === "turn_pausing") return appendStatus({ ...state, turnStatus: "pausing" }, "Pausing…", "info");
  if (type === "user_input_requested") {
    return { ...state, pendingInteraction: { kind: "user_input_required", pauseId: textValue(payload.pause_id), runId: textValue(payload.run_id), turnId, toolCallId: textValue(payload.tool_call_id) || undefined, request: asRecord(payload.request) ?? undefined, reason: "user_input_required" }, turnStatus: "paused", activeTurn: true, terminalStatusPending: false };
  }
  if (type === "turn_paused") {
    const pause = asRecord(payload.pause);
    if (!pause) return state;
    const kind = pause.kind;
    const interactionKind: InteractionKind = kind === "user_input_required" || kind === "provider_unavailable" || kind === "permission_required" || kind === "plan_review_required" ? kind : "user_requested";
    const request = asRecord(pause.user_input_request ?? pause.permission_request ?? pause.plan_review_request);
    const next = { ...state, pendingInteraction: { kind: interactionKind, pauseId: textValue(pause.pause_id), runId: textValue(pause.run_id), turnId: textValue(pause.turn_id), toolCallId: textValue(pause.tool_call_id) || undefined, request: request ?? undefined, reason: textValue(pause.reason), iteration: typeof pause.iteration === "number" ? pause.iteration : undefined }, turnStatus: "paused" as const, activeTurn: true, terminalStatusPending: false };
    const label = interactionKind === "permission_required" ? "permission" : interactionKind === "plan_review_required" ? "plan review" : interactionKind === "provider_unavailable" ? "provider retry" : interactionKind === "user_input_required" ? "user input" : "turn pause";
    return appendStatus(next, `Waiting for ${label}`, "info");
  }
  if (type === "turn_resumed") return appendStatus({ ...state, pendingInteraction: null, turnStatus: "running", activeTurn: true, terminalStatusPending: false }, "Interaction answered", "info");
  if (type === "usage_updated") {
    const usage = asRecord(payload.usage);
    // Core UsageUpdated is cumulative across every Provider request in the
    // Turn. It is valid Run accounting, but it is not the size of the current
    // request and therefore must not drive the Context ring after tool
    // continuations. Application context_status remains that projection's
    // authority.
    return { ...state, run: { ...(state.run ?? {}), usage: usage ?? undefined } };
  }
  if (type === "behavior_mode_changed") return { ...state, run: { ...(state.run ?? {}), behavior_mode: textValue(payload.behavior_mode) } };
  if (type === "turn_completed") {
    const runId = eventRunId ?? textValue(payload.run_id);
    const timeline = settlePlanEntries(state, runId, turnId, "completed").timeline
      .map((entry) => entry.turnId === turnId && (!entry.runId || entry.runId === runId) && entry.kind === "reasoning" && entry.streaming
        ? { ...entry, streaming: false, status: "completed" as TimelineStatus }
        : entry)
      .filter((entry) => !(entry.turnId === turnId && (!entry.runId || entry.runId === runId) && entry.kind === "assistant" && entry.streaming));
    let next = { ...state, timeline };
    next = { ...next, activeTurn: true, terminalStatusPending: true, turnStatus: "completed", pendingInteraction: null, completionBlocked: null, run: { ...(next.run ?? {}), run_id: runId, turn_id: turnId, status: "completed", termination_reason: "final_answer" } };
    const finalText = textValue(payload.final_text);
    if (finalText) {
      const lastAssistant = [...next.timeline].reverse().find((entry) => entry.kind === "assistant" && entry.turnId === turnId);
      if (lastAssistant) next = updateTimelineEntry(next, lastAssistant.id, (entry) => ({ ...entry, text: finalText, status: "completed", streaming: false }));
      else next = { ...next, timeline: [...next.timeline, { id: `assistant:final:${runId}:${turnId}`, kind: "assistant", text: finalText, runId, turnId, status: "completed", streaming: false }] };
    }
    return next;
  }
  if (type === "turn_failed" || type === "turn_cancelled") {
    const failed = type === "turn_failed";
    const runId = eventRunId ?? textValue(payload.run_id);
    const next = settleTerminalTurn(state, runId, turnId, failed ? "failed" : "cancelled");
    const reason = failed ? `Turn failed: ${textValue(payload.failure_reason) || textValue(payload.termination_reason) || "runtime error"}` : "Turn cancelled";
    return appendStatus({ ...next, activeTurn: true, terminalStatusPending: true, turnStatus: failed ? "failed" : "cancelled", pendingInteraction: null, run: { ...(next.run ?? {}), run_id: runId, turn_id: turnId, status: failed ? "failed" : "cancelled", termination_reason: textValue(payload.termination_reason) || (failed ? "internal_error" : "user_cancelled") } }, reason, failed ? "failed" : "cancelled");
  }
  return state;
}

export type RendererAction =
  | { type: "hydrate_preferences"; preferences: Partial<DesktopPreferences> }
  | { type: "runtime_state"; state: RuntimeStateName; error?: string | null }
  | { type: "runtime_initialized"; result: unknown; preserveRuntimeState?: boolean }
  | { type: "status_loaded"; result: unknown }
  | { type: "runtime_error"; message: string; state?: RuntimeStateName }
  | { type: "project_opened"; result: unknown; preserveRuntimeState?: boolean }
  | { type: "catalog_refreshed"; projectKey: string; sessions: unknown[]; reason?: SessionOrderReason; focusSessionId?: string }
  | { type: "session_resumed"; result: unknown; preserveRuntimeState?: boolean }
  | { type: "session_mutated"; sourceProjectKey: string; result: unknown }
  | { type: "session_new"; sessionId: string; run: unknown; modelRef?: string | null }
  | { type: "compaction_started"; trigger?: CompactionTrigger }
  | { type: "agent_event"; event: AgentEvent }
  | { type: "interaction_submitting"; value: boolean }
  | { type: "session_mutation_busy"; value: boolean }
  | { type: "command_candidates"; result: unknown }
  | { type: "model_candidates"; values: string[] }
  | { type: "turn_accepted"; run: unknown; steering: boolean; text?: string }
  | { type: "command_result"; result: unknown; notice?: string | null }
  | { type: "composer_text"; text: string }
  | { type: "clear_timeline" }
  | { type: "workspace_cleared" }
  | { type: "notice"; text: string | null }
  | { type: "set_theme"; theme: ThemePreference }
  | { type: "set_panel_mode"; panelMode: PanelModePreference }
  | { type: "set_sidebar_width"; width: number }
  | { type: "set_runtime_panel_width"; width: number }
  | { type: "set_focus_mode"; value: boolean }
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
        sidebarWidth: preferences.sidebarWidth !== undefined && Number.isSafeInteger(preferences.sidebarWidth)
          ? Math.min(SIDEBAR_WIDTH_MAX, Math.max(SIDEBAR_WIDTH_MIN, preferences.sidebarWidth))
          : state.sidebarWidth,
        runtimePanelWidth: preferences.runtimePanelWidth !== undefined && Number.isSafeInteger(preferences.runtimePanelWidth)
          ? Math.min(RUNTIME_PANEL_WIDTH_MAX, Math.max(RUNTIME_PANEL_WIDTH_MIN, preferences.runtimePanelWidth))
          : state.runtimePanelWidth,
      };
    }
    case "runtime_state":
      return { ...state, runtimeState: action.state, runtimeError: action.error !== undefined ? action.error : state.runtimeError };
    case "runtime_initialized": {
      const source = resultRecord(action.result);
      const run = normalizeRun(source.run);
      return {
        ...state,
        runtimeState: action.preserveRuntimeState ? state.runtimeState : "ready",
        runtimeError: null,
        ...(run ? { run, permissionMode: permissionModeOf(run) } : { permissionMode: "unknown" as const }),
      };
    }
    case "status_loaded": {
      const source = resultRecord(action.result);
      const application = asRecord(source.application);
      const runtimeState = runtimeStateFromProjection(source.runtime);
      const currentModelRef = nonEmptyText(application?.current_model);
      const contextValue = application?.context_status;
      const legacyContextPresent = application !== null && Object.prototype.hasOwnProperty.call(application, "context_usage");
      const compactionValue = application && Object.prototype.hasOwnProperty.call(application, "compaction_status")
        ? application.compaction_status
        : undefined;
      const providerUsageValue = application && Object.prototype.hasOwnProperty.call(application, "last_provider_request_usage")
        ? application.last_provider_request_usage
        : undefined;
      const normalizedProviderUsage = providerUsageValue !== undefined
        ? normalizeProviderRequestUsage(providerUsageValue)
        : undefined;
      const activeTurn = source.active_turn === true ? true : source.active_turn === false ? false : state.activeTurn;
      const sessionId = state.selectedSessionId;
      const nextSessionModels = currentModelRef && sessionId
        ? { ...state.sessionModels, [sessionId]: currentModelRef }
        : state.sessionModels;
      const rawStatusSessionId = nonEmptyText(source.session_id);
      const statusSessionId = rawStatusSessionId ?? sessionId;
      const statusProjectKey = nonEmptyText(source.project_key) ?? state.selectedProjectKey;
      const statusKey = statusSessionId ? sessionRuntimeKey(statusProjectKey, statusSessionId) : null;
      const hydrated = statusSessionId
        ? sessionRuntimeFromSource(source, state.timeline, state.sessionRuntime[statusKey as string] ?? null, normalizedProviderUsage)
        : null;
      const nextSessionRuntime = statusKey && hydrated
        ? { ...state.sessionRuntime, [statusKey]: hydrated }
        : state.sessionRuntime;
      const visibleHydrated = statusSessionId === sessionId && hydrated ? hydrated : null;
      const statusTargetsVisibleSession = rawStatusSessionId === null || rawStatusSessionId === sessionId;
      const visibleProviderUsage = statusTargetsVisibleSession
        ? hydrated?.lastProviderRequestUsage ?? normalizedProviderUsage
        : undefined;
      const statusState: RendererState = {
        ...state,
        ...(runtimeState ? { runtimeState } : {}),
        ...(source.active_turn === true || source.active_turn === false ? { activeTurn } : {}),
        ...(source.active_turn === false ? { terminalStatusPending: false } : {}),
        ...(currentModelRef ? { currentModelRef } : {}),
        sessionModels: nextSessionModels,
        // A partial status response is allowed during transport recovery. It
        // must not erase the last complete Context measurement or Compaction
        // state that the Application already published.
        ...(contextValue !== undefined
          ? { contextUsage: normalizeContextUsage(contextValue) }
          : legacyContextPresent
            ? { contextUsage: contextUsageAtBoundary() }
            : {}),
        ...(compactionValue !== undefined ? { compactionStatus: normalizeCompactionStatus(compactionValue) } : {}),
        ...(visibleProviderUsage ? { lastProviderRequestUsage: cloneProviderRequestUsage(visibleProviderUsage) } : {}),
        ...(visibleHydrated ? {
          timeline: visibleHydrated.timeline,
          todo: visibleHydrated.todo,
          todoIteration: visibleHydrated.todoIteration,
          run: visibleHydrated.run ?? state.run,
          activeTurn: visibleHydrated.activeTurn,
          terminalStatusPending: visibleHydrated.terminalStatusPending,
          turnStatus: visibleHydrated.turnStatus,
          pendingInteraction: visibleHydrated.pendingInteraction,
          completionBlocked: visibleHydrated.completionBlocked,
        } : {}),
        sessionRuntime: nextSessionRuntime,
      };
      return hydrated && statusSessionId ? updateSessionRuntimeStatus(statusState, statusProjectKey, statusSessionId, runtimeStatus(hydrated)) : statusState;
    }
    case "runtime_error":
      return { ...state, runtimeState: action.state ?? "failed", runtimeError: action.message };
    case "project_opened":
      return applyProjectOpened(state, action.result, action.preserveRuntimeState);
    case "catalog_refreshed":
      return applyCatalogRefreshed(state, action.projectKey, action.sessions, action.reason, action.focusSessionId);
    case "session_resumed":
      return applySessionResumed(state, action.result, action.preserveRuntimeState, providerRequestUsageFromResult(action.result));
    case "session_mutated":
      return applySessionMutation(state, action.sourceProjectKey, action.result);
    case "session_new": {
      const stateWithCache = cacheVisibleRuntime(state, state.selectedProjectKey, state.selectedSessionId);
      const modelRef = nonEmptyText(action.modelRef);
      const next: RendererState = {
        ...permissionUnknownAtRunBoundary(stateWithCache, action.run),
        selectedSessionId: action.sessionId,
        timeline: [],
        todo: [],
        todoIteration: 0,
        activeTurn: false,
        terminalStatusPending: false,
        turnStatus: "idle",
        pendingInteraction: null,
        contextUsage: contextUsageAtBoundary(),
        lastProviderRequestUsage: providerRequestUsageAtBoundary(),
        compactionStatus: { state: "idle", trigger: null, changed: null },
        ...(modelRef ? { currentModelRef: modelRef, sessionModels: { ...stateWithCache.sessionModels, [action.sessionId]: modelRef } } : {}),
        sessionViewRevision: stateWithCache.sessionViewRevision + 1,
        notice: "New Session",
        runtimeError: null,
      };
      const key = sessionRuntimeKey(stateWithCache.selectedProjectKey, action.sessionId);
      const runtime = runtimeSnapshotFromState(next);
      return updateSessionRuntimeStatus({ ...next, sessionRuntime: { ...stateWithCache.sessionRuntime, [key]: runtime } }, stateWithCache.selectedProjectKey, action.sessionId, "idle");
    }
    case "compaction_started":
      return { ...state, compactionStatus: { state: "running", trigger: action.trigger ?? "manual", changed: null }, notice: null };
    case "agent_event": {
      const event = action.event as Record<string, JsonValue>;
      const eventSessionId = nonEmptyText(event.session_id);
      const eventProjectKey = nonEmptyText(event.project_key) ?? state.selectedProjectKey;
      const offscreen = Boolean(eventSessionId && (eventSessionId !== state.selectedSessionId || (eventProjectKey && eventProjectKey !== state.selectedProjectKey)));
      if (!offscreen) {
        const next = reduceAgentEvent(state, action.event);
        return cacheVisibleRuntime(
          updateSessionRuntimeStatus(next, state.selectedProjectKey, state.selectedSessionId ?? "", runtimeStatus(runtimeSnapshotFromState(next))),
          state.selectedProjectKey,
          state.selectedSessionId,
        );
      }
      const key = sessionRuntimeKey(eventProjectKey, eventSessionId as string);
      const cached = state.sessionRuntime[key];
      const base = cached
        ? applyRuntimeSnapshot(emptyRuntimeBoundary(state), cached)
        : emptyRuntimeBoundary(state);
      const next = reduceAgentEvent(base, action.event);
      const snapshot = runtimeSnapshotFromState(next);
      const stored = { ...state.sessionRuntime, [key]: snapshot };
      return updateSessionRuntimeStatus({ ...state, sessionRuntime: stored }, eventProjectKey, eventSessionId as string, runtimeStatus(snapshot));
    }
    case "interaction_submitting":
      return state.pendingInteraction ? { ...state, pendingInteraction: { ...state.pendingInteraction, submitting: action.value } } : state;
    case "session_mutation_busy":
      return { ...state, sessionMutationBusy: action.value };
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
      const next = { ...state, run: acceptedRun ?? state.run, permissionMode: acceptedRun ? permissionModeOf(acceptedRun) : state.permissionMode, activeTurn: true, terminalStatusPending: false, turnStatus: "running" as const, composerText: "", ...(action.steering ? {} : { pendingInteraction: null, todo: [], todoIteration: 0 }) };
      if (!action.steering || !action.text?.trim()) return next;
      return { ...next, timeline: [...next.timeline, { id: `steering:${next.run?.run_id ?? "run"}:${next.run?.turn_id ?? "turn"}:${next.nextStatusId}`, kind: "steering", text: action.text, turnId: next.run?.turn_id, status: "completed" }], nextStatusId: next.nextStatusId + 1 };
    }
    case "command_result": {
      const source = resultRecord(action.result);
      // Command results are a typed Desktop contract.  Never render
      // Application `output`/`error` text here: CLI/TUI prose stays on their
      // own interface boundary, while Renderer notices come from locale-owned
      // semantic codes supplied by App.
      const params = asRecord(source.params);
      const notice = action.notice ?? null;
      const actionValue = asRecord(source.ui_action);
      if (source.code === "compact_failed" || source.code === "compact_cancelled" || source.code === "compact_no_change" || source.code === "compact_completed") {
        const compactState: CompactionState = source.code === "compact_failed"
          ? "failed"
          : source.code === "compact_cancelled"
            ? "cancelled"
            : source.code === "compact_no_change"
              ? "no_change"
              : "completed";
        return {
          ...state,
          compactionStatus: { state: compactState, trigger: "manual", changed: compactState === "completed" ? true : compactState === "no_change" ? false : null },
          commandOutput: notice,
          notice,
          composerText: "",
        };
      }
      // `/status` carries the same safe projection as `status.get`.  Consume
      // that typed payload directly so the command does not depend on a
      // second status RPC (which may be unavailable or stale) before the
      // existing RuntimePanel can render its localized facts.
      if (source.code === "status_ready") {
        const projected = reduceRendererState(state, {
          type: "status_loaded",
          result: params ?? {},
        });
        return { ...projected, commandOutput: notice, notice, composerText: "" };
      }
      // `/compact` returns only its safe compaction DTO.  Apply it at the
      // same typed boundary; no command prose is needed to update the panel.
      if (params && Object.prototype.hasOwnProperty.call(params, "compaction_status")) {
        return {
          ...state,
          compactionStatus: normalizeCompactionStatus(params.compaction_status),
          commandOutput: notice,
          notice,
          composerText: "",
        };
      }
      const sessionChanged = actionValue?.type === "session_changed";
      if (sessionChanged && typeof actionValue.session_id === "string") {
        const replay = params?.replay;
        const run = params?.run;
        const next = actionValue.restored === true
          ? applySessionResumed(state, { session_id: actionValue.session_id, replay, run, active_turn: params?.active_turn, model_ref: params?.model_ref }, false, providerRequestUsageFromResult(params))
          : { ...permissionUnknownAtRunBoundary(state, run), selectedSessionId: actionValue.session_id, timeline: [], todo: [], todoIteration: 0, activeTurn: params?.active_turn === true, terminalStatusPending: false, turnStatus: params?.active_turn === true ? "running" as const : "idle" as const, pendingInteraction: null, contextUsage: contextUsageAtBoundary(), lastProviderRequestUsage: providerRequestUsageAtBoundary(), compactionStatus: { state: "idle" as const, trigger: null, changed: null }, ...(typeof params?.model_ref === "string" ? { currentModelRef: params.model_ref, sessionModels: { ...state.sessionModels, [actionValue.session_id]: params.model_ref } } : {}), sessionViewRevision: state.sessionViewRevision + 1 };
        return { ...next, commandOutput: notice, notice, composerText: "", modelPickerOpen: false };
      }
      if (actionValue?.type === "clear_transcript") return { ...state, timeline: [], commandOutput: notice, composerText: "" };
      if (actionValue?.type === "behavior_mode_selected" || actionValue?.type === "permission_mode_selected" || actionValue?.type === "model_selected") {
        const projectedRun = normalizeRun(params?.run);
        const projectedPermission = permissionModeOf(projectedRun);
        const permissionMode = projectedPermission !== "unknown"
          ? projectedPermission
          : actionValue.type === "permission_mode_selected" && (actionValue.mode === "default" || actionValue.mode === "auto" || actionValue.mode === "full_access")
            ? actionValue.mode
            : state.permissionMode;
        const run = actionValue.type === "behavior_mode_selected" && typeof actionValue.mode === "string"
          ? { ...(state.run ?? {}), behavior_mode: actionValue.mode }
          : projectedRun ?? state.run;
        const selectedModelRef = actionValue.type === "model_selected" ? nonEmptyText(actionValue.model_ref) : null;
        const currentModelRef = selectedModelRef ?? state.currentModelRef;
        const contextUsage = actionValue.type === "model_selected"
          ? contextUsageAtBoundary()
          : state.contextUsage;
        const sessionModels = selectedModelRef && state.selectedSessionId
          ? { ...state.sessionModels, [state.selectedSessionId]: selectedModelRef }
          : state.sessionModels;
        const projects = selectedModelRef && state.selectedSessionId
          ? state.projects.map((project) => ({
            ...project,
            sessions: project.sessions.map((session) => session.session_id === state.selectedSessionId ? { ...session, model_ref: selectedModelRef } : session),
          }))
          : state.projects;
        return { ...state, run, permissionMode, currentModelRef, sessionModels, projects, contextUsage, commandOutput: notice, notice, composerText: "", modelPickerOpen: false };
      }
      if (actionValue?.type === "open_model_picker") return { ...state, modelPickerOpen: true, commandOutput: notice, notice, composerText: "" };
      return { ...state, commandOutput: notice, notice, composerText: "" };
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
        todoIteration: 0,
        run: null,
        contextUsage: contextUsageAtBoundary(),
        lastProviderRequestUsage: providerRequestUsageAtBoundary(),
        permissionMode: "unknown",
        currentModelRef: null,
        activeTurn: false,
        terminalStatusPending: false,
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
        sessionViewRevision: state.sessionViewRevision + 1,
      };
    case "notice":
      return { ...state, notice: action.text };
    case "set_theme":
      return { ...state, theme: action.theme };
    case "set_panel_mode":
      return { ...state, panelMode: action.panelMode };
    case "set_sidebar_width":
      return {
        ...state,
        sidebarWidth: Number.isSafeInteger(action.width)
          ? Math.min(SIDEBAR_WIDTH_MAX, Math.max(SIDEBAR_WIDTH_MIN, action.width))
          : state.sidebarWidth,
      };
    case "set_runtime_panel_width":
      return {
        ...state,
        runtimePanelWidth: Number.isSafeInteger(action.width)
          ? Math.min(RUNTIME_PANEL_WIDTH_MAX, Math.max(RUNTIME_PANEL_WIDTH_MIN, action.width))
          : state.runtimePanelWidth,
      };
    case "set_focus_mode":
      return { ...state, focusMode: action.value };
    case "set_view":
      return { ...state, view: action.view };
    case "settings_loaded":
      return {
        ...state,
        configuration: action.configuration,
        permissionMode: state.run ? state.permissionMode : "unknown",
        settingsLoaded: true,
        settingsError: null,
      };
    case "settings_error":
      return { ...state, settingsError: action.message };
    case "settings_saving":
      return { ...state, settingsSaving: action.value };
  }
}

// The Sidebar keeps this existing renderer composition entry because it is a
// real production consumer; reducer-only and normalization helpers stay in
// their owning modules rather than becoming public facade exports.
export { sessionLabel } from "./state-session";

export type { DesktopApi, DesktopPreferences, JsonObject };
