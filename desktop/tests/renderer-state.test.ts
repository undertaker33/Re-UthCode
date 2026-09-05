import { test } from "node:test";
import assert from "node:assert/strict";
import type { AgentEvent } from "../src/desktop-api";
import {
  createInitialState,
  normalizeProviderRequestUsage,
  reduceRendererState,
  type RendererState,
} from "../src/renderer/state";
import {
  normalizeCompactionStatus,
  normalizeContextUsage,
  normalizePendingInteraction,
  normalizeRun,
  replayToTimeline,
} from "../src/renderer/state-normalization";
import { recoverMojibake } from "../src/renderer/text-normalization";
import { applyProjectOpened, applyRuntimeSnapshot, applySessionResumed, runtimeSnapshotFromState, sessionLabel, sessionRuntimeKey } from "../src/renderer/state-session";

function replayRecord(sequence: number, kind: string, text: string) {
  return {
    session_id: "session-1",
    sequence,
    turn_id: "turn-1",
    kind,
    text,
    is_error: false,
  } as never;
}

test("T04 replay is ordered and session labels use title, preview, then short id", () => {
  const records = [
    replayRecord(5, "assistant", "answer"),
    replayRecord(1, "user", "prompt"),
    replayRecord(4, "tool", "Bash completed"),
    replayRecord(2, "steering", "continue"),
    replayRecord(3, "reasoning", "thinking"),
  ];
  const timeline = replayToTimeline(records);
  assert.deepEqual(timeline.map((entry) => entry.text), ["prompt", "continue", "thinking", "Bash completed", "answer"]);
  assert.equal(sessionLabel({ session_id: "session-1", title: "Persistent title", preview: "A useful preview" }), "Persistent title");
  assert.equal(sessionLabel({ session_id: "session-1", preview: "A useful preview" }), "A useful preview");
  assert.equal(sessionLabel({ session_id: "abcdef1234567890", preview: "" }), "abcdef12");
});

test("T04 session transitions replace replay and keep new session empty", () => {
  const initial = createInitialState();
  const opened = applyProjectOpened(initial, {
    project: { path: "C:/Projects/one" },
    sessions: [
      { session_id: "one", project_key: "C:/Projects/one", preview: "first", last_used_at: "" },
      { session_id: "two", project_key: "C:/Projects/one", preview: "second", last_used_at: "" },
      { session_id: "three", project_key: "C:/Projects/one", preview: "third", last_used_at: "" },
    ],
    run: null,
  });
  const resumed = applySessionResumed(opened, {
    session_id: "two",
    restored: true,
    replay: [replayRecord(1, "user", "restored")],
    run: null,
  });
  assert.equal(resumed.selectedSessionId, "two");
  assert.deepEqual(resumed.timeline.map((entry) => entry.text), ["restored"]);
  const fresh = reduceRendererState(resumed, { type: "session_new", sessionId: "three", run: { run_id: "fresh-run", status: "idle" } });
  assert.equal(fresh.selectedSessionId, "three");
  assert.deepEqual(fresh.timeline, []);
  assert.equal(fresh.activeTurn, false);
  assert.equal(fresh.run?.run_id, "fresh-run");
});

test("history pages merge with live output, dedupe stable identities, and ignore stale Sessions", () => {
  const projectKey = "C:/Projects/history-renderer";
  const key = sessionRuntimeKey(projectKey, "session-a");
  let state = createInitialState({
    selectedProjectKey: projectKey,
    selectedSessionId: "session-a",
    timeline: [{ id: "live-assistant", kind: "assistant", text: "live tail", turnId: "turn-1", messageId: "message-1", streaming: true }],
    projects: [{
      path: projectKey,
      projectKey,
      alias: "History",
      pinned: false,
      sessions: [{ session_id: "session-a" }, { session_id: "session-b" }],
      catalogFresh: true,
    }],
  });
  state = reduceRendererState(state, { type: "history_page_started", projectKey, sessionId: "session-a" });
  state = reduceRendererState(state, {
    type: "history_page_loaded",
    projectKey,
    sessionId: "session-a",
    replace: true,
    result: {
      session_id: "session-a",
      records: [
        { record_id: "session-a:1:user:0", session_id: "session-a", sequence: 1, turn_id: "turn-1", kind: "user", text: "prompt", is_error: false },
        { record_id: "session-a:2:assistant:0", session_id: "session-a", sequence: 2, turn_id: "turn-1", kind: "assistant", message_id: "message-1", text: "durable final", is_error: false },
      ],
      next_cursor: "older",
      has_more: true,
      unit_count: 1,
    },
  });
  assert.deepEqual(state.timeline.map((entry) => entry.text), ["prompt", "durable final"]);
  assert.equal(state.sessionHistory[key]?.records.length, 2);
  state = reduceRendererState(state, {
    type: "history_page_loaded",
    projectKey,
    sessionId: "session-a",
    result: {
      session_id: "session-a",
      records: [
        { record_id: "session-a:1:user:0", session_id: "session-a", sequence: 1, turn_id: "turn-1", kind: "user", text: "prompt", is_error: false },
        { record_id: "session-a:2:assistant:0", session_id: "session-a", sequence: 2, turn_id: "turn-1", kind: "assistant", text: "durable final", is_error: false },
      ],
      next_cursor: null,
      has_more: false,
      unit_count: 1,
    },
  });
  assert.equal(state.sessionHistory[key]?.records.length, 2, "repeated page identities are collapsed");
  assert.equal(state.timeline.filter((entry) => entry.kind === "assistant").length, 1, "live and durable assistant are one visible record");

  let liveTail = createInitialState({
    selectedProjectKey: projectKey,
    selectedSessionId: "session-a",
    timeline: [{ id: "live-new", kind: "assistant", text: "live:new", turnId: "turn-2", streaming: true }],
  });
  liveTail = reduceRendererState(liveTail, {
    type: "history_page_loaded",
    projectKey,
    sessionId: "session-a",
    replace: true,
    result: {
      session_id: "session-a",
      records: [
        { record_id: "session-a:1:user:0", session_id: "session-a", sequence: 1, turn_id: "turn-1", kind: "user", text: "oldprompt", is_error: false },
        { record_id: "session-a:2:assistant:0", session_id: "session-a", sequence: 2, turn_id: "turn-1", kind: "assistant", text: "oldanswer", is_error: false },
      ],
      next_cursor: null,
      has_more: false,
      unit_count: 1,
    },
  });
  assert.deepEqual(liveTail.timeline.map((entry) => entry.text), ["oldprompt", "oldanswer", "live:new"], "live records remain at the tail after older history is inserted");

  const beforeStale = state;
  const stale = reduceRendererState(state, {
    type: "history_page_loaded",
    projectKey,
    sessionId: "session-b",
    result: { session_id: "session-a", records: [], next_cursor: null, has_more: false, unit_count: 0 },
  });
  assert.deepEqual(stale, beforeStale, "a response for another Session cannot replace the current view");
});

test("history merge preserves distinct same-turn assistant parts and messages", () => {
  const projectKey = "C:/Projects/history-identities";
  const base = createInitialState({
    selectedProjectKey: projectKey,
    selectedSessionId: "session-a",
    timeline: [{ id: "live-assistant", kind: "assistant", text: "streaming prefix", turnId: "turn-1", messageId: "message-1", streaming: true }],
  });
  const result = reduceRendererState(base, {
    type: "history_page_loaded",
    projectKey,
    sessionId: "session-a",
    replace: true,
    result: {
      session_id: "session-a",
      records: [
        { record_id: "session-a:1:assistant::0", session_id: "session-a", sequence: 1, turn_id: "turn-1", kind: "assistant", message_id: "message-1", text: "part one", is_error: false },
        { record_id: "session-a:1:assistant::1", session_id: "session-a", sequence: 1, turn_id: "turn-1", kind: "assistant", message_id: "message-1", text: "part two", is_error: false },
        { record_id: "session-a:2:assistant::0", session_id: "session-a", sequence: 2, turn_id: "turn-1", kind: "assistant", message_id: "message-2", text: "independent message", is_error: false },
      ],
      next_cursor: null,
      has_more: false,
      unit_count: 1,
    },
  });
  assert.equal(result.timeline.filter((entry) => entry.kind === "assistant").length, 3);
  assert.deepEqual(result.timeline.map((entry) => entry.text), ["part one", "part two", "independent message"]);
  assert.equal(result.sessionHistory[sessionRuntimeKey(projectKey, "session-a")]?.records.length, 3);
});

test("preparing Session resume keeps its history timeline and marks ready only after the boundary", () => {
  const projectKey = "C:/Projects/history-preparing";
  let state = createInitialState({ selectedProjectKey: projectKey, selectedSessionId: "session-a" });
  state = reduceRendererState(state, { type: "history_page_started", projectKey, sessionId: "session-a" });
  state = reduceRendererState(state, {
    type: "history_page_loaded",
    projectKey,
    sessionId: "session-a",
    replace: true,
    result: {
      session_id: "session-a",
      records: [{ record_id: "session-a:1:user:0", session_id: "session-a", sequence: 1, turn_id: "turn-1", kind: "user", text: "history", is_error: false }],
      next_cursor: null,
      has_more: false,
      unit_count: 1,
    },
  });
  assert.equal(state.sessionPreparation[sessionRuntimeKey(projectKey, "session-a")], "preparing");
  const resumed = reduceRendererState(state, {
    type: "session_resumed",
    preserveRuntimeState: true,
    preserveSessionRuntime: true,
    preserveTimeline: true,
    result: {
      session_id: "session-a",
      replay: [],
      run: null,
      session_state: { active_turn: false, run: null },
    },
  });
  assert.deepEqual(resumed.timeline.map((entry) => entry.text), ["history"]);
  assert.equal(resumed.sessionPreparation[sessionRuntimeKey(projectKey, "session-a")], "ready");
  assert.deepEqual(resumed.sessionRuntime[sessionRuntimeKey(projectKey, "session-a")]?.timeline.map((entry) => entry.text), ["history"]);
});

test("T05 Provider usage follows Session boundaries, snapshots, and delayed status", () => {
  const projectKey = "C:/Projects/provider-usage-boundary";
  const usage = (input: number, output: number) => normalizeProviderRequestUsage({
    status: "available",
    input_tokens: input,
    output_tokens: output,
    total_tokens: input + output,
    cache_read: { status: "not_available", tokens: null, provenance: null },
    cache_write: { status: "not_available", tokens: null, provenance: null },
  });
  const usageA = usage(111, 22);
  const usageB = usage(17, 9);
  const opened = applyProjectOpened(createInitialState(), {
    project: { path: projectKey },
    sessions: [{ session_id: "session-a" }, { session_id: "session-b" }],
    run: null,
  });
  const stateA = createInitialState({
    ...opened,
    selectedSessionId: "session-a",
    lastProviderRequestUsage: usageA,
    run: { run_id: "run-a", status: "completed" },
  });

  const newSession = reduceRendererState(stateA, {
    type: "session_new",
    sessionId: "session-b",
    run: { run_id: "run-b", status: "idle" },
  });
  assert.equal(newSession.lastProviderRequestUsage.status, "not_available", "new Session starts without the prior request usage");
  assert.equal(newSession.sessionRuntime[sessionRuntimeKey(projectKey, "session-a")]?.lastProviderRequestUsage?.total_tokens, 133, "the prior usage remains with Session A");
  assert.equal(newSession.sessionRuntime[sessionRuntimeKey(projectKey, "session-b")]?.lastProviderRequestUsage?.status, "not_available");

  const projectOpened = applyProjectOpened(stateA, {
    project: { path: "C:/Projects/provider-usage-other" },
    sessions: [],
    run: null,
  });
  assert.equal(projectOpened.lastProviderRequestUsage.status, "not_available", "project_opened clears the visible usage boundary");
  assert.equal(projectOpened.sessionRuntime[sessionRuntimeKey(projectKey, "session-a")]?.lastProviderRequestUsage?.total_tokens, 133);

  const cachedB = runtimeSnapshotFromState(createInitialState({
    ...stateA,
    selectedSessionId: "session-b",
    lastProviderRequestUsage: usageB,
    run: { run_id: "run-b", status: "completed" },
  }));
  const resumedB = applySessionResumed(
    createInitialState({
      ...stateA,
      sessionRuntime: { [sessionRuntimeKey(projectKey, "session-b")]: cachedB },
    }),
    {
      session_id: "session-b",
      session_state: { active_turn: false, run: { run_id: "run-b", status: "completed" } },
      replay: [],
    },
  );
  assert.equal(resumedB.lastProviderRequestUsage.total_tokens, 26, "session_resumed restores usage from the existing Session snapshot");

  const delayedFailure = reduceRendererState(newSession, {
    type: "status_loaded",
    result: {
      session_id: "session-a",
      project_key: projectKey,
      active_turn: false,
      application: { last_provider_request_usage: usageA },
      session_state: { active_turn: false, run: { run_id: "run-a", status: "failed" } },
    },
  });
  assert.equal(delayedFailure.selectedSessionId, "session-b");
  assert.equal(delayedFailure.lastProviderRequestUsage.status, "not_available", "a delayed failure for Session A cannot overwrite Session B usage");
  assert.equal(delayedFailure.sessionRuntime[sessionRuntimeKey(projectKey, "session-a")]?.lastProviderRequestUsage?.total_tokens, 133, "the delayed status is retained on Session A");
});

test("delayed status from another project cannot overwrite the visible Session projection", () => {
  const visibleProject = "C:/Projects/status-visible";
  const delayedProject = "C:/Projects/status-delayed";
  const visible = createInitialState({
    selectedProjectKey: visibleProject,
    selectedSessionId: "shared-session",
    timeline: [{ id: "visible", kind: "assistant", text: "visible output", runId: "visible-run", turnId: "visible-turn" }],
    run: { run_id: "visible-run", turn_id: "visible-turn", status: "running" },
    activeTurn: true,
    turnStatus: "running",
    contextUsage: { used_tokens: 12, budget_tokens: 100, available: true, measurement: "exact", source: "visible" },
    projects: [{
      path: visibleProject,
      projectKey: visibleProject,
      alias: "Visible",
      pinned: false,
      sessions: [{ session_id: "shared-session", runtime_status: "running" }],
      catalogFresh: true,
    }],
  });
  const delayed = reduceRendererState(visible, {
    type: "status_loaded",
    result: {
      session_id: "shared-session",
      project_key: delayedProject,
      active_turn: false,
      application: { context_status: { used_tokens: 999, budget_tokens: 1000, available: true, measurement: "exact", source: "delayed" } },
      session_state: { active_turn: false, run: { run_id: "delayed-run", status: "completed" } },
    },
  });
  assert.equal(delayed.timeline[0]?.text, "visible output");
  assert.equal(delayed.run?.run_id, "visible-run");
  assert.equal(delayed.contextUsage.used_tokens, 12);
  assert.equal(delayed.sessionRuntime[sessionRuntimeKey(delayedProject, "shared-session")]?.timeline.length, 0, "the offscreen project must not seed its cache from visible timeline");
});

test("durable failure replay restores retained output and the failed Turn projection", () => {
  const initial = applyProjectOpened(createInitialState(), {
    project: { path: "C:/Projects/failure-replay" },
    sessions: [{ session_id: "failed-session", preview: "failed request" }],
    run: null,
  });
  let resumed = applySessionResumed(initial, {
    session_id: "failed-session",
    restored: true,
    replay: [
      replayRecord(1, "user", "investigate"),
      replayRecord(2, "reasoning", "retained reasoning"),
      replayRecord(3, "assistant", "retained partial answer"),
      { session_id: "failed-session", sequence: 4, turn_id: "turn-failed", kind: "failure", termination_reason: "provider_error", failure_reason: "invalid_provider_response", is_error: true },
    ],
    active_turn: false,
    run: { run_id: "fresh-run", status: "idle" },
    session_state: { active_turn: false, run: { run_id: "fresh-run", status: "idle" } },
  });
  assert.deepEqual(resumed.timeline.map((entry) => entry.text), ["investigate", "retained reasoning", "retained partial answer", "Turn failed: invalid_provider_response"]);
  assert.equal(resumed.timeline.at(-1)?.kind, "status");
  assert.equal(resumed.timeline.at(-1)?.status, "failed");
  assert.equal(resumed.timeline.at(-1)?.isError, true);
  assert.equal(resumed.activeTurn, false);
  assert.equal(resumed.turnStatus, "failed");
  assert.equal(resumed.projects[0]?.sessions[0]?.runtime_status, "failed");
  resumed = reduceRendererState(resumed, {
    type: "status_loaded",
    result: { session_id: "failed-session", project_key: "C:/Projects/failure-replay", active_turn: false, session_state: { active_turn: false, run: { run_id: "fresh-run", status: "idle" } } },
  });
  assert.equal(resumed.turnStatus, "failed", "the authoritative idle refresh must not erase the replayed terminal failure");
  assert.equal(resumed.projects[0]?.sessions[0]?.runtime_status, "failed");
});

test("background Agent events are cached per Session and restored with Todo/pause state", () => {
  let state = applyProjectOpened(createInitialState(), {
    project: { path: "C:/Projects/background" },
    sessions: [
      { session_id: "session-a", preview: "A" },
      { session_id: "session-b", preview: "B" },
    ],
    run: null,
  });
  state = applySessionResumed(state, {
    session_id: "session-a",
    restored: true,
    replay: [],
    active_turn: false,
    run: { run_id: "run-a", turn_id: "turn-a", status: "idle" },
  });
  const event = (payload: Record<string, unknown>) => ({ type: "agent_event" as const, event: payload as AgentEvent });
  state = reduceRendererState(state, event({
    type: "assistant_message_delta",
    session_id: "session-b",
    project_key: "C:/Projects/background",
    run_id: "run-b",
    turn_id: "turn-b",
    message_id: "message-b",
    text: "后台输出",
  }));
  state = reduceRendererState(state, event({
    type: "task_state_changed",
    session_id: "session-b",
    project_key: "C:/Projects/background",
    run_id: "run-b",
    turn_id: "turn-b",
    iteration: 1,
    task_state: { items: [{ content: "后台任务", status: "in_progress" }] },
  }));
  state = reduceRendererState(state, event({
    type: "turn_paused",
    session_id: "session-b",
    project_key: "C:/Projects/background",
    run_id: "run-b",
    turn_id: "turn-b",
    pause: { pause_id: "pause-b", run_id: "run-b", turn_id: "turn-b", kind: "user_input_required", reason: "user_input_required", iteration: 1 },
  }));
  assert.equal(state.projects[0]?.sessions[1]?.runtime_status, "waiting");
  const cached = state.sessionRuntime[sessionRuntimeKey("C:/Projects/background", "session-b")];
  assert.equal(cached?.todo[0]?.content, "后台任务");
  assert.equal(cached?.pendingInteraction?.pauseId, "pause-b");

  state = applySessionResumed(state, {
    session_id: "session-b",
    restored: true,
    replay: [],
    active_turn: true,
    run: { run_id: "run-b", turn_id: "turn-b", status: "paused" },
  });
  assert.equal(state.selectedSessionId, "session-b");
  assert.equal(state.timeline[0]?.text, "后台输出");
  assert.deepEqual(state.todo, [{ content: "后台任务", status: "in_progress" }]);
  assert.equal(state.pendingInteraction?.pauseId, "pause-b");
  assert.equal(state.turnStatus, "paused");
});

test("a running Session keeps later deltas and status when navigating away and back", () => {
  const projectKey = "C:/Projects/navigation-live";
  const event = (payload: Record<string, unknown>) => ({ type: "agent_event" as const, event: payload as AgentEvent });
  let state = applyProjectOpened(createInitialState(), {
    project: { path: projectKey },
    sessions: [{ session_id: "session-a" }, { session_id: "session-b" }],
    run: null,
  });
  state = applySessionResumed(state, {
    session_id: "session-a",
    restored: true,
    replay: [],
    active_turn: true,
    run: { run_id: "run-a", turn_id: "turn-a", status: "running" },
    session_state: { active_turn: true, run: { run_id: "run-a", turn_id: "turn-a", status: "running" } },
  });
  state = reduceRendererState(state, event({
    type: "assistant_message_delta",
    session_id: "session-a",
    project_key: projectKey,
    run_id: "run-a",
    turn_id: "turn-a",
    message_id: "message-a",
    text: "before navigation",
  }));
  state = applySessionResumed(state, {
    session_id: "session-b",
    restored: true,
    replay: [],
    active_turn: true,
    run: { run_id: "run-b", turn_id: "turn-b", status: "running" },
    session_state: { active_turn: true, run: { run_id: "run-b", turn_id: "turn-b", status: "running" } },
  }, true, undefined, true);
  state = reduceRendererState(state, event({
    type: "assistant_message_delta",
    session_id: "session-a",
    project_key: projectKey,
    run_id: "run-a",
    turn_id: "turn-a",
    message_id: "message-a",
    text: "after navigation",
  }));
  const cachedA = state.sessionRuntime[sessionRuntimeKey(projectKey, "session-a")];
  assert.equal(cachedA?.timeline.find((entry) => entry.messageId === "message-a")?.text, "before navigationafter navigation");
  assert.equal(state.projects[0]?.sessions[0]?.runtime_status, "running");

  state = reduceRendererState(state, {
    type: "catalog_refreshed",
    projectKey,
    sessions: [{ session_id: "session-a" }, { session_id: "session-b" }],
  });
  assert.equal(state.projects[0]?.sessions[0]?.runtime_status, "running", "catalog refresh without a live field must not clear the running icon");

  state = applySessionResumed(state, {
    session_id: "session-a",
    restored: true,
    replay: [],
    active_turn: true,
    run: { run_id: "run-a", turn_id: "turn-a", status: "running" },
    session_state: { active_turn: true, run: { run_id: "run-a", turn_id: "turn-a", status: "running" } },
  }, true, undefined, true);
  state = reduceRendererState(state, event({
    type: "assistant_message_delta",
    session_id: "session-a",
    project_key: projectKey,
    run_id: "run-a",
    turn_id: "turn-a",
    message_id: "message-a",
    text: "after return",
  }));
  assert.equal(state.timeline.find((entry) => entry.messageId === "message-a")?.text, "before navigationafter navigationafter return");
});

test("workspace clear invalidates visible and parked Session runs before late events can rebuild cache", () => {
  const projectKey = "C:/Projects/clear-runtime";
  const event = (sessionId: string, runId: string, turnId: string) => ({
    type: "agent_event" as const,
    event: {
      type: "assistant_message_delta",
      session_id: sessionId,
      project_key: projectKey,
      run_id: runId,
      turn_id: turnId,
      message_id: `message-${sessionId}`,
      text: "late",
    } as AgentEvent,
  });
  let state = applyProjectOpened(createInitialState(), {
    project: { path: projectKey },
    sessions: [{ session_id: "session-a" }, { session_id: "session-b" }],
    run: null,
  });
  state = applySessionResumed(state, {
    session_id: "session-a",
    restored: true,
    replay: [],
    active_turn: true,
    run: { run_id: "run-a", turn_id: "turn-a", status: "running" },
    session_state: { active_turn: true, run: { run_id: "run-a", turn_id: "turn-a", status: "running" } },
  });
  state = reduceRendererState(state, event("session-a", "run-a", "turn-a"));
  state = reduceRendererState(state, {
    type: "session_resumed",
    preserveRuntimeState: true,
    preserveSessionRuntime: true,
    result: {
      session_id: "session-b",
      restored: true,
      replay: [],
      active_turn: true,
      run: { run_id: "run-b", turn_id: "turn-b", status: "running" },
      session_state: { active_turn: true, run: { run_id: "run-b", turn_id: "turn-b", status: "running" } },
    },
  });
  state = reduceRendererState(state, event("session-b", "run-b", "turn-b"));
  assert.ok(state.sessionRuntime[sessionRuntimeKey(projectKey, "session-a")]);
  assert.ok(state.sessionRuntime[sessionRuntimeKey(projectKey, "session-b")]);

  state = reduceRendererState(state, { type: "workspace_cleared" });
  assert.deepEqual(state.sessionRuntime, {});
  state = reduceRendererState(state, event("session-a", "run-a", "turn-a"));
  state = reduceRendererState(state, event("session-b", "run-b", "turn-b"));
  assert.deepEqual(state.sessionRuntime, {}, "late events from every invalidated Session remain stale after clear");
  assert.deepEqual(state.timeline, []);
});

test("Renderer treats an explicit null pending pause as authoritative", () => {
  let state = createInitialState({
    selectedProjectKey: "C:/Projects/current",
    selectedSessionId: "session-current",
    run: { run_id: "run-current", turn_id: "turn-current", status: "running" },
    activeTurn: true,
    turnStatus: "running",
  });
  state = reduceRendererState(state, {
    type: "agent_event",
    event: {
      type: "turn_paused",
      run_id: "run-current",
      turn_id: "turn-current",
      pause: {
        kind: "permission_required",
        pause_id: "pause-completed",
        run_id: "run-current",
        turn_id: "turn-current",
        permission_request: { permission_id: "permission-completed", choices: ["once", "reject"] },
      },
    },
  });
  assert.equal(state.sessionRuntime[sessionRuntimeKey("C:/Projects/current", "session-current")]?.pendingInteraction?.pauseId, "pause-completed");
  state = reduceRendererState(state, {
    type: "status_loaded",
    result: {
      session_id: "session-current",
      project_key: "C:/Projects/current",
      active_turn: true,
      session_state: {
        run: { run_id: "run-current", turn_id: "turn-current", status: "running" },
        active_turn: true,
        status: "running",
        pending_pause: null,
      },
    },
  });
  assert.equal(state.pendingInteraction, null, "an answered permission cannot be restored from cached Renderer state");
  assert.equal(state.turnStatus, "running");
});

test("Renderer retains a cached pause only when a partial status omits the field", () => {
  let state = createInitialState({
    selectedProjectKey: "C:/Projects/current",
    selectedSessionId: "session-current",
    run: { run_id: "run-current", turn_id: "turn-current", status: "running" },
    activeTurn: true,
    turnStatus: "running",
  });
  state = reduceRendererState(state, {
    type: "agent_event",
    event: {
      type: "turn_paused",
      run_id: "run-current",
      turn_id: "turn-current",
      pause: {
        kind: "permission_required",
        pause_id: "pause-current",
        run_id: "run-current",
        turn_id: "turn-current",
        permission_request: { permission_id: "permission-current", choices: ["once", "reject"] },
      },
    },
  });
  state = reduceRendererState(state, {
    type: "status_loaded",
    result: {
      session_id: "session-current",
      project_key: "C:/Projects/current",
      active_turn: true,
      session_state: {
        run: { run_id: "run-current", turn_id: "turn-current", status: "paused" },
        active_turn: true,
        status: "waiting",
      },
    },
  });
  assert.equal(state.pendingInteraction?.pauseId, "pause-current");
});

test("Renderer increments live context estimate for streamed assistant deltas", () => {
  const initial = createInitialState({
    contextUsage: { used_tokens: 10, budget_tokens: 100, available: true, measurement: "exact", source: "provider" },
    run: { run_id: "run-live", turn_id: "turn-live", status: "running" },
    activeTurn: true,
    turnStatus: "running",
  });
  const next = reduceRendererState(initial, {
    type: "agent_event",
    event: {
      type: "assistant_message_delta",
      run_id: "run-live",
      turn_id: "turn-live",
      message_id: "message-live",
      text: "streamed output",
    },
  });
  assert.ok(next.contextUsage.used_tokens > 10);
  assert.equal(next.contextUsage.measurement, "estimate");
  assert.equal(next.contextUsage.source, "turn");
  assert.equal(next.timeline.find((entry) => entry.kind === "assistant")?.text, "streamed output");
});

test("Renderer keeps cumulative Turn usage out of the current-request Context projection", () => {
  const contextUsage = { used_tokens: 40, budget_tokens: 100, available: true, measurement: "estimate" as const, source: "application" };
  const initial = createInitialState({
    contextUsage,
    run: { run_id: "run-tools", turn_id: "turn-tools", status: "running" },
    activeTurn: true,
    turnStatus: "running",
  });
  const next = reduceRendererState(initial, {
    type: "agent_event",
    event: {
      type: "usage_updated",
      run_id: "run-tools",
      turn_id: "turn-tools",
      iteration: 2,
      usage: { input_tokens: 175, output_tokens: 12 },
    },
  });
  assert.deepEqual(next.contextUsage, contextUsage, "multi-request Turn totals are not current Context usage");
  assert.deepEqual(next.run?.usage, { input_tokens: 175, output_tokens: 12 }, "cumulative usage remains visible on the Run");
});

test("Renderer recovers unambiguous UTF-8 mojibake without changing real Chinese", () => {
  const latinMojibake = String.fromCharCode(0xe4, 0xbd, 0xa0, 0xe5, 0xa5, 0xbd);
  assert.equal(recoverMojibake(latinMojibake), "你好");
  assert.equal(recoverMojibake("浣犲ソ"), "你好");
  assert.equal(recoverMojibake("你好，这是正常文本"), "你好，这是正常文本");
});

test("T04 catalog and preference updates keep the active project/session navigation projection", () => {
  let state = applyProjectOpened(createInitialState(), {
    project: { path: "C:/Projects/one" },
    sessions: [{ session_id: "session-1", preview: "first" }],
    run: null,
  });
  state = reduceRendererState(state, { type: "catalog_refreshed", projectKey: "C:/Projects/two", sessions: [{ session_id: "session-2", preview: "second" }] });
  state = reduceRendererState(state, { type: "hydrate_preferences", preferences: { recentProjects: [{ path: "C:/Projects/one" }, { path: "C:/Projects/two" }], selectedProjectKey: "C:/Projects/one", selectedSessionId: "session-1" } });
  state = reduceRendererState(state, { type: "hydrate_preferences", preferences: { projectAliases: { "C:/Projects/one": "Renamed" } } });
  state = reduceRendererState(state, { type: "hydrate_preferences", preferences: { pinnedSessions: [{ projectKey: "C:/Projects/one", sessionId: "session-1" }] } });
  assert.equal(state.selectedProjectKey, "C:/Projects/one");
  assert.equal(state.selectedSessionId, "session-1");
  assert.equal(state.projects.find((project) => project.projectKey === "C:/Projects/one")?.sessions[0]?.session_id, "session-1");
  assert.equal(state.projects.find((project) => project.projectKey === "C:/Projects/two")?.sessions[0]?.session_id, "session-2");
  assert.equal(state.projects.find((project) => project.projectKey === "C:/Projects/one")?.alias, "Renamed");
  assert.equal(state.projects.find((project) => project.projectKey === "C:/Projects/one")?.sessions[0]?.pinned, true);
});

test("renderer state keeps one reducer authority and normalizes safe projections", () => {
  assert.deepEqual(normalizeCompactionStatus({ state: "running", trigger: "auto", changed: true }), { state: "running", trigger: "auto", changed: null });
  assert.deepEqual(normalizeContextUsage({ used_tokens: 4, budget_tokens: 100, available: true, measurement: "exact", source: "provider" }), { used_tokens: 4, budget_tokens: 100, available: true, measurement: "exact", source: "provider" });
  assert.deepEqual(normalizeContextUsage({ used_tokens: 4 }), { used_tokens: 0, budget_tokens: 0, available: false, measurement: "unavailable", source: "unavailable" });
  assert.deepEqual(normalizePendingInteraction({ pause_id: "pause", run_id: "run", turn_id: "turn", kind: "permission_required" })?.pauseId, "pause");
  assert.equal(normalizeRun({ run_id: "run", permission_mode: "full_access" })?.permission_mode, "full_access");
});

test("renderer state snapshots are copied at session boundaries", () => {
  const state = createInitialState({
    timeline: [{ id: "assistant", kind: "assistant", text: "answer", status: "completed" }],
    todo: [{ content: "task", status: "pending" }],
  });
  const snapshot = runtimeSnapshotFromState(state);
  snapshot.timeline[0]!.text = "mutated";
  snapshot.todo[0]!.content = "mutated";
  assert.equal(state.timeline[0]?.text, "answer");
  assert.equal(state.todo[0]?.content, "task");
  const restored = applyRuntimeSnapshot(createInitialState(), snapshot);
  assert.equal(restored.timeline[0]?.text, "mutated");
});

test("T05 reducer keeps event order, replaces assistant preview, and settles tools once", () => {
  let state = createInitialState();
  state = reduceRendererState(state, { type: "agent_event", event: { type: "turn_started", run_id: "run-1", turn_id: "turn-1", message_id: "user-1", message: { role: "user", parts: [{ type: "text", text: "prompt" }] } } });
  state = reduceRendererState(state, { type: "agent_event", event: { type: "reasoning_started", run_id: "run-1", turn_id: "turn-1", message_id: "reason-1", iteration: 1, segment_index: 1 } });
  state = reduceRendererState(state, { type: "agent_event", event: { type: "reasoning_delta", run_id: "run-1", turn_id: "turn-1", message_id: "reason-1", iteration: 1, text: "thinking" } });
  state = reduceRendererState(state, { type: "agent_event", event: { type: "assistant_message_delta", run_id: "run-1", turn_id: "turn-1", message_id: "answer-1", iteration: 1, text: "preview" } });
  state = reduceRendererState(state, { type: "agent_event", event: { type: "tool_started", run_id: "run-1", turn_id: "turn-1", batch_id: "batch-1", tool_call_id: "call-1", tool_name: "Bash", command: "echo safe", iteration: 1 } });
  state = reduceRendererState(state, { type: "agent_event", event: { type: "tool_finished", run_id: "run-1", turn_id: "turn-1", batch_id: "batch-1", tool_call_id: "call-1", tool_name: "Bash", command: "echo safe", status: "succeeded", is_error: false, iteration: 1 } });
  state = reduceRendererState(state, { type: "agent_event", event: { type: "assistant_message_completed", run_id: "run-1", turn_id: "turn-1", message_id: "answer-1", iteration: 1, kind: "final", message: { role: "assistant", parts: [{ type: "text", text: "authoritative" }] } } });
  const assistant = state.timeline.filter((entry) => entry.kind === "assistant");
  const tools = state.timeline.filter((entry) => entry.kind === "tool");
  assert.deepEqual(assistant.map((entry) => entry.text), ["authoritative"]);
  assert.equal(tools.length, 1);
  assert.equal(tools[0]?.status, "completed");
  assert.equal(state.timeline.find((entry) => entry.kind === "reasoning")?.streaming, false);
});

test("T08 reducer rejects stale same-Run events from an older Turn", () => {
  const current = createInitialState({
    activeTurn: true,
    turnStatus: "running",
    run: { run_id: "run-1", turn_id: "turn-2", status: "running" },
    todo: [{ content: "current task", status: "in_progress" }],
    todoIteration: 3,
  });
  const staleEvents: AgentEvent[] = [
    { type: "assistant_message_delta", run_id: "run-1", turn_id: "turn-1", message_id: "old-answer", text: "stale" },
    { type: "task_state_changed", run_id: "run-1", turn_id: "turn-1", iteration: 4, task_state: { items: [{ content: "old task", status: "completed" }] } },
    { type: "turn_completed", run_id: "run-1", turn_id: "turn-1", final_text: "old final" },
  ];
  for (const event of staleEvents) {
    assert.equal(reduceRendererState(current, { type: "agent_event", event }), current, `stale ${event.type} must not mutate the current Turn`);
  }
});

test("T08 reducer ignores late stream data and duplicate tool terminals", () => {
  let state = createInitialState();
  const event = (payload: Record<string, unknown>) => ({ type: "agent_event" as const, event: payload as AgentEvent });
  state = reduceRendererState(state, event({ type: "reasoning_delta", run_id: "run-1", turn_id: "turn-1", message_id: "reason-1", text: "thinking" }));
  state = reduceRendererState(state, event({ type: "reasoning_finished", run_id: "run-1", turn_id: "turn-1", message_id: "reason-1" }));
  assert.equal(reduceRendererState(state, event({ type: "reasoning_delta", run_id: "run-1", turn_id: "turn-1", message_id: "reason-1", text: "late" })), state);

  state = reduceRendererState(state, event({ type: "assistant_message_delta", run_id: "run-1", turn_id: "turn-1", message_id: "answer-1", text: "answer" }));
  state = reduceRendererState(state, event({ type: "assistant_message_completed", run_id: "run-1", turn_id: "turn-1", message_id: "answer-1", message: { role: "assistant", parts: [{ type: "text", text: "answer" }] } }));
  assert.equal(reduceRendererState(state, event({ type: "assistant_message_delta", run_id: "run-1", turn_id: "turn-1", message_id: "answer-1", text: "late" })), state);

  state = reduceRendererState(state, event({ type: "tool_started", run_id: "run-1", turn_id: "turn-1", batch_id: "batch-1", tool_call_id: "call-1", tool_name: "Bash" }));
  state = reduceRendererState(state, event({ type: "tool_finished", run_id: "run-1", turn_id: "turn-1", batch_id: "batch-1", tool_call_id: "call-1", tool_name: "Bash", status: "completed", is_error: false }));
  const completedTool = state.timeline.find((entry) => entry.kind === "tool");
  assert.ok(completedTool?.endedAt);
  assert.equal(reduceRendererState(state, event({ type: "tool_finished", run_id: "run-1", turn_id: "turn-1", batch_id: "batch-1", tool_call_id: "call-1", tool_name: "Bash", status: "failed", is_error: true })), state);
  assert.equal(state.timeline.find((entry) => entry.kind === "tool")?.endedAt, completedTool?.endedAt);

  state = reduceRendererState(state, event({ type: "turn_completed", run_id: "run-1", turn_id: "turn-1", final_text: "final" }));
  assert.equal(reduceRendererState(state, event({ type: "assistant_message_delta", run_id: "run-1", turn_id: "turn-1", message_id: "late-answer", text: "late" })), state);
});

test("T08 TaskState projection keeps the newest iteration", () => {
  let state = createInitialState({ run: { run_id: "run-1", turn_id: "turn-1", status: "running" }, activeTurn: true, turnStatus: "running" });
  const event = (iteration: number, content: string) => ({ type: "agent_event" as const, event: { type: "task_state_changed", run_id: "run-1", turn_id: "turn-1", iteration, task_state: { items: [{ content, status: "in_progress" }] } } });
  state = reduceRendererState(state, event(3, "newest"));
  state = reduceRendererState(state, event(2, "older"));
  assert.deepEqual(state.todo, [{ content: "newest", status: "in_progress" }]);
  assert.equal(state.todoIteration, 3);
});

test("T05 failed turns retain displayed assistant content until durable replay", () => {
  let state = createInitialState();
  state = reduceRendererState(state, { type: "agent_event", event: { type: "assistant_message_delta", run_id: "run-1", turn_id: "turn-1", message_id: "answer-1", iteration: 1, text: "unfinished" } });
  state = reduceRendererState(state, { type: "agent_event", event: { type: "turn_failed", run_id: "run-1", turn_id: "turn-1", termination_reason: "provider_error", failure_reason: "provider_request" } });
  assert.equal(state.timeline.some((entry) => entry.text === "unfinished" && entry.kind === "assistant" && entry.streaming === false), true);
  assert.equal(state.timeline.some((entry) => entry.text.includes("provider_request")), true);
  assert.equal(state.activeTurn, true, "Core terminal event must wait for Application active_turn=false");
  assert.equal(state.terminalStatusPending, true);
  state = reduceRendererState(state, { type: "status_loaded", result: { active_turn: true } });
  assert.equal(state.activeTurn, true);
  assert.equal(state.terminalStatusPending, true);
  state = reduceRendererState(state, { type: "status_loaded", result: { active_turn: false } });
  assert.equal(state.activeTurn, false, "only the Application status boundary releases the gate");
  assert.equal(state.terminalStatusPending, false);
});

test("T05 steering and typed pause events remain ordered and visible without exposing request payloads", () => {
  let state = createInitialState({ activeTurn: true, turnStatus: "running", run: { run_id: "run-1", turn_id: "turn-1", status: "running" } });
  state = reduceRendererState(state, { type: "turn_accepted", run: state.run, steering: true, text: "please continue" });
  state = reduceRendererState(state, { type: "agent_event", event: { type: "user_steering_requested", run_id: "run-1", turn_id: "turn-1", steering_id: "steer-1" } });
  state = reduceRendererState(state, { type: "agent_event", event: { type: "turn_pausing", run_id: "run-1", turn_id: "turn-1", pause_id: "pause-1", kind: "user_requested", reason: "user_requested", iteration: 1 } });
  state = reduceRendererState(state, { type: "agent_event", event: { type: "turn_paused", run_id: "run-1", turn_id: "turn-1", pause: { pause_id: "pause-1", run_id: "run-1", turn_id: "turn-1", kind: "user_requested", reason: "user_requested", iteration: 1, created_at: "now" } } });
  assert.equal(state.pendingInteraction?.kind, "user_requested");
  assert.match(state.timeline.map((entry) => entry.text).join(" | "), /please continue|Steering requested|Pausing|Waiting for turn pause/u);
  assert.doesNotMatch(state.timeline.map((entry) => entry.text).join(" | "), /created_at|pause-1/u);
  state = reduceRendererState(state, { type: "agent_event", event: { type: "turn_resumed", run_id: "run-1", turn_id: "turn-1", pause_id: "pause-1", kind: "user_requested" } });
  assert.equal(state.pendingInteraction, null);
  assert.match(state.timeline.at(-1)?.text ?? "", /Interaction answered/u);
});

test("T05 TaskState replaces the visible todo projection and terminal completion clears a block", () => {
  let state = createInitialState();
  state = reduceRendererState(state, { type: "agent_event", event: { type: "task_state_changed", run_id: "run-1", turn_id: "turn-1", iteration: 1, task_state: { items: [{ content: "one", status: "in_progress" }] } } });
  state = reduceRendererState(state, { type: "agent_event", event: { type: "task_state_changed", run_id: "run-1", turn_id: "turn-1", iteration: 2, task_state: { items: [{ content: "two", status: "completed" }] } } });
  assert.deepEqual(state.todo, [{ content: "two", status: "completed" }]);
  state = reduceRendererState(state, { type: "agent_event", event: { type: "completion_blocked", run_id: "run-1", turn_id: "turn-1", iteration: 2, unfinished_count: 1 } });
  assert.match(state.completionBlocked ?? "", /1 unfinished/);
  state = reduceRendererState(state, { type: "agent_event", event: { type: "turn_completed", run_id: "run-1", turn_id: "turn-1", final_text: "final" } });
  assert.equal(state.completionBlocked, null);
  assert.match(state.timeline.at(-1)?.text ?? "", /final/u);
});

test("T06 PlanContentDelta uses iteration identity and PlanProposed seals the matching draft", () => {
  let state = createInitialState();
  const event = (payload: Record<string, unknown>) => ({ type: "agent_event" as const, event: payload as AgentEvent });
  state = reduceRendererState(state, event({ type: "plan_content_delta", run_id: "run-1", turn_id: "turn-1", iteration: 1, tool_call_id: "plan-1", text: "Step " }));
  state = reduceRendererState(state, event({ type: "plan_content_delta", run_id: "run-1", turn_id: "turn-1", iteration: 1, tool_call_id: "plan-1", text: "one" }));
  state = reduceRendererState(state, event({ type: "plan_content_delta", run_id: "run-1", turn_id: "turn-1", iteration: 2, tool_call_id: "plan-2", text: "Other" }));
  const drafts = state.timeline.filter((entry) => entry.kind === "plan");
  assert.equal(drafts.length, 2);
  assert.deepEqual(drafts.map((entry) => entry.text), ["Step one", "Other"]);
  const firstId = drafts[0]?.id;
  state = reduceRendererState(state, event({ type: "plan_proposed", run_id: "run-1", turn_id: "turn-1", iteration: 1, revision: 3, plan_text: "Step one\nStep two" }));
  const finalized = state.timeline.find((entry) => entry.id === firstId);
  assert.equal(state.timeline.filter((entry) => entry.kind === "plan").length, 2);
  assert.equal(finalized?.text, "Step one\nStep two");
  assert.equal(finalized?.streaming, false);
  assert.equal(finalized?.planState, "final");
  state = reduceRendererState(state, event({ type: "plan_content_delta", run_id: "run-1", turn_id: "turn-1", iteration: 1, tool_call_id: "plan-1", text: "stale" }));
  assert.equal(state.timeline.find((entry) => entry.id === firstId)?.text, "Step one\nStep two");
  state = reduceRendererState(state, event({ type: "plan_proposed", run_id: "run-1", turn_id: "turn-1", iteration: 1, revision: 4, plan_text: "Revised step" }));
  assert.equal(state.timeline.filter((entry) => entry.kind === "plan").length, 2, "a later proposal keeps the same visual Plan entity");
  assert.equal(state.timeline.find((entry) => entry.id === firstId)?.text, "Revised step");
});

test("T06 PlanProposed leaves an ambiguous same-iteration pair open", () => {
  let state = createInitialState();
  const event = (payload: Record<string, unknown>) => ({ type: "agent_event" as const, event: payload as AgentEvent });
  state = reduceRendererState(state, event({ type: "plan_content_delta", run_id: "run-1", turn_id: "turn-1", iteration: 1, tool_call_id: "plan-a", text: "A" }));
  state = reduceRendererState(state, event({ type: "plan_content_delta", run_id: "run-1", turn_id: "turn-1", iteration: 1, tool_call_id: "plan-b", text: "B" }));
  state = reduceRendererState(state, event({ type: "plan_proposed", run_id: "run-1", turn_id: "turn-1", iteration: 1, revision: 1, plan_text: "authoritative" }));
  const drafts = state.timeline.filter((entry) => entry.kind === "plan");
  assert.equal(drafts.length, 2);
  assert.equal(drafts.every((entry) => entry.streaming === true && entry.planState === "draft"), true, "missing public tool identity must not close an arbitrary draft");
});

test("T06 Plan draft failure and cancellation settle the matching draft", () => {
  for (const status of ["failed", "cancelled"] as const) {
    let state = createInitialState();
    const event = (payload: Record<string, unknown>) => ({ type: "agent_event" as const, event: payload as AgentEvent });
    state = reduceRendererState(state, event({ type: "plan_content_delta", run_id: "run-1", turn_id: "turn-1", iteration: 1, tool_call_id: `plan-${status}`, text: "draft" }));
    state = reduceRendererState(state, event({ type: "tool_finished", run_id: "run-1", turn_id: "turn-1", batch_id: `batch-${status}`, tool_call_id: `plan-${status}`, tool_name: "ProposePlan", iteration: 1, status, is_error: status === "failed" }));
    const plan = state.timeline.find((entry) => entry.kind === "plan");
    assert.equal(plan?.streaming, false);
    assert.equal(plan?.status, status);
    assert.equal(plan?.planState, status);
  }
});

test("T06 tool rows freeze elapsed time and settle explicit failure/cancellation", () => {
  let state = createInitialState();
  const event = (payload: Record<string, unknown>) => ({ type: "agent_event" as const, event: payload as AgentEvent });
  state = reduceRendererState(state, event({ type: "tool_started", run_id: "run-1", turn_id: "turn-1", batch_id: "batch-1", tool_call_id: "call-1", tool_name: "Bash" }));
  const started = state.timeline.find((entry) => entry.kind === "tool");
  assert.equal(started?.status, "running");
  assert.equal(typeof started?.startedAt, "number");
  state = reduceRendererState(state, event({ type: "tool_finished", run_id: "run-1", turn_id: "turn-1", batch_id: "batch-1", tool_call_id: "call-1", tool_name: "Bash", status: "cancelled", is_error: false }));
  const finished = state.timeline.find((entry) => entry.kind === "tool");
  assert.equal(state.timeline.filter((entry) => entry.kind === "tool").length, 1);
  assert.equal(finished?.status, "cancelled");
  assert.equal(finished?.isError, false);
  assert.equal(typeof finished?.endedAt, "number");
  assert.ok((finished?.endedAt ?? 0) >= (finished?.startedAt ?? 0));
});

test("T05 turn_completed settles reasoning while removing only the assistant preview", () => {
  let state = createInitialState();
  state = reduceRendererState(state, { type: "agent_event", event: { type: "reasoning_delta", run_id: "run-one", turn_id: "turn-one", message_id: "reason-one", text: "reasoning tail" } });
  state = reduceRendererState(state, { type: "agent_event", event: { type: "assistant_message_delta", run_id: "run-one", turn_id: "turn-one", message_id: "answer-one", text: "preview" } });
  state = reduceRendererState(state, { type: "agent_event", event: { type: "turn_completed", run_id: "run-one", turn_id: "turn-one", final_text: "authoritative" } });
  assert.deepEqual(state.timeline.filter((entry) => entry.kind === "reasoning").map((entry) => ({ text: entry.text, status: entry.status, streaming: entry.streaming })), [{ text: "reasoning tail", status: "completed", streaming: false }]);
  assert.deepEqual(state.timeline.filter((entry) => entry.kind === "assistant").map((entry) => entry.text), ["authoritative"]);
  assert.equal(state.timeline.some((entry) => entry.text === "preview"), false);
  assert.equal(state.activeTurn, true);
  assert.equal(state.terminalStatusPending, true);
});

test("T05 failed turns settle and retain reasoning and assistant tails", () => {
  let state = createInitialState();
  state = reduceRendererState(state, { type: "agent_event", event: { type: "reasoning_delta", run_id: "run-one", turn_id: "turn-one", message_id: "reason-one", text: "failed reasoning tail" } });
  state = reduceRendererState(state, { type: "agent_event", event: { type: "assistant_message_delta", run_id: "run-one", turn_id: "turn-one", message_id: "answer-one", text: "failed preview" } });
  state = reduceRendererState(state, { type: "agent_event", event: { type: "turn_failed", run_id: "run-one", turn_id: "turn-one", termination_reason: "provider_error", failure_reason: "provider_request" } });
  assert.deepEqual(state.timeline.filter((entry) => entry.kind === "reasoning").map((entry) => ({ text: entry.text, status: entry.status, streaming: entry.streaming })), [{ text: "failed reasoning tail", status: "completed", streaming: false }]);
  assert.deepEqual(state.timeline.filter((entry) => entry.kind === "assistant").map((entry) => ({ text: entry.text, status: entry.status, streaming: entry.streaming })), [{ text: "failed preview", status: "completed", streaming: false }]);
  assert.equal(state.activeTurn, true);
  assert.equal(state.terminalStatusPending, true);
});

test("T05 cancelled turns settle reasoning tail while removing only assistant preview", () => {
  let state = createInitialState();
  state = reduceRendererState(state, { type: "agent_event", event: { type: "reasoning_delta", run_id: "run-one", turn_id: "turn-one", message_id: "reason-one", text: "cancelled reasoning tail" } });
  state = reduceRendererState(state, { type: "agent_event", event: { type: "assistant_message_delta", run_id: "run-one", turn_id: "turn-one", message_id: "answer-one", text: "cancelled preview" } });
  state = reduceRendererState(state, { type: "agent_event", event: { type: "turn_cancelled", run_id: "run-one", turn_id: "turn-one", termination_reason: "user_cancelled" } });
  assert.deepEqual(state.timeline.filter((entry) => entry.kind === "reasoning").map((entry) => ({ text: entry.text, status: entry.status, streaming: entry.streaming })), [{ text: "cancelled reasoning tail", status: "completed", streaming: false }]);
  assert.equal(state.timeline.some((entry) => entry.text === "cancelled preview"), false);
  assert.equal(state.activeTurn, true);
  assert.equal(state.terminalStatusPending, true);
});

test("T06 permission projection is cleared at fresh Run boundaries and only set by a command result", () => {
  let state = createInitialState({ permissionMode: "auto" });
  state = applyProjectOpened(state, { project: { path: "C:/one" }, sessions: [], run: { run_id: "run-one" } });
  assert.equal(state.permissionMode, "unknown");
  state = reduceRendererState(state, { type: "session_new", sessionId: "session-one", run: { run_id: "run-two" } });
  assert.equal(state.permissionMode, "unknown");
  state = reduceRendererState(state, { type: "command_result", result: { command: "permission", status: "success", code: "permission_mode_selected", params: { mode: "auto", warning: false }, ui_action: { type: "permission_mode_selected", mode: "auto", warning: false } } });
  assert.equal(state.permissionMode, "auto");
});

test("T06 permission projection follows safe Run snapshots and ignores settings defaults", () => {
  const noRun = reduceRendererState(createInitialState({ permissionMode: "auto" }), { type: "settings_loaded", configuration: { default_permission_mode: "auto" } });
  assert.equal(noRun.permissionMode, "unknown");
  let state = createInitialState({ permissionMode: "auto", run: { run_id: "run-old", permission_mode: "auto" } });
  state = reduceRendererState(state, { type: "settings_loaded", configuration: { default_permission_mode: "default" } });
  assert.equal(state.permissionMode, "auto");
  state = applyProjectOpened(state, { project: { path: "C:/one" }, sessions: [], run: { run_id: "run-project", permission_mode: "full_access" } });
  assert.equal(state.permissionMode, "full_access");
  state = reduceRendererState(state, { type: "session_new", sessionId: "session-one", run: { run_id: "run-session", permission_mode: "auto" } });
  assert.equal(state.permissionMode, "auto");
  state = reduceRendererState(state, { type: "command_result", result: { command: "permission", status: "success", code: "permission_mode_selected", params: { run: { run_id: "run-session", permission_mode: "full_access" } }, ui_action: { type: "permission_mode_selected", mode: "default", warning: false } } });
  assert.equal(state.permissionMode, "full_access");
  state = reduceRendererState(state, { type: "turn_accepted", run: { run_id: "run-session", turn_id: "turn-one", permission_mode: "default" }, steering: false });
  assert.equal(state.permissionMode, "default");
});

test("T06 runtime initialization updates permission from its safe Run projection", () => {
  const state = reduceRendererState(createInitialState(), {
    type: "runtime_initialized",
    result: { state: "ready", run: { run_id: "run-runtime", permission_mode: "auto" } },
  });
  assert.equal(state.runtimeState, "ready");
  assert.equal(state.run?.run_id, "run-runtime");
  assert.equal(state.permissionMode, "auto");
});
