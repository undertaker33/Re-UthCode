import { test } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { JSDOM } from "jsdom";
import type { DesktopApi, DesktopAttachmentDraft, DesktopAttachmentInput, JsonValue } from "../src/desktop-api";
import { App } from "../src/renderer/App";
import { Composer } from "../src/renderer/Composer";
import { createInitialState } from "../src/renderer/state";
import { LanguageProvider } from "../src/renderer/i18n";

async function withRendererDom<T>(callback: (dom: JSDOM, container: HTMLElement, root: Root) => Promise<T>): Promise<T> {
  const dom = new JSDOM("<!doctype html><html><body><div id=root></div></body></html>", { url: "http://localhost/" });
  const container = dom.window.document.getElementById("root");
  assert.ok(container);
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

const attachment: DesktopAttachmentDraft = {
  ref: "att-1",
  display_name: "diagram.png",
  mime_type: "image/png",
  size_bytes: 4,
  data_url: "data:image/png;base64,AAAA",
};

function renderComposer(
  state = createInitialState({ language: "en", composerAttachments: [attachment] }),
  callbacks: {
    submitted?: Array<{ text: string; attachments: readonly DesktopAttachmentDraft[] }>;
    imported?: File[];
    removed?: string[];
    chosen?: number;
    pasted?: number;
  } = {},
) {
  return <LanguageProvider value="en"><Composer
    state={state}
    onChange={() => undefined}
    onSubmit={(text, attachments) => callbacks.submitted?.push({ text, attachments })}
    onCommand={() => undefined}
    onPause={() => undefined}
    onCancel={() => undefined}
    onChooseAttachment={() => { callbacks.chosen = (callbacks.chosen ?? 0) + 1; }}
    onPasteAttachment={() => { callbacks.pasted = (callbacks.pasted ?? 0) + 1; }}
    onImportFile={(file) => { callbacks.imported?.push(file); }}
    onRemoveAttachment={(ref) => callbacks.removed?.push(ref)}
  /></LanguageProvider>;
}

test("Composer exposes attachment-only send, preview/remove, and choose/paste controls", () => {
  const callbacks = { submitted: [] as Array<{ text: string; attachments: readonly DesktopAttachmentDraft[] }>, removed: [] as string[], imported: [] as File[] };
  const markup = renderToStaticMarkup(renderComposer(undefined, callbacks));
  assert.match(markup, /diagram\.png/u);
  assert.match(markup, /data:image\/png;base64,AAAA/u);
  assert.match(markup, /Attach/u);
  assert.match(markup, /Paste/u);
  assert.match(markup, /Send/u);
});

test("Composer routes native choose/paste, file drop/paste, remove, and attachment-only submit", async () => {
  const callbacks = { submitted: [] as Array<{ text: string; attachments: readonly DesktopAttachmentDraft[] }>, removed: [] as string[], imported: [] as File[], chosen: 0, pasted: 0 };
  await withRendererDom(async (dom, container, root) => {
    act(() => { root.render(renderComposer(undefined, callbacks)); });
    const choose = container.querySelector<HTMLButtonElement>('button[aria-label="Attach"]');
    const pasteButton = container.querySelector<HTMLButtonElement>('button[aria-label="Paste"]');
    const remove = container.querySelector<HTMLButtonElement>('button[aria-label^="Remove attachment"]');
    const send = container.querySelector<HTMLButtonElement>('button[aria-label="Send"]');
    const composer = container.querySelector<HTMLElement>(".composer");
    assert.ok(choose && pasteButton && remove && send && composer);

    act(() => { choose.click(); pasteButton.click(); });
    assert.equal(callbacks.chosen, 1);
    assert.equal(callbacks.pasted, 1);

    const dropped = new dom.window.File(["drop"], "drop.txt", { type: "text/plain" });
    const drop = new dom.window.Event("drop", { bubbles: true, cancelable: true });
    Object.defineProperty(drop, "dataTransfer", { value: { files: [dropped], types: ["Files"] } });
    act(() => { composer.dispatchEvent(drop); });
    const pasted = new dom.window.File(["paste"], "paste.txt", { type: "text/plain" });
    const paste = new dom.window.Event("paste", { bubbles: true, cancelable: true });
    Object.defineProperty(paste, "clipboardData", { value: { files: [pasted] } });
    act(() => { composer.dispatchEvent(paste); });
    assert.deepEqual(callbacks.imported, [dropped, pasted]);

    act(() => { remove.click(); send.click(); });
    assert.deepEqual(callbacks.removed, ["att-1"]);
    assert.equal(callbacks.submitted.length, 1);
    assert.equal(callbacks.submitted[0].text, "");
    assert.deepEqual(callbacks.submitted[0].attachments, [attachment]);
  });
});

test("App keeps an imported attachment available for retry when turn.start fails", async () => {
  const calls: string[] = [];
  let turnStarts = 0;
  const api: DesktopApi = {
    openProject: async () => null,
    openProjectInExplorer: async () => undefined,
    copyText: async () => undefined,
    closeShell: async () => undefined,
    requestRuntime: async (method) => {
      calls.push(method);
      if (method === "turn.start") {
        turnStarts += 1;
        if (turnStarts === 1) throw new Error("turn rejected");
        return { run_id: "run-retry", turn_id: "turn-retry", status: "running" };
      }
      return method === "status.get" ? { active_turn: false } : {};
    },
    subscribeAgentEvents: () => () => undefined,
    readPreference: async (key) => {
      const values: Record<string, unknown> = {
        theme: "light",
        language: "en",
        panelMode: "docked",
        sidebarWidth: 286,
        runtimePanelWidth: 318,
        recentProjects: [],
        projectAliases: {},
        pinnedProjectKeys: [],
        pinnedSessions: [],
        expandedProjects: {},
        selectedProjectKey: null,
        selectedSessionId: null,
      };
      return values[key] as never;
    },
    writePreference: async () => ({}) as never,
    chooseAttachment: async () => null,
    pasteAttachment: async () => null,
  };
  await withRendererDom(async (_dom, container, root) => {
    act(() => {
      root.render(<App initialState={createInitialState({
        language: "en",
        runtimeState: "ready",
        composerAttachments: [attachment],
      })} api={api} />);
    });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    const send = container.querySelector<HTMLButtonElement>(".composer-send");
    assert.ok(send);
    assert.equal(send.disabled, false);
    act(() => { send!.click(); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    assert.equal(calls.filter((method) => method === "turn.start").length, 1);
    assert.ok(container.querySelector('[aria-label="Attachments"]'));
    assert.match(container.textContent ?? "", /diagram\.png/u);
    act(() => { send!.click(); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    assert.equal(turnStarts, 2);
    assert.equal(container.querySelector('[aria-label="Attachments"]'), null);
  });
});

test("App drops an attachment import or preview that finishes after Session navigation", async () => {
  const projectPath = "C:/attachment-owner";
  let resolveImport: ((value: JsonValue) => void) | null = null;
  let resolvePreview: ((value: JsonValue) => void) | null = null;
  let resolveNewSession: ((value: JsonValue) => void) | null = null;
  const api: DesktopApi = {
    openProject: async () => null,
    openProjectInExplorer: async () => undefined,
    copyText: async () => undefined,
    closeShell: async () => undefined,
    requestRuntime: async (method) => {
      if (method === "attachment.import") return await new Promise<JsonValue>((resolve) => { resolveImport = resolve; });
      if (method === "attachment.preview") return await new Promise<JsonValue>((resolve) => { resolvePreview = resolve; });
      if (method === "session.new") return await new Promise<JsonValue>((resolve) => { resolveNewSession = resolve; });
      if (method === "project.sessions") return { sessions: [] };
      if (method === "status.get") return { active_turn: false };
      return {};
    },
    subscribeAgentEvents: () => () => undefined,
    readPreference: async () => undefined as never,
    writePreference: async () => undefined as never,
    chooseAttachment: async (): Promise<DesktopAttachmentInput> => ({
      name: "late.png",
      mime_type: "image/png",
      data_base64: "AQI=",
    }),
    pasteAttachment: async () => null,
  };
  const state = createInitialState({
    language: "en",
    runtimeState: "ready",
    projects: [{ path: projectPath, projectKey: projectPath, alias: "Attachment owner", pinned: false, sessions: [], catalogFresh: true }],
    selectedProjectKey: projectPath,
    selectedSessionId: null,
  });
  await withRendererDom(async (_dom, container, root) => {
    act(() => { root.render(<App initialState={state} api={api} />); });
    const tick = () => new Promise<void>((resolve) => setTimeout(resolve, 0));
    const flush = async () => { await act(async () => { await tick(); await tick(); }); };
    await flush();

    const choose = container.querySelector<HTMLButtonElement>('button[aria-label="Attach"]');
    assert.ok(choose);
    act(() => { choose!.click(); });
    await flush();
    assert.ok(resolveImport);
    act(() => {
      resolveImport!({
        attachment: {
          ref: "late-attachment",
          session_id: "session-a",
          display_name: "late.png",
          mime_type: "image/png",
          size_bytes: 2,
        },
      });
    });
    await flush();
    assert.ok(resolvePreview);

    const newChat = container.querySelector<HTMLButtonElement>('button[title="New chat"]');
    assert.ok(newChat);
    act(() => { newChat!.click(); });
    await flush();
    assert.ok(resolveNewSession);
    act(() => { resolveNewSession!({ session_id: "session-b", run: null }); });
    await flush();
    act(() => { resolvePreview!({ attachment: { ref: "late-attachment", display_name: "late.png", mime_type: "image/png", size_bytes: 2 } }); });
    await flush();
    assert.equal(container.querySelector('[aria-label="Attachments"]'), null);
  });
});
