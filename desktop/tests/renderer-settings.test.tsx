import { test } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { JSDOM } from "jsdom";
import { createInitialState } from "../src/renderer/state";
import { SettingsView, providerGroupSaveRequest, type ConfigurationWrite } from "../src/renderer/SettingsView";
import { LanguageProvider } from "../src/renderer/i18n";

async function withRendererDom<T>(callback: (dom: JSDOM, container: HTMLElement, root: Root) => Promise<T>): Promise<T> {
  const dom = new JSDOM("<!doctype html><html><body><button id=before>Before</button><div id=root></div><button id=after>After</button></body></html>", { url: "http://localhost/" });
  Object.defineProperty(dom.window.HTMLElement.prototype, "scrollTo", { configurable: true, value: () => undefined });
  if (!("attachEvent" in dom.window.HTMLElement.prototype)) {
    Object.defineProperty(dom.window.HTMLElement.prototype, "attachEvent", { configurable: true, value: () => undefined });
    Object.defineProperty(dom.window.HTMLElement.prototype, "detachEvent", { configurable: true, value: () => undefined });
  }
  const container = dom.window.document.getElementById("root");
  assert.ok(container);
  const globalObject = globalThis as unknown as Record<string, unknown>;
  const bindings: Record<string, unknown> = {
    window: dom.window, document: dom.window.document, navigator: dom.window.navigator,
    Node: dom.window.Node, HTMLElement: dom.window.HTMLElement, HTMLButtonElement: dom.window.HTMLButtonElement,
    HTMLInputElement: dom.window.HTMLInputElement, Event: dom.window.Event, MouseEvent: dom.window.MouseEvent,
    KeyboardEvent: dom.window.KeyboardEvent, PointerEvent: dom.window.PointerEvent ?? dom.window.MouseEvent,
    getComputedStyle: dom.window.getComputedStyle, IS_REACT_ACT_ENVIRONMENT: true,
  };
  const previous = new Map<string, unknown>();
  for (const [key, value] of Object.entries(bindings)) {
    previous.set(key, globalObject[key]);
    Object.defineProperty(globalObject, key, { configurable: true, writable: true, value });
  }
  const root = createRoot(container);
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

function baseConfiguration() {
  return {
    default_model: "provider/model",
    default_permission_mode: "default" as const,
    providers: { provider: { kind: "openai_compat", base_url: "https://gateway.example/v1", display_name: "Gateway", api_key_configured: true } },
    models: { "provider/model": { provider_profile_id: "provider", remote_id: "remote-model", display_name: "Model", context_window: 128000, max_output_tokens: 4096, reasoning_effort: "none" } },
  };
}

async function tick() {
  await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
}

function setInput(dom: JSDOM, input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, "value")?.set;
  assert.ok(setter);
  input.focus();
  setter!.call(input, value);
  input.dispatchEvent(new dom.window.InputEvent("input", { bubbles: true, inputType: "insertText", data: value }));
  input.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
  input.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
  input.dispatchEvent(new dom.window.KeyboardEvent("keyup", { bubbles: true, key: "Unidentified" }));
}

test("Settings uses one Provider/Model modal root with transactional Back and Cancel", async () => {
  await withRendererDom(async (dom, container, root) => {
    const saves: ConfigurationWrite[] = [];
    const state = createInitialState({ configuration: baseConfiguration(), settingsLoaded: true });
    act(() => { root.render(<LanguageProvider value="en"><SettingsView state={state} onRevealApiKey={undefined} onBack={() => undefined} onSave={(request) => saves.push(request)} onThemeChange={() => undefined} onLanguageChange={() => undefined} /></LanguageProvider>); });
    await tick();
    const providerRow = container.querySelector<HTMLButtonElement>(".provider-row");
    assert.ok(providerRow);
    providerRow!.focus();
    act(() => { providerRow!.click(); });
    await tick();
    const editor = () => container.querySelector<HTMLElement>(".settings-editor-modal");
    assert.equal(container.querySelectorAll("[role=dialog]").length, 1);
    assert.equal(editor()?.getAttribute("aria-modal"), "true");
    assert.equal(dom.window.document.activeElement?.id, "modal-provider-display-name");
    const editModel = container.querySelector<HTMLButtonElement>('button[aria-label="Edit model Model"]');
    assert.ok(editModel);
    act(() => { editModel!.click(); });
    await tick();
    assert.equal(container.querySelectorAll(".settings-editor-modal").length, 1);
    assert.equal(editor()?.getAttribute("data-settings-editor-step"), "model");
    assert.equal(editor()?.getAttribute("aria-hidden"), null);
    assert.equal((container.querySelector(".settings-nav") as HTMLElement & { inert?: boolean })?.inert, true);
    assert.equal(container.querySelector(".settings-nav")?.getAttribute("aria-hidden"), "true");
    const back = editor()?.querySelector<HTMLButtonElement>('footer button[title="Back to chat"]');
    assert.ok(back);
    act(() => { back!.click(); });
    await tick();
    assert.equal(editor()?.getAttribute("data-settings-editor-step"), "provider");
    const modelEdit = () => [...container.querySelectorAll<HTMLButtonElement>("[data-model-edit-ref]")].find((button) => button.getAttribute("data-model-edit-ref") === "provider/model");
    assert.equal(dom.window.document.activeElement, modelEdit(), "Back restores focus to the re-mounted model trigger");
    const editAgain = modelEdit();
    assert.ok(editAgain);
    act(() => { editAgain!.click(); });
    await tick();
    const applyModel = editor()?.querySelector<HTMLButtonElement>('footer button[title="Apply"]');
    assert.ok(applyModel);
    act(() => { applyModel!.click(); });
    await tick();
    assert.equal(editor()?.getAttribute("data-settings-editor-step"), "provider");
    assert.equal(dom.window.document.activeElement, modelEdit(), "Apply restores focus to the re-mounted model trigger");
    const displayName = container.querySelector<HTMLInputElement>("#modal-provider-display-name");
    assert.ok(displayName);
    act(() => { setInput(dom, displayName!, "Changed only in draft"); });
    await tick();
    const cancel = editor()?.querySelector<HTMLButtonElement>('footer button[title="Cancel"]');
    assert.ok(cancel);
    act(() => { cancel!.click(); });
    await tick();
    assert.equal(editor(), null);
    assert.equal(dom.window.document.activeElement, providerRow);
    assert.equal(container.querySelector('.settings-actions .save-button'), null, "Settings has no global Save action");
    assert.equal(saves.length, 0, "cancelling a Provider/Model editor does not persist its draft");
  });
});

test("Settings displays effective project limits and their source beside the user draft", async () => {
  await withRendererDom(async (_dom, container, root) => {
    const state = createInitialState({
      configuration: {
        ...baseConfiguration(),
        configured: { ...baseConfiguration(), search: { enabled: true, max_results: 8 }, tool_limits: { output_bytes: 16777216, attachment_bytes: 16777216 } },
        effective: { ...baseConfiguration(), search: { enabled: true, max_results: 2 }, tool_limits: { output_bytes: 4096, attachment_bytes: 4096 }, models: { "provider/model": { ...baseConfiguration().models["provider/model"], supports_images: false } } },
        source: { search: "project", vision: "project", tool_limits: "project", attachment_limits: "project" },
      },
      settingsLoaded: true,
    });
    act(() => { root.render(<LanguageProvider value="en"><SettingsView state={state} onRevealApiKey={undefined} onBack={() => undefined} onSave={() => undefined} onThemeChange={() => undefined} onLanguageChange={() => undefined} /></LanguageProvider>); });
    await tick();
    const summary = container.querySelector<HTMLElement>(".settings-effective");
    assert.ok(summary);
    assert.match(summary!.textContent ?? "", /Effective at next safe boundary/u);
    assert.match(summary!.textContent ?? "", /Max results: 2/u);
    assert.match(summary!.textContent ?? "", /Tool output limit \(bytes\): 4096/u);
    assert.match(summary!.textContent ?? "", /Source: project/u);
  });
});

test("Settings keeps API key reveal editor-local and writes only an explicit replacement", async () => {
  await withRendererDom(async (dom, container, root) => {
    const saves: ConfigurationWrite[] = [];
    const state = createInitialState({ configuration: baseConfiguration(), settingsLoaded: true });
    act(() => { root.render(<LanguageProvider value="en"><SettingsView state={state} onRevealApiKey={async () => "saved-secret"} onBack={() => undefined} onSave={(request) => saves.push(request)} onThemeChange={() => undefined} onLanguageChange={() => undefined} /></LanguageProvider>); });
    await tick();
    const row = container.querySelector<HTMLButtonElement>(".provider-row");
    assert.ok(row);
    act(() => { row!.click(); });
    await tick();
    const toggle = container.querySelector<HTMLButtonElement>('#modal-api-key + button[title="Show saved API key"]');
    assert.ok(toggle);
    act(() => { toggle!.click(); });
    await tick();
    await tick();
    const key = container.querySelector<HTMLInputElement>("#modal-api-key");
    assert.ok(key);
    assert.equal(key!.value, "saved-secret");
    assert.doesNotMatch(container.querySelector(".settings-view")?.textContent ?? "", /saved-secret/u);
    const cancel = container.querySelector<HTMLButtonElement>('.settings-editor-modal footer button[title="Cancel"]');
    assert.ok(cancel);
    act(() => { cancel!.click(); });
    await tick();
    act(() => { row!.click(); });
    await tick();
    assert.equal(container.querySelector<HTMLInputElement>("#modal-api-key")?.value, "");
    const replacement = container.querySelector<HTMLInputElement>("#modal-api-key");
    assert.ok(replacement);
    act(() => { setInput(dom, replacement!, "r"); });
    await tick();
    assert.equal(replacement!.value, "r", "the editor-local replacement value follows the first input event");
    act(() => { setInput(dom, replacement!, "re"); });
    await tick();
    assert.equal(replacement!.value, "re", "the editor-local replacement value follows continuous typing");
    act(() => { setInput(dom, replacement!, "replacement-secret"); });
    await tick();
    assert.equal(replacement!.value, "replacement-secret");
    const apply = container.querySelector<HTMLButtonElement>('.settings-editor-modal footer button[title="Apply"]');
    assert.ok(apply);
    act(() => { apply!.click(); });
    await tick();
    assert.equal(saves.length, 1, "applying a Provider group persists it immediately");
    assert.equal(saves[0]?.providers?.provider?.api_key, "replacement-secret");
    assert.equal(JSON.stringify(saves[0]).includes("saved-secret"), false);
  });
});

test("Provider group patches omit untouched saved credentials and include explicit replacements only", () => {
  const before = { providers: { provider: { kind: "openai_compat", api_key_configured: true } }, models: { "provider/model": { provider_profile_id: "provider", remote_id: "remote" } }, default_model: "provider/model" };
  const untouched = providerGroupSaveRequest(before, before, "provider");
  assert.equal(Object.hasOwn(untouched.providers?.provider ?? {}, "api_key"), false);
  assert.equal(Object.hasOwn(untouched.providers?.provider ?? {}, "api_key_configured"), false);
  const replacement = providerGroupSaveRequest(before, before, "provider", "new", true);
  assert.equal(replacement.providers?.provider?.api_key, "new");
});

test("Settings restores App-owned failed field patches and delegates retry", async () => {
  await withRendererDom(async (_dom, container, root) => {
    let retries = 0;
    const state = {
      ...createInitialState({ configuration: { ...baseConfiguration(), search: { enabled: false, max_results: 5 } }, settingsLoaded: true }),
      settingsWriteFailures: 1,
    };
    act(() => { root.render(<LanguageProvider value="en"><SettingsView state={state} pendingWrites={[{ identity: "search.max_results", request: { search: { max_results: 6 } }, revision: 1 }]} onBack={() => undefined} onSave={() => undefined} onRetrySave={async () => { retries += 1; }} onThemeChange={() => undefined} onLanguageChange={() => undefined} /></LanguageProvider>); });
    await tick();
    assert.equal(container.querySelector<HTMLInputElement>("#settings-search-max-results")?.value, "6");
    const retry = container.querySelector<HTMLButtonElement>('.settings-autosave-status button[title="Retry save"]');
    assert.ok(retry);
    act(() => { retry!.click(); });
    await tick();
    assert.equal(retries, 1);
    assert.equal(container.querySelector('.settings-actions .save-button'), null);
  });
});

test("Settings archive filters project and text, then restores the matching original owner", async () => {
  await withRendererDom(async (dom, container, root) => {
    const restored: string[] = [];
    const sessions = [
      { projectKey: "C:/one", projectLabel: "Repo", session: { session_id: "coding-a", title: "Review source", preview: "unique preview", archived: true } },
      { projectKey: "D:/two", projectLabel: "Repo", session: { session_id: "coding-b", title: "Other source", preview: "another preview", archived: true } },
      { projectKey: "uthcode:general", projectLabel: "General", session: { session_id: "general-a", title: "Notes", preview: "other text", archived: true } },
    ];
    const state = createInitialState({ configuration: baseConfiguration(), settingsLoaded: true });
    act(() => { root.render(<LanguageProvider value="en"><SettingsView state={state} onBack={() => undefined} onSave={() => undefined} onThemeChange={() => undefined} onLanguageChange={() => undefined} onLoadArchivedSessions={async () => sessions} onRestoreArchivedSession={async (item) => { restored.push(item.session.session_id); return true; }} /></LanguageProvider>); });
    await tick();
    const archiveNav = container.querySelector<HTMLAnchorElement>('a[href="#settings-archive"]');
    assert.ok(archiveNav);
    act(() => { archiveNav!.click(); });
    await tick();
    await tick();
    assert.deepEqual([...container.querySelectorAll(".settings-archive__group h3")].map((heading) => heading.textContent), ["Repo", "Repo", "General"]);
    const projectFilter = container.querySelector<HTMLButtonElement>("#settings-archive-project-filter");
    assert.ok(projectFilter);
    const chooseProject = async (label: string) => {
      act(() => { projectFilter!.click(); });
      await tick();
      const option = [...dom.window.document.querySelectorAll<HTMLButtonElement>('[role="option"]')].find((item) => item.textContent === label);
      assert.ok(option, "archive project option exists");
      act(() => { option!.click(); });
      await tick();
    };
    await chooseProject("Repo · C:/one");
    assert.deepEqual([...container.querySelectorAll(".settings-archive__item")].map((item) => item.textContent?.includes("Review source")), [true]);
    await chooseProject("General");
    await tick();
    assert.deepEqual([...container.querySelectorAll(".settings-archive__item")].map((item) => item.textContent?.includes("Notes")), [true]);
    await chooseProject("All projects");
    const textFilter = container.querySelector<HTMLInputElement>("#settings-archive-text-filter");
    assert.ok(textFilter);
    act(() => { setInput(dom, textFilter!, "unique preview"); });
    await tick();
    assert.equal(container.querySelectorAll(".settings-archive__item").length, 1);
    assert.match(container.querySelector(".settings-archive__item")?.textContent ?? "", /Review source/u);
    const restore = container.querySelector<HTMLButtonElement>('.settings-archive__item button[title="Restore and open"]');
    assert.ok(restore);
    act(() => { restore!.click(); });
    await tick();
    assert.deepEqual(restored, ["coding-a"]);
    assert.equal(container.querySelectorAll(".settings-archive__item").length, 0);
  });
});

test("Settings follows the five reference categories, keeps one Archive page, and changes its page title", async () => {
  await withRendererDom(async (_dom, container, root) => {
    const state = createInitialState({
      configuration: {
        ...baseConfiguration(),
        search: { enabled: true, api_key_configured: true, max_results: 5, max_fetch_bytes: 4096, timeout_seconds: 20 },
        tool_limits: { timeout_seconds: 30, output_bytes: 4096, attachment_bytes: 8192 },
      },
      settingsLoaded: true,
    });
    act(() => { root.render(<LanguageProvider value="zh-CN"><SettingsView state={state} onBack={() => undefined} onSave={() => undefined} onThemeChange={() => undefined} onLanguageChange={() => undefined} /></LanguageProvider>); });
    await tick();

    const expected = ["模型与 Provider", "常规", "工具与限制", "权限与安全", "外观与语言", "已归档会话"];
    assert.deepEqual([...container.querySelectorAll(".settings-nav nav a")].map((item) => item.textContent), expected);
    assert.equal(container.querySelectorAll('.settings-nav nav a[href="#settings-archive"]').length, 1);
    assert.equal(container.querySelectorAll(".settings-content > header h1")[0]?.textContent, "模型与 Provider");
    assert.match(container.querySelector("#settings-providers")?.textContent ?? "", /默认模型/u);
    assert.ok(container.querySelector("#settings-tools #settings-search-enabled"));
    assert.ok(container.querySelector("#settings-tools #settings-tool-output"));
    assert.ok(container.querySelector("#settings-security"));
    assert.ok(container.querySelector("#settings-appearance"));
    assert.ok(container.querySelector("#settings-archive .settings-archive__filters"));
    assert.match(container.querySelector("#settings-general")?.textContent ?? "", /UthCode Desktop/u);
    assert.equal(container.querySelector(".settings-nav .eyebrow, .settings-content > header .eyebrow"), null, "Settings omits the repeated product eyebrow");

    const archive = container.querySelector<HTMLAnchorElement>('a[href="#settings-archive"]');
    assert.ok(archive);
    act(() => { archive!.click(); });
    await tick();
    assert.equal(container.querySelector(".settings-content > header h1")?.textContent, "已归档会话");
    assert.equal(container.querySelector("#settings-archive")?.getAttribute("aria-hidden"), null);

    const security = container.querySelector<HTMLAnchorElement>('a[href="#settings-security"]');
    assert.ok(security);
    act(() => { security!.click(); });
    await tick();
    assert.equal(container.querySelector(".settings-content > header h1")?.textContent, "权限与安全");
    assert.equal(container.querySelector("#settings-security")?.getAttribute("aria-hidden"), null);
  });
});

test("Settings search opens and focuses the matching Provider field without indexing values", async () => {
  await withRendererDom(async (dom, container, root) => {
    const state = createInitialState({
      configuration: {
        ...baseConfiguration(),
        search: { enabled: true, api_key_configured: true, max_results: 5 },
      },
      settingsLoaded: true,
    });
    act(() => { root.render(<LanguageProvider value="en"><SettingsView state={state} onBack={() => undefined} onSave={() => undefined} onThemeChange={() => undefined} onLanguageChange={() => undefined} /></LanguageProvider>); });
    await tick();
    const search = container.querySelector<HTMLInputElement>("#settings-global-search-input");
    assert.ok(search);
    act(() => { setInput(dom, search!, "base url"); });
    await tick();
    const fieldResult = [...container.querySelectorAll<HTMLButtonElement>(".settings-global-search__results button")].find((button) => button.querySelector("span")?.textContent === "Base URL" && button.querySelector("small")?.textContent === "Protocol 1");
    assert.ok(fieldResult);
    act(() => { fieldResult!.click(); });
    await tick();
    const editor = container.querySelector<HTMLElement>('[role="dialog"][data-settings-editor-step="provider"]');
    const baseUrl = editor?.querySelector<HTMLInputElement>("#modal-base-url");
    assert.ok(baseUrl, "Base URL search opens the Provider editor");
    assert.equal(dom.window.document.activeElement, baseUrl, "search focuses the matching editable field");
    act(() => { editor?.querySelector<HTMLButtonElement>('footer button[title="Cancel"]')?.click(); });
    await tick();
    act(() => { setInput(dom, search!, "credential-that-is-not-a-label"); });
    await tick();
    assert.match(container.querySelector(".settings-global-search__results")?.textContent ?? "", /No matching settings/u);
    act(() => { setInput(dom, search!, ""); });
    await tick();
    assert.equal(container.querySelector(".settings-global-search__results"), null);
    assert.equal(container.querySelector(".settings-global-search__clear"), null);
  });
});

test("Settings search indexes editable Provider and Model labels and focuses each exact control", async () => {
  await withRendererDom(async (dom, container, root) => {
    const state = createInitialState({ configuration: baseConfiguration(), settingsLoaded: true });
    act(() => { root.render(<LanguageProvider value="en"><SettingsView state={state} onBack={() => undefined} onSave={() => undefined} onThemeChange={() => undefined} onLanguageChange={() => undefined} /></LanguageProvider>); });
    await tick();
    const search = container.querySelector<HTMLInputElement>("#settings-global-search-input");
    assert.ok(search);
    const cases = [
      { query: "provider name", label: "Provider name", context: "Protocol 1", step: "provider", selector: "#modal-provider-display-name" },
      { query: "protocol", label: "Protocol", context: "Protocol 1", step: "provider", selector: "#modal-protocol" },
      { query: "api key", label: "API Key", context: "Protocol 1", step: "provider", selector: "#modal-api-key", hidden: true },
      { query: "remote model id", label: "Remote model ID", context: "Model 1", step: "model", selector: '[id$="-remote"]' },
      { query: "display name", label: "Display name", context: "Model 1", step: "model", selector: '[id$="-display"]' },
      { query: "context window", label: "Context window", context: "Model 1", step: "model", selector: '[id$="-context"]' },
      { query: "max output tokens", label: "Max output tokens", context: "Model 1", step: "model", selector: '[id$="-output"]' },
      { query: "reasoning effort", label: "Reasoning effort", context: "Model 1", step: "model", selector: '[id$="-reasoning"]' },
      { query: "supports image input", label: "Supports image input", context: "Model 1", step: "model", selector: '[id$="-supports"]' },
      { query: "use as default", label: "Use as default model", context: "Model 1", step: "model", selector: '[id$="-default"]' },
    ] as const;
    for (const item of cases) {
      act(() => { setInput(dom, search!, item.query); });
      await tick();
      const result = [...container.querySelectorAll<HTMLButtonElement>(".settings-global-search__results button")]
        .find((button) => button.querySelector("span")?.textContent === item.label && button.querySelector("small")?.textContent === item.context);
      assert.ok(result, `search includes ${item.label} for ${item.context}`);
      act(() => { result!.click(); });
      await tick();
      const editor = container.querySelector<HTMLElement>(`[role="dialog"][data-settings-editor-step="${item.step}"]`);
      const field = editor?.querySelector<HTMLElement>(item.selector);
      assert.ok(field, `${item.label} search opens the matching editor control`);
      assert.equal(dom.window.document.activeElement, field, `${item.label} search focuses the exact control`);
      if ("hidden" in item && item.hidden) {
        assert.equal((field as HTMLInputElement).type, "password", "search does not reveal or index the saved API key");
        assert.equal((field as HTMLInputElement).value, "", "the saved key remains absent from the renderer draft");
      }
      act(() => { editor?.querySelector<HTMLButtonElement>('footer button[title="Cancel"]')?.click(); });
      await tick();
    }
    for (const configuredValue of ["128000", "4096", "remote-model", "gateway.example"]) {
      act(() => { setInput(dom, search!, configuredValue); });
      await tick();
      assert.match(container.querySelector(".settings-global-search__results")?.textContent ?? "", /No matching settings/u, `${configuredValue} is not part of the search index`);
    }
  });
});

test("Settings search opens the supports-images model field without indexing configured values", async () => {
  await withRendererDom(async (dom, container, root) => {
    const saves: ConfigurationWrite[] = [];
    const state = createInitialState({ configuration: baseConfiguration(), settingsLoaded: true });
    act(() => { root.render(<LanguageProvider value="zh-CN"><SettingsView state={state} onBack={() => undefined} onSave={(request) => { saves.push(request); }} onThemeChange={() => undefined} onLanguageChange={() => undefined} /></LanguageProvider>); });
    await tick();
    const search = container.querySelector<HTMLInputElement>("#settings-global-search-input");
    assert.ok(search);
    act(() => { setInput(dom, search!, "支持图片输入"); });
    await tick();
    const result = container.querySelector<HTMLButtonElement>(".settings-global-search__results button");
    assert.ok(result);
    act(() => { result!.click(); });
    await tick();
    const modal = container.querySelector<HTMLElement>('[role="dialog"][data-settings-editor-step="model"]');
    assert.ok(modal, "search opens the selected model editor directly");
    const supportsSwitch = modal.querySelector<HTMLInputElement>('[role="switch"]');
    assert.ok(supportsSwitch);
    assert.equal(supportsSwitch.id.endsWith("-supports"), true);
    assert.equal(supportsSwitch.checked, false);
    assert.ok(supportsSwitch.labels?.[0]?.textContent?.includes("支持图片输入"));
    act(() => { supportsSwitch.click(); });
    await tick();
    assert.equal(supportsSwitch.checked, true, "the switch preserves native checkbox activation semantics");
    const applyModel = modal.querySelector<HTMLButtonElement>('footer button[title="应用"]');
    assert.ok(applyModel);
    act(() => { applyModel!.click(); });
    await tick();
    assert.equal(container.querySelector('[role="dialog"]')?.getAttribute("data-settings-editor-step"), "provider");
    const cancelEditor = container.querySelector<HTMLButtonElement>('[role="dialog"] footer button[title="取消"]');
    assert.ok(cancelEditor);
    act(() => { cancelEditor!.click(); });
    await tick();
    assert.equal(saves.length, 0, "the Model editor keeps its existing draft and Cancel persistence boundary");
    assert.ok(container.querySelector(".settings-global-search__results"), "search text remains available without scanning the modal");
  });
});

test("Settings boolean controls expose compact switch semantics and autosave", async () => {
  await withRendererDom(async (_dom, container, root) => {
    const saves: ConfigurationWrite[] = [];
    const state = createInitialState({ configuration: { ...baseConfiguration(), search: { enabled: false } }, settingsLoaded: true });
    act(() => { root.render(<LanguageProvider value="en"><SettingsView state={state} onBack={() => undefined} onSave={(request) => saves.push(request)} onThemeChange={() => undefined} onLanguageChange={() => undefined} /></LanguageProvider>); });
    await tick();
    const searchSwitch = container.querySelector<HTMLInputElement>('#settings-search-enabled[role="switch"]');
    assert.ok(searchSwitch);
    assert.equal(searchSwitch.checked, false);
    assert.equal(searchSwitch.disabled, false);
    act(() => { searchSwitch!.click(); });
    await tick();
    assert.deepEqual(saves.at(-1), { search: { enabled: true } });
  });
});

test("CustomSelect portal inherits the selected Settings theme", async () => {
  await withRendererDom(async (dom, container, root) => {
    for (const theme of ["theme-light", "theme-dark", "theme-system"] as const) {
      act(() => { root.render(<div className={theme}><LanguageProvider value="en"><SettingsView state={createInitialState({ configuration: baseConfiguration(), settingsLoaded: true })} onBack={() => undefined} onSave={() => undefined} onThemeChange={() => undefined} onLanguageChange={() => undefined} /></LanguageProvider></div>); });
      await tick();
      const trigger = container.querySelector<HTMLButtonElement>("#settings-theme");
      assert.ok(trigger);
      act(() => { trigger!.click(); });
      await tick();
      assert.ok(dom.window.document.querySelector(".custom-select__portal-scope." + theme), "portal inherits the active theme class");
      act(() => { trigger!.dispatchEvent(new dom.window.KeyboardEvent("keydown", { key: "Escape", bubbles: true })); });
      await tick();
    }
  });
});

test("Provider Apply adopts the safe persisted group and key status without copying the key", async () => {
  await withRendererDom(async (dom, container, root) => {
    const saved = {
      ...baseConfiguration(),
      providers: { provider: { kind: "openai_compat", base_url: "https://saved.example/v1", display_name: "Saved gateway", api_key_configured: true } },
      models: { "provider/model": { provider_profile_id: "provider", remote_id: "saved-remote", display_name: "Saved model", context_window: 128000, max_output_tokens: 4096, reasoning_effort: "none", supports_images: false } },
    };
    let submitted: ConfigurationWrite | null = null;
    const initial = createInitialState({
      configuration: { ...baseConfiguration(), providers: { provider: { ...baseConfiguration().providers.provider, api_key_configured: false } } },
      settingsLoaded: true,
    });
    act(() => { root.render(<LanguageProvider value="en"><SettingsView state={initial} onBack={() => undefined} onSave={async (request) => { submitted = request; return saved; }} onThemeChange={() => undefined} onLanguageChange={() => undefined} /></LanguageProvider>); });
    await tick();
    const row = container.querySelector<HTMLButtonElement>(".provider-row");
    assert.ok(row);
    act(() => { row!.click(); });
    await tick();
    const displayName = container.querySelector<HTMLInputElement>("#modal-provider-display-name");
    const apiKey = container.querySelector<HTMLInputElement>("#modal-api-key");
    assert.ok(displayName && apiKey);
    act(() => { setInput(dom, displayName!, "Draft gateway"); setInput(dom, apiKey!, "one-time-secret"); });
    await tick();
    const apply = container.querySelector<HTMLButtonElement>('.settings-editor-modal footer button[title="Apply"]');
    assert.ok(apply);
    act(() => { apply!.click(); });
    await tick();

    assert.equal(submitted?.providers?.provider?.api_key, "one-time-secret");
    const savedRow = container.querySelector(".provider-row");
    assert.match(savedRow?.textContent ?? "", /Saved gateway/u);
    assert.match(savedRow?.textContent ?? "", /saved\.example/u);
    assert.match(savedRow?.textContent ?? "", /Saved model/u);
    assert.match(container.textContent ?? "", /API key saved/u);
    assert.doesNotMatch(container.textContent ?? "", /one-time-secret/u);
  });
});
