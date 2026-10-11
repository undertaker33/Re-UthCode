import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import Prism, { Token, type TokenStream } from "prismjs";
import "prismjs/components/prism-batch";
import "prismjs/components/prism-bash";
import "prismjs/components/prism-c";
import "prismjs/components/prism-cpp";
import "prismjs/components/prism-csharp";
import "prismjs/components/prism-css";
import "prismjs/components/prism-go";
import "prismjs/components/prism-java";
import "prismjs/components/prism-javascript";
import "prismjs/components/prism-jsx";
import "prismjs/components/prism-json";
import "prismjs/components/prism-markdown";
import "prismjs/components/prism-markup";
import "prismjs/components/prism-powershell";
import "prismjs/components/prism-python";
import "prismjs/components/prism-ruby";
import "prismjs/components/prism-rust";
import "prismjs/components/prism-typescript";
import "prismjs/components/prism-tsx";
import "prismjs/components/prism-xml-doc";
import "prismjs/components/prism-yaml";
import type { FileCardAsset } from "./FileCard";
import { ImagePreviewModal, fileActionMessage, fileDisplayName, fileExtension, fileKind } from "./FileCard";
import { renderMarkdown } from "./safe-markdown";
import { useTranslation } from "./i18n";
import type { ProcessLogEntry, ProcessReaderState } from "./state";

export interface DocumentPreview {
  asset: FileCardAsset;
  text: string;
  imageSrc?: string;
  onOpen?: () => void | Promise<void>;
  owner?: DocumentPreviewOwner;
}

export interface DocumentPreviewOwner {
  generation: number;
  mode: "coding" | "general";
  projectKey: string | null;
  sessionId: string | null;
  viewRevision: number;
}

export interface WorkspaceDiffView {
  source: "current_working_tree";
  project_key: string;
  viewed_at: string;
  status: { branch: string | null; entries: Array<{ xy: string; path: string; original_path?: string }>; unborn: boolean; truncated: boolean };
  staged_diff: { text: string; truncated: boolean; size_bytes: number };
  unstaged_diff: { text: string; truncated: boolean; size_bytes: number };
  truncated: boolean;
}

interface ReviewTabOwner extends DocumentPreviewOwner { ownerKey: string; }

export type ReviewPanelTab =
  | { kind: "document"; id: string; title: string; owner: ReviewTabOwner; preview: DocumentPreview }
  | { kind: "workspace-diff"; id: string; title: string; owner: ReviewTabOwner; path?: string; state: "reviewing" | "completed" | "failed" | "cancelled" | "stale"; error?: string; diff?: WorkspaceDiffView }
  | { kind: "tool-output"; id: string; title: string; owner: ReviewTabOwner; ref?: string; text: string; loading: boolean; error?: string; truncated: boolean; offset: number; nextOffset: number | null; totalBytes: number | null; sha256: string | null; eof: boolean }
  | { kind: "process-log"; id: string; title: string; owner: ReviewTabOwner; processId: string; entries: ProcessLogEntry[]; reader: ProcessReaderState };

const LANGUAGE_ALIASES: Record<string, string> = {
  bat: "batch",
  cc: "cpp",
  h: "c",
  hpp: "cpp",
  html: "markup",
  js: "javascript",
  jsx: "jsx",
  md: "markdown",
  markdown: "markdown",
  ps1: "powershell",
  py: "python",
  pyw: "python",
  rb: "ruby",
  rs: "rust",
  sh: "bash",
  ts: "typescript",
  tsx: "tsx",
  xml: "markup",
  yml: "yaml",
};

function prismLanguage(asset: FileCardAsset): string {
  const extension = fileExtension(asset);
  const language = LANGUAGE_ALIASES[extension] ?? extension;
  return Prism.languages[language] ? language : "plain";
}

function renderTokens(value: string | Token | Array<string | Token>, keyPrefix: string): ReactNode {
  if (typeof value === "string") return value;
  if (value instanceof Token) {
    const alias = Array.isArray(value.alias) ? value.alias : value.alias ? [value.alias] : [];
    return <span className={["token", value.type, ...alias].join(" ")} key={keyPrefix}>{renderTokens(value.content, keyPrefix + ":content")}</span>;
  }
  return value.map((item, index) => <span key={`${keyPrefix}:${index}`}>{renderTokens(item, `${keyPrefix}:${index}`)}</span>);
}

function splitTokenStream(stream: TokenStream): Array<Array<string | Token>> {
  const lines: Array<Array<string | Token>> = [[]];
  const append = (value: TokenStream): void => {
    if (typeof value === "string") {
      const parts = value.split("\n");
      lines[lines.length - 1]!.push(parts[0] ?? "");
      for (const part of parts.slice(1)) {
        lines.push([]);
        lines[lines.length - 1]!.push(part);
      }
      return;
    }
    if (value instanceof Token) {
      const nested = splitTokenStream(value.content);
      if (nested.length === 1) {
        lines[lines.length - 1]!.push(value);
        return;
      }
      lines[lines.length - 1]!.push(new Token(value.type, nested[0] ?? [], value.alias));
      for (const content of nested.slice(1)) {
        lines.push([new Token(value.type, content, value.alias)]);
      }
      return;
    }
    for (const item of value) append(item);
  };
  append(stream);
  return lines;
}

export interface DocumentPreviewPanelProps {
  preview: DocumentPreview;
  width: number;
  minWidth: number;
  maxWidth: number;
  onWidthChange: (width: number) => void;
  onClose: () => void;
  embedded?: boolean;
}

/** Read-only right-side source canvas shared by Markdown and code artifacts. */
export function DocumentPreviewPanel({ preview, width, minWidth, maxWidth, onWidthChange, onClose, embedded = false }: DocumentPreviewPanelProps) {
  const { t } = useTranslation();
  const [markdownMode, setMarkdownMode] = useState<"render" | "source">("render");
  const [imageModalOpen, setImageModalOpen] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const startRef = useRef<{ x: number; width: number } | null>(null);
  const resizeLimitsRef = useRef({ minWidth, maxWidth, onWidthChange });
  resizeLimitsRef.current = { minWidth, maxWidth, onWidthChange };
  const language = prismLanguage(preview.asset);
  const isMarkdown = fileKind(preview.asset) === "markdown" || language === "markdown";
  const normalizedText = preview.text.replace(/\r\n?/gu, "\n");
  const lines = normalizedText.split("\n");
  const openTruncated = () => {
    setActionError(null);
    try {
      const result = preview.onOpen?.();
      if (result && typeof result.then === "function") void result.catch((error) => setActionError(fileActionMessage(error, t)));
    } catch (error) {
      setActionError(fileActionMessage(error, t));
    }
  };
  const tokenLines = useMemo(() => {
    const grammar = Prism.languages[language] ?? Prism.languages.plain;
    return splitTokenStream(Prism.tokenize(normalizedText, grammar));
  }, [language, normalizedText]);

  useEffect(() => { setMarkdownMode("render"); setActionError(null); setImageModalOpen(false); }, [preview.asset.ref, preview.asset.path, preview.asset.name, preview.imageSrc]);
  useEffect(() => {
    const move = (event: PointerEvent) => {
      if (!startRef.current) return;
      const { minWidth: min, maxWidth: max, onWidthChange: changeWidth } = resizeLimitsRef.current;
      changeWidth(Math.max(min, Math.min(max, startRef.current.width - event.clientX + startRef.current.x)));
    };
    const up = () => { startRef.current = null; };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
  }, []);

  const PanelElement = embedded ? "div" : "aside";
  return <PanelElement className={embedded ? "document-preview-content" : "document-preview-panel"} aria-label={`${t("filePreview")}: ${fileDisplayName(preview.asset)}`}>
    {!embedded && <button className="document-preview-panel__resize" type="button" aria-label={t("resizeFilePreview")} onPointerDown={(event) => { startRef.current = { x: event.clientX, width }; event.currentTarget.setPointerCapture?.(event.pointerId); }} />}
    <header><div><strong>{fileDisplayName(preview.asset)}</strong><small>{language}</small></div><div className="document-preview-panel__actions">{isMarkdown && <button type="button" onClick={() => setMarkdownMode((value) => value === "render" ? "source" : "render")}>{markdownMode === "render" ? t("viewSource") : t("viewRendered")}</button>}{preview.onOpen && <button type="button" onClick={openTruncated}>{t("artifactOpen")}</button>}<button type="button" aria-label={t("closeFilePreview")} onClick={onClose}>×</button></div></header>
    <div className="document-preview-panel__body">{preview.imageSrc && /^data:[^,]+,/u.test(preview.imageSrc)
      ? <div className="document-review-image"><button type="button" aria-label={t("filePreview")} onClick={() => setImageModalOpen(true)}><img src={preview.imageSrc} alt={fileDisplayName(preview.asset)} /></button>{imageModalOpen && <ImagePreviewModal src={preview.imageSrc} alt={fileDisplayName(preview.asset)} onClose={() => setImageModalOpen(false)} />}</div>
      : isMarkdown && markdownMode === "render"
      ? <div className="document-preview-markdown">{renderMarkdown(preview.text)}</div>
      : <pre className="document-preview-code" data-language={language}>{lines.map((line, index) => <code key={`${index}:${line}`}><span className="document-preview-code__line-number">{index + 1}</span><span className={`language-${language}`}>{renderTokens(tokenLines[index] ?? [line], `${language}:${index}`)}</span>{index < lines.length - 1 ? "\n" : ""}</code>)}</pre>}
    </div>
    {actionError && <p className="document-preview-panel__notice" role="alert">{actionError}</p>}
    {preview.asset.truncated && <p className="document-preview-panel__notice">{t("previewTruncated")}</p>}
  </PanelElement>;
}

export interface ReviewPanelProps {
  tabs: ReviewPanelTab[];
  activeTabId: string;
  width: number;
  minWidth: number;
  maxWidth: number;
  onWidthChange: (width: number) => void;
  onSelectTab: (id: string) => void;
  onCloseTab: (id: string) => void;
  onClose: () => void;
  onReadToolOutput: (id: string) => void;
  onReadProcess: (processId: string, cursor: number) => void;
}

/** One owner-scoped side canvas for documents, current Diff, safe output, and process logs. */
export function ReviewPanel({ tabs, activeTabId, width, minWidth, maxWidth, onWidthChange, onSelectTab, onCloseTab, onClose, onReadToolOutput, onReadProcess }: ReviewPanelProps) {
  const { t } = useTranslation();
  const active = tabs.find((tab) => tab.id === activeTabId) ?? tabs.at(-1);
  const resizeStart = useRef<{ x: number; width: number } | null>(null);
  const resizeLimits = useRef({ minWidth, maxWidth, onWidthChange });
  resizeLimits.current = { minWidth, maxWidth, onWidthChange };
  useEffect(() => {
    const move = (event: PointerEvent) => {
      if (!resizeStart.current) return;
      const limits = resizeLimits.current;
      limits.onWidthChange(Math.max(limits.minWidth, Math.min(limits.maxWidth, resizeStart.current.width - event.clientX + resizeStart.current.x)));
    };
    const up = () => { resizeStart.current = null; };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
  }, []);
  if (!active) return null;
  return <aside className="document-preview-panel review-panel" aria-label={t("reviewTitle")}>
    <button className="document-preview-panel__resize" type="button" aria-label={t("resizeFilePreview")} onPointerDown={(event) => { resizeStart.current = { x: event.clientX, width }; event.currentTarget.setPointerCapture?.(event.pointerId); }} />
    <header className="review-panel__header"><strong>{t("reviewTitle")}</strong><button type="button" aria-label={t("closeFilePreview")} onClick={onClose}>×</button></header>
    <nav className="review-panel__tabs" role="tablist" aria-label={t("reviewTitle")}>
      {tabs.map((tab) => <span className="review-panel__tab" key={tab.id}>
        <button type="button" role="tab" aria-selected={active.id === tab.id} onClick={() => onSelectTab(tab.id)}>{tab.title}</button>
        <button type="button" aria-label={`${t("closeFilePreview")}: ${tab.title}`} onClick={() => onCloseTab(tab.id)}>×</button>
      </span>)}
    </nav>
    <div className="review-panel__content" role="tabpanel" aria-label={active.title}>
      {active.kind === "document" && <DocumentPreviewPanel preview={active.preview} width={width} minWidth={minWidth} maxWidth={maxWidth} onWidthChange={onWidthChange} onClose={() => onCloseTab(active.id)} embedded />}
      {active.kind === "workspace-diff" && <>
        <header className="review-panel__content-header"><strong>{active.path ? `${t("currentWorkingTree")}: ${active.path}` : t("currentWorkingTree")}</strong>{active.diff && <small>{new Date(active.diff.viewed_at).toLocaleString()}</small>}</header>
        {active.state === "reviewing" && <p className="review-panel__notice" role="status">{t("workspaceDiffReviewing")}</p>}
        {active.state === "failed" && <p className="review-panel__notice" role="alert">{active.error || t("workspaceDiffUnavailable")}</p>}
        {active.state === "cancelled" && <p className="review-panel__notice" role="status">{t("workspaceDiffCancelled")}</p>}
        {active.state === "stale" && <p className="review-panel__notice" role="status">{t("workspaceDiffStale")}</p>}
        {active.state === "completed" && active.diff && <div className="review-panel__diff">
          <p className="review-panel__source">{t("currentWorkingTree")} · {active.diff.project_key}{active.diff.status.branch ? ` · ${active.diff.status.branch}` : active.diff.status.unborn ? ` · ${t("unbornBranch")}` : ""}</p>
          {active.diff.status.truncated && <p className="review-panel__notice">{t("previewTruncated")}</p>}
          {active.diff.status.entries.length > 0 && <ul className="review-panel__paths" aria-label={t("changedFiles")}>{active.diff.status.entries.map((entry, index) => <li key={`${entry.xy}:${entry.path}:${index}`}><code>{entry.xy}</code><span>{entry.path}</span>{entry.original_path && <small>← {entry.original_path}</small>}</li>)}</ul>}
          {(["staged_diff", "unstaged_diff"] as const).map((key) => {
            const section = active.diff![key];
            return <section key={key} className="review-panel__diff-section"><h3>{t(key === "staged_diff" ? "staged" : "unstaged")}{section.truncated && ` · ${t("previewTruncated")}`}</h3>{section.text ? <pre>{section.text}</pre> : <p>{t("noDiffContent")}</p>}</section>;
          })}
          {active.diff.truncated && <p className="review-panel__notice">{t("previewTruncated")}</p>}
        </div>}
      </>}
      {active.kind === "tool-output" && <>
        <header className="review-panel__content-header"><strong>{active.title}</strong>{active.totalBytes !== null && <small>{active.totalBytes.toLocaleString()} B</small>}</header>
        {active.error && <p className="review-panel__notice" role="alert">{active.error}</p>}
        {active.truncated && <p className="review-panel__notice">{t("previewTruncated")}</p>}
        <pre className="review-panel__output">{active.text || t("noDiffContent")}</pre>
        {active.sha256 && <p className="review-panel__digest">SHA-256 · {active.sha256}</p>}
        {active.loading && <p className="review-panel__notice" role="status">{t("loading")}</p>}
        {!active.eof && active.ref && active.nextOffset !== null && <button className="review-panel__more" type="button" disabled={active.loading} onClick={() => onReadToolOutput(active.id)}>{t("loadMoreOutput")}</button>}
      </>}
      {active.kind === "process-log" && <>
        <header className="review-panel__content-header"><strong>{active.title}</strong><small>{active.reader.state || t("unavailable")}</small></header>
        {active.reader.error && <p className="review-panel__notice" role="alert">{active.reader.error}</p>}
        {active.reader.cursorExpired && <p className="review-panel__notice">{t("processCursorExpired")} · {active.reader.earliestCursor}</p>}
        <div className="review-panel__process-output">{active.entries.map((entry) => <pre key={`${active.processId}:${entry.sequence}`} data-process-sequence={entry.sequence}>{entry.stream === "status" ? `[status] ${entry.state || entry.text || "updated"}` : entry.text}</pre>)}</div>
        {active.reader.loading && <p className="review-panel__notice" role="status">{t("loading")}</p>}
        {active.reader.state === "running" && active.reader.nextCursor > 0 && <button className="review-panel__more" type="button" disabled={active.reader.loading} onClick={() => onReadProcess(active.processId, active.reader.nextCursor)}>{t("readNewer")}</button>}
      </>}
    </div>
  </aside>;
}
