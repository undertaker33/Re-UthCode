import { test } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { JSDOM } from "jsdom";
import { ChatTimeline } from "../src/renderer/ChatTimeline";
import { renderMarkdown } from "../src/renderer/safe-markdown";
import { LanguageProvider } from "../src/renderer/i18n";
import type { TimelineEntry } from "../src/renderer/state";

async function withRendererDom<T>(callback: (dom: JSDOM, container: HTMLElement, root: Root) => Promise<T>): Promise<T> {
  const dom = new JSDOM("<!doctype html><html><body><div id=root></div></body></html>", { url: "http://localhost/" });
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

function renderEnglish(node: React.ReactNode): string {
  return renderToStaticMarkup(<LanguageProvider value="en">{node}</LanguageProvider>);
}

const codeEntry = (text: string): TimelineEntry => ({ id: "assistant-1", kind: "assistant", text });

test("safe Markdown keeps raw HTML inert and code fences expose language plus raw copy", async () => {
  const markup = renderEnglish(<div>{renderMarkdown("<script>alert(1)</script>\n\n```python\nprint('<script>')\n```")}</div>);
  assert.match(markup, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/u);
  assert.match(markup, /class="markdown-code-fence" data-language="python"/u);
  assert.match(markup, /Copy code/u);
  assert.doesNotMatch(markup, /<script>alert/u);

  await withRendererDom(async (dom, container, root) => {
    const copied: string[] = [];
    act(() => { root.render(<LanguageProvider value="en"><ChatTimeline entries={[codeEntry("```python\nprint('raw')\n```")]} todo={[]} sessionKey="copy" onCopyText={async (text) => { copied.push(text); }} /></LanguageProvider>); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    const copy = container.querySelector<HTMLButtonElement>(".markdown-code-fence__copy");
    assert.ok(copy);
    act(() => { copy!.click(); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    assert.deepEqual(copied, ["print('raw')\n"]);
    assert.match(copy!.textContent ?? "", /Code copied/u);
  });
});

test("code fence copy preserves exact raw body for empty, CRLF, blank, whitespace, and unclosed fences", async () => {
  const cases: Array<[string, string]> = [
    ["```text\n```", ""],
    ["```text\r\nline 1\r\nline 2  \r\n```", "line 1\r\nline 2  \r\n"],
    ["```text\n\n```", "\n"],
    ["```text\nline\t \n```", "line\t \n"],
    ["```text\r\nline\r\n", "line\r\n"],
  ];
  await withRendererDom(async (_dom, container, root) => {
    for (const [source, expected] of cases) {
      const copied: string[] = [];
      act(() => { root.render(<LanguageProvider value="en"><ChatTimeline entries={[codeEntry(source)]} todo={[]} sessionKey={source} onCopyText={async (text) => { copied.push(text); }} /></LanguageProvider>); });
      await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
      const copy = container.querySelector<HTMLButtonElement>(".markdown-code-fence__copy");
      assert.ok(copy, `missing copy button for ${JSON.stringify(source)}`);
      act(() => { copy!.click(); });
      await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
      assert.deepEqual(copied, [expected], `raw body mismatch for ${JSON.stringify(source)}`);
    }
  });
});

test("ChatTimeline preserves a reader's position and offers an explicit new-message jump", async () => {
  await withRendererDom(async (dom, container, root) => {
    let scrollTop = 0;
    act(() => { root.render(<LanguageProvider value="en"><ChatTimeline entries={[codeEntry("first")]} todo={[]} sessionKey="session-a" /></LanguageProvider>); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    const timeline = container.querySelector<HTMLElement>(".timeline");
    assert.ok(timeline);
    Object.defineProperty(timeline, "scrollHeight", { configurable: true, get: () => 500 });
    Object.defineProperty(timeline, "clientHeight", { configurable: true, get: () => 100 });
    Object.defineProperty(timeline, "scrollTop", { configurable: true, get: () => scrollTop, set: (value: number) => { scrollTop = value; } });
    act(() => { dom.window.dispatchEvent(new dom.window.Event("resize")); });
    act(() => { timeline!.dispatchEvent(new dom.window.Event("scroll", { bubbles: true })); });
    assert.equal(scrollTop, 400, "the initial session is positioned at the tail");
    scrollTop = 40;
    act(() => { timeline!.dispatchEvent(new dom.window.Event("scroll", { bubbles: true })); });
    act(() => { root.render(<LanguageProvider value="en"><ChatTimeline entries={[codeEntry("first"), { id: "assistant-2", kind: "assistant", text: "second", streaming: true }]} todo={[]} sessionKey="session-a" /></LanguageProvider>); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    assert.equal(scrollTop, 40, "streaming does not pull a reader back to the tail");
    const newMessages = container.querySelector<HTMLButtonElement>("[data-new-messages]");
    assert.ok(newMessages);
    act(() => { newMessages!.click(); });
    assert.equal(scrollTop, 400);
    assert.equal(container.querySelector("[data-new-messages]"), null);
    act(() => { root.render(<LanguageProvider value="en"><ChatTimeline entries={[codeEntry("first"), { id: "assistant-2", kind: "assistant", text: "second update", streaming: true }]} todo={[]} sessionKey="session-a" /></LanguageProvider>); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    assert.equal(scrollTop, 400, "the explicit jump re-arms follow-tail");
  });
});

test("ChatTimeline requests one older page, preserves its anchor, and offers a local retry", async () => {
  await withRendererDom(async (dom, container, root) => {
    let scrollTop = 0;
    let scrollHeight = 500;
    let loadCalls = 0;
    let retryCalls = 0;
    const entries = (prefix: string): TimelineEntry[] => [
      { id: `${prefix}-user`, kind: "user", text: `${prefix} prompt`, sequence: prefix === "old" ? 1 : 2, turnId: prefix },
      { id: `${prefix}-assistant`, kind: "assistant", text: `${prefix} answer`, sequence: prefix === "old" ? 2 : 3, turnId: prefix },
    ];
    act(() => {
      root.render(<LanguageProvider value="en"><ChatTimeline
        entries={entries("recent")}
        todo={[]}
        sessionKey="history"
        historyHasMore
        onLoadOlder={() => { loadCalls += 1; }}
        onRetryOlder={() => { retryCalls += 1; }}
      /></LanguageProvider>);
    });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    const timeline = container.querySelector<HTMLElement>(".timeline");
    assert.ok(timeline);
    Object.defineProperty(timeline, "scrollHeight", { configurable: true, get: () => scrollHeight });
    Object.defineProperty(timeline, "clientHeight", { configurable: true, get: () => 100 });
    Object.defineProperty(timeline, "scrollTop", { configurable: true, get: () => scrollTop, set: (value: number) => { scrollTop = value; } });
    act(() => { dom.window.dispatchEvent(new dom.window.Event("resize")); });
    assert.equal(scrollTop, 400);
    scrollTop = 32;
    act(() => { timeline!.dispatchEvent(new dom.window.Event("scroll", { bubbles: true })); });
    assert.equal(loadCalls, 1);

    scrollHeight = 800;
    act(() => {
      root.render(<LanguageProvider value="en"><ChatTimeline
        entries={[...entries("old"), ...entries("recent")]}
        todo={[]}
        sessionKey="history"
        historyHasMore
        historyLoading
        historyRevision={1}
        onLoadOlder={() => { loadCalls += 1; }}
        onRetryOlder={() => { retryCalls += 1; }}
      /></LanguageProvider>);
    });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    assert.equal(scrollTop, 332, "older rows are inserted above the same visible pixel");
    act(() => { timeline!.dispatchEvent(new dom.window.Event("scroll", { bubbles: true })); });
    assert.equal(loadCalls, 1, "loading suppresses a duplicate top request");

    act(() => {
      root.render(<LanguageProvider value="en"><ChatTimeline
        entries={[...entries("old"), ...entries("recent")]}
        todo={[]}
        sessionKey="history"
        historyHasMore
        historyError="history unavailable"
        onLoadOlder={() => { loadCalls += 1; }}
        onRetryOlder={() => { retryCalls += 1; }}
      /></LanguageProvider>);
    });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    const retry = container.querySelector<HTMLButtonElement>(".timeline-history-error button");
    assert.ok(retry);
    act(() => { retry!.click(); });
    assert.equal(retryCalls, 1);
  });
});
