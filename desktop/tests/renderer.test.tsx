import { test } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import {
  applyProjectOpened,
  applySessionResumed,
  createInitialState,
  replayToTimeline,
  reduceRendererState,
  sessionLabel,
  type RendererState,
} from "../src/renderer/state";
import { App, projectPinPlan, projectRemovalPlan, rebootstrapProject } from "../src/renderer/App";
import { ChatTimeline, renderMarkdown } from "../src/renderer/ChatTimeline";
import { Composer, applyCompletion } from "../src/renderer/Composer";
import { InteractionSurface, buildPermissionResponse, buildPlanResponse, buildResumeResponse, buildRetryResponse, buildUserInputResponse, interactionSurfaceKey } from "../src/renderer/InteractionSurface";
import { SettingsView, configurationRequest, parseOptionalPositiveInteger, renameModelRef, renameProviderId } from "../src/renderer/SettingsView";
import { RuntimePanel } from "../src/renderer/RuntimePanel";

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

function contrastRatio(foreground: string, background: string): number {
  const luminance = (hex: string) => {
    const channels = hex.slice(1).match(/.{2}/gu)?.map((value) => Number.parseInt(value, 16) / 255) ?? [];
    const linear = channels.map((value) => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
  };
  const a = luminance(foreground);
  const b = luminance(background);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

test("T04 replay is ordered and session labels use preview then short id", () => {
  const records = [
    replayRecord(5, "assistant", "answer"),
    replayRecord(1, "user", "prompt"),
    replayRecord(4, "tool", "Bash completed"),
    replayRecord(2, "steering", "continue"),
    replayRecord(3, "reasoning", "thinking"),
  ];
  const timeline = replayToTimeline(records);
  assert.deepEqual(timeline.map((entry) => entry.text), ["prompt", "continue", "thinking", "Bash completed", "answer"]);
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

test("semantic shell mounts without prototype state", () => {
  const state: RendererState = createInitialState();
  const markup = renderToStaticMarkup(<App initialState={state} api={undefined} />);
  assert.match(markup, /aria-label="UthCode conversation workspace"/);
  assert.match(markup, /New chat/);
  assert.match(markup, /Open project/);
  assert.match(markup, /Settings/);
  assert.match(markup, /Runtime/);
  assert.doesNotMatch(markup, /Log out|Usage|account|Hover preview|demo/u);
  assert.doesNotMatch(markup, /prompt\(|confirm\(/u);
});

test("project groups, session state, and Runtime projections remain connected", () => {
  const base = createInitialState({
    projects: [
      { path: "C:/one", projectKey: "C:/one", alias: "One", pinned: true, sessions: [{ session_id: "s1", preview: "first" }], catalogFresh: true },
      { path: "C:/two", projectKey: "C:/two", alias: "Two", pinned: false, sessions: [{ session_id: "s2", preview: "second", pinned: true }], catalogFresh: true },
    ],
    selectedProjectKey: "C:/one",
    pinnedSessions: [{ projectKey: "C:/two", sessionId: "s2" }],
  });
  const appMarkup = renderToStaticMarkup(<App initialState={base} api={undefined} />);
  assert.match(appMarkup, /aria-label="Project navigation"/);
  assert.match(appMarkup, /One/);
  assert.match(appMarkup, /Two/);
  assert.match(appMarkup, /first/);
  assert.match(appMarkup, />Pinned</);
  assert.match(appMarkup, />Projects</);
  assert.match(appMarkup, /aria-label="Remove One"/);
  assert.match(appMarkup, /Pinned sessions/);
  assert.match(appMarkup, /aria-label="Unpin session second"/);
  assert.equal((appMarkup.match(/>second</gu) ?? []).length, 1);
  assert.equal((appMarkup.match(/>first</gu) ?? []).length, 1);
  assert.doesNotMatch(appMarkup, /aria-label="Pin session first"/);
  for (const panelMode of ["docked", "floating", "hidden"] as const) {
    const panelMarkup = renderToStaticMarkup(<RuntimePanel state={createInitialState({ ...base, panelMode, currentModelRef: "provider/model", permissionMode: "auto", run: { run_id: "run-123456", behavior_mode: "plan", usage: { used_tokens: 1200, budget_tokens: 4000 } } })} onPanelModeChange={() => undefined} />);
    assert.match(panelMarkup, /aria-label="Runtime information"/);
    assert.match(panelMarkup, new RegExp(`runtime-panel--${panelMode}`));
    assert.match(panelMarkup, /1,200 \/ 4,000/);
    assert.match(panelMarkup, />plan</);
    assert.match(panelMarkup, />Run ID</);
    assert.match(panelMarkup, /provider\/model/);
    assert.match(panelMarkup, />auto</);
    if (panelMode === "hidden") assert.match(panelMarkup, /aria-hidden="true"/);
    else assert.doesNotMatch(panelMarkup, /aria-hidden="true"/);
  }
});

test("project pinning absorbs independent Session pins into the project tree", () => {
  const projects = [{ path: "C:/one", projectKey: "C:/one", alias: "One", pinned: false, sessions: [{ session_id: "s1", pinned: true }], catalogFresh: true }];
  const plan = projectPinPlan(projects, [{ projectKey: "C:/one", sessionId: "s1" }, { projectKey: "C:/two", sessionId: "s2" }], "C:/one");
  assert.equal(plan.projects[0].pinned, true);
  assert.deepEqual(plan.pinnedSessions, [{ projectKey: "C:/two", sessionId: "s2" }]);
  const normalized = reduceRendererState(createInitialState({ projects }), { type: "hydrate_preferences", preferences: { recentProjects: [{ path: "C:/one", pinned: true }], pinnedProjectKeys: ["C:/one"], pinnedSessions: [{ projectKey: "C:/one", sessionId: "s1" }] } });
  assert.deepEqual(normalized.pinnedSessions, []);
  assert.equal(normalized.projects[0].sessions[0].pinned, false);
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

test("T05 failed and cancelled turns discard incomplete assistant previews", () => {
  let state = createInitialState();
  state = reduceRendererState(state, { type: "agent_event", event: { type: "assistant_message_delta", run_id: "run-1", turn_id: "turn-1", message_id: "answer-1", iteration: 1, text: "unfinished" } });
  state = reduceRendererState(state, { type: "agent_event", event: { type: "turn_failed", run_id: "run-1", turn_id: "turn-1", termination_reason: "provider_error", failure_reason: "provider_request" } });
  assert.equal(state.timeline.some((entry) => entry.text === "unfinished"), false);
  assert.equal(state.timeline.some((entry) => entry.text.includes("provider_request")), true);
  assert.equal(state.activeTurn, false);
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

test("T05 markdown renderer covers common blocks without executing raw HTML", () => {
  const html = renderToStaticMarkup(<div>{renderMarkdown("# Heading\n\n- one\n- two\n\n> quote\n\n| A | B |\n| --- | --- |\n| x | y |\n\n[docs](https://example.com) `code`\n\n```python\nprint('<script>')\n```")}</div>);
  assert.match(html, /<h1>Heading<\/h1>/);
  assert.match(html, /<ul>/);
  assert.match(html, /<blockquote>/);
  assert.match(html, /<table>/);
  assert.match(html, /href="https:\/\/example\.com\/?"/);
  assert.match(html, /<code>code<\/code>/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;script&gt;/);
});

test("T05 tool timeline rows keep only the safe summary projection", () => {
  const markup = renderToStaticMarkup(<ChatTimeline entries={[{ id: "tool-1", kind: "tool", text: "Bash completed", command: "cat secret-result", toolName: "Bash", status: "completed", isError: false }]} todo={[]} />);
  assert.match(markup, /Bash completed/);
  assert.doesNotMatch(markup, /cat secret-result|ToolResult|secret-result/u);
});

test("T05 Composer exposes separate steering, pause, cancel, and Python-backed command completion paths", () => {
  const state = createInitialState({
    composerText: "/mo",
    activeTurn: true,
    turnStatus: "running",
    run: { run_id: "run", turn_id: "turn", behavior_mode: "default", usage: {} },
    commandCandidates: [{ value: "/model", display: "/model", description: "Select a model" }],
  });
  const markup = renderToStaticMarkup(<Composer state={state} onChange={() => undefined} onSubmit={() => undefined} onCommand={() => undefined} onPause={() => undefined} onCancel={() => undefined} />);
  assert.match(markup, /Steer/);
  assert.match(markup, /Pause/);
  assert.match(markup, /Cancel/);
  assert.match(markup, /Select a model/);
  assert.doesNotMatch(markup, /full command list|hard-coded/);
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

test("T06 pending interaction blocks Composer commands and keeps typed control identity", () => {
  const pending = createInitialState({ composerText: "/model", activeTurn: true, turnStatus: "paused", pendingInteraction: { kind: "user_requested", pauseId: "p", runId: "r", turnId: "t" }, commandCandidates: [{ value: "/model", description: "model" }] });
  const markup = renderToStaticMarkup(<Composer state={pending} onChange={() => undefined} onSubmit={() => undefined} onCommand={() => undefined} onPause={() => undefined} onCancel={() => undefined} />);
  assert.match(markup, /Waiting/);
  assert.doesNotMatch(markup, /role="listbox"/u);
  assert.doesNotMatch(markup, />Steer</u);
});

test("T06 typed interaction response builders preserve the same pause identity", () => {
  const interaction = { kind: "user_input_required", pauseId: "pause-1", runId: "run-1", turnId: "turn-1", toolCallId: "call-1" } as const;
  assert.deepEqual(buildUserInputResponse(interaction, { q1: ["answer"] }), { type: "user_input", pause_id: "pause-1", run_id: "run-1", turn_id: "turn-1", tool_call_id: "call-1", answers: { q1: ["answer"] } });
  assert.deepEqual(buildPermissionResponse({ ...interaction, kind: "permission_required" }, "perm-1", "once"), { type: "permission_approval", pause_id: "pause-1", run_id: "run-1", turn_id: "turn-1", permission_id: "perm-1", choice: "once" });
  assert.deepEqual(buildPlanResponse({ ...interaction, kind: "plan_review_required" }, 2, "revise", "change step"), { type: "plan_review", pause_id: "pause-1", run_id: "run-1", turn_id: "turn-1", revision: 2, choice: "revise", feedback: "change step" });
  assert.deepEqual(buildRetryResponse({ ...interaction, kind: "provider_unavailable" }), { type: "retry_provider", pause_id: "pause-1", run_id: "run-1", turn_id: "turn-1" });
  assert.deepEqual(buildResumeResponse(interaction), { type: "resume_turn", pause_id: "pause-1", run_id: "run-1", turn_id: "turn-1" });
});

test("T06 Interaction Surface uses dynamic Permission choices and never assumes session grant", () => {
  const interaction = { kind: "permission_required", pauseId: "pause-1", runId: "run-1", turnId: "turn-1", request: { permission_id: "perm-1", tool: "Bash", action: "execute", choices: ["once", "reject"] } } as const;
  const markup = renderToStaticMarkup(<InteractionSurface interaction={interaction} onSubmit={() => undefined} onCancel={() => undefined} />);
  assert.match(markup, /Allow once/);
  assert.match(markup, /Reject/);
  assert.doesNotMatch(markup, /Allow for session/);
  const sessionMarkup = renderToStaticMarkup(<InteractionSurface interaction={{ ...interaction, request: { ...interaction.request, choices: ["once", "session", "reject"] } }} onSubmit={() => undefined} onCancel={() => undefined} />);
  assert.match(sessionMarkup, /Allow for session/);
});

test("T06 Interaction Surface exposes AskUser review and Plan revision controls", () => {
  const inputInteraction = { kind: "user_input_required", pauseId: "pause-1", runId: "run-1", turnId: "turn-1", toolCallId: "call-1", request: { questions: [{ question_id: "q1", header: "Name", question: "Your name?", kind: "text" }, { question_id: "q2", header: "Color", question: "Pick", kind: "single_select", options: [{ label: "Red", description: "warm" }, { label: "Blue", description: "cool" }], allow_other: true }] } } as const;
  const inputMarkup = renderToStaticMarkup(<InteractionSurface interaction={inputInteraction} onSubmit={() => undefined} onCancel={() => undefined} />);
  assert.match(inputMarkup, /Your name\?/);
  assert.match(inputMarkup, /Next/);
  assert.match(inputMarkup, /Cancel turn/);
  const planInteraction = { kind: "plan_review_required", pauseId: "pause-2", runId: "run-1", turnId: "turn-1", request: { revision: 3, plan_text: "Step one\nStep two" } } as const;
  const planMarkup = renderToStaticMarkup(<InteractionSurface interaction={planInteraction} onSubmit={() => undefined} onCancel={() => undefined} />);
  assert.match(planMarkup, /Revision 3/);
  assert.match(planMarkup, /Approve and execute/);
  assert.match(planMarkup, /Revision feedback/);
  const multiMarkup = renderToStaticMarkup(<InteractionSurface interaction={{ ...inputInteraction, request: { questions: [{ question_id: "q1", header: "Tags", question: "Pick tags", kind: "multi_select", options: [{ label: "One", description: "first" }, { label: "Two", description: "second" }], allow_other: true }] } }} onSubmit={() => undefined} onCancel={() => undefined} />);
  assert.match(multiMarkup, /Pick tags/);
  assert.match(multiMarkup, /Other/);
});

test("T06 Provider Retry and user Pause render only typed continuation/cancel controls", () => {
  const retry = { kind: "provider_unavailable", pauseId: "pause-3", runId: "run-1", turnId: "turn-1", reason: "rate_limited" } as const;
  const retryMarkup = renderToStaticMarkup(<InteractionSurface interaction={retry} onSubmit={() => undefined} onCancel={() => undefined} />);
  assert.match(retryMarkup, /Retry/);
  assert.match(retryMarkup, /Cancel turn/);
  assert.doesNotMatch(retryMarkup, /backoff|reconnect|HTTP/u);
  const pause = { kind: "user_requested", pauseId: "pause-4", runId: "run-1", turnId: "turn-1", reason: "user_requested" } as const;
  const pauseMarkup = renderToStaticMarkup(<InteractionSurface interaction={pause} onSubmit={() => undefined} onCancel={() => undefined} />);
  assert.match(pauseMarkup, /Continue/);
  assert.match(pauseMarkup, /Cancel turn/);
});

test("T07 Settings uses the current configuration view and does not render secret values", () => {
  const state = createInitialState({ configuration: { default_model: "fake/model", default_permission_mode: "auto", providers: { fake: { provider_profile_id: "fake", kind: "fake", base_url: null, api_key_configured: false } }, models: { "fake/model": { model_ref: "fake/model", provider_profile_id: "fake", remote_id: "model", display_name: "Model", context_window: 128000, max_output_tokens: 4096, reasoning_effort: "none" } } }, settingsLoaded: true });
  const markup = renderToStaticMarkup(<SettingsView state={state} api={undefined} onBack={() => undefined} onSave={() => undefined} onThemeChange={() => undefined} />);
  assert.match(markup, /Models|Providers|Permissions|Interface|About/);
  assert.match(markup, /fake\/model/);
  assert.doesNotMatch(markup, /sk-live-secret|api_key=|secret value/u);
});

test("T07 configuration request keeps API key transient and maps current schema fields", () => {
  const request = configurationRequest({
    default_model: "fake/model",
    default_permission_mode: "default",
    providers: { fake: { kind: "fake", base_url: null, api_key: "sk-transient" } },
    models: { "fake/model": { provider_profile_id: "fake", remote_id: "model", display_name: "Model", context_window: 1000, max_output_tokens: 500, reasoning_effort: "none" } },
  });
  assert.equal(request.default_model, "fake/model");
  assert.equal((request.providers as Record<string, Record<string, unknown>>).fake.api_key, "sk-transient");
  assert.equal(JSON.stringify(request).includes("sk-transient"), true);
});

test("T07 theme classes expose system, dark, and light without changing content authority", () => {
  for (const theme of ["system", "dark", "light"] as const) {
    const state = createInitialState({ theme });
    const markup = renderToStaticMarkup(<App initialState={state} api={undefined} />);
    assert.match(markup, new RegExp(`theme-${theme}`));
  }
});

test("main workspace visual contract keeps 16px SVGs and readable theme tokens", async () => {
  const markup = renderToStaticMarkup(<App initialState={createInitialState({ theme: "dark", timeline: [{ id: "user-1", kind: "user", text: "hello" }] })} api={undefined} />);
  assert.match(markup, /class="ui-icon" viewBox="0 0 16 16"/);
  assert.match(markup, /class="timeline-entry timeline-entry--user"/);
  const css = await (await import("node:fs/promises")).readFile(new URL("../src/renderer/app.css", import.meta.url), "utf8");
  assert.match(css, /\.ui-icon\s*\{[^}]*width:\s*16px;[^}]*height:\s*16px;[^}]*stroke-width:\s*1\.35/s);
  assert.match(css, /\.timeline-entry--user \.timeline-content\s*\{[^}]*color:\s*#fff;[^}]*background:\s*#4a50b8/s);
  assert.match(css, /@media \(prefers-color-scheme: light\)[\s\S]*\.theme-system[\s\S]*--text:\s*#202027/s);
  assert.match(css, /\.theme-light\s*\{[^}]*--bg:\s*#f5f5f7;[^}]*--accent:\s*#565fd7/s);
  for (const background of ["#1d1d1f", "#18181a", "#242427", "#2b2b2f"]) assert.ok(contrastRatio("#9696a1", background) >= 4.5);
  for (const background of ["#f5f5f7", "#ececef", "#ffffff", "#e3e3e9"]) assert.ok(contrastRatio("#5b5c67", background) >= 4.5);
});

test("Runtime model uses only the Application status and model-selection projections", () => {
  let state = createInitialState();
  state = reduceRendererState(state, { type: "status_loaded", result: { application: { current_model: "provider/authoritative" } } });
  assert.equal(state.currentModelRef, "provider/authoritative");
  state = reduceRendererState(state, { type: "command_result", result: { ui_action: { type: "model_selected", model_ref: "provider/selected" }, output: "selected" } });
  assert.equal(state.currentModelRef, "provider/selected");
  state = reduceRendererState(state, { type: "status_loaded", result: { application: { current_model: "" }, raw_provider_payload: "secret" } });
  assert.equal(state.currentModelRef, "provider/selected");
});

test("T04 settings rebootstrap uses the real Runtime and project/session boundaries", async () => {
  const calls: Array<{ method: string; params: unknown }> = [];
  const opened: unknown[] = [];
  const resumed: unknown[] = [];
  const request = async (method: Parameters<NonNullable<Parameters<typeof rebootstrapProject>[0]>>[0], params: Record<string, unknown>) => {
    calls.push({ method, params });
    if (method === "project.open") return { project: { path: "C:/Projects/one" }, sessions: [], run: { run_id: "fresh-run" } } as const;
    if (method === "session.resume") return { session_id: "durable-session", replay: [], run: { run_id: "resumed-run" } } as const;
    return { state: "ready" } as const;
  };
  await rebootstrapProject(request, "C:/Projects/one", "durable-session", (result) => opened.push(result), (result) => resumed.push(result));
  assert.deepEqual(calls.map((call) => call.method), ["runtime.shutdown", "runtime.initialize", "project.open", "session.resume"]);
  assert.deepEqual(calls[1]?.params, { workdir: "C:/Projects/one" });
  assert.equal(opened.length, 1);
  assert.equal(resumed.length, 1);

  const failedCalls: string[] = [];
  await assert.rejects(rebootstrapProject(async (method) => {
    failedCalls.push(method);
    if (method === "runtime.initialize") throw new Error("initialize failed");
    return {};
  }, "C:/Projects/one", null, () => assert.fail("project.open must not run after initialize failure"), () => assert.fail("resume must not run after initialize failure")));
  assert.deepEqual(failedCalls, ["runtime.shutdown", "runtime.initialize"]);
});

test("T04 rebootstrap stops at every failed lifecycle boundary", async () => {
  const lifecycle: Array<"runtime.shutdown" | "runtime.initialize" | "project.open" | "session.resume"> = [
    "runtime.shutdown",
    "runtime.initialize",
    "project.open",
    "session.resume",
  ];
  for (const failedMethod of lifecycle) {
    const calls: string[] = [];
    await assert.rejects(rebootstrapProject(async (method) => {
      calls.push(method);
      if (method === failedMethod) throw new Error(`${failedMethod} failed`);
      if (method === "project.open") return { project: { path: "C:/Projects/one" }, sessions: [], run: { run_id: "fresh-run" } };
      if (method === "session.resume") return { session_id: "durable-session", replay: [], run: { run_id: "resumed-run" } };
      return { state: "ready" };
    }, "C:/Projects/one", "durable-session", () => undefined, () => undefined));
    assert.deepEqual(calls, lifecycle.slice(0, lifecycle.indexOf(failedMethod) + 1));
  }
});

test("T04 project removal distinguishes non-current retention from current switching/clearing", () => {
  const projects = [
    { path: "C:/one", projectKey: "C:/one", alias: "One", pinned: false, sessions: [], catalogFresh: true },
    { path: "C:/two", projectKey: "C:/two", alias: "Two", pinned: false, sessions: [], catalogFresh: true },
  ];
  const nonCurrent = projectRemovalPlan(projects, "C:/one", "C:/two");
  assert.equal(nonCurrent.current, false);
  assert.equal(nonCurrent.replacement?.projectKey, "C:/one");
  assert.deepEqual(nonCurrent.remaining.map((project) => project.projectKey), ["C:/one"]);
  const current = projectRemovalPlan(projects, "C:/one", "C:/one");
  assert.equal(current.current, true);
  assert.equal(current.replacement?.projectKey, "C:/two");
  assert.equal(projectRemovalPlan(projects.slice(0, 1), "C:/one", "C:/one").replacement, null);
});

test("T04 stale events from a replaced Run cannot write into the new timeline", () => {
  let state = applyProjectOpened(createInitialState(), { project: { path: "C:/one" }, sessions: [], run: { run_id: "run-one" } });
  state = reduceRendererState(state, { type: "agent_event", event: { type: "assistant_message_delta", run_id: "run-one", turn_id: "turn-one", message_id: "message-one", text: "old" } });
  state = applyProjectOpened(state, { project: { path: "C:/two" }, sessions: [], run: { run_id: "run-two" } });
  state = reduceRendererState(state, { type: "agent_event", event: { type: "assistant_message_delta", run_id: "run-one", turn_id: "turn-one", message_id: "message-one", text: "stale" } });
  assert.equal(state.selectedProjectKey, "C:/two");
  assert.deepEqual(state.timeline, []);
});

test("T04 clearing the last project keeps terminal Run events from repopulating the workspace", () => {
  let state = applyProjectOpened(createInitialState(), { project: { path: "C:/one" }, sessions: [], run: { run_id: "run-one" } });
  state = reduceRendererState(state, { type: "agent_event", event: { type: "assistant_message_delta", run_id: "run-one", turn_id: "turn-one", message_id: "message-one", text: "old" } });
  state = reduceRendererState(state, { type: "workspace_cleared" });
  state = reduceRendererState(state, { type: "agent_event", event: { type: "assistant_message_delta", run_id: "run-one", turn_id: "turn-one", message_id: "message-one", text: "stale" } });
  assert.equal(state.selectedProjectKey, null);
  assert.equal(state.run, null);
  assert.deepEqual(state.timeline, []);
});

test("T05 turn_completed settles reasoning while removing only the assistant preview", () => {
  let state = createInitialState();
  state = reduceRendererState(state, { type: "agent_event", event: { type: "reasoning_delta", run_id: "run-one", turn_id: "turn-one", message_id: "reason-one", text: "reasoning tail" } });
  state = reduceRendererState(state, { type: "agent_event", event: { type: "assistant_message_delta", run_id: "run-one", turn_id: "turn-one", message_id: "answer-one", text: "preview" } });
  state = reduceRendererState(state, { type: "agent_event", event: { type: "turn_completed", run_id: "run-one", turn_id: "turn-one", final_text: "authoritative" } });
  assert.deepEqual(state.timeline.filter((entry) => entry.kind === "reasoning").map((entry) => ({ text: entry.text, status: entry.status, streaming: entry.streaming })), [{ text: "reasoning tail", status: "completed", streaming: false }]);
  assert.deepEqual(state.timeline.filter((entry) => entry.kind === "assistant").map((entry) => entry.text), ["authoritative"]);
  assert.equal(state.timeline.some((entry) => entry.text === "preview"), false);
});

test("T05 failed turns settle reasoning tail while removing only assistant preview", () => {
  let state = createInitialState();
  state = reduceRendererState(state, { type: "agent_event", event: { type: "reasoning_delta", run_id: "run-one", turn_id: "turn-one", message_id: "reason-one", text: "failed reasoning tail" } });
  state = reduceRendererState(state, { type: "agent_event", event: { type: "assistant_message_delta", run_id: "run-one", turn_id: "turn-one", message_id: "answer-one", text: "failed preview" } });
  state = reduceRendererState(state, { type: "agent_event", event: { type: "turn_failed", run_id: "run-one", turn_id: "turn-one", termination_reason: "provider_error", failure_reason: "provider_request" } });
  assert.deepEqual(state.timeline.filter((entry) => entry.kind === "reasoning").map((entry) => ({ text: entry.text, status: entry.status, streaming: entry.streaming })), [{ text: "failed reasoning tail", status: "completed", streaming: false }]);
  assert.equal(state.timeline.some((entry) => entry.text === "failed preview"), false);
});

test("T05 cancelled turns settle reasoning tail while removing only assistant preview", () => {
  let state = createInitialState();
  state = reduceRendererState(state, { type: "agent_event", event: { type: "reasoning_delta", run_id: "run-one", turn_id: "turn-one", message_id: "reason-one", text: "cancelled reasoning tail" } });
  state = reduceRendererState(state, { type: "agent_event", event: { type: "assistant_message_delta", run_id: "run-one", turn_id: "turn-one", message_id: "answer-one", text: "cancelled preview" } });
  state = reduceRendererState(state, { type: "agent_event", event: { type: "turn_cancelled", run_id: "run-one", turn_id: "turn-one", termination_reason: "user_cancelled" } });
  assert.deepEqual(state.timeline.filter((entry) => entry.kind === "reasoning").map((entry) => ({ text: entry.text, status: entry.status, streaming: entry.streaming })), [{ text: "cancelled reasoning tail", status: "completed", streaming: false }]);
  assert.equal(state.timeline.some((entry) => entry.text === "cancelled preview"), false);
});

test("T06 same-turn AskUser and Plan pauses receive distinct remount keys", () => {
  let state = createInitialState({ activeTurn: true, turnStatus: "running" });
  state = reduceRendererState(state, { type: "agent_event", event: { type: "turn_paused", run_id: "run-one", turn_id: "turn-one", pause: { pause_id: "pause-user", run_id: "run-one", turn_id: "turn-one", kind: "user_input_required", user_input_request: { questions: [] } } } });
  const first = state.pendingInteraction;
  state = reduceRendererState(state, { type: "agent_event", event: { type: "turn_resumed", run_id: "run-one", turn_id: "turn-one", pause_id: "pause-user" } });
  state = reduceRendererState(state, { type: "agent_event", event: { type: "turn_paused", run_id: "run-one", turn_id: "turn-one", pause: { pause_id: "pause-plan", run_id: "run-one", turn_id: "turn-one", kind: "plan_review_required", plan_review_request: { revision: 2, plan_text: "next" } } } });
  const second = state.pendingInteraction;
  assert.equal(first?.kind, "user_input_required");
  assert.equal(second?.kind, "plan_review_required");
  assert.notEqual(interactionSurfaceKey(first!), interactionSurfaceKey(second!));
  assert.equal(interactionSurfaceKey(first!), "pause-user");
  assert.equal(interactionSurfaceKey(second!), "pause-plan");
});

test("T06 permission projection is cleared at fresh Run boundaries and only set by a command result", () => {
  let state = createInitialState({ permissionMode: "auto" });
  state = applyProjectOpened(state, { project: { path: "C:/one" }, sessions: [], run: { run_id: "run-one" } });
  assert.equal(state.permissionMode, "unknown");
  state = reduceRendererState(state, { type: "session_new", sessionId: "session-one", run: { run_id: "run-two" } });
  assert.equal(state.permissionMode, "unknown");
  const markup = renderToStaticMarkup(<Composer state={state} onChange={() => undefined} onSubmit={() => undefined} onCommand={() => undefined} onPause={() => undefined} onCancel={() => undefined} />);
  assert.match(markup, /Unavailable/);
  state = reduceRendererState(state, { type: "command_result", result: { ui_action: { type: "permission_mode_selected", mode: "auto" }, output: "Permission mode: auto" } });
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
  state = reduceRendererState(state, { type: "command_result", result: { ui_action: { type: "permission_mode_selected", mode: "default" }, run: { run_id: "run-session", permission_mode: "full_access" }, output: "Permission mode: default" } });
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

test("T07 Settings exposes editable schema IDs and model context/token limits", () => {
  const state = createInitialState({ configuration: { default_model: "fake/model", default_permission_mode: "default", providers: { fake: { kind: "fake", base_url: null, api_key_configured: false } }, models: { "fake/model": { provider_profile_id: "fake", remote_id: "model", display_name: "Model", context_window: 128000, max_output_tokens: 4096, reasoning_effort: "none" } } }, settingsLoaded: true });
  const markup = renderToStaticMarkup(<SettingsView state={state} api={undefined} onBack={() => undefined} onSave={() => undefined} onThemeChange={() => undefined} />);
  assert.match(markup, /aria-label="fake provider id"/);
  assert.match(markup, /aria-label="fake\/model model ref"/);
  assert.match(markup, /aria-label="fake\/model context window"/);
  assert.match(markup, /aria-label="fake\/model max output tokens"/);
  assert.match(markup, /value="128000"/);
  assert.match(markup, /value="4096"/);
  assert.equal(parseOptionalPositiveInteger("128000"), 128000);
  assert.equal(parseOptionalPositiveInteger(""), null);
  const renamedProvider = renameProviderId({ providers: { fake: { kind: "fake" } }, models: { "fake/model": { provider_profile_id: "fake" } }, providerOriginalIds: { fake: "fake" } }, "fake", "local");
  assert.equal(renamedProvider.models?.["fake/model"]?.provider_profile_id, "local");
  assert.deepEqual(renamedProvider.provider_renames, { fake: "local" });
  const renamedAgain = renameProviderId(renamedProvider, "local", "cloud");
  assert.deepEqual(renamedAgain.provider_renames, { fake: "cloud" });
  assert.deepEqual(configurationRequest(renamedProvider).provider_renames, { fake: "local" });
  assert.equal(configurationRequest(renamedProvider).providerOriginalIds, undefined);
  const returnedToOriginal = renameProviderId(renamedAgain, "cloud", "fake");
  assert.equal(returnedToOriginal.provider_renames, undefined);
  assert.deepEqual(returnedToOriginal.providerOriginalIds, { fake: "fake" });

  const draftProvider = renameProviderId({ providers: { provider: { kind: "fake" } } }, "provider", "local");
  assert.equal(draftProvider.provider_renames, undefined);

  const movedA = renameProviderId({
    providers: { A: { kind: "fake" }, B: { kind: "fake" } },
    models: { "a/model": { provider_profile_id: "A" }, "b/model": { provider_profile_id: "B" } },
    providerOriginalIds: { A: "A", B: "B" },
  }, "A", "X");
  const movedBatch = renameProviderId(movedA, "B", "A");
  assert.deepEqual(movedBatch.provider_renames, { A: "X", B: "A" });
  assert.deepEqual(Object.keys(movedBatch.providers ?? {}).sort(), ["A", "X"]);
  assert.equal(movedBatch.models?.["a/model"]?.provider_profile_id, "X");
  assert.equal(movedBatch.models?.["b/model"]?.provider_profile_id, "A");
  const renamedModel = renameModelRef({ default_model: "fake/model", models: { "fake/model": { provider_profile_id: "local" } } }, "fake/model", "local/model");
  assert.equal(renamedModel.default_model, "local/model");
  assert.ok(renamedModel.models?.["local/model"]);
});

test("T07 hidden Runtime Panel keeps restore controls in the shell", () => {
  const markup = renderToStaticMarkup(<App initialState={createInitialState({ panelMode: "hidden" })} api={undefined} />);
  assert.match(markup, /Show Runtime/);
  assert.match(markup, /Open Runtime/);
});

test("T07 Runtime switch and three layout modes remain operational", async () => {
  const dockedMarkup = renderToStaticMarkup(<App initialState={createInitialState({ panelMode: "docked" })} api={undefined} />);
  assert.match(dockedMarkup, /aria-label="Toggle Runtime panel"/);
  assert.match(dockedMarkup, /Open Runtime/);
  const floatingMarkup = renderToStaticMarkup(<App initialState={createInitialState({ panelMode: "floating" })} api={undefined} />);
  assert.match(floatingMarkup, /Hide Runtime/);
  assert.match(floatingMarkup, /runtime-panel--floating/);
  const css = await (await import("node:fs/promises")).readFile(new URL("../src/renderer/app.css", import.meta.url), "utf8");
  assert.match(css, /\.runtime-panel--docked\s*\{[^}]*position:\s*relative[^}]*width:/s);
  assert.match(css, /\.runtime-panel--floating\s*\{[^}]*position:\s*fixed[^}]*inset:[^}]*max-height:/s);
  assert.match(css, /\.runtime-panel--hidden\s*\{\s*display:\s*none;/s);
});

test("T07 completion preserves canonical slash prefixes and replaces only the current argument", () => {
  assert.equal(applyCompletion("/mo", "/model"), "/model ");
  assert.equal(applyCompletion("/model f", "fake/model"), "/model fake/model ");
  assert.equal(applyCompletion("/m f", "fake/model"), "/m fake/model ");
  assert.equal(applyCompletion("  /model old arg", "new"), "  /model old new ");
});
