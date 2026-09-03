import { test } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { JSDOM } from "jsdom";
import { createInitialState } from "../src/renderer/state";
import { SettingsView, settingsSaveRequest, type ConfigurationWrite } from "../src/renderer/SettingsView";
import { LanguageProvider } from "../src/renderer/i18n";

async function withRendererDom<T>(callback: (dom: JSDOM, container: HTMLElement, root: Root) => Promise<T>): Promise<T> {
  const dom = new JSDOM("<!doctype html><html><body><button id=before>Before</button><div id=root></div><button id=after>After</button></body></html>", { url: "http://localhost/" });
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
    const save = container.querySelector<HTMLButtonElement>('.settings-actions button[title="Save settings"]');
    assert.ok(save);
    act(() => { save!.click(); });
    await tick();
    assert.equal(saves.at(-1)?.providers?.provider?.display_name, "Gateway");
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
    act(() => { container.querySelector<HTMLButtonElement>('.settings-actions button[title="Save settings"]')!.click(); });
    await tick();
    assert.equal(saves.at(-1)?.providers?.provider?.api_key, "replacement-secret");
    assert.equal(JSON.stringify(saves.at(-1)).includes("saved-secret"), false);
  });
});

test("settingsSaveRequest strips saved metadata and revealed values from untouched providers", () => {
  const request = settingsSaveRequest({ providers: { provider: { kind: "openai_compat", api_key_configured: true, api_key: "revealed" } } }, {}, {});
  assert.equal(request.providers?.provider?.api_key, undefined);
  assert.equal(request.providers?.provider?.api_key_configured, undefined);
  const replaced = settingsSaveRequest({ providers: { provider: { kind: "openai_compat", api_key_configured: true } } }, { provider: "new" }, { provider: true });
  assert.equal(replaced.providers?.provider?.api_key, "new");
});
