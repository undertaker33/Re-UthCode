import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { App } from "../src/renderer/App";
import { createInitialState, reduceRendererState } from "../src/renderer/state";
import type { AgentEvent } from "../src/desktop-api";

async function main() {
const output = process.argv[2];
if (!output) throw new Error("output path is required");
let state = createInitialState({
  runtimeState: "ready",
  theme: "dark",
  panelMode: "docked",
  currentModelRef: "offline/model",
  permissionMode: "auto",
  run: {
    run_id: "run-visual-authority",
    turn_id: "turn-active",
    permission_mode: "auto",
    behavior_mode: "plan",
    usage: { used_tokens: 1840, budget_tokens: 4096 },
  },
});
state = reduceRendererState(state, {
  type: "hydrate_preferences",
  preferences: {
    recentProjects: [{ path: "C:/acceptance", alias: "Acceptance project", pinned: true }],
    projectAliases: { "C:/acceptance": "Acceptance project" },
    pinnedProjectKeys: ["C:/acceptance"],
    pinnedSessions: [],
    selectedProjectKey: "C:/acceptance",
    selectedSessionId: "session-visual",
  },
});
state = reduceRendererState(state, {
  type: "catalog_refreshed",
  projectKey: "C:/acceptance",
  sessions: [{ session_id: "session-visual", preview: "Real session projection" }],
});
const events = [
  { type: "turn_started", run_id: "run-visual-authority", turn_id: "turn-complete", message_id: "user-1", message: { role: "user", parts: [{ type: "text", text: "Review the implementation and run the checks." }] } },
  { type: "reasoning_delta", run_id: "run-visual-authority", turn_id: "turn-complete", message_id: "reason-1", text: "Inspecting the authoritative project state and verification results." },
  { type: "tool_started", run_id: "run-visual-authority", turn_id: "turn-complete", batch_id: "batch-1", tool_call_id: "tool-1", tool_name: "Bash", command: "npm test" },
  { type: "tool_finished", run_id: "run-visual-authority", turn_id: "turn-complete", batch_id: "batch-1", tool_call_id: "tool-1", tool_name: "Bash", command: "npm test", status: "succeeded", is_error: false },
  { type: "plan_proposed", run_id: "run-visual-authority", turn_id: "turn-complete", revision: 1, plan_text: "1. Inspect\n2. Verify\n3. Report" },
  { type: "task_state_changed", run_id: "run-visual-authority", turn_id: "turn-complete", task_state: { items: [{ content: "Inspect UI contracts", status: "completed" }, { content: "Run visual verification", status: "in_progress" }] } },
  { type: "assistant_message_completed", run_id: "run-visual-authority", turn_id: "turn-complete", message_id: "assistant-1", kind: "final", message: { role: "assistant", parts: [{ type: "text", text: "The main workspace contracts are connected and the verification is running." }] } },
  { type: "completion_blocked", run_id: "run-visual-authority", turn_id: "turn-complete", unfinished_count: 1 },
] satisfies AgentEvent[];
for (const event of events) state = reduceRendererState(state, { type: "agent_event", event });
state = reduceRendererState(state, { type: "turn_accepted", run: { ...state.run, turn_id: "turn-active", status: "running" }, steering: false });
const css = await readFile(new URL("../src/renderer/app.css", import.meta.url), "utf8");
await mkdir(dirname(output), { recursive: true });
if (state.pinnedSessions.length !== 0 || state.projects[0]?.sessions[0]?.pinned === true) throw new Error("fixture pin projection is not normalized");
const markup = renderToStaticMarkup(<App initialState={state} api={undefined} />);
if ((markup.match(/Real session projection/gu) ?? []).length !== 1) throw new Error("fixture session must render exactly once");
await writeFile(output, `<!doctype html><html><head><meta charset="UTF-8"><style>${css}</style></head><body><div id="root">${markup}</div></body></html>`, "utf8");
}
void main();
