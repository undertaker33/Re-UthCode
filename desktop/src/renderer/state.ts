import type { AgentEvent, DesktopPreferences, DesktopApi, JsonObject, JsonValue, LanguagePreference, PanelModePreference, ThemePreference } from "../desktop-api";

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
    compactionStatus: state.compactionStatus,
    permissionMode: state.permissionMode,
    activeTurn: state.activeTurn,
    terminalStatusPending: state.terminalStatusPending,
    turnStatus: state.turnStatus,
    pendingInteraction: state.pendingInteraction,
    completionBlocked: state.completionBlocked,
  });
}

function applyRuntimeSnapshot(state: RendererState, snapshot: SessionRuntimeSnapshot): RendererState {
  return {
    ...state,
    timeline: snapshot.timeline.map((entry) => ({ ...entry })),
    todo: snapshot.todo.map((item) => ({ ...item })),
    todoIteration: snapshot.todoIteration,
    run: snapshot.run ? { ...snapshot.run, usage: snapshot.run.usage ? { ...snapshot.run.usage } : undefined } : null,
    contextUsage: { ...snapshot.contextUsage },
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

function emptyRuntimeBoundary(state: RendererState): RendererState {
  return {
    ...state,
    timeline: [],
    todo: [],
    todoIteration: 0,
    run: null,
    contextUsage: contextUsageAtBoundary(),
    compactionStatus: { state: "idle", trigger: null, changed: null },
    permissionMode: "unknown",
    activeTurn: false,
    terminalStatusPending: false,
    turnStatus: "idle",
    pendingInteraction: null,
    completionBlocked: null,
  };
}

function runtimeStatus(snapshot: SessionRuntimeSnapshot): SessionSummary["runtime_status"] {
  if (snapshot.pendingInteraction || snapshot.turnStatus === "paused" || snapshot.turnStatus === "pausing") return "waiting";
  if (snapshot.activeTurn && snapshot.turnStatus === "running") return "running";
  if (snapshot.turnStatus === "failed") return "failed";
  if (snapshot.turnStatus === "cancelled") return "cancelled";
  if (snapshot.turnStatus === "completed" || snapshot.terminalStatusPending) return "completed";
  return "idle";
}

function updateSessionRuntimeStatus(
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

function cacheVisibleRuntime(state: RendererState, projectKey: string | null, sessionId: string | null): RendererState {
  if (!projectKey || !sessionId) return state;
  const snapshot = runtimeSnapshotFromState(state);
  return {
    ...state,
    sessionRuntime: { ...state.sessionRuntime, [sessionRuntimeKey(projectKey, sessionId)]: snapshot },
  };
}

function asRecord(value: unknown): Record<string, JsonValue> | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, JsonValue>;
}

const MOJIBAKE_MARKERS = ["Ã", "Â", "â", "ä", "å", "æ", "ç", "è", "é", "ê", "ï¿½", "锟"];
// These are high-signal characters produced by the common UTF-8-as-GB18030
// failure mode.  Restricting the reverse-table pass to a marked string keeps
// normal long Chinese transcripts on the ordinary O(n) normalization path.
const GB18030_MOJIBAKE_MARKERS = ["浣", "犲", "ソ", "姝", "ｅ", "鍒", "璇", "鎴", "锟"];

let gb18030PairMap: Map<number, Uint8Array> | null | undefined;

/**
 * Build the small GB18030 two-byte reverse table lazily.  A real-world
 * mojibake sample such as `浣犲ソ` is UTF-8 bytes decoded as GB18030; unlike
 * Latin-1 corruption it contains no obvious ASCII marker.  TextDecoder is
 * available in the renderer, so one bounded table pass lets us recover only
 * candidates that round-trip to valid UTF-8, without shipping a second
 * encoding library or changing ordinary Chinese text.
 */
function gb18030Pairs(): Map<number, Uint8Array> | null {
  if (gb18030PairMap !== undefined) return gb18030PairMap;
  try {
    const bytes: number[] = [];
    const pairs: Array<[number, number]> = [];
    for (let lead = 0x81; lead <= 0xfe; lead += 1) {
      for (let trail = 0x40; trail <= 0xfe; trail += 1) {
        if (trail === 0x7f) continue;
        bytes.push(lead, trail, 0);
        pairs.push([lead, trail]);
      }
    }
    const decoded = new TextDecoder("gb18030").decode(Uint8Array.from(bytes));
    const result = new Map<number, Uint8Array>();
    let offset = 0;
    for (const [lead, trail] of pairs) {
      const code = decoded.charCodeAt(offset);
      if (Number.isFinite(code) && decoded.charCodeAt(offset + 1) === 0) {
        result.set(code, Uint8Array.of(lead, trail));
      }
      offset += 2;
    }
    gb18030PairMap = result;
  } catch {
    // Some embedded runtimes may not expose GB18030.  Latin-1 recovery and
    // the authoritative UTF-8 transport remain fully functional there.
    gb18030PairMap = null;
  }
  return gb18030PairMap;
}

function decodeGb18030MojibakeRun(run: readonly string[]): string | null {
  if (run.length < 2) return null;
  const pairs = gb18030Pairs();
  if (!pairs) return null;
  const bytes: number[] = [];
  for (const character of run) {
    const pair = pairs.get(character.codePointAt(0) ?? -1);
    if (!pair) return null;
    bytes.push(pair[0], pair[1]);
  }
  try {
    const decoded = new TextDecoder("utf-8", { fatal: true }).decode(Uint8Array.from(bytes));
    return decoded && decoded !== run.join("") ? decoded : null;
  } catch {
    return null;
  }
}

function recoverGb18030Mojibake(value: string): string {
  const characters = [...value];
  if (characters.length < 2
    || !characters.some((character) => (character.codePointAt(0) ?? 0) > 0x7f)
    || !GB18030_MOJIBAKE_MARKERS.some((marker) => value.includes(marker))) return value;
  let result = "";
  let index = 0;
  while (index < characters.length) {
    let bestLength = 0;
    let best: string | null = null;
    const run: string[] = [];
    for (let end = index; end < characters.length; end += 1) {
      run.push(characters[end]!);
      const candidate = decodeGb18030MojibakeRun(run);
      if (candidate !== null) {
        bestLength = run.length;
        best = candidate;
      }
    }
    if (best !== null && bestLength >= 2) {
      result += best;
      index += bestLength;
    } else {
      result += characters[index]!;
      index += 1;
    }
  }
  return result;
}

/** Recover only the common UTF-8-as-Latin-1 display corruption pattern. */
export function recoverMojibake(value: string): string {
  let recovered = value;
  if (MOJIBAKE_MARKERS.some((marker) => value.includes(marker))) {
    try {
      if (![...value].some((character) => character.charCodeAt(0) > 255)) {
        const bytes = Uint8Array.from([...value].map((character) => character.charCodeAt(0)));
        const decoded = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
        const sourceScore = MOJIBAKE_MARKERS.reduce((score, marker) => score + value.split(marker).length - 1, 0);
        const decodedScore = MOJIBAKE_MARKERS.reduce((score, marker) => score + decoded.split(marker).length - 1, 0);
        if (decodedScore < sourceScore) recovered = decoded;
      }
    } catch {
      // Try the GB18030 path below; malformed Latin-1 text is left intact.
    }
  }
  return recoverGb18030Mojibake(recovered);
}

function textValue(value: unknown): string {
  return typeof value === "string" ? recoverMojibake(value) : "";
}

function numberText(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : "";
}

function nonEmptyText(value: unknown): string | null {
  const text = textValue(value).trim();
  return text ? text : null;
}

function positiveInteger(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0 ? value : null;
}

function runtimeStateFromProjection(value: unknown): RuntimeStateName | null {
  const source = asRecord(value);
  const state = source?.state;
  return state === "booting" || state === "restarting" || state === "ready" || state === "configuration_required"
    || state === "failed" || state === "stopping" || state === "stopped"
    ? state
    : null;
}

/** Normalize the Application-owned Context status without manufacturing a limit. */
export function normalizeContextUsage(value: unknown): ContextUsageProjection {
  const source = asRecord(value);
  // Application.status() always serializes this complete DTO.  A partial or
  // malformed object is not evidence for a new measurement: hide it at the
  // projection boundary instead of manufacturing an estimate/source.
  if (!source
    || !Object.prototype.hasOwnProperty.call(source, "used_tokens")
    || !Object.prototype.hasOwnProperty.call(source, "budget_tokens")
    || !Object.prototype.hasOwnProperty.call(source, "available")
    || !Object.prototype.hasOwnProperty.call(source, "measurement")
    || !Object.prototype.hasOwnProperty.call(source, "source")) return contextUsageAtBoundary();
  const budget = positiveInteger(source.budget_tokens);
  const used = typeof source.used_tokens === "number" && Number.isSafeInteger(source.used_tokens) && source.used_tokens >= 0
    ? source.used_tokens
    : null;
  const availableValue = typeof source.available === "boolean" ? source.available : null;
  const measurementValue = source.measurement;
  const measurement: ContextMeasurement | null = measurementValue === "estimate" || measurementValue === "exact" || measurementValue === "unavailable"
    ? measurementValue
    : null;
  const sourceValue = nonEmptyText(source.source);
  if (budget === null || used === null || availableValue === null || measurement === null || sourceValue === null) return contextUsageAtBoundary();
  if ((measurement === "unavailable" && availableValue) || (measurement !== "unavailable" && !availableValue)) return contextUsageAtBoundary();
  return {
    used_tokens: used,
    budget_tokens: budget,
    available: availableValue,
    measurement,
    source: sourceValue,
  };
}

function contextUsageAtBoundary(): ContextUsageProjection {
  return { used_tokens: 0, budget_tokens: 0, available: false, measurement: "unavailable", source: "unavailable" };
}

function normalizeCompactionStatus(value: unknown): CompactionStatusProjection {
  const source = asRecord(value);
  const stateValue = source?.state;
  const state: CompactionState = stateValue === "running" || stateValue === "completed" || stateValue === "no_change" || stateValue === "failed" || stateValue === "cancelled"
    ? stateValue
    : "idle";
  const triggerValue = source?.trigger;
  const trigger: CompactionTrigger | null = triggerValue === "manual" || triggerValue === "auto" || triggerValue === "overflow"
    ? triggerValue
    : null;
  const changed = typeof source?.changed === "boolean" ? source.changed : null;
  return { state, trigger: state === "idle" ? null : trigger, changed: state === "running" ? null : changed };
}

function normalizeTodo(value: unknown): TodoItem[] {
  const source = asRecord(value);
  const items = Array.isArray(source?.items) ? source.items : [];
  return items.map((item) => {
    const row = asRecord(item);
    return {
      content: textValue(row?.content),
      status: row?.status === "completed" || row?.status === "in_progress" ? row.status : "pending",
    } as TodoItem;
  });
}

function normalizePendingInteraction(value: unknown): PendingInteraction | null {
  const pause = asRecord(value);
  if (!pause) return null;
  const rawKind = textValue(pause.kind);
  const kind: InteractionKind = rawKind === "user_input_required" || rawKind === "provider_unavailable" || rawKind === "permission_required" || rawKind === "plan_review_required"
    ? rawKind
    : "user_requested";
  const request = asRecord(pause.user_input_request ?? pause.permission_request ?? pause.plan_review_request);
  const pauseId = nonEmptyText(pause.pause_id);
  const runId = nonEmptyText(pause.run_id);
  const turnId = nonEmptyText(pause.turn_id);
  if (!pauseId || !runId || !turnId) return null;
  return {
    kind,
    pauseId,
    runId,
    turnId,
    toolCallId: nonEmptyText(pause.tool_call_id) ?? undefined,
    request: request ?? undefined,
    reason: nonEmptyText(pause.reason) ?? undefined,
    iteration: positiveInteger(pause.iteration) ?? undefined,
  };
}

function sessionRuntimeFromSource(source: Record<string, JsonValue>, replay: TimelineEntry[], fallback: SessionRuntimeSnapshot | null): SessionRuntimeSnapshot | null {
  const sessionState = asRecord(source.session_state);
  if (!sessionState && !fallback) return null;
  const root = sessionState ?? {};
  const run = normalizeRun(root.run ?? source.run) ?? fallback?.run ?? null;
  const runStatus = textValue(run?.status).toLowerCase();
  const pendingValue = Object.prototype.hasOwnProperty.call(root, "pending_pause")
    ? root.pending_pause
    : Object.prototype.hasOwnProperty.call(source, "pending_pause")
      ? source.pending_pause
      : undefined;
  // An explicit null is the Application's authoritative statement that the
  // pause was answered. Only an omitted field may retain a cached projection.
  const pending = pendingValue === undefined
    ? fallback?.pendingInteraction ?? null
    : normalizePendingInteraction(pendingValue);
  const taskState = root.task_state ?? source.task_state;
  const todo = taskState !== undefined ? normalizeTodo(taskState) : fallback?.todo ?? [];
  const iterationValue = root.todo_iteration ?? source.todo_iteration;
  const todoIteration = typeof iterationValue === "number" && Number.isSafeInteger(iterationValue) && iterationValue >= 0
    ? iterationValue
    : fallback?.todoIteration ?? 0;
  const app = asRecord(root.application ?? source.application);
  const contextValue = app?.context_status ?? root.context_status ?? source.context_status;
  const compactionValue = app?.compaction_status ?? root.compaction_status ?? source.compaction_status;
  const activeValue = Object.prototype.hasOwnProperty.call(root, "active_turn") ? root.active_turn : source.active_turn;
  const activeTurn = activeValue === true || (activeValue !== false && (runStatus === "running" || runStatus === "paused" || runStatus === "pausing"))
    ? true
    : activeValue === false ? false : fallback?.activeTurn ?? false;
  const settledFallback = fallback?.turnStatus === "completed" || fallback?.turnStatus === "failed" || fallback?.turnStatus === "cancelled"
    ? fallback.turnStatus
    : "idle";
  const turnStatus: RendererState["turnStatus"] = activeValue === false
    ? settledFallback
    : pending
    ? "paused"
    : runStatus === "paused" ? "paused" : runStatus === "pausing" ? "pausing" : activeTurn ? "running" : fallback?.turnStatus ?? "idle";
  return {
    timeline: fallback?.timeline?.length ? fallback.timeline : replay,
    todo,
    todoIteration,
    run,
    contextUsage: contextValue !== undefined ? normalizeContextUsage(contextValue) : fallback?.contextUsage ?? contextUsageAtBoundary(),
    compactionStatus: compactionValue !== undefined ? normalizeCompactionStatus(compactionValue) : fallback?.compactionStatus ?? { state: "idle", trigger: null, changed: null },
    permissionMode: permissionModeOf(run),
    activeTurn,
    terminalStatusPending: activeValue === false ? false : fallback?.terminalStatusPending ?? false,
    turnStatus,
    pendingInteraction: pending,
    completionBlocked: fallback?.completionBlocked ?? null,
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
    runtime_status: source?.runtime_status === "running" || source?.runtime_status === "waiting" || source?.runtime_status === "completed" || source?.runtime_status === "failed" || source?.runtime_status === "cancelled"
      ? source.runtime_status
      : "idle",
  };
}

function applySessionPins(sessions: SessionSummary[], projectKey: string, pinnedSessions: DesktopPreferences["pinnedSessions"]): SessionSummary[] {
  const pinned = new Set(pinnedSessions.filter((item) => item.projectKey === projectKey).map((item) => item.sessionId));
  return sessions.map((session) => ({ ...session, pinned: pinned.has(session.session_id) }));
}

function mergeSessionModels(
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

/**
 * Catalog authority may order metadata by last-used time.  That is useful for
 * a cold project open, but a refresh must not make selecting or resuming an
 * existing row move it to another position in the navigation.  Reconcile
 * known rows in their existing order and append only genuinely new rows.
 */
export type SessionOrderReason = "project_open" | "catalog_refresh" | "message" | "session_resume" | "session_new" | "session_pin" | "session_rename";

/**
 * Keep navigation presentation stable for metadata refreshes and actions that
 * update a row in place.  New rows are appended; pinning is handled by the
 * group projection, not by a hidden last-used sort.
 */
function preserveSessionOrder(previous: readonly SessionSummary[], incoming: readonly SessionSummary[], reason: SessionOrderReason, focusSessionId?: string): SessionSummary[] {
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
      const failedTurn = kind === "failure";
      const normalizedKind: TimelineKind =
        kind === "user" || kind === "steering" || kind === "reasoning" || kind === "assistant" || kind === "tool" || kind === "plan"
          ? kind
          : "status";
      const sequence = typeof source.sequence === "number" ? source.sequence : index + 1;
      const statusValue = source.status;
      const terminalStatus: TimelineStatus = statusValue === "failed" || statusValue === "error" || statusValue === "rejected"
        ? "failed"
        : statusValue === "cancelled" || statusValue === "canceled"
          ? "cancelled"
          : "completed";
      return {
        id: `replay:${sequence}:${index}`,
        kind: normalizedKind,
        text: failedTurn
          ? `Turn failed: ${textValue(source.failure_reason) || textValue(source.termination_reason) || "runtime error"}`
          : textValue(source.text),
        runId: nonEmptyText(source.run_id) ?? undefined,
        turnId: nonEmptyText(source.turn_id) ?? undefined,
        iteration: positiveInteger(source.iteration) ?? undefined,
        toolCallId: nonEmptyText(source.tool_call_id) ?? undefined,
        toolName: nonEmptyText(source.tool_name) ?? undefined,
        status: failedTurn ? "failed" : normalizedKind === "tool" || normalizedKind === "plan" ? terminalStatus : "completed",
        isError: failedTurn || source.is_error === true,
        planRevision: typeof source.revision === "number" ? source.revision : undefined,
        planState: normalizedKind === "plan"
          ? terminalStatus === "failed" ? "failed" : terminalStatus === "cancelled" ? "cancelled" : "final"
          : undefined,
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

export function applyProjectOpened(state: RendererState, result: unknown, preserveRuntimeState = false): RendererState {
  const stateWithCache = cacheVisibleRuntime(state, state.selectedProjectKey, state.selectedSessionId);
  const source = resultRecord(result);
  const project = resultRecord(source.project);
  const path = normalizeProjectPath(project.path);
  if (!path) return { ...state, runtimeError: "Project path is unavailable" };
  const existing = stateWithCache.projects.find((item) => item.projectKey === path);
  const incomingSessions = Array.isArray(source.sessions)
    ? source.sessions.map((item) => normalizeSession(item, path)).filter((item): item is SessionSummary => item !== null)
    : [];
  const sessions = preserveSessionOrder(existing?.sessions ?? [], incomingSessions, "project_open");
  const nextRun = normalizeRun(source.run);
  return {
    ...permissionUnknownAtRunBoundary(replaceProject(stateWithCache, { ...projectFromPath(path, existing), sessions: applySessionPins(sessions, path, stateWithCache.pinnedSessions), catalogFresh: true }), nextRun),
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
  const sessions = applySessionPins(preserveSessionOrder(previous, incoming, reason, focusSessionId), projectKey, state.pinnedSessions);
  const replaced = replaceProject(state, projectFromPath(projectKey, state.projects.find((item) => item.projectKey === projectKey)));
  return {
    ...replaced,
    projects: replaced.projects.map((item) => item.projectKey === projectKey ? { ...item, sessions, catalogFresh: true } : item),
    sessionModels: mergeSessionModels(state.sessionModels, sessions),
  };
}

export function applySessionResumed(state: RendererState, result: unknown, preserveRuntimeState = false): RendererState {
  const stateWithCache = cacheVisibleRuntime(state, state.selectedProjectKey, state.selectedSessionId);
  const source = resultRecord(result);
  const sessionId = nonEmptyText(source.session_id);
  if (!sessionId) return { ...state, runtimeError: "Session identity is unavailable" };
  const projectKey = state.selectedProjectKey;
  const key = sessionRuntimeKey(projectKey, sessionId);
  const cached = stateWithCache.sessionRuntime[key] ?? null;
  const replay = replayToTimeline(Array.isArray(source.replay) ? source.replay : []);
  const replayEndsInFailure = [...(Array.isArray(source.replay) ? source.replay : [])]
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
  const runtime = sessionRuntimeFromSource(source, replay, canRestoreLiveCache ? cached : null);
  const restoredRuntime = runtime && replayEndsInFailure && !runtime.activeTurn
    ? { ...runtime, turnStatus: "failed" as const, terminalStatusPending: false }
    : runtime;
  const boundary = permissionUnknownAtRunBoundary(stateWithCache, restoredRuntime?.run ?? source.run);
  const resumedRun = boundary.run;
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
        sessionViewRevision: state.sessionViewRevision + 1,
      }
      : {}),
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
      const activeTurn = source.active_turn === true ? true : source.active_turn === false ? false : state.activeTurn;
      const sessionId = state.selectedSessionId;
      const nextSessionModels = currentModelRef && sessionId
        ? { ...state.sessionModels, [sessionId]: currentModelRef }
        : state.sessionModels;
      const statusSessionId = nonEmptyText(source.session_id) ?? sessionId;
      const statusProjectKey = nonEmptyText(source.project_key) ?? state.selectedProjectKey;
      const statusKey = statusSessionId ? sessionRuntimeKey(statusProjectKey, statusSessionId) : null;
      const hydrated = statusSessionId
        ? sessionRuntimeFromSource(source, state.timeline, state.sessionRuntime[statusKey as string] ?? null)
        : null;
      const nextSessionRuntime = statusKey && hydrated
        ? { ...state.sessionRuntime, [statusKey]: hydrated }
        : state.sessionRuntime;
      const visibleHydrated = statusSessionId === sessionId && hydrated ? hydrated : null;
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
      return applySessionResumed(state, action.result, action.preserveRuntimeState);
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
          ? applySessionResumed(state, { session_id: actionValue.session_id, replay, run, active_turn: params?.active_turn, model_ref: params?.model_ref })
          : { ...permissionUnknownAtRunBoundary(state, run), selectedSessionId: actionValue.session_id, timeline: [], todo: [], todoIteration: 0, activeTurn: params?.active_turn === true, terminalStatusPending: false, turnStatus: params?.active_turn === true ? "running" as const : "idle" as const, pendingInteraction: null, contextUsage: contextUsageAtBoundary(), compactionStatus: { state: "idle" as const, trigger: null, changed: null }, ...(typeof params?.model_ref === "string" ? { currentModelRef: params.model_ref, sessionModels: { ...state.sessionModels, [actionValue.session_id]: params.model_ref } } : {}), sessionViewRevision: state.sessionViewRevision + 1 };
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

// Stable aliases keep reducer-oriented tests and future renderer composition
// code independent from the action/event implementation names.
export const rendererReducer = reduceRendererState;
export const reduceEvent = reduceAgentEvent;

export type { DesktopApi, DesktopPreferences, JsonObject };
