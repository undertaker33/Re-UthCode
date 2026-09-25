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
import { fileActionMessage, fileDisplayName, fileExtension, fileKind } from "./FileCard";
import { renderMarkdown } from "./safe-markdown";
import { useTranslation } from "./i18n";

export interface DocumentPreview {
  asset: FileCardAsset;
  text: string;
  onOpen?: () => void | Promise<void>;
  owner?: DocumentPreviewOwner;
}

export interface DocumentPreviewOwner {
  generation: number;
  projectKey: string | null;
  sessionId: string | null;
  viewRevision: number;
}

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
}

/** Read-only right-side source canvas shared by Markdown and code artifacts. */
export function DocumentPreviewPanel({ preview, width, minWidth, maxWidth, onWidthChange, onClose }: DocumentPreviewPanelProps) {
  const { t } = useTranslation();
  const [markdownMode, setMarkdownMode] = useState<"render" | "source">("render");
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

  useEffect(() => { setMarkdownMode("render"); setActionError(null); }, [preview.asset.ref, preview.asset.path, preview.asset.name]);
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

  return <aside className="document-preview-panel" aria-label={`${t("filePreview")}: ${fileDisplayName(preview.asset)}`}>
    <button className="document-preview-panel__resize" type="button" aria-label={t("resizeFilePreview")} onPointerDown={(event) => { startRef.current = { x: event.clientX, width }; event.currentTarget.setPointerCapture?.(event.pointerId); }} />
    <header><div><strong>{fileDisplayName(preview.asset)}</strong><small>{language}</small></div><div className="document-preview-panel__actions">{isMarkdown && <button type="button" onClick={() => setMarkdownMode((value) => value === "render" ? "source" : "render")}>{markdownMode === "render" ? t("viewSource") : t("viewRendered")}</button>}{preview.asset.truncated && preview.onOpen && <button type="button" onClick={openTruncated}>{t("artifactOpen")}</button>}<button type="button" aria-label={t("closeFilePreview")} onClick={onClose}>×</button></div></header>
    <div className="document-preview-panel__body">{isMarkdown && markdownMode === "render"
      ? <div className="document-preview-markdown">{renderMarkdown(preview.text)}</div>
      : <pre className="document-preview-code" data-language={language}>{lines.map((line, index) => <code key={`${index}:${line}`}><span className="document-preview-code__line-number">{index + 1}</span><span className={`language-${language}`}>{renderTokens(tokenLines[index] ?? [line], `${language}:${index}`)}</span>{index < lines.length - 1 ? "\n" : ""}</code>)}</pre>}
    </div>
    {actionError && <p className="document-preview-panel__notice" role="alert">{actionError}</p>}
    {preview.asset.truncated && <p className="document-preview-panel__notice">{t("previewTruncated")}</p>}
  </aside>;
}
