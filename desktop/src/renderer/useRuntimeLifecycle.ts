import { useCallback, useEffect, useRef, type Dispatch, type MutableRefObject } from "react";
import type { AgentEvent, DesktopApi, JsonObject, JsonValue } from "../desktop-api";
import type { RendererAction, RendererState } from "./state";

export type RuntimeRequest = (method: Parameters<DesktopApi["requestRuntime"]>[0], params: JsonObject) => Promise<JsonValue>;
export type RuntimeOwnershipCheck = () => boolean;
export type RuntimeOperationKind = "startup" | "recovery" | "navigation";

export interface RuntimeIdentity {
  runId: string;
  turnId: string;
}

export interface PendingTurnStart {
  id: number;
  events: AgentEvent[];
}

export type AuthoritativeIdleResult =
  | { state: "idle"; result: JsonValue }
  | { state: "cancelled" };

export interface AuthoritativeIdleOptions {
  signal: AbortSignal;
  initialDelayMs?: number;
  maxDelayMs?: number;
}

export interface RuntimeLifecycleOptions {
  api?: DesktopApi;
  stateRef: MutableRefObject<RendererState>;
  dispatch: Dispatch<RendererAction>;
}

export interface RuntimeLifecycle {
  isMounted: () => boolean;
  hasOwner: () => boolean;
  runtimeGeneration: () => number;
  waitForRuntimeLifecycleIdle: () => Promise<boolean>;
  waitForRuntimeUserAccess: () => Promise<boolean>;
  enqueueRuntimeOperation: (
    kind: RuntimeOperationKind,
    work: (isOwned: RuntimeOwnershipCheck) => Promise<void>,
    onFailure: (error: unknown, isOwned: RuntimeOwnershipCheck) => void | Promise<void>,
    terminalState?: RendererState["runtimeState"],
  ) => Promise<void>;
  cancelTerminalStatusPoll: () => void;
  startTerminalStatusConvergence: (
    runId: string,
    turnId: string,
    allowLifecycleOwner?: boolean,
    onIdle?: (result: JsonValue) => void | Promise<void>,
  ) => Promise<AuthoritativeIdleResult>;
  hasTerminalStatusPoll: () => boolean;
  terminalStatusPollFor: (runId: string, turnId: string) => Promise<AuthoritativeIdleResult> | null;
  latestTurnIdentity: () => RuntimeIdentity;
  setLatestTurnIdentity: (identity: RuntimeIdentity) => void;
  beginPendingTurnStart: () => PendingTurnStart;
  pendingTurnStart: () => PendingTurnStart | null;
  bufferPendingTurnEvent: (event: AgentEvent) => boolean;
  finishPendingTurnStart: (pending: PendingTurnStart, identity: RuntimeIdentity) => AgentEvent[];
  clearPendingTurnStart: () => void;
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

export class StaleRuntimeOperation extends Error {
  constructor() {
    super("Runtime operation is no longer current");
    this.name = "StaleRuntimeOperation";
  }
}

export class RuntimeOperationCancelled extends Error {
  constructor() {
    super("Runtime operation was cancelled");
    this.name = "RuntimeOperationCancelled";
  }
}

function asObject(value: unknown): Record<string, JsonValue> {
  if (value && typeof value === "object" && !Array.isArray(value)) return value as Record<string, JsonValue>;
  return {};
}

export function stringValue(value: unknown): string {
  return typeof value === "string" ? value : "";
}

export function knownIdentityMatches(currentRunId: string, currentTurnId: string, runId: string, turnId: string): boolean {
  return (!runId || !currentRunId || currentRunId === runId)
    && (!turnId || !currentTurnId || currentTurnId === turnId);
}

export function hasTurnIdentity(runId: string, turnId: string): boolean {
  return Boolean(runId || turnId);
}

export function hasCompleteTurnIdentity(identity: RuntimeIdentity): boolean {
  return identity.runId.trim().length > 0 && identity.turnId.trim().length > 0;
}

export function identityFromRun(value: unknown): RuntimeIdentity {
  const run = asObject(value);
  return { runId: stringValue(run.run_id), turnId: stringValue(run.turn_id) };
}

export function eventIdentity(event: AgentEvent): RuntimeIdentity {
  return { runId: stringValue(event.run_id), turnId: stringValue(event.turn_id) };
}

export function eventMatchesIdentity(event: AgentEvent, identity: RuntimeIdentity): boolean {
  const current = eventIdentity(event);
  return current.runId === identity.runId && current.turnId === identity.turnId;
}

function requestStatusWithCancellation(api: DesktopApi, signal: AbortSignal): Promise<{ state: "result"; result: JsonValue } | { state: "error" } | { state: "cancelled" }> {
  if (signal.aborted) return Promise.resolve({ state: "cancelled" });
  return new Promise((resolve) => {
    let settled = false;
    const finish = (outcome: { state: "result"; result: JsonValue } | { state: "error" } | { state: "cancelled" }) => {
      if (settled) return;
      settled = true;
      signal.removeEventListener("abort", onAbort);
      resolve(outcome);
    };
    const onAbort = () => finish({ state: "cancelled" });
    signal.addEventListener("abort", onAbort, { once: true });
    // Start through a microtask so a test double or an adapter that throws
    // before returning its Promise is handled as a transient RPC failure.
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

export function useRuntimeLifecycle(options: RuntimeLifecycleOptions): RuntimeLifecycle {
  const { api, stateRef, dispatch } = options;
  const mountedRef = useRef(false);
  const runtimeGenerationRef = useRef(0);
  const runtimeOwnerRef = useRef<RuntimeOperationOwner | null>(null);
  const runtimeOperationTailRef = useRef<Promise<void>>(Promise.resolve());
  const latestTurnRef = useRef<RuntimeIdentity>(identityFromRun(stateRef.current.run));
  const pendingTurnStartRef = useRef<PendingTurnStart | null>(null);
  const pendingTurnStartSequenceRef = useRef(0);
  const terminalStatusPollRef = useRef<TerminalStatusPoll | null>(null);

  const cancelTerminalStatusPoll = useCallback(() => {
    const current = terminalStatusPollRef.current;
    if (!current) return;
    terminalStatusPollRef.current = null;
    current.controller.abort();
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      runtimeGenerationRef.current += 1;
      runtimeOwnerRef.current = null;
      pendingTurnStartRef.current = null;
      cancelTerminalStatusPoll();
    };
  }, [cancelTerminalStatusPoll]);

  const isMounted = useCallback(() => mountedRef.current, []);
  const hasOwner = useCallback(() => runtimeOwnerRef.current !== null, []);
  const runtimeGeneration = useCallback(() => runtimeGenerationRef.current, []);

  const waitForRuntimeLifecycleIdle = useCallback(async (): Promise<boolean> => {
    while (mountedRef.current) {
      const owner = runtimeOwnerRef.current;
      if (!owner) return true;
      await owner.promise;
      // A newer generation may have taken ownership while the previous
      // promise was settling. Observe the newer owner before granting access.
      if (runtimeOwnerRef.current === owner) return false;
    }
    return false;
  }, []);

  const waitForRuntimeUserAccess = useCallback(async (): Promise<boolean> => {
    return await waitForRuntimeLifecycleIdle()
      && mountedRef.current
      && runtimeOwnerRef.current === null
      && stateRef.current.runtimeState !== "restarting";
  }, [stateRef, waitForRuntimeLifecycleIdle]);

  const enqueueRuntimeOperation = useCallback((
    kind: RuntimeOperationKind,
    work: (isOwned: RuntimeOwnershipCheck) => Promise<void>,
    onFailure: (error: unknown, isOwned: RuntimeOwnershipCheck) => void | Promise<void>,
    terminalState: RendererState["runtimeState"] = "ready",
  ): Promise<void> => {
    const generation = runtimeGenerationRef.current + 1;
    runtimeGenerationRef.current = generation;
    const publishesLifecycleState = kind !== "navigation";
    const clearsSupersededLifecycleState = kind === "navigation" && stateRef.current.runtimeState === "restarting";
    if (publishesLifecycleState) dispatch({ type: "runtime_state", state: "restarting", error: null });
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
      if (runtimeGenerationRef.current !== generation
        || runtimeOwnerRef.current !== owner
        || runtimeOwnerRef.current?.promise !== owner.promise) return;
      if (!failed && (publishesLifecycleState || clearsSupersededLifecycleState)) dispatch({ type: "runtime_state", state: terminalState, error: null });
      runtimeOwnerRef.current = null;
    });
    const safeOperation = operation.catch(() => {
      // Keep later lifecycle operations runnable if an unexpected adapter
      // error escapes the guarded work above.
    });
    owner.promise = safeOperation;
    runtimeOwnerRef.current = owner;
    runtimeOperationTailRef.current = safeOperation;
    return safeOperation;
  }, [dispatch, stateRef]);

  const startTerminalStatusConvergence = useCallback((
    runId: string,
    turnId: string,
    allowLifecycleOwner = false,
    onIdle?: (result: JsonValue) => void | Promise<void>,
  ): Promise<AuthoritativeIdleResult> => {
    if (!api) return Promise.resolve({ state: "cancelled" });
    if (!knownIdentityMatches(latestTurnRef.current.runId, latestTurnRef.current.turnId, runId, turnId)) return Promise.resolve({ state: "cancelled" });
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
      if (idle.state !== "idle" || !onIdle) return;
      try {
        await onIdle(idle.result);
      } catch {
        // Status/catalog refresh is supplementary; an adapter failure must not
        // create an unhandled rejection from the convergence observer.
      }
    });
    return poll.promise;
  }, [api, cancelTerminalStatusPoll]);

  const hasTerminalStatusPoll = useCallback(() => terminalStatusPollRef.current !== null, []);
  const terminalStatusPollFor = useCallback((runId: string, turnId: string) => {
    const current = terminalStatusPollRef.current;
    return current && current.runId === runId && current.turnId === turnId ? current.promise : null;
  }, []);

  const latestTurnIdentity = useCallback(() => ({ ...latestTurnRef.current }), []);
  const setLatestTurnIdentity = useCallback((identity: RuntimeIdentity) => {
    latestTurnRef.current = { ...identity };
  }, []);
  const beginPendingTurnStart = useCallback((): PendingTurnStart => {
    const pending = { id: pendingTurnStartSequenceRef.current += 1, events: [] as AgentEvent[] };
    pendingTurnStartRef.current = pending;
    return pending;
  }, []);
  const pendingTurnStart = useCallback(() => pendingTurnStartRef.current, []);
  const bufferPendingTurnEvent = useCallback((event: AgentEvent): boolean => {
    const pending = pendingTurnStartRef.current;
    if (!pending || !hasTurnIdentity(eventIdentity(event).runId, eventIdentity(event).turnId)) return false;
    pending.events.push(event);
    return true;
  }, []);
  const finishPendingTurnStart = useCallback((pending: PendingTurnStart, identity: RuntimeIdentity): AgentEvent[] => {
    if (pendingTurnStartRef.current !== pending) return [];
    const buffered = pending.events.filter((event) => eventMatchesIdentity(event, identity));
    pendingTurnStartRef.current = null;
    return buffered;
  }, []);
  const clearPendingTurnStart = useCallback(() => {
    pendingTurnStartRef.current = null;
  }, []);

  return {
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
  };
}

export type { AgentEvent, DesktopApi, JsonObject, JsonValue };
