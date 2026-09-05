import { test } from "node:test";
import assert from "node:assert/strict";
import { createInitialState, reduceRendererState } from "../src/renderer/state";
import {
  applySessionMutation,
  applyRuntimeSnapshot,
  runtimeSnapshotFromState,
  sessionRuntimeKey,
} from "../src/renderer/state-session";

test("renderer Session runtime snapshots round-trip without sharing mutable projection data", () => {
  const source = createInitialState({
    selectedProjectKey: "C:/one",
    selectedSessionId: "session-a",
    timeline: [{ id: "assistant", kind: "assistant", text: "A", status: "completed" }],
    todo: [{ content: "A task", status: "pending" }],
    run: { run_id: "run-a", turn_id: "turn-a", status: "completed", usage: { output_tokens: 2 } },
  });
  const snapshot = runtimeSnapshotFromState(source);
  const restored = applyRuntimeSnapshot(createInitialState(), snapshot);
  assert.deepEqual(restored.timeline, source.timeline);
  assert.deepEqual(restored.todo, source.todo);
  assert.deepEqual(restored.run, source.run);
  restored.timeline[0]!.text = "changed";
  restored.todo[0]!.content = "changed";
  assert.equal(source.timeline[0]!.text, "A");
  assert.equal(source.todo[0]!.content, "A task");
});

test("renderer Session keys isolate same IDs across projects", () => {
  assert.notEqual(sessionRuntimeKey("C:/one", "shared"), sessionRuntimeKey("C:/two", "shared"));
  assert.equal(sessionRuntimeKey(null, "shared"), "\u0000shared");
});

test("catalog refresh updates session rows in place instead of sorting a resumed row to the head", () => {
  const initial = createInitialState({
    projects: [{
      path: "C:/one",
      projectKey: "C:/one",
      alias: "One",
      pinned: false,
      sessions: [
        { session_id: "s1", preview: "one", last_used_at: "2026-08-01" },
        { session_id: "s2", preview: "two", last_used_at: "2026-08-02" },
        { session_id: "s3", preview: "three", last_used_at: "2026-08-03" },
      ],
      catalogFresh: true,
    }],
  });
  const refreshed = reduceRendererState(initial, {
    type: "catalog_refreshed",
    projectKey: "C:/one",
    sessions: [
      { session_id: "s3", preview: "three updated", last_used_at: "2026-08-04" },
      { session_id: "s2", preview: "two updated", last_used_at: "2026-08-05" },
      { session_id: "s1", preview: "one updated", last_used_at: "2026-08-06" },
      { session_id: "s4", preview: "new", last_used_at: "2026-08-07" },
    ],
  });
  assert.deepEqual(refreshed.projects[0]?.sessions.map((session) => session.session_id), ["s1", "s2", "s3", "s4"]);
  assert.equal(refreshed.projects[0]?.sessions[0]?.preview, "one updated");
});

test("catalog refresh preserves live Session status when metadata omits it", () => {
  const projectKey = "C:/one";
  const initial = createInitialState({
    projects: [{
      path: projectKey,
      projectKey,
      alias: "One",
      pinned: false,
      sessions: [
        { session_id: "running", preview: "running", runtime_status: "running" },
        { session_id: "waiting", preview: "waiting", runtime_status: "waiting" },
      ],
      catalogFresh: true,
    }],
  });
  const refreshed = reduceRendererState(initial, {
    type: "catalog_refreshed",
    projectKey,
    sessions: [
      { session_id: "running", preview: "running updated" },
      { session_id: "waiting", preview: "waiting updated" },
    ],
  });
  assert.equal(refreshed.projects[0]?.sessions[0]?.runtime_status, "running");
  assert.equal(refreshed.projects[0]?.sessions[1]?.runtime_status, "waiting");

  const terminal = reduceRendererState(refreshed, {
    type: "catalog_refreshed",
    projectKey,
    sessions: [
      { session_id: "running", preview: "done", runtime_status: "completed" },
      { session_id: "waiting", preview: "waiting updated" },
    ],
  });
  assert.equal(terminal.projects[0]?.sessions[0]?.runtime_status, "completed", "an explicit terminal status remains authoritative");
  assert.equal(terminal.projects[0]?.sessions[1]?.runtime_status, "waiting");
});

test("session mutation moves one catalog row to the target without changing its identity or history projection", () => {
  const initial = createInitialState({
    projects: [
      { path: "C:/source", projectKey: "C:/source", alias: "Source", pinned: false, sessions: [{ session_id: "move-me", title: "Keep title", preview: "Keep preview", transcript_entries: 7, pinned: true }], catalogFresh: true },
      { path: "C:/target", projectKey: "C:/target", alias: "Target", pinned: false, sessions: [{ session_id: "existing", preview: "Existing" }], catalogFresh: true },
    ],
    pinnedSessions: [{ projectKey: "C:/source", sessionId: "move-me" }],
  });
  const moved = applySessionMutation(initial, "C:/source", {
    session_id: "move-me",
    project_key: "C:/target",
    title: "Keep title",
    session: { session_id: "move-me", project_key: "C:/target", title: "Keep title" },
  });
  assert.deepEqual(moved.projects[0]?.sessions, []);
  assert.deepEqual(moved.projects[1]?.sessions.map((session) => session.session_id), ["existing", "move-me"]);
  assert.equal(moved.projects[1]?.sessions[1]?.title, "Keep title");
  assert.equal(moved.projects[1]?.sessions[1]?.preview, "Keep preview");
  assert.equal(moved.projects[1]?.sessions[1]?.transcript_entries, 7);
  assert.deepEqual(moved.pinnedSessions, [{ projectKey: "C:/target", sessionId: "move-me" }]);
});

test("T05 session presentation reasons preserve refresh/resume/rename order and only elevate new messages", () => {
  let state = createInitialState({
    projects: [{ path: "C:/one", projectKey: "C:/one", alias: "One", pinned: false, sessions: [{ session_id: "s1" }, { session_id: "s2" }], catalogFresh: true }],
    selectedProjectKey: "C:/one",
    selectedSessionId: "s1",
    timeline: [{ id: "assistant-1", kind: "assistant", text: "old", status: "completed" }],
  });
  state = reduceRendererState(state, { type: "catalog_refreshed", projectKey: "C:/one", sessions: [{ session_id: "s2" }, { session_id: "s3" }, { session_id: "s1" }] });
  assert.deepEqual(state.projects[0]?.sessions.map((session) => session.session_id), ["s1", "s2", "s3"]);
  state = reduceRendererState(state, { type: "catalog_refreshed", projectKey: "C:/one", sessions: [{ session_id: "s1" }, { session_id: "s2" }, { session_id: "s3" }], reason: "message", focusSessionId: "s2" });
  assert.deepEqual(state.projects[0]?.sessions.map((session) => session.session_id), ["s2", "s1", "s3"]);
  state = reduceRendererState(state, { type: "catalog_refreshed", projectKey: "C:/one", sessions: [{ session_id: "s2" }, { session_id: "s4" }, { session_id: "s1" }, { session_id: "s3" }], reason: "session_new", focusSessionId: "s4" });
  assert.deepEqual(state.projects[0]?.sessions.map((session) => session.session_id), ["s4", "s2", "s1", "s3"]);
  state = applySessionMutation(state, "C:/one", { session_id: "s1", project_key: "C:/two", session: { session_id: "s1", project_key: "C:/two" } });
  assert.equal(state.selectedSessionId, null, "moving the selected idle Session clears stale selection");
  assert.deepEqual(state.timeline, []);
});
