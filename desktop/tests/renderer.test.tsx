import { test } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { JSDOM } from "jsdom";
import { isJsonValue } from "../src/desktop-api";
import type { AgentEvent, DesktopApi, DesktopPreferences, JsonObject } from "../src/desktop-api";

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
import { App, projectNavigationPreferences, projectPinPlan, projectRemovalPlan, rebootstrapProject, safeErrorMessage } from "../src/renderer/App";
import { MAX_VISIBLE_SESSIONS, Sidebar, sessionGroups } from "../src/renderer/Sidebar";
import { ChatTimeline, isNearBottom, renderMarkdown, scrollTimelineToBottom } from "../src/renderer/ChatTimeline";
import { Composer, ContextRing, applyCompletion, contextUsagePercent, edgeCompletionIndex, modelDisplayName, nextCompletionIndex } from "../src/renderer/Composer";
import { InteractionSurface, buildPermissionResponse, buildPlanResponse, buildResumeResponse, buildRetryResponse, buildUserInputResponse, interactionSurfaceKey } from "../src/renderer/InteractionSurface";
import { SettingsView, configurationRequest, modelFieldId, parseOptionalPositiveInteger, providerModels, reasoningEffortOptions, settingsSaveRequest, withoutRecordKey, type ConfigurationWrite } from "../src/renderer/SettingsView";
import { RuntimeLayoutSelect, RuntimePanel, stateLabel } from "../src/renderer/RuntimePanel";
import { CustomSelect, customSelectConsumesEscape, initialEnabledOption, nextEnabledOption } from "../src/renderer/CustomSelect";
import { LanguageProvider, resources, translate } from "../src/renderer/i18n";

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

test("T08 renderer error projection keeps transport details out of both localized UIs", () => {
  const failures: unknown[] = [
    Object.assign(new Error("Runtime request settings.get failed: user config not initialized"), { name: "RuntimeRequestError" }),
    { name: "RuntimeRequestError", message: "RuntimeRequestError: settings.get /private/config.toml" },
    { error: { name: "RuntimeRequestError", message: "preference.write failed: EPERM C:\\Users\\user\\config.toml" } },
    { code: "EPERM", message: "native rejection from sandbox bundle" },
    "unknown native rejection",
    null,
  ];
  for (const language of ["zh-CN", "en"] as const) {
    const fallback = translate(language, "settingsSaveFailed");
    for (const failure of failures) {
      assert.equal(safeErrorMessage(failure, fallback), fallback);
      assert.doesNotMatch(safeErrorMessage(failure, fallback), /RuntimeRequestError|settings\.get|preference\.write|EPERM|sandbox bundle|config\.toml|native rejection/u);
    }
  }
});

test("T08 App presents localized safe fallbacks for settings, preference, and bundled Runtime failures", async () => {
  const projectPath = "C:/sandbox-project";
  const preferences = (language: "zh-CN" | "en", selectedProjectKey: string | null = null): DesktopPreferences => ({
    theme: "system",
    language,
    windowBounds: { width: 1100, height: 760, maximized: false },
    panelMode: "docked",
    recentProjects: selectedProjectKey ? [{ path: selectedProjectKey }] : [],
    projectAliases: {},
    pinnedProjectKeys: [],
    pinnedSessions: [],
    expandedProjects: {},
    selectedProjectKey,
    selectedSessionId: null,
  });
  const flush = async () => { await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); }); };

  for (const language of ["zh-CN", "en"] as const) {
    await withRendererDom(async (_dom, container, root) => {
      const stored = preferences(language);
      const rawSettingsGet = "RuntimeRequestError: settings.get user config not initialized /private/config.toml";
      const rawPreferenceWrite = "Error: preference.write EPERM C:\\Users\\user\\config.toml";
      const rawSave = "RuntimeRequestError: settings.save native rejection RuntimeRequestError";
      const api: DesktopApi = {
        openProject: async () => null,
        openProjectInExplorer: async () => undefined,
        copySessionId: async () => undefined,
        closeShell: async () => undefined,
        requestRuntime: async (method) => {
          if (method === "settings.get") throw new Error(rawSettingsGet);
          if (method === "settings.save") throw new Error(rawSave);
          return {};
        },
        subscribeAgentEvents: () => () => undefined,
        readPreference: async (key) => stored[key],
        writePreference: async () => { throw new Error(rawPreferenceWrite); },
      };
      const configuration = {
        default_model: "provider/model",
        default_permission_mode: "default" as const,
        providers: { provider: { kind: "openai_compat", base_url: "https://gateway.example/v1", api_key_configured: false } },
        models: { "provider/model": { provider_profile_id: "provider", remote_id: "remote-model", display_name: "Model" } },
      };
      const state = createInitialState({ language, view: "settings", configuration, settingsLoaded: true });
      act(() => { root.render(<App initialState={state} api={api} />); });
      for (let index = 0; index < 4; index += 1) await flush();

      const save = container.querySelector<HTMLButtonElement>(".settings-actions .save-button");
      assert.ok(save);
      act(() => { save!.click(); });
      for (let index = 0; index < 10; index += 1) await flush();
      const saveError = container.querySelector<HTMLElement>(".settings-view__error")?.textContent ?? "";
      assert.equal(saveError, translate(language, "settingsSaveFailed"));
      assert.doesNotMatch(container.textContent ?? "", /RuntimeRequestError|settings\.save|native rejection|config\.toml/u);

      const theme = Array.from(container.querySelectorAll<HTMLButtonElement>(".custom-select__trigger"))
        .find((button) => button.title === translate(language, "theme"));
      assert.ok(theme);
      act(() => { theme!.click(); });
      await flush();
      const alternateTheme = container.querySelector<HTMLButtonElement>(`[role="option"][title="${language === "en" ? "Light" : "浅色"}"]`);
      assert.ok(alternateTheme);
      act(() => { alternateTheme!.click(); });
      for (let index = 0; index < 4; index += 1) await flush();
      act(() => { container.querySelector<HTMLButtonElement>(`.settings-view__back[title="${translate(language, "back")}"]`)?.click(); });
      await flush();
      assert.match(container.querySelector<HTMLElement>(".timeline-notice")?.textContent ?? "", new RegExp(language === "en" ? "Desktop preferences are unavailable" : "桌面偏好不可用", "u"));
      assert.doesNotMatch(container.textContent ?? "", /EPERM|preference\.write|config\.toml|RuntimeRequestError|native rejection/u);

      const settingsButton = container.querySelector<HTMLButtonElement>(`.sidebar-footer button[title="${translate(language, "openSettings")}"]`);
      assert.ok(settingsButton);
      act(() => { settingsButton!.click(); });
      for (let index = 0; index < 8; index += 1) await flush();
      const settingsError = container.querySelector<HTMLElement>(".settings-view__error")?.textContent ?? "";
      assert.equal(settingsError, translate(language, "configUnavailable"));
      assert.doesNotMatch(container.textContent ?? "", /RuntimeRequestError|settings\.get|user config not initialized|config\.toml/u);
    });
  }

  await withRendererDom(async (_dom, container, root) => {
    const stored = preferences("en", projectPath);
    const rawSandboxFailure = "RuntimeBoundaryError: bundled Runtime sandbox launch failed at C:\\resources\\uthcode-runtime";
    const api: DesktopApi = {
      openProject: async () => null,
      openProjectInExplorer: async () => undefined,
      copySessionId: async () => undefined,
      requestRuntime: async (method) => {
        if (method === "runtime.initialize") throw new Error(rawSandboxFailure);
        return {};
      },
      subscribeAgentEvents: () => () => undefined,
      readPreference: async (key) => stored[key],
      writePreference: async () => stored,
    };
    act(() => { root.render(<App initialState={createInitialState({ language: "en" })} api={api} />); });
    for (let index = 0; index < 12; index += 1) await flush();
    assert.match(container.querySelector<HTMLElement>(".runtime-panel__error")?.textContent ?? "", /Runtime could not start/u);
    assert.doesNotMatch(container.textContent ?? "", /RuntimeBoundaryError|sandbox launch failed|uthcode-runtime|resources/u);
  });
});

test("T06 Runtime error owns one accessible DOM entity across renderer modes", async () => {
  await withRendererDom(async (dom, container, root) => {
    const scenarios = [
      { width: 1100, panelMode: "docked" as const, owner: "runtime-panel" },
      { width: 1100, panelMode: "floating" as const, owner: "runtime-panel" },
      { width: 760, panelMode: "docked" as const, owner: "runtime-panel" },
      { width: 1100, panelMode: "hidden" as const, owner: "timeline" },
      { width: 680, panelMode: "docked" as const, owner: "timeline" },
      { width: 608, panelMode: "docked" as const, owner: "timeline" },
      { width: 533, panelMode: "docked" as const, owner: "timeline" },
      { width: 520, panelMode: "floating" as const, owner: "runtime-panel" },
      { width: 507, panelMode: "docked" as const, owner: "timeline" },
      { width: 500, panelMode: "hidden" as const, owner: "timeline" },
    ];
    const themes = ["dark", "light"] as const;
    const languages = ["en", "zh-CN"] as const;
    let renderIndex = 0;
    for (const theme of themes) {
      for (const language of languages) {
        for (const scenario of scenarios) {
          Object.defineProperty(dom.window, "innerWidth", { configurable: true, value: scenario.width });
          const error = translate(language, "runtimeStartFailed");
          const state = createInitialState({ language, theme, panelMode: scenario.panelMode, runtimeState: "configuration_required", runtimeError: error, notice: error });
          const stored: DesktopPreferences = { theme, language, windowBounds: { width: scenario.width, height: 800, maximized: false }, panelMode: scenario.panelMode, recentProjects: [], projectAliases: {}, pinnedProjectKeys: [], pinnedSessions: [], expandedProjects: {}, selectedProjectKey: null, selectedSessionId: null };
          const api: DesktopApi = { openProject: async () => null, openProjectInExplorer: async () => undefined, copySessionId: async () => undefined, closeShell: async () => undefined, requestRuntime: async () => ({}), subscribeAgentEvents: () => () => undefined, readPreference: async (key) => stored[key], writePreference: async () => stored };
          act(() => { root.render(<App key={`${theme}-${language}-${scenario.width}-${scenario.panelMode}-${renderIndex++}`} initialState={state} api={api} />); });
          await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });

          const runtimeError = container.querySelector<HTMLElement>("[data-runtime-error-owner]");
          assert.ok(runtimeError, `${theme}/${language}/${scenario.width}/${scenario.panelMode} should render an error`);
          assert.equal(runtimeError?.getAttribute("data-runtime-error-owner"), scenario.owner);
          assert.equal(container.querySelectorAll<HTMLElement>("[data-runtime-error-owner]").length, 1, "one Runtime error has one visual owner");
          assert.equal(container.querySelectorAll<HTMLElement>('[role="alert"]').length, 1, "one Runtime error has one alert region");
          assert.equal(container.querySelector(".configuration-banner"), null, "the old fixed bottom banner is gone");
          assert.match(runtimeError?.textContent ?? "", new RegExp(error.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&"), "u"));

          const composer = container.querySelector<HTMLElement>(".composer");
          assert.ok(composer);
          if (scenario.owner === "timeline") {
            const notice = container.querySelector<HTMLElement>(".timeline-runtime-error");
            assert.ok(notice);
            assert.equal(notice?.parentElement?.classList.contains("timeline"), true);
            assert.equal(notice?.getAttribute("role"), "alert");
            const openSettings = notice?.querySelector<HTMLButtonElement>("button");
            assert.ok(openSettings, "configuration error keeps a reachable settings action");
            assert.equal(openSettings?.textContent, translate(language, "openSettings"));
            act(() => { openSettings?.focus(); });
            assert.equal(dom.window.document.activeElement, openSettings);
          } else {
            assert.equal(container.querySelector(".timeline-runtime-error"), null, "visible Runtime owns the error");
            const runtimePanel = container.querySelector<HTMLElement>("#runtime-panel");
            assert.equal(runtimeError?.closest("#runtime-panel"), runtimePanel);
            assert.equal(runtimePanel?.getAttribute("aria-hidden"), null);
            const panelError = runtimePanel?.querySelector<HTMLElement>(".runtime-panel__error");
            assert.ok(panelError);
          }
          assert.equal(container.querySelector<HTMLElement>(".composer textarea")?.disabled, false, "error presentation must not disable the main Composer");
        }
      }
    }
  });
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
    const panelMarkup = renderLanguage("en", <RuntimePanel state={createInitialState({ ...base, panelMode, currentModelRef: "provider/model", permissionMode: "auto", contextUsage: { used_tokens: 1200, budget_tokens: 128000, available: true, measurement: "estimate", source: "application" }, run: { run_id: "run-123456", behavior_mode: "plan", usage: { used_tokens: 1200, budget_tokens: 4000 } } })} onPanelModeChange={() => undefined} />);
    assert.match(panelMarkup, /aria-label="Runtime information"/);
    assert.match(panelMarkup, new RegExp(`runtime-panel--${panelMode}`));
    assert.match(panelMarkup, /1,200 \/ 128,000/);
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
    const renderSidebar = async (items: ProjectState[], selectedSessionId: string | null = null, expandedProjects: Record<string, boolean> = {}, key = "sidebar", sessionMutationBusy = false) => {
      act(() => {
        root.render(<LanguageProvider value="en"><Sidebar
          key={key}
          projects={items}
          selectedProjectKey={items[0]?.projectKey ?? null}
          selectedSessionId={selectedSessionId}
          activeTurn={false}
          sessionMutationBusy={sessionMutationBusy}
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

    // A durable Session rename/move is single-flight.  The busy projection is
    // exposed on the navigation root and disables both mutation actions,
    // including the target-specific Move entry.
    const target = { path: "C:/target", projectKey: "C:/target", alias: "Target", pinned: false, sessions: [], catalogFresh: true } satisfies ProjectState;
    await renderSidebar([project(), target], "s1", {}, "busy-sidebar", true);
    assert.equal(container.querySelector<HTMLElement>("aside")?.getAttribute("aria-busy"), "true");
    const busyTrigger = container.querySelector<HTMLButtonElement>(".session-menu-trigger");
    assert.ok(busyTrigger);
    await openMenu(busyTrigger!);
    const busyItems = Array.from(container.querySelectorAll<HTMLButtonElement>(".sidebar-menu__item"));
    const busyRename = busyItems.find((button) => button.textContent?.includes("Rename"));
    const busyMove = busyItems.find((button) => button.textContent?.includes("Move to project Target"));
    assert.equal(busyRename?.disabled, true);
    assert.equal(busyMove?.disabled, true);
    assert.match(busyRename?.getAttribute("aria-label") ?? "", /already in progress/u);
    assert.match(busyMove?.getAttribute("title") ?? "", /already in progress/u);
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

test("T05 App single-flights Session mutations and applies only the accepted move", async () => {
  await withRendererDom(async (_dom, container, root) => {
    const sourcePath = "C:/source";
    const targetPath = "C:/target";
    const sourceSession = { session_id: "move-a", project_key: sourcePath, title: "Original", preview: "Original preview", last_used_at: "2026-08-01", transcript_entries: 2 };
    let moveCalls = 0;
    let renameCalls = 0;
    let catalogCalls = 0;
    let resolveMove: ((value: JsonValue) => void) | null = null;
    const api: DesktopApi = {
      openProject: async () => null,
      openProjectInExplorer: async () => undefined,
      copySessionId: async () => undefined,
      closeShell: async () => undefined,
      requestRuntime: async (method) => {
        if (method === "session.move") {
          moveCalls += 1;
          return await new Promise<JsonValue>((resolve) => { resolveMove = resolve; });
        }
        if (method === "session.rename") {
          renameCalls += 1;
          return { session_id: "move-a", project_key: sourcePath, title: "Should not run" };
        }
        if (method === "project.sessions") {
          catalogCalls += 1;
          return { sessions: [] };
        }
        return {};
      },
      subscribeAgentEvents: () => () => undefined,
      readPreference: async () => undefined as never,
      writePreference: async () => undefined as never,
    };
    const state = createInitialState({
      language: "en",
      runtimeState: "ready",
      projects: [
        { path: sourcePath, projectKey: sourcePath, alias: "Source", pinned: false, sessions: [sourceSession], catalogFresh: true },
        { path: targetPath, projectKey: targetPath, alias: "Target", pinned: false, sessions: [], catalogFresh: true },
      ],
      selectedProjectKey: sourcePath,
      selectedSessionId: sourceSession.session_id,
    });
    act(() => { root.render(<App initialState={state} api={api} />); });
    const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0));
    const flush = async () => { await act(async () => { await tick(); await tick(); await tick(); }); };
    const openSessionMenu = async () => {
      const trigger = container.querySelector<HTMLButtonElement>(".project-item .session-menu-trigger");
      assert.ok(trigger);
      act(() => { trigger.click(); });
      await flush();
      return Array.from(container.querySelectorAll<HTMLButtonElement>(".sidebar-menu__item"));
    };
    await flush();

    const moveItems = await openSessionMenu();
    const moveItem = moveItems.find((button) => button.textContent?.includes("Move to project Target"));
    assert.ok(moveItem);
    act(() => { moveItem!.click(); });
    await flush();
    assert.equal(moveCalls, 1, "the first move owns the only mutation RPC");
    assert.equal(container.querySelector<HTMLElement>("aside")?.getAttribute("aria-busy"), "true");

    // A second Move and Rename are disabled while A is waiting, so neither a
    // stale menu nor a second click can produce another side effect.
    const blockedItems = await openSessionMenu();
    const blockedRename = blockedItems.find((button) => button.textContent?.includes("Rename"));
    const blockedMove = blockedItems.find((button) => button.textContent?.includes("Move to project Target"));
    assert.equal(blockedRename?.disabled, true);
    assert.equal(blockedMove?.disabled, true);
    act(() => { blockedRename?.click(); blockedMove?.click(); });
    assert.equal(moveCalls, 1);
    assert.equal(renameCalls, 0);

    assert.ok(resolveMove);
    act(() => {
      resolveMove!({
        session_id: "move-a",
        project_key: targetPath,
        title: "Moved",
        session: { session_id: "move-a", project_key: targetPath, title: "Moved" },
      });
    });
    await flush();
    const target = Array.from(container.querySelectorAll<HTMLElement>(".project-item"))
      .find((item) => item.textContent?.includes("Target"));
    assert.ok(target);
    assert.equal(container.querySelector<HTMLElement>("aside")?.getAttribute("aria-busy"), null);
    assert.equal(catalogCalls, 1, "accepted Move refreshes the source catalog authority");
    assert.ok(!container.querySelector<HTMLElement>(".project-item:first-child .session-line")?.textContent?.includes("Original"));
    const targetDisclosure = target?.querySelector<HTMLButtonElement>(".disclosure");
    assert.ok(targetDisclosure);
    act(() => { targetDisclosure!.click(); });
    await flush();
    assert.match(target?.textContent ?? "", /Moved/u);
  });
});

test("T05 App keeps the original Session projection after a failed mutation", async () => {
  await withRendererDom(async (_dom, container, root) => {
    const sourcePath = "C:/source";
    const targetPath = "C:/target";
    const sourceSession = { session_id: "move-fail", project_key: sourcePath, title: "Original", preview: "Original preview", last_used_at: "2026-08-01" };
    let moveCalls = 0;
    let rejectMove: ((reason?: unknown) => void) | null = null;
    let catalogCalls = 0;
    const api: DesktopApi = {
      openProject: async () => null,
      openProjectInExplorer: async () => undefined,
      copySessionId: async () => undefined,
      closeShell: async () => undefined,
      requestRuntime: async (method) => {
        if (method === "session.move") {
          moveCalls += 1;
          return await new Promise<JsonValue>((_resolve, reject) => { rejectMove = reject; });
        }
        if (method === "project.sessions") {
          catalogCalls += 1;
          return { sessions: [sourceSession] };
        }
        return {};
      },
      subscribeAgentEvents: () => () => undefined,
      readPreference: async () => undefined as never,
      writePreference: async () => undefined as never,
    };
    const state = createInitialState({
      language: "en",
      runtimeState: "ready",
      projects: [
        { path: sourcePath, projectKey: sourcePath, alias: "Source", pinned: false, sessions: [sourceSession], catalogFresh: true },
        { path: targetPath, projectKey: targetPath, alias: "Target", pinned: false, sessions: [], catalogFresh: true },
      ],
      selectedProjectKey: sourcePath,
      selectedSessionId: sourceSession.session_id,
    });
    act(() => { root.render(<App initialState={state} api={api} />); });
    const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0));
    const flush = async () => { await act(async () => { await tick(); await tick(); await tick(); }); };
    await flush();
    const trigger = container.querySelector<HTMLButtonElement>(".project-item .session-menu-trigger");
    assert.ok(trigger);
    act(() => { trigger!.click(); });
    await flush();
    const move = Array.from(container.querySelectorAll<HTMLButtonElement>(".sidebar-menu__item"))
      .find((button) => button.textContent?.includes("Move to project Target"));
    assert.ok(move);
    act(() => { move!.click(); });
    await flush();
    assert.equal(moveCalls, 1);
    assert.equal(container.querySelector<HTMLElement>("aside")?.getAttribute("aria-busy"), "true");
    assert.ok(rejectMove);
    act(() => { rejectMove!(new Error("move failed")); });
    await flush();
    assert.equal(moveCalls, 1, "failure does not retry the side-effect RPC");
    assert.equal(catalogCalls, 1, "failure reconciles the source catalog once");
    assert.equal(container.querySelector<HTMLElement>("aside")?.getAttribute("aria-busy"), null);
    assert.match(container.querySelector<HTMLElement>(".project-item:first-child")?.textContent ?? "", /Original/u);
    assert.doesNotMatch(container.querySelector<HTMLElement>(".project-item:nth-child(2)")?.textContent ?? "", /move-fail/u);
  });
});

test("T05 App ignores a late mutation result after navigation changes the Runtime generation", async () => {
  await withRendererDom(async (_dom, container, root) => {
    const sourcePath = "C:/source";
    const targetPath = "C:/target";
    const sourceSession = { session_id: "move-late", project_key: sourcePath, title: "Original", preview: "Original preview" };
    let moveCalls = 0;
    let resolveMove: ((value: JsonValue) => void) | null = null;
    const api: DesktopApi = {
      openProject: async () => null,
      openProjectInExplorer: async () => undefined,
      copySessionId: async () => undefined,
      closeShell: async () => undefined,
      requestRuntime: async (method, params) => {
        if (method === "session.move") {
          moveCalls += 1;
          return await new Promise<JsonValue>((resolve) => { resolveMove = resolve; });
        }
        if (method === "project.open") {
          return { project: { path: String(params.path) }, sessions: [], run: null };
        }
        if (method === "project.sessions") return { sessions: [] };
        return {};
      },
      subscribeAgentEvents: () => () => undefined,
      readPreference: async () => undefined as never,
      writePreference: async () => undefined as never,
    };
    const state = createInitialState({
      language: "en",
      runtimeState: "ready",
      projects: [
        { path: sourcePath, projectKey: sourcePath, alias: "Source", pinned: false, sessions: [sourceSession], catalogFresh: true },
        { path: targetPath, projectKey: targetPath, alias: "Target", pinned: false, sessions: [], catalogFresh: true },
      ],
      selectedProjectKey: sourcePath,
      selectedSessionId: sourceSession.session_id,
    });
    act(() => { root.render(<App initialState={state} api={api} />); });
    const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0));
    const flush = async () => { await act(async () => { await tick(); await tick(); await tick(); }); };
    await flush();
    const sourceTrigger = container.querySelector<HTMLButtonElement>(".project-item .session-menu-trigger");
    assert.ok(sourceTrigger);
    act(() => { sourceTrigger!.click(); });
    await flush();
    const move = Array.from(container.querySelectorAll<HTMLButtonElement>(".sidebar-menu__item"))
      .find((button) => button.textContent?.includes("Move to project Target"));
    assert.ok(move);
    act(() => { move!.click(); });
    await flush();
    assert.equal(moveCalls, 1);

    // Navigation is allowed while the mutation is in flight, but it owns a
    // newer Runtime generation. The late Move result must not be applied to
    // the now-selected Target project.
    const targetSelect = Array.from(container.querySelectorAll<HTMLButtonElement>(".project-select"))
      .find((button) => button.textContent?.includes("Target"));
    assert.ok(targetSelect);
    act(() => { targetSelect!.click(); });
    await flush();
    assert.match(container.querySelector<HTMLElement>(".project-item.is-active")?.textContent ?? "", /Target/u);
    assert.ok(resolveMove);
    act(() => {
      resolveMove!({
        session_id: "move-late",
        project_key: targetPath,
        title: "Late move",
        session: { session_id: "move-late", project_key: targetPath, title: "Late move" },
      });
    });
    await flush();
    assert.equal(moveCalls, 1);
    assert.equal(container.querySelector<HTMLElement>("aside")?.getAttribute("aria-busy"), null);
    assert.doesNotMatch(container.querySelector<HTMLElement>(".project-item.is-active")?.textContent ?? "", /Late move/u);
    assert.doesNotMatch(container.querySelector<HTMLElement>(".project-item.is-active")?.textContent ?? "", /move-late/u);
  });
});

test("T05 App routes direct commands and waits for terminal status authority", async () => {
  await withRendererDom(async (dom, container, root) => {
    const preferences: DesktopPreferences = {
      theme: "system",
      language: "en",
      windowBounds: { width: 1100, height: 760, maximized: false },
      panelMode: "docked",
      recentProjects: [],
      projectAliases: {},
      pinnedProjectKeys: [],
      pinnedSessions: [],
      expandedProjects: {},
      selectedProjectKey: null,
      selectedSessionId: null,
    };
    const calls: Array<{ method: string; params: JsonObject }> = [];
    let eventListener: ((event: AgentEvent) => void) | null = null;
    let terminalStatusPoll = false;
    let terminalStatusCalls = 0;
    const api: DesktopApi = {
      openProject: async () => null,
      openProjectInExplorer: async () => undefined,
      copySessionId: async () => undefined,
      closeShell: async () => undefined,
      requestRuntime: async (method, params) => {
        calls.push({ method, params });
        if (method === "command.execute") return { ui_action: { type: "command_executed" }, output: "compact complete" };
        if (method === "status.get") {
          if (terminalStatusPoll) {
            const active = terminalStatusCalls < 2;
            terminalStatusCalls += 1;
            return { active_turn: active, application: { current_model: "local/chat", context_status: { used_tokens: 12, budget_tokens: 100, available: true, measurement: "estimate", source: "application" }, compaction_status: { state: "completed", trigger: "manual", changed: true } } };
          }
          return { active_turn: false, application: { current_model: "local/chat", context_status: { used_tokens: 12, budget_tokens: 100, available: true, measurement: "estimate", source: "application" }, compaction_status: { state: "completed", trigger: "manual", changed: true } } };
        }
        return {};
      },
      subscribeAgentEvents: (listener) => { eventListener = listener; return () => { eventListener = null; }; },
      readPreference: async (key) => preferences[key],
      writePreference: async () => preferences,
    };
    const state = createInitialState({ composerText: "/compact", commandCandidates: [], language: "en", run: { run_id: "run-1" }, activeTurn: true, turnStatus: "running" });
    act(() => { root.render(<App initialState={state} api={api} />); });
    const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0));
    await act(async () => { await tick(); await tick(); });
    const send = container.querySelector<HTMLButtonElement>(".composer-actions button:last-child");
    assert.ok(send);
    act(() => { send!.click(); });
    await act(async () => { await tick(); await tick(); });
    assert.equal(calls.filter((call) => call.method === "command.execute").length, 1);
    assert.equal(calls.filter((call) => call.method === "turn.start").length, 0, "direct slash commands must not become turn.start prompts");
    const statusAfterCommand = calls.filter((call) => call.method === "status.get").length;
    assert.ok(statusAfterCommand >= 1, "command completion should refresh the Application status projection");

    act(() => { eventListener?.({ type: "assistant_message_delta", run_id: "run-1", turn_id: "turn-1", message_id: "message-1", text: "delta" }); });
    await act(async () => { await tick(); });
    assert.equal(calls.filter((call) => call.method === "status.get").length, statusAfterCommand, "streaming deltas must not poll status");
    terminalStatusPoll = true;
    act(() => { eventListener?.({ type: "turn_completed", run_id: "run-1", turn_id: "turn-1", final_text: "done" }); });
    await act(async () => { await tick(); });
    assert.equal(container.querySelector<HTMLTextAreaElement>(".composer textarea")?.disabled, true, "active status observations keep Composer locked");
    // The convergence backoff is 25ms then 50ms; leave a small scheduler
    // margin so the third (authoritative false) observation is deterministic
    // when the full Desktop suite runs alongside other workers.
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 160)); });
    assert.ok(terminalStatusCalls >= 3, "terminal status waits through active observations before accepting idle");
    assert.equal(container.querySelector<HTMLTextAreaElement>(".composer textarea")?.disabled, false, "only the final active_turn=false releases Composer");
  });
});

test("T08 DesktopApi JSON validation accepts shared data and rejects cycles", () => {
  const shared = { label: "shared" };
  assert.equal(isJsonValue({ first: shared, second: shared }), true, "reused JSON values are valid when they are not cyclic");
  const cyclic: Record<string, unknown> = {};
  cyclic.self = cyclic;
  assert.equal(isJsonValue(cyclic), false, "a recursive back-edge is not valid JSON");
});

test("T05 terminal convergence retries transient failures with backoff past one wait window", async () => {
  await withRendererDom(async (_dom, container, root) => {
    const responses = ["error", "active", "active", "active", "active", "idle"] as const;
    let statusCalls = 0;
    let eventListener: ((event: AgentEvent) => void) | null = null;
    const api: DesktopApi = {
      openProject: async () => null,
      openProjectInExplorer: async () => undefined,
      copySessionId: async () => undefined,
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
      copySessionId: async () => undefined,
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
      copySessionId: async () => undefined,
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
      copySessionId: async () => undefined,
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
      copySessionId: async () => undefined,
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
    assert.equal(statusCalls, 2, "the buffered terminal poll reaches authoritative false");
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
      copySessionId: async () => undefined,
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

test("T05 narrow viewport structure keeps Sidebar visible and reopens hidden Runtime as a drawer", async () => {
  await withRendererDom(async (dom, container, root) => {
    Object.defineProperty(dom.window, "innerWidth", { configurable: true, value: 533 });
    const project: ProjectState = { path: "C:/narrow", projectKey: "C:/narrow", alias: "Narrow", pinned: false, sessions: [], catalogFresh: true };
    act(() => { root.render(<App initialState={createInitialState({ language: "en", theme: "dark", projects: [project], selectedProjectKey: project.projectKey })} api={undefined} />); });
    const shell = container.querySelector<HTMLElement>(".app-shell");
    assert.ok(shell);
    assert.ok(container.querySelector(".sidebar"), "navigation remains available at 533 CSS px");
    const toggle = container.querySelector<HTMLButtonElement>(".conversation-actions button");
    assert.ok(toggle);
    assert.equal(toggle?.getAttribute("aria-controls"), "runtime-panel");
    assert.equal(toggle?.getAttribute("aria-expanded"), "false");
    assert.equal(toggle?.getAttribute("aria-label"), "Open Runtime panel");
    assert.equal(toggle?.querySelector(".sr-only")?.textContent, "Runtime panel closed");
    act(() => { toggle!.click(); });
    assert.ok(shell!.classList.contains("panel-floating"), "docked Runtime switches directly to an overlay on narrow viewports");
    const drawer = container.querySelector<HTMLElement>(".runtime-panel--floating");
    assert.ok(drawer);
    const drawerTrigger = drawer?.querySelector<HTMLButtonElement>(".custom-select__trigger");
    assert.equal(dom.window.document.activeElement, drawerTrigger, "opening the Runtime drawer moves focus into it");
    assert.equal(toggle?.getAttribute("aria-expanded"), "true");
    assert.equal(toggle?.getAttribute("aria-label"), "Close Runtime panel");
    assert.equal(toggle?.querySelector(".sr-only")?.textContent, "Runtime panel open");
    const escape = new dom.window.KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
    act(() => { drawerTrigger?.dispatchEvent(escape); });
    assert.equal(escape.defaultPrevented, true);
    assert.ok(shell!.classList.contains("panel-hidden"));
    assert.equal(toggle?.getAttribute("aria-expanded"), "false");
    assert.equal(dom.window.document.activeElement, toggle, "Escape closes the drawer and restores toggle focus");
    act(() => { toggle!.click(); });
    assert.ok(container.querySelector(".runtime-panel--floating"), "hidden Runtime remains reopenable from the conversation bar");
    const reopened = container.querySelector<HTMLElement>(".runtime-panel--floating");
    assert.equal(dom.window.document.activeElement, reopened?.querySelector(".custom-select__trigger"));
    act(() => { dom.window.document.body.dispatchEvent(new dom.window.Event("pointerdown", { bubbles: true })); });
    assert.ok(shell!.classList.contains("panel-hidden"), "outside pointer closes the Runtime drawer");
    assert.equal(dom.window.document.activeElement, toggle, "outside close restores toggle focus");
  });
});

test("T05 Runtime drawer restores focus when a wide docked panel becomes hidden at narrow width", async () => {
  await withRendererDom(async (dom, container, root) => {
    Object.defineProperty(dom.window, "innerWidth", { configurable: true, value: 1100 });
    act(() => { root.render(<App initialState={createInitialState({ language: "en", panelMode: "docked" })} api={undefined} />); });
    const toggle = container.querySelector<HTMLButtonElement>(".conversation-actions button");
    const runtime = container.querySelector<HTMLElement>("#runtime-panel");
    assert.ok(toggle);
    assert.ok(runtime);
    const runtimeTrigger = runtime?.querySelector<HTMLButtonElement>(".custom-select__trigger");
    runtimeTrigger?.focus();
    Object.defineProperty(dom.window, "innerWidth", { configurable: true, value: 533 });
    act(() => { dom.window.dispatchEvent(new dom.window.Event("resize")); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    assert.equal(toggle?.getAttribute("aria-expanded"), "false");
    assert.equal(runtime?.getAttribute("aria-hidden"), "true");
    assert.equal(dom.window.document.activeElement, toggle, "responsive hiding restores focus instead of leaving it in the hidden panel");
  });
});

test("T06 responsive Runtime error owner handoff preserves focus across a real resize", async () => {
  await withRendererDom(async (dom, container, root) => {
    Object.defineProperty(dom.window, "innerWidth", { configurable: true, value: 680 });
    const error = translate("en", "runtimeStartFailed");
    act(() => {
      root.render(<App initialState={createInitialState({ language: "en", panelMode: "docked", runtimeState: "configuration_required", runtimeError: error, notice: error })} api={undefined} />);
    });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    const timelineError = container.querySelector<HTMLElement>(".timeline-runtime-error");
    const openSettings = timelineError?.querySelector<HTMLButtonElement>("button");
    const toggle = container.querySelector<HTMLButtonElement>(".conversation-actions button");
    assert.ok(timelineError && openSettings && toggle);
    assert.equal(container.querySelector("#runtime-panel")?.getAttribute("aria-hidden"), "true");
    act(() => { openSettings!.focus(); });
    assert.equal(dom.window.document.activeElement, openSettings);

    Object.defineProperty(dom.window, "innerWidth", { configurable: true, value: 760 });
    act(() => { dom.window.dispatchEvent(new dom.window.Event("resize")); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });

    assert.equal(container.querySelector(".timeline-runtime-error"), null, "wide docked Runtime becomes the sole error owner");
    assert.equal(container.querySelector("#runtime-panel")?.getAttribute("aria-hidden"), null);
    assert.equal(container.querySelectorAll<HTMLElement>("[data-runtime-error-owner]").length, 1);
    assert.equal(dom.window.document.activeElement, toggle, "owner handoff restores focus to the stable Runtime toggle");
    assert.equal(toggle?.getAttribute("aria-expanded"), "true");
  });
});

test("T05 wide floating Runtime keeps its three-state layout without drawer dismissal", async () => {
  await withRendererDom(async (dom, container, root) => {
    Object.defineProperty(dom.window, "innerWidth", { configurable: true, value: 1100 });
    const before = dom.window.document.getElementById("before");
    before?.focus();
    act(() => { root.render(<App initialState={createInitialState({ language: "en", panelMode: "floating" })} api={undefined} />); });
    const shell = container.querySelector<HTMLElement>(".app-shell");
    const toggle = container.querySelector<HTMLButtonElement>(".conversation-actions button");
    const runtime = container.querySelector<HTMLElement>("#runtime-panel");
    assert.ok(shell);
    assert.ok(runtime);
    assert.equal(shell?.classList.contains("panel-floating"), true);
    assert.equal(toggle?.getAttribute("aria-expanded"), "true");
    assert.equal(dom.window.document.activeElement, before, "wide floating layout does not steal focus as a drawer");

    const escape = new dom.window.KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
    act(() => { dom.window.document.body.dispatchEvent(escape); });
    act(() => { dom.window.document.body.dispatchEvent(new dom.window.Event("pointerdown", { bubbles: true })); });
    assert.equal(escape.defaultPrevented, false, "wide floating layout does not consume global Escape");
    assert.equal(shell?.classList.contains("panel-floating"), true, "wide floating layout remains visible after workspace pointerdown");
    assert.equal(toggle?.getAttribute("aria-expanded"), "true");
    assert.equal(runtime?.getAttribute("aria-hidden"), null);
  });
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

test("T08 reducer rejects stale same-Run events from an older Turn", () => {
  const current = createInitialState({
    activeTurn: true,
    turnStatus: "running",
    run: { run_id: "run-1", turn_id: "turn-2", status: "running" },
    todo: [{ content: "current task", status: "in_progress" }],
    todoIteration: 3,
  });
  const staleEvents = [
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
  const event = (payload: Record<string, unknown>) => ({ type: "agent_event" as const, event: payload });
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

test("T05 failed and cancelled turns discard incomplete assistant previews", () => {
  let state = createInitialState();
  state = reduceRendererState(state, { type: "agent_event", event: { type: "assistant_message_delta", run_id: "run-1", turn_id: "turn-1", message_id: "answer-1", iteration: 1, text: "unfinished" } });
  state = reduceRendererState(state, { type: "agent_event", event: { type: "turn_failed", run_id: "run-1", turn_id: "turn-1", termination_reason: "provider_error", failure_reason: "provider_request" } });
  assert.equal(state.timeline.some((entry) => entry.text === "unfinished"), false);
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
  assert.match(markup, /查看或切换当前模型/);
  assert.match(markup, /id="composer-state"[^>]*role="status"[^>]*aria-live="polite"/u);
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

test("T06 PlanContentDelta uses iteration identity and PlanProposed seals the matching draft", () => {
  let state = createInitialState();
  const event = (payload: Record<string, unknown>) => ({ type: "agent_event" as const, event: payload });
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
  const event = (payload: Record<string, unknown>) => ({ type: "agent_event" as const, event: payload });
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
    const event = (payload: Record<string, unknown>) => ({ type: "agent_event" as const, event: payload });
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
  const event = (payload: Record<string, unknown>) => ({ type: "agent_event" as const, event: payload });
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

test("T06 tool DOM rows expose one status entity with icon, text, ARIA, and frozen elapsed", async () => {
  await withRendererDom(async (_dom, container, root) => {
    const startedAt = Date.now() - 5000;
    const renderTimeline = (entry: Parameters<typeof ChatTimeline>[0]["entries"]) => {
      act(() => { root.render(<LanguageProvider value="en"><ChatTimeline entries={entry} todo={[]} /></LanguageProvider>); });
    };
    renderTimeline([{ id: "tool-row", kind: "tool", text: "Bash summary", toolName: "Bash", status: "running", streaming: false, startedAt }]);
    const running = container.querySelector<HTMLElement>(".timeline-entry--tool");
    assert.ok(running);
    assert.equal(running?.getAttribute("aria-busy"), "true");
    assert.equal(running?.querySelector<HTMLElement>('[data-status="running"]')?.textContent?.includes("running"), true);
    assert.ok(running?.querySelector(".tool-status .ui-icon"));
    assert.ok(running?.querySelector(".tool-elapsed"));
    const initialElapsed = Number.parseInt(running?.querySelector(".tool-elapsed")?.textContent?.replace(/\D/gu, "") ?? "0", 10);
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 1050)); });
    const laterElapsed = Number.parseInt(container.querySelector(".tool-elapsed")?.textContent?.replace(/\D/gu, "") ?? "0", 10);
    assert.ok(laterElapsed > initialElapsed, "running elapsed must continue increasing");
    renderTimeline([{ id: "tool-row", kind: "tool", text: "Bash summary", toolName: "Bash", status: "completed", streaming: false, startedAt, endedAt: startedAt + 3000 }]);
    const completed = container.querySelector<HTMLElement>(".timeline-entry--tool");
    assert.equal(container.querySelectorAll(".timeline-entry--tool").length, 1);
    assert.equal(completed?.getAttribute("aria-busy"), null);
    assert.equal(completed?.querySelector<HTMLElement>('[data-status="completed"]')?.textContent?.includes("completed"), true);
    assert.match(completed?.querySelector(".tool-elapsed")?.textContent ?? "", /3s/u);
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 20)); });
    assert.match(container.querySelector(".tool-elapsed")?.textContent ?? "", /3s/u, "terminal elapsed remains frozen");
    for (const status of ["failed", "cancelled"] as const) {
      renderTimeline([{ id: `tool-${status}`, kind: "tool", text: "Bash summary", toolName: "Bash", status, streaming: false, startedAt, endedAt: startedAt + 4000, isError: status === "failed" }]);
      const terminal = container.querySelector<HTMLElement>(".timeline-entry--tool");
      assert.equal(terminal?.querySelector<HTMLElement>(`[data-status="${status}"]`) !== null, true);
      assert.match(terminal?.getAttribute("aria-label") ?? "", new RegExp(status, "iu"));
      assert.ok(terminal?.querySelector(".tool-status .ui-icon"));
    }
  });
});

test("T06 Todo strip exposes status text and one compact focusable visual entity", async () => {
  const markup = renderLanguage("en", <ChatTimeline entries={[]} todo={[{ content: "one", status: "in_progress" }, { content: "two", status: "completed" }]} />);
  assert.match(markup, /class="todo-strip"[^>]*tabindex="0"/);
  assert.match(markup, /aria-label="Tasks"/);
  assert.match(markup, /aria-label="one: in progress"/);
  assert.match(markup, /aria-label="two: completed"/);
  assert.match(markup, /ui-icon/);
  const css = await (await import("node:fs/promises")).readFile(new URL("../src/renderer/app.css", import.meta.url), "utf8");
  assert.match(css, /\.todo-strip:hover, \.todo-strip:focus, \.todo-strip:focus-within\s*\{[^}]*max-height:/u);
});

test("T06 pending interaction blocks Composer commands and keeps typed control identity", () => {
  const pending = createInitialState({ composerText: "/model", activeTurn: true, turnStatus: "paused", pendingInteraction: { kind: "user_requested", pauseId: "p", runId: "r", turnId: "t" }, commandCandidates: [{ value: "/model", description: "model" }] });
  const markup = renderToStaticMarkup(<Composer state={pending} onChange={() => undefined} onSubmit={() => undefined} onCommand={() => undefined} onPause={() => undefined} onCancel={() => undefined} />);
  assert.match(markup, /等待中/);
  assert.doesNotMatch(markup, /role="listbox"/u);
  assert.doesNotMatch(markup, />引导</u);
});

test("T05 terminal status pending keeps Composer locked until Application idle", () => {
  const pending = createInitialState({ composerText: "continue", activeTurn: true, terminalStatusPending: true, turnStatus: "completed" });
  const markup = renderLanguage("en", <Composer state={pending} onChange={() => undefined} onSubmit={() => undefined} onCommand={() => undefined} onPause={() => undefined} onCancel={() => undefined} />);
  assert.match(markup, /<textarea[^>]*disabled=""/u);
  assert.match(markup, /title="Waiting"[^>]*disabled=""/u);
  assert.doesNotMatch(markup, /title="Cancel"/u);
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

test("T08 Interaction Surface submits one response and blocks cancel while submitting", async () => {
  await withRendererDom(async (dom, container, root) => {
    const submitted: JsonObject[] = [];
    let cancelled = 0;
    const interaction = { kind: "permission_required", pauseId: "pause-submit", runId: "run-submit", turnId: "turn-submit", request: { permission_id: "permission", choices: ["once", "reject"] } } as const;
    act(() => {
      root.render(<LanguageProvider value="en"><InteractionSurface interaction={interaction} onSubmit={(response) => submitted.push(response)} onCancel={() => { cancelled += 1; }} /></LanguageProvider>);
    });
    const allow = container.querySelector<HTMLButtonElement>('button[title="Allow once"]');
    assert.ok(allow);
    act(() => { allow!.click(); allow!.click(); });
    assert.equal(submitted.length, 1, "rapid duplicate clicks keep one typed resume request");
    const escape = new dom.window.KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
    act(() => { container.querySelector<HTMLElement>('[role="dialog"]')?.dispatchEvent(escape); });
    assert.equal(escape.defaultPrevented, true);
    assert.equal(cancelled, 0, "Escape cannot race an in-flight response");
  });
});

test("T06 Interaction Surface exposes AskUser controls and preserves its DOM flow", async () => {
  const inputInteraction = { kind: "user_input_required", pauseId: "pause-1", runId: "run-1", turnId: "turn-1", toolCallId: "call-1", request: { questions: [{ question_id: "q1", header: "Name", question: "Your name?", kind: "text" }, { question_id: "q2", header: "Color", question: "Pick", kind: "single_select", options: [{ label: "Red", description: "warm" }, { label: "Blue", description: "cool" }] }] } } as const;
  const inputMarkup = renderToStaticMarkup(<InteractionSurface interaction={inputInteraction} onSubmit={() => undefined} onCancel={() => undefined} />);
  assert.match(inputMarkup, /Your name\?/);
  assert.match(inputMarkup, /下一步/);
  assert.match(inputMarkup, /取消轮次/);
  const singleMarkup = renderLanguage("en", <InteractionSurface interaction={{ ...inputInteraction, request: { questions: [inputInteraction.request.questions[1]] } }} onSubmit={() => undefined} onCancel={() => undefined} />);
  assert.match(singleMarkup, /Color Provide another answer/);
  const planInteraction = { kind: "plan_review_required", pauseId: "pause-2", runId: "run-1", turnId: "turn-1", request: { revision: 3, plan_text: "Step one\nStep two" } } as const;
  const planMarkup = renderLanguage("en", <InteractionSurface interaction={planInteraction} onSubmit={() => undefined} onCancel={() => undefined} />);
  assert.match(planMarkup, /Revision 3/);
  assert.match(planMarkup, /Approve and execute/);
  assert.match(planMarkup, /Revision feedback/);
  const multiMarkup = renderLanguage("en", <InteractionSurface interaction={{ ...inputInteraction, request: { questions: [{ question_id: "q1", header: "Tags", question: "Pick tags", kind: "multi_select", options: [{ label: "One", description: "first" }, { label: "Two", description: "second" }] }] } }} onSubmit={() => undefined} onCancel={() => undefined} />);
  assert.match(multiMarkup, /Pick tags/);
  assert.match(multiMarkup, /Tags Provide another answer/);
  const fourQuestionMarkup = renderLanguage("en", <InteractionSurface interaction={{ ...inputInteraction, request: { questions: [...inputInteraction.request.questions, { question_id: "extra", header: "Extra", question: "One more answer", kind: "text" }, { question_id: "last", header: "Last", question: "Final answer", kind: "text" }] } }} onSubmit={() => undefined} onCancel={() => undefined} />);
  assert.match(fourQuestionMarkup, /1 \/ 4/);
  assert.doesNotMatch(fourQuestionMarkup, /Back to chat|返回聊天/u);
  await withRendererDom(async (dom, container, root) => {
    const submitted: unknown[] = [];
    const cancelled: string[] = [];
    const inputInteraction = {
      kind: "user_input_required",
      pauseId: "pause-dom",
      runId: "run-dom",
      turnId: "turn-dom",
      toolCallId: "call-dom",
      request: {
        questions: [
          {
            question_id: "mode",
            header: "Mode",
            question: "Choose a mode",
            kind: "single_select",
            options: [
              { label: "Fast", description: "Fast mode" },
              { label: "Safe", description: "Safe mode" },
            ],
          },
          {
            question_id: "tags",
            header: "Tags",
            question: "Choose tags",
            kind: "multi_select",
            options: [
              { label: "One", description: "First tag" },
              { label: "Two", description: "Second tag" },
            ],
          },
          {
            question_id: "details",
            header: "Details",
            question: "Add details",
            kind: "text",
          },
        ],
      },
    } as const;
    const renderInteraction = async (interaction: typeof inputInteraction) => {
      act(() => {
        root.render(
          <LanguageProvider value="en">
            <InteractionSurface
              interaction={interaction}
              onSubmit={(response) => submitted.push(response)}
              onCancel={() => cancelled.push(interaction.pauseId)}
            />
          </LanguageProvider>,
        );
      });
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
    };
    const clickButton = async (title: string) => {
      const button = container.querySelector<HTMLButtonElement>(`button[title="${title}"]`);
      assert.ok(button, `button ${title} should be present`);
      act(() => { button!.click(); });
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
    };
    const setInputValue = async (input: HTMLInputElement, value: string) => {
      const setter = Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, "value")?.set;
      assert.ok(setter, "JSDOM input value setter should be available");
      act(() => {
        setter!.call(input, value);
        input.dispatchEvent(new dom.window.InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
        input.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
        // React is imported before the JSDOM window in this suite, so its legacy input fallback observes keyup for controlled fields.
        input.dispatchEvent(new dom.window.KeyboardEvent("keyup", { bubbles: true, key: "Unidentified" }));
      });
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
    };
    const freeInput = (header: string) => {
      const input = container.querySelector<HTMLInputElement>(`input[aria-label="${header} Provide another answer"]`);
      assert.ok(input, `${header} free input should be present`);
      return input!;
    };

    await renderInteraction(inputInteraction);
    const modeOptions = Array.from(container.querySelectorAll<HTMLInputElement>('input[name="mode"]'));
    assert.equal(modeOptions.length, 2);
    act(() => { modeOptions[0]!.click(); });
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
    assert.equal(modeOptions[0]!.checked, true);
    await clickButton("Next");

    const tagOptions = Array.from(container.querySelectorAll<HTMLInputElement>('input[name="tags"]'));
    assert.equal(tagOptions.length, 2);
    act(() => { tagOptions[0]!.click(); });
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
    assert.equal(tagOptions[0]!.checked, true);
    await setInputValue(freeInput("Tags"), "custom-tag");
    await clickButton("Previous");
    assert.equal(container.querySelector<HTMLInputElement>('input[name="mode"]')?.checked, true, "previous single option should survive navigation");
    await setInputValue(freeInput("Mode"), "custom-mode");
    assert.equal(freeInput("Mode").value, "custom-mode");
    await clickButton("Next");
    assert.equal(tagOptions[0]!.checked, true, "previous multi option should survive navigation");
    assert.equal(freeInput("Tags").value, "custom-tag", "previous multi free text should survive navigation");
    await clickButton("Next");

    const details = container.querySelector<HTMLInputElement>('input[aria-label="Details"]');
    assert.ok(details);
    await setInputValue(details!, "details");
    await clickButton("Previous");
    assert.equal(freeInput("Tags").value, "custom-tag");
    await clickButton("Next");
    assert.equal(container.querySelector<HTMLInputElement>('input[aria-label="Details"]')?.value, "details");
    await clickButton("Review");
    assert.match(container.querySelector<HTMLElement>(".answer-review")?.textContent ?? "", /custom-mode/);
    assert.match(container.querySelector<HTMLElement>(".answer-review")?.textContent ?? "", /One, custom-tag/);
    assert.match(container.querySelector<HTMLElement>(".answer-review")?.textContent ?? "", /details/);
    const editAnswers = container.querySelector<HTMLButtonElement>('button[title="Edit answers"]');
    assert.ok(editAnswers);
    assert.equal(dom.window.document.activeElement, editAnswers, "entering Review moves focus to its first action");
    await clickButton("Edit answers");
    assert.equal(dom.window.document.activeElement, container.querySelector<HTMLInputElement>('input[aria-label="Details"]'), "returning to the last question restores focus inside that question");
    await clickButton("Review");
    assert.equal(dom.window.document.activeElement, container.querySelector<HTMLButtonElement>('button[title="Edit answers"]'), "re-entering Review restores its first action focus");
    await clickButton("Submit answers");
    assert.equal(submitted.length, 1, "AskUser should submit exactly once");
    assert.deepEqual(submitted[0], {
      type: "user_input",
      pause_id: "pause-dom",
      run_id: "run-dom",
      turn_id: "turn-dom",
      tool_call_id: "call-dom",
      answers: {
        mode: ["custom-mode"],
        tags: ["One", "custom-tag"],
        details: ["details"],
      },
    });

    const escapeInteraction = { ...inputInteraction, pauseId: "pause-escape" };
    await renderInteraction(escapeInteraction);
    const askDialog = container.querySelector<HTMLElement>('[role="dialog"]');
    assert.ok(askDialog);
    const askEscape = new dom.window.KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
    act(() => { askDialog!.dispatchEvent(askEscape); });
    assert.equal(askEscape.defaultPrevented, true, "AskUser Escape remains a typed cancel path");
    assert.deepEqual(cancelled, ["pause-escape"], "AskUser Escape preserves its pending pause identity");

    const cancelInteraction = { ...inputInteraction, pauseId: "pause-cancel" };
    await renderInteraction(cancelInteraction);
    await clickButton("Cancel turn");
    assert.deepEqual(cancelled, ["pause-escape", "pause-cancel"], "Escape and button cancel should retain each pending pause identity");
  });
});

test("T06 modal traps Tab focus, inerts background, restores focus, and handles Escape", async () => {
  await withRendererDom(async (dom, container, root) => {
    const before = dom.window.document.getElementById("before") as HTMLButtonElement;
    const after = dom.window.document.getElementById("after") as HTMLButtonElement;
    before.focus();
    let cancelled = 0;
    const interaction = { kind: "permission_required", pauseId: "pause-modal", runId: "run-modal", turnId: "turn-modal", request: { choices: ["once", "reject"] } } as const;
    act(() => {
      root.render(<LanguageProvider value="en"><InteractionSurface interaction={interaction} onSubmit={() => undefined} onCancel={() => { cancelled += 1; }} /></LanguageProvider>);
    });
    const dialog = container.querySelector<HTMLElement>('[role="dialog"]');
    assert.ok(dialog);
    assert.equal(dialog?.getAttribute("aria-modal"), "true");
    assert.equal((before as HTMLElement & { inert?: boolean }).inert, true);
    assert.equal((after as HTMLElement & { inert?: boolean }).inert, true);
    assert.equal(before.getAttribute("aria-hidden"), "true");
    const buttons = Array.from(dialog!.querySelectorAll<HTMLButtonElement>("button"));
    assert.equal(buttons.length, 2);
    buttons[1]!.focus();
    const tab = new dom.window.KeyboardEvent("keydown", { key: "Tab", bubbles: true, cancelable: true });
    act(() => { buttons[1]!.dispatchEvent(tab); });
    assert.equal(tab.defaultPrevented, true);
    assert.equal(dom.window.document.activeElement, buttons[0]);
    buttons[0]!.focus();
    const shiftTab = new dom.window.KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true, cancelable: true });
    act(() => { buttons[0]!.dispatchEvent(shiftTab); });
    assert.equal(shiftTab.defaultPrevented, true);
    assert.equal(dom.window.document.activeElement, buttons[1]);
    const escape = new dom.window.KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true });
    act(() => { buttons[0]!.dispatchEvent(escape); });
    assert.equal(escape.defaultPrevented, true);
    assert.equal(cancelled, 1);
    act(() => { root.render(<button id="restored" type="button">Restored</button>); });
    assert.equal(dom.window.document.activeElement, before);
    assert.equal((before as HTMLElement & { inert?: boolean }).inert, false);
    assert.equal(before.getAttribute("aria-hidden"), null);
  });
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
  const markup = renderToStaticMarkup(<SettingsView state={state} onRevealApiKey={undefined} onBack={() => undefined} onSave={() => undefined} onThemeChange={() => undefined} onLanguageChange={() => undefined} />);
  assert.match(markup, /协议与模型|默认项|界面|关于/);
  assert.match(markup, />Model</);
  assert.doesNotMatch(markup, /sk-live-secret|api_key=|secret value/u);
});

test("T07 rebuilt Settings and typed interactions keep accessible continuous and narrow layouts", async () => {
  const state = createInitialState({ runtimeState: "ready", theme: "light", configuration: { default_model: "fake/model", default_permission_mode: "default", providers: { fake: { kind: "fake", api_key_configured: true } }, models: { "fake/model": { provider_profile_id: "fake", remote_id: "model" } } }, settingsLoaded: true });
  const settingsMarkup = renderToStaticMarkup(<SettingsView state={state} onRevealApiKey={undefined} onBack={() => undefined} onSave={() => undefined} onThemeChange={() => undefined} onLanguageChange={() => undefined} />);
  assert.match(settingsMarkup, /aria-label="设置"/u);
  for (const id of ["providers", "defaults", "interface", "about"]) {
    assert.match(settingsMarkup, new RegExp(`href="#settings-${id}"`));
    assert.match(settingsMarkup, new RegExp(`id="settings-${id}"`));
  }
  assert.doesNotMatch(settingsMarkup, /aria-current=/u);
  assert.match(settingsMarkup, /class="provider-row"[^>]*fake/u);
  assert.match(settingsMarkup, />model</u);
  assert.match(settingsMarkup, /API Key 已保存/u);
  assert.doesNotMatch(settingsMarkup, /已配置/u);
  assert.doesNotMatch(settingsMarkup, /<select|legacy-settings-editor/u);
  const permission = { kind: "permission_required", pauseId: "pause-a11y", runId: "run-a11y", turnId: "turn-a11y", request: { permission_id: "permission-a11y", choices: ["once", "reject"] } } as const;
  const interactionMarkup = renderLanguage("en", <InteractionSurface interaction={permission} onSubmit={() => undefined} onCancel={() => undefined} />);
  assert.match(interactionMarkup, /aria-label="Permission approval"/u);
  assert.match(interactionMarkup, /type="button"/u);
  const css = await (await import("node:fs/promises")).readFile(new URL("../src/renderer/app.css", import.meta.url), "utf8");
  assert.match(css, /\.settings-view\s*\{[^}]*grid-template-columns:\s*var\(--sidebar-width, 220px\) minmax\(0, 1fr\)/s);
  assert.match(css, /\.settings-section\s*\{[^}]*border-top:\s*1px solid var\(--line\)/s);
  assert.match(css, /@media \(max-width:\s*900px\)[\s\S]*?\.settings-view\s*\{[^}]*grid-template-columns:\s*1fr/s);
  assert.match(css, /settings-modal-rise|settings-modal-fade/u);
  assert.match(css, /prefers-reduced-motion/u);
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

test("T07 saved API key reveal is explicit, transient, and cleared with the protocol modal", async () => {
  await withRendererDom(async (dom, container, root) => {
    const calls: Array<{ method: string; params: unknown }> = [];
    const saves: ConfigurationWrite[] = [];
    const onRevealApiKey = async (providerId: string) => {
        const method = "settings.reveal_api_key";
        const params = { provider_profile_id: providerId };
        calls.push({ method, params });
        return "env:W04_RENDERER_TEST_KEY";
      };
    const state = createInitialState({ configuration: { default_model: "provider/model", default_permission_mode: "default", providers: { provider: { kind: "openai_compat", api_key_configured: true } }, models: { "provider/model": { provider_profile_id: "provider", remote_id: "remote-model", display_name: "Model" } } }, settingsLoaded: true });
    const render = () => act(() => { root.render(<LanguageProvider value="en"><SettingsView state={state} onRevealApiKey={onRevealApiKey} onBack={() => undefined} onSave={(request) => { saves.push(request); }} onThemeChange={() => undefined} onLanguageChange={() => undefined} /></LanguageProvider>); });
    const tick = async () => { await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); }); };
    render();
    await tick();
    const row = container.querySelector<HTMLButtonElement>(".provider-row");
    assert.ok(row);
    act(() => { row!.click(); });
    await tick();
    const input = container.querySelector<HTMLInputElement>("#modal-api-key");
    const show = container.querySelector<HTMLButtonElement>('button[aria-label="Show saved API key"]');
    assert.ok(input);
    assert.ok(show);
    assert.equal(input!.type, "password");
    act(() => { show!.click(); });
    await tick();
    assert.deepEqual(calls, [{ method: "settings.reveal_api_key", params: { provider_profile_id: "provider" } }]);
    assert.equal(input!.type, "text");
    assert.equal(input!.value, "env:W04_RENDERER_TEST_KEY");
    assert.equal(saves.length, 0, "revealing a saved key must not mark settings dirty");
    const hide = container.querySelector<HTMLButtonElement>('button[aria-label="Hide saved API key"]');
    assert.ok(hide);
    act(() => { hide!.click(); });
    await tick();
    assert.equal(input!.type, "password");
    assert.equal(saves.length, 0, "hiding a saved key must not trigger a write");
    const apply = container.querySelector<HTMLButtonElement>('.provider-modal > footer button[title="Apply"]');
    assert.ok(apply);
    act(() => { apply!.click(); });
    await tick();
    const save = container.querySelector<HTMLButtonElement>(".settings-actions .save-button");
    assert.ok(save);
    act(() => { save!.click(); });
    await tick();
    const providerRequest = saves[0]?.providers?.provider;
    assert.ok(providerRequest);
    assert.equal(providerRequest.api_key, undefined, "the revealed value must never enter an untouched write");
    const reopened = container.querySelector<HTMLButtonElement>(".provider-row");
    assert.ok(reopened);
    act(() => { reopened!.click(); });
    await tick();
    const showAgain = container.querySelector<HTMLButtonElement>('button[aria-label="Show saved API key"]');
    assert.ok(showAgain);
    act(() => { showAgain!.click(); });
    await tick();
    assert.equal(calls.length, 2, "closing the protocol modal clears the reveal cache");
    void dom;
  });
});

test("T07 replacement key remains after a failed save and is the only key-bearing write", async () => {
  await withRendererDom(async (dom, container, root) => {
    let rejectedRequest: ConfigurationWrite | null = null;
    const onRevealApiKey = async () => null;
    const state = createInitialState({ configuration: { default_model: "provider/model", providers: { provider: { kind: "openai_compat", api_key_configured: true } }, models: { "provider/model": { provider_profile_id: "provider", remote_id: "remote-model" } } }, settingsLoaded: true });
    const onSave = (request: ConfigurationWrite) => { rejectedRequest = request; throw new Error("save rejected"); };
    const tick = async () => { await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); }); };
    act(() => { root.render(<LanguageProvider value="en"><SettingsView state={state} onRevealApiKey={onRevealApiKey} onBack={() => undefined} onSave={onSave} onThemeChange={() => undefined} onLanguageChange={() => undefined} /></LanguageProvider>); });
    await tick();
    const row = container.querySelector<HTMLButtonElement>(".provider-row");
    assert.ok(row);
    act(() => { row!.click(); });
    await tick();
    const input = container.querySelector<HTMLInputElement>("#modal-api-key");
    const setter = Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, "value")?.set;
    assert.ok(input);
    assert.ok(setter);
    act(() => {
      input!.focus();
      setter!.call(input, "replacement-only");
      input!.dispatchEvent(new dom.window.InputEvent("input", { bubbles: true, inputType: "insertText", data: "replacement-only" }));
      input!.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
      input!.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
      input!.dispatchEvent(new dom.window.KeyboardEvent("keyup", { bubbles: true, key: "Unidentified" }));
    });
    await tick();
    const apply = container.querySelector<HTMLButtonElement>('.provider-modal > footer button[title="Apply"]');
    assert.ok(apply);
    act(() => { apply!.click(); });
    await tick();
    const save = container.querySelector<HTMLButtonElement>(".settings-actions .save-button");
    assert.ok(save);
    act(() => { save!.click(); });
    await tick();
    assert.equal(rejectedRequest?.providers?.provider?.api_key, "replacement-only");
    const reopened = container.querySelector<HTMLButtonElement>(".provider-row");
    assert.ok(reopened);
    act(() => { reopened!.click(); });
    await tick();
    assert.equal(container.querySelector<HTMLInputElement>("#modal-api-key")?.value, "replacement-only", "a failed save keeps the replacement in the modal");
  });
});

test("T07 a delayed reveal response cannot repopulate a closed protocol modal", async () => {
  await withRendererDom(async (_dom, container, root) => {
    let calls = 0;
    let resolveReveal: ((value: string) => void) | null = null;
    const onRevealApiKey = async () => {
      calls += 1;
      return await new Promise<string>((resolve) => { resolveReveal = resolve; });
    };
    const state = createInitialState({ configuration: { default_model: "provider/model", providers: { provider: { kind: "openai_compat", api_key_configured: true } }, models: { "provider/model": { provider_profile_id: "provider", remote_id: "remote-model" } } }, settingsLoaded: true });
    const tick = async () => { await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); }); };
    act(() => { root.render(<LanguageProvider value="en"><SettingsView state={state} onRevealApiKey={onRevealApiKey} onBack={() => undefined} onSave={() => undefined} onThemeChange={() => undefined} onLanguageChange={() => undefined} /></LanguageProvider>); });
    await tick();
    const row = container.querySelector<HTMLButtonElement>(".provider-row");
    assert.ok(row);
    act(() => { row!.click(); });
    await tick();
    const show = container.querySelector<HTMLButtonElement>('button[aria-label="Show saved API key"]');
    assert.ok(show);
    act(() => { show!.click(); });
    await tick();
    assert.equal(calls, 1);
    const close = container.querySelector<HTMLButtonElement>('.provider-modal > header button[title="Cancel"]');
    assert.ok(close);
    act(() => { close!.click(); });
    await tick();
    assert.equal(container.querySelector('[role="dialog"]'), null);
    resolveReveal?.("env:STALE_REVEAL");
    await tick();
    const reopened = container.querySelector<HTMLButtonElement>(".provider-row");
    assert.ok(reopened);
    act(() => { reopened!.click(); });
    await tick();
    const showAgain = container.querySelector<HTMLButtonElement>('button[aria-label="Show saved API key"]');
    assert.ok(showAgain);
    act(() => { showAgain!.click(); });
    await tick();
    assert.equal(calls, 2);
    resolveReveal?.("env:FRESH_REVEAL");
    await tick();
    assert.equal(container.querySelector<HTMLInputElement>("#modal-api-key")?.value, "env:FRESH_REVEAL");
  });
});

test("T07 empty settings and model profiles use display labels without exposing internal references", async () => {
  const emptyState = createInitialState({ configuration: {}, settingsLoaded: true });
  const emptyMarkup = renderLanguage("en", <SettingsView state={emptyState} onRevealApiKey={undefined} onBack={() => undefined} onSave={() => undefined} onThemeChange={() => undefined} onLanguageChange={() => undefined} />);
  assert.match(emptyMarkup, /No protocols yet/u);
  assert.doesNotMatch(emptyMarkup, new RegExp(["model" + "-1", "modal-new-model-ref", "settings-advanced"].join("|"), "u"));
  const zhMarkup = renderLanguage("zh-CN", <SettingsView state={emptyState} onRevealApiKey={undefined} onBack={() => undefined} onSave={() => undefined} onThemeChange={() => undefined} onLanguageChange={() => undefined} />);
  assert.match(zhMarkup, /暂无协议/u);
  assert.doesNotMatch(zhMarkup, /已配置|清除 Key/u);
  const multiState = createInitialState({ configuration: { default_model: "provider/primary", providers: { provider: { kind: "openai_compat", api_key_configured: false } }, models: { "provider/primary": { provider_profile_id: "provider", remote_id: "remote-primary", display_name: "Primary" }, "provider/secondary": { provider_profile_id: "provider", remote_id: "remote-secondary", display_name: "" } } }, settingsLoaded: true });
  const multiMarkup = renderLanguage("en", <SettingsView state={multiState} onRevealApiKey={undefined} onBack={() => undefined} onSave={() => undefined} onThemeChange={() => undefined} onLanguageChange={() => undefined} />);
  assert.match(multiMarkup, /Primary/u);
  assert.match(multiMarkup, /Primary \+1/u);
  assert.doesNotMatch(multiMarkup, /provider\/primary|provider\/secondary/u);
});

test("T07 protocol model modal supports add, default, edit, delete, and focus-safe close", async () => {
  await withRendererDom(async (dom, container, root) => {
    const saves: ConfigurationWrite[] = [];
    const state = createInitialState({ configuration: { default_model: "provider/primary", providers: { provider: { kind: "openai_compat", api_key_configured: false } }, models: { "provider/primary": { provider_profile_id: "provider", remote_id: "remote-primary", display_name: "Primary" }, "provider/secondary": { provider_profile_id: "provider", remote_id: "remote-secondary", display_name: "Secondary" } } }, settingsLoaded: true });
    act(() => { root.render(<LanguageProvider value="en"><SettingsView state={state} onRevealApiKey={undefined} onBack={() => undefined} onSave={(request) => saves.push(request)} onThemeChange={() => undefined} onLanguageChange={() => undefined} /></LanguageProvider>); });
    const tick = async () => { await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); }); };
    await tick();
    const providerRow = container.querySelector<HTMLButtonElement>(".provider-row");
    assert.ok(providerRow);
    providerRow!.focus();
    act(() => { providerRow!.click(); });
    await tick();
    const providerDialog = () => container.querySelector<HTMLElement>('.provider-modal[aria-labelledby$="protocol-title"]');
    assert.equal(container.querySelectorAll(".settings-model-row").length, 2);
    assert.ok(providerDialog());
    assert.equal((dom.window.document.activeElement as HTMLElement)?.id, "modal-protocol");
    const editSecondary = container.querySelector<HTMLButtonElement>('button[aria-label="Edit model Secondary"]');
    assert.ok(editSecondary);
    act(() => { editSecondary!.click(); });
    await tick();
    const modelDialog = container.querySelector<HTMLElement>(".model-modal");
    assert.ok(modelDialog);
    assert.equal(modelDialog!.getAttribute("aria-modal"), "true");
    assert.equal(providerDialog()!.getAttribute("aria-hidden"), "true", "the covered Provider modal is hidden from the accessibility tree");
    assert.equal(providerDialog()!.getAttribute("aria-modal"), null, "only the top-level nested modal is aria-modal");
    assert.equal((providerDialog() as HTMLElement & { inert?: boolean }).inert, true, "the covered Provider modal is inert");
    assert.equal(container.querySelectorAll('[role="dialog"][aria-modal="true"]').length, 1);
    assert.doesNotMatch(modelDialog!.textContent ?? "", /provider\/secondary|__uthcode_model_/u);
    const modalFocusable = Array.from(modelDialog!.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), [role="button"]:not([aria-disabled="true"])'));
    assert.ok(modalFocusable.length > 2);
    modalFocusable.at(-1)!.focus();
    act(() => { dom.window.document.dispatchEvent(new dom.window.KeyboardEvent("keydown", { bubbles: true, key: "Tab" })); });
    assert.equal(dom.window.document.activeElement, modalFocusable[0], "Tab wraps within the nested modal");
    modalFocusable[0]!.focus();
    act(() => { dom.window.document.dispatchEvent(new dom.window.KeyboardEvent("keydown", { bubbles: true, key: "Tab", shiftKey: true })); });
    assert.equal(dom.window.document.activeElement, modalFocusable.at(-1), "Shift+Tab wraps within the nested modal");
    const cancelModel = modelDialog!.querySelector<HTMLButtonElement>('button[title="Cancel"]');
    assert.ok(cancelModel);
    const makeDefault = modelDialog!.querySelector<HTMLInputElement>('input[type="checkbox"]');
    assert.ok(makeDefault);
    assert.equal(makeDefault!.checked, false);
    act(() => { makeDefault!.click(); });
    assert.equal(makeDefault!.checked, true);
    act(() => { dom.window.document.dispatchEvent(new dom.window.KeyboardEvent("keydown", { bubbles: true, key: "Escape" })); });
    await tick();
    assert.equal(container.querySelector(".model-modal"), null);
    assert.equal(dom.window.document.activeElement, editSecondary, "Escape restores focus to the model row that opened the modal");
    const saveBeforeAdd = container.querySelector<HTMLButtonElement>(".settings-actions .save-button");
    assert.ok(saveBeforeAdd);
    act(() => { saveBeforeAdd!.click(); });
    await tick();
    assert.equal(saves.at(-1)?.default_model, "provider/primary", "Cancel restores default_model before global Save");
    const addModel = providerDialog()!.querySelector<HTMLButtonElement>('button[title="Add model"]');
    assert.ok(addModel);
    act(() => { addModel!.click(); });
    await tick();
    const newModelDialog = container.querySelector<HTMLElement>(".model-modal");
    assert.ok(newModelDialog);
    assert.match(newModelDialog!.textContent ?? "", /Unnamed model/u);
    const remoteInput = newModelDialog!.querySelector<HTMLInputElement>('input[id$="-remote"]');
    assert.ok(remoteInput);
    const setter = Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, "value")?.set;
    assert.ok(setter);
    act(() => {
      remoteInput!.focus();
      setter!.call(remoteInput, "remote-added");
      remoteInput!.dispatchEvent(new dom.window.InputEvent("input", { bubbles: true, inputType: "insertText", data: "remote-added" }));
      remoteInput!.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
      remoteInput!.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
      remoteInput!.dispatchEvent(new dom.window.KeyboardEvent("keyup", { bubbles: true, key: "Unidentified" }));
    });
    await tick();
    const applyModel = newModelDialog!.querySelector<HTMLButtonElement>('button[title="Apply"]');
    assert.ok(applyModel);
    act(() => { applyModel!.click(); });
    await tick();
    assert.equal(container.querySelectorAll(".settings-model-row").length, 3);
    assert.match(container.querySelector(".settings-model-list")?.textContent ?? "", /remote-added/u);
    const addedRemove = Array.from(container.querySelectorAll<HTMLButtonElement>('button[aria-label^="Remove model"]')).find((button) => button.getAttribute("aria-label")?.includes("remote-added"));
    assert.ok(addedRemove);
    act(() => { addedRemove!.click(); });
    await tick();
    assert.equal(container.querySelectorAll(".settings-model-row").length, 2);
    const providerCancel = providerDialog()!.querySelector<HTMLButtonElement>('button[title="Cancel"]');
    assert.ok(providerCancel);
    act(() => { providerCancel!.click(); });
    await tick();
    assert.equal(container.querySelector('[role="dialog"]'), null);
  });
});

test("T07 provider URL and model display name preserve edit-time spaces and normalize at Apply/Save", async () => {
  await withRendererDom(async (dom, container, root) => {
    const saves: ConfigurationWrite[] = [];
    const state = createInitialState({ configuration: { default_model: "provider/model", providers: { provider: { kind: "openai_compat", base_url: "https://gateway.example/v1", api_key_configured: false } }, models: { "provider/model": { provider_profile_id: "provider", remote_id: "remote-model", display_name: "Existing" } } }, settingsLoaded: true });
    const tick = async () => { await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); }); };
    act(() => { root.render(<LanguageProvider value="en"><SettingsView state={state} onRevealApiKey={undefined} onBack={() => undefined} onSave={(request) => saves.push(request)} onThemeChange={() => undefined} onLanguageChange={() => undefined} /></LanguageProvider>); });
    await tick();
    const providerRow = container.querySelector<HTMLButtonElement>(".provider-row");
    assert.ok(providerRow);
    act(() => { providerRow!.click(); });
    await tick();
    const setter = Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, "value")?.set;
    assert.ok(setter);
    const baseUrl = container.querySelector<HTMLInputElement>("#modal-base-url");
    assert.ok(baseUrl);
    act(() => {
      baseUrl!.focus();
      setter!.call(baseUrl, "  https://gateway.example/v1  ");
      baseUrl!.dispatchEvent(new dom.window.InputEvent("input", { bubbles: true, inputType: "insertText", data: "  https://gateway.example/v1  " }));
      baseUrl!.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
      baseUrl!.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
      baseUrl!.dispatchEvent(new dom.window.KeyboardEvent("keyup", { bubbles: true, key: "Unidentified" }));
    });
    await tick();
    assert.equal(baseUrl!.value, "  https://gateway.example/v1  ", "Base URL editing retains surrounding spaces until Apply");
    const editModel = container.querySelector<HTMLButtonElement>('button[aria-label="Edit model Existing"]');
    assert.ok(editModel);
    act(() => { editModel!.click(); });
    await tick();
    const displayName = container.querySelector<HTMLInputElement>('input[id$="-display"]');
    assert.ok(displayName);
    act(() => {
      displayName!.focus();
      setter!.call(displayName, " My Model ");
      displayName!.dispatchEvent(new dom.window.InputEvent("input", { bubbles: true, inputType: "insertText", data: " My Model " }));
      displayName!.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
      displayName!.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
      displayName!.dispatchEvent(new dom.window.KeyboardEvent("keyup", { bubbles: true, key: "Unidentified" }));
    });
    await tick();
    assert.equal(displayName!.value, " My Model ", "display name editing retains spaces and the real internal space");
    const applyModel = container.querySelector<HTMLElement>(".model-modal button[title=\"Apply\"]") as HTMLButtonElement | null;
    assert.ok(applyModel);
    act(() => { applyModel!.click(); });
    await tick();
    const applyProvider = container.querySelector<HTMLElement>(".provider-modal:not(.model-modal) footer button[title=\"Apply\"]") as HTMLButtonElement | null;
    assert.ok(applyProvider);
    act(() => { applyProvider!.click(); });
    await tick();
    const save = container.querySelector<HTMLButtonElement>(".settings-actions .save-button");
    assert.ok(save);
    act(() => { save!.click(); });
    await tick();
    assert.equal(saves.at(-1)?.providers?.provider?.base_url, "https://gateway.example/v1");
    assert.equal(saves.at(-1)?.models?.["provider/model"]?.display_name, "My Model");
  });
});

test("T07 durable Settings save clears transient secrets even when Runtime recovery fails", async () => {
  type RecoveryFailure = "project.open" | "session.resume" | "status.get" | "project.sessions";
  const config = { default_model: "provider/model", default_permission_mode: "default" as const, providers: { provider: { kind: "openai_compat", base_url: "https://gateway.example/v1", api_key_configured: true } }, models: { "provider/model": { provider_profile_id: "provider", remote_id: "remote-model", display_name: "Model" } } };
  const project: ProjectState = { path: "C:/settings-project", projectKey: "C:/settings-project", alias: "Settings project", pinned: false, sessions: [{ session_id: "session-1" }], catalogFresh: true };
  const preferences: DesktopPreferences = {
    theme: "system", language: "en", windowBounds: { width: 1100, height: 760, maximized: false }, panelMode: "docked",
    recentProjects: [{ path: project.path, alias: project.alias }], projectAliases: {}, pinnedProjectKeys: [], pinnedSessions: [], expandedProjects: {}, selectedProjectKey: project.projectKey, selectedSessionId: "session-1",
  };
  const runScenario = async (failure: RecoveryFailure, replacement = false, deferFailure = false) => withRendererDom(async (dom, container, root) => {
    const calls: Array<{ method: string; params: JsonObject }> = [];
    const saveRequests: JsonObject[] = [];
    let savingStarted = false;
    let rejectDeferredFailure: ((reason?: unknown) => void) | null = null;
    const deferredFailure = new Promise<never>((_resolve, reject) => { rejectDeferredFailure = reject; });
    const api: DesktopApi = {
      openProject: async () => null,
      openProjectInExplorer: async () => undefined,
      copySessionId: async () => undefined,
      closeShell: async () => undefined,
      requestRuntime: async (method, params) => {
        calls.push({ method, params });
        if (method === "settings.save") {
          savingStarted = true;
          saveRequests.push(params.request as JsonObject);
          return { configuration: config };
        }
        if (savingStarted && method === failure) {
          if (deferFailure && failure === "project.open") return await deferredFailure;
          throw new Error(`synthetic ${failure} failure`);
        }
        if (method === "settings.get") return { configuration: config };
        if (method === "project.open") return { project: { path: project.path }, sessions: [], run: null };
        if (method === "session.resume") return { session_id: "session-1", replay: [], run: null };
        if (method === "project.sessions") return { sessions: [] };
        if (method === "status.get") return { active_turn: false };
        return {};
      },
      subscribeAgentEvents: () => () => undefined,
      readPreference: async (key) => preferences[key],
      writePreference: async () => preferences,
    };
    const state = createInitialState({ language: "en", view: "settings", configuration: config, settingsLoaded: true, projects: [project], selectedProjectKey: project.projectKey, selectedSessionId: project.sessions[0]?.session_id ?? null });
    const tick = async () => { await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); }); };
    act(() => { root.render(<App initialState={state} api={api} />); });
    await tick();
    await tick();
    if (replacement) {
      const providerRow = container.querySelector<HTMLButtonElement>(".provider-row");
      assert.ok(providerRow);
      act(() => { providerRow!.click(); });
      await tick();
      const input = container.querySelector<HTMLInputElement>("#modal-api-key");
      const setter = Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, "value")?.set;
      assert.ok(input);
      assert.ok(setter);
      act(() => {
        input!.focus();
        setter!.call(input, "w04-replacement-only");
        input!.dispatchEvent(new dom.window.InputEvent("input", { bubbles: true, inputType: "insertText", data: "w04-replacement-only" }));
        input!.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
        input!.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
        input!.dispatchEvent(new dom.window.KeyboardEvent("keyup", { bubbles: true, key: "Unidentified" }));
      });
      await tick();
      const applyProvider = container.querySelector<HTMLButtonElement>('.provider-modal:not(.model-modal) footer button[title="Apply"]');
      assert.ok(applyProvider);
      act(() => { applyProvider!.click(); });
      await tick();
    }
    const save = container.querySelector<HTMLButtonElement>(".settings-actions .save-button");
    assert.ok(save);
    act(() => { save!.click(); });
    if (deferFailure) {
      await tick();
      assert.equal(save!.disabled, false, "Settings saving ends at the durable write while Runtime recovery is pending");
      const reopened = container.querySelector<HTMLButtonElement>(".provider-row");
      assert.ok(reopened);
      act(() => { reopened!.click(); });
      await tick();
      assert.equal(container.querySelector<HTMLInputElement>("#modal-api-key")?.value, "", "transient key is cleared before deferred Runtime recovery settles");
      const applyProvider = container.querySelector<HTMLButtonElement>('.provider-modal:not(.model-modal) footer button[title="Apply"]');
      assert.ok(applyProvider);
      act(() => { applyProvider!.click(); });
      await tick();
      rejectDeferredFailure?.(new Error(`synthetic ${failure} failure`));
    }
    for (let index = 0; index < 8; index += 1) await tick();
    assert.equal(container.querySelector(".settings-view__error"), null, "durable save does not become a Settings error after recovery failure");
    const recoveryMessage = container.querySelector(".settings-view__runtime-error")?.textContent
      ?? container.querySelector("#runtime-panel [role=alert]")?.textContent
      ?? "";
    assert.match(recoveryMessage, /Settings were saved/u, "Runtime recovery failure is presented independently from the durable Settings result");
    assert.ok(calls.some((call) => call.method === failure), `save recovery reaches ${failure}`);
    assert.equal(saveRequests.length, 1);
    if (replacement) {
      assert.equal(saveRequests[0]?.providers?.provider?.api_key, "w04-replacement-only");
      const reopened = container.querySelector<HTMLButtonElement>(".provider-row");
      assert.ok(reopened);
      act(() => { reopened!.click(); });
      await tick();
      assert.equal(container.querySelector<HTMLInputElement>("#modal-api-key")?.value, "", "a durable save does not repopulate the saved plaintext after recovery failure");
      const applyProvider = container.querySelector<HTMLButtonElement>('.provider-modal:not(.model-modal) footer button[title="Apply"]');
      assert.ok(applyProvider);
      act(() => { applyProvider!.click(); });
      await tick();
      const secondSave = container.querySelector<HTMLButtonElement>(".settings-actions .save-button");
      assert.ok(secondSave);
      act(() => { secondSave!.click(); });
      for (let index = 0; index < 8; index += 1) await tick();
      assert.equal(saveRequests.length, 2);
      assert.equal(saveRequests[1]?.providers?.provider?.api_key, undefined, "a later Save cannot resubmit the cleared plaintext");
      assert.doesNotMatch(JSON.stringify(saveRequests[1]), /w04-replacement-only/u);
    }
  });
  await runScenario("project.open", true, true);
  await runScenario("session.resume");
  await runScenario("status.get");
  await runScenario("project.sessions");
});

test("T07 durable Settings Save locks the real Settings DOM and clears an A draft after success", async () => {
  await withRendererDom(async (dom, container, root) => {
    const config = {
      default_model: "provider/model",
      default_permission_mode: "default" as const,
      providers: { provider: { kind: "openai_compat", base_url: "https://gateway.example/v1", api_key_configured: true } },
      models: { "provider/model": { provider_profile_id: "provider", remote_id: "remote-model", display_name: "Model" } },
    };
    const project: ProjectState = { path: "C:/settings-dom-success", projectKey: "C:/settings-dom-success", alias: "Settings DOM success", pinned: false, sessions: [], catalogFresh: true };
    const preferences: DesktopPreferences = {
      theme: "light", language: "en", windowBounds: { width: 1100, height: 760, maximized: false }, panelMode: "docked",
      recentProjects: [{ path: project.path, alias: project.alias }], projectAliases: {}, pinnedProjectKeys: [], pinnedSessions: [], expandedProjects: {}, selectedProjectKey: project.projectKey, selectedSessionId: null,
    };
    const calls: Array<{ method: string; params: JsonObject }> = [];
    const saveRequests: JsonObject[] = [];
    let resolveSave: ((value: JsonObject) => void) | null = null;
    let resolveShutdown: ((value: JsonObject) => void) | null = null;
    const pendingSave = new Promise<JsonObject>((resolve) => { resolveSave = resolve; });
    const pendingShutdown = new Promise<JsonObject>((resolve) => { resolveShutdown = resolve; });
    const api: DesktopApi = {
      openProject: async () => null,
      openProjectInExplorer: async () => undefined,
      copySessionId: async () => undefined,
      closeShell: async () => undefined,
      requestRuntime: async (method, params) => {
        calls.push({ method, params });
        if (method === "settings.save") {
          saveRequests.push(params.request as JsonObject);
          return pendingSave;
        }
        if (method === "runtime.shutdown") return pendingShutdown;
        if (method === "runtime.initialize") return { run: null };
        if (method === "project.open") return { project: { path: project.path }, sessions: [], run: null };
        if (method === "project.sessions") return { sessions: [] };
        if (method === "status.get") return { active_turn: false };
        if (method === "settings.get") return { configuration: config };
        return {};
      },
      subscribeAgentEvents: () => () => undefined,
      // Keep preference bootstrap from opening a second lifecycle owner; this
      // fixture supplies the selected Project as its authoritative state.
      readPreference: async (key) => { if (key === "theme") throw new Error("synthetic preferences unavailable"); return preferences[key]; },
      writePreference: async () => preferences,
    };
    const state = createInitialState({ language: "en", theme: "light", view: "settings", configuration: config, settingsLoaded: true, projects: [project], selectedProjectKey: project.projectKey });
    const tick = async () => { await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); }); };
    const setInput = (input: HTMLInputElement, value: string) => {
      const setter = Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, "value")?.set;
      assert.ok(setter);
      if (input.isConnected) input.focus();
      setter!.call(input, value);
      input.dispatchEvent(new dom.window.InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
      input.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
      input.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
      input.dispatchEvent(new dom.window.KeyboardEvent("keyup", { bubbles: true, key: "Unidentified" }));
    };

    act(() => { root.render(<App initialState={state} api={api} />); });
    for (let index = 0; index < 4; index += 1) await tick();
    const providerRow = container.querySelector<HTMLButtonElement>(".provider-row");
    assert.ok(providerRow);
    act(() => { providerRow!.click(); });
    await tick();
    const baseUrl = container.querySelector<HTMLInputElement>("#modal-base-url");
    const apiKey = container.querySelector<HTMLInputElement>("#modal-api-key");
    const modelEdit = container.querySelector<HTMLButtonElement>(".settings-model-row__actions button[title^=\"Edit model\"]");
    assert.ok(baseUrl && apiKey && modelEdit);
    act(() => {
      setInput(baseUrl!, " https://gateway.example/v1 ");
      setInput(apiKey!, "draft-a");
    });
    await tick();
    // Open an existing Model modal so Save also closes the nested modal and
    // its input handlers are exercised after the lifecycle starts.
    act(() => { modelEdit!.click(); });
    await tick();
    const modelRemote = container.querySelector<HTMLInputElement>(".model-modal input[id$=\"-remote\"]");
    const addModel = container.querySelector<HTMLButtonElement>(".provider-modal:not(.model-modal) .settings-subsection__heading > button[title=\"Add model\"]");
    assert.ok(modelRemote && addModel);

    const save = container.querySelector<HTMLButtonElement>(".settings-actions .save-button");
    assert.ok(save);
    act(() => { save!.click(); });
    for (let index = 0; index < 4; index += 1) await tick();
    const settings = container.querySelector<HTMLElement>(".settings-view");
    assert.equal(settings?.getAttribute("aria-busy"), "true");
    assert.equal(settings?.getAttribute("aria-describedby"), "settings-busy-status");
    assert.match(container.querySelector<HTMLElement>(".settings-view__busy-status")?.textContent ?? "", /Saving settings…/u);
    assert.equal(dom.window.document.activeElement, container.querySelector("#settings-busy-status"), "busy status receives focus while the modal is closed");
    assert.equal(container.querySelector("[role=dialog]"), null, "Save closes both provider and nested Model modal");
    assert.equal(calls.filter((call) => call.method === "settings.save").length, 1);
    assert.equal(calls.filter((call) => call.method === "runtime.shutdown").length, 0, "Runtime recovery waits for durable Save");
    assert.equal(saveRequests[0]?.providers?.provider?.api_key, "draft-a");

    const addProvider = container.querySelector<HTMLButtonElement>(".row-add--inline");
    const triggers = Array.from(container.querySelectorAll<HTMLButtonElement>(".settings-view .custom-select__trigger"));
    const back = container.querySelector<HTMLButtonElement>(".settings-view__back");
    const cancel = container.querySelector<HTMLButtonElement>('.settings-actions button[title="Cancel"]');
    assert.ok(addProvider && back && cancel);
    assert.equal(addProvider!.disabled, true);
    assert.equal(providerRow!.disabled, true);
    assert.equal(triggers.length, 4);
    assert.ok(triggers.every((trigger) => trigger.disabled), "permission/default/theme/language controls are disabled");
    assert.equal(back!.disabled, true);
    assert.equal(cancel!.disabled, true);
    assert.equal(save!.disabled, true);

    // These are the real DOM entry points captured before Save. Native
    // disabled controls and detached modal controls must not create a B draft
    // or mutate A while the durable request is pending.
    act(() => {
      providerRow!.click();
      addProvider!.click();
      triggers.forEach((trigger) => trigger.click());
      back!.click();
      cancel!.click();
      addModel!.click();
      setInput(baseUrl!, " B provider ");
      setInput(apiKey!, "draft-b");
      setInput(modelRemote!, "model-b");
    });
    await tick();
    assert.equal(container.querySelector("[role=dialog]"), null);
    assert.equal(container.querySelectorAll(".provider-row").length, 1, "Add Provider and Provider row remain inert");
    assert.equal(calls.filter((call) => call.method === "settings.save").length, 1, "blocked entries do not issue a second Save");

    resolveSave?.({
      configuration: {
        ...config,
        providers: { provider: { ...config.providers.provider } },
        models: { "provider/model": { ...config.models["provider/model"] } },
      },
    });
    for (let index = 0; index < 8; index += 1) await tick();
    assert.equal(container.querySelector<HTMLElement>(".settings-view")?.getAttribute("aria-busy"), "false");
    assert.equal(container.querySelector(".settings-view__busy-status"), null);
    assert.equal(container.querySelector<HTMLButtonElement>(".settings-actions .save-button")?.disabled, false);
    assert.equal(dom.window.document.activeElement, container.querySelector(".settings-actions .save-button"), "Save regains focus at the durable boundary");
    assert.equal(calls.filter((call) => call.method === "runtime.shutdown").length, 1);

    // settings_loaded resets the visible draft and clears the transient key;
    // the still-pending Runtime recovery must not reintroduce it.
    const reopened = container.querySelector<HTMLButtonElement>(".provider-row");
    assert.ok(reopened);
    act(() => { reopened!.click(); });
    await tick();
    assert.equal(container.querySelector<HTMLInputElement>("#modal-api-key")?.value, "", "durable success clears the A replacement");
    assert.equal(container.querySelector<HTMLInputElement>("#modal-base-url")?.value, "https://gateway.example/v1");
    assert.equal(container.querySelectorAll(".settings-model-row").length, 1, "no B model draft was created");
    act(() => { container.querySelector<HTMLButtonElement>('.provider-modal > footer button[title="Cancel"]')?.click(); });
    await tick();

    resolveShutdown?.({});
    for (let index = 0; index < 16; index += 1) await tick();
    assert.equal(container.querySelector<HTMLElement>(".settings-view__runtime-status"), null);
  });
});

test("T07 durable Settings Save failure keeps the A draft after the modal closes and re-enables editing", async () => {
  await withRendererDom(async (dom, container, root) => {
    const config = {
      default_model: "provider/model",
      default_permission_mode: "default" as const,
      providers: { provider: { kind: "openai_compat", base_url: "https://gateway.example/v1", api_key_configured: true } },
      models: { "provider/model": { provider_profile_id: "provider", remote_id: "remote-model", display_name: "Model" } },
    };
    const calls: Array<{ method: string; params: JsonObject }> = [];
    let rejectSave: ((reason?: unknown) => void) | null = null;
    const pendingSave = new Promise<JsonObject>((_resolve, reject) => { rejectSave = reject; });
    const api: DesktopApi = {
      openProject: async () => null,
      openProjectInExplorer: async () => undefined,
      copySessionId: async () => undefined,
      closeShell: async () => undefined,
      requestRuntime: async (method, params) => {
        calls.push({ method, params });
        if (method === "settings.save") return pendingSave;
        if (method === "settings.get") return { configuration: config };
        return {};
      },
      subscribeAgentEvents: () => () => undefined,
      readPreference: async (key) => { if (key === "theme") throw new Error("synthetic preferences unavailable"); return undefined; },
      writePreference: async () => undefined,
    };
    const state = createInitialState({ language: "en", view: "settings", configuration: config, settingsLoaded: true });
    const tick = async () => { await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); }); };
    const setInput = (input: HTMLInputElement, value: string) => {
      const setter = Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, "value")?.set;
      assert.ok(setter);
      if (input.isConnected) input.focus();
      setter!.call(input, value);
      input.dispatchEvent(new dom.window.InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
      input.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
      input.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
      input.dispatchEvent(new dom.window.KeyboardEvent("keyup", { bubbles: true, key: "Unidentified" }));
    };

    act(() => { root.render(<App initialState={state} api={api} />); });
    for (let index = 0; index < 4; index += 1) await tick();
    const providerRow = container.querySelector<HTMLButtonElement>(".provider-row");
    assert.ok(providerRow);
    act(() => { providerRow!.click(); });
    await tick();
    const baseUrl = container.querySelector<HTMLInputElement>("#modal-base-url");
    const apiKey = container.querySelector<HTMLInputElement>("#modal-api-key");
    assert.ok(baseUrl && apiKey);
    act(() => {
      setInput(baseUrl!, " A draft ");
      setInput(apiKey!, "draft-a");
    });
    await tick();
    const save = container.querySelector<HTMLButtonElement>(".settings-actions .save-button");
    assert.ok(save);
    act(() => { save!.click(); });
    for (let index = 0; index < 4; index += 1) await tick();
    assert.equal(container.querySelector<HTMLElement>(".settings-view")?.getAttribute("aria-busy"), "true");
    assert.equal(container.querySelector("[role=dialog]"), null);
    rejectSave?.(new Error("synthetic durable failure"));
    for (let index = 0; index < 10; index += 1) await tick();
    assert.equal(calls.filter((call) => call.method === "settings.save").length, 1);
    assert.equal(container.querySelector<HTMLElement>(".settings-view")?.getAttribute("aria-busy"), "false");
    assert.match(container.querySelector<HTMLElement>(".settings-view__error")?.textContent ?? "", /Configuration could not be saved/u);
    assert.doesNotMatch(container.textContent ?? "", /synthetic durable failure/u);
    assert.equal(container.querySelector<HTMLButtonElement>(".settings-actions .save-button")?.disabled, false);

    const reopened = container.querySelector<HTMLButtonElement>(".provider-row");
    assert.ok(reopened);
    act(() => { reopened!.click(); });
    await tick();
    assert.equal(container.querySelector<HTMLInputElement>("#modal-base-url")?.value, " A draft ", "durable failure retains A's edit-time spaces");
    assert.equal(container.querySelector<HTMLInputElement>("#modal-api-key")?.value, "draft-a", "durable failure retains A's replacement");
    assert.equal(container.querySelectorAll(".provider-row").length, 1);
    assert.equal(container.querySelectorAll(".settings-model-row").length, 1);
    const editedBaseUrl = container.querySelector<HTMLInputElement>("#modal-base-url");
    const editedApiKey = container.querySelector<HTMLInputElement>("#modal-api-key");
    assert.ok(editedBaseUrl && editedApiKey);
    act(() => {
      setInput(editedBaseUrl!, " A draft edited ");
      setInput(editedApiKey!, "draft-a-edited");
    });
    await tick();
    assert.equal(editedBaseUrl!.value, " A draft edited ", "the retained A draft remains editable");
    assert.equal(editedApiKey!.value, "draft-a-edited", "the retained replacement remains editable");
  });
});

test("T07 durable Save owns the lifecycle before its RPC, gates Back, and lets newer navigation supersede stale recovery", async () => {
  await withRendererDom(async (_dom, container, root) => {
    const config = {
      default_model: "provider/model",
      default_permission_mode: "default" as const,
      providers: { provider: { kind: "openai_compat", base_url: "https://gateway.example/v1", api_key_configured: false } },
      models: { "provider/model": { provider_profile_id: "provider", remote_id: "remote-model", display_name: "Model" } },
    };
    const first: ProjectState = { path: "C:/pending-save-a", projectKey: "C:/pending-save-a", alias: "Pending A", pinned: false, sessions: [{ session_id: "session-a" }], catalogFresh: true };
    const second: ProjectState = { path: "C:/pending-save-b", projectKey: "C:/pending-save-b", alias: "Pending B", pinned: false, sessions: [], catalogFresh: true };
    const preferences: DesktopPreferences = {
      theme: "system", language: "en", windowBounds: { width: 1100, height: 760, maximized: false }, panelMode: "docked",
      recentProjects: [{ path: first.path, alias: first.alias }, { path: second.path, alias: second.alias }], projectAliases: {}, pinnedProjectKeys: [], pinnedSessions: [], expandedProjects: {}, selectedProjectKey: first.projectKey, selectedSessionId: "session-a",
    };
    const calls: Array<{ method: string; params: JsonObject }> = [];
    let resolveSave: ((value: JsonObject) => void) | null = null;
    let resolveShutdown: ((value: JsonObject) => void) | null = null;
    const pendingSave = new Promise<JsonObject>((resolve) => { resolveSave = resolve; });
    const pendingShutdown = new Promise<JsonObject>((resolve) => { resolveShutdown = resolve; });
    const api: DesktopApi = {
      openProject: async () => null,
      openProjectInExplorer: async () => undefined,
      copySessionId: async () => undefined,
      closeShell: async () => undefined,
      requestRuntime: async (method, params) => {
        calls.push({ method, params });
        if (method === "settings.save") return pendingSave;
        if (method === "runtime.shutdown") return pendingShutdown;
        if (method === "runtime.initialize") return { run: null };
        if (method === "project.open") return { project: { path: params.path }, sessions: [], run: null };
        if (method === "session.resume") return { session_id: "session-a", replay: [], run: null };
        if (method === "project.sessions") return { sessions: [] };
        if (method === "status.get") return { active_turn: false };
        if (method === "settings.get") return { configuration: config };
        return {};
      },
      subscribeAgentEvents: () => () => undefined,
      // Prevent preference bootstrap from creating an unrelated lifecycle
      // owner; this test controls the selected Project explicitly.
      readPreference: async (key) => { if (key === "theme") throw new Error("synthetic preferences unavailable"); return preferences[key]; },
      writePreference: async () => preferences,
    };
    const state = createInitialState({ language: "en", view: "settings", configuration: config, settingsLoaded: true, projects: [first, second], selectedProjectKey: first.projectKey, selectedSessionId: "session-a" });
    const tick = async () => { await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); }); };
    act(() => { root.render(<App initialState={state} api={api} />); });
    for (let index = 0; index < 4; index += 1) await tick();

    const save = container.querySelector<HTMLButtonElement>(".settings-actions .save-button");
    const back = container.querySelector<HTMLButtonElement>(".settings-view__back");
    const cancel = container.querySelector<HTMLButtonElement>('.settings-actions button[title="Cancel"]');
    assert.ok(save && back && cancel);
    act(() => { save!.click(); });
    for (let index = 0; index < 4; index += 1) await tick();
    assert.deepEqual(calls.map((call) => call.method), ["settings.save"], "the durable RPC is issued only after the new lifecycle owner is installed");
    assert.equal(save!.disabled, true);
    assert.equal(back!.disabled, true, "Back is gated while the durable request is pending");
    assert.equal(cancel!.disabled, true, "Cancel is gated while the durable request is pending");
    act(() => { back!.click(); cancel!.click(); });
    await tick();
    assert.ok(container.querySelector(".settings-view"), "a pending Save cannot leave Settings through Back or Cancel");

    // Durable success releases transient Settings saving immediately, but the
    // same owner remains in Runtime shutdown until its projection recovery is
    // either completed or superseded.
    resolveSave?.({ configuration: config });
    for (let index = 0; index < 6; index += 1) await tick();
    assert.equal(container.querySelector<HTMLButtonElement>(".settings-actions .save-button")?.disabled, false);
    assert.equal(calls.filter((call) => call.method === "runtime.shutdown").length, 1);

    // Back is now allowed at the durable boundary. Selecting Project B takes
    // the next generation, so A's late shutdown completion cannot continue to
    // initialize/open/resume A or overwrite B's owner state.
    act(() => { container.querySelector<HTMLButtonElement>(".settings-view__back")?.click(); });
    await tick();
    const projectButton = Array.from(container.querySelectorAll<HTMLButtonElement>(".project-select")).find((button) => button.textContent?.includes("Pending B"));
    assert.ok(projectButton);
    act(() => { projectButton!.click(); });
    for (let index = 0; index < 5; index += 1) await tick();
    assert.equal(calls.filter((call) => call.method === "project.open").length, 0, "Project B waits for A's already-issued shutdown rather than racing it");
    resolveShutdown?.({});
    for (let index = 0; index < 16; index += 1) await tick();
    assert.deepEqual(calls.filter((call) => ["runtime.initialize", "project.open", "session.resume"].includes(call.method)).map((call) => [call.method, call.params.path ?? null]), [["project.open", second.path]], "stale A recovery cannot publish or continue after B takes ownership");
    assert.equal(container.querySelector<HTMLElement>("#runtime-panel h2")?.textContent?.includes("Ready"), true);
  });
});

test("T07 durable Save failure releases its lifecycle owner without starting Runtime recovery", async () => {
  await withRendererDom(async (_dom, container, root) => {
    const config = { default_model: "provider/model", providers: { provider: { kind: "openai_compat", api_key_configured: false } }, models: { "provider/model": { provider_profile_id: "provider", remote_id: "remote-model" } } };
    const calls: string[] = [];
    const api: DesktopApi = {
      openProject: async () => null,
      openProjectInExplorer: async () => undefined,
      copySessionId: async () => undefined,
      closeShell: async () => undefined,
      requestRuntime: async (method) => {
        calls.push(method);
        if (method === "settings.save") throw new Error("synthetic durable failure");
        if (method === "settings.get") return { configuration: config };
        return {};
      },
      subscribeAgentEvents: () => () => undefined,
      readPreference: async (key) => { if (key === "theme") throw new Error("synthetic preferences unavailable"); return undefined; },
      writePreference: async () => undefined,
    };
    const state = createInitialState({ language: "en", view: "settings", configuration: config, settingsLoaded: true });
    const tick = async () => { await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); }); };
    act(() => { root.render(<App initialState={state} api={api} />); });
    for (let index = 0; index < 3; index += 1) await tick();
    act(() => { container.querySelector<HTMLButtonElement>(".settings-actions .save-button")?.click(); });
    for (let index = 0; index < 8; index += 1) await tick();
    assert.deepEqual(calls, ["settings.save"], "a failed durable Save never starts project recovery");
    assert.match(container.querySelector<HTMLElement>(".settings-view__error")?.textContent ?? "", /Configuration could not be saved/u);
    assert.doesNotMatch(container.textContent ?? "", /synthetic durable failure/u);
    assert.equal(container.querySelector<HTMLButtonElement>(".settings-actions .save-button")?.disabled, false, "failure returns Save to an actionable state");
    assert.equal(container.querySelector<HTMLElement>(".settings-view__runtime-status"), null, "failed Save leaves no stuck restarting state");
  });
});

test("T07 unmount invalidates a pending durable Save without continuing its old recovery", async () => {
  await withRendererDom(async (_dom, container, root) => {
    const config = { default_model: "provider/model", providers: { provider: { kind: "openai_compat", api_key_configured: false } }, models: { "provider/model": { provider_profile_id: "provider", remote_id: "remote-model" } } };
    const calls: string[] = [];
    let resolveSave: ((value: JsonObject) => void) | null = null;
    const pendingSave = new Promise<JsonObject>((resolve) => { resolveSave = resolve; });
    const api: DesktopApi = {
      openProject: async () => null,
      openProjectInExplorer: async () => undefined,
      copySessionId: async () => undefined,
      closeShell: async () => undefined,
      requestRuntime: async (method) => {
        calls.push(method);
        if (method === "settings.save") return pendingSave;
        if (method === "settings.get") return { configuration: config };
        return {};
      },
      subscribeAgentEvents: () => () => undefined,
      readPreference: async (key) => { if (key === "theme") throw new Error("synthetic preferences unavailable"); return undefined; },
      writePreference: async () => undefined,
    };
    const state = createInitialState({ language: "en", view: "settings", configuration: config, settingsLoaded: true, selectedProjectKey: "C:/detached-save", selectedSessionId: "session-1" });
    const tick = async () => { await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); }); };
    act(() => { root.render(<App initialState={state} api={api} />); });
    for (let index = 0; index < 3; index += 1) await tick();
    act(() => { container.querySelector<HTMLButtonElement>(".settings-actions .save-button")?.click(); });
    await tick();
    assert.deepEqual(calls, ["settings.save"]);
    act(() => { root.unmount(); });
    resolveSave?.({ configuration: config });
    for (let index = 0; index < 4; index += 1) await tick();
    assert.deepEqual(calls, ["settings.save"], "unmount prevents a late durable response from starting project recovery");
  });
});

test("T07 newer durable Save supersedes a blocked recovery without concurrent Runtime ownership", async () => {
  await withRendererDom(async (_dom, container, root) => {
    const config = {
      default_model: "provider/model",
      default_permission_mode: "default" as const,
      providers: { provider: { kind: "openai_compat", base_url: "https://gateway.example/v1", api_key_configured: false } },
      models: { "provider/model": { provider_profile_id: "provider", remote_id: "remote-model", display_name: "Model" } },
    };
    const project: ProjectState = { path: "C:/save-ownership", projectKey: "C:/save-ownership", alias: "Save ownership", pinned: false, sessions: [{ session_id: "session-1" }], catalogFresh: true };
    const preferences: DesktopPreferences = {
      theme: "system", language: "en", windowBounds: { width: 1100, height: 760, maximized: false }, panelMode: "docked",
      recentProjects: [{ path: project.path, alias: project.alias }], projectAliases: {}, pinnedProjectKeys: [], pinnedSessions: [], expandedProjects: {}, selectedProjectKey: project.projectKey, selectedSessionId: "session-1",
    };
    const calls: string[] = [];
    let saveCalls = 0;
    let shutdownCalls = 0;
    let resolveFirstShutdown: ((value: JsonObject) => void) | null = null;
    const firstShutdown = new Promise<JsonObject>((resolve) => { resolveFirstShutdown = resolve; });
    let eventListener: ((event: AgentEvent) => void) | null = null;
    const api: DesktopApi = {
      openProject: async () => null,
      openProjectInExplorer: async () => undefined,
      copySessionId: async () => undefined,
      closeShell: async () => undefined,
      requestRuntime: async (method) => {
        calls.push(method);
        if (method === "settings.save") {
          saveCalls += 1;
          return { configuration: config };
        }
        if (method === "runtime.shutdown") {
          shutdownCalls += 1;
          if (shutdownCalls === 1) eventListener?.({ type: "runtime_state", state: "ready" });
          return shutdownCalls === 1 ? firstShutdown : {};
        }
        if (method === "runtime.initialize") return { run: null };
        if (method === "project.open") return { project: { path: project.path }, sessions: [], run: null };
        if (method === "session.resume") return { session_id: "session-1", replay: [], run: null };
        if (method === "project.sessions") return { sessions: [] };
        if (method === "status.get") return { active_turn: false };
        if (method === "settings.get") return { configuration: config };
        return {};
      },
      subscribeAgentEvents: (listener) => { eventListener = listener; return () => { eventListener = null; }; },
      readPreference: async (key) => preferences[key],
      writePreference: async () => preferences,
    };
    const state = createInitialState({ language: "en", view: "settings", configuration: config, settingsLoaded: true, projects: [project], selectedProjectKey: project.projectKey, selectedSessionId: "session-1" });
    const tick = async () => { await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); }); };
    act(() => { root.render(<App initialState={state} api={api} />); });
    for (let index = 0; index < 6; index += 1) await tick();
    const save = () => {
      const button = container.querySelector<HTMLButtonElement>(".settings-actions .save-button");
      assert.ok(button);
      act(() => { button!.click(); });
    };
    save();
    for (let index = 0; index < 4; index += 1) await tick();
    assert.equal(saveCalls, 1);
    assert.match(container.querySelector<HTMLElement>(".settings-view__runtime-status")?.textContent ?? "", /Runtime is restarting/u);
    save();
    for (let index = 0; index < 4; index += 1) await tick();
    assert.equal(saveCalls, 1, "the next durable Save waits behind the first owner instead of racing its in-flight Runtime RPC");
    assert.equal(shutdownCalls, 1, "the second recovery waits for the first in-flight lifecycle RPC");
    resolveFirstShutdown?.({});
    for (let index = 0; index < 14; index += 1) await tick();
    assert.equal(saveCalls, 2, "the next durable Save is issued only after the stale owner settles");
    assert.equal(shutdownCalls, 2);
    const lifecycle = calls.slice(calls.indexOf("settings.save")).filter((method) => ["runtime.shutdown", "runtime.initialize", "project.open", "session.resume"].includes(method));
    assert.deepEqual(lifecycle, ["runtime.shutdown", "runtime.shutdown", "runtime.initialize", "project.open", "session.resume"], "the stale Save cannot publish or continue its old lifecycle");
    assert.equal(container.querySelector(".settings-view__runtime-status"), null, "the terminal recovery state leaves restarting");
    assert.equal(container.querySelector(".settings-view__runtime-error"), null, "a stale recovery does not surface a late error");
    assert.match(container.querySelector<HTMLElement>("#runtime-panel h2")?.textContent ?? "", /Ready/u, "the newest Runtime owner reaches ready");
  });
});

test("T07 completed lifecycle owner releases ordinary refreshes and runtime events", async () => {
  await withRendererDom(async (_dom, container, root) => {
    const config = {
      default_model: "provider/model",
      default_permission_mode: "default" as const,
      providers: { provider: { kind: "openai_compat", base_url: "https://gateway.example/v1", api_key_configured: false } },
      models: { "provider/model": { provider_profile_id: "provider", remote_id: "remote-model", display_name: "Model" } },
    };
    const project: ProjectState = { path: "C:/lifecycle-terminal", projectKey: "C:/lifecycle-terminal", alias: "Lifecycle terminal", pinned: false, sessions: [{ session_id: "session-1" }], catalogFresh: true };
    const preferences: DesktopPreferences = {
      theme: "system", language: "en", windowBounds: { width: 1100, height: 760, maximized: false }, panelMode: "docked",
      recentProjects: [{ path: project.path, alias: project.alias }], projectAliases: {}, pinnedProjectKeys: [], pinnedSessions: [], expandedProjects: {}, selectedProjectKey: project.projectKey, selectedSessionId: "session-1",
    };
    const calls: Array<{ method: string; params: JsonObject }> = [];
    let resolveShutdown: ((value: JsonObject) => void) | null = null;
    let eventListener: ((event: AgentEvent) => void) | null = null;
    const shutdown = new Promise<JsonObject>((resolve) => { resolveShutdown = resolve; });
    const api: DesktopApi = {
      openProject: async () => null,
      openProjectInExplorer: async () => undefined,
      copySessionId: async () => undefined,
      closeShell: async () => undefined,
      requestRuntime: async (method, params) => {
        calls.push({ method, params });
        if (method === "settings.save") return { configuration: config };
        if (method === "runtime.shutdown") return await shutdown;
        if (method === "runtime.initialize") return { run: null };
        if (method === "project.open") return { project: { path: project.path }, sessions: [], run: null };
        if (method === "session.resume") return { session_id: "session-1", replay: [], run: null };
        if (method === "project.sessions") return { sessions: [{ session_id: "session-1", preview: "refreshed" }] };
        if (method === "status.get") return { active_turn: false };
        if (method === "settings.get") return { configuration: config };
        if (method === "command.complete") return { candidates: [{ value: "/model", display: "/model" }], argument_candidates: [] };
        if (method === "command.execute") return { ui_action: { type: "session_changed", session_id: "session-1" } };
        return {};
      },
      subscribeAgentEvents: (listener) => { eventListener = listener; return () => { eventListener = null; }; },
      // Keep preference bootstrap from starting a second lifecycle owner; the
      // test supplies the selected project as its authoritative initial state.
      readPreference: async (key) => { if (key === "theme") throw new Error("synthetic preferences unavailable"); return preferences[key]; },
      writePreference: async () => preferences,
    };
    const state = createInitialState({
      language: "en", view: "settings", runtimeState: "ready", configuration: config, settingsLoaded: true,
      composerText: "/", commandCandidates: [{ value: "/model", display: "/model" }], projects: [project], selectedProjectKey: project.projectKey, selectedSessionId: "session-1",
      run: { run_id: "run-recovery", turn_id: "turn-recovery", status: "idle" },
    });
    const tick = async () => { await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); }); };
    act(() => { root.render(<App initialState={state} api={api} />); });
    for (let index = 0; index < 4; index += 1) await tick();
    const save = container.querySelector<HTMLButtonElement>(".settings-actions .save-button");
    assert.ok(save);
    act(() => { save!.click(); });
    for (let index = 0; index < 4; index += 1) await tick();
    assert.equal(calls.filter((call) => call.method === "runtime.shutdown").length, 1);
    assert.match(container.querySelector<HTMLElement>(".settings-view__runtime-status")?.textContent ?? "", /Runtime is restarting/u);

    // Transport lifecycle envelopes cannot replace the explicit restarting
    // state while the recovery owner is still pending.
    act(() => { eventListener?.({ type: "runtime_state", state: "ready" }); });
    await tick();
    assert.match(container.querySelector<HTMLElement>(".settings-view__runtime-status")?.textContent ?? "", /Runtime is restarting/u);
    const beforeStaleTerminal = calls.length;
    act(() => { eventListener?.({ type: "turn_completed", run_id: "run-recovery", turn_id: "turn-recovery" }); });
    await tick();
    assert.equal(calls.slice(beforeStaleTerminal).filter((call) => call.method === "status.get").length, 0, "a terminal event cannot start a status RPC during lifecycle recovery");

    act(() => { container.querySelector<HTMLButtonElement>(".settings-view__back")?.click(); });
    await tick();
    const textarea = container.querySelector<HTMLTextAreaElement>(".composer textarea");
    const send = container.querySelector<HTMLButtonElement>(".composer-actions button:last-child");
    const modelTrigger = container.querySelector<HTMLButtonElement>(".composer-model .custom-select__trigger");
    assert.ok(textarea && send && modelTrigger);
    assert.equal(textarea!.disabled, true, "returning to chat keeps Composer locked during recovery");
    assert.equal(container.querySelector<HTMLElement>(".composer")?.getAttribute("aria-disabled"), "true");
    assert.equal(container.querySelector(".command-menu"), null, "slash completion is hidden during recovery");
    const beforeBlockedChat = calls.length;
    act(() => { send!.click(); modelTrigger!.click(); });
    await tick();
    assert.equal(calls.length, beforeBlockedChat, "chat buttons cannot issue Runtime RPC while recovery is pending");

    resolveShutdown?.({});
    for (let index = 0; index < 18; index += 1) await tick();
    assert.match(container.querySelector<HTMLElement>("#runtime-panel h2")?.textContent ?? "", /Ready/u, "terminal lifecycle completion leaves Runtime ready");
    assert.equal(container.querySelector<HTMLTextAreaElement>(".composer textarea")?.disabled, false, "terminal lifecycle completion releases Composer");
    const completion = container.querySelector<HTMLButtonElement>(".command-menu button");
    assert.ok(completion, "completion controls return after recovery terminal");
    const beforeCompletion = calls.length;
    act(() => { completion!.click(); });
    await tick();
    assert.ok(calls.slice(beforeCompletion).some((call) => call.method === "command.complete"), "completion resumes after recovery terminal");

    const setter = Object.getOwnPropertyDescriptor((_dom.window.HTMLTextAreaElement as typeof HTMLTextAreaElement).prototype, "value")?.set;
    assert.ok(setter);
    const beforeCommand = calls.length;
    act(() => {
      setter!.call(textarea, "/switch");
      textarea!.dispatchEvent(new _dom.window.InputEvent("input", { bubbles: true, inputType: "insertText", data: "/switch" }));
      textarea!.dispatchEvent(new _dom.window.Event("input", { bubbles: true }));
    });
    await tick();
    act(() => { send!.click(); });
    for (let index = 0; index < 6; index += 1) await tick();
    const afterCommand = calls.slice(beforeCommand).map((call) => call.method);
    assert.ok(afterCommand.includes("command.execute"), "command entry resumes after recovery terminal");
    assert.ok(afterCommand.includes("status.get"), "ordinary status refresh resumes after owner cleanup");
    assert.ok(afterCommand.includes("project.sessions"), "ordinary catalog refresh resumes after owner cleanup");

    act(() => { eventListener?.({ type: "runtime_state", state: "stopped" }); });
    await tick();
    assert.match(container.querySelector<HTMLElement>("#runtime-panel h2")?.textContent ?? "", /Stopped/u, "runtime_state events are accepted after owner cleanup");
    act(() => { eventListener?.({ type: "runtime_state", state: "ready" }); });
    await tick();
    assert.match(container.querySelector<HTMLElement>("#runtime-panel h2")?.textContent ?? "", /Ready/u);

    const settings = container.querySelector<HTMLButtonElement>('button[title="Open Settings"]');
    assert.ok(settings);
    const beforeSettings = calls.length;
    act(() => { settings!.click(); });
    for (let index = 0; index < 4; index += 1) await tick();
    assert.ok(calls.slice(beforeSettings).some((call) => call.method === "settings.get"), "settings refresh resumes after owner cleanup");
  });
});

test("T07 navigation supersedes blocked recovery and unmount suppresses late lifecycle writes", async () => {
  await withRendererDom(async (_dom, container, root) => {
    const config = { default_model: "provider/model", providers: { provider: { kind: "openai_compat", api_key_configured: false } }, models: { "provider/model": { provider_profile_id: "provider", remote_id: "remote-model", display_name: "Model" } } };
    const first: ProjectState = { path: "C:/recovery-project", projectKey: "C:/recovery-project", alias: "Recovery", pinned: false, sessions: [{ session_id: "session-1" }], catalogFresh: true };
    const second: ProjectState = { path: "C:/navigation-project", projectKey: "C:/navigation-project", alias: "Navigation", pinned: false, sessions: [], catalogFresh: true };
    const calls: string[] = [];
    let shutdownCalls = 0;
    let resolveFirstShutdown: ((value: JsonObject) => void) | null = null;
    let resolveSecondShutdown: ((value: JsonObject) => void) | null = null;
    const api: DesktopApi = {
      openProject: async () => null,
      openProjectInExplorer: async () => undefined,
      copySessionId: async () => undefined,
      closeShell: async () => undefined,
      requestRuntime: async (method, params) => {
        calls.push(method);
        if (method === "settings.save") return { configuration: config };
        if (method === "runtime.shutdown") {
          shutdownCalls += 1;
          if (shutdownCalls === 1) return new Promise<JsonObject>((resolve) => { resolveFirstShutdown = resolve; });
          if (shutdownCalls === 2) return new Promise<JsonObject>((resolve) => { resolveSecondShutdown = resolve; });
          return {};
        }
        if (method === "project.open") return { project: { path: params.path }, sessions: [], run: null };
        if (method === "runtime.initialize") return { run: null };
        if (method === "session.resume") return { session_id: "session-1", replay: [], run: null };
        if (method === "project.sessions") return { sessions: [] };
        if (method === "status.get") return { active_turn: false };
        if (method === "settings.get") return { configuration: config };
        return {};
      },
      subscribeAgentEvents: () => () => undefined,
      // Reject preference bootstrap so the initial selected Project remains the
      // supplied test state; this test is about the lifecycle queue itself.
      readPreference: async (key) => { if (key === "theme") throw new Error("synthetic preferences unavailable"); return undefined; },
      writePreference: async () => undefined,
    };
    const state = createInitialState({ language: "en", view: "settings", configuration: config, settingsLoaded: true, projects: [first, second], selectedProjectKey: first.projectKey, selectedSessionId: "session-1" });
    const tick = async () => { await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); }); };
    act(() => { root.render(<App initialState={state} api={api} />); });
    for (let index = 0; index < 4; index += 1) await tick();
    act(() => { container.querySelector<HTMLButtonElement>(".settings-actions .save-button")?.click(); });
    for (let index = 0; index < 4; index += 1) await tick();
    assert.equal(shutdownCalls, 1);
    act(() => { container.querySelector<HTMLButtonElement>(".settings-actions button[title=\"Cancel\"]")?.click(); });
    await tick();
    const projectButton = Array.from(container.querySelectorAll<HTMLButtonElement>(".project-select")).find((button) => button.textContent?.includes("Navigation"));
    assert.ok(projectButton);
    act(() => { projectButton!.click(); });
    for (let index = 0; index < 4; index += 1) await tick();
    assert.equal(shutdownCalls, 1, "navigation waits for the blocked recovery RPC instead of racing it");
    resolveFirstShutdown?.({});
    for (let index = 0; index < 14; index += 1) await tick();
    assert.equal(calls.filter((method) => method === "project.open").length, 1);
    assert.equal(calls.filter((method) => method === "session.resume").length, 0, "the stale recovery cannot resume the old session");
    assert.match(container.querySelector<HTMLElement>("#runtime-panel h2")?.textContent ?? "", /Ready/u);

    // A second blocked recovery is invalidated by unmount. Its in-flight
    // shutdown may settle, but no late project/session lifecycle call follows.
    act(() => { container.querySelector<HTMLButtonElement>("button[title=\"Open Settings\"]")?.click(); });
    await tick();
    const save = container.querySelector<HTMLButtonElement>(".settings-actions .save-button");
    assert.ok(save);
    act(() => { save!.click(); });
    for (let index = 0; index < 4; index += 1) await tick();
    assert.equal(shutdownCalls, 2);
    act(() => { root.unmount(); });
    resolveSecondShutdown?.({});
    for (let index = 0; index < 6; index += 1) await tick();
    assert.equal(calls.filter((method) => method === "project.open").length, 1, "unmount invalidates the detached recovery before project.open");
  });
});

test("T07 duplicate Save clicks issue one durable request", async () => {
  await withRendererDom(async (_dom, container, root) => {
    const config = { default_model: "provider/model", providers: { provider: { kind: "openai_compat", api_key_configured: false } }, models: { "provider/model": { provider_profile_id: "provider", remote_id: "remote-model" } } };
    let resolveSave: ((value: JsonObject) => void) | null = null;
    let saveCalls = 0;
    const api: DesktopApi = {
      openProject: async () => null,
      openProjectInExplorer: async () => undefined,
      copySessionId: async () => undefined,
      closeShell: async () => undefined,
      requestRuntime: async (method) => {
        if (method === "settings.save") {
          saveCalls += 1;
          return new Promise<JsonObject>((resolve) => { resolveSave = resolve; });
        }
        if (method === "settings.get") return { configuration: config };
        return {};
      },
      subscribeAgentEvents: () => () => undefined,
      readPreference: async (key) => { if (key === "theme") throw new Error("synthetic preferences unavailable"); return undefined; },
      writePreference: async () => undefined,
    };
    const state = createInitialState({ language: "en", view: "settings", configuration: config, settingsLoaded: true });
    act(() => { root.render(<App initialState={state} api={api} />); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    const save = container.querySelector<HTMLButtonElement>(".settings-actions .save-button");
    assert.ok(save);
    act(() => { save!.click(); save!.click(); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    assert.equal(saveCalls, 1);
    resolveSave?.({ configuration: config });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
  });
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
  const staleRequest = settingsSaveRequest({ ...draft, providers: { provider: { kind: "openai_compat", api_key: "stale-revealed-value" } } }, {}, {});
  assert.equal(staleRequest.providers?.provider?.api_key, undefined);
});

test("T07 missing optional model fields stay null instead of becoming invalid empty strings", () => {
  const state = createInitialState({ configuration: { default_model: "provider/model", default_permission_mode: "default", providers: { provider: { kind: "openai_compat", base_url: "https://gateway.example/v1", api_key_configured: true } }, models: { "provider/model": { provider_profile_id: "provider", remote_id: "served-model" } } }, settingsLoaded: true });
  const markup = renderToStaticMarkup(<SettingsView state={state} onRevealApiKey={undefined} onBack={() => undefined} onSave={() => undefined} onThemeChange={() => undefined} onLanguageChange={() => undefined} />);
  assert.match(markup, />served-model</u);
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
  assert.match(css, /\.timeline-entry--user \.timeline-content\s*\{[^}]*color:\s*var\(--on-accent\);[^}]*background:\s*var\(--accent-user\)/s);
  assert.match(css, /--accent-user:\s*#4a50b8;[^\n]*--accent-action:\s*#5158c9;[^\n]*--on-accent:\s*#fff/s);
  assert.match(css, /@media \(prefers-color-scheme: light\)[\s\S]*\.theme-system[\s\S]*--text:\s*#202027/s);
  assert.match(css, /\.theme-light\s*\{[^}]*--bg:\s*#f5f5f7;[^}]*--accent:\s*#565fd7/s);
  assert.match(css, /\.settings-view__busy-status::before\s*\{[^}]*content:\s*"";[^}]*animation:\s*settings-save-spin/s);
  assert.match(css, /\.settings-view\[aria-busy="true"\][^}]*opacity:\s*1[^}]*background:\s*var\(--raised\)/s);
  assert.match(css, /@keyframes\s+settings-save-spin\s*\{[^}]*transform:\s*rotate\(360deg\)/s);
  assert.ok(contrastRatio("#aaaab4", "#2b2b2f") >= 4.5, "dark busy disabled text remains readable on raised controls");
  assert.ok(contrastRatio("#5f606b", "#e3e3e9") >= 4.5, "light busy disabled text remains readable on raised controls");
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

test("T05 Runtime context measurement labels come from zh/en locale resources", () => {
  const state = createInitialState({ contextUsage: { used_tokens: 12, budget_tokens: 100, available: true, measurement: "estimate", source: "application" } });
  const english = renderLanguage("en", <RuntimePanel state={state} onPanelModeChange={() => undefined} />);
  const chinese = renderLanguage("zh-CN", <RuntimePanel state={state} onPanelModeChange={() => undefined} />);
  assert.match(english, /12 \/ 100 · estimate/);
  assert.match(chinese, /12 \/ 100 · 估算/);
  assert.doesNotMatch(english, /不可用|估算/u);
  assert.doesNotMatch(chinese, /Unavailable|estimate/u);
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
  assert.equal(state.activeTurn, true);
  assert.equal(state.terminalStatusPending, true);
});

test("T05 failed turns settle reasoning tail while removing only assistant preview", () => {
  let state = createInitialState();
  state = reduceRendererState(state, { type: "agent_event", event: { type: "reasoning_delta", run_id: "run-one", turn_id: "turn-one", message_id: "reason-one", text: "failed reasoning tail" } });
  state = reduceRendererState(state, { type: "agent_event", event: { type: "assistant_message_delta", run_id: "run-one", turn_id: "turn-one", message_id: "answer-one", text: "failed preview" } });
  state = reduceRendererState(state, { type: "agent_event", event: { type: "turn_failed", run_id: "run-one", turn_id: "turn-one", termination_reason: "provider_error", failure_reason: "provider_request" } });
  assert.deepEqual(state.timeline.filter((entry) => entry.kind === "reasoning").map((entry) => ({ text: entry.text, status: entry.status, streaming: entry.streaming })), [{ text: "failed reasoning tail", status: "completed", streaming: false }]);
  assert.equal(state.timeline.some((entry) => entry.text === "failed preview"), false);
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
  const markup = renderToStaticMarkup(<SettingsView state={state} onRevealApiKey={undefined} onBack={() => undefined} onSave={() => undefined} onThemeChange={() => undefined} onLanguageChange={() => undefined} />);
  assert.match(markup, />Model</);
  assert.doesNotMatch(markup, /context window|max output tokens|legacy-settings-editor/i);
  assert.equal(parseOptionalPositiveInteger("128000"), 128000);
  assert.equal(parseOptionalPositiveInteger(""), null);
  const identityDraft = { providers: { fake: { kind: "fake" } }, models: { "fake/model": { provider_profile_id: "fake" } } };
  const identityRequest = configurationRequest(identityDraft);
  assert.deepEqual(Object.keys(identityRequest.providers ?? {}), ["fake"], "provider identity stays as the configuration key");
  assert.equal(identityRequest.models?.["fake/model"]?.provider_profile_id, "fake");
  assert.doesNotMatch(markup, /model_ref|modelReference|Profile ID|配置 ID/u);
});

test("Prompt 1 hidden Runtime is restored only from the chat header", () => {
  const markup = renderToStaticMarkup(<App initialState={createInitialState({ panelMode: "hidden" })} api={undefined} />);
  assert.match(markup, /title="打开 Runtime 面板" aria-label="打开 Runtime 面板"/);
  assert.match(markup, /aria-expanded="false" aria-controls="runtime-panel"/);
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
  const forbiddenRendererTokens = ["rename" + "ModelRef", "model" + "-1", "clear" + "Key"];
  for (const token of forbiddenRendererTokens) assert.doesNotMatch(settingsSource + require("node:fs").readFileSync(new URL("../src/renderer/locales/en.ts", import.meta.url), "utf8"), new RegExp(token.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&")));
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
  assert.match(dockedMarkup, /aria-label="关闭 Runtime 面板"/);
  assert.match(dockedMarkup, /aria-expanded="true"/);
  assert.match(dockedMarkup, /aria-controls="runtime-panel"/);
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

test("Prompt 4 timeline follows the tail only while near the bottom and re-arms after a session boundary", async () => {
  assert.equal(isNearBottom({ scrollTop: 428, scrollHeight: 1000, clientHeight: 500 }), true);
  assert.equal(isNearBottom({ scrollTop: 427, scrollHeight: 1000, clientHeight: 500 }), false);
  assert.equal(isNearBottom({ scrollTop: 0, scrollHeight: 500, clientHeight: 500 }), true);
  const element = { scrollTop: 0, scrollHeight: 1200, clientHeight: 500 };
  scrollTimelineToBottom(element);
  assert.equal(element.scrollTop, 700);

  class TestResizeObserver {
    static instances: TestResizeObserver[] = [];
    private readonly callback: ResizeObserverCallback;
    target: Element | null = null;

    constructor(callback: ResizeObserverCallback) {
      this.callback = callback;
      TestResizeObserver.instances.push(this);
    }

    observe(target: Element): void {
      this.target = target;
    }

    disconnect(): void {
      this.target = null;
    }

    trigger(): void {
      this.callback([], this as unknown as ResizeObserver);
    }
  }
  const globalObject = globalThis as unknown as Record<string, unknown>;
  const previousResizeObserver = globalObject.ResizeObserver;
  Object.defineProperty(globalObject, "ResizeObserver", { configurable: true, writable: true, value: TestResizeObserver });
  try {
    await withRendererDom(async (dom, container, root) => {
      const entry = (id: string, text: string) => ({ id, kind: "assistant" as const, text, status: "completed" as const });
      let entries = [entry("one", "one")];
      let scrollTop = 0;
      let scrollHeight = 1000;
      const renderTimeline = async (sessionKey: string) => {
        act(() => {
          root.render(<LanguageProvider value="en"><ChatTimeline entries={entries} todo={[]} sessionKey={sessionKey} /></LanguageProvider>);
        });
        await new Promise<void>((resolve) => setTimeout(resolve, 0));
      };

      await renderTimeline("project:session-a:1");
      const timeline = container.querySelector<HTMLElement>(".timeline");
      assert.ok(timeline);
      Object.defineProperties(timeline, {
        scrollTop: { configurable: true, get: () => scrollTop, set: (value: number) => { scrollTop = value; } },
        scrollHeight: { configurable: true, get: () => scrollHeight },
        clientHeight: { configurable: true, get: () => 400 },
      });
      const timelineObserver = () => TestResizeObserver.instances.find((observer) => observer.target === timeline);
      assert.ok(timelineObserver(), "production timeline must install ResizeObserver");

      // A real timeline size change while at the tail follows new content.
      scrollTop = 600;
      act(() => { timeline?.dispatchEvent(new dom.window.Event("scroll", { bubbles: true })); });
      scrollHeight = 1200;
      act(() => { timelineObserver()?.trigger(); });
      assert.equal(scrollTop, 800);

      // Scrolling well above the threshold opts out; a real ResizeObserver
      // callback from a subsequent content change does not steal the position.
      scrollTop = 450;
      act(() => { timeline?.dispatchEvent(new dom.window.Event("scroll", { bubbles: true })); });
      entries = [...entries, entry("three", "three")];
      scrollHeight = 1400;
      await renderTimeline("project:session-a:1");
      assert.equal(scrollTop, 450);
      act(() => { timelineObserver()?.trigger(); });
      assert.equal(scrollTop, 450);

      // Returning to the tail re-enables following for a later real geometry
      // change. No global scroll handler is involved in this assertion.
      scrollTop = 1000;
      act(() => { timeline?.dispatchEvent(new dom.window.Event("scroll", { bubbles: true })); });
      scrollHeight = 1600;
      act(() => { timelineObserver()?.trigger(); });
      assert.equal(scrollTop, 1200);

      // Session replacement scrolls to the new session's end and resets the
      // follow state. A normal rerender in that session still respects scrolling
      // away from the tail.
      entries = [entry("new-one", "new session")];
      scrollHeight = 1800;
      await renderTimeline("project:session-b:2");
      assert.equal(scrollTop, 1400);
      scrollTop = 600;
      act(() => { timeline?.dispatchEvent(new dom.window.Event("scroll", { bubbles: true })); });
      entries = [...entries, entry("new-two", "new tail")];
      scrollHeight = 2000;
      await renderTimeline("project:session-b:2");
      assert.equal(scrollTop, 600);
    });

    await withRendererDom(async (dom, container, root) => {
      const geometryState = createInitialState({
        permissionMode: "default",
        currentModelRef: "local/chat",
        configuration: { models: { "local/chat": { context_window: 128000 } } },
      });
      const geometryEntries = [
        { id: "geometry-1", kind: "assistant" as const, text: "one", status: "completed" as const },
        { id: "geometry-2", kind: "assistant" as const, text: "two", status: "completed" as const },
      ];
      const renderGeometry = async (panelMode: "docked" | "floating") => {
        act(() => {
          root.render(<LanguageProvider value="en"><div className={`app-shell panel-${panelMode}`}>
            <main className="main-content">
              <ChatTimeline entries={geometryEntries} todo={[]} sessionKey="geometry:session" />
              <Composer state={geometryState} onChange={() => undefined} onSubmit={() => undefined} onCommand={() => undefined} onPause={() => undefined} onCancel={() => undefined} />
            </main>
            <RuntimePanel state={{ ...geometryState, panelMode }} onPanelModeChange={() => undefined} />
          </div></LanguageProvider>);
        });
        await new Promise<void>((resolve) => setTimeout(resolve, 0));
        await new Promise<void>((resolve) => setTimeout(resolve, 0));
      };

      await renderGeometry("docked");
      const timeline = container.querySelector<HTMLElement>(".timeline");
      const composer = container.querySelector<HTMLElement>(".composer");
      const main = container.querySelector<HTMLElement>(".main-content");
      assert.ok(timeline);
      assert.ok(composer);
      assert.ok(main);
      let scrollTop = 600;
      let scrollHeight = 1000;
      let clientHeight = 400;
      let composerHeight = 120;
      Object.defineProperties(timeline, {
        scrollTop: { configurable: true, get: () => scrollTop, set: (value: number) => { scrollTop = value; } },
        scrollHeight: { configurable: true, get: () => scrollHeight },
        clientHeight: { configurable: true, get: () => clientHeight },
      });
      composer.getBoundingClientRect = () => ({ x: 0, y: 0, width: 720, height: composerHeight, top: 0, right: 720, bottom: composerHeight, left: 0, toJSON: () => ({}) }) as DOMRect;
      const timelineObserver = () => TestResizeObserver.instances.find((observer) => observer.target === timeline);
      const composerObserver = () => TestResizeObserver.instances.find((observer) => observer.target === composer);
      assert.ok(timelineObserver(), "timeline geometry uses the production ResizeObserver");
      assert.ok(composerObserver(), "composer geometry uses the production ResizeObserver");

      // The Composer's actual measured height is written to its parent and a
      // content-box change then drives the timeline observer.
      act(() => { composerObserver()?.trigger(); });
      assert.equal(main?.style.getPropertyValue("--composer-height"), "120px");
      scrollHeight = 1240;
      act(() => { timelineObserver()?.trigger(); });
      assert.equal(scrollTop, 840);

      // Switching the real RuntimePanel DOM from docked to floating changes
      // the available geometry, but an away-from-tail reader stays put.
      scrollTop = 500;
      act(() => { timeline?.dispatchEvent(new dom.window.Event("scroll", { bubbles: true })); });
      await renderGeometry("floating");
      assert.ok(container.querySelector(".runtime-panel--floating"));
      clientHeight = 460;
      scrollHeight = 1500;
      act(() => { timelineObserver()?.trigger(); });
      assert.equal(scrollTop, 500);

      // Returning to the tail re-enables follow, including a Composer height
      // change observed through its real ResizeObserver.
      scrollTop = scrollHeight - clientHeight;
      act(() => { timeline?.dispatchEvent(new dom.window.Event("scroll", { bubbles: true })); });
      composerHeight = 168;
      act(() => { composerObserver()?.trigger(); });
      assert.equal(main?.style.getPropertyValue("--composer-height"), "168px");
      scrollHeight = 1710;
      act(() => { timelineObserver()?.trigger(); });
      assert.equal(scrollTop, 1250);
    });
  } finally {
    if (previousResizeObserver === undefined) delete globalObject.ResizeObserver;
    else Object.defineProperty(globalObject, "ResizeObserver", { configurable: true, writable: true, value: previousResizeObserver });
  }
});

test("Prompt 4 slash completion supports cyclic keyboard navigation, mouse selection, dismissal, and IME safety", async () => {
  // These are the candidate records returned by Application's built-in
  // command.complete registry for "/".  Keep the DOM fixture on the real
  // protocol shape: slash candidates do not carry a disabled state.
  const registryCandidates = [
    { value: "/clear", canonical: "clear", display: "/clear — 清空当前界面 Transcript", description: "清空当前界面 Transcript", aliases: [], usage: "/clear", argument_prompt: "", matched_alias: null },
    { value: "/model", canonical: "model", display: "/model — 查看或切换当前模型", description: "查看或切换当前模型", aliases: ["models", "m"], usage: "/model [model-ref]", argument_prompt: "model-ref: Model Ref", matched_alias: null },
    { value: "/permission", canonical: "permission", display: "/permission — 查看或切换当前 Run 权限模式", description: "查看或切换当前 Run 权限模式", aliases: [], usage: "/permission [mode]", argument_prompt: "mode: Permission mode", matched_alias: null },
    { value: "/status", canonical: "status", display: "/status — 显示当前 Application 状态", description: "显示当前 Application 状态", aliases: ["s"], usage: "/status", argument_prompt: "", matched_alias: null },
    { value: "/quit", canonical: "quit", display: "/quit — 退出当前 Interface", description: "退出当前 Interface", aliases: ["q", "exit"], usage: "/quit", argument_prompt: "", matched_alias: null },
    { value: "/compact", canonical: "compact", display: "/compact — 压缩上下文", description: "压缩上下文", aliases: ["c"], usage: "/compact", argument_prompt: "", matched_alias: null },
    { value: "/plan", canonical: "plan", display: "/plan — 进入规划模式", description: "进入规划模式", aliases: [], usage: "/plan", argument_prompt: "", matched_alias: null },
    { value: "/new", canonical: "new", display: "/new — 创建新会话", description: "创建新会话", aliases: [], usage: "/new", argument_prompt: "", matched_alias: null },
    { value: "/resume", canonical: "resume", display: "/resume — 恢复会话", description: "恢复会话", aliases: [], usage: "/resume [session-id]", argument_prompt: "session-id", matched_alias: null },
    { value: "/do", canonical: "do", display: "/do — 进入默认执行模式", description: "进入默认执行模式", aliases: ["build"], usage: "/do", argument_prompt: "", matched_alias: null },
    { value: "/help", canonical: "help", display: "/help — 显示命令帮助", description: "显示命令帮助", aliases: ["h", "?"], usage: "/help [command]", argument_prompt: "command", matched_alias: null },
  ];
  const baseState = createInitialState({
    composerText: "/",
    commandCandidates: registryCandidates,
  });
  assert.deepEqual(baseState.commandCandidates.map((candidate) => candidate.value), ["/clear", "/model", "/permission", "/status", "/quit", "/compact", "/plan", "/new", "/resume", "/do", "/help"]);
  assert.equal(nextCompletionIndex(baseState.commandCandidates, 0, 1), 1);
  const visibleCandidates = baseState.commandCandidates.filter((candidate) => !["/clear", "/quit", "/resume", "/permission", "/help"].includes(candidate.value));
  assert.deepEqual(visibleCandidates.map((candidate) => candidate.value), ["/model", "/status", "/compact", "/plan", "/new", "/do"]);
  assert.equal(nextCompletionIndex(visibleCandidates, 0, 1), 1);
  assert.equal(nextCompletionIndex(visibleCandidates, 0, -1), 5);
  assert.equal(edgeCompletionIndex(baseState.commandCandidates, false), 0);
  assert.equal(edgeCompletionIndex(baseState.commandCandidates, true), 10);

  await withRendererDom(async (dom, container, root) => {
    const changes: string[] = [];
    const submitted: string[] = [];
    const dismissed: number[] = [];
    const scrollCalls: unknown[] = [];
    Object.defineProperty(dom.window.HTMLElement.prototype, "scrollIntoView", { configurable: true, value: (options: unknown) => { scrollCalls.push(options); } });
    const renderComposer = async (key: string, state = baseState) => {
      act(() => {
        root.render(<LanguageProvider value="en"><Composer key={key} state={state} onChange={(value) => changes.push(value)} onSubmit={(value) => submitted.push(value)} onCommand={() => undefined} onPause={() => undefined} onCancel={() => undefined} onDismissCompletion={() => dismissed.push(1)} /></LanguageProvider>);
      });
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
    };
    const press = async (textarea: HTMLTextAreaElement, key: string, init: KeyboardEventInit = {}) => {
      let event!: KeyboardEvent;
      act(() => {
        textarea.focus();
        event = new dom.window.KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...init });
        textarea.dispatchEvent(event);
      });
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
      return event;
    };
    const activeIndex = () => Array.from(container.querySelectorAll<HTMLButtonElement>(".command-menu button")).findIndex((button) => button.classList.contains("is-active"));

    await renderComposer("arrow");
    const textarea = container.querySelector<HTMLTextAreaElement>("textarea");
    assert.ok(textarea);
    const options = () => Array.from(container.querySelectorAll<HTMLButtonElement>(".command-menu button"));
    assert.equal(activeIndex(), 0);
    await press(textarea!, "ArrowDown");
    assert.equal(activeIndex(), 1);
    await press(textarea!, "ArrowDown");
    assert.equal(activeIndex(), 2);
    assert.ok(scrollCalls.some((options) => typeof options === "object" && options !== null && (options as { block?: unknown }).block === "nearest"), "active completion should scroll into view with nearest alignment");
    await press(textarea!, "ArrowUp");
    assert.equal(activeIndex(), 1);
    await press(textarea!, "ArrowUp");
    assert.equal(activeIndex(), 0);
    await press(textarea!, "ArrowUp");
    assert.equal(activeIndex(), 5, "ArrowUp wraps to the last visible candidate");
    await press(textarea!, "ArrowDown");
    assert.equal(activeIndex(), 0, "ArrowDown wraps to the first registry candidate");
    await press(textarea!, "Home");
    assert.equal(activeIndex(), 0);
    await press(textarea!, "End");
    assert.equal(activeIndex(), 5);

    act(() => { options()[1]?.dispatchEvent(new dom.window.MouseEvent("mouseover", { bubbles: true })); });
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
    assert.equal(activeIndex(), 1, "mouse hover and keyboard active state share one index");
    act(() => { options().find((button) => button.textContent?.startsWith("/model"))?.click(); });
    assert.deepEqual(changes.at(-1), "/model ");
    assert.equal(container.querySelector(".command-menu"), null);

    // Application complete("  /m") returns /model then /help. Selecting the
    // first real candidate replaces only the current token in the DOM path.
    const replacementState = createInitialState({
      composerText: "  /m",
      commandCandidates: registryCandidates.filter((candidate) => candidate.value === "/model" || candidate.value === "/help"),
    });
    await renderComposer("replacement", replacementState);
    const replacementArea = container.querySelector<HTMLTextAreaElement>("textarea");
    assert.ok(replacementArea);
    const replacementOptions = () => Array.from(container.querySelectorAll<HTMLButtonElement>(".command-menu button"));
    assert.deepEqual(replacementOptions().map((button) => button.querySelector("span")?.textContent), ["/model"]);
    const replacementEvent = await press(replacementArea!, "Enter");
    assert.equal(replacementEvent.defaultPrevented, true);
    assert.deepEqual(changes.at(-1), "  /model ");
    assert.equal(submitted.length, 0);
    assert.equal(container.querySelector(".command-menu"), null);

    await renderComposer("enter");
    const enterArea = container.querySelector<HTMLTextAreaElement>("textarea");
    assert.ok(enterArea);
    const enterEvent = await press(enterArea!, "Enter");
    assert.equal(enterEvent.defaultPrevented, true);
    assert.deepEqual(changes.at(-1), "/model ");
    assert.equal(submitted.length, 0, "completion Enter must not submit the prompt");
    assert.equal(container.querySelector(".command-menu"), null);

    await renderComposer("tab");
    const tabArea = container.querySelector<HTMLTextAreaElement>("textarea");
    assert.ok(tabArea);
    const tabEvent = await press(tabArea!, "Tab");
    assert.equal(tabEvent.defaultPrevented, true);
    assert.deepEqual(changes.at(-1), "/model ");
    assert.equal(container.querySelector(".command-menu"), null);

    await renderComposer("escape");
    const escapeArea = container.querySelector<HTMLTextAreaElement>("textarea");
    assert.ok(escapeArea);
    const escapeEvent = await press(escapeArea!, "Escape");
    assert.equal(escapeEvent.defaultPrevented, true);
    assert.equal(container.querySelector(".command-menu"), null);
    assert.equal(dismissed.length, 1);

    await renderComposer("ime");
    const imeArea = container.querySelector<HTMLTextAreaElement>("textarea");
    assert.ok(imeArea);
    const composingEvent = await press(imeArea!, "Enter", { isComposing: true });
    assert.equal(composingEvent.defaultPrevented, false);
    assert.equal(submitted.length, 0);
    assert.notEqual(container.querySelector(".command-menu"), null);
    const keyCodeEvent = await press(imeArea!, "Enter", { keyCode: 229 });
    assert.equal(keyCodeEvent.defaultPrevented, false);
    assert.equal(submitted.length, 0);
  });
});

test("T06 slash completion uses canonical values and locale-only descriptions", async () => {
  const candidates = [
    { value: "/model", canonical: "model", display: "/model — 查看或切换当前模型", description: "查看或切换当前模型" },
    { value: "/status", canonical: "status", display: "/status — 显示当前 Application 状态", description: "显示当前 Application 状态" },
    { value: "/compact", canonical: "compact", display: "/compact — 压缩上下文", description: "压缩上下文" },
    { value: "/plan", canonical: "plan", display: "/plan — 进入规划模式", description: "进入规划模式" },
    { value: "/new", canonical: "new", display: "/new — 创建新会话", description: "创建新会话" },
    { value: "/do", canonical: "do", display: "/do — 进入默认执行模式", description: "进入默认执行模式" },
    { value: "/mystery", canonical: "mystery", display: "/mystery — 未知命令说明", description: "未知命令说明" },
  ];
  const state = createInitialState({ composerText: "/", commandCandidates: candidates });
  const expected = {
    "/model": { en: "View or switch the current model", zh: "查看或切换当前模型" },
    "/status": { en: "Show current Application status", zh: "显示当前 Application 状态" },
    "/compact": { en: "Compact context", zh: "压缩上下文" },
    "/plan": { en: "Enter planning mode", zh: "进入规划模式" },
    "/new": { en: "Create a new Session", zh: "创建新会话" },
    "/do": { en: "Enter default execution mode", zh: "进入默认执行模式" },
  } as const;

  await withRendererDom(async (_dom, container, root) => {
    const renderComposer = async (language: "zh-CN" | "en") => {
      act(() => {
        root.render(<LanguageProvider value={language}><Composer state={state} onChange={() => undefined} onSubmit={() => undefined} onCommand={() => undefined} onPause={() => undefined} onCancel={() => undefined} /></LanguageProvider>);
      });
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
    };
    const readOptions = () => Array.from(container.querySelectorAll<HTMLButtonElement>(".command-menu button")).map((button) => ({
      label: button.querySelector("span")?.textContent ?? "",
      description: button.querySelector("small")?.textContent ?? null,
      text: button.textContent ?? "",
    }));

    await renderComposer("en");
    const english = readOptions();
    assert.deepEqual(english.map((option) => option.label), ["/model", "/status", "/compact", "/plan", "/new", "/do", "/mystery"]);
    for (const option of english.slice(0, 6)) {
      assert.equal(option.description, expected[option.label as keyof typeof expected].en);
      assert.equal(option.text, `${option.label}${option.description}`);
      assert.doesNotMatch(option.text, /[\u4e00-\u9fff]/u, `English command option leaked Chinese text: ${option.text}`);
      assert.doesNotMatch(option.text, /\s—\s/u, "the candidate display field must not be rendered");
    }
    assert.equal(english.at(-1)?.description, null, "unknown candidates use a non-duplicating value-only fallback");
    assert.equal(english.at(-1)?.text, "/mystery");

    await renderComposer("zh-CN");
    const chinese = readOptions();
    assert.deepEqual(chinese.map((option) => option.label), english.map((option) => option.label));
    for (const option of chinese.slice(0, 6)) {
      assert.equal(option.description, expected[option.label as keyof typeof expected].zh);
      assert.equal(option.text, `${option.label}${option.description}`);
    }
    assert.equal(chinese.at(-1)?.description, null, "unknown descriptions are not copied from the Application prose");
    assert.equal(chinese.at(-1)?.text, "/mystery");
  });
});

test("T06 CustomSelect flips by available geometry and restores trigger focus", async () => {
  await withRendererDom(async (dom, container, root) => {
    Object.defineProperty(dom.window, "innerHeight", { configurable: true, value: 240 });
    let rect = { top: 20, bottom: 50, left: 0, right: 180 };
    act(() => {
      root.render(<LanguageProvider value="en"><CustomSelect value="one" label="Choice" options={[{ value: "one", label: "One" }, { value: "two", label: "Two" }]} onChange={() => undefined} /></LanguageProvider>);
    });
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
    const trigger = container.querySelector<HTMLButtonElement>(".custom-select__trigger");
    assert.ok(trigger);
    trigger!.getBoundingClientRect = () => ({ ...rect, width: rect.right - rect.left, height: rect.bottom - rect.top, x: rect.left, y: rect.top, toJSON: () => ({}) }) as DOMRect;
    act(() => { trigger!.click(); });
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
    assert.ok(container.querySelector(".custom-select__list.is-below"), "menu should flip below when the lower viewport has more space");
    rect = { top: 200, bottom: 230, left: 0, right: 180 };
    act(() => { dom.window.dispatchEvent(new dom.window.Event("resize")); });
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
    assert.ok(container.querySelector(".custom-select__list.is-above"), "menu should return above after the available geometry changes");
    const option = container.querySelector<HTMLButtonElement>('.custom-select__list button[role="option"]');
    assert.ok(option);
    act(() => { option!.click(); });
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
    assert.equal(dom.window.document.activeElement, trigger, "closing a select should restore focus to its trigger");
  });
});

test("Prompt 4 Composer keeps mode authority in slash commands while placing permission/model controls in the bottom row", async () => {
  const state = createInitialState({
    composerText: "/p",
    run: { run_id: "run-1", behavior_mode: "plan" },
    permissionMode: "auto",
    currentModelRef: "local/chat",
    modelCandidates: ["local/chat", "remote/fallback"],
    configuration: {
      models: {
        "local/chat": { display_name: "Local Chat", remote_id: "chat-v1", context_window: 128000 },
        "remote/fallback": { remote_id: "remote-chat" },
      },
    },
    commandCandidates: [{ value: "/plan", display: "/plan", description: "Plan" }],
  });
  const commands: string[] = [];
  assert.equal(modelDisplayName(state.configuration, state.currentModelRef), "Local Chat");
  assert.equal(modelDisplayName(state.configuration, "remote/fallback"), "remote-chat");
  const markup = renderLanguage("en", <Composer state={state} onChange={() => undefined} onSubmit={() => undefined} onCommand={(value) => commands.push(value)} onPause={() => undefined} onCancel={() => undefined} />);
  assert.match(markup, /Model: Local Chat/);
  assert.match(markup, /Default permission/);
  assert.match(markup, /\/plan/);
  assert.doesNotMatch(markup, /class="composer-selectors"[^>]*>\s*<button/);

  await withRendererDom(async (dom, container, root) => {
    act(() => { root.render(<LanguageProvider value="en"><Composer state={state} onChange={() => undefined} onSubmit={() => undefined} onCommand={(value) => commands.push(value)} onPause={() => undefined} onCancel={() => undefined} /></LanguageProvider>); });
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
    const permissionTrigger = container.querySelector<HTMLButtonElement>(".composer-selectors .custom-select__trigger");
    const modelTrigger = container.querySelector<HTMLButtonElement>(".composer-model .custom-select__trigger");
    assert.ok(permissionTrigger);
    assert.ok(modelTrigger);
    assert.match(modelTrigger?.getAttribute("aria-label") ?? "", /Model: Local Chat/);
    act(() => { permissionTrigger?.click(); });
    const permissionOption = Array.from(container.querySelectorAll<HTMLButtonElement>(".composer-selectors .custom-select__list button")).find((button) => button.textContent === "Full access");
    assert.ok(permissionOption);
    act(() => { permissionOption?.click(); });
    act(() => { modelTrigger?.click(); });
    const modelOption = Array.from(container.querySelectorAll<HTMLButtonElement>(".composer-model .custom-select__list button")).find((button) => button.textContent === "remote-chat");
    assert.ok(modelOption);
    act(() => { modelOption?.click(); });
    assert.deepEqual(commands, ["/permission full_access", "/model", "/model remote/fallback"]);
  });
});

test("T05 context ring uses only the Application status projection and accessible tooltip text", () => {
  const translateEn = (key: "contextUsage" | "contextTokens" | "contextNotStarted" | "unavailable") => translate("en", key);
  const unavailable = renderLanguage("en", <ContextRing usage={{ used_tokens: 0, budget_tokens: 0, available: false, measurement: "unavailable", source: "unavailable" }} language="en" translate={translateEn} />);
  assert.match(unavailable, /class="context-ring /);
  assert.match(unavailable, /data-used="0"/);
  assert.match(unavailable, /data-budget="0"/);
  assert.match(unavailable, /data-available="false"/);
  assert.match(unavailable, /aria-label="Context usage: 0% · Unavailable · not started"/);
  const estimate = { used_tokens: 0, budget_tokens: 128000, available: true, measurement: "estimate" as const, source: "application" };
  const highUsage = { used_tokens: 115200, budget_tokens: 128000, available: true, measurement: "estimate" as const, source: "application" };
  assert.equal(contextUsagePercent(estimate), 0);
  assert.equal(contextUsagePercent(highUsage), 90);
  const high = renderLanguage("en", <ContextRing usage={highUsage} language="en" translate={translateEn} />);
  assert.match(high, /class="context-ring is-warning"/);
  assert.match(high, /115,200 \/ 128,000 tokens/);
  const critical = renderLanguage("zh-CN", <ContextRing usage={{ used_tokens: 128000, budget_tokens: 128000, available: true, measurement: "exact", source: "application" }} language="zh-CN" translate={(key) => translate("zh-CN", key)} />);
  assert.match(critical, /class="context-ring is-critical"/);
  assert.match(critical, /上下文使用量: 100%/);
  assert.match(critical, /128,000 \/ 128,000 Token/);
  const overBudget = renderLanguage("en", <ContextRing usage={{ used_tokens: 200000, budget_tokens: 4096, available: true, measurement: "exact", source: "application" }} language="en" translate={translateEn} />);
  assert.match(overBudget, /class="context-ring is-critical"/);
  assert.match(overBudget, /data-used="200000"/);
  assert.match(overBudget, /data-budget="4096"/);
  assert.match(overBudget, /data-percent="100"/);
});

test("T05 context usage reducer consumes the Application status and ignores the legacy usage field", () => {
  let state = createInitialState({ currentModelRef: "local/chat", contextUsage: { used_tokens: 9, budget_tokens: 10, available: true, measurement: "estimate", source: "test" } });
  state = reduceRendererState(state, { type: "status_loaded", result: { application: { current_model: "local/chat", context_usage: { used_tokens: 999, budget_tokens: 1, available: true }, context_status: { used_tokens: 64000, budget_tokens: 4096, available: true, measurement: "exact", source: "application" }, compaction_status: { state: "running", trigger: "manual", changed: null } } } });
  assert.deepEqual(state.contextUsage, { used_tokens: 64000, budget_tokens: 4096, available: true, measurement: "exact", source: "application" });
  assert.deepEqual(state.compactionStatus, { state: "running", trigger: "manual", changed: null });
  state = reduceRendererState(state, { type: "status_loaded", result: { application: { context_usage: { used_tokens: 200000, budget_tokens: 128000, available: true } } } });
  assert.deepEqual(state.contextUsage, { used_tokens: 0, budget_tokens: 0, available: false, measurement: "unavailable", source: "unavailable" }, "legacy context_usage must not become a second authority");
  state = reduceRendererState(state, { type: "status_loaded", result: { application: { context_status: { used_tokens: 0, budget_tokens: 2048, available: false, measurement: "unavailable", source: "unavailable" }, compaction_status: { state: "completed", trigger: "manual", changed: true } } } });
  assert.deepEqual(state.contextUsage, { used_tokens: 0, budget_tokens: 2048, available: false, measurement: "unavailable", source: "unavailable" });
  assert.deepEqual(state.compactionStatus, { state: "completed", trigger: "manual", changed: true });
  for (const context_status of [
    { used_tokens: 1, budget_tokens: 2, available: true, source: "application" },
    { used_tokens: 1, budget_tokens: 2, available: true, measurement: "mystery", source: "application" },
    { used_tokens: 1, budget_tokens: 2, available: true, measurement: "estimate", source: "" },
  ]) {
    state = reduceRendererState(state, { type: "status_loaded", result: { application: { context_status } } });
    assert.equal(state.contextUsage.available, false, "incomplete/invalid Context DTO must be unavailable");
    assert.equal(state.contextUsage.budget_tokens, 0, "invalid Context DTO must not retain a guessed denominator");
  }
});

test("T05 Composer gates ordinary sends on the Application compaction status", () => {
  const running = createInitialState({ composerText: "continue", compactionStatus: { state: "running", trigger: "manual", changed: null } });
  const runningMarkup = renderLanguage("en", <Composer state={running} onChange={() => undefined} onSubmit={() => undefined} onCommand={() => undefined} onPause={() => undefined} onCancel={() => undefined} />);
  assert.match(runningMarkup, /<textarea[^>]*disabled=""/u);
  assert.match(runningMarkup, /<button[^>]*title="Send"[^>]*disabled=""/u);
  const settled = createInitialState({ composerText: "continue", compactionStatus: { state: "completed", trigger: "manual", changed: true } });
  const settledMarkup = renderLanguage("en", <Composer state={settled} onChange={() => undefined} onSubmit={() => undefined} onCommand={() => undefined} onPause={() => undefined} onCancel={() => undefined} />);
  assert.doesNotMatch(settledMarkup, /<textarea[^>]*disabled=""/u);
});

test("T07 Composer locks every chat control while Runtime recovery owns the lifecycle", () => {
  const restarting = createInitialState({
    language: "en",
    runtimeState: "restarting",
    composerText: "/",
    commandCandidates: [{ value: "/model", display: "/model" }],
    activeTurn: true,
  });
  const markup = renderLanguage("en", <Composer state={restarting} onChange={() => undefined} onSubmit={() => undefined} onCommand={() => undefined} onPause={() => undefined} onCancel={() => undefined} />);
  assert.match(markup, /class="composer"[^>]*aria-disabled="true"/u);
  assert.match(markup, /placeholder="Runtime is restarting…"/u);
  assert.match(markup, /<textarea[^>]*disabled=""/u);
  assert.match(markup, /<button[^>]*title="Runtime is restarting…"[^>]*disabled=""/u);
  assert.match(markup, /<button[^>]*title="Pause"[^>]*disabled=""/u);
  assert.match(markup, /<button[^>]*title="Cancel"[^>]*disabled=""/u);
  assert.match(markup, /<button[^>]*title="Default permission"[^>]*disabled=""/u);
  assert.match(markup, /<button[^>]*title="Model"[^>]*disabled=""/u);
  assert.doesNotMatch(markup, /class="command-menu"/u, "slash completion cannot issue a completion request during recovery");
});

test("Prompt 4 theme and responsive CSS contracts cover context ring and composer", async () => {
  const css = await (await import("node:fs/promises")).readFile(new URL("../src/renderer/app.css", import.meta.url), "utf8");
  assert.match(css, /\.context-ring__track\s*\{\s*stroke:\s*var\(--line-strong\)/);
  assert.match(css, /\.context-ring__progress\s*\{\s*stroke:\s*var\(--accent-strong\)/);
  assert.match(css, /@media \(max-width: 820px\)[\s\S]*?\.app-shell\.panel-docked \.composer-toolbar\s*\{[^}]*display:\s*grid/);
  assert.match(css, /@media \(max-width: 820px\)[\s\S]*?\.composer-actions\s*\{[^}]*flex-wrap:\s*wrap/);
  assert.match(css, /@media \(max-width: 820px\)[\s\S]*?\.composer-model \.custom-select\s*\{\s*width:\s*min\(230px, calc\(100% - 40px\)\)/);
  assert.match(css, /@media \(max-width: 680px\)[\s\S]*?grid-template-columns:\s*var\(--sidebar-width\) minmax\(0, 1fr\)/);
  assert.match(css, /@media \(max-width: 680px\)[\s\S]*?\.runtime-panel--docked\s*\{\s*display:\s*none/);
  assert.match(css, /@media \(max-width: 680px\)[\s\S]*?\.runtime-panel--floating\s*\{[^}]*width:\s*min\(304px, calc\(100vw - 16px\)\)/);
  assert.doesNotMatch(css, /@media \(max-width: 520px\)[\s\S]*?\.sidebar[^}]*display:\s*none/);
  assert.match(css, /\.runtime-panel--floating\s*\{[^}]*background:\s*var\(--surface\)[^}]*box-shadow:/);
  assert.match(css, /\.timeline-runtime-error\s*\{[^}]*position:\s*sticky;[^}]*overflow:\s*auto;[^}]*background:\s*var\(--surface\)/s);
  assert.match(css, /\.runtime-panel__error\s*\{[^}]*border-left:\s*3px solid var\(--danger\);[^}]*background:\s*var\(--surface\)/s);
  assert.match(css, /@media \(max-width: 520px\)[\s\S]*?\.timeline-runtime-error\s*\{[^}]*flex-wrap:\s*wrap/);
  assert.doesNotMatch(css, /\.configuration-banner\s*\{/u);
  assert.match(css, /\.runtime-heading h2 \.ui-icon\s*\{[^}]*color:\s*var\(--accent-strong\)/);
  assert.match(css, /--composer-height/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)[\s\S]*?scroll-behavior:\s*auto[\s\S]*?transition-duration:\s*0\.01ms/);
  assert.match(renderLanguage("en", <App initialState={createInitialState({ theme: "dark" })} api={undefined} />), /theme-dark/);
  assert.match(renderLanguage("en", <App initialState={createInitialState({ theme: "light" })} api={undefined} />), /theme-light/);
  assert.ok(contrastRatio("#f0f0f3", "#242427") >= 4.5, "dark Runtime error text remains readable on its opaque surface");
  assert.ok(contrastRatio("#202027", "#ffffff") >= 4.5, "light Runtime error text remains readable on its opaque surface");
});
