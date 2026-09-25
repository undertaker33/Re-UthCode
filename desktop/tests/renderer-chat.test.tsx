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
import type { ArtifactDescriptor, DesktopAttachmentDraft } from "../src/desktop-api";

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

test("ChatTimeline replays durable attachment metadata with an image preview and file fallback", () => {
  const markup = renderEnglish(<ChatTimeline
    entries={[{
      id: "user-attachment",
      kind: "user",
      text: "",
      attachments: [
        { ref: "image-ref", display_name: "diagram.png", mime_type: "image/png", size_bytes: 4, data_url: "data:image/png;base64,AAAA" },
        { ref: "file-ref", display_name: "notes.txt", mime_type: "text/plain", size_bytes: 12 },
      ],
    }]}
    todo={[]}
    sessionKey="attachment-history"
  />);
  assert.match(markup, /timeline-attachments/u);
  assert.match(markup, /alt="diagram\.png"/u);
  assert.match(markup, /data:image\/png;base64,AAAA/u);
  assert.match(markup, /notes\.txt/u);
  assert.match(markup, />TXT</u);
  assert.match(markup, /12 B/u);
});

test("ChatTimeline hydrates only visible image cards, reaches later history, and rejects late Session previews", async () => {
  let activeObserver: { reveal: (ref: string) => void } | null = null;
  class FakeIntersectionObserver {
    private readonly callback: IntersectionObserverCallback;
    private readonly targets = new Map<string, Element>();
    constructor(callback: IntersectionObserverCallback) {
      this.callback = callback;
      activeObserver = this;
    }
    observe(target: Element): void {
      const ref = (target as HTMLElement).dataset.fileRef;
      if (ref) this.targets.set(ref, target);
    }
    disconnect(): void { this.targets.clear(); }
    reveal(ref: string): void {
      const target = this.targets.get(ref);
      if (!target) return;
      this.callback([{ target, isIntersecting: true } as IntersectionObserverEntry], this as unknown as IntersectionObserver);
    }
  }
  const globalObject = globalThis as unknown as Record<string, unknown>;
  const previousObserver = globalObject.IntersectionObserver;
  Object.defineProperty(globalObject, "IntersectionObserver", { configurable: true, writable: true, value: FakeIntersectionObserver });
  try {
    const oldImages = Array.from({ length: 33 }, (_, index): TimelineEntry => ({
      id: `old-${index + 1}`,
      kind: "user",
      text: "",
      attachments: [{ ref: `old-image-${index + 1}`, display_name: `old-${index + 1}.png`, mime_type: "image/png", size_bytes: 4 }],
    }));
    const pending = new Map<string, (value: DesktopAttachmentDraft | null) => void>();
    const calls: string[] = [];
    const preview = (ref: string): Promise<DesktopAttachmentDraft | null> => {
      calls.push(ref);
      return new Promise((resolve) => pending.set(ref, resolve));
    };
    await withRendererDom(async (_dom, container, root) => {
      const render = (entries: TimelineEntry[], sessionKey: string) => <LanguageProvider value="en"><ChatTimeline entries={entries} todo={[]} sessionKey={sessionKey} onPreviewAttachment={preview} /></LanguageProvider>;
      act(() => { root.render(render(oldImages, "old-session")); });
      await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
      assert.equal(calls.length, 0, "cards outside the viewport stay metadata-only");
      assert.ok(activeObserver);
      activeObserver!.reveal("old-image-1");
      activeObserver!.reveal("old-image-33");
      assert.deepEqual(calls, ["old-image-1", "old-image-33"]);

      act(() => { root.render(render([{ id: "new", kind: "user", text: "", attachments: [{ ref: "new-image", display_name: "new.png", mime_type: "image/png", size_bytes: 4 }] }], "new-session")); });
      await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
      pending.get("old-image-33")?.({ ref: "old-image-33", display_name: "old-33.png", mime_type: "image/png", size_bytes: 4, data_url: "data:image/png;base64,OLD" });
      activeObserver!.reveal("new-image");
      pending.get("new-image")?.({ ref: "new-image", display_name: "new.png", mime_type: "image/png", size_bytes: 4, data_url: "data:image/png;base64,NEW" });
      await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
      assert.equal(container.querySelector('img[src="data:image/png;base64,OLD"]'), null);
      assert.ok(container.querySelector('img[src="data:image/png;base64,NEW"]'));
    });
  } finally {
    if (previousObserver === undefined) delete globalObject.IntersectionObserver;
    else Object.defineProperty(globalObject, "IntersectionObserver", { configurable: true, writable: true, value: previousObserver });
  }
});

test("ChatTimeline retries an in-flight image preview when history updates replace its observer", async () => {
  let activeObserver: { reveal: (ref: string) => void } | null = null;
  class FakeIntersectionObserver {
    private readonly callback: IntersectionObserverCallback;
    private readonly targets = new Map<string, Element>();
    constructor(callback: IntersectionObserverCallback) {
      this.callback = callback;
      activeObserver = this;
    }
    observe(target: Element): void {
      const ref = (target as HTMLElement).dataset.fileRef;
      if (ref) this.targets.set(ref, target);
    }
    disconnect(): void { this.targets.clear(); }
    reveal(ref: string): void {
      const target = this.targets.get(ref);
      if (target) this.callback([{ target, isIntersecting: true } as IntersectionObserverEntry], this as unknown as IntersectionObserver);
    }
  }
  const globalObject = globalThis as unknown as Record<string, unknown>;
  const previousObserver = globalObject.IntersectionObserver;
  Object.defineProperty(globalObject, "IntersectionObserver", { configurable: true, writable: true, value: FakeIntersectionObserver });
  try {
    const image: TimelineEntry = {
      id: "history-image",
      kind: "user",
      text: "",
      attachments: [{ ref: "history-image-ref", display_name: "history.png", mime_type: "image/png", size_bytes: 4 }],
    };
    const resolvers: Array<(value: DesktopAttachmentDraft | null) => void> = [];
    const calls: string[] = [];
    const preview = (ref: string): Promise<DesktopAttachmentDraft | null> => {
      calls.push(ref);
      return new Promise((resolve) => resolvers.push(resolve));
    };
    await withRendererDom(async (_dom, container, root) => {
      const render = (entries: TimelineEntry[]) => <LanguageProvider value="en"><ChatTimeline entries={entries} todo={[]} sessionKey="history-pages" onPreviewAttachment={preview} /></LanguageProvider>;
      act(() => { root.render(render([image])); });
      await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
      activeObserver?.reveal("history-image-ref");
      assert.deepEqual(calls, ["history-image-ref"]);

      const olderImage: TimelineEntry = {
        id: "older-page-image",
        kind: "user",
        text: "",
        attachments: [{ ref: "older-page-image-ref", display_name: "older.png", mime_type: "image/png", size_bytes: 4 }],
      };
      act(() => { root.render(render([image, olderImage])); });
      await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
      activeObserver?.reveal("history-image-ref");
      assert.deepEqual(calls, ["history-image-ref", "history-image-ref"], "a canceled request must not leave its ref marked requested");

      await act(async () => {
        resolvers[0]?.({ ref: "history-image-ref", display_name: "history.png", mime_type: "image/png", size_bytes: 4, data_url: "data:image/png;base64,STALE" });
        resolvers[1]?.({ ref: "history-image-ref", display_name: "history.png", mime_type: "image/png", size_bytes: 4, data_url: "data:image/png;base64,CURRENT" });
        await new Promise<void>((resolve) => setTimeout(resolve, 0));
      });
      assert.equal(container.querySelector('img[src="data:image/png;base64,STALE"]'), null);
      assert.ok(container.querySelector('img[src="data:image/png;base64,CURRENT"]'));
    });
  } finally {
    if (previousObserver === undefined) delete globalObject.IntersectionObserver;
    else Object.defineProperty(globalObject, "IntersectionObserver", { configurable: true, writable: true, value: previousObserver });
  }
});

test("ChatTimeline resolves artifact links into the formal card and controlled preview", async () => {
  await withRendererDom(async (_dom, container, root) => {
    const artifact: ArtifactDescriptor = {
      path: "C:\\Projects\\UthCode\\preview.png",
      name: "preview.png",
      kind: "image",
      mime_type: "image/png",
      size_bytes: 4,
      default_action: "open",
      preview_supported: true,
    };
    let describeCalls = 0;
    let openCalls = 0;
    let previewCalls = 0;
    const render = () => root.render(<LanguageProvider value="en"><ChatTimeline
      entries={[codeEntry("[preview](artifact:C:\\Projects\\UthCode\\preview.png)")]}
      todo={[]}
      sessionKey="artifact-session"
      onDescribeArtifact={async () => { describeCalls += 1; return artifact; }}
      onOpenArtifact={async () => { openCalls += 1; }}
      onPreviewArtifact={async () => { previewCalls += 1; return { ...artifact, data_url: "data:image/png;base64,AAAA" }; }}
    /></LanguageProvider>);
    act(render);
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    assert.ok(container.querySelector(".artifact-card"));
    const preview = container.querySelector<HTMLButtonElement>(".artifact-card__actions button");
    assert.ok(preview);
    act(() => { preview!.click(); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    assert.equal(describeCalls, 1);
    assert.equal(previewCalls, 1);
    assert.ok(container.querySelector('img[src="data:image/png;base64,AAAA"]'));
    const open = Array.from(container.querySelectorAll<HTMLButtonElement>(".artifact-card__actions button")).find((button) => button.textContent === "Open");
    assert.ok(open);
    act(() => { open!.click(); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    assert.equal(openCalls, 1);
  });
});

test("safe Markdown decodes artifact targets with spaces and balanced parentheses", () => {
  const markup = renderToStaticMarkup(<LanguageProvider value="en">{renderMarkdown(
    "[report](artifact:C:/folder%20with%20(draft).txt)",
    {
      onDescribeArtifact: async () => null,
      onOpenArtifact: async () => undefined,
    },
  )}</LanguageProvider>);
  assert.match(markup, /class="file-card artifact-card"/u);
  assert.match(markup, /data-artifact-path="C:\/folder with \(draft\)\.txt"/u);
});

test("ChatTimeline renders bounded Session process observations separately from the Turn timeline", () => {
  const markup = renderEnglish(<ChatTimeline
    entries={[]}
    todo={[]}
    processLogs={[
      { processId: "process-1", sequence: 1, stream: "stdout", text: "live output" },
      { processId: "process-1", sequence: 2, stream: "status", text: "", state: "exited", exitCode: 0 },
    ]}
    sessionKey="process-session"
  />);
  assert.match(markup, /data-process-log="true"/u);
  assert.match(markup, /Process logs \(2\)/u);
  assert.match(markup, /live output/u);
  assert.match(markup, /\[status\] exited/u);
});

test("ChatTimeline exposes process.read continuation and terminal facts", () => {
  const reads: Array<[string, number]> = [];
  const stopped: string[] = [];
  const markup = renderEnglish(<ChatTimeline
    entries={[]}
    todo={[]}
    processLogs={[
      { processId: "process-1", sequence: 4, stream: "stdout", text: "available" },
    ]}
    processReaders={{
      "process-1": {
        nextCursor: 9,
        earliestCursor: 4,
        cursorExpired: true,
        state: "running",
        expired: false,
        loading: false,
        error: null,
      },
    }}
    onReadProcess={(processId, cursor) => reads.push([processId, cursor])}
    onStopProcess={(processId) => stopped.push(processId)}
    sessionKey="process-session"
  />);
  assert.match(markup, /Read newer/u);
  assert.match(markup, /Load earliest/u);
  assert.match(markup, />Stop</u);
  assert.match(markup, /Cursor expired; earliest cursor: 4/u);
  assert.match(markup, /data-process-session="process-session"/u);
  assert.match(markup, /data-process-owner="process-1"/u);
  assert.deepEqual(reads, []);
  assert.deepEqual(stopped, []);
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
