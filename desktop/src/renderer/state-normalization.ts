import type { JsonValue, TimelineAttachment, TimelineUnavailableAttachment } from "../desktop-api";
import type {
  CompactionState,
  CompactionStatusProjection,
  CompactionTrigger,
  ContextMeasurement,
  ContextUsageProjection,
  InteractionKind,
  PendingInteraction,
  PermissionModeProjection,
  ProviderRequestUsageProjection,
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

function safeCompactionReason(value: unknown): string | undefined {
  if (typeof value !== "string" || !/^[a-z][a-z0-9_]{0,63}$/u.test(value)) return undefined;
  return value;
}

export function normalizeCompactionStatus(value: unknown, fallback?: CompactionStatusProjection | null): CompactionStatusProjection {
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
  const operationId = nonEmptyText(source?.operation_id)
    ?? (state === "running" && fallback?.state === "running" ? fallback.operation_id : undefined);
  const reason = safeCompactionReason(source?.reason);
  return {
    state,
    trigger: state === "idle" ? null : trigger,
    changed: state === "running" ? null : changed,
    ...(operationId ? { operation_id: operationId } : {}),
    ...(reason ? { reason } : {}),
  };
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
export function sessionRuntimeFromSource(
  source: Record<string, JsonValue>,
  replay: TimelineEntry[],
  fallback: SessionRuntimeSnapshot | null,
  providerRequestUsage?: ProviderRequestUsageProjection,
): SessionRuntimeSnapshot | null {
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
  const runPermission = permissionModeOf(run);
  // A partial status projection may omit permission_mode, but only the same
  // live Run may inherit the previous projection. New or unidentified Runs
  // remain unknown until the Application publishes an authoritative value.
  const currentRunId = runIdOf(run);
  const fallbackRunId = runIdOf(fallback?.run);
  const permissionMode = runPermission !== "unknown"
    ? runPermission
    : currentRunId && fallbackRunId === currentRunId
      ? fallback?.permissionMode ?? "unknown"
      : "unknown";
  return {
    timeline: fallback?.timeline?.length ? fallback.timeline : replay,
    todo,
    todoIteration,
    run,
    contextUsage: contextValue !== undefined ? normalizeContextUsage(contextValue) : fallback?.contextUsage ?? contextUsageAtBoundary(),
    ...(providerRequestUsage
      ? { lastProviderRequestUsage: providerRequestUsage }
      : fallback?.lastProviderRequestUsage
        ? { lastProviderRequestUsage: fallback.lastProviderRequestUsage }
        : {}),
    compactionStatus: compactionValue !== undefined ? normalizeCompactionStatus(compactionValue, fallback?.compactionStatus) : fallback?.compactionStatus ?? { state: "idle", trigger: null, changed: null },
    permissionMode,
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

function isUnavailableAttachment(attachment: TimelineAttachment): attachment is TimelineUnavailableAttachment {
  return "available" in attachment && attachment.available === false;
}

function attachmentIdentity(attachment: TimelineAttachment): string | null {
  return attachment.asset_ref ?? attachment.ref ?? null;
}

function normalizeAttachment(value: unknown): TimelineAttachment | null {
  const source = asRecord(value);
  if (source?.available === false) {
    const assetRef = nonEmptyText(source.asset_ref);
    if (!assetRef || source.error_code !== "attachment_unavailable") return null;
    const type = nonEmptyText(source.type);
    const ref = nonEmptyText(source.ref);
    const mimeType = nonEmptyText(source.mime_type);
    const width = typeof source.width === "number" && Number.isSafeInteger(source.width) && source.width > 0 ? source.width : null;
    const height = typeof source.height === "number" && Number.isSafeInteger(source.height) && source.height > 0 ? source.height : null;
    return {
      ...(type ? { type } : {}),
      ...(ref ? { ref } : {}),
      asset_ref: assetRef,
      available: false,
      error_code: "attachment_unavailable",
      ...(mimeType ? { mime_type: mimeType } : {}),
      ...(width !== null ? { width } : {}),
      ...(height !== null ? { height } : {}),
    };
  }
  const ref = nonEmptyText(source?.ref);
  const type = nonEmptyText(source?.type);
  const displayName = nonEmptyText(source?.display_name) ?? nonEmptyText(source?.name);
  const mimeType = nonEmptyText(source?.mime_type);
  const size = typeof source?.size_bytes === "number" && Number.isSafeInteger(source.size_bytes) && source.size_bytes >= 0
    ? source.size_bytes
    : null;
  if (!ref || !displayName || !mimeType || size === null) return null;
  const width = typeof source?.width === "number" && Number.isSafeInteger(source.width) && source.width > 0 ? source.width : null;
  const height = typeof source?.height === "number" && Number.isSafeInteger(source.height) && source.height > 0 ? source.height : null;
  const dataUrl = typeof source?.data_url === "string" && /^data:[^,]+,/.test(source.data_url) ? source.data_url : undefined;
  const assetRef = nonEmptyText(source?.asset_ref);
  const previewKind = nonEmptyText(source?.preview_kind);
  const previewText = typeof source?.text === "string" ? source.text : undefined;
  return {
    ...(type ? { type } : {}),
    ...(source?.available === true ? { available: true as const } : {}),
    ref,
    ...(assetRef ? { asset_ref: assetRef } : {}),
    display_name: displayName,
    mime_type: mimeType,
    size_bytes: size,
    ...(width !== null ? { width } : {}),
    ...(height !== null ? { height } : {}),
    ...(previewKind ? { preview_kind: previewKind } : {}),
    ...(previewText !== undefined ? { text: previewText } : {}),
    ...(source?.truncated === true ? { truncated: true } : {}),
    ...(dataUrl ? { data_url: dataUrl } : {}),
  };
}

export function normalizeAttachments(value: unknown): TimelineAttachment[] {
  if (!Array.isArray(value)) return [];
  return value.map(normalizeAttachment).filter((item): item is TimelineAttachment => item !== null);
}

function mergeAttachmentLists(left: readonly TimelineAttachment[] | undefined, right: readonly TimelineAttachment[] | undefined): TimelineAttachment[] {
  const result: TimelineAttachment[] = [];
  const seen = new Map<string, number>();
  for (const attachment of [...(left ?? []), ...(right ?? [])]) {
    const identity = attachmentIdentity(attachment);
    if (!identity) continue;
    const existingIndex = seen.get(identity);
    if (existingIndex !== undefined) {
      if (isUnavailableAttachment(result[existingIndex]!) && !isUnavailableAttachment(attachment)) result[existingIndex] = { ...attachment };
      continue;
    }
    seen.set(identity, result.length);
    result.push({ ...attachment });
  }
  return result;
}

function mergeReplayText(left: string, right: string): string {
  if (!left) return right;
  if (!right || left === right) return left;
  // A live/durable boundary may expose a complete text value after its
  // prefix. Avoid duplicating that prefix while still retaining distinct
  // text parts from one Message.
  if (right.startsWith(left)) return right;
  if (left.startsWith(right)) return left;
  return left + right;
}

function mergeUserMessageParts(entries: TimelineEntry[]): TimelineEntry[] {
  const merged: TimelineEntry[] = [];
  for (const entry of entries) {
    const previous = merged.at(-1);
    if (previous
      && previous.kind === "user"
      && entry.kind === "user"
      && previous.turnId
      && previous.turnId === entry.turnId
      && previous.messageId
      && previous.messageId === entry.messageId) {
      const attachments = mergeAttachmentLists(previous.attachments, entry.attachments);
      merged[merged.length - 1] = {
        ...previous,
        text: mergeReplayText(previous.text, entry.text),
        ...(attachments.length > 0 ? { attachments } : {}),
      };
      continue;
    }
    merged.push({ ...entry, ...(entry.attachments ? { attachments: mergeAttachmentLists(entry.attachments, undefined) } : {}) });
  }
  return merged;
}

export function replayToTimeline(records: readonly unknown[]): TimelineEntry[] {
  const timeline: TimelineEntry[] = records
    .map((value, index) => ({ value: asRecord(value), index }))
    .filter(({ value }) => value !== null)
    .sort((left, right) => {
      const a = left.value?.sequence;
      const b = right.value?.sequence;
      const aSequence = typeof a === "number" ? a : Number.MAX_SAFE_INTEGER;
      const bSequence = typeof b === "number" ? b : Number.MAX_SAFE_INTEGER;
      return aSequence - bSequence || Number(left.value?.kind === "compaction") - Number(right.value?.kind === "compaction") || left.index - right.index;
    })
    .map(({ value }, index) => {
      const source = value as Record<string, JsonValue>;
      const kind = source.kind;
      const failedTurn = kind === "failure";
      const normalizedKind: TimelineKind =
        kind === "user" || kind === "steering" || kind === "reasoning" || kind === "assistant" || kind === "tool" || kind === "plan" || kind === "compaction"
          ? kind
          : "status";
      const sequence = typeof source.sequence === "number" ? source.sequence : index + 1;
      const attachments = normalizeAttachments(source.attachments);
      const statusValue = source.status;
      const terminalStatus: TimelineStatus = statusValue === "failed" || statusValue === "error" || statusValue === "rejected"
        ? "failed"
        : statusValue === "cancelled" || statusValue === "canceled"
          ? "cancelled"
          : "completed";
      return {
        id: nonEmptyText(source.record_id)
          ?? `replay:${textValue(source.session_id)}:${sequence}:${normalizedKind}:${textValue(source.tool_call_id)}`,
        kind: normalizedKind,
        text: failedTurn
          ? `Turn failed: ${textValue(source.failure_reason) || textValue(source.termination_reason) || "runtime error"}`
          : textValue(source.text),
        runId: nonEmptyText(source.run_id) ?? undefined,
        turnId: nonEmptyText(source.turn_id) ?? undefined,
        messageId: nonEmptyText(source.message_id) ?? undefined,
        iteration: positiveInteger(source.iteration) ?? undefined,
        toolCallId: nonEmptyText(source.tool_call_id) ?? undefined,
        toolName: nonEmptyText(source.tool_name) ?? undefined,
        status: failedTurn ? "failed" : normalizedKind === "tool" || normalizedKind === "plan" ? terminalStatus : "completed",
        isError: failedTurn || source.is_error === true,
        planRevision: typeof source.revision === "number" ? source.revision : undefined,
        planState: normalizedKind === "plan"
          ? terminalStatus === "failed" ? "failed" : terminalStatus === "cancelled" ? "cancelled" : "final"
          : undefined,
        ...(attachments.length > 0 ? { attachments } : {}),
        sequence,
      };
    });
  return mergeUserMessageParts(timeline);
}

/** Normalize a complete Desktop command response for reducer branches. */
export function resultRecord(value: unknown): Record<string, JsonValue> {
  return asRecord(value) ?? {};
}

/** Normalize a path-like projection while keeping all path policy in Bridge/Application. */
export function normalizeProjectPath(value: unknown): string | null {
  return nonEmptyText(value);
}
