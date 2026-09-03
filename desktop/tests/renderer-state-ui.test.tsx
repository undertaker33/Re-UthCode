import { test } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createInitialState, reduceRendererState } from "../src/renderer/state";
import { applyProjectOpened } from "../src/renderer/state-session";
import { Composer } from "../src/renderer/Composer";

test("T06 unknown permission projection renders the Composer unavailable option", () => {
  let state = createInitialState({ permissionMode: "auto" });
  state = applyProjectOpened(state, { project: { path: "C:/one" }, sessions: [], run: { run_id: "run-one" } });
  state = reduceRendererState(state, { type: "session_new", sessionId: "session-one", run: { run_id: "run-two" } });
  assert.equal(state.permissionMode, "unknown");
  const markup = renderToStaticMarkup(<Composer state={state} onChange={() => undefined} onSubmit={() => undefined} onCommand={() => undefined} onPause={() => undefined} onCancel={() => undefined} />);
  assert.match(markup, /不可用|Unavailable/u);
});
