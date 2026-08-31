import { test } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { JSDOM } from "jsdom";

import {
  applyProjectOpened,
  applySessionMutation,
  applySessionResumed,
  createInitialState,
  replayToTimeline,
  reduceRendererState,
  sessionLabel,
  type ProjectState,
  type SessionSummary,
  type RendererState,
} from "../src/renderer/state";
import { App, projectNavigationPreferences, projectPinPlan, projectRemovalPlan, rebootstrapProject } from "../src/renderer/App";
import { MAX_VISIBLE_SESSIONS, Sidebar, sessionGroups } from "../src/renderer/Sidebar";
import { ChatTimeline, renderMarkdown } from "../src/renderer/ChatTimeline";
import { Composer, applyCompletion } from "../src/renderer/Composer";
import { InteractionSurface, buildPermissionResponse, buildPlanResponse, buildResumeResponse, buildRetryResponse, buildUserInputResponse, interactionSurfaceKey } from "../src/renderer/InteractionSurface";
import { SettingsView, configurationRequest, modelFieldId, parseOptionalPositiveInteger, providerModels, reasoningEffortOptions, renameModelRef, renameProviderId, settingsSaveRequest, withoutRecordKey } from "../src/renderer/SettingsView";
import { RuntimeLayoutSelect, RuntimePanel, stateLabel } from "../src/renderer/RuntimePanel";
import { CustomSelect, customSelectConsumesEscape, initialEnabledOption, nextEnabledOption } from "../src/renderer/CustomSelect";
import { LanguageProvider, resources, translate } from "../src/renderer/i18n";

async function withRendererDom<T>(callback: (dom: JSDOM, container: HTMLElement, root: Root) => Promise<T>): Promise<T> {
  const dom = new JSDOM("<!doctype html><html><body><button id=before>Before</button><div id=root></div><button id=after>After</button></body></html>", { url: "http://localhost/" });
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
function renderLanguage(language: "zh-CN" | "en", element: React.ReactNode): string {
  return renderToStaticMarkup(<LanguageProvider value={language}>{element}</LanguageProvider>);
}

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
  assert.match(markup, /aria-label="UthCode 对话工作区"/);
  assert.match(markup, /新聊天/);
  assert.match(markup, /打开项目/);
  assert.match(markup, /设置/);
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
  assert.match(appMarkup, /aria-label="项目"/);
  assert.match(appMarkup, /One/);
  assert.match(appMarkup, /Two/);
  assert.match(appMarkup, /first/);
  assert.match(appMarkup, />已置顶</);
  assert.match(appMarkup, />项目</);
  assert.match(appMarkup, /aria-label="更多操作 One"/);
  assert.doesNotMatch(appMarkup, /已置顶会话/);
  assert.doesNotMatch(appMarkup, /aria-label="移除 One"/);
  assert.equal((appMarkup.match(/>second</gu) ?? []).length, 0);
  assert.equal((appMarkup.match(/>first</gu) ?? []).length, 1);
  assert.doesNotMatch(appMarkup, /aria-label="置顶 first"/);
  for (const panelMode of ["docked", "floating", "hidden"] as const) {
    const panelMarkup = renderLanguage("en", <RuntimePanel state={createInitialState({ ...base, panelMode, currentModelRef: "provider/model", permissionMode: "auto", run: { run_id: "run-123456", behavior_mode: "plan", usage: { used_tokens: 1200, budget_tokens: 4000 } } })} onPanelModeChange={() => undefined} />);
    assert.match(panelMarkup, /aria-label="Runtime information"/);
    assert.match(panelMarkup, new RegExp(`runtime-panel--${panelMode}`));
    assert.match(panelMarkup, /1,200 \/ 4,000/);
    assert.match(panelMarkup, />PLAN</);
    assert.match(panelMarkup, />Run ID</);
    assert.match(panelMarkup, /provider\/model/);
    assert.match(panelMarkup, />Auto</);
    if (panelMode === "hidden") assert.match(panelMarkup, /<aside[^>]*aria-hidden="true"/);
    else assert.doesNotMatch(panelMarkup, /<aside[^>]*aria-hidden="true"/);
  }
});

test("sidebar session grouping keeps catalog order, pins above five ordinary rows, and expands explicitly", () => {
  const sessions = [
    { session_id: "s1", preview: "one" },
    { session_id: "s2", preview: "two" },
    { session_id: "s3", preview: "three" },
    { session_id: "s4", preview: "four" },
    { session_id: "s5", preview: "five" },
    { session_id: "s6", preview: "six" },
    { session_id: "pinned", preview: "pinned", pinned: true },
  ];
  const collapsed = sessionGroups(sessions, false);
  assert.deepEqual(collapsed.pinned.map((session) => session.session_id), ["pinned"]);
  assert.deepEqual(collapsed.visibleOrdinary.map((session) => session.session_id), sessions.slice(0, MAX_VISIBLE_SESSIONS).map((session) => session.session_id));
  assert.equal(collapsed.hiddenCount, 1);
  const expanded = sessionGroups(sessions, true);
  assert.deepEqual(expanded.visibleOrdinary.map((session) => session.session_id), ["s1", "s2", "s3", "s4", "s5", "s6"]);

  const state = createInitialState({
    projects: [{ path: "C:/one", projectKey: "C:/one", alias: "One", pinned: false, sessions, catalogFresh: true }],
    selectedProjectKey: "C:/one",
    selectedSessionId: "s6",
  });
  const renamed = applySessionMutation(state, "C:/one", { session_id: "s6", title: "renamed", session: { session_id: "s6", title: "renamed" } });
  assert.deepEqual(renamed.projects[0]?.sessions.map((session) => session.session_id), sessions.map((session) => session.session_id));
  assert.equal(renamed.projects[0]?.sessions[5]?.preview, "six");
});

test("production Sidebar keeps selected rows visible, restores expansion, and exposes non-modal menus", async () => {
  await withRendererDom(async (dom, container, root) => {
    const expansionWrites: Array<{ projectKey: string; expanded: boolean }> = [];
    const pinWrites: string[] = [];
    const sessionPinWrites: string[] = [];
    const copiedIds: string[] = [];
    const sessions: SessionSummary[] = Array.from({ length: 6 }, (_, index) => ({ session_id: `s${index + 1}`, preview: `session-${index + 1}` }));
    const project = (items: SessionSummary[] = sessions): ProjectState => ({ path: "C:/source", projectKey: "C:/source", alias: "Source", pinned: false, sessions: items, catalogFresh: true });
    const renderSidebar = async (items: ProjectState[], selectedSessionId: string | null = null, expandedProjects: Record<string, boolean> = {}, key = "sidebar") => {
      act(() => {
        root.render(<LanguageProvider value="en"><Sidebar
          key={key}
          projects={items}
          selectedProjectKey={items[0]?.projectKey ?? null}
          selectedSessionId={selectedSessionId}
          activeTurn={false}
          expandedProjects={expandedProjects}
          onProjectExpandedChange={(projectKey, expanded) => expansionWrites.push({ projectKey, expanded })}
          onNewSession={() => undefined}
          onOpenProject={() => undefined}
          onOpenProjectSession={() => undefined}
          onResumeSession={() => undefined}
          onAliasChange={() => undefined}
          onTogglePin={(item) => pinWrites.push(item.projectKey)}
          onOpenExplorer={() => undefined}
          onRemoveProject={() => undefined}
          onToggleSessionPin={(item, session) => sessionPinWrites.push(`${item.projectKey}:${session.session_id}`)}
          onRenameSession={() => undefined}
          onMoveSession={() => undefined}
          onCopySessionId={(session) => copiedIds.push(session.session_id)}
          onOpenSettings={() => undefined}
        /></LanguageProvider>);
      });
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
    };
    const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0));
    const visibleSessionIds = (scope: ParentNode = container) => Array.from(scope.querySelectorAll<HTMLButtonElement>(".session-line:not(.new-session-line)"), (button) => button.textContent?.trim() ?? "");
    const mockRect = (element: HTMLElement, rect: { left: number; right: number; top: number; bottom: number }) => {
      element.getBoundingClientRect = () => ({ ...rect, width: rect.right - rect.left, height: rect.bottom - rect.top, x: rect.left, y: rect.top, toJSON: () => ({}) }) as DOMRect;
    };
    const openMenu = async (trigger: HTMLButtonElement) => {
      act(() => { trigger.click(); });
      await tick();
      await tick();
      return container.querySelector<HTMLElement>(".sidebar-menu");
    };
    const keydown = async (element: HTMLElement, key: string, shiftKey = false) => {
      let event!: KeyboardEvent;
      act(() => {
        event = new dom.window.KeyboardEvent("keydown", { key, shiftKey, bubbles: true, cancelable: true });
        element.dispatchEvent(event);
      });
      await tick();
      return event;
    };
    const keyboardActivate = async (element: HTMLButtonElement, key: string) => {
      element.focus();
      let event!: KeyboardEvent;
      act(() => {
        event = new dom.window.KeyboardEvent("keydown", { key, bubbles: true, cancelable: true });
        element.dispatchEvent(event);
        // JSDOM dispatches keydown but does not synthesize the native button
        // click that Enter/Space produce in a browser, so mirror that UA step.
        if (!event.defaultPrevented) element.click();
      });
      await tick();
      await tick();
      return event;
    };
    const focusablesOutsideMenu = () => Array.from(container.ownerDocument.querySelectorAll<HTMLElement>("button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), a[href], [tabindex]:not([tabindex='-1'])"))
      .filter((element) => !element.closest(".sidebar-menu"));

    // Explicit "show more" survives a component rebuild through the typed
    // preference projection, while a selected sixth row is derived visible
    // without changing the source array order.
    await renderSidebar([project()], null, {});
    const more = container.querySelector<HTMLButtonElement>(".session-more");
    assert.ok(more);
    act(() => { more.click(); });
    await tick();
    assert.deepEqual(expansionWrites.at(-1), { projectKey: "C:/source", expanded: true });
    await renderSidebar([project()], null, { "C:/source": true }, "reloaded-sidebar");
    assert.deepEqual(visibleSessionIds(), sessions.map((session) => session.preview));
    await renderSidebar([project()], "s6", {}, "selected-sixth");
    assert.deepEqual(visibleSessionIds(), sessions.map((session) => session.preview));
    const selectedRow = Array.from(container.querySelectorAll<HTMLButtonElement>(".session-line")).find((button) => button.textContent?.includes("session-6"));
    assert.ok(selectedRow, "selected sixth session must be present in the DOM");
    assert.equal(selectedRow?.classList.contains("is-selected"), true);
    const recentRows = Array.from(container.querySelectorAll<HTMLButtonElement>(".recent .recent-line"), (button) => button.querySelectorAll("span")[1]?.textContent ?? "");
    assert.deepEqual(recentRows, sessions.map((session) => session.preview));

    // Project click and Session right-click share one anchored menu instance.
    const projectTrigger = container.querySelector<HTMLButtonElement>(".project-menu-anchor .menu-trigger");
    const sessionTrigger = container.querySelector<HTMLButtonElement>(".session-menu-trigger");
    assert.ok(projectTrigger);
    assert.ok(sessionTrigger);
    const projectAnchor = projectTrigger?.closest<HTMLElement>(".project-menu-anchor");
    const sessionAnchor = sessionTrigger?.closest<HTMLElement>(".session-menu-anchor");
    assert.ok(projectAnchor);
    assert.ok(sessionAnchor);
    mockRect(projectAnchor, { left: 900, right: 980, top: 700, bottom: 720 });
    mockRect(sessionAnchor, { left: 900, right: 980, top: 700, bottom: 720 });
    const projectMenu = await openMenu(projectTrigger);
    assert.ok(projectMenu);
    assert.equal(container.querySelectorAll(".sidebar-menu").length, 1);
    const projectItems = () => Array.from(container.querySelectorAll<HTMLButtonElement>(".sidebar-menu__item"));
    assert.equal(document.activeElement, projectItems()[0]);
    await keydown(projectItems()[0]!, "ArrowDown");
    assert.equal(document.activeElement, projectItems()[1]);
    await keydown(projectItems()[1]!, "ArrowUp");
    assert.equal(document.activeElement, projectItems()[0]);
    await keydown(projectItems()[0]!, "End");
    assert.equal(document.activeElement, projectItems().at(-1));
    await keydown(projectItems().at(-1)!, "Home");
    assert.equal(document.activeElement, projectItems()[0]);
    act(() => { projectItems()[0]?.click(); });
    await tick();
    assert.deepEqual(pinWrites, ["C:/source"]);
    assert.equal(container.querySelector(".sidebar-menu"), null);
    assert.equal(document.activeElement, projectTrigger);

    // Real keyboard activation uses both browser button keys: Enter opens a
    // Project menu and Space activates its focused item; Space opens a Session
    // menu and Enter activates its focused item. Both actions close and
    // return focus to their originating trigger.
    await keyboardActivate(projectTrigger, "Enter");
    assert.equal(container.querySelectorAll(".sidebar-menu").length, 1);
    const keyboardProjectItems = Array.from(container.querySelectorAll<HTMLButtonElement>(".sidebar-menu__item"));
    assert.equal(document.activeElement, keyboardProjectItems[0]);
    await keyboardActivate(keyboardProjectItems[0]!, " ");
    assert.deepEqual(pinWrites, ["C:/source", "C:/source"]);
    assert.equal(container.querySelector(".sidebar-menu"), null);
    assert.equal(document.activeElement, projectTrigger);

    await keyboardActivate(sessionTrigger, " ");
    assert.equal(container.querySelectorAll(".sidebar-menu").length, 1);
    const keyboardSessionItems = Array.from(container.querySelectorAll<HTMLButtonElement>(".sidebar-menu__item"));
    assert.equal(document.activeElement, keyboardSessionItems[0]);
    await keyboardActivate(keyboardSessionItems[0]!, "Enter");
    assert.deepEqual(sessionPinWrites, ["C:/source:s1"]);
    assert.equal(container.querySelector(".sidebar-menu"), null);
    assert.equal(document.activeElement, sessionTrigger);

    act(() => {
      sessionAnchor?.dispatchEvent(new dom.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true, button: 2 }));
    });
    await tick();
    await tick();
    assert.equal(container.querySelectorAll(".sidebar-menu").length, 1);
    assert.match(container.querySelector<HTMLElement>(".sidebar-menu")?.getAttribute("aria-label") ?? "", /session-1/u);
    const sessionItems = () => Array.from(container.querySelectorAll<HTMLButtonElement>(".sidebar-menu__item"));
    act(() => { document.body.dispatchEvent(new dom.window.Event("pointerdown", { bubbles: true })); });
    await tick();
    assert.equal(container.querySelector(".sidebar-menu"), null);
    assert.equal(document.activeElement, sessionTrigger);

    await openMenu(sessionTrigger);
    act(() => { document.dispatchEvent(new dom.window.KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true })); });
    await tick();
    assert.equal(container.querySelector(".sidebar-menu"), null);
    assert.equal(document.activeElement, sessionTrigger);

    await openMenu(sessionTrigger);
    const tabMenuItems = sessionItems();
    const nextFocusable = focusablesOutsideMenu();
    const triggerIndex = nextFocusable.indexOf(sessionTrigger);
    const expectedAfter = nextFocusable[triggerIndex + 1];
    tabMenuItems[0]?.focus();
    const tabEvent = await keydown(tabMenuItems[0]!, "Tab");
    assert.equal(tabEvent.defaultPrevented, true);
    assert.equal(container.querySelector(".sidebar-menu"), null);
    assert.equal(document.activeElement, expectedAfter);

    await openMenu(sessionTrigger);
    const shiftTabMenuItems = sessionItems();
    const previousFocusable = focusablesOutsideMenu();
    const previousTriggerIndex = previousFocusable.indexOf(sessionTrigger);
    const expectedBefore = previousFocusable[previousTriggerIndex - 1];
    shiftTabMenuItems[0]?.focus();
    const shiftTabEvent = await keydown(shiftTabMenuItems[0]!, "Tab", true);
    assert.equal(shiftTabEvent.defaultPrevented, true);
    assert.equal(container.querySelector(".sidebar-menu"), null);
    assert.equal(document.activeElement, expectedBefore);

    const lowMenu = await openMenu(sessionTrigger);
    assert.ok(lowMenu);
    assert.ok(Number.parseFloat(lowMenu?.style.left ?? "0") >= 8);
    assert.ok(Number.parseFloat(lowMenu?.style.top ?? "9999") < 700, "menu should flip above a low viewport anchor");
    const copy = sessionItems().find((button) => button.textContent?.includes("Copy session ID"));
    assert.ok(copy);
    act(() => { copy?.click(); });
    await tick();
    assert.deepEqual(copiedIds, ["s1"]);
    assert.equal(container.querySelector(".sidebar-menu"), null);
    assert.equal(document.activeElement, sessionTrigger);
  });
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

test("project pinning absorbs independent Session pins into the project tree", () => {
  const projects = [{ path: "C:/one", projectKey: "C:/one", alias: "One", pinned: false, sessions: [{ session_id: "s1", pinned: true }], catalogFresh: true }];
  const plan = projectPinPlan(projects, [{ projectKey: "C:/one", sessionId: "s1" }, { projectKey: "C:/two", sessionId: "s2" }], "C:/one");
  assert.equal(plan.projects[0].pinned, true);
  assert.deepEqual(plan.pinnedSessions, [{ projectKey: "C:/two", sessionId: "s2" }]);
  const normalized = reduceRendererState(createInitialState({ projects }), { type: "hydrate_preferences", preferences: { recentProjects: [{ path: "C:/one", pinned: true }], pinnedProjectKeys: ["C:/one"], pinnedSessions: [{ projectKey: "C:/one", sessionId: "s1" }] } });
  assert.deepEqual(normalized.pinnedSessions, []);
  assert.equal(normalized.projects[0].sessions[0].pinned, false);
});

test("project removal prunes only Desktop navigation preferences and never implies disk deletion", () => {
  const projects = [
    { path: "C:/keep", projectKey: "C:/keep", alias: "Keep", pinned: true, sessions: [], catalogFresh: true },
    { path: "C:/remove", projectKey: "C:/remove", alias: "Remove", pinned: false, sessions: [], catalogFresh: true },
  ];
  const navigation = projectNavigationPreferences([projects[0]], [
    { projectKey: "C:/keep", sessionId: "keep-session" },
    { projectKey: "C:/remove", sessionId: "remove-session" },
  ], { "C:/keep": true, "C:/remove": false });
  assert.deepEqual(navigation.recentProjects, [{ path: "C:/keep", alias: "Keep", pinned: true }]);
  assert.deepEqual(navigation.projectAliases, { "C:/keep": "Keep" });
  assert.deepEqual(navigation.pinnedProjectKeys, ["C:/keep"]);
  assert.deepEqual(navigation.pinnedSessions, [{ projectKey: "C:/keep", sessionId: "keep-session" }]);
  assert.deepEqual(navigation.expandedProjects, { "C:/keep": true });
  // The helper only returns preference projections; it has no filesystem
  // operation or project-directory mutation side effect.
  assert.equal(projects[1].path, "C:/remove");
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
  assert.match(markup, /引导/);
  assert.match(markup, /暂停/);
  assert.match(markup, /取消/);
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
  assert.match(markup, /等待中/);
  assert.doesNotMatch(markup, /role="listbox"/u);
  assert.doesNotMatch(markup, />引导</u);
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
  const markup = renderLanguage("en", <InteractionSurface interaction={interaction} onSubmit={() => undefined} onCancel={() => undefined} />);
  assert.match(markup, /Allow once/);
  assert.match(markup, /Reject/);
  assert.doesNotMatch(markup, /Allow for session/);
  const sessionMarkup = renderLanguage("en", <InteractionSurface interaction={{ ...interaction, request: { ...interaction.request, choices: ["once", "session", "reject"] } }} onSubmit={() => undefined} onCancel={() => undefined} />);
  assert.match(sessionMarkup, /Allow for session/);
});

test("T06 Interaction Surface exposes AskUser review and Plan revision controls", () => {
  const inputInteraction = { kind: "user_input_required", pauseId: "pause-1", runId: "run-1", turnId: "turn-1", toolCallId: "call-1", request: { questions: [{ question_id: "q1", header: "Name", question: "Your name?", kind: "text" }, { question_id: "q2", header: "Color", question: "Pick", kind: "single_select", options: [{ label: "Red", description: "warm" }, { label: "Blue", description: "cool" }], allow_other: true }] } } as const;
  const inputMarkup = renderToStaticMarkup(<InteractionSurface interaction={inputInteraction} onSubmit={() => undefined} onCancel={() => undefined} />);
  assert.match(inputMarkup, /Your name\?/);
  assert.match(inputMarkup, /下一步/);
  assert.match(inputMarkup, /取消轮次/);
  const planInteraction = { kind: "plan_review_required", pauseId: "pause-2", runId: "run-1", turnId: "turn-1", request: { revision: 3, plan_text: "Step one\nStep two" } } as const;
  const planMarkup = renderLanguage("en", <InteractionSurface interaction={planInteraction} onSubmit={() => undefined} onCancel={() => undefined} />);
  assert.match(planMarkup, /Revision 3/);
  assert.match(planMarkup, /Approve and execute/);
  assert.match(planMarkup, /Revision feedback/);
  const multiMarkup = renderLanguage("en", <InteractionSurface interaction={{ ...inputInteraction, request: { questions: [{ question_id: "q1", header: "Tags", question: "Pick tags", kind: "multi_select", options: [{ label: "One", description: "first" }, { label: "Two", description: "second" }], allow_other: true }] } }} onSubmit={() => undefined} onCancel={() => undefined} />);
  assert.match(multiMarkup, /Pick tags/);
  assert.match(multiMarkup, /Other/);
});

test("T06 Provider Retry and user Pause render only typed continuation/cancel controls", () => {
  const retry = { kind: "provider_unavailable", pauseId: "pause-3", runId: "run-1", turnId: "turn-1", reason: "rate_limited" } as const;
  const retryMarkup = renderLanguage("en", <InteractionSurface interaction={retry} onSubmit={() => undefined} onCancel={() => undefined} />);
  assert.match(retryMarkup, /Retry/);
  assert.match(retryMarkup, /Cancel turn/);
  assert.doesNotMatch(retryMarkup, /backoff|reconnect|HTTP/u);
  const pause = { kind: "user_requested", pauseId: "pause-4", runId: "run-1", turnId: "turn-1", reason: "user_requested" } as const;
  const pauseMarkup = renderLanguage("en", <InteractionSurface interaction={pause} onSubmit={() => undefined} onCancel={() => undefined} />);
  assert.match(pauseMarkup, /Continue/);
  assert.match(pauseMarkup, /Cancel turn/);
});

test("T07 Settings uses the current configuration view and does not render secret values", () => {
  const state = createInitialState({ configuration: { default_model: "fake/model", default_permission_mode: "auto", providers: { fake: { provider_profile_id: "fake", kind: "fake", base_url: null, api_key_configured: false } }, models: { "fake/model": { model_ref: "fake/model", provider_profile_id: "fake", remote_id: "model", display_name: "Model", context_window: 128000, max_output_tokens: 4096, reasoning_effort: "none" } } }, settingsLoaded: true });
  const markup = renderToStaticMarkup(<SettingsView state={state} api={undefined} onBack={() => undefined} onSave={() => undefined} onThemeChange={() => undefined} onLanguageChange={() => undefined} />);
  assert.match(markup, /Provider 与模型|默认项|界面|关于/);
  assert.match(markup, /fake\/model/);
  assert.doesNotMatch(markup, /sk-live-secret|api_key=|secret value/u);
});

test("T07 rebuilt Settings and typed interactions keep accessible continuous and narrow layouts", async () => {
  const state = createInitialState({ runtimeState: "ready", theme: "light", configuration: { default_model: "fake/model", default_permission_mode: "default", providers: { fake: { kind: "fake", api_key_configured: true } }, models: { "fake/model": { provider_profile_id: "fake", remote_id: "model" } } }, settingsLoaded: true });
  const settingsMarkup = renderToStaticMarkup(<SettingsView state={state} api={undefined} onBack={() => undefined} onSave={() => undefined} onThemeChange={() => undefined} onLanguageChange={() => undefined} />);
  assert.match(settingsMarkup, /aria-label="设置"/u);
  for (const id of ["providers", "defaults", "interface", "about"]) {
    assert.match(settingsMarkup, new RegExp(`href="#settings-${id}"`));
    assert.match(settingsMarkup, new RegExp(`id="settings-${id}"`));
  }
  assert.doesNotMatch(settingsMarkup, /aria-current=/u);
  assert.match(settingsMarkup, /class="provider-row"[^>]*fake/u);
  assert.match(settingsMarkup, /fake\/model/u);
  assert.match(settingsMarkup, /已配置/u);
  assert.doesNotMatch(settingsMarkup, /<select|legacy-settings-editor/u);
  const permission = { kind: "permission_required", pauseId: "pause-a11y", runId: "run-a11y", turnId: "turn-a11y", request: { permission_id: "permission-a11y", choices: ["once", "reject"] } } as const;
  const interactionMarkup = renderLanguage("en", <InteractionSurface interaction={permission} onSubmit={() => undefined} onCancel={() => undefined} />);
  assert.match(interactionMarkup, /aria-label="Permission approval"/u);
  assert.match(interactionMarkup, /type="button"/u);
  const css = await (await import("node:fs/promises")).readFile(new URL("../src/renderer/app.css", import.meta.url), "utf8");
  assert.match(css, /\.settings-view\s*\{[^}]*grid-template-columns:\s*220px minmax\(0, 1fr\)/s);
  assert.match(css, /\.settings-section\s*\{[^}]*border-top:\s*1px solid var\(--line\)/s);
  assert.match(css, /@media \(max-width:\s*900px\)[\s\S]*?\.settings-view\s*\{[^}]*grid-template-columns:\s*1fr/s);
  assert.match(css, /\.interaction-surface\s*\{[^}]*border-top:\s*2px solid var\(--accent\)/s);
});

test("T07 removing a provider discards its transient key before the same ID can be recreated", () => {
  const apiKeys = withoutRecordKey({ fake: "sk-transient", keep: "sk-keep" }, "fake");
  const touchedKeys = withoutRecordKey({ fake: true, keep: true }, "fake");
  const recreatedDraft = { providers: { fake: { kind: "fake", base_url: null }, keep: { kind: "fake", base_url: null } } };
  const request = settingsSaveRequest(recreatedDraft, apiKeys, touchedKeys);
  const providers = request.providers as Record<string, Record<string, unknown>>;
  assert.equal(providers.fake.api_key, undefined);
  assert.equal(providers.keep.api_key, "sk-keep");
  assert.doesNotMatch(JSON.stringify(request), /sk-transient/u);
});

test("T07 four-field setup writes a valid OpenAI-compatible candidate without guessed model limits", () => {
  const request = settingsSaveRequest({
    default_model: "model",
    default_permission_mode: "default",
    providers: { provider: { kind: "openai_compat", base_url: "https://gateway.example/v1", api_key_configured: false } },
    models: { model: { provider_profile_id: "provider", remote_id: "served-model", display_name: null, context_window: null, max_output_tokens: null, reasoning_effort: null } },
  }, { provider: "sk-test-only" }, { provider: true });
  assert.equal(request.default_model, "model");
  assert.deepEqual(request.providers?.provider, { kind: "openai_compat", base_url: "https://gateway.example/v1", api_key: "sk-test-only" });
  assert.deepEqual(request.models?.model, { provider_profile_id: "provider", remote_id: "served-model", display_name: null, context_window: null, max_output_tokens: null, reasoning_effort: null });
});

test("Prompt 2 provider editor groups and preserves every existing model field", () => {
  assert.equal(modelFieldId("dialog", "a/b", "remote"), "dialog-0061-002f-0062-remote");
  assert.equal(modelFieldId("dialog", "a/b", "remote"), modelFieldId("dialog", "a/b", "remote"));
  assert.notEqual(modelFieldId("dialog", "a/b", "remote"), modelFieldId("dialog", "a-b", "remote"));
  assert.notEqual(modelFieldId("dialog", "中文", "remote"), modelFieldId("dialog", "--", "remote"));
  assert.notEqual(modelFieldId("dialog", "", "remote"), modelFieldId("dialog", "empty", "remote"));
  assert.notEqual(modelFieldId("dialog", "one/model", "remote"), modelFieldId("dialog", "two/model", "remote"));
  assert.deepEqual(reasoningEffortOptions, ["", "none", "minimal", "low", "medium", "high", "xhigh", "max"]);
  assert.equal(reasoningEffortOptions.includes("invalid" as never), false);
  const draft = { providers: { provider: { kind: "openai_compat" } }, models: { primary: { provider_profile_id: "provider", remote_id: "one", display_name: "One", context_window: 128000, max_output_tokens: 8192, reasoning_effort: "high" }, secondary: { provider_profile_id: "provider", remote_id: "two", display_name: null, context_window: null, max_output_tokens: null, reasoning_effort: null }, other: { provider_profile_id: "other", remote_id: "three" } } };
  assert.deepEqual(providerModels(draft, "provider"), [["primary", draft.models.primary], ["secondary", draft.models.secondary]]);
  const request = settingsSaveRequest(draft, {}, {});
  assert.deepEqual(request.models?.primary, draft.models.primary);
  assert.deepEqual(request.models?.secondary, draft.models.secondary);
});

test("T07 missing optional model fields stay null instead of becoming invalid empty strings", () => {
  const state = createInitialState({ configuration: { default_model: "provider/model", default_permission_mode: "default", providers: { provider: { kind: "openai_compat", base_url: "https://gateway.example/v1", api_key_configured: true } }, models: { "provider/model": { provider_profile_id: "provider", remote_id: "served-model" } } }, settingsLoaded: true });
  const markup = renderToStaticMarkup(<SettingsView state={state} api={undefined} onBack={() => undefined} onSave={() => undefined} onThemeChange={() => undefined} onLanguageChange={() => undefined} />);
  assert.match(markup, /provider\/model/u);
  const request = settingsSaveRequest({ default_model: "provider/model", providers: { provider: { kind: "openai_compat", base_url: "https://gateway.example/v1" } }, models: { "provider/model": { provider_profile_id: "provider", remote_id: "served-model", display_name: null, context_window: null, max_output_tokens: null, reasoning_effort: null } } }, {}, {});
  assert.deepEqual(request.models?.["provider/model"], { provider_profile_id: "provider", remote_id: "served-model", display_name: null, context_window: null, max_output_tokens: null, reasoning_effort: null });
  assert.doesNotMatch(JSON.stringify(request), /"display_name":""/u);
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
  assert.match(markup, /不可用|Unavailable/);
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
  const markup = renderToStaticMarkup(<SettingsView state={state} api={undefined} onBack={() => undefined} onSave={() => undefined} onThemeChange={() => undefined} onLanguageChange={() => undefined} />);
  assert.match(markup, /fake\/model/);
  assert.doesNotMatch(markup, /context window|max output tokens|legacy-settings-editor/i);
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

test("Prompt 1 hidden Runtime is restored only from the chat header", () => {
  const markup = renderToStaticMarkup(<App initialState={createInitialState({ panelMode: "hidden" })} api={undefined} />);
  assert.match(markup, /title="切换 Runtime" aria-label="切换 Runtime"/);
  assert.doesNotMatch(markup, />Open Runtime</);
  assert.doesNotMatch(markup, /Compact Session|Show status/);
});

test("Prompt 2 locale resources have exact parity and custom select skips disabled options", () => {
  assert.equal(customSelectConsumesEscape(false), false);
  assert.equal(customSelectConsumesEscape(true), true);
  assert.equal(stateLabel("pausing", (key) => translate("zh-CN", key)), "正在暂停…");
  assert.equal(stateLabel("provider-payload", (key) => translate("zh-CN", key)), "provider-payload");
  assert.equal(initialEnabledOption([{ value: "", label: "Choose", disabled: true }, { value: "a", label: "A" }], ""), 1);
  assert.equal(initialEnabledOption([{ value: "a", label: "A" }, { value: "b", label: "B" }], "b"), 1);
  assert.equal(initialEnabledOption([{ value: "a", label: "A", disabled: true }], "a"), -1);
  assert.deepEqual(Object.keys(resources.en).sort(), Object.keys(resources["zh-CN"]).sort());
  assert.equal(translate("en", "settings"), "Settings");
  assert.equal(translate("zh-CN", "settings"), "设置");
  const options = [{ value: "none", label: "None", disabled: true }, { value: "a", label: "A" }, { value: "b", label: "B" }];
  assert.equal(nextEnabledOption(options, 2, 1), 1);
  assert.equal(nextEnabledOption(options, 1, -1), 2);
  const source = require("node:fs").readFileSync(new URL("../src/renderer/CustomSelect.tsx", import.meta.url), "utf8");
  for (const key of ["Enter", " ", "ArrowDown", "ArrowUp", "Home", "End", "Escape", "Tab"]) assert.match(source, new RegExp(JSON.stringify(key).slice(1, -1).replace(/[.*+?^${}()|[\]\\]/gu, "\\$&")));
  assert.doesNotMatch(source, /aria-activedescendant/u);
  assert.match(source, /event\.stopPropagation\(\)/u);
  const settingsSource = require("node:fs").readFileSync(new URL("../src/renderer/SettingsView.tsx", import.meta.url), "utf8");
  assert.match(settingsSource, /event\.defaultPrevented/u);
  const selectMarkup = renderToStaticMarkup(<><CustomSelect value="a" label="First" options={[{ value: "a", label: "A" }]} onChange={() => undefined} /><CustomSelect value="b" label="Second" options={[{ value: "b", label: "B" }]} onChange={() => undefined} /></>);
  assert.match(selectMarkup, /aria-haspopup="listbox"/u);
  assert.match(selectMarkup, /aria-expanded="false"/u);
  const controls = [...selectMarkup.matchAll(/aria-controls="([^"]+)"/gu)].map((match) => match[1]);
  assert.equal(new Set(controls).size, 2);
  const selectSources = ["Composer.tsx", "RuntimePanel.tsx", "SettingsView.tsx"].map((name) => require("node:fs").readFileSync(new URL(`../src/renderer/${name}`, import.meta.url), "utf8")).join("\n");
  assert.doesNotMatch(selectSources, /<select/u);
  const english = renderToStaticMarkup(<App initialState={createInitialState({ language: "en", view: "settings", settingsLoaded: true })} api={undefined} />);
  const chinese = renderToStaticMarkup(<App initialState={createInitialState({ language: "zh-CN", view: "settings", settingsLoaded: true })} api={undefined} />);
  assert.match(english, />Settings</);
  assert.match(chinese, />设置</);
});

test("T07 Runtime switch and three layout modes remain operational", async () => {
  const dockedMarkup = renderToStaticMarkup(<App initialState={createInitialState({ panelMode: "docked" })} api={undefined} />);
  assert.match(dockedMarkup, /aria-label="切换 Runtime"/);
  const floatingMarkup = renderToStaticMarkup(<App initialState={createInitialState({ panelMode: "floating" })} api={undefined} />);
  assert.match(floatingMarkup, /runtime-panel--floating/);
  const settingsMarkup = renderToStaticMarkup(<App initialState={createInitialState({ view: "settings", panelMode: "docked", settingsLoaded: true })} api={undefined} />);
  assert.match(settingsMarkup, /class="app-shell theme-system panel-docked settings-shell"/);
  assert.match(settingsMarkup, /aria-label="设置"/);
  assert.doesNotMatch(settingsMarkup, /aria-label="Project navigation"|aria-label="Runtime information"|settings-runtime|>READY<|>Ready</);
  assert.doesNotMatch(settingsMarkup, /Connect the service that runs your models|Use the model name expected by your provider|Default permission mode for new Runs|Appearance preferences are stored on this Desktop installation/);
  const selectedModes: string[] = [];
  const modeSelect = RuntimeLayoutSelect({ value: "docked", onChange: (mode) => selectedModes.push(mode), labels: { control: "Layout", docked: "Docked", floating: "Floating", hidden: "Hidden" } }) as React.ReactElement<{ onChange: (value: string) => void }>;
  assert.equal(modeSelect.type, CustomSelect);
  for (const value of ["floating", "docked", "hidden"]) modeSelect.props.onChange(value);
  assert.deepEqual(selectedModes, ["floating", "docked", "hidden"]);
  const css = await (await import("node:fs/promises")).readFile(new URL("../src/renderer/app.css", import.meta.url), "utf8");
  assert.match(css, /\.runtime-panel--docked\s*\{[^}]*position:\s*relative[^}]*width:/s);
  assert.match(css, /\.runtime-panel--floating\s*\{[^}]*position:\s*fixed[^}]*width:\s*304px;[^}]*height:\s*304px;[^}]*border-radius:\s*18px/s);
  assert.match(css, /\.runtime-panel--hidden\s*\{\s*display:\s*none;/s);
  assert.match(css, /@media \(max-width: 820px\)[\s\S]*?\.app-shell\s*\{\s*--sidebar-width:\s*196px;/);
  assert.match(css, /\.app-shell\.panel-docked \.composer-toolbar\s*\{[^}]*display:\s*grid;[^}]*grid-template-columns:\s*minmax\(0, 1fr\)/s);
  assert.match(css, /\.app-shell\.panel-docked \.composer-input\s*\{[^}]*display:\s*flex;[^}]*flex-direction:\s*column/s);
  assert.match(css, /\.app-shell\.panel-docked \.composer textarea\s*\{[^}]*width:\s*100%;[^}]*min-width:\s*0;[^}]*min-height:\s*72px;[^}]*word-break:\s*normal/s);
  assert.match(css, /\.app-shell\.panel-docked \.composer-actions\s*\{[^}]*flex-wrap:\s*wrap;[^}]*justify-content:\s*flex-end/s);
  assert.match(css, /\.app-shell\.panel-docked \.timeline\s*\{\s*padding-bottom:\s*286px;/);
  assert.doesNotMatch(css, /settings-runtime|settings-section__hint/);
});

test("T07 completion preserves canonical slash prefixes and replaces only the current argument", () => {
  assert.equal(applyCompletion("/mo", "/model"), "/model ");
  assert.equal(applyCompletion("/model f", "fake/model"), "/model fake/model ");
  assert.equal(applyCompletion("/m f", "fake/model"), "/m fake/model ");
  assert.equal(applyCompletion("  /model old arg", "new"), "  /model old new ");
});
