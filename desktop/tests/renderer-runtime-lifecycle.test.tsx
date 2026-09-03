import { test } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { JSDOM } from "jsdom";
import type { AgentEvent, DesktopApi, JsonObject } from "../src/desktop-api";
import { createInitialState } from "../src/renderer/state";
import { App } from "../src/renderer/App";
import { rebootstrapProject } from "../src/renderer/useRuntimeLifecycle";

async function withRendererDom<T>(callback: (dom: JSDOM, container: HTMLElement, root: Root) => Promise<T>): Promise<T> {
  const dom = new JSDOM("<!doctype html><html><body><button id=before>Before</button><div id=root></div><button id=after>After</button></body></html>", { url: "http://localhost/" });
  // React's input polyfill probes the legacy IE hook when focusing a
  // textarea in JSDOM. Keep the fixture focused on renderer behavior.
  if (!("attachEvent" in dom.window.HTMLElement.prototype)) {
    Object.defineProperty(dom.window.HTMLElement.prototype, "attachEvent", { configurable: true, value: () => undefined });
    Object.defineProperty(dom.window.HTMLElement.prototype, "detachEvent", { configurable: true, value: () => undefined });
  }
  const container = dom.window.document.getElementById("root");
  assert.ok(container);
  let root!: Root;
  const globalObject = globalThis as unknown as Record<string, unknown>;
  const bindings: Record<string, unknown> = {
    window: dom.window,
    document: dom.window.document,
    navigator: dom.window.navigator,
    Node: dom.window.Node,
    HTMLElement: dom.window.HTMLElement,
    HTMLButtonElement: dom.window.HTMLButtonElement,
    HTMLInputElement: dom.window.HTMLInputElement,
    Event: dom.window.Event,
    MouseEvent: dom.window.MouseEvent,
    KeyboardEvent: dom.window.KeyboardEvent,
    PointerEvent: dom.window.PointerEvent ?? dom.window.MouseEvent,
    getComputedStyle: dom.window.getComputedStyle,
    IS_REACT_ACT_ENVIRONMENT: true,
  };
  const previous = new Map<string, unknown>();
  for (const [key, value] of Object.entries(bindings)) {
    previous.set(key, globalObject[key]);
    Object.defineProperty(globalObject, key, { configurable: true, writable: true, value });
  }
  root = createRoot(container);
  try {
    return await callback(dom, container, root);
  } finally {
    act(() => { root.unmount(); });
    dom.window.close();
    for (const [key, value] of previous) {
      if (value === undefined) delete globalObject[key];
      else Object.defineProperty(globalObject, key, { configurable: true, writable: true, value });
    }
  }
}

test("T05 terminal convergence retries transient failures with backoff past one wait window", async () => {
  await withRendererDom(async (_dom, container, root) => {
    const responses = ["error", "active", "active", "active", "active", "idle"] as const;
    let statusCalls = 0;
    let eventListener: ((event: AgentEvent) => void) | null = null;
    const api: DesktopApi = {
      openProject: async () => null,
      openProjectInExplorer: async () => undefined,
      copyText: async () => undefined,
      closeShell: async () => undefined,
      requestRuntime: async (method) => {
        if (method !== "status.get") return {};
        const response = responses[statusCalls++] ?? "active";
        if (response === "error") throw new Error("transient status failure");
        return response === "idle"
          ? { active_turn: false, application: { context_status: { used_tokens: 12, budget_tokens: 100, available: true, measurement: "estimate", source: "application" } } }
          : { active_turn: true };
      },
      subscribeAgentEvents: (listener) => { eventListener = listener; return () => { eventListener = null; }; },
      readPreference: async () => undefined,
      writePreference: async () => undefined,
    };
    const state = createInitialState({ language: "en", composerText: "continue", activeTurn: true, turnStatus: "running", run: { run_id: "run-retry", turn_id: "turn-retry" } });
    act(() => { root.render(<App initialState={state} api={api} />); });
    const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0));
    await act(async () => { await tick(); await tick(); });
    act(() => { eventListener?.({ type: "turn_completed", run_id: "run-retry", turn_id: "turn-retry", final_text: "done" }); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 550)); });
    assert.equal(container.querySelector<HTMLTextAreaElement>(".composer textarea")?.disabled, true, "transient errors and active status keep the Composer locked beyond the old timeout window");
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 350)); });
    assert.equal(statusCalls, 6, "the same background poll survives five backoff intervals before the false authority");
    assert.equal(container.querySelector<HTMLTextAreaElement>(".composer textarea")?.disabled, false, "the recovered authoritative false status eventually releases the Composer");
  });
});

test("T05 terminal convergence is cancelled on unmount without a timer or stale status write", async () => {
  await withRendererDom(async (_dom, container, root) => {
    let statusCalls = 0;
    let eventListener: ((event: AgentEvent) => void) | null = null;
    const api: DesktopApi = {
      openProject: async () => null,
      openProjectInExplorer: async () => undefined,
      copyText: async () => undefined,
      closeShell: async () => undefined,
      requestRuntime: async () => { statusCalls += 1; return { active_turn: true }; },
      subscribeAgentEvents: (listener) => { eventListener = listener; return () => { eventListener = null; }; },
      readPreference: async () => undefined,
      writePreference: async () => undefined,
    };
    act(() => { root.render(<App initialState={createInitialState({ activeTurn: true, turnStatus: "running", run: { run_id: "run-unmount", turn_id: "turn-unmount" } })} api={api} />); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    act(() => { eventListener?.({ type: "turn_completed", run_id: "run-unmount", turn_id: "turn-unmount", final_text: "done" }); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    assert.equal(statusCalls, 1, "terminal convergence starts with one status request");
    act(() => { root.render(null); });
    await new Promise<void>((resolve) => setTimeout(resolve, 90));
    assert.equal(statusCalls, 1, "unmount aborts the pending backoff and prevents later status writes");
    assert.equal(container.textContent, "");
  });
});

test("T05 accepted flat Run boundaries own consecutive Turn polls and stale turn_started cannot replace them", async () => {
  await withRendererDom(async (dom, container, root) => {
    let statusCalls = 0;
    let turnStartCalls = 0;
    let eventListener: ((event: AgentEvent) => void) | null = null;
    const idle = { active_turn: false, application: { context_status: { used_tokens: 12, budget_tokens: 100, available: true, measurement: "estimate", source: "application" } } };
    const api: DesktopApi = {
      openProject: async () => null,
      openProjectInExplorer: async () => undefined,
      copyText: async () => undefined,
      closeShell: async () => undefined,
      requestRuntime: async (method) => {
        if (method === "turn.start") {
          turnStartCalls += 1;
          // Match the real Bridge: turn.start returns a flat Run DTO.  The
          // second accepted turn reuses the Run but has a new Turn identity.
          return turnStartCalls === 1
            ? { run_id: "run-new", turn_id: "turn-one", status: "running" }
            : { run_id: "run-new", turn_id: "turn-two", status: "running" };
        }
        if (method !== "status.get") return {};
        statusCalls += 1;
        return statusCalls % 2 === 1 ? { active_turn: true } : idle;
      },
      subscribeAgentEvents: (listener) => { eventListener = listener; return () => { eventListener = null; }; },
      readPreference: async () => undefined,
      writePreference: async () => undefined,
    };
    act(() => { root.render(<App initialState={createInitialState({ language: "en", composerText: "new prompt", activeTurn: false, run: { run_id: "run-old", turn_id: "turn-old" } })} api={api} />); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    const send = container.querySelector<HTMLButtonElement>(".composer-actions button:last-child");
    assert.ok(send);
    act(() => { send!.click(); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    assert.equal(turnStartCalls, 1);
    assert.equal(container.querySelector<HTMLElement>("#runtime-panel")?.textContent?.includes("run-new"), true, "the flat accepted Application Run becomes the current owner");
    assert.equal(container.querySelector<HTMLTextAreaElement>(".composer textarea")?.value, "", "accepted boundary clears the submitted composer draft");

    act(() => { eventListener?.({ type: "turn_started", run_id: "run-new", turn_id: "turn-one", message_id: "message-one", message: { role: "user", parts: [{ type: "text", text: "new prompt" }] } }); });
    assert.match(container.querySelector<HTMLElement>(".timeline")?.textContent ?? "", /new prompt/u, "accepted turn_started owns the first new user timeline entry");
    act(() => { eventListener?.({ type: "turn_completed", run_id: "run-new", turn_id: "turn-one", final_text: "first done" }); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    assert.equal(statusCalls, 1, "the first accepted Turn starts one authoritative poll");
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 70)); });
    assert.equal(statusCalls, 2, "the first Turn reaches authoritative idle");
    assert.equal(container.querySelector<HTMLTextAreaElement>(".composer textarea")?.disabled, false, "authoritative idle releases the Composer for the next Turn");

    const textarea = container.querySelector<HTMLTextAreaElement>(".composer textarea");
    assert.ok(textarea);
    const setter = Object.getOwnPropertyDescriptor(dom.window.HTMLTextAreaElement.prototype, "value")?.set;
    assert.ok(setter);
    act(() => {
      textarea!.focus();
      setter!.call(textarea, "second prompt");
      textarea!.dispatchEvent(new dom.window.InputEvent("input", { bubbles: true, inputType: "insertText", data: "second prompt" }));
      textarea!.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
      // React is imported before the JSDOM window in this suite, so its
      // legacy controlled-input fallback observes keyup for textareas.
      textarea!.dispatchEvent(new dom.window.KeyboardEvent("keyup", { bubbles: true, key: "Unidentified" }));
    });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    assert.equal(textarea?.value, "second prompt");
    act(() => { container.querySelector<HTMLButtonElement>(".composer-actions button:last-child")?.click(); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    assert.equal(turnStartCalls, 2, "the second same-Run Turn uses the flat turn.start contract");

    act(() => { eventListener?.({ type: "turn_started", run_id: "run-new", turn_id: "turn-two", message_id: "message-two", message: { role: "user", parts: [{ type: "text", text: "second prompt" }] } }); });
    assert.match(container.querySelector<HTMLElement>(".timeline")?.textContent ?? "", /new prompt[\s\S]*second prompt/u, "the same Run keeps both accepted Turn user entries");
    act(() => { eventListener?.({ type: "turn_completed", run_id: "run-new", turn_id: "turn-two", final_text: "second done" }); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    assert.equal(statusCalls, 3, "the second Turn owns a new terminal poll");

    // A stale start from the replaced Run is rejected before it can touch
    // either the reducer or the second Turn's poll ownership.
    act(() => { eventListener?.({ type: "turn_started", run_id: "run-old", turn_id: "turn-old", message_id: "message-old", message: { role: "user", parts: [{ type: "text", text: "stale old" }] } }); });
    assert.equal(container.querySelector<HTMLElement>("#runtime-panel")?.textContent?.includes("run-new"), true, "stale start does not replace the accepted Run");
    assert.doesNotMatch(container.querySelector<HTMLElement>(".timeline")?.textContent ?? "", /stale old/u, "stale start does not add a user timeline entry");
    assert.equal(statusCalls, 3, "stale start does not cancel or replace the second Turn poll");
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 70)); });
    assert.equal(statusCalls, 4, "the second Turn poll survives stale events and reaches authoritative idle");
    assert.equal(container.querySelector<HTMLTextAreaElement>(".composer textarea")?.disabled, false, "consecutive Turns do not leave the Composer locked");
  });
});

test("T05 steering keeps the Bridge nested Run DTO separate from flat turn.start", async () => {
  await withRendererDom(async (_dom, container, root) => {
    let eventListener: ((event: AgentEvent) => void) | null = null;
    const calls: string[] = [];
    const api: DesktopApi = {
      openProject: async () => null,
      openProjectInExplorer: async () => undefined,
      copyText: async () => undefined,
      closeShell: async () => undefined,
      requestRuntime: async (method) => {
        calls.push(method);
        if (method === "turn.steer") return { accepted: true, run: { run_id: "run-steer", turn_id: "turn-steer", status: "running" } };
        return {};
      },
      subscribeAgentEvents: (listener) => { eventListener = listener; return () => { eventListener = null; }; },
      readPreference: async () => undefined,
      writePreference: async () => undefined,
    };
    act(() => { root.render(<App initialState={createInitialState({ language: "en", composerText: "steer this", activeTurn: true, turnStatus: "running", run: { run_id: "run-steer", turn_id: "turn-before" } })} api={api} />); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    act(() => { container.querySelector<HTMLButtonElement>(".composer-actions button:last-child")?.click(); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    assert.equal(calls.includes("turn.start"), false, "an active Composer uses turn.steer");
    assert.equal(calls.filter((method) => method === "turn.steer").length, 1);
    act(() => { eventListener?.({ type: "turn_started", run_id: "run-steer", turn_id: "turn-steer", message_id: "steer-message", message: { role: "user", parts: [{ type: "text", text: "steering accepted" }] } }); });
    assert.match(container.querySelector<HTMLElement>(".timeline")?.textContent ?? "", /steer this[\s\S]*steering accepted/u, "the nested steering Run identity is accepted for its next event");
  });
});

test("T05 buffers synchronous turn.start stdout until the flat accepted identity and replays once", async () => {
  await withRendererDom(async (_dom, container, root) => {
    let statusCalls = 0;
    let allowIdle = false;
    let eventListener: ((event: AgentEvent) => void) | null = null;
    const api: DesktopApi = {
      openProject: async () => null,
      openProjectInExplorer: async () => undefined,
      copyText: async () => undefined,
      closeShell: async () => undefined,
      requestRuntime: (method) => {
        if (method === "turn.start") {
          // The Runtime resolves the response and emits the following stdout
          // events in one synchronous call stack, before App's await
          // continuation can record the accepted flat identity.
          return new Promise((resolve) => {
            resolve({ run_id: "run-sync", turn_id: "turn-sync", status: "running" });
            eventListener?.({ type: "turn_started", run_id: "run-sync", turn_id: "turn-sync", message_id: "message-sync", message: { role: "user", parts: [{ type: "text", text: "sync prompt" }] } });
            eventListener?.({ type: "assistant_message_delta", run_id: "run-sync", turn_id: "turn-sync", message_id: "assistant-sync", text: "partial" });
            eventListener?.({ type: "assistant_message_delta", run_id: "run-other", turn_id: "turn-other", message_id: "assistant-other", text: "other run" });
            eventListener?.({ type: "turn_completed", run_id: "run-sync", turn_id: "turn-sync", final_text: "sync final" });
          });
        }
        if (method !== "status.get") return Promise.resolve({});
        statusCalls += 1;
        return Promise.resolve(allowIdle
          ? { active_turn: false, application: { context_status: { used_tokens: 12, budget_tokens: 100, available: true, measurement: "estimate", source: "application" } } }
          : { active_turn: true });
      },
      subscribeAgentEvents: (listener) => { eventListener = listener; return () => { eventListener = null; }; },
      readPreference: async () => undefined,
      writePreference: async () => undefined,
    };
    act(() => { root.render(<App initialState={createInitialState({ language: "en", composerText: "sync prompt", activeTurn: false, run: { run_id: "run-old", turn_id: "turn-old" } })} api={api} />); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    act(() => { container.querySelector<HTMLButtonElement>(".composer-actions button:last-child")?.click(); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    assert.equal(container.querySelectorAll(".timeline-entry--user").length, 1, "buffered turn_started replays exactly one user row");
    assert.equal(container.querySelectorAll(".timeline-entry--assistant").length, 1, "buffered delta and terminal replay settle one assistant row");
    assert.match(container.querySelector<HTMLElement>(".timeline")?.textContent ?? "", /sync prompt[\s\S]*sync final/u);
    assert.doesNotMatch(container.querySelector<HTMLElement>(".timeline")?.textContent ?? "", /other run/u, "buffered events from another Run are discarded");
    // The renderer test file runs its independent DOM fixtures concurrently;
    // under a loaded scheduler the first 25ms backoff may elapse before these
    // two zero-delay flushes return.  The invariant is one initial request and
    // at most one follow-up for the active->idle response pair.
    assert.ok(statusCalls >= 1 && statusCalls <= 2, "buffered terminal starts one bounded poll after accepted identity");
    assert.equal(container.querySelector<HTMLTextAreaElement>(".composer textarea")?.disabled, true, "active authority keeps Composer locked before status idle");
    allowIdle = true;
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 70)); });
    // The convergence loop may have already issued its next bounded retry on
    // a loaded test scheduler.  The observable contract is authoritative idle
    // (and the resulting unlock), not an exact wall-clock request count.
    assert.ok(statusCalls >= 2, "the buffered terminal poll reaches authoritative false");
    assert.equal(container.querySelector<HTMLTextAreaElement>(".composer textarea")?.disabled, false, "buffered stdout does not lose terminal unlock");
  });
});

test("T05 pending turn.start ownership is single-flight and discarded on unmount", async () => {
  await withRendererDom(async (_dom, container, root) => {
    let turnStartCalls = 0;
    let statusCalls = 0;
    let resolveStart: ((result: JsonObject) => void) | null = null;
    let eventListener: ((event: AgentEvent) => void) | null = null;
    const api: DesktopApi = {
      openProject: async () => null,
      openProjectInExplorer: async () => undefined,
      copyText: async () => undefined,
      closeShell: async () => undefined,
      requestRuntime: (method) => {
        if (method === "turn.start") {
          turnStartCalls += 1;
          return new Promise<JsonObject>((resolve) => {
            resolveStart = resolve;
            eventListener?.({ type: "turn_started", run_id: "run-pending", turn_id: "turn-pending", message_id: "pending-message", message: { role: "user", parts: [{ type: "text", text: "pending" }] } });
          });
        }
        if (method === "status.get") {
          statusCalls += 1;
          return Promise.resolve({ active_turn: false });
        }
        return Promise.resolve({});
      },
      subscribeAgentEvents: (listener) => { eventListener = listener; return () => { eventListener = null; }; },
      readPreference: async () => undefined,
      writePreference: async () => undefined,
    };
    act(() => { root.render(<App initialState={createInitialState({ language: "en", composerText: "pending", activeTurn: false, run: { run_id: "run-old", turn_id: "turn-old" } })} api={api} />); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    const send = container.querySelector<HTMLButtonElement>(".composer-actions button:last-child");
    assert.ok(send);
    act(() => { send!.click(); send!.click(); });
    assert.equal(turnStartCalls, 1, "a pending turn.start request is single-flight");
    assert.doesNotMatch(container.querySelector<HTMLElement>(".timeline")?.textContent ?? "", /pending/u, "buffered events are not rendered before accepted identity");
    act(() => { root.render(null); });
    act(() => { resolveStart?.({ run_id: "run-pending", turn_id: "turn-pending", status: "running" }); });
    await new Promise<void>((resolve) => setTimeout(resolve, 50));
    assert.equal(statusCalls, 0, "unmount discards the pending event buffer before any terminal poll");
    assert.equal(container.textContent, "");
  });
});

test("T03 project removal publishes terminal idle before replacement navigation failure", async () => {
  await withRendererDom(async (_dom, container, root) => {
    let eventListener: ((event: AgentEvent) => void) | null = null;
    let statusCalls = 0;
    const calls: string[] = [];
    const api: DesktopApi = {
      openProject: async () => null,
      openProjectInExplorer: async () => undefined,
      copyText: async () => undefined,
      closeShell: async () => undefined,
      requestRuntime: async (method) => {
        calls.push(method);
        if (method === "turn.cancel") {
          // The terminal event arrives while the navigation operation owns the
          // lifecycle, so the normal event-side poll is intentionally blocked.
          eventListener?.({ type: "turn_cancelled", run_id: "run-remove", turn_id: "turn-remove", termination_reason: "user_cancelled" });
          return {};
        }
        if (method === "status.get") {
          statusCalls += 1;
          return { active_turn: false };
        }
        if (method === "project.open") throw new Error("replacement project failed");
        return {};
      },
      subscribeAgentEvents: (listener) => { eventListener = listener; return () => { eventListener = null; }; },
      // Stop preference bootstrap before it can create an unrelated owner;
      // this fixture supplies the selected projects as authoritative state.
      readPreference: async (key) => { if (key === "theme") throw new Error("synthetic preferences unavailable"); return undefined; },
      writePreference: async () => undefined,
    };
    const state = createInitialState({
      language: "en",
      runtimeState: "ready",
      composerText: "continue",
      projects: [
        { path: "C:/remove", projectKey: "C:/remove", alias: "Remove", pinned: false, sessions: [], catalogFresh: true },
        { path: "C:/keep", projectKey: "C:/keep", alias: "Keep", pinned: false, sessions: [], catalogFresh: true },
      ],
      selectedProjectKey: "C:/remove",
      activeTurn: true,
      turnStatus: "running",
      run: { run_id: "run-remove", turn_id: "turn-remove", status: "running" },
    });
    const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0));
    act(() => { root.render(<App initialState={state} api={api} />); });
    await act(async () => { await tick(); await tick(); });

    const menuTrigger = container.querySelector<HTMLButtonElement>('button.menu-trigger[aria-label="More actions Remove"]');
    assert.ok(menuTrigger);
    act(() => { menuTrigger!.click(); });
    await act(async () => { await tick(); });
    const removeMenuItem = Array.from(container.querySelectorAll<HTMLButtonElement>('button[role="menuitem"]')).find((button) => button.title === "Remove");
    assert.ok(removeMenuItem);
    act(() => { removeMenuItem!.click(); });
    await act(async () => { await tick(); });
    const confirmation = container.querySelector<HTMLElement>('[role="alertdialog"]');
    assert.ok(confirmation);
    const confirmRemove = confirmation.querySelector<HTMLButtonElement>('button[title="Remove"]');
    assert.ok(confirmRemove);
    act(() => { confirmRemove!.click(); });
    await act(async () => {
      await tick();
      await tick();
      await new Promise<void>((resolve) => setTimeout(resolve, 70));
    });

    assert.deepEqual(calls.filter((method) => method === "turn.cancel" || method === "status.get" || method === "project.open"), ["turn.cancel", "status.get", "project.open"]);
    assert.equal(statusCalls, 1, "the owner path performs one authoritative idle poll");
    assert.equal(container.querySelector<HTMLTextAreaElement>(".composer textarea")?.disabled, false, "a failed replacement navigation cannot strand the old Composer in terminal pending");
    assert.doesNotMatch(container.querySelector<HTMLElement>(".composer-state")?.textContent ?? "", /Waiting/u, "terminal idle is published through the reducer before navigation failure");
  });
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

test("T07 rebootstrap ownership stops stale lifecycle calls and callbacks", async () => {
  let owned = true;
  const calls: string[] = [];
  const opened: unknown[] = [];
  const resumed: unknown[] = [];
  await assert.rejects(rebootstrapProject(async (method) => {
    calls.push(method);
    if (method === "runtime.initialize") owned = false;
    return { project: { path: "C:/Projects/stale" }, sessions: [], run: null };
  }, "C:/Projects/stale", "session-stale", (result) => opened.push(result), (result) => resumed.push(result), () => owned), /no longer current/u);
  assert.deepEqual(calls, ["runtime.shutdown", "runtime.initialize"]);
  assert.deepEqual(opened, []);
  assert.deepEqual(resumed, []);
});
