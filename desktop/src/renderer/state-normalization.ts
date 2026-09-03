import type { JsonValue } from "../desktop-api";
import type {
  CompactionState,
  CompactionStatusProjection,
  CompactionTrigger,
  ContextMeasurement,
  ContextUsageProjection,
  InteractionKind,
  PendingInteraction,
  PermissionModeProjection,
  RendererState,
  RunProjection,
  SessionRuntimeSnapshot,
  TimelineEntry,
  TimelineKind,
  TimelineStatus,
  TodoItem,
  RuntimeStateName,
} from "./state";
import { nonEmptyText, numberText, positiveInteger, textValue } from "./text-normalization";

/** Convert an untrusted Desktop JSON value to a non-array record. */
export function asRecord(value: unknown): Record<string, JsonValue> | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, JsonValue>;
}

export function runtimeStateFromProjection(value: unknown): RuntimeStateName | null {
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
  // Application.status() always serializes this complete DTO. A partial or
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

export function contextUsageAtBoundary(): ContextUsageProjection {
  return { used_tokens: 0, budget_tokens: 0, available: false, measurement: "unavailable", source: "unavailable" };
}

export function normalizeCompactionStatus(value: unknown): CompactionStatusProjection {
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

export function normalizeTodo(value: unknown): TodoItem[] {
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

export function normalizePendingInteraction(value: unknown): PendingInteraction | null {
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

/** Hydrate one Session runtime projection from an Application status DTO. */
export function sessionRuntimeFromSource(source: Record<string, JsonValue>, replay: TimelineEntry[], fallback: SessionRuntimeSnapshot | null): SessionRuntimeSnapshot | null {
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

export function normalizeRun(value: unknown): RunProjection | null {
  const source = asRecord(value);
  if (!source) return null;
  const permissionMode = permissionModeOf(source);
  return {
    ...source,
    ...(permissionMode === "unknown" ? {} : { permission_mode: permissionMode }),
  } as RunProjection;
}

export function permissionModeOf(value: unknown): PermissionModeProjection {
  const source = asRecord(value);
  const mode = source?.permission_mode;
  return mode === "default" || mode === "auto" || mode === "full_access" ? mode : "unknown";
}

export function runIdOf(value: unknown): string | null {
  const source = asRecord(value);
  return nonEmptyText(source?.run_id);
}

export function messageText(value: unknown): string {
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

export function messageReasoning(value: unknown): string {
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

/** Normalize a complete Desktop command response for reducer branches. */
export function resultRecord(value: unknown): Record<string, JsonValue> {
  return asRecord(value) ?? {};
}

/** Normalize a path-like projection while keeping all path policy in Bridge/Application. */
export function normalizeProjectPath(value: unknown): string | null {
  return nonEmptyText(value);
}
