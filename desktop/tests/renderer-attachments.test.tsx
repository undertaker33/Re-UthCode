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
import { DocumentPreviewPanel } from "../src/renderer/DocumentPreviewPanel";
import { FileCard } from "../src/renderer/FileCard";
import { RendererErrorBoundary } from "../src/renderer/RendererErrorBoundary";
import { createInitialState } from "../src/renderer/state";
import { LanguageProvider, resources } from "../src/renderer/i18n";

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

function appTestApi(requestRuntime: DesktopApi["requestRuntime"]): DesktopApi {
  return {
    openProject: async () => null,
    openProjectInExplorer: async () => undefined,
    copyText: async () => undefined,
    closeShell: async () => undefined,
    requestRuntime,
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
}

test("Composer exposes attachment-only send and an accessible plus-only attachment control", () => {
  const callbacks = { submitted: [] as Array<{ text: string; attachments: readonly DesktopAttachmentDraft[] }>, removed: [] as string[], imported: [] as File[] };
  const markup = renderToStaticMarkup(renderComposer(undefined, callbacks));
  assert.match(markup, /diagram\.png/u);
  assert.match(markup, /data:image\/png;base64,AAAA/u);
  assert.match(markup, /title="Attach" aria-label="Attach"/u);
  assert.doesNotMatch(markup, /<button[^>]*aria-label="Attach"[^>]*>[^<]*Attach/u);
  assert.doesNotMatch(markup, /aria-label="Paste"/u);
  assert.match(markup, /Send/u);
});

test("RendererErrorBoundary reports only its fixed boundary code and recovers locally", async () => {
  const globalObject = globalThis as unknown as Record<string, unknown>;
  const previousApi = globalObject.uthcode;
  const previousConsoleError = console.error;
  const reported: string[] = [];
  Object.defineProperty(globalObject, "uthcode", { configurable: true, writable: true, value: { reportRendererDiagnostic: async (boundary: string) => { reported.push(boundary); } } });
  console.error = () => undefined;
  function BrokenSurface(): never { throw new Error("secret renderer stack"); }
  try {
    await withRendererDom(async (_dom, container, root) => {
      act(() => { root.render(<LanguageProvider value="en"><RendererErrorBoundary name="timeline"><BrokenSurface /></RendererErrorBoundary></LanguageProvider>); });
      await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
      assert.ok(container.querySelector(".renderer-error-boundary"));
      assert.deepEqual(reported, ["timeline"]);
      assert.doesNotMatch(container.textContent ?? "", /secret renderer stack/u);
    });
  } finally {
    console.error = previousConsoleError;
    if (previousApi === undefined) delete globalObject.uthcode;
    else Object.defineProperty(globalObject, "uthcode", { configurable: true, writable: true, value: previousApi });
  }
});

test("Composer routes choose, file drop/paste, image fallback, text paste, remove, and attachment-only submit", async () => {
  const callbacks = { submitted: [] as Array<{ text: string; attachments: readonly DesktopAttachmentDraft[] }>, removed: [] as string[], imported: [] as File[], chosen: 0, pasted: 0 };
  await withRendererDom(async (dom, container, root) => {
    act(() => { root.render(renderComposer(undefined, callbacks)); });
    const choose = container.querySelector<HTMLButtonElement>('button[aria-label="Attach"]');
    const pasteButton = container.querySelector<HTMLButtonElement>('button[aria-label="Paste"]');
    const remove = container.querySelector<HTMLButtonElement>('button[aria-label^="Remove attachment"]');
    const send = container.querySelector<HTMLButtonElement>('button[aria-label="Send"]');
    const composer = container.querySelector<HTMLElement>(".composer");
    assert.ok(choose && remove && send && composer);
    assert.equal(pasteButton, null);

    act(() => { choose.click(); });
    assert.equal(callbacks.chosen, 1);

    const dropped = new dom.window.File(["drop"], "drop.txt", { type: "text/plain" });
    const drop = new dom.window.Event("drop", { bubbles: true, cancelable: true });
    Object.defineProperty(drop, "dataTransfer", { value: { files: [dropped], types: ["Files"] } });
    act(() => { composer.dispatchEvent(drop); });
    const pasted = new dom.window.File(["paste"], "paste.txt", { type: "text/plain" });
    const paste = new dom.window.Event("paste", { bubbles: true, cancelable: true });
    Object.defineProperty(paste, "clipboardData", { value: { files: [pasted] } });
    act(() => { composer.dispatchEvent(paste); });
    assert.equal(paste.defaultPrevented, true);
    assert.deepEqual(callbacks.imported, [dropped, pasted]);

    const imagePaste = new dom.window.Event("paste", { bubbles: true, cancelable: true });
    Object.defineProperty(imagePaste, "clipboardData", { value: { files: [], types: ["image/png"] } });
    act(() => { composer.dispatchEvent(imagePaste); });
    assert.equal(imagePaste.defaultPrevented, true);
    assert.equal(callbacks.pasted, 1);
    const textPaste = new dom.window.Event("paste", { bubbles: true, cancelable: true });
    Object.defineProperty(textPaste, "clipboardData", { value: { files: [], types: ["text/plain"] } });
    act(() => { composer.dispatchEvent(textPaste); });
    assert.equal(textPaste.defaultPrevented, false);
    assert.equal(callbacks.pasted, 1);

    act(() => { remove.click(); send.click(); });
    assert.deepEqual(callbacks.removed, ["att-1"]);
    assert.equal(callbacks.submitted.length, 1);
    assert.equal(callbacks.submitted[0].text, "");
    assert.deepEqual(callbacks.submitted[0].attachments, [attachment]);
  });
});

test("image cards keep names accessible, show only a bounded thumbnail, and expose draft-only remove", async () => {
  const removed: string[] = [];
  const previews: string[] = [];
  const imageAsset = { ref: "image-ref", display_name: "private-name.png", mime_type: "image/png", size_bytes: 20_000, data_url: attachment.data_url };
  await withRendererDom(async (dom, container, root) => {
    act(() => { root.render(<LanguageProvider value="en"><div>
      <FileCard asset={imageAsset} draft onRemove={() => { removed.push("image-ref"); }} onPreview={async () => { previews.push("preview"); return null; }} />
      <FileCard asset={imageAsset} />
    </div></LanguageProvider>); });
    const cards = [...container.querySelectorAll<HTMLElement>(".file-card")];
    assert.equal(cards.length, 2);
    for (const card of cards) {
      assert.match(card.getAttribute("aria-label") ?? "", /private-name\.png/u);
      assert.equal(card.getAttribute("title"), null);
      assert.equal(card.querySelector(".file-card__meta"), null);
      assert.equal(card.querySelector("img")?.getAttribute("alt"), "private-name.png");
      assert.ok(card.classList.contains("file-card--image-preview"));
    }
    const remove = cards[0].querySelector<HTMLButtonElement>(".file-card__remove-button");
    assert.ok(remove);
    assert.equal(remove.getAttribute("aria-label"), "Remove attachment: private-name.png");
    assert.equal(cards[1].querySelector(".file-card__remove-button"), null);
    act(() => { remove.dispatchEvent(new dom.window.MouseEvent("dblclick", { bubbles: true, cancelable: true })); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    assert.deepEqual(previews, []);
    act(() => { remove.click(); });
    assert.deepEqual(removed, ["image-ref"]);
  });
});

test("App routes attachment copy path through the ref-only Runtime request", async () => {
  const calls: Array<{ method: string; params: unknown }> = [];
  const api = appTestApi(async (method, params) => {
    calls.push({ method, params });
    return method === "status.get" ? { active_turn: false } : {};
  });
  await withRendererDom(async (dom, container, root) => {
    act(() => { root.render(<App api={api} initialState={createInitialState({ language: "en", runtimeState: "ready", composerAttachments: [attachment] })} />); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    const card = container.querySelector<HTMLElement>(".file-card");
    assert.ok(card);
    act(() => { card!.dispatchEvent(new dom.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true })); });
    const copy = [...container.querySelectorAll<HTMLButtonElement>(".file-card__menu button[role='menuitem']")].find((button) => button.textContent === "Copy path");
    assert.ok(copy);
    act(() => { copy!.click(); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    assert.deepEqual(calls.filter(({ method }) => method === "attachment.copy_path"), [{ method: "attachment.copy_path", params: { ref: attachment.ref } }]);
  });
});

test("App preserves imported Markdown preview text and opens its document panel", async () => {
  const markdownInput: DesktopAttachmentInput = { name: "notes.md", mime_type: "text/markdown", data_base64: "Iw==" };
  const markdownAttachment = { ref: "markdown-app-ref", display_name: "notes.md", mime_type: "text/markdown", size_bytes: 2, preview_kind: "text", text: "# notes" };
  const api = appTestApi(async (method) => {
    if (method === "attachment.import") return { attachment: { ref: markdownAttachment.ref, display_name: markdownAttachment.display_name, mime_type: markdownAttachment.mime_type, size_bytes: markdownAttachment.size_bytes } };
    if (method === "attachment.preview") return { attachment: markdownAttachment };
    return method === "status.get" ? { active_turn: false } : {};
  });
  api.chooseAttachment = async () => markdownInput;
  await withRendererDom(async (dom, container, root) => {
    act(() => { root.render(<App api={api} initialState={createInitialState({ language: "en", runtimeState: "ready" })} />); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    const choose = container.querySelector<HTMLButtonElement>('button[aria-label="Attach"]');
    assert.ok(choose);
    act(() => { choose!.click(); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    const card = container.querySelector<HTMLElement>(".file-card");
    assert.ok(card);
    act(() => { card!.dispatchEvent(new dom.window.MouseEvent("dblclick", { bubbles: true })); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    assert.ok(container.querySelector(".document-preview-panel"));
    const shell = container.querySelector<HTMLElement>(".app-shell");
    assert.ok(shell?.classList.contains("document-preview-visible"));
    assert.equal(shell?.style.getPropertyValue("--document-preview-width"), "460px");
    assert.equal(container.querySelector("#runtime-panel"), null, "the document canvas takes the Runtime panel's right grid slot while open");
    const source = [...container.querySelectorAll<HTMLButtonElement>(".document-preview-panel__actions button")].find((button) => button.textContent === "View source");
    assert.ok(source);
    act(() => { source!.click(); });
    assert.match(container.textContent ?? "", /# notes/u);
    const close = container.querySelector<HTMLButtonElement>('[aria-label="Close file preview"]');
    assert.ok(close);
    act(() => { close!.click(); });
    assert.equal(container.querySelector(".document-preview-panel"), null);
    assert.equal(shell?.classList.contains("document-preview-visible"), false);
    assert.ok(container.querySelector("#runtime-panel"), "closing restores the existing Runtime layout mode");
  });
});

test("Python document preview renders syntax tokens with dark and light theme colors", async () => {
  const markup = renderToStaticMarkup(<LanguageProvider value="en"><DocumentPreviewPanel
    preview={{ asset: { display_name: "sample.py", mime_type: "text/x-python" }, text: "# note\ndef greet(name):\n    return str(42)\nmessage = 'ok'" }}
    width={460}
    minWidth={220}
    maxWidth={700}
    onWidthChange={() => undefined}
    onClose={() => undefined}
  /></LanguageProvider>);
  assert.match(markup, /class="token comment"/u);
  assert.match(markup, /class="token keyword"/u);
  assert.match(markup, /class="token operator"/u);
  assert.match(markup, /class="token number"/u);
  assert.match(markup, /class="token function"/u);
  assert.match(markup, /class="token builtin"/u);
  assert.match(markup, /class="token string"/u);

  const css = await (await import("node:fs/promises")).readFile(new URL("../src/renderer/app.css", import.meta.url), "utf8");
  assert.match(css, /\.document-preview-code \.token\.keyword\s*,[^\n]*color:\s*var\(--code-keyword\)/u);
  assert.match(css, /\.document-preview-code \.token\.string\s*,[^\n]*color:\s*var\(--code-string\)/u);
  assert.match(css, /--code-keyword:\s*#c6a0f6/u);
  assert.match(css, /\.theme-light\s*\{[^}]*--code-keyword:\s*#7048a8/su);
  assert.match(css, /\.theme-system\s*\{[^}]*--code-keyword:\s*#7048a8/su);
});

test("document preview composer adapts to conversation-column width", async () => {
  const css = await (await import("node:fs/promises")).readFile(new URL("../src/renderer/app.css", import.meta.url), "utf8");
  assert.match(css, /\.app-shell\.document-preview-visible > main\s*\{[^}]*container-name:\s*conversation;[^}]*container-type:\s*inline-size/su);
  const compactComposer = css.split("@container conversation (max-width: 720px)")[1]?.split("@container conversation (max-width: 380px)")[0];
  const narrowComposer = css.split("@container conversation (max-width: 380px)")[1];
  assert.ok(compactComposer);
  assert.ok(narrowComposer);
  assert.match(compactComposer, /\.composer-toolbar\s*\{[^}]*display:\s*grid;[^}]*grid-template-columns:\s*minmax\(0, 1fr\) auto/su);
  assert.match(compactComposer, /\.composer-model\s*\{[^}]*grid-column:\s*1 \/ -1;[^}]*grid-row:\s*2/su);
  assert.match(compactComposer, /\.composer-send\s*\{[^}]*grid-column:\s*2;[^}]*grid-row:\s*1;[^}]*white-space:\s*nowrap/su);
  assert.match(compactComposer, /\.composer-attachment-actions button\s*\{[^}]*white-space:\s*nowrap/su);
  assert.match(narrowComposer, /\.composer-selectors\s*\{[^}]*display:\s*grid;[^}]*grid-column:\s*1 \/ -1/su);
  assert.match(narrowComposer, /\.composer-model\s*\{[^}]*grid-row:\s*2/su);
  assert.match(narrowComposer, /\.composer-send\s*\{[^}]*grid-row:\s*2/su);
});

test("App keeps a draft and renders attachment removal failures on the local card", async () => {
  const api = appTestApi(async (method) => {
    if (method === "attachment.remove") {
      const error = new Error("attachment denied") as Error & { kind?: string };
      error.kind = "attachment_not_authorized";
      throw error;
    }
    return method === "status.get" ? { active_turn: false } : {};
  });
  await withRendererDom(async (dom, container, root) => {
    act(() => { root.render(<App api={api} initialState={createInitialState({ language: "en", runtimeState: "ready", composerAttachments: [attachment] })} />); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    const card = container.querySelector<HTMLElement>(".file-card");
    assert.ok(card);
    act(() => { card!.dispatchEvent(new dom.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true })); });
    const remove = [...container.querySelectorAll<HTMLButtonElement>(".file-card__menu button[role='menuitem']")].find((button) => button.textContent === "Remove");
    assert.ok(remove);
    act(() => { remove!.click(); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    assert.ok(container.querySelector(".file-card"));
    assert.equal(container.querySelector(".file-card__error")?.textContent, resources.en.fileNotAuthorized);
  });
});

test("Composer attachment cards open Office files and route text previews to the right canvas", async () => {
  const office: DesktopAttachmentDraft = {
    ref: "office-ref",
    display_name: "report.docx",
    mime_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    size_bytes: 12,
  };
  const markdown: DesktopAttachmentDraft = {
    ref: "markdown-ref",
    display_name: "notes.md",
    mime_type: "text/markdown",
    size_bytes: 8,
  };
  const opened: string[] = [];
  const previews: Array<{ ref: string; mode?: string }> = [];
  const documents: string[] = [];
  await withRendererDom(async (_dom, container, root) => {
    act(() => {
      root.render(<LanguageProvider value="en"><Composer
        state={createInitialState({ language: "en", composerAttachments: [office, markdown] })}
        onChange={() => undefined}
        onSubmit={() => undefined}
        onCommand={() => undefined}
        onPause={() => undefined}
        onCancel={() => undefined}
        onChooseAttachment={() => undefined}
        onPasteAttachment={() => undefined}
        onImportFile={() => undefined}
        onRemoveAttachment={() => undefined}
        onOpenAttachment={(ref) => { opened.push(ref); }}
        onRevealAttachment={() => undefined}
        onPreviewAttachment={async (ref, mode) => {
          previews.push({ ref, mode });
          return ref === markdown.ref ? { ...markdown, preview_kind: "text", text: "# notes" } : null;
        }}
        onOpenDocument={(preview) => { documents.push(preview.text); }}
      /></LanguageProvider>);
    });
    const cards = container.querySelectorAll<HTMLElement>(".file-card");
    assert.equal(cards.length, 2);
    act(() => { cards[0]!.dispatchEvent(new _dom.window.MouseEvent("dblclick", { bubbles: true })); });
    assert.deepEqual(opened, [office.ref]);
    act(() => { cards[1]!.dispatchEvent(new _dom.window.MouseEvent("dblclick", { bubbles: true })); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    assert.deepEqual(previews, [{ ref: markdown.ref, mode: "full" }]);
    assert.deepEqual(documents, ["# notes"]);
  });
});

test("executable attachment cards only offer and perform reveal", async () => {
  const opened: string[] = [];
  const revealed: string[] = [];
  await withRendererDom(async (dom, container, root) => {
    act(() => {
      root.render(<LanguageProvider value="en"><FileCard
        asset={{ ref: "script-ref", name: "build.ps1", mime_type: "application/octet-stream", size_bytes: 12 }}
        onOpen={() => { opened.push("open"); }}
        onReveal={() => { revealed.push("reveal"); }}
        onCopyPath={() => { opened.push("copy"); }}
      /></LanguageProvider>);
    });
    const card = container.querySelector<HTMLElement>(".file-card");
    assert.ok(card);
    assert.equal(card.dataset.fileKind, "executable");
    act(() => { card!.dispatchEvent(new dom.window.MouseEvent("dblclick", { bubbles: true })); });
    assert.deepEqual(opened, []);
    assert.deepEqual(revealed, ["reveal"]);
    act(() => { card!.dispatchEvent(new dom.window.MouseEvent("contextmenu", { bubbles: true, cancelable: true })); });
    const menuItems = [...container.querySelectorAll<HTMLButtonElement>(".file-card__menu button[role='menuitem']")].map((button) => button.textContent);
    assert.deepEqual(menuItems, ["Reveal", "Copy path"]);
  });
});

test("full image preview sizing is isolated from attachment thumbnail rules", async () => {
  const css = await (await import("node:fs/promises")).readFile(new URL("../src/renderer/app.css", import.meta.url), "utf8");
  assert.doesNotMatch(css, /[^{}]*\.timeline-attachment\b[^{}]*\bimg\b[^{}]*\{/u, "timeline attachment selectors must not size modal images by ancestry");
  assert.doesNotMatch(css, /[^{}]*\.composer-attachment\b[^{}]*\bimg\b[^{}]*\{/u, "composer attachment selectors must not size modal images by ancestry");
  assert.doesNotMatch(css, /\.timeline-attachment__fallback|\.composer-attachment__fallback/u, "replaced attachment fallback rules are removed");
  assert.match(css, /\.image-preview-stage\s*>\s*img\s*\{[^}]*width:\s*auto;[^}]*height:\s*auto;[^}]*max-width:\s*90%;[^}]*max-height:\s*90%;[^}]*object-fit:\s*contain;/u);
  assert.match(css, /\.file-card--image-preview\s+\.file-card__visual\s*\{[^}]*width:\s*104px;[^}]*height:\s*104px;[^}]*flex-basis:\s*104px;/u);
  assert.match(css, /\.file-card__visual\s+img\s*\{[^}]*object-fit:\s*contain;/u);
});

test("File action failures retain known causes in the local card message", async () => {
  const cases = [
    { ref: "missing", name: "missing.docx", kind: "attachment_not_found", message: resources.en.fileNotFound },
    { ref: "open-failed", name: "broken.pdf", kind: "artifact_open_failed", message: resources.en.fileOpenFailed },
    { ref: "unknown", name: "unknown.bin", kind: "runtime_error", message: resources.en.fileActionFailed },
  ];
  await withRendererDom(async (_dom, container, root) => {
    act(() => { root.render(<LanguageProvider value="en"><div>{cases.map((item) => <FileCard key={item.ref} asset={{ ref: item.ref, name: item.name, mime_type: "application/octet-stream", size_bytes: 1 }} onOpen={async () => { const error = new Error("failed") as Error & { kind?: string }; error.kind = item.kind; throw error; }} />)}</div></LanguageProvider>); });
    const cards = container.querySelectorAll<HTMLElement>(".file-card");
    assert.equal(cards.length, cases.length);
    for (const card of cards) act(() => { card.dispatchEvent(new _dom.window.MouseEvent("dblclick", { bubbles: true })); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    const errors = [...container.querySelectorAll<HTMLElement>(".file-card__error")].map((element) => element.textContent);
    assert.deepEqual(errors, cases.map((item) => item.message));
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
    const imageCard = container.querySelector<HTMLElement>(".composer-attachments .file-card[data-file-kind='image']");
    assert.equal(imageCard?.getAttribute("aria-label"), "diagram.png · image");
    assert.equal(imageCard?.querySelector("img")?.getAttribute("alt"), "diagram.png");
    assert.equal(imageCard?.querySelector(".file-card__meta"), null);
    act(() => { send!.click(); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    assert.equal(turnStarts, 2);
    assert.equal(container.querySelector('[aria-label="Attachments"]'), null);
  });
});

test("App localizes the image capability refusal and keeps the attachment for retry", async () => {
  assert.match(resources.en.turnImageInputUnsupported, /image input/u);
  assert.match(resources["zh-CN"].turnImageInputUnsupported, /图片输入/u);

  const runCase = async (language: "en" | "zh-CN", expectedNotice: string) => {
    let turnStarts = 0;
    const api: DesktopApi = {
      openProject: async () => null,
      openProjectInExplorer: async () => undefined,
      copyText: async () => undefined,
      closeShell: async () => undefined,
      requestRuntime: async (method) => {
        if (method === "turn.start") {
          turnStarts += 1;
          if (turnStarts === 1) {
            return {
              __uthcode_runtime_error: {
                kind: "image_input_unsupported",
                message: "The selected model does not support image input",
              },
            };
          }
          return { run_id: "run-image-retry", turn_id: "turn-image-retry", status: "running" };
        }
        return method === "status.get" ? { active_turn: false } : {};
      },
      subscribeAgentEvents: () => () => undefined,
      readPreference: async (key) => {
        const values: Record<string, unknown> = {
          theme: "light",
          language,
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
          language,
          runtimeState: "ready",
          composerAttachments: [attachment],
        })} api={api} />);
      });
      await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
      const send = container.querySelector<HTMLButtonElement>(".composer-send");
      assert.ok(send);
      act(() => { send!.click(); });
      await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
      assert.equal(turnStarts, 1);
      const attachmentsLabel = resources[language].attachments;
      assert.ok(container.querySelector(`[aria-label="${attachmentsLabel}"]`), container.textContent ?? "");
      assert.match(container.textContent ?? "", new RegExp(expectedNotice.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "u"));

      act(() => { send!.click(); });
      await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
      assert.equal(turnStarts, 2);
      assert.equal(container.querySelector(`[aria-label="${attachmentsLabel}"]`), null);
    });
  };

  await runCase("en", resources.en.turnImageInputUnsupported);
  await runCase("zh-CN", resources["zh-CN"].turnImageInputUnsupported);
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
