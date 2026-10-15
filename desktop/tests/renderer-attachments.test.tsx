import { test } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { JSDOM } from "jsdom";
import type { AgentEvent, DesktopApi, DesktopAttachmentDraft, DesktopAttachmentInput, JsonValue } from "../src/desktop-api";
import { App } from "../src/renderer/App";
import { Composer } from "../src/renderer/Composer";
import { DocumentPreviewPanel, ReviewPanel, parseUnifiedDiffLines } from "../src/renderer/DocumentPreviewPanel";
import { FileCard } from "../src/renderer/FileCard";
import { RendererErrorBoundary } from "../src/renderer/RendererErrorBoundary";
import { createInitialState, type ProcessLogEntry, type ProjectState } from "../src/renderer/state";
import { sessionRuntimeKey } from "../src/renderer/state-session";
import { LanguageProvider, resources } from "../src/renderer/i18n";

async function withRendererDom<T>(callback: (dom: JSDOM, container: HTMLElement, root: Root) => Promise<T>): Promise<T> {
  const dom = new JSDOM("<!doctype html><html><body><div id=root></div></body></html>", { url: "http://localhost/" });
  if (!("attachEvent" in dom.window.HTMLElement.prototype)) {
    Object.defineProperty(dom.window.HTMLElement.prototype, "attachEvent", { configurable: true, value: () => undefined });
    Object.defineProperty(dom.window.HTMLElement.prototype, "detachEvent", { configurable: true, value: () => undefined });
  }
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

test("Review Diff scopes preserve Git status and render actual unified hunk line numbers", async () => {
  await withRendererDom(async (dom, container, root) => {
    const diff = {
      source: "current_working_tree" as const,
      project_key: "C:/workspace",
      viewed_at: "2026-10-12T00:00:00Z",
      status: {
        branch: "main",
        unborn: false,
        truncated: false,
        entries: [
          { xy: "M ", path: "staged.py" },
          { xy: " M", path: "unstaged.py" },
          { xy: "??", path: "untracked.txt" },
        ],
      },
      staged_diff: {
        text: "diff --git a/staged.py b/staged.py\n--- a/staged.py\n+++ b/staged.py\n@@ -8,2 +8,2 @@\n context\n-old value\n+new value\n",
        truncated: false,
        size_bytes: 100,
      },
      unstaged_diff: {
        text: "diff --git a/unstaged.py b/unstaged.py\n--- a/unstaged.py\n+++ b/unstaged.py\n@@ -3 +3 @@\n-before\n+after\n",
        truncated: false,
        size_bytes: 100,
      },
      truncated: false,
    };
    const owner = { generation: 1, mode: "coding" as const, projectKey: "C:/workspace", sessionId: "session", viewRevision: 1, ownerKey: "C:/workspace" };
    const tab = { kind: "workspace-diff" as const, id: "diff-tab", title: "Working tree", owner, state: "completed" as const, diff };
    await act(async () => { root.render(<LanguageProvider value="en"><ReviewPanel tabs={[tab]} activeTabId="diff-tab" width={360} minWidth={220} maxWidth={700} onWidthChange={() => undefined} onSelectTab={() => undefined} onCloseTab={() => undefined} onClose={() => undefined} onReadToolOutput={() => undefined} onReadProcess={() => undefined} /></LanguageProvider>); });
    assert.equal(container.querySelectorAll(".review-panel__diff-section").length, 2);
    assert.deepEqual([...container.querySelectorAll(".review-panel__diff-file > summary span")].map((path) => path.textContent), ["staged.py", "unstaged.py", "untracked.txt"]);
    assert.deepEqual([...container.querySelectorAll<HTMLDetailsElement>(".review-panel__diff-file")].map((file) => file.open), [true, false, false], "only the first file starts expanded");
    const diffHeader = container.querySelector(".review-panel__content-header--diff");
    assert.ok(diffHeader);
    assert.match(diffHeader.textContent ?? "", /Current working tree/u);
    assert.equal(diffHeader.querySelector("time"), null, "the current workspace heading does not display a snapshot timestamp");
    assert.ok(diffHeader.querySelector('[aria-label="Diff scope"]'), "scope is beside the workspace title");
    assert.equal(container.querySelector(".review-panel__diff-toolbar [aria-label='Diff scope']"), null);
    const removed = container.querySelector<HTMLElement>('[data-diff-kind="removed"]');
    const added = container.querySelector<HTMLElement>('[data-diff-kind="added"]');
    assert.equal(removed?.querySelectorAll(".review-panel__diff-line-number")[0]?.textContent, "9");
    assert.equal(removed?.querySelectorAll(".review-panel__diff-line-number")[1]?.textContent, "");
    assert.equal(added?.querySelectorAll(".review-panel__diff-line-number")[0]?.textContent, "");
    assert.equal(added?.querySelectorAll(".review-panel__diff-line-number")[1]?.textContent, "9");
    const scope = container.querySelector<HTMLButtonElement>('[aria-label="Diff scope"]');
    assert.ok(scope);
    act(() => { scope!.click(); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    const stagedOption = [...dom.window.document.querySelectorAll<HTMLButtonElement>('[role="option"]')].find((option) => option.textContent === "Staged");
    assert.ok(stagedOption);
    act(() => { stagedOption!.click(); });
    assert.deepEqual([...container.querySelectorAll(".review-panel__diff-section")].map((section) => section.getAttribute("data-diff-scope")), ["staged"]);
    assert.deepEqual([...container.querySelectorAll(".review-panel__diff-file > summary span")].map((path) => path.textContent), ["staged.py"]);
    assert.equal(container.querySelector(".review-panel__diff-file")?.textContent?.includes("untracked.txt"), false, "untracked status is not converted to synthetic patch content in a staged view");
    assert.deepEqual(parseUnifiedDiffLines("@@ -2,2 +4,2 @@ context\n same\n-old\n+new").map((line) => [line.kind, line.oldLine, line.newLine]), [
      ["hunk", null, null],
      ["context", 2, 4],
      ["removed", 3, null],
      ["added", null, 5],
    ]);
    assert.deepEqual(parseUnifiedDiffLines("@@ -1,<redacted> +1,<redacted> @@\n-old tracked line\n+new tracked line\n unchanged context").map((line) => [line.kind, line.text, line.oldLine, line.newLine]), [
      ["hunk", "@@ -1,<redacted> +1,<redacted> @@", null, null],
      ["removed", "old tracked line", 1, null],
      ["added", "new tracked line", null, 1],
      ["context", "unchanged context", 2, 2],
    ]);
  });
});

test("Review keeps the selected tab visible by scrolling only the tab strip and avoids duplicate embedded close controls", async () => {
  await withRendererDom(async (dom, container, root) => {
    const owner = { generation: 1, mode: "coding" as const, projectKey: "C:/review-tabs", sessionId: "session", viewRevision: 1, ownerKey: "C:/review-tabs" };
    const tabs = Array.from({ length: 4 }, (_, index) => {
      const name = `review-${index + 1}.txt`;
      return { kind: "document" as const, id: `document-${index + 1}`, title: name, owner, preview: { asset: { display_name: name, mime_type: "text/plain" }, text: `body ${index + 1}` } };
    });
    const render = (activeTabId: string) => <LanguageProvider value="en"><ReviewPanel tabs={tabs} activeTabId={activeTabId} width={360} minWidth={220} maxWidth={700} onWidthChange={() => undefined} onSelectTab={() => undefined} onCloseTab={() => undefined} onClose={() => undefined} onReadToolOutput={() => undefined} onReadProcess={() => undefined} /></LanguageProvider>;
    await act(async () => { root.render(render(tabs[0]!.id)); });
    const nav = container.querySelector<HTMLElement>(".review-panel__tabs");
    const reviewPanel = container.querySelector<HTMLElement>(".review-panel");
    assert.ok(nav);
    assert.ok(reviewPanel);
    Object.defineProperty(nav, "clientWidth", { configurable: true, value: 200 });
    Object.defineProperty(nav, "clientLeft", { configurable: true, value: 0 });
    Object.defineProperty(nav, "scrollLeft", { configurable: true, writable: true, value: 0 });
    Object.defineProperty(nav, "getBoundingClientRect", { configurable: true, value: () => ({ left: 100, right: 300, width: 200, top: 20, bottom: 58, height: 38 }) });
    const selected = container.querySelector<HTMLElement>(`.review-panel__tab:nth-child(4)`);
    assert.ok(selected);
    Object.defineProperty(selected, "getBoundingClientRect", { configurable: true, value: () => {
      const left = 270 - nav.scrollLeft;
      return { left, right: left + 80, width: 80, top: 20, bottom: 47, height: 27 };
    } });
    await act(async () => { root.render(render(tabs[3]!.id)); });
    assert.equal(nav.scrollLeft, 50, "the selected tab is brought into view with the tab strip's horizontal scroll position");
    const wrapperRect = selected.getBoundingClientRect();
    const navRect = nav.getBoundingClientRect();
    assert.ok(wrapperRect.left >= navRect.left && wrapperRect.right <= navRect.right, "the active tab and its close button are inside the visible tab strip");
    assert.equal(reviewPanel.scrollLeft, 0, "tab selection does not scroll the Review panel or chat ancestors");
    assert.equal(container.querySelector(".document-preview-content .document-preview-panel__close"), null, "the embedded document header has no second close action");
    assert.ok(container.querySelector(".review-panel__tab > button:nth-child(2)"), "the active tab keeps its tab-close action");
    assert.ok(container.querySelector(".review-panel__header > button"), "the Review panel keeps its close-all action");
  });
});

test("Review process output labels streams and omits empty ordinary chunks while retaining status", async () => {
  await withRendererDom(async (_dom, container, root) => {
    const owner = { generation: 1, mode: "coding" as const, projectKey: "C:/process-review", sessionId: "session", viewRevision: 1, ownerKey: "C:/process-review" };
    const processId = "process-streams";
    const entries: ProcessLogEntry[] = [
      { processId, sequence: 1, stream: "stdout", text: "stdout line" },
      { processId, sequence: 2, stream: "stderr", text: "stderr line" },
      { processId, sequence: 3, stream: "stdout", text: "later stdout" },
      { processId, sequence: 4, stream: "stdout", text: "" },
      { processId, sequence: 5, stream: "stdout", text: "final stdout bytes", state: "exited", exitCode: 0 },
      { processId, sequence: 6, stream: "status", text: "", state: "exited", exitCode: 0 },
    ];
    const tab = { kind: "process-log" as const, id: "process-tab", title: `Process log: ${processId}`, owner, processId, entries, reader: { nextCursor: 5, earliestCursor: 1, cursorExpired: false, state: "exited", expired: false, loading: false, error: null } };
    await act(async () => { root.render(<LanguageProvider value="en"><ReviewPanel tabs={[tab]} activeTabId={tab.id} width={360} minWidth={220} maxWidth={700} onWidthChange={() => undefined} onSelectTab={() => undefined} onCloseTab={() => undefined} onClose={() => undefined} onReadToolOutput={() => undefined} onReadProcess={() => undefined} /></LanguageProvider>); });
    const rows = [...container.querySelectorAll<HTMLElement>(".review-panel__process-entry")];
    assert.deepEqual(rows.map((row) => row.getAttribute("data-process-stream")), ["stdout", "stderr", "stdout", "stdout", "status"]);
    assert.deepEqual(rows.map((row) => row.querySelector("small")?.textContent), ["stdout", "stderr", "stdout", "stdout · exited", "status · exited"]);
    assert.deepEqual(rows.map((row) => row.querySelector("pre")?.textContent), ["stdout line", "stderr line", "later stdout", "final stdout bytes", "exited"]);
    assert.equal(container.querySelector('[data-process-sequence="4"]'), null, "an empty ordinary output chunk does not create a blank card");
    assert.equal(container.querySelector('[data-process-sequence="5"][data-process-stream="stdout"] pre')?.textContent, "final stdout bytes", "the state label does not replace non-empty output");
    assert.ok(container.querySelector('[data-process-sequence="6"][data-process-stream="status"]'), "the terminal status entry remains visible");
  });
});

test("image Review header uses its MIME type while standalone previews keep a close action", () => {
  const preview = { asset: { display_name: "review-image.png", mime_type: "image/png" }, text: "", imageSrc: "data:image/png;base64,AAAA" };
  const markup = renderToStaticMarkup(<LanguageProvider value="en"><DocumentPreviewPanel
    preview={preview}
    width={460}
    minWidth={220}
    maxWidth={700}
    onWidthChange={() => undefined}
    onClose={() => undefined}
  /></LanguageProvider>);
  assert.match(markup, /<small>image\/png<\/small>/u);
  assert.match(markup, /class="document-preview-panel__close"/u);
  assert.doesNotMatch(markup, /<small>plain<\/small>/u);

  const owner = { generation: 1, mode: "coding" as const, projectKey: "C:/review-image", sessionId: "session", viewRevision: 1, ownerKey: "C:/review-image" };
  const tab = { kind: "document" as const, id: "image-tab", title: "review-image.png", owner, preview };
  const embeddedMarkup = renderToStaticMarkup(<LanguageProvider value="en"><ReviewPanel
    tabs={[tab]}
    activeTabId={tab.id}
    width={460}
    minWidth={220}
    maxWidth={700}
    onWidthChange={() => undefined}
    onSelectTab={() => undefined}
    onCloseTab={() => undefined}
    onClose={() => undefined}
    onReadToolOutput={() => undefined}
    onReadProcess={() => undefined}
  /></LanguageProvider>);
  assert.match(embeddedMarkup, /<small>image\/png<\/small>/u);
  assert.doesNotMatch(embeddedMarkup, /<small>plain<\/small>/u);
});

test("Review Diff renders untracked text patches and leaves empty scopes without a footer", async () => {
  await withRendererDom(async (dom, container, root) => {
    const diff = {
      source: "current_working_tree" as const,
      project_key: "C:/workspace-empty",
      viewed_at: "2026-10-12T01:00:00Z",
      status: { branch: "main", unborn: false, truncated: false, entries: [{ xy: "??", path: "new.txt" }, { xy: "??", path: "unavailable.bin", review_error: "unavailable" as const }] },
      staged_diff: { text: "", truncated: false, size_bytes: 0 },
      unstaged_diff: {
        text: "diff --git a/new.txt b/new.txt\nnew file mode 100644\n--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1 @@\n+new file body\n",
        truncated: false,
        size_bytes: 112,
      },
      truncated: false,
    };
    const owner = { generation: 1, mode: "coding" as const, projectKey: "C:/workspace-empty", sessionId: "session", viewRevision: 1, ownerKey: "C:/workspace-empty" };
    const tab = { kind: "workspace-diff" as const, id: "empty-diff-tab", title: "Working tree", owner, state: "completed" as const, diff };
    await act(async () => { root.render(<LanguageProvider value="en"><ReviewPanel tabs={[tab]} activeTabId="empty-diff-tab" width={360} minWidth={220} maxWidth={700} onWidthChange={() => undefined} onSelectTab={() => undefined} onCloseTab={() => undefined} onClose={() => undefined} onReadToolOutput={() => undefined} onReadProcess={() => undefined} /></LanguageProvider>); });
    assert.equal(container.querySelectorAll(".review-panel__diff-empty").length, 0);
    const fileRows = [...container.querySelectorAll<HTMLDetailsElement>(".review-panel__diff-file")];
    assert.deepEqual(fileRows.map((file) => file.querySelector("summary span")?.textContent), ["new.txt", "unavailable.bin"]);
    assert.deepEqual(fileRows.map((file) => file.open), [true, false]);
    assert.equal(container.querySelector('[data-diff-kind="added"] code')?.textContent, "new file body");
    assert.match(fileRows[1]?.querySelector('[role="status"]')?.textContent ?? "", /content is unavailable/u);
    assert.equal(fileRows[1]?.querySelector(".review-panel__diff-section"), null, "unavailable content keeps its path/status explanation without fabricating a patch");
    const scope = container.querySelector<HTMLButtonElement>('.review-panel__content-header--diff [aria-label="Diff scope"]');
    assert.ok(scope);
    act(() => { scope!.click(); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    const stagedOption = [...dom.window.document.querySelectorAll<HTMLButtonElement>('[role="option"]')].find((option) => option.textContent === "Staged");
    assert.ok(stagedOption);
    act(() => { stagedOption!.click(); });
    assert.equal(container.querySelectorAll(".review-panel__diff-empty").length, 0, "an empty scope does not add a redundant empty-state footer");
    assert.equal(container.querySelectorAll(".review-panel__diff-section").length, 0);
    assert.equal(container.querySelector('[data-diff-kind="added"] code'), null, "the untracked patch appears only in the unstaged scope");
  });
});

test("Review Diff keeps one independently collapsible file header across staged and unstaged patches", async () => {
  await withRendererDom(async (_dom, container, root) => {
    const path = "src/file with spaces.ts";
    const diff = {
      source: "current_working_tree" as const,
      project_key: "C:/workspace-files",
      viewed_at: "2026-10-13T00:00:00Z",
      status: { branch: "main", unborn: false, truncated: false, entries: [{ xy: "MM", path }, { xy: " M", path: "src/second.ts" }] },
      staged_diff: {
        text: 'diff --git "a/src/file with spaces.ts" "b/src/file with spaces.ts"\n--- "a/src/file with spaces.ts"\n+++ "b/src/file with spaces.ts"\n@@ -1 +1 @@\n-old staged\n+new staged\n',
        truncated: false,
        size_bytes: 140,
      },
      unstaged_diff: {
        text: 'diff --git "a/src/file with spaces.ts" "b/src/file with spaces.ts"\n@@ -1 +1 @@\n-old unstaged\n+new unstaged\ndiff --git a/src/second.ts b/src/second.ts\n@@ -2 +2 @@\n-old second\n+new second\n',
        truncated: false,
        size_bytes: 170,
      },
      truncated: false,
    };
    const owner = { generation: 1, mode: "coding" as const, projectKey: "C:/workspace-files", sessionId: "session", viewRevision: 1, ownerKey: "C:/workspace-files" };
    const tab = { kind: "workspace-diff" as const, id: "files-tab", title: "Working tree", owner, state: "completed" as const, diff };
    await act(async () => { root.render(<LanguageProvider value="en"><ReviewPanel tabs={[tab]} activeTabId="files-tab" width={360} minWidth={220} maxWidth={700} onWidthChange={() => undefined} onSelectTab={() => undefined} onCloseTab={() => undefined} onClose={() => undefined} onReadToolOutput={() => undefined} onReadProcess={() => undefined} /></LanguageProvider>); });
    const files = [...container.querySelectorAll<HTMLDetailsElement>(".review-panel__diff-file")];
    assert.equal(files.length, 2, "a file modified in both scopes has one summary, not two");
    assert.deepEqual(files.map((file) => file.getAttribute("data-file-path")), [path, "src/second.ts"]);
    assert.deepEqual(files.map((file) => file.querySelector("summary code")?.textContent), ["MM", " M"]);
    assert.deepEqual(files.map((file) => file.open), [true, false]);
    assert.ok(files.every((file) => file.querySelector("summary > .ui-icon--chevron")?.getAttribute("aria-hidden") === "true"), "file headers show a decorative expand/collapse indicator");
    assert.deepEqual([...files[0]!.querySelectorAll(".review-panel__diff-section")].map((section) => section.getAttribute("data-diff-scope")), ["staged", "unstaged"]);
    assert.equal(files[0]!.querySelectorAll('[data-diff-kind="removed"] code').length, 2);
    files[1]!.querySelector<HTMLElement>("summary")?.click();
    assert.equal(files[0]!.open, true, "opening a second file leaves the first file open");
    assert.equal(files[1]!.open, true);
    files[1]!.querySelector<HTMLElement>("summary")?.click();
    assert.equal(files[1]!.open, false, "each file can be closed without changing its neighbors");
  });
});

test("Review Diff groups mixed-quoted rename hunks by the decoded file path", async () => {
  await withRendererDom(async (_dom, container, root) => {
    const renamedPath = "重命名.txt";
    const diff = {
      source: "current_working_tree" as const,
      project_key: "C:/workspace-renames",
      viewed_at: "2026-10-13T00:00:00Z",
      status: { branch: "main", unborn: false, truncated: false, entries: [
        { xy: " R", path: renamedPath, original_path: "old.txt" },
        { xy: " R", path: "new file.txt", original_path: renamedPath },
        { xy: " M", path: "other.txt" },
        { xy: "A ", path: "staged-1" },
      ] },
      staged_diff: {
        text: "diff --git a/staged-1 b/staged-1\n@@ -0,0 +1 @@\n+staged body\n",
        truncated: false,
        size_bytes: 62,
      },
      unstaged_diff: {
        text: 'diff --git a/old.txt "b/\\351\\207\\215\\345\\221\\275\\345\\220\\215.txt"\nrename from old.txt\nrename to ' + renamedPath + '\n@@ -1 +1 @@\n-old body\n+renamed body\ndiff --git "a/\\351\\207\\215\\345\\221\\275\\345\\220\\215.txt" b/new file.txt\nrename from ' + renamedPath + '\nrename to new file.txt\n@@ -1 +1 @@\n-old renamed\n+new file\ndiff --git a/other.txt b/other.txt\n@@ -1 +1 @@\n-old other\n+new other\ndiff --git a/unknown.txt c/unknown.txt\n@@ -0,0 +1 @@\n+unknown payload\n',
        truncated: false,
        size_bytes: 250,
      },
      truncated: false,
    };
    const owner = { generation: 1, mode: "coding" as const, projectKey: "C:/workspace-renames", sessionId: "session", viewRevision: 1, ownerKey: "C:/workspace-renames" };
    const tab = { kind: "workspace-diff" as const, id: "rename-tab", title: "Working tree", owner, state: "completed" as const, diff };
    await act(async () => { root.render(<LanguageProvider value="en"><ReviewPanel tabs={[tab]} activeTabId="rename-tab" width={360} minWidth={220} maxWidth={700} onWidthChange={() => undefined} onSelectTab={() => undefined} onCloseTab={() => undefined} onClose={() => undefined} onReadToolOutput={() => undefined} onReadProcess={() => undefined} /></LanguageProvider>); });
    const files = [...container.querySelectorAll<HTMLDetailsElement>(".review-panel__diff-file")];
    assert.deepEqual(files.map((file) => file.getAttribute("data-file-path")), [renamedPath, "new file.txt", "other.txt", "staged-1", "unstaged-4"]);
    assert.deepEqual(files.map((file) => file.open), [true, false, false, false, false]);
    assert.equal(files[0]?.querySelector("summary small")?.textContent, "← old.txt");
    assert.equal(files[0]?.querySelector('[data-diff-kind="added"] code')?.textContent, "renamed body");
    assert.equal(files[0]?.querySelector('[data-diff-kind="removed"] code')?.textContent, "old body");
    assert.equal(files[1]?.querySelector("summary small")?.textContent, `← ${renamedPath}`);
    assert.equal(files[1]?.querySelector('[data-diff-kind="added"] code')?.textContent, "new file");
    assert.equal(files[1]?.querySelector('[data-diff-kind="removed"] code')?.textContent, "old renamed");
    assert.equal(files[0]?.textContent?.includes("old renamed"), false, "the reverse mixed-quoted rename patch belongs to its decoded destination path");
    assert.equal(files[0]?.textContent?.includes("unknown payload"), false, "an unparseable multi-file chunk is not attached to the first known file");
    assert.ok(files[4]?.textContent?.includes("diff --git a/unknown.txt c/unknown.txt"), "the unknown chunk keeps its original header and body");
  });
});

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

test("empty Composer marks the compact state while keeping its submit label accessible", () => {
  const empty = renderToStaticMarkup(renderComposer(createInitialState({
    language: "en",
    composerText: "",
    composerAttachments: [],
  })));
  assert.match(empty, /class="composer" data-empty="true" data-coding-mode="true"/u);
  assert.match(empty, /<button class="composer-send"[^>]*title="Send" aria-label="Send"[^>]*><svg[\s\S]*?<\/svg><span class="composer-send__label">Send<\/span><\/button>/u);

  const populated = renderToStaticMarkup(renderComposer(createInitialState({
    language: "en",
    composerText: "draft",
    composerAttachments: [],
  })));
  assert.match(populated, /class="composer" data-empty="false" data-coding-mode="true"/u);
  assert.match(populated, /<span class="composer-send__label">Send<\/span>/u);
});

test("active Composer keeps an empty or whitespace draft disabled until Steering has text", () => {
  for (const composerText of ["", " \n\t "]) {
    const markup = renderToStaticMarkup(renderComposer(createInitialState({
      language: "en",
      composerText,
      composerAttachments: [],
      activeTurn: true,
      turnStatus: "running",
    })));
    assert.match(markup, /class="composer-send"[^>]*title="Send" aria-label="Send" disabled=""/u, "empty Steering is not labeled or styled like an enabled blue action");
    assert.match(markup, /class="composer-submit-proxy"[^>]*disabled=""/u, "the hidden submit hook observes the same empty-text rule");
  }

  const activeDraft = renderToStaticMarkup(renderComposer(createInitialState({
    language: "en",
    composerText: "continue the current task",
    composerAttachments: [],
    activeTurn: true,
    turnStatus: "running",
  })));
  assert.match(activeDraft, /class="composer-send"[^>]*title="Steer" aria-label="Steer"/u);
  assert.doesNotMatch(activeDraft, /class="composer-send"[^>]*title="Steer" aria-label="Steer" disabled=""/u);
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
    const remove = container.querySelector<HTMLButtonElement>('button[aria-label^="Remove attachment"]');
    const send = container.querySelector<HTMLButtonElement>('button[aria-label="Send"]');
    const composer = container.querySelector<HTMLElement>(".composer");
    assert.ok(choose && remove && send && composer);
    assert.equal(container.querySelectorAll('button[aria-label="Paste"]').length, 0);

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
      assert.equal(card.querySelectorAll(".file-card__meta").length, 0);
      assert.equal(card.querySelector("img")?.getAttribute("alt"), "private-name.png");
      assert.ok(card.classList.contains("file-card--image-preview"));
    }
    const remove = cards[0].querySelector<HTMLButtonElement>(".file-card__remove-button");
    assert.ok(remove);
    assert.equal(remove.getAttribute("aria-label"), "Remove attachment: private-name.png");
    assert.equal(cards[1].querySelectorAll(".file-card__remove-button").length, 0);
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
    assert.equal(container.querySelectorAll("#runtime-panel").length, 0, "the document canvas takes the Runtime panel's right grid slot while open");
    const source = [...container.querySelectorAll<HTMLButtonElement>(".document-preview-panel__actions button")].find((button) => button.textContent === "View source");
    assert.ok(source);
    act(() => { source!.click(); });
    assert.match(container.textContent ?? "", /# notes/u);
    const close = container.querySelector<HTMLButtonElement>('[aria-label="Close file preview"]');
    assert.ok(close);
    act(() => { close!.click(); });
    assert.equal(container.querySelectorAll(".document-preview-panel").length, 0);
    assert.equal(shell?.classList.contains("document-preview-visible"), false);
    assert.ok(container.querySelector("#runtime-panel"), "closing restores the existing Runtime layout mode");
  });
});

test("T09 chat image attachment opens in the shared review tab and keeps the zoom modal", async () => {
  const api = appTestApi(async (method) => {
    if (method === "attachment.preview") return { attachment: { ...attachment, preview_kind: "image", data_url: attachment.data_url } };
    return method === "status.get" ? { active_turn: false } : {};
  });
  await withRendererDom(async (dom, container, root) => {
    act(() => { root.render(<App api={api} initialState={createInitialState({
      language: "en",
      runtimeState: "ready",
      timeline: [{ id: "image-message", kind: "user", text: "See image", attachments: [{ ref: attachment.ref, display_name: attachment.display_name, mime_type: attachment.mime_type, size_bytes: attachment.size_bytes, data_url: attachment.data_url }] }],
    })} />); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    const card = container.querySelector<HTMLElement>(".timeline-attachments .file-card");
    assert.ok(card);
    act(() => { card.dispatchEvent(new dom.window.MouseEvent("dblclick", { bubbles: true })); });
    await act(async () => { for (let index = 0; index < 3; index += 1) await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    assert.equal(container.querySelectorAll(".review-panel").length, 1);
    assert.equal(container.querySelector(".document-review-image img")?.getAttribute("src"), attachment.data_url);
    const imageButton = container.querySelector<HTMLButtonElement>(".document-review-image button");
    assert.ok(imageButton);
    act(() => { imageButton.click(); });
    assert.ok(container.querySelector(".image-preview-modal[role='dialog']"), "the right-panel preview retains the existing zoom and focus modal");
    assert.ok(container.querySelector(".image-preview-modal footer button"));
    const stage = container.querySelector<HTMLElement>(".image-preview-stage");
    assert.ok(stage);
    const wheel = new dom.window.WheelEvent("wheel", { deltaY: -1, cancelable: true, bubbles: true });
    act(() => { stage.dispatchEvent(wheel); });
    assert.equal(wheel.defaultPrevented, true, "native zoom consumes the wheel event so the underlying chat does not scroll");
    assert.match(container.querySelector(".image-preview-modal footer")?.textContent ?? "", /112%/u);
  });
});

test("T09 App reviews preserve Runtime error ownership and let its toggle restore the panel", async () => {
  const projectPath = "C:/review-runtime-owner";
  const project: ProjectState = {
    path: projectPath,
    projectKey: projectPath,
    alias: "Runtime review",
    pinned: false,
    catalogFresh: true,
    sessions: [],
  };
  const calls: Array<{ method: string; params: Record<string, unknown> }> = [];
  let diffSequence = 0;
  const runtimeError = "Runtime could not start";
  const api = appTestApi(async (method, params = {}) => {
    calls.push({ method, params: { ...params } });
    if (method === "runtime.initialize") throw new Error(runtimeError);
    if (method === "workspace.diff") {
      diffSequence += 1;
      return { operation_id: `runtime-review-${diffSequence}`, owner_key: projectPath, state: "reviewing" };
    }
    if (method === "workspace.diff.cancel") return { operation_id: params.operation_id ?? null, state: "cancelled" };
    if (method === "project.sessions") return { sessions: project.sessions };
    if (method === "history.page") return { session_id: params.session_id ?? null, records: [], next_cursor: null, has_more: false };
    return method === "status.get" ? { active_turn: false } : {};
  });
  const preferenceValues: Record<string, unknown> = {
    theme: "light", language: "en", panelMode: "docked", sidebarWidth: 286, runtimePanelWidth: 318,
    recentProjects: [{ path: projectPath, alias: project.alias, pinned: false }],
    projectAliases: { [projectPath]: project.alias }, pinnedProjectKeys: [], pinnedSessions: [],
    expandedProjects: { [projectPath]: true }, selectedProjectKey: projectPath, selectedSessionId: null,
  };
  api.readPreference = async (key) => preferenceValues[key] as never;
  const state = createInitialState({
    language: "en",
    mode: "coding",
    panelMode: "docked",
    runtimeState: "configuration_required",
    runtimeError,
    projects: [project],
    selectedProjectKey: projectPath,
    selectedSessionId: null,
    expandedProjects: { [projectPath]: true },
  });
  const flush = async () => { await act(async () => { for (let index = 0; index < 8; index += 1) await new Promise<void>((resolve) => setTimeout(resolve, 0)); }); };

  await withRendererDom(async (dom, container, root) => {
    act(() => { root.render(<App api={api} initialState={state} />); });
    await flush();
    const runtimeToggle = container.querySelector<HTMLButtonElement>('.conversation-actions button[aria-controls="runtime-panel"]');
    assert.ok(runtimeToggle);
    assert.equal(runtimeToggle.getAttribute("aria-label"), "Close Runtime panel");
    assert.equal(runtimeToggle.getAttribute("aria-expanded"), "true");
    assert.equal(container.querySelector("[data-runtime-error-owner]")?.getAttribute("data-runtime-error-owner"), "runtime-panel");
    assert.match(container.querySelector(".runtime-panel__error")?.textContent ?? "", new RegExp(runtimeError, "u"));

    const openDiff = () => [...container.querySelectorAll<HTMLButtonElement>(".conversation-actions button")]
      .find((button) => button.getAttribute("aria-label") === "Review current diff");
    act(() => { openDiff()?.click(); });
    await flush();
    assert.ok(container.querySelector(".review-panel"));
    assert.equal(container.querySelectorAll("#runtime-panel").length, 0, "Review takes the shared right panel slot");
    assert.equal(container.querySelector("[data-runtime-error-owner]")?.getAttribute("data-runtime-error-owner"), "timeline");
    assert.match(container.querySelector(".timeline-runtime-error")?.textContent ?? "", new RegExp(runtimeError, "u"));
    assert.equal(container.querySelectorAll('[role="alert"]').length, 1, "Review does not hide or duplicate the Runtime error alert");
    assert.equal(runtimeToggle.getAttribute("aria-label"), "Open Runtime panel");
    assert.equal(runtimeToggle.getAttribute("aria-expanded"), "false");

    runtimeToggle.focus();
    act(() => { runtimeToggle.click(); });
    await flush();
    assert.equal(container.querySelector(".review-panel"), null, "the Runtime toggle closes the existing owner-bound ReviewPanel");
    assert.ok(container.querySelector("#runtime-panel"), "the Runtime toggle restores the preferred docked Runtime panel");
    assert.equal(container.querySelector("[data-runtime-error-owner]")?.getAttribute("data-runtime-error-owner"), "runtime-panel");
    assert.equal(container.querySelector(".timeline-runtime-error"), null);
    assert.equal(runtimeToggle.getAttribute("aria-label"), "Close Runtime panel");
    assert.equal(runtimeToggle.getAttribute("aria-expanded"), "true");
    assert.equal(dom.window.document.activeElement, runtimeToggle, "the stable Runtime control retains focus across the panel handoff");
    assert.deepEqual(calls.filter((call) => call.method === "workspace.diff.cancel").map((call) => call.params.operation_id), ["runtime-review-1"]);

    act(() => { openDiff()?.click(); });
    await flush();
    assert.ok(container.querySelector(".review-panel"), "the user can switch back to Review from the same Runtime layout preference");
    assert.equal(container.querySelector("[data-runtime-error-owner]")?.getAttribute("data-runtime-error-owner"), "timeline");
    assert.equal(runtimeToggle.getAttribute("aria-label"), "Open Runtime panel");
    assert.equal(runtimeToggle.getAttribute("aria-expanded"), "false");

    act(() => { runtimeToggle.click(); });
    await flush();
    assert.ok(container.querySelector("#runtime-panel"));
    assert.equal(container.querySelector(".review-panel"), null);
  });
});

test("T09 App auto-discovers current workspace changes without taking the panel and discards a late owner result", async () => {
  const projectPath = "C:/summary-owner";
  const firstSession = "summary-session-a";
  const secondSession = "summary-session-b";
  const project: ProjectState = {
    path: projectPath,
    projectKey: projectPath,
    alias: "Summary owner",
    pinned: false,
    catalogFresh: true,
    sessions: [
      { session_id: firstSession, project_key: projectPath, title: "Summary session A" },
      { session_id: secondSession, project_key: projectPath, title: "Summary session B" },
    ],
  };
  const calls: Array<{ method: string; params: Record<string, unknown> }> = [];
  let eventListener: ((event: AgentEvent) => void) | null = null;
  let diffSequence = 0;
  let resolveLateKickoff: ((value: JsonValue) => void) | null = null;
  const diffEvent = (operationId: string, path = "src/created.py"): AgentEvent => ({
    type: "workspace_diff_result",
    operation_id: operationId,
    owner_key: projectPath,
    state: "completed",
    source: "current_working_tree",
    project_key: projectPath,
    viewed_at: "2026-10-11T03:00:00.000Z",
    status: { branch: "main", entries: [{ xy: " M", path }], unborn: false, truncated: false },
    staged_diff: { text: `diff --git a/${path} b/${path}\n@@ -0,0 +1 @@\n+written`, truncated: false, size_bytes: 50 },
    unstaged_diff: { text: "", truncated: false, size_bytes: 0 },
    truncated: false,
  } as AgentEvent);
  const api = appTestApi(async (method, params = {}) => {
    calls.push({ method, params: { ...params } });
    if (method === "workspace.diff") {
      diffSequence += 1;
      if (diffSequence === 1) {
        eventListener?.(diffEvent("summary-operation-1"));
        return { operation_id: "summary-operation-1", owner_key: projectPath, state: "reviewing" };
      }
      if (diffSequence === 2) {
        eventListener?.(diffEvent("review-operation-2"));
        return { operation_id: "review-operation-2", owner_key: projectPath, state: "reviewing" };
      }
      if (diffSequence === 3) {
        eventListener?.(diffEvent("late-summary-operation-3", "src/old-owner.py"));
        return await new Promise<JsonValue>((resolve) => { resolveLateKickoff = resolve; });
      }
      return { operation_id: `unused-operation-${diffSequence}`, owner_key: projectPath, state: "reviewing" };
    }
    if (method === "workspace.diff.cancel") return { operation_id: params.operation_id ?? null, state: "cancelled" };
    if (method === "project.sessions") return { sessions: project.sessions };
    if (method === "session.resume") return { session_id: params.session_id ?? null, replay: [], run: null };
    if (method === "history.page") return { session_id: params.session_id ?? null, records: [], next_cursor: null, has_more: false };
    return method === "status.get" ? { active_turn: false } : {};
  });
  api.subscribeAgentEvents = (listener) => { eventListener = listener; return () => { eventListener = null; }; };
  api.readPreference = async (key) => {
    const values: Record<string, unknown> = {
      theme: "light", language: "en", panelMode: "docked", sidebarWidth: 286, runtimePanelWidth: 318,
      recentProjects: [{ path: projectPath, alias: project.alias, pinned: false }],
      projectAliases: { [projectPath]: project.alias }, pinnedProjectKeys: [], pinnedSessions: [],
      expandedProjects: { [projectPath]: true }, selectedProjectKey: projectPath, selectedSessionId: firstSession,
    };
    return values[key] as never;
  };
  const state = createInitialState({
    language: "en", mode: "coding", panelMode: "docked", runtimeState: "ready",
    projects: [project], selectedProjectKey: projectPath, selectedSessionId: firstSession,
    expandedProjects: { [projectPath]: true }, timeline: [],
  });
  const flush = async (delay = 0) => { await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, delay)); for (let index = 0; index < 8; index += 1) await new Promise<void>((resolve) => setTimeout(resolve, 0)); }); };

  await withRendererDom(async (_dom, container, root) => {
    act(() => { root.render(<App api={api} initialState={state} />); });
    await flush(10);
    assert.ok(eventListener);
    act(() => { eventListener!({
      type: "tool_finished", project_key: projectPath, session_id: firstSession,
      run_id: "summary-run", turn_id: "summary-turn", batch_id: "summary-batch",
      tool_call_id: "summary-write-1", tool_name: "WriteFile", status: "succeeded", is_error: false,
    } as AgentEvent); });
    await flush(180);
    assert.equal(calls.filter((call) => call.method === "workspace.diff").length, 1, "a successful live writer takes one real current-diff snapshot");
    const summary = container.querySelector<HTMLElement>("[data-workspace-change-summary]");
    assert.ok(summary);
    assert.match(summary.textContent ?? "", /Files changed: 1/u);
    assert.match(summary.textContent ?? "", /\+1/u);
    assert.match(summary.textContent ?? "", /src\/created\.py/u);
    assert.equal(container.querySelector(".review-panel"), null, "background discovery leaves the user's shared right-panel selection alone");
    assert.ok(container.querySelector("#runtime-panel"), "background discovery does not replace the preferred Runtime panel");

    const viewChanges = [...summary.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent === "View changes");
    assert.ok(viewChanges);
    act(() => { viewChanges.click(); });
    await flush(10);
    assert.ok(container.querySelector(".review-panel"), "the explicit summary action opens the existing ReviewPanel");
    assert.deepEqual(calls.filter((call) => call.method === "workspace.diff")[1]?.params, { project_key: projectPath });

    act(() => { eventListener!({
      type: "tool_finished", project_key: projectPath, session_id: firstSession,
      run_id: "summary-run", turn_id: "summary-turn", batch_id: "summary-batch",
      tool_call_id: "summary-write-2", tool_name: "EditFile", status: "succeeded", is_error: false,
    } as AgentEvent); });
    await flush(180);
    assert.equal(typeof resolveLateKickoff, "function", "the second summary request is pending for the old Session owner");
    const nextSession = [...container.querySelectorAll<HTMLButtonElement>("button.session-line")]
      .find((button) => button.textContent?.includes("Summary session B"));
    assert.ok(nextSession);
    act(() => { nextSession.click(); });
    await flush(10);
    assert.equal(container.querySelector("[data-workspace-change-summary]"), null, "the old Session summary is removed on navigation");
    resolveLateKickoff!({ operation_id: "late-summary-operation-3", owner_key: projectPath, state: "reviewing" });
    await flush(10);
    assert.ok(calls.some((call) => call.method === "workspace.diff.cancel" && call.params.operation_id === "late-summary-operation-3"), "a kickoff returned after navigation is cancelled under its old owner");
    act(() => { eventListener!(diffEvent("late-summary-operation-3", "src/old-owner.py")); });
    await flush(10);
    assert.doesNotMatch(container.textContent ?? "", /old-owner\.py/u, "a late old-owner result cannot populate the new Session");
  });
});

test("T09 App reviews the kickoff event, bounded output pages, process log, and rejects stale owners", async () => {
  const projectPath = "C:/review-owner";
  const firstSession = "review-session-a";
  const secondSession = "review-session-b";
  const project: ProjectState = {
    path: projectPath,
    projectKey: projectPath,
    alias: "Review owner",
    pinned: false,
    catalogFresh: true,
    sessions: [
      { session_id: firstSession, project_key: projectPath, title: "Review session A" },
      { session_id: secondSession, project_key: projectPath, title: "Review session B" },
    ],
  };
  const sessionKey = sessionRuntimeKey(projectPath, firstSession);
  const logs: ProcessLogEntry[] = [{ processId: "process-review", sequence: 1, stream: "stdout", text: "first process line", nextCursor: 1 }];
  const calls: Array<{ method: string; params: Record<string, unknown> }> = [];
  let eventListener: ((event: AgentEvent) => void) | null = null;
  let diffSequence = 0;
  let resolveLateOutput: ((value: JsonValue) => void) | null = null;
  const diffEvent = (operationId: string, content: string, path = "src/current.ts"): AgentEvent => ({
    type: "workspace_diff_result",
    operation_id: operationId,
    owner_key: projectPath,
    state: "completed",
    source: "current_working_tree",
    project_key: projectPath,
    viewed_at: "2026-10-11T02:00:00.000Z",
    status: { branch: "main", entries: [{ xy: " M", path }], unborn: false, truncated: false },
    staged_diff: { text: `+ staged ${content}`, truncated: false, size_bytes: content.length + 9 },
    unstaged_diff: { text: `- unstaged ${content}`, truncated: false, size_bytes: content.length + 11 },
    truncated: false,
  } as AgentEvent);
  const api = appTestApi(async (method, params = {}) => {
    calls.push({ method, params: { ...params } });
    if (method === "workspace.diff") {
      diffSequence += 1;
      const operationId = `review-diff-${diffSequence}`;
      if (diffSequence === 1) eventListener?.(diffEvent(operationId, "first"));
      if (diffSequence === 2) eventListener?.(diffEvent(operationId, "path", String(params.path)));
      if (diffSequence === 4) eventListener?.({
        type: "workspace_diff_result",
        operation_id: operationId,
        owner_key: projectPath,
        state: "failed",
        error_kind: "workspace_unavailable",
      } as AgentEvent);
      return { operation_id: operationId, owner_key: projectPath, state: "reviewing" };
    }
    if (method === "workspace.diff.cancel") return { operation_id: params.operation_id ?? null, state: "cancelled" };
    if (method === "tool_result.read") {
      if (params.ref === "result-late") return await new Promise<JsonValue>((resolve) => { resolveLateOutput = resolve; });
      const offset = Number(params.offset ?? 0);
      return offset === 0
        ? { ref: params.ref, content: "first", offset: 0, next_offset: 5, total_bytes: 11, sha256: "a".repeat(64), eof: false }
        : { ref: params.ref, content: "second", offset: 5, next_offset: 11, total_bytes: 11, sha256: "a".repeat(64), eof: true };
    }
    if (method === "process.read") return { process_id: params.process_id ?? "process-review", entries: [{ sequence: 2, stream: "stdout", text: "continued process output" }, { sequence: 3, stream: "stderr", text: "continued stderr output" }], next_cursor: 3, earliest_cursor: 0, state: "exited", exit_code: 0 };
    if (method === "project.sessions") return { sessions: project.sessions };
    if (method === "session.resume") return { session_id: params.session_id ?? null, replay: [], run: null };
    if (method === "history.page") return { session_id: params.session_id ?? null, records: [], next_cursor: null, has_more: false };
    return method === "status.get" ? { active_turn: false } : {};
  });
  api.subscribeAgentEvents = (listener) => { eventListener = listener; return () => { eventListener = null; }; };
  api.readPreference = async (key) => {
    const values: Record<string, unknown> = {
      theme: "light", language: "en", panelMode: "docked", sidebarWidth: 286, runtimePanelWidth: 318,
      recentProjects: [{ path: projectPath, alias: "Review owner", pinned: false }],
      projectAliases: { [projectPath]: "Review owner" }, pinnedProjectKeys: [], pinnedSessions: [],
      expandedProjects: { [projectPath]: true }, selectedProjectKey: projectPath, selectedSessionId: firstSession,
    };
    return values[key] as never;
  };
  const state = createInitialState({
    language: "en",
    mode: "coding",
    runtimeState: "ready",
    projects: [project],
    selectedProjectKey: projectPath,
    selectedSessionId: firstSession,
    expandedProjects: { [projectPath]: true },
    timeline: [
      { id: "review-tool-a", kind: "tool", text: "Read completed", toolName: "Read", status: "completed", outputPreview: "safe preview", outputPreviewTruncated: true, outputRef: "result-a", fileChanges: [{ path: "src/entry.ts", status: "modified" }] },
      { id: "review-tool-late", kind: "tool", text: "Run completed", toolName: "Run", status: "completed", outputPreview: "late preview", outputPreviewTruncated: true, outputRef: "result-late" },
    ],
    processLogs: { [sessionKey]: logs },
    processReaders: { [sessionKey]: { "process-review": { nextCursor: 1, earliestCursor: 0, cursorExpired: false, state: "running", expired: false, loading: false, error: null } } },
  });
  const flush = async () => { await act(async () => { for (let index = 0; index < 8; index += 1) await new Promise<void>((resolve) => setTimeout(resolve, 0)); }); };

  await withRendererDom(async (_dom, container, root) => {
    act(() => { root.render(<App api={api} initialState={state} />); });
    await flush();
    assert.ok(eventListener);
    const currentDiff = [...container.querySelectorAll<HTMLButtonElement>(".conversation-actions button")]
      .find((button) => button.getAttribute("aria-label") === "Review current diff");
    assert.ok(currentDiff);
    act(() => { currentDiff.click(); });
    await flush();
    assert.deepEqual(calls.find((call) => call.method === "workspace.diff")?.params, { project_key: projectPath });
    assert.match(container.querySelector(".review-panel")?.textContent ?? "", /\+ staged first/u);
    assert.match(container.querySelector(".review-panel")?.textContent ?? "", /- unstaged first/u);
    assert.match(container.querySelector(".review-panel")?.textContent ?? "", /src\/current\.ts/u);
    assert.equal(container.querySelector(".review-panel__content-header--diff time"), null, "viewed_at remains internal and is not shown in the workspace heading");

    const activities = [...container.querySelectorAll<HTMLDetailsElement>("details.timeline-activity-group")];
    assert.equal(activities.length, 2, "legacy entries without a Turn identity remain independently grouped");
    activities.forEach((activity) => act(() => { activity.querySelector("summary")?.dispatchEvent(new _dom.window.MouseEvent("click", { bubbles: true })); }));
    const activityItems = activities.flatMap((activity) => [...activity.querySelectorAll<HTMLDetailsElement>("details.timeline-activity-item")]);
    assert.equal(activityItems.length, 2);
    assert.equal(activityItems.every((item) => !item.open), true, "tool input and output actions start behind their own disclosure");
    activityItems.forEach((item) => { item.open = true; });
    const pathDiff = [...container.querySelectorAll<HTMLButtonElement>(".timeline-file-changes button")]
      .find((button) => button.textContent?.includes("src/entry.ts"));
    assert.ok(pathDiff);
    act(() => { pathDiff.click(); });
    await flush();
    assert.deepEqual(calls.filter((call) => call.method === "workspace.diff")[1]?.params, { project_key: projectPath, path: "src/entry.ts" });
    assert.match(container.querySelector(".review-panel")?.textContent ?? "", /\+ staged path/u);
    const reviewTabs = () => [...container.querySelectorAll<HTMLButtonElement>(".review-panel__tabs [role='tab']")];
    assert.deepEqual(reviewTabs().map((tab) => tab.textContent), ["Current working tree", "entry.ts"]);
    assert.equal(reviewTabs()[1]?.getAttribute("aria-selected"), "true");
    act(() => { reviewTabs()[0]!.click(); });
    assert.equal(reviewTabs()[0]?.getAttribute("aria-selected"), "true");
    assert.equal(container.querySelector(".review-panel__content-header strong")?.textContent, "Current working tree");
    act(() => { reviewTabs()[1]!.click(); });
    assert.equal(reviewTabs()[1]?.getAttribute("aria-selected"), "true");
    assert.equal(container.querySelector(".review-panel__content-header strong")?.textContent, "Current working tree: src/entry.ts");
    const pathTabClose = [...container.querySelectorAll<HTMLElement>(".review-panel__tab")]
      .find((tab) => tab.querySelector("[role='tab']")?.textContent === "entry.ts")
      ?.querySelector<HTMLButtonElement>("button[aria-label]");
    assert.ok(pathTabClose);
    act(() => { pathTabClose.click(); });
    assert.deepEqual(reviewTabs().map((tab) => tab.textContent), ["Current working tree"]);
    assert.equal(container.querySelector(".review-panel__content-header strong")?.textContent, "Current working tree", "closing an inactive/selected tab keeps the remaining Review tab usable");

    const outputButtons = activities.flatMap((activity) => [...activity.querySelectorAll<HTMLButtonElement>(".timeline-tool-output")]);
    assert.equal(outputButtons.length, 2);
    assert.ok(container.querySelector(".timeline")?.getAttribute("data-session-key")?.includes(firstSession), container.querySelector(".timeline")?.getAttribute("data-session-key") ?? "no timeline session key");
    act(() => { outputButtons[0]!.click(); });
    await flush();
    assert.ok(calls.some((call) => call.method === "tool_result.read"), JSON.stringify(calls));
    assert.match(container.querySelector(".review-panel__output")?.textContent ?? "", /first/u);
    assert.ok((calls.find((call) => call.method === "tool_result.read")?.params.limit as number) <= 64 * 1024);
    const readMore = container.querySelector<HTMLButtonElement>(".review-panel__more");
    assert.ok(readMore);
    act(() => { readMore.click(); });
    await flush();
    assert.equal(container.querySelector(".review-panel__output")?.textContent, "firstsecond");
    assert.deepEqual(calls.filter((call) => call.method === "tool_result.read").map((call) => call.params.offset), [0, 5]);

    const processLog = [...container.querySelectorAll<HTMLButtonElement>(".timeline-process-log button")]
      .find((button) => button.textContent === "Review process log");
    assert.ok(processLog);
    act(() => { processLog.click(); });
    assert.match(container.querySelector(".review-panel")?.textContent ?? "", /first process line/u);
    const readNewer = [...container.querySelectorAll<HTMLButtonElement>(".review-panel__more")]
      .find((button) => button.textContent === "Read newer");
    assert.ok(readNewer);
    act(() => { readNewer.click(); });
    await flush();
    assert.deepEqual(calls.find((call) => call.method === "process.read")?.params, { process_id: "process-review", cursor: 1 });
    assert.match(container.querySelector(".review-panel__process-output")?.textContent ?? "", /continued process output/u);
    const loadedStdout = container.querySelector<HTMLElement>('[data-process-sequence="2"][data-process-stream="stdout"]');
    const loadedStderr = container.querySelector<HTMLElement>('[data-process-sequence="3"][data-process-stream="stderr"]');
    assert.equal(loadedStdout?.querySelector("small")?.textContent, "stdout · exited");
    assert.equal(loadedStdout?.querySelector("pre")?.textContent, "continued process output", "process.read_loaded preserves the returned text alongside its authoritative state");
    assert.equal(loadedStderr?.querySelector("small")?.textContent, "stderr · exited");
    assert.equal(loadedStderr?.querySelector("pre")?.textContent, "continued stderr output");
    assert.deepEqual(reviewTabs().map((tab) => tab.textContent), ["Current working tree", "Read", "Process log: process-review"]);
    act(() => { reviewTabs()[1]!.click(); });
    assert.equal(reviewTabs()[1]?.getAttribute("aria-selected"), "true");
    assert.equal(container.querySelector(".review-panel__output")?.textContent, "firstsecond");
    act(() => { reviewTabs()[2]!.click(); });
    assert.equal(reviewTabs()[2]?.getAttribute("aria-selected"), "true");
    assert.match(container.querySelector(".review-panel__process-output")?.textContent ?? "", /first process line/u);
    const processTabClose = [...container.querySelectorAll<HTMLElement>(".review-panel__tab")]
      .find((tab) => tab.querySelector("[role='tab']")?.textContent === "Process log: process-review")
      ?.querySelector<HTMLButtonElement>("button[aria-label]");
    assert.ok(processTabClose);
    act(() => { processTabClose.click(); });
    assert.deepEqual(reviewTabs().map((tab) => tab.textContent), ["Current working tree", "Read"]);
    assert.equal(container.querySelector(".review-panel").getAttribute("aria-label"), "File and log review");

    act(() => { outputButtons[1]!.click(); });
    await flush();
    assert.equal(typeof resolveLateOutput, "function");
    const secondSessionButton = [...container.querySelectorAll<HTMLButtonElement>("button.session-line")]
      .find((button) => button.textContent?.includes("Review session B"));
    assert.ok(secondSessionButton);
    act(() => { secondSessionButton.click(); });
    await flush();
    assert.equal(container.querySelector(".review-panel"), null, "switching Session closes the old owner tabs");
    resolveLateOutput!({ ref: "result-late", content: "late private page", offset: 0, next_offset: 17, total_bytes: 17, sha256: "b".repeat(64), eof: true });
    await flush();
    assert.doesNotMatch(container.textContent ?? "", /late private page/u);

    const nextOwnerDiff = [...container.querySelectorAll<HTMLButtonElement>(".conversation-actions button")]
      .find((button) => button.getAttribute("aria-label") === "Review current diff");
    assert.ok(nextOwnerDiff);
    act(() => { nextOwnerDiff.click(); });
    await flush();
    assert.match(container.querySelector(".review-panel")?.textContent ?? "", /Reading the current working tree/u);
    const firstSessionButton = [...container.querySelectorAll<HTMLButtonElement>("button.session-line")]
      .find((button) => button.textContent?.includes("Review session A"));
    assert.ok(firstSessionButton);
    act(() => { firstSessionButton.click(); });
    await flush();
    assert.ok(calls.some((call) => call.method === "workspace.diff.cancel" && call.params.operation_id === "review-diff-3"));
    eventListener!({ ...diffEvent("review-diff-3", "late old owner"), project_key: projectPath } as AgentEvent);
    await flush();
    assert.doesNotMatch(container.textContent ?? "", /late old owner/u);

    const failedDiff = [...container.querySelectorAll<HTMLButtonElement>(".conversation-actions button")]
      .find((button) => button.getAttribute("aria-label") === "Review current diff");
    assert.ok(failedDiff);
    act(() => { failedDiff.click(); });
    await flush();
    assert.match(container.querySelector(".review-panel")?.textContent ?? "", /unavailable/u);
    const closePanel = container.querySelector<HTMLButtonElement>(".review-panel__header button[aria-label='Close file preview']");
    assert.ok(closePanel);
    act(() => { closePanel.click(); });
    assert.equal(container.querySelector(".review-panel"), null, "closing the Review panel clears the owner-bound tabs");
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
  assert.match(css, /\.composer\s*\{[^}]*container-name:\s*composer-controls;[^}]*container-type:\s*inline-size/su);
  const narrowComposer = css.split("@container conversation (max-width: 720px)")[1]?.split("@container composer-controls (min-width: 600px)")[0];
  const wideComposer = css.split("@container composer-controls (min-width: 600px)")[1];
  assert.ok(narrowComposer);
  assert.ok(wideComposer);
  assert.match(narrowComposer, /\.composer-toolbar\s*\{[^}]*display:\s*flex;[^}]*flex-wrap:\s*nowrap/su, "compact controls stay on one row when the conversation column narrows");
  assert.match(css, /\.composer-toolbar\s*\{[^}]*justify-content:\s*space-between/su, "the toolbar reserves the left side for permission/attachments and the right side for model/context/send");
  assert.match(css, /\.composer-right-controls\s*\{[^}]*margin-left:\s*auto/su);
  assert.match(css, /\.composer \.custom-select--responsive-trigger\s*\{[^}]*width:\s*30px;[^}]*min-width:\s*30px;[^}]*flex:\s*0 0 30px/su);
  assert.match(wideComposer, /\.composer-selectors \.custom-select--responsive-trigger\s*\{[^}]*width:\s*138px/su);
  assert.match(wideComposer, /\.composer-model \.custom-select--responsive-trigger,[\s\S]*?\.composer-model \.custom-select--responsive-trigger\s*\{[^}]*width:\s*max-content;[^}]*max-width:\s*100%;[^}]*flex:\s*0 1 auto/su, "wide model label uses its natural width while remaining constrained by available Composer space");
  assert.match(wideComposer, /\.custom-select__responsive-label\s*\{[^}]*display:\s*block/su);
  assert.match(wideComposer, /\.custom-select__trigger > \.ui-icon:nth-of-type\(2\)\s*\{[^}]*display:\s*block/su);
  assert.match(narrowComposer, /\.composer-attachment-actions button\s*\{[^}]*white-space:\s*nowrap/su);
  assert.doesNotMatch(css, /@container conversation \(max-width: 380px\)/u, "the former stacked toolbar does not reappear on a very narrow panel");
  assert.doesNotMatch(css, /\.composer\[data-empty="true"\] \.composer-toolbar\s*\{[^}]*grid-template-columns/u, "empty content does not switch to a separate toolbar layout");
  assert.match(css, /@container composer-controls \(max-width: 599px\)[\s\S]*?\.composer \.composer-send\s*\{[^}]*width:\s*30px;[^}]*min-width:\s*30px/su, "the narrow send icon shares the compact control rail in every turn state");
  assert.match(css, /@container composer-controls \(max-width: 599px\)[\s\S]*?\.composer \.composer-send__label\s*\{\s*display:\s*none/su);
  assert.match(css, /@media \(max-width: 820px\)[\s\S]*?\.app-shell\.panel-docked \.composer-input\s*\{[^}]*display:\s*flex;[^}]*flex-direction:\s*column;[^}]*gap:\s*6px/su, "filled text entry keeps its existing stacked narrow layout");
  assert.match(css, /@media \(max-width: 820px\)[\s\S]*?\.app-shell\.panel-docked \.composer-toolbar\s*\{[^}]*display:\s*flex;[^}]*flex-wrap:\s*nowrap/su, "the filled toolbar does not wrap as the text area grows");
  assert.match(css, /\.app-shell\.panel-docked \.composer\[data-empty="true"\]\s*\{\s*padding-bottom:\s*8px;/su, "the narrow docked empty composer keeps its fixed height");
  assert.match(css, /@media \(max-width: 820px\)[\s\S]*?\.app-shell\.panel-docked \.composer\[data-empty="true"\] \.composer-input\s*\{[^}]*display:\s*grid;[^}]*grid-template-columns:\s*minmax\(0, 1fr\) auto;[^}]*gap:\s*8px/su, "the empty docked input row avoids the filled state's extra vertical gap");
});

test("Composer keeps mode controls left and model, context, and send together on the right", async () => {
  const common = { runtimeState: "ready" as const, currentModelRef: "provider/model", modelCandidates: ["provider/model"], configuration: { models: { "provider/model": { display_name: "Model" } } } };
  const states = [
    createInitialState({ ...common, mode: "coding", composerText: "" }),
    createInitialState({ ...common, mode: "coding", composerText: "draft" }),
    createInitialState({ ...common, mode: "coding", composerText: "", activeTurn: true, turnStatus: "running", run: { run_id: "run-active" } }),
    createInitialState({ ...common, mode: "coding", composerText: "continue", activeTurn: true, turnStatus: "running", run: { run_id: "run-active" } }),
    createInitialState({ ...common, mode: "general", composerText: "draft" }),
  ];
  await withRendererDom(async (_dom, container, root) => {
    for (const state of states) {
      await act(async () => { root.render(<LanguageProvider value="en"><Composer state={state} onChange={() => undefined} onSubmit={() => undefined} onCommand={() => undefined} onPause={() => undefined} onCancel={() => undefined} /></LanguageProvider>); });
      const toolbar = container.querySelector<HTMLElement>(".composer-toolbar");
      const right = toolbar?.querySelector<HTMLElement>(":scope > .composer-right-controls");
      assert.ok(toolbar);
      assert.ok(right);
      assert.ok(right.querySelector(":scope > .composer-model"));
      assert.ok(right.querySelector(":scope > .composer-send"));
      assert.equal(right.querySelector(":scope > .composer-model .context-ring") !== null, state.mode === "coding");
      const left = toolbar.querySelector<HTMLElement>(":scope > .composer-selectors");
      assert.equal(left !== null, state.mode === "coding");
      if (left) {
        assert.ok(left.querySelector(".custom-select__trigger"));
        assert.ok(left.compareDocumentPosition(right) & container.ownerDocument.defaultView!.Node.DOCUMENT_POSITION_FOLLOWING, "permission stays before the right-aligned model controls");
      }
      assert.equal(right.querySelector(".composer-send")?.getAttribute("aria-label"), state.activeTurn && state.composerText.trim() ? "Steer" : "Send");
      assert.equal(right.querySelector<HTMLButtonElement>(".composer-send")?.disabled, !state.composerText.trim() && (state.activeTurn || state.composerAttachments.length === 0), "empty active-turn steering stays disabled while idle attachment-only submission remains available");
    }
  });
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
    assert.equal(container.querySelectorAll(".composer-attachments .file-card[data-file-ref='att-1']").length, 1);
    const imageCard = container.querySelector<HTMLElement>(".composer-attachments .file-card[data-file-kind='image']");
    assert.equal(imageCard?.getAttribute("aria-label"), "diagram.png · image");
    assert.equal(imageCard?.querySelector("img")?.getAttribute("alt"), "diagram.png");
    assert.equal(imageCard?.querySelectorAll(".file-card__meta").length ?? 0, 0);
    act(() => { send!.click(); });
    await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    assert.equal(turnStarts, 2);
    assert.equal(container.querySelectorAll(".composer-attachments .file-card[data-file-ref='att-1']").length, 0);
    assert.equal(container.querySelectorAll(".timeline-entry--user .file-card[data-file-ref='att-1']").length, 1);
  });
});

test("T10 a successful lazy Turn preserves the edited prompt and attachment vector", async () => {
  const projectPath = "C:/t10-lazy-draft-version";
  const laterAttachment = { ref: "att-later", display_name: "later.txt", mime_type: "text/plain", size_bytes: 6 };
  const calls: Array<{ method: string; params: Record<string, unknown> }> = [];
  let resolveTurnStart: ((result: JsonValue) => void) | null = null;
  const api: DesktopApi = {
    openProject: async () => null,
    openProjectInExplorer: async () => undefined,
    copyText: async () => undefined,
    closeShell: async () => undefined,
    requestRuntime: async (method, params) => {
      calls.push({ method, params });
      if (method === "runtime.initialize") return { state: "ready", run: null };
      if (method === "settings.get") return { configuration: {} };
      if (method === "status.get") return { active_turn: false };
      if (method === "project.sessions") return { sessions: [] };
      if (method === "attachment.import") return { attachment: laterAttachment };
      if (method === "attachment.preview") return { attachment: laterAttachment };
      if (method === "turn.start") return new Promise<JsonValue>((resolve) => { resolveTurnStart = resolve; });
      return {};
    },
    subscribeAgentEvents: () => () => undefined,
    readPreference: async (key) => {
      const values: Record<string, unknown> = {
        theme: "light", language: "en", panelMode: "docked", sidebarWidth: 286, runtimePanelWidth: 318,
        recentProjects: [{ path: projectPath, alias: "Draft version" }], projectAliases: {}, pinnedProjectKeys: [], pinnedSessions: [], expandedProjects: {},
        selectedProjectKey: projectPath, selectedSessionId: null,
      };
      return values[key] as never;
    },
    writePreference: async () => ({}) as never,
    chooseAttachment: async () => ({ name: "later.txt", mime_type: "text/plain", data_base64: "bGF0ZXI=" }),
    pasteAttachment: async () => null,
  };
  const project: ProjectState = { path: projectPath, projectKey: projectPath, alias: "Draft version", pinned: false, sessions: [], catalogFresh: true };
  const initialState = createInitialState({
    language: "en",
    runtimeState: "ready",
    composerText: "submitted prompt",
    composerAttachments: [attachment],
    projects: [project],
    selectedProjectKey: projectPath,
    selectedSessionId: null,
  });
  await withRendererDom(async (dom, container, root) => {
    act(() => { root.render(<App initialState={initialState} api={api} />); });
    const flush = async () => { await act(async () => { for (let index = 0; index < 5; index += 1) await new Promise<void>((resolve) => setTimeout(resolve, 0)); }); };
    await flush();
    const send = container.querySelector<HTMLButtonElement>(".composer-send");
    assert.ok(send);
    act(() => { send!.click(); });
    await flush();
    assert.equal(typeof resolveTurnStart, "function");
    assert.deepEqual(calls.find((call) => call.method === "turn.start")?.params, {
      prompt: "submitted prompt",
      attachments: [{ ref: attachment.ref, kind: "image" }],
    });

    const textarea = container.querySelector<HTMLTextAreaElement>(".composer textarea");
    assert.ok(textarea);
    const setter = Object.getOwnPropertyDescriptor(dom.window.HTMLTextAreaElement.prototype, "value")?.set;
    assert.ok(setter);
    act(() => {
      textarea!.focus();
      setter!.call(textarea, "later draft text");
      textarea!.dispatchEvent(new dom.window.InputEvent("input", { bubbles: true, inputType: "insertText", data: "later draft text" }));
      textarea!.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
      textarea!.dispatchEvent(new dom.window.KeyboardEvent("keyup", { bubbles: true, key: "Unidentified" }));
    });
    await flush();
    const choose = container.querySelector<HTMLButtonElement>(".composer-attachment-actions button");
    assert.ok(choose);
    act(() => { choose!.click(); });
    await flush();
    assert.equal(container.querySelectorAll(".composer-attachments .file-card").length, 2, "a later attachment joins the still-editable draft while the first request is pending");
    assert.equal(textarea!.value, "later draft text");

    act(() => { resolveTurnStart!({ run_id: "run-lazy-version", turn_id: "turn-lazy-version", status: "running", session_id: "session-lazy-version" }); });
    await flush();
    assert.equal(container.querySelector<HTMLTextAreaElement>(".composer textarea")?.value, "later draft text", "success clears only the submitted text value");
    assert.equal(container.querySelectorAll(".composer-attachments .file-card").length, 2, "success does not clear later attachment refs");
    assert.equal(calls.some((call) => call.method === "session.new"), false, "first accepted Turn uses the returned lazy Session identity");
  });
});

test("General lazy Turns keep their accepted Session out of the Coding resume preference", async () => {
  const writes: Array<{ key: string; value: unknown }> = [];
  const calls: string[] = [];
  const api: DesktopApi = {
    ...appTestApi(async (method) => {
      calls.push(method);
      if (method === "turn.start") return { run_id: "run-general-lazy", turn_id: "turn-general-lazy", status: "running", session_id: "general-lazy-session" };
      if (method === "status.get") return { active_turn: false };
      if (method === "project.sessions") return { sessions: [{ session_id: "general-lazy-session", project_key: "uthcode:general", preview: "hello" }] };
      return {};
    }),
    readPreference: async () => await new Promise<never>(() => undefined) as never,
    writePreference: async (key, value) => { writes.push({ key, value }); return {} as never; },
  };
  const state = createInitialState({
    mode: "general",
    language: "en",
    runtimeState: "ready",
    composerText: "hello from General",
    selectedProjectKey: "uthcode:general",
    selectedSessionId: null,
    projects: [{ path: "uthcode:general", projectKey: "uthcode:general", alias: "General", pinned: false, sessions: [], catalogFresh: true }],
  });
  await withRendererDom(async (_dom, container, root) => {
    act(() => { root.render(<App initialState={state} api={api} />); });
    await act(async () => { for (let index = 0; index < 4; index += 1) await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    const send = container.querySelector<HTMLButtonElement>(".composer-send");
    assert.ok(send);
    act(() => { send!.click(); });
    await act(async () => { for (let index = 0; index < 4; index += 1) await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
    assert.ok(calls.includes("turn.start"));
    assert.match(container.querySelector(".conversation-title h1")?.textContent ?? "", /^Session general-/u, "the accepted lazy Session still becomes the live General owner");
    assert.equal(writes.some((write) => write.key === "selectedSessionId" && write.value === "general-lazy-session"), false, "the General Session ID cannot poison Coding startup selection");
  });
});

test("App moves a sent attachment into the user row and merges the empty-text authoritative message id", async () => {
  const calls: Array<{ method: string; params: Record<string, unknown> }> = [];
  let eventListener: ((event: AgentEvent) => void) | null = null;
  const api: DesktopApi = {
    openProject: async () => null,
    openProjectInExplorer: async () => undefined,
    copyText: async () => undefined,
    closeShell: async () => undefined,
    requestRuntime: async (method, params) => {
      calls.push({ method, params });
      if (method === "turn.start") return { run_id: "run-attachment-app", turn_id: "turn-attachment-app", status: "running" };
      if (method === "status.get") return { active_turn: false };
      return {};
    },
    subscribeAgentEvents: (listener) => { eventListener = listener; return () => { eventListener = null; }; },
    readPreference: async (key) => {
      const values: Record<string, unknown> = {
        theme: "light", language: "en", panelMode: "docked", sidebarWidth: 286, runtimePanelWidth: 318,
        recentProjects: [], projectAliases: {}, pinnedProjectKeys: [], pinnedSessions: [], expandedProjects: {},
        selectedProjectKey: null, selectedSessionId: null,
      };
      return values[key] as never;
    },
    writePreference: async () => ({}) as never,
    chooseAttachment: async () => null,
    pasteAttachment: async () => null,
  };
  await withRendererDom(async (_dom, container, root) => {
    act(() => { root.render(<App initialState={createInitialState({ language: "en", runtimeState: "ready", composerAttachments: [attachment] })} api={api} />); });
    const flush = async () => { await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); await new Promise<void>((resolve) => setTimeout(resolve, 0)); }); };
    await flush();
    const send = container.querySelector<HTMLButtonElement>(".composer-send");
    assert.ok(send);
    act(() => { send.click(); });
    await flush();
    assert.deepEqual(calls.find((call) => call.method === "turn.start")?.params, {
      prompt: "",
      attachments: [{ ref: "att-1", kind: "image" }],
    });
    assert.equal(container.querySelectorAll(".composer-attachments").length, 0);
    assert.equal(container.querySelectorAll(".timeline-entry--user").length, 1);
    assert.ok(container.querySelector(".timeline-entry--user .timeline-attachments"));
    assert.ok(eventListener);
    act(() => { eventListener!({
      type: "turn_started",
      run_id: "run-attachment-app",
      turn_id: "turn-attachment-app",
      message_id: "authoritative-attachment-message",
      message: { role: "user", parts: [] },
    }); });
    await flush();
    const userRows = container.querySelectorAll<HTMLElement>(".timeline-entry--user");
    assert.equal(userRows.length, 1);
    assert.ok(userRows[0]?.querySelector(".timeline-attachments"));
  });
});

test("App adopts a lazy first Session before replaying early attachment events and merges UUID history identities", async () => {
  const projectPath = "C:/lazy-first-session";
  const lazySessionId = "lazy-session-created-by-turn";
  const otherSessionId = "other-session";
  const runId = "run-lazy-session";
  const turnId = "turn-lazy-session";
  const userMessageId = "d95b5ac8-e07d-4ba2-8e67-ca0b59842ba1";
  const reasoningBeforeId = "74d2ae9c-a790-4b43-a839-e2fb95f3c00d";
  const assistantMessageId = "589fe495-5b8f-45cc-9ed8-5faec24fe2d1";
  const toolCallId = "call-lazy-session";
  const prompt = "Read sample.xlsx";
  const otherSession = { session_id: otherSessionId, title: "Other session", preview: "Existing chat" };
  const lazySession = { session_id: lazySessionId, title: "First attachment chat", preview: prompt };
  const durableRecords = [
    { record_id: `${lazySessionId}:1:user::0`, session_id: lazySessionId, sequence: 1, turn_id: turnId, message_id: userMessageId, kind: "user", text: prompt },
    { record_id: `${lazySessionId}:3:assistant::0`, session_id: lazySessionId, sequence: 3, turn_id: turnId, message_id: reasoningBeforeId, kind: "reasoning", text: "I will inspect the workbook." },
    { record_id: `${lazySessionId}:5:tool:${toolCallId}:-`, session_id: lazySessionId, sequence: 5, run_id: runId, turn_id: turnId, tool_call_id: toolCallId, kind: "tool", tool_name: "ReadDocument", text: "ReadDocument", status: "succeeded", is_error: false },
    { record_id: `${lazySessionId}:6:assistant::0`, session_id: lazySessionId, sequence: 6, turn_id: turnId, message_id: assistantMessageId, kind: "reasoning", text: "The workbook is readable." },
    { record_id: `${lazySessionId}:7:assistant::1`, session_id: lazySessionId, sequence: 7, turn_id: turnId, message_id: assistantMessageId, kind: "assistant", text: "The workbook has one sheet." },
  ];
  assert.notEqual(durableRecords[0]?.record_id, userMessageId);
  const identity = { run_id: runId, turn_id: turnId, session_id: lazySessionId, project_key: projectPath };
  const earlyEvents: Record<string, unknown>[] = [
    { type: "turn_started", ...identity, message_id: userMessageId, message: { role: "user", parts: [{ type: "text", text: prompt }] } },
    { type: "reasoning_started", ...identity, message_id: reasoningBeforeId },
    { type: "reasoning_delta", ...identity, message_id: reasoningBeforeId, text: "I will inspect the workbook." },
    { type: "assistant_message_completed", ...identity, message_id: reasoningBeforeId, kind: "progress", message: { role: "assistant", parts: [{ type: "reasoning", text: "I will inspect the workbook." }, { type: "tool_call", tool_call_id: toolCallId, name: "ReadDocument", arguments: { path: "sample.xlsx" } }] } },
    { type: "tool_started", ...identity, batch_id: "batch-lazy", tool_call_id: toolCallId, tool_name: "ReadDocument", command: "sample.xlsx" },
    { type: "tool_finished", ...identity, batch_id: "batch-lazy", tool_call_id: toolCallId, tool_name: "ReadDocument", command: "sample.xlsx", status: "succeeded", is_error: false },
    { type: "reasoning_started", ...identity, message_id: assistantMessageId },
    { type: "reasoning_delta", ...identity, message_id: assistantMessageId, text: "The workbook is readable." },
    { type: "assistant_message_completed", ...identity, message_id: assistantMessageId, message: { role: "assistant", parts: [{ type: "reasoning", text: "The workbook is readable." }, { type: "text", text: "The workbook has one sheet." }] } },
    { type: "turn_completed", ...identity, final_text: "The workbook has one sheet." },
  ];
  const calls: Array<{ method: string; params: Record<string, unknown> }> = [];
  const preferenceWrites: Array<{ key: string; value: unknown }> = [];
  let eventListener: ((event: AgentEvent) => void) | null = null;
  let resolveTurnStart: ((result: JsonValue) => void) | null = null;
  let turnStartAccepted = false;
  const api: DesktopApi = {
    openProject: async () => null,
    openProjectInExplorer: async () => undefined,
    copyText: async () => undefined,
    closeShell: async () => undefined,
    requestRuntime: async (method, params) => {
      calls.push({ method, params });
      if (method === "runtime.initialize") return { run: null };
      if (method === "settings.get") return { configuration: {} };
      if (method === "status.get") return { active_turn: false };
      if (method === "project.sessions") return { sessions: turnStartAccepted ? [lazySession, otherSession] : [otherSession] };
      if (method === "turn.start") {
        earlyEvents.forEach((event) => eventListener?.(event as AgentEvent));
        return new Promise<JsonValue>((resolve) => { resolveTurnStart = resolve; });
      }
      if (method === "session.resume") {
        const sessionId = String(params.session_id ?? "");
        return {
          session_id: sessionId,
          replay: [],
          active_turn: false,
          run: sessionId === lazySessionId ? { run_id: runId, turn_id: turnId, status: "completed" } : null,
        };
      }
      if (method === "history.page") {
        const sessionId = String(params.session_id ?? "");
        return { session_id: sessionId, records: sessionId === lazySessionId ? durableRecords : [], next_cursor: null, has_more: false };
      }
      return {};
    },
    subscribeAgentEvents: (listener) => { eventListener = listener; return () => { eventListener = null; }; },
    readPreference: async (key) => {
      const values: Record<string, unknown> = {
        theme: "light", language: "en", panelMode: "docked", sidebarWidth: 286, runtimePanelWidth: 318,
        recentProjects: [{ path: projectPath, alias: "Lazy project", pinned: false }],
        projectAliases: { [projectPath]: "Lazy project" }, pinnedProjectKeys: [], pinnedSessions: [],
        expandedProjects: { [projectPath]: true }, selectedProjectKey: projectPath, selectedSessionId: null,
      };
      return values[key] as never;
    },
    writePreference: async (key, value) => { preferenceWrites.push({ key, value }); return {} as never; },
    chooseAttachment: async () => null,
    pasteAttachment: async () => null,
  };
  const state = createInitialState({
    language: "en",
    runtimeState: "ready",
    composerText: prompt,
    composerAttachments: [attachment],
    projects: [{ path: projectPath, projectKey: projectPath, alias: "Lazy project", pinned: false, sessions: [otherSession], catalogFresh: true }],
    selectedProjectKey: projectPath,
    selectedSessionId: null,
    expandedProjects: { [projectPath]: true },
  });

  await withRendererDom(async (dom, container, root) => {
    act(() => { root.render(<App initialState={state} api={api} />); });
    const flush = async () => {
      await act(async () => {
        for (let index = 0; index < 8; index += 1) await new Promise<void>((resolve) => setTimeout(resolve, 0));
      });
    };
    const sessionButton = (label: string) => [...container.querySelectorAll<HTMLButtonElement>("button.session-line")]
      .find((button) => button.textContent?.includes(label));
    await flush();
    assert.equal(Boolean(eventListener), true);
    const send = container.querySelector<HTMLButtonElement>(".composer-send");
    assert.equal(Boolean(send), true);
    const statusCallsBeforeStart = calls.filter((call) => call.method === "status.get").length;
    act(() => { send!.click(); });
    await flush();
    assert.equal(typeof resolveTurnStart, "function");
    assert.equal(container.querySelectorAll(".composer-attachments .file-card[data-file-ref='att-1']").length, 1);

    turnStartAccepted = true;
    act(() => { resolveTurnStart!({ run_id: runId, turn_id: turnId, status: "running", session_id: lazySessionId }); });
    await flush();
    assert.deepEqual(calls.find((call) => call.method === "turn.start")?.params, {
      prompt,
      attachments: [{ ref: attachment.ref, kind: "image" }],
    });
    assert.equal(calls.some((call) => call.method === "session.new"), false);
    assert.equal(preferenceWrites.some((item) => item.key === "selectedSessionId" && item.value === lazySessionId), true);
    assert.equal(calls.filter((call) => call.method === "status.get").length > statusCallsBeforeStart, true);
    assert.equal(container.querySelectorAll(".timeline-entry--user").length, 1);
    const restoredActivity = container.querySelector<HTMLElement>("details.timeline-activity-group");
    assert.ok(restoredActivity);
    assert.equal(container.querySelectorAll("details.timeline-activity-group").length, 1, "live and replayed entries from one Turn share one activity group");
    assert.equal(restoredActivity.dataset.turnId, turnId);
    assert.equal(restoredActivity.querySelectorAll(".timeline-activity-reasoning").length, 2);
    assert.equal(restoredActivity.querySelectorAll(".timeline-activity-item").length, 1);
    assert.match(restoredActivity.textContent ?? "", /ReadDocument/u);

    const otherButton = sessionButton("Other session");
    assert.equal(Boolean(otherButton), true);
    act(() => { otherButton!.click(); });
    await flush();
    assert.equal(calls.some((call) => call.method === "session.resume" && call.params.session_id === otherSessionId), true);
    assert.equal(container.querySelectorAll(".timeline-entry").length, 0);

    const lazyButton = sessionButton("First attachment chat");
    assert.equal(Boolean(lazyButton), true);
    act(() => { lazyButton!.click(); });
    await flush();
    const rows = [...container.querySelectorAll<HTMLElement>(".timeline-entry")];
    const kinds = rows.map((row) => [...row.classList].find((name) => name.startsWith("timeline-entry--"))?.slice("timeline-entry--".length));
    assert.deepEqual(kinds, ["user", "assistant"], "reasoning and tools are grouped outside the message rows");
    assert.equal(rows.filter((row) => row.classList.contains("timeline-entry--user")).length, 1);
    const replayedActivity = container.querySelector<HTMLElement>("details.timeline-activity-group");
    assert.ok(replayedActivity);
    assert.equal(container.querySelectorAll("details.timeline-activity-group").length, 1);
    assert.equal(replayedActivity.dataset.turnId, turnId);
    assert.equal(replayedActivity.dataset.reasoningCount, "2");
    assert.equal(replayedActivity.querySelectorAll(".timeline-activity-reasoning").length, 2);
    assert.equal(replayedActivity.querySelectorAll(".timeline-activity-item").length, 1);
    assert.match(replayedActivity.textContent ?? "", /ReadDocument/u);
    assert.equal(container.querySelectorAll(".timeline-entry--user .file-card[data-file-ref='att-1']").length, 1);
    assert.equal(calls.some((call) => call.method === "history.page" && call.params.session_id === lazySessionId), true);
  });
});

test("App parks a lazy turn accepted after navigation without stealing the selected Session", async () => {
  const projectPath = "C:/lazy-session-navigation-race";
  const lazySessionId = "lazy-session-race";
  const otherSessionId = "existing-session-race";
  const runId = "run-lazy-race";
  const turnId = "turn-lazy-race";
  const userMessageId = "b73322b9-e69f-4413-b5a8-b4582e2fc838";
  const otherRunId = "run-existing-background";
  const otherTurnId = "turn-existing-background";
  const otherMessageId = "a5f0d79d-24a6-4b2d-9c39-6221af8f1836";
  const prompt = "Read sample.xlsx";
  const otherSession = { session_id: otherSessionId, title: "Existing session", preview: "Existing chat" };
  const lazySession = { session_id: lazySessionId, title: "New background session", preview: prompt };
  const calls: Array<{ method: string; params: Record<string, unknown> }> = [];
  const preferenceWrites: Array<{ key: string; value: unknown }> = [];
  let eventListener: ((event: AgentEvent) => void) | null = null;
  let resolveTurnStart: ((result: JsonValue) => void) | null = null;
  let turnStartAccepted = false;
  const identity = { run_id: runId, turn_id: turnId, session_id: lazySessionId, project_key: projectPath };
  const earlyEvents: Record<string, unknown>[] = [
    { type: "turn_started", ...identity, message_id: userMessageId, message: { role: "user", parts: [{ type: "text", text: prompt }] } },
    { type: "reasoning_started", run_id: otherRunId, turn_id: otherTurnId, session_id: otherSessionId, project_key: projectPath, message_id: otherMessageId },
    { type: "reasoning_delta", run_id: otherRunId, turn_id: otherTurnId, session_id: otherSessionId, project_key: projectPath, message_id: otherMessageId, text: "Background work continued." },
    { type: "turn_completed", ...identity, final_text: "The workbook has one sheet." },
  ];
  const api: DesktopApi = {
    openProject: async () => null,
    openProjectInExplorer: async () => undefined,
    copyText: async () => undefined,
    closeShell: async () => undefined,
    requestRuntime: async (method, params) => {
      calls.push({ method, params });
      if (method === "runtime.initialize") return { run: null };
      if (method === "settings.get") return { configuration: {} };
      if (method === "status.get") return { active_turn: false };
      if (method === "project.sessions") return { sessions: turnStartAccepted ? [lazySession, otherSession] : [otherSession] };
      if (method === "turn.start") {
        earlyEvents.forEach((event) => eventListener?.(event as AgentEvent));
        return new Promise<JsonValue>((resolve) => { resolveTurnStart = resolve; });
      }
      if (method === "session.resume") {
        const sessionId = String(params.session_id ?? "");
        return { session_id: sessionId, replay: [], active_turn: false, run: null };
      }
      if (method === "history.page") {
        const sessionId = String(params.session_id ?? "");
        return {
          session_id: sessionId,
          records: sessionId === lazySessionId
            ? [{ record_id: `${lazySessionId}:1:user::0`, session_id: lazySessionId, sequence: 1, turn_id: turnId, message_id: userMessageId, kind: "user", text: prompt }]
            : [],
          next_cursor: null,
          has_more: false,
        };
      }
      return {};
    },
    subscribeAgentEvents: (listener) => { eventListener = listener; return () => { eventListener = null; }; },
    readPreference: async (key) => {
      const values: Record<string, unknown> = {
        theme: "light", language: "en", panelMode: "docked", sidebarWidth: 286, runtimePanelWidth: 318,
        recentProjects: [{ path: projectPath, alias: "Race project", pinned: false }], projectAliases: { [projectPath]: "Race project" },
        pinnedProjectKeys: [], pinnedSessions: [], expandedProjects: { [projectPath]: true },
        selectedProjectKey: projectPath, selectedSessionId: null,
      };
      return values[key] as never;
    },
    writePreference: async (key, value) => { preferenceWrites.push({ key, value }); return {} as never; },
    chooseAttachment: async () => null,
    pasteAttachment: async () => null,
  };
  const state = createInitialState({
    language: "en",
    runtimeState: "ready",
    composerText: prompt,
    composerAttachments: [attachment],
    projects: [{ path: projectPath, projectKey: projectPath, alias: "Race project", pinned: false, sessions: [otherSession], catalogFresh: true }],
    selectedProjectKey: projectPath,
    selectedSessionId: null,
    expandedProjects: { [projectPath]: true },
  });

  await withRendererDom(async (_dom, container, root) => {
    act(() => { root.render(<App initialState={state} api={api} />); });
    const flush = async () => {
      await act(async () => {
        for (let index = 0; index < 8; index += 1) await new Promise<void>((resolve) => setTimeout(resolve, 0));
      });
    };
    const sessionButton = (label: string) => [...container.querySelectorAll<HTMLButtonElement>("button.session-line")]
      .find((button) => button.textContent?.includes(label));
    await flush();
    const send = container.querySelector<HTMLButtonElement>(".composer-send");
    assert.equal(Boolean(send), true);
    act(() => { send!.click(); });
    await flush();
    assert.equal(typeof resolveTurnStart, "function");

    const otherButton = sessionButton("Existing session");
    assert.equal(Boolean(otherButton), true);
    act(() => { otherButton!.click(); });
    await flush();
    assert.equal(container.querySelectorAll(".session-line.is-selected").length, 1);
    assert.equal(container.querySelector(".session-line.is-selected")?.textContent?.includes("Existing session"), true);

    turnStartAccepted = true;
    act(() => { resolveTurnStart!({ run_id: runId, turn_id: turnId, status: "running", session_id: lazySessionId }); });
    await flush();
    assert.equal(container.querySelectorAll(".session-line.is-selected").length, 1);
    assert.equal(container.querySelector(".session-line.is-selected")?.textContent?.includes("Existing session"), true);
    assert.equal(container.querySelectorAll(".timeline-entry").length, 0, "background Turn activity does not become a message row in the selected Session");
    const backgroundActivity = container.querySelector<HTMLElement>(`details.timeline-activity-group[data-turn-id="${otherTurnId}"]`);
    assert.ok(backgroundActivity, "the background Turn is retained under its own activity group");
    assert.equal(backgroundActivity.querySelector(".timeline-activity-reasoning")?.textContent?.includes("Background work continued."), true);
    assert.equal(preferenceWrites.some((item) => item.key === "selectedSessionId" && item.value === lazySessionId), false);
    assert.equal(preferenceWrites.some((item) => item.key === "selectedSessionId" && item.value === otherSessionId), true);
    assert.equal(calls.some((call) => call.method === "project.sessions") && sessionButton("New background session") !== undefined, true);

    const lazyButton = sessionButton("New background session");
    assert.equal(Boolean(lazyButton), true);
    act(() => { lazyButton!.click(); });
    await flush();
    assert.equal(container.querySelectorAll(".timeline-entry--user").length, 1);
    assert.equal(container.querySelectorAll(".timeline-entry--user .file-card[data-file-ref='att-1']").length, 0);
  });
});

test("App does not report a lazy turn-start error in a Session opened while the request was pending", async () => {
  const projectPath = "C:/lazy-session-rejection-race";
  const otherSessionId = "existing-session-after-rejection";
  const otherSession = { session_id: otherSessionId, title: "Existing session", preview: "Existing chat" };
  let eventListener: ((event: AgentEvent) => void) | null = null;
  let rejectTurnStart: ((error: Error) => void) | null = null;
  const api: DesktopApi = {
    openProject: async () => null,
    openProjectInExplorer: async () => undefined,
    copyText: async () => undefined,
    closeShell: async () => undefined,
    requestRuntime: async (method) => {
      if (method === "runtime.initialize") return { run: null };
      if (method === "settings.get") return { configuration: {} };
      if (method === "status.get") return { active_turn: false };
      if (method === "project.sessions") return { sessions: [otherSession] };
      if (method === "turn.start") return new Promise<JsonValue>((_resolve, reject) => { rejectTurnStart = reject; });
      if (method === "session.resume") return { session_id: otherSessionId, replay: [], active_turn: false, run: null };
      if (method === "history.page") return { session_id: otherSessionId, records: [], next_cursor: null, has_more: false };
      return {};
    },
    subscribeAgentEvents: (listener) => { eventListener = listener; return () => { eventListener = null; }; },
    readPreference: async (key) => {
      const values: Record<string, unknown> = {
        theme: "light", language: "en", panelMode: "docked", sidebarWidth: 286, runtimePanelWidth: 318,
        recentProjects: [{ path: projectPath, alias: "Rejection project", pinned: false }],
        projectAliases: { [projectPath]: "Rejection project" }, pinnedProjectKeys: [], pinnedSessions: [],
        expandedProjects: { [projectPath]: true }, selectedProjectKey: projectPath, selectedSessionId: null,
      };
      return values[key] as never;
    },
    writePreference: async () => ({} as never),
    chooseAttachment: async () => null,
    pasteAttachment: async () => null,
  };
  const state = createInitialState({
    language: "en",
    runtimeState: "ready",
    composerText: "Read sample.xlsx",
    projects: [{ path: projectPath, projectKey: projectPath, alias: "Rejection project", pinned: false, sessions: [otherSession], catalogFresh: true }],
    selectedProjectKey: projectPath,
    selectedSessionId: null,
    expandedProjects: { [projectPath]: true },
  });

  await withRendererDom(async (_dom, container, root) => {
    act(() => { root.render(<App initialState={state} api={api} />); });
    const flush = async () => {
      await act(async () => {
        for (let index = 0; index < 8; index += 1) await new Promise<void>((resolve) => setTimeout(resolve, 0));
      });
    };
    await flush();
    assert.equal(Boolean(eventListener), true);
    const send = container.querySelector<HTMLButtonElement>(".composer-send");
    assert.equal(Boolean(send), true);
    act(() => { send!.click(); });
    await flush();
    assert.equal(typeof rejectTurnStart, "function");
    const sessionButton = [...container.querySelectorAll<HTMLButtonElement>("button.session-line")]
      .find((button) => button.textContent?.includes("Existing session"));
    assert.equal(Boolean(sessionButton), true);
    act(() => { sessionButton!.click(); });
    await flush();

    act(() => { rejectTurnStart!(new Error("stale turn-start failure")); });
    await flush();
    assert.equal(container.querySelectorAll(".session-line.is-selected").length, 1);
    assert.equal(container.querySelector(".session-line.is-selected")?.textContent?.includes("Existing session"), true);
    assert.equal(container.querySelectorAll(".timeline-notice").length, 0);
  });
});

test("App hydrates externalized tool output after terminal idle without replacing a newer Session draft", async () => {
  const projectPath = "C:/first-turn-navigation";
  let eventListener: ((event: AgentEvent) => void) | null = null;
  const calls: Array<{ method: string; params: Record<string, unknown> }> = [];
  let resolveFirstSessionHistory: ((value: JsonValue) => void) | null = null;
  let firstSessionHistoryRequests = 0;
  const userMessageId = "d95b5ac8e07d4ba28e67ca0b59842ba1";
  const reasoningBeforeId = "74d2ae9ca7904b43a839e2fb95f3c00d";
  const assistantMessageId = "589fe4955b8f45cc9ed85faec24fe2d1";
  const reasoningAfterId = assistantMessageId;
  const durableRecords = [
    { record_id: "session-a:1:user::0", session_id: "session-a", sequence: 1, turn_id: "turn-a", message_id: userMessageId, kind: "user", text: "Read sample.xlsx" },
    { record_id: "session-a:3:assistant::0", session_id: "session-a", sequence: 3, turn_id: "turn-a", message_id: reasoningBeforeId, kind: "reasoning", text: "I will inspect the workbook." },
    { record_id: "tool-record", session_id: "session-a", sequence: 5, run_id: "run-a", turn_id: "turn-a", tool_call_id: "call-a", kind: "tool", tool_name: "ReadDocument", text: "ReadDocument", status: "succeeded", is_error: false, output_ref: "tool-result-ref:session-a:call-a" },
    { record_id: "session-a:6:assistant::0", session_id: "session-a", sequence: 6, turn_id: "turn-a", message_id: reasoningAfterId, kind: "reasoning", text: "The workbook is readable." },
    { record_id: "session-a:7:assistant::1", session_id: "session-a", sequence: 7, turn_id: "turn-a", message_id: assistantMessageId, kind: "assistant", text: "The workbook has one sheet." },
  ];
  const catalog = [
    { session_id: "session-a", title: "First session", preview: "Read sample.xlsx" },
    { session_id: "session-b", title: "Other session", preview: "Other conversation" },
  ];
  const api: DesktopApi = {
    openProject: async () => null,
    openProjectInExplorer: async () => undefined,
    copyText: async () => undefined,
    closeShell: async () => undefined,
    requestRuntime: async (method, params) => {
      calls.push({ method, params });
      if (method === "runtime.initialize") return { run: null };
      if (method === "settings.get") return { configuration: {} };
      if (method === "status.get") return { active_turn: false };
      if (method === "project.sessions") return { sessions: catalog };
      if (method === "session.new") return { session_id: "session-a", run: null };
      if (method === "turn.start") return { run_id: "run-a", turn_id: "turn-a", status: "running" };
      if (method === "session.resume") {
        const sessionId = String(params.session_id ?? "");
        return {
          session_id: sessionId,
          replay: [],
          run: sessionId === "session-a"
            ? { run_id: "run-a", turn_id: "turn-a", status: "completed" }
            : null,
        };
      }
      if (method === "history.page") {
        const sessionId = String(params.session_id ?? "");
        if (sessionId !== "session-a") return { session_id: sessionId, records: [], next_cursor: null, has_more: false };
        firstSessionHistoryRequests += 1;
        if (firstSessionHistoryRequests === 1) {
          return await new Promise<JsonValue>((resolve) => { resolveFirstSessionHistory = resolve; });
        }
        return { session_id: sessionId, records: durableRecords, next_cursor: null, has_more: false };
      }
      return {};
    },
    subscribeAgentEvents: (listener) => { eventListener = listener; return () => { eventListener = null; }; },
    readPreference: async (key) => {
      const values: Record<string, unknown> = {
        theme: "light", language: "en", panelMode: "docked", sidebarWidth: 286, runtimePanelWidth: 318,
        recentProjects: [{ path: projectPath, alias: "First-turn project", pinned: false }],
        projectAliases: { [projectPath]: "First-turn project" }, pinnedProjectKeys: [], pinnedSessions: [],
        expandedProjects: { [projectPath]: true }, selectedProjectKey: projectPath, selectedSessionId: null,
      };
      return values[key] as never;
    },
    writePreference: async () => ({}) as never,
    chooseAttachment: async () => null,
    pasteAttachment: async () => null,
  };
  const state = createInitialState({
    language: "en",
    runtimeState: "ready",
    composerText: "Read sample.xlsx",
    projects: [{
      path: projectPath,
      projectKey: projectPath,
      alias: "First-turn project",
      pinned: false,
      sessions: [catalog[1]!],
      catalogFresh: true,
    }],
    selectedProjectKey: projectPath,
    expandedProjects: { [projectPath]: true },
  });
  await withRendererDom(async (dom, container, root) => {
    act(() => { root.render(<App initialState={state} api={api} />); });
    const flush = async () => {
      await act(async () => {
        for (let index = 0; index < 6; index += 1) await new Promise<void>((resolve) => setTimeout(resolve, 0));
      });
    };
    const sessionButton = (label: string) => [...container.querySelectorAll<HTMLButtonElement>("button.session-line")]
      .find((button) => button.textContent?.includes(label));
    await flush();
    const newChat = container.querySelector<HTMLButtonElement>('button[title="New chat"]');
    assert.ok(newChat);
    act(() => { newChat.click(); });
    await flush();
    assert.equal(container.querySelectorAll(".timeline-activity-item").length, 0);
    const send = container.querySelector<HTMLButtonElement>(".composer-send");
    assert.ok(send);
    act(() => { send.click(); });
    await flush();
    assert.ok(calls.some((call) => call.method === "turn.start"));
    assert.ok(eventListener);
    const publish = (event: Record<string, unknown>) => eventListener!(event as AgentEvent);
    act(() => {
      publish({ type: "turn_started", run_id: "run-a", turn_id: "turn-a", session_id: "session-a", project_key: projectPath, message_id: userMessageId, message: { role: "user", parts: [{ type: "text", text: "Read sample.xlsx" }] } });
      publish({ type: "reasoning_started", run_id: "run-a", turn_id: "turn-a", session_id: "session-a", project_key: projectPath, message_id: reasoningBeforeId });
      publish({ type: "reasoning_delta", run_id: "run-a", turn_id: "turn-a", session_id: "session-a", project_key: projectPath, message_id: reasoningBeforeId, text: "I will inspect the workbook." });
      publish({ type: "assistant_message_completed", run_id: "run-a", turn_id: "turn-a", session_id: "session-a", project_key: projectPath, message_id: reasoningBeforeId, kind: "progress", message: { role: "assistant", parts: [{ type: "reasoning", text: "I will inspect the workbook." }, { type: "tool_call", tool_call_id: "call-a", name: "ReadDocument", arguments: { path: "sample.xlsx" } }] } });
      publish({ type: "tool_started", run_id: "run-a", turn_id: "turn-a", session_id: "session-a", project_key: projectPath, batch_id: "batch-a", tool_call_id: "call-a", tool_name: "ReadDocument", command: "sample.xlsx" });
      publish({ type: "tool_finished", run_id: "run-a", turn_id: "turn-a", session_id: "session-a", project_key: projectPath, batch_id: "batch-a", tool_call_id: "call-a", tool_name: "ReadDocument", command: "sample.xlsx", status: "succeeded", is_error: false });
      publish({ type: "reasoning_started", run_id: "run-a", turn_id: "turn-a", session_id: "session-a", project_key: projectPath, message_id: reasoningAfterId });
      publish({ type: "reasoning_delta", run_id: "run-a", turn_id: "turn-a", session_id: "session-a", project_key: projectPath, message_id: reasoningAfterId, text: "The workbook is readable." });
      publish({ type: "assistant_message_completed", run_id: "run-a", turn_id: "turn-a", session_id: "session-a", project_key: projectPath, message_id: assistantMessageId, message: { role: "assistant", parts: [{ type: "text", text: "The workbook has one sheet." }] } });
      publish({ type: "turn_completed", run_id: "run-a", turn_id: "turn-a", session_id: "session-a", project_key: projectPath, final_text: "The workbook has one sheet." });
    });
    await flush();
    assert.ok(resolveFirstSessionHistory, "the completed Session requests its durable first page after terminal idle");
    const liveActivity = container.querySelector<HTMLElement>("details.timeline-activity-group");
    assert.ok(liveActivity, "the live first-turn tool call is shown in an activity group");
    const liveActivitySummary = liveActivity.querySelector("summary");
    assert.ok(liveActivitySummary);
    assert.equal(liveActivity.open, false, "tool activity starts collapsed");
    act(() => { liveActivitySummary.click(); });
    assert.equal(liveActivity.open, true, "the user can expand the activity group");
    assert.equal(liveActivity.querySelectorAll(".timeline-activity-item").length, 1);
    assert.match(liveActivity.textContent ?? "", /ReadDocument/u);
    assert.equal(liveActivity.querySelector(".timeline-tool-output"), null, "the externalized result is not fabricated from the preview-free live event");

    const otherSession = sessionButton("Other session");
    assert.ok(otherSession);
    act(() => { otherSession.click(); });
    await flush();
    const newerDraft = "keep this newer Session draft";
    const textarea = container.querySelector<HTMLTextAreaElement>(".composer textarea");
    const textareaSetter = Object.getOwnPropertyDescriptor(dom.window.HTMLTextAreaElement.prototype, "value")?.set;
    assert.ok(textarea && textareaSetter);
    act(() => {
      textarea!.focus();
      textareaSetter!.call(textarea, newerDraft);
      textarea!.dispatchEvent(new dom.window.InputEvent("input", { bubbles: true, inputType: "insertText", data: newerDraft }));
      textarea!.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
      textarea!.dispatchEvent(new dom.window.KeyboardEvent("keyup", { bubbles: true, key: "Unidentified" }));
    });
    await flush();
    assert.equal(container.querySelector<HTMLTextAreaElement>(".composer textarea")?.value, newerDraft, "the newer Session draft is established before resolving the old page");
    act(() => { resolveFirstSessionHistory!({ session_id: "session-a", records: durableRecords, next_cursor: null, has_more: false }); });
    await flush();
    assert.equal(container.querySelector(".session-line.is-selected")?.textContent?.includes("Other session"), true, "a late first Session page stays under its original owner");
    assert.equal(container.querySelector<HTMLTextAreaElement>(".composer textarea")?.value, newerDraft, "late history does not replace the newer Session draft");

    const firstSession = sessionButton("First session");
    assert.ok(firstSession);
    act(() => { firstSession.click(); });
    await flush();

    const rows = [...container.querySelectorAll<HTMLElement>(".timeline-entry")];
    const kinds = rows.map((row) => [...row.classList].find((name) => name.startsWith("timeline-entry--"))?.slice("timeline-entry--".length));
    assert.deepEqual(kinds, ["user", "assistant"], "history keeps reasoning inside the Turn activity group");
    const recoveredActivity = container.querySelector<HTMLElement>("details.timeline-activity-group");
    assert.ok(recoveredActivity);
    assert.equal(container.querySelectorAll("details.timeline-activity-group").length, 1);
    assert.equal(recoveredActivity.dataset.turnId, "turn-a");
    assert.equal(recoveredActivity.dataset.reasoningCount, "2");
    assert.equal(recoveredActivity.querySelectorAll(".timeline-activity-reasoning").length, 2);
    assert.equal(recoveredActivity.querySelectorAll(".timeline-activity-item").length, 1);
    assert.match(recoveredActivity.textContent ?? "", /ReadDocument/u);
    assert.ok(recoveredActivity.querySelector(".timeline-tool-output"), "replay metadata adds the durable externalized result action to the live tool row");
    assert.equal(firstSessionHistoryRequests, 2, "the original late page is cached, then its first page is refreshed on Session return");
    assert.ok(calls.filter((call) => call.method === "session.resume" && call.params.session_id === "session-a").every(() => true));
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
      assert.equal(container.querySelectorAll(".composer-attachments .file-card[data-file-ref='att-1']").length, 1, container.textContent ?? "");
      assert.match(container.textContent ?? "", new RegExp(expectedNotice.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "u"));

      act(() => { send!.click(); });
      await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });
      assert.equal(turnStarts, 2);
      assert.equal(container.querySelectorAll(".composer-attachments .file-card[data-file-ref='att-1']").length, 0);
      assert.equal(container.querySelectorAll(".timeline-entry--user .file-card[data-file-ref='att-1']").length, 1);
    });
  };

  await runCase("en", resources.en.turnImageInputUnsupported);
  await runCase("zh-CN", resources["zh-CN"].turnImageInputUnsupported);
});

interface ModelImageSwitchFixture {
  calls: Array<{ method: string; params: Record<string, JsonValue> }>;
  activeSessionId: string;
  modelBySession: Record<string, string>;
  override: ((method: string, params: Record<string, JsonValue>, fixture: ModelImageSwitchFixture) => JsonValue | undefined | Promise<JsonValue | undefined>) | null;
  api: DesktopApi;
  state: ReturnType<typeof createInitialState>;
}

function createModelImageSwitchFixture(): ModelImageSwitchFixture {
  const projectPath = "C:/model-image-switch";
  const sessions = [
    { session_id: "session-a", title: "Image history" },
    { session_id: "session-b", title: "Other session" },
  ];
  const project: ProjectState = {
    path: projectPath,
    projectKey: projectPath,
    alias: "Model switch",
    pinned: false,
    sessions,
    catalogFresh: true,
  };
  const configuration = {
    default_model: "vision/ref",
    default_permission_mode: "default" as const,
    providers: { provider: { kind: "openai_compat", api_key_configured: true } },
    models: {
      "vision/ref": { provider_profile_id: "provider", remote_id: "vision", display_name: "Vision Model", supports_images: true },
      "text/ref": { provider_profile_id: "provider", remote_id: "text", display_name: "Text Model", supports_images: false },
      "other/ref": { provider_profile_id: "provider", remote_id: "other", display_name: "Other Session Model", supports_images: true },
    },
  };
  const fixture = {
    calls: [] as Array<{ method: string; params: Record<string, JsonValue> }>,
    activeSessionId: "session-a",
    modelBySession: { "session-a": "vision/ref", "session-b": "other/ref" },
    override: null,
  } as ModelImageSwitchFixture;
  const preferences = {
    theme: "light",
    language: "en",
    panelMode: "docked",
    sidebarWidth: 286,
    runtimePanelWidth: 318,
    recentProjects: [{ path: projectPath, alias: project.alias, pinned: false }],
    projectAliases: {},
    pinnedProjectKeys: [],
    pinnedSessions: [],
    expandedProjects: { [projectPath]: true },
    selectedProjectKey: projectPath,
    selectedSessionId: "session-a",
  };
  fixture.api = {
    openProject: async () => null,
    openProjectInExplorer: async () => undefined,
    copyText: async () => undefined,
    closeShell: async () => undefined,
    requestRuntime: async (method, params) => {
      fixture.calls.push({ method, params });
      const overridden = await fixture.override?.(method, params, fixture);
      if (overridden !== undefined) return overridden;
      if (method === "runtime.initialize") return { state: "ready", run: { run_id: "run-model-switch", status: "idle" } };
      if (method === "settings.get") return { configuration };
      if (method === "status.get") {
        return {
          active_turn: false,
          run: { run_id: `run-${fixture.activeSessionId}`, status: "idle" },
          application: { current_model: fixture.modelBySession[fixture.activeSessionId] ?? "vision/ref" },
        };
      }
      if (method === "project.sessions") return { sessions };
      if (method === "session.resume") {
        fixture.activeSessionId = String(params.session_id ?? "");
        return {
          session_id: fixture.activeSessionId,
          replay: [],
          run: { run_id: `run-${fixture.activeSessionId}`, status: "idle" },
          model_ref: fixture.modelBySession[fixture.activeSessionId] ?? null,
        };
      }
      if (method === "command.complete") return { candidates: [], argument_candidates: ["text/ref"] };
      return {};
    },
    subscribeAgentEvents: () => () => undefined,
    readPreference: async (key) => preferences[key] as never,
    writePreference: async () => preferences as never,
    chooseAttachment: async () => null,
    pasteAttachment: async () => null,
  };
  fixture.state = createInitialState({
    language: "en",
    runtimeState: "ready",
    composerText: "/model text/ref",
    projects: [project],
    selectedProjectKey: projectPath,
    selectedSessionId: "session-a",
    expandedProjects: { [projectPath]: true },
    currentModelRef: "vision/ref",
    configuration,
  });
  return fixture;
}

test("App switches an image Session with placeholders and keeps the selected button busy until authoritative completion", async () => {
  const fixture = createModelImageSwitchFixture();
  let operationId = "";
  let pollCount = 0;
  fixture.override = (method, params, owner) => {
    if (method !== "command.execute") return undefined;
    const text = String(params.text ?? "");
    if (text === "/model text/ref" && params.image_handling === undefined) {
      return { command: "model", status: "execution_error", code: "image_input_unsupported", params: {}, ui_action: null };
    }
    if (text === "/model text/ref" && params.image_handling === "placeholder") {
      operationId = String(params.operation_id ?? "");
      assert.equal(params.expected_session_id, "session-a");
      return { command: "model", status: "success", code: "model_switch_started", params: { operation_id: operationId, session_id: "session-a", model_ref: "text/ref" }, ui_action: null };
    }
    if (method === "model.switch.status") return undefined;
    return undefined;
  };
  const originalOverride = fixture.override;
  fixture.override = async (method, params, owner) => {
    const command = await originalOverride?.(method, params, owner);
    if (command !== undefined) return command;
    if (method === "model.switch.status") {
      assert.equal(params.session_id, "session-a");
      assert.equal(params.operation_id, operationId);
      pollCount += 1;
      if (pollCount === 1) return { operation_id: operationId, session_id: "session-a", state: "running" };
      owner.modelBySession["session-a"] = "text/ref";
      return {
        operation_id: operationId,
        session_id: "session-a",
        state: "completed",
        result: { command: "model", status: "success", code: "model_selected", params: { model_ref: "text/ref" }, ui_action: { type: "model_selected", model_ref: "text/ref" } },
      };
    }
    return undefined;
  };
  await withRendererDom(async (_dom, container, root) => {
    act(() => { root.render(<App initialState={fixture.state} api={fixture.api} />); });
    const flush = async (delay = 0) => {
      await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, delay)); });
    };
    await flush();
    const submit = container.querySelector<HTMLButtonElement>(".composer-send");
    assert.ok(submit);
    act(() => { submit.click(); });
    await flush();
    assert.ok(container.querySelector("#model-image-switch-dialog"), "unsupported image history opens the explicit choice dialog");
    const placeholder = container.querySelector<HTMLButtonElement>("#model-image-switch-placeholder");
    const summarize = container.querySelector<HTMLButtonElement>("#model-image-switch-summarize");
    assert.ok(placeholder && summarize);
    act(() => { placeholder.click(); });
    await flush();
    const dialog = container.querySelector<HTMLElement>("#model-image-switch-dialog");
    assert.equal(dialog?.getAttribute("aria-busy"), "true");
    assert.equal(placeholder.disabled, true);
    assert.equal(summarize.disabled, true);
    assert.equal(placeholder.querySelector(".model-image-switch-spinner") !== null, true, "the selected action alone displays the spinner");
    assert.equal(summarize.querySelector(".model-image-switch-spinner"), null);
    assert.ok(fixture.calls.some((call) => call.method === "command.execute" && call.params.image_handling === "placeholder" && call.params.expected_session_id === "session-a"));
    await flush(135);
    assert.equal(container.querySelector("#model-image-switch-dialog")?.getAttribute("aria-busy"), "true", "the operation remains busy while status is running");
    await flush(135);
    assert.equal(container.querySelector("#model-image-switch-dialog"), null, "completion closes the dialog only after the Bridge reports the selected model");
    assert.equal(container.querySelector(".composer-model .custom-select__trigger")?.getAttribute("aria-label"), "Model: Text Model");
    assert.equal(fixture.modelBySession["session-a"], "text/ref");
    assert.ok(fixture.calls.some((call) => call.method === "model.switch.status" && call.params.operation_id === operationId));
  });
});

test("App closes an unstarted image model choice when Cancel is clicked", async () => {
  const fixture = createModelImageSwitchFixture();
  fixture.override = (method, params) => {
    if (method === "command.execute" && params.image_handling === undefined) {
      return { command: "model", status: "execution_error", code: "image_input_unsupported", params: {}, ui_action: null };
    }
    return undefined;
  };

  await withRendererDom(async (_dom, container, root) => {
    act(() => { root.render(<App initialState={fixture.state} api={fixture.api} />); });
    const flush = async () => { await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); }); };
    await flush();
    const submit = container.querySelector<HTMLButtonElement>(".composer-send");
    assert.ok(submit);
    act(() => { submit.click(); });
    await flush();
    assert.ok(container.querySelector("#model-image-switch-dialog"), "unsupported image history opens the choice dialog");
    assert.equal(container.querySelector<HTMLElement>("#model-image-switch-dialog")?.getAttribute("aria-busy"), "false");

    const cancel = container.querySelector<HTMLButtonElement>("#model-image-switch-cancel");
    assert.ok(cancel);
    act(() => { cancel.click(); });
    await flush();
    assert.equal(container.querySelector("#model-image-switch-dialog"), null, "Cancel closes a choice with no running Bridge operation");
    assert.equal(fixture.calls.some((call) => call.method === "model.switch.cancel"), false, "there is no operation to cancel");
  });
});

test("App applies an immediately selected configured model without a competing open-picker command", async () => {
  const fixture = createModelImageSwitchFixture();
  let markPickerRequestStarted: (() => void) | null = null;
  const pickerRequestStarted = new Promise<void>((resolve) => { markPickerRequestStarted = resolve; });
  let releasePickerRequest: ((result: JsonValue) => void) | null = null;
  let pickerRequestSeen = false;
  let selectedModelRequests = 0;
  fixture.override = (method, params, owner) => {
    if (method !== "command.execute") return undefined;
    const text = String(params.text ?? "");
    if (text === "/model") {
      pickerRequestSeen = true;
      markPickerRequestStarted?.();
      return new Promise<JsonValue>((resolve) => { releasePickerRequest = resolve; });
    }
    if (text === "/model text/ref") {
      selectedModelRequests += 1;
      owner.modelBySession["session-a"] = "text/ref";
      return {
        command: "model",
        status: "success",
        code: "model_selected",
        params: { model_ref: "text/ref" },
        ui_action: { type: "model_selected", model_ref: "text/ref" },
      };
    }
    return undefined;
  };

  await withRendererDom(async (_dom, container, root) => {
    act(() => { root.render(<App initialState={fixture.state} api={fixture.api} />); });
    const flush = async () => { await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); }); };
    await flush();
    const trigger = container.querySelector<HTMLButtonElement>(".composer-model .custom-select__trigger");
    assert.ok(trigger);
    act(() => { trigger.click(); });
    await flush();
    const target = [..._dom.window.document.querySelectorAll<HTMLButtonElement>(".composer-model [role=option], .custom-select__list [role=option]")]
      .find((option) => option.textContent?.includes("Text Model"));
    assert.ok(target, "the configured model is available before opening requires a backend command");

    // Yield only until the old onOpen command has had a chance to reach the
    // bridge; selection then occurs immediately while that request is pending.
    await Promise.race([pickerRequestStarted, new Promise<void>((resolve) => setTimeout(resolve, 0))]);
    act(() => { target.click(); });
    await flush();
    const modelCommandTexts = fixture.calls
      .filter((call) => call.method === "command.execute")
      .map((call) => String(call.params.text ?? ""));

    if (releasePickerRequest) {
      releasePickerRequest({ command: "model", status: "success", code: "model_picker_opened", params: {}, ui_action: { type: "open_model_picker" } });
      await flush();
    }
    assert.equal(pickerRequestSeen, false, "opening the selector does not enqueue a redundant /model command");
    assert.equal(selectedModelRequests, 1, "the immediate option click reaches the selected model command");
    assert.deepEqual(modelCommandTexts, ["/model text/ref"]);
    assert.equal(container.querySelector(".composer-model .custom-select__trigger")?.getAttribute("aria-label"), "Model: Text Model");
    assert.equal(fixture.modelBySession["session-a"], "text/ref");
  });
});

test("App keeps the Yes confirmation busy through failure, then allows a successful retry", async () => {
  const fixture = createModelImageSwitchFixture();
  const operations: string[] = [];
  let pollCount = 0;
  fixture.override = (method, params) => {
    if (method === "command.execute") {
      const text = String(params.text ?? "");
      if (text === "/model text/ref" && params.image_handling === undefined) {
        return { command: "model", status: "execution_error", code: "image_input_unsupported", params: {}, ui_action: null };
      }
      if (text === "/model text/ref" && params.image_handling === "summarize") {
        const operationId = String(params.operation_id ?? "");
        operations.push(operationId);
        return { command: "model", status: "success", code: "model_switch_started", params: { operation_id: operationId, session_id: "session-a", model_ref: "text/ref" }, ui_action: null };
      }
    }
    if (method === "model.switch.status") {
      const operationId = String(params.operation_id ?? "");
      pollCount += 1;
      if (pollCount === 1) return { operation_id: operationId, session_id: "session-a", state: "running" };
      if (pollCount === 2) return { operation_id: operationId, session_id: "session-a", state: "failed" };
      fixture.modelBySession["session-a"] = "text/ref";
      return {
        operation_id: operationId,
        session_id: "session-a",
        state: "completed",
        result: { command: "model", status: "success", code: "model_selected", params: { model_ref: "text/ref" }, ui_action: { type: "model_selected", model_ref: "text/ref" } },
      };
    }
    return undefined;
  };
  await withRendererDom(async (_dom, container, root) => {
    act(() => { root.render(<App initialState={fixture.state} api={fixture.api} />); });
    const flush = async (delay = 0) => { await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, delay)); }); };
    await flush();
    const submit = container.querySelector<HTMLButtonElement>(".composer-send");
    assert.ok(submit);
    act(() => { submit.click(); });
    await flush();
    const summarize = container.querySelector<HTMLButtonElement>("#model-image-switch-summarize");
    const placeholder = container.querySelector<HTMLButtonElement>("#model-image-switch-placeholder");
    assert.ok(summarize && placeholder);
    act(() => { summarize.click(); });
    await flush();
    assert.equal(container.querySelector<HTMLElement>("#model-image-switch-dialog")?.getAttribute("aria-busy"), "true");
    assert.equal(summarize.disabled, true);
    assert.equal(placeholder.disabled, true);
    assert.ok(summarize.querySelector(".model-image-switch-spinner"));
    assert.equal(placeholder.querySelector(".model-image-switch-spinner"), null);
    await flush(135);
    assert.equal(container.querySelector<HTMLElement>("#model-image-switch-dialog")?.getAttribute("aria-busy"), "true");
    await flush(135);
    assert.equal(container.querySelector<HTMLElement>("#model-image-switch-dialog")?.getAttribute("aria-busy"), "false");
    assert.match(container.querySelector("#model-image-switch-dialog")?.textContent ?? "", /current model is still selected|current model is still/u);
    assert.equal(fixture.modelBySession["session-a"], "vision/ref", "failure keeps the original model authoritative");
    assert.equal(container.querySelector(".composer-model .custom-select__trigger")?.getAttribute("aria-label"), "Model: Vision Model");
    act(() => { summarize.click(); });
    await flush();
    assert.equal(operations.length, 2, "the failed choice can be retried with a fresh operation identity");
    assert.notEqual(operations[0], operations[1]);
    assert.equal(container.querySelector<HTMLElement>("#model-image-switch-dialog")?.getAttribute("aria-busy"), "true");
    await flush(135);
    assert.equal(container.querySelector("#model-image-switch-dialog"), null);
    assert.equal(container.querySelector(".composer-model .custom-select__trigger")?.getAttribute("aria-label"), "Model: Text Model");
  });
});

test("App cancels an image model operation on Session navigation and ignores its late completion", async () => {
  const fixture = createModelImageSwitchFixture();
  let operationId = "";
  let resolveLateStatus: ((result: JsonValue) => void) | null = null;
  let statusRequested: (() => void) | null = null;
  const statusStarted = new Promise<void>((resolve) => { statusRequested = resolve; });
  fixture.override = (method, params) => {
    if (method === "command.execute") {
      const text = String(params.text ?? "");
      if (text === "/model text/ref" && params.image_handling === undefined) {
        return { command: "model", status: "execution_error", code: "image_input_unsupported", params: {}, ui_action: null };
      }
      if (text === "/model text/ref" && params.image_handling === "summarize") {
        operationId = String(params.operation_id ?? "");
        return { command: "model", status: "success", code: "model_switch_started", params: { operation_id: operationId, session_id: "session-a", model_ref: "text/ref" }, ui_action: null };
      }
    }
    if (method === "model.switch.status") {
      statusRequested?.();
      return new Promise<JsonValue>((resolve) => { resolveLateStatus = resolve; });
    }
    if (method === "model.switch.cancel") return { accepted: true, operation_id: params.operation_id ?? "", session_id: params.session_id ?? "" };
    return undefined;
  };
  await withRendererDom(async (_dom, container, root) => {
    act(() => { root.render(<App initialState={fixture.state} api={fixture.api} />); });
    const flush = async (delay = 0) => { await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, delay)); }); };
    await flush();
    const submit = container.querySelector<HTMLButtonElement>(".composer-send");
    assert.ok(submit);
    act(() => { submit.click(); });
    await flush();
    const summarize = container.querySelector<HTMLButtonElement>("#model-image-switch-summarize");
    assert.ok(summarize);
    act(() => { summarize.click(); });
    await flush();
    await flush(135);
    await statusStarted;
    assert.equal(container.querySelector<HTMLElement>("#model-image-switch-dialog")?.getAttribute("aria-busy"), "true");
    const otherSession = [...container.querySelectorAll<HTMLButtonElement>("button.session-line")].find((button) => button.textContent?.includes("Other session"));
    assert.ok(otherSession);
    act(() => { otherSession.click(); });
    await flush();
    assert.equal(container.querySelector("#model-image-switch-dialog"), null, "navigation closes the old Session's choice");
    assert.equal(container.querySelector(".session-line.is-selected")?.textContent?.includes("Other session"), true);
    assert.ok(fixture.calls.some((call) => call.method === "model.switch.cancel" && call.params.session_id === "session-a" && call.params.operation_id === operationId));
    assert.equal(fixture.activeSessionId, "session-b");
    const textarea = container.querySelector<HTMLTextAreaElement>(".composer textarea");
    const textareaSetter = Object.getOwnPropertyDescriptor(_dom.window.HTMLTextAreaElement.prototype, "value")?.set;
    assert.ok(textarea && textareaSetter);
    act(() => {
      textarea!.focus();
      textareaSetter!.call(textarea, "/model text/ref");
      textarea!.dispatchEvent(new _dom.window.InputEvent("input", { bubbles: true, inputType: "insertText", data: "/model text/ref" }));
      textarea!.dispatchEvent(new _dom.window.Event("change", { bubbles: true }));
      textarea!.dispatchEvent(new _dom.window.KeyboardEvent("keyup", { bubbles: true, key: "Unidentified" }));
    });
    const submitAgain = container.querySelector<HTMLButtonElement>(".composer-send");
    assert.ok(submitAgain);
    act(() => { submitAgain.click(); });
    await flush();
    assert.ok(container.querySelector("#model-image-switch-dialog"), "Session B now owns a separate pending model choice");
    assert.equal(container.querySelector(".composer-model .custom-select__trigger")?.getAttribute("aria-label"), "Model: Other Session Model");
    const statusCallsBeforeLateResult = fixture.calls.filter((call) => call.method === "status.get").length;
    fixture.modelBySession["session-a"] = "text/ref";
    assert.ok(resolveLateStatus);
    await act(async () => {
      resolveLateStatus!({
        operation_id: operationId,
        session_id: "session-a",
        state: "completed",
        result: { command: "model", status: "success", code: "model_selected", params: { model_ref: "text/ref" }, ui_action: { type: "model_selected", model_ref: "text/ref" } },
      });
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
    });
    assert.equal(container.querySelector(".session-line.is-selected")?.textContent?.includes("Other session"), true);
    assert.equal(container.querySelector(".composer-model .custom-select__trigger")?.getAttribute("aria-label"), "Model: Other Session Model", "the late completion cannot project Session A's model into Session B");
    assert.ok(container.querySelector("#model-image-switch-dialog"), "the late Session A completion cannot clear Session B's pending choice");
    assert.equal(fixture.calls.filter((call) => call.method === "status.get").length, statusCallsBeforeLateResult, "the stale completion cannot refresh or dispatch its model into the new owner");
  });
});

test("App cancels the captured model operation after a status timeout and waits for cancellation", async () => {
  const fixture = createModelImageSwitchFixture();
  let operationId = "";
  let statusCalls = 0;
  fixture.override = async (method, params) => {
    if (method === "command.execute") {
      const text = String(params.text ?? "");
      if (text === "/model text/ref" && params.image_handling === undefined) {
        return { command: "model", status: "execution_error", code: "image_input_unsupported", params: {}, ui_action: null };
      }
      if (text === "/model text/ref" && params.image_handling === "summarize") {
        operationId = String(params.operation_id ?? "");
        return { command: "model", status: "success", code: "model_switch_started", params: { operation_id: operationId, session_id: "session-a", model_ref: "text/ref" }, ui_action: null };
      }
    }
    if (method === "model.switch.status") {
      statusCalls += 1;
      if (statusCalls === 1) throw new Error("renderer request timed out");
      return { operation_id: operationId, session_id: "session-a", state: "cancelled" };
    }
    if (method === "model.switch.cancel") {
      assert.equal(params.session_id, "session-a");
      assert.equal(params.operation_id, operationId);
      return { accepted: true, operation_id: operationId, session_id: "session-a" };
    }
    return undefined;
  };

  await withRendererDom(async (_dom, container, root) => {
    act(() => { root.render(<App initialState={fixture.state} api={fixture.api} />); });
    const flush = async (delay = 0) => { await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, delay)); }); };
    await flush();
    const submit = container.querySelector<HTMLButtonElement>(".composer-send");
    assert.ok(submit);
    act(() => { submit.click(); });
    await flush();
    const summarize = container.querySelector<HTMLButtonElement>("#model-image-switch-summarize");
    assert.ok(summarize);
    act(() => { summarize.click(); });
    await flush(500);
    assert.ok(fixture.calls.some((call) => call.method === "model.switch.cancel" && call.params.session_id === "session-a" && call.params.operation_id === operationId));
    assert.equal(container.querySelector("#model-image-switch-dialog"), null, "the dialog closes after Bridge confirms cancellation");
    assert.equal(fixture.modelBySession["session-a"], "vision/ref", "the model remains unchanged after confirmed cancellation");
    assert.equal(container.querySelector(".composer-model .custom-select__trigger")?.getAttribute("aria-label"), "Model: Vision Model");
  });
});

test("App reconciles a timed-out status whose Bridge operation already completed", async () => {
  const fixture = createModelImageSwitchFixture();
  let operationId = "";
  let statusCalls = 0;
  fixture.override = async (method, params, owner) => {
    if (method === "command.execute") {
      const text = String(params.text ?? "");
      if (text === "/model text/ref" && params.image_handling === undefined) {
        return { command: "model", status: "execution_error", code: "image_input_unsupported", params: {}, ui_action: null };
      }
      if (text === "/model text/ref" && params.image_handling === "summarize") {
        operationId = String(params.operation_id ?? "");
        return { command: "model", status: "success", code: "model_switch_started", params: { operation_id: operationId, session_id: "session-a", model_ref: "text/ref" }, ui_action: null };
      }
    }
    if (method === "model.switch.status") {
      statusCalls += 1;
      if (statusCalls === 1) {
        owner.modelBySession["session-a"] = "text/ref";
        throw new Error("terminal status response timed out after Bridge completion");
      }
      return { __uthcode_runtime_error: { kind: "stale_operation", message: "operation is no longer available" } };
    }
    if (method === "model.switch.cancel") {
      assert.equal(params.session_id, "session-a");
      assert.equal(params.operation_id, operationId);
      return { __uthcode_runtime_error: { kind: "stale_operation", message: "operation is no longer active" } };
    }
    return undefined;
  };

  await withRendererDom(async (_dom, container, root) => {
    act(() => { root.render(<App initialState={fixture.state} api={fixture.api} />); });
    const flush = async (delay = 0) => { await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, delay)); }); };
    await flush();
    const submit = container.querySelector<HTMLButtonElement>(".composer-send");
    assert.ok(submit);
    act(() => { submit.click(); });
    await flush();
    const summarize = container.querySelector<HTMLButtonElement>("#model-image-switch-summarize");
    assert.ok(summarize);
    act(() => { summarize.click(); });
    await flush(500);
    assert.ok(fixture.calls.some((call) => call.method === "model.switch.cancel" && call.params.session_id === "session-a" && call.params.operation_id === operationId));
    assert.ok(fixture.calls.some((call) => call.method === "status.get"), "a consumed terminal operation falls back to authoritative Runtime status");
    assert.equal(container.querySelector("#model-image-switch-dialog"), null);
    assert.equal(container.querySelector(".composer-model .custom-select__trigger")?.getAttribute("aria-label"), "Model: Text Model", "the UI follows the model actually committed by the Bridge");
    assert.equal(fixture.modelBySession["session-a"], "text/ref");
  });
});

test("App keeps an explicit cancel owner until Bridge resolves a completion race", async () => {
  const fixture = createModelImageSwitchFixture();
  let operationId = "";
  let statusCalls = 0;
  let resolveLateStatus: ((result: JsonValue) => void) | null = null;
  let markSecondStatusRequested: (() => void) | null = null;
  const secondStatusRequested = new Promise<void>((resolve) => { markSecondStatusRequested = resolve; });
  fixture.override = (method, params) => {
    if (method === "command.execute") {
      const text = String(params.text ?? "");
      if (text === "/model text/ref" && params.image_handling === undefined) {
        return { command: "model", status: "execution_error", code: "image_input_unsupported", params: {}, ui_action: null };
      }
      if (text === "/model text/ref" && params.image_handling === "summarize") {
        operationId = String(params.operation_id ?? "");
        return { command: "model", status: "success", code: "model_switch_started", params: { operation_id: operationId, session_id: "session-a", model_ref: "text/ref" }, ui_action: null };
      }
    }
    if (method === "model.switch.status") {
      statusCalls += 1;
      if (statusCalls === 1) return { operation_id: operationId, session_id: "session-a", state: "running" };
      markSecondStatusRequested?.();
      return new Promise<JsonValue>((resolve) => { resolveLateStatus = resolve; });
    }
    if (method === "model.switch.cancel") {
      assert.equal(params.session_id, "session-a");
      assert.equal(params.operation_id, operationId);
      return { __uthcode_runtime_error: { kind: "stale_operation", message: "operation already completed" } };
    }
    return undefined;
  };

  await withRendererDom(async (_dom, container, root) => {
    act(() => { root.render(<App initialState={fixture.state} api={fixture.api} />); });
    const flush = async (delay = 0) => { await act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, delay)); }); };
    await flush();
    const submit = container.querySelector<HTMLButtonElement>(".composer-send");
    assert.ok(submit);
    act(() => { submit.click(); });
    await flush();
    const summarize = container.querySelector<HTMLButtonElement>("#model-image-switch-summarize");
    assert.ok(summarize);
    act(() => { summarize.click(); });
    await flush(280);
    await secondStatusRequested;
    const cancel = container.querySelector<HTMLButtonElement>("#model-image-switch-cancel");
    assert.ok(cancel);
    act(() => { cancel.click(); });
    await flush();
    assert.equal(container.querySelector<HTMLElement>("#model-image-switch-dialog")?.getAttribute("aria-busy"), "true", "a stale cancel response keeps the operation owner until its status is known");
    fixture.modelBySession["session-a"] = "text/ref";
    assert.ok(resolveLateStatus);
    await act(async () => {
      resolveLateStatus!({
        operation_id: operationId,
        session_id: "session-a",
        state: "completed",
        result: { command: "model", status: "success", code: "model_selected", params: { model_ref: "text/ref" }, ui_action: { type: "model_selected", model_ref: "text/ref" } },
      });
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
    });
    assert.equal(container.querySelector("#model-image-switch-dialog"), null);
    assert.equal(container.querySelector(".composer-model .custom-select__trigger")?.getAttribute("aria-label"), "Model: Text Model", "the selector follows the operation that actually committed before cancellation");
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
    assert.equal(container.querySelectorAll(".composer-attachments").length, 0);
  });
});
