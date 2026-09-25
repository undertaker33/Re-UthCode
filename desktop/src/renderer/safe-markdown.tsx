import { useState, type ElementType, type ReactNode } from "react";
import { useTranslation } from "./i18n";
import type { ArtifactDescriptor } from "../desktop-api";
import { FileCard, fileExtension, fileKind, type FilePreviewMode } from "./FileCard";
import type { DocumentPreview } from "./DocumentPreviewPanel";

export interface MarkdownRenderOptions {
  /** Narrow Desktop clipboard adapter; never read from window/electron here. */
  onCopyText?: (text: string) => Promise<void>;
  /** Open a previously validated local artifact through Main. */
  onOpenArtifact?: (path: string) => Promise<void>;
  /** Resolve a model-provided artifact reference into the formal DTO. */
  onDescribeArtifact?: (path: string) => Promise<ArtifactDescriptor | null>;
  /** Ask Main to show its picker and authorize one external artifact file. */
  onAuthorizeArtifact?: (path: string) => Promise<ArtifactDescriptor | null>;
  authorizeArtifactLabel?: string;
  /** Reveal a previously validated local artifact in the system shell. */
  onRevealArtifact?: (path: string) => Promise<void>;
  /** Request a controlled preview for a formal artifact DTO. */
  onPreviewArtifact?: (path: string, mode?: FilePreviewMode) => Promise<ArtifactDescriptor | null>;
  /** Open a read-only code/Markdown canvas owned by the Desktop shell. */
  onOpenDocument?: (preview: DocumentPreview) => void;
  /** Copy a validated artifact path through Main. */
  onCopyPath?: (path: string) => Promise<void>;
  artifacts?: Readonly<Record<string, ArtifactDescriptor>>;
}

export function safeHref(value: string): string | null {
  try {
    const url = new URL(value);
    if (url.protocol === "https:" || url.protocol === "http:" || url.protocol === "mailto:") return url.toString();
  } catch {
    // Invalid and local URLs remain plain text.
  }
  return null;
}

export function ArtifactCard({ artifact, onOpen, onReveal, onPreview, onOpenDocument, onCopyPath, onAuthorize }: { artifact: ArtifactDescriptor; onOpen?: () => Promise<void>; onReveal?: () => Promise<void>; onPreview?: (mode?: FilePreviewMode) => Promise<ArtifactDescriptor | null | void>; onOpenDocument?: (preview: DocumentPreview) => void; onCopyPath?: () => Promise<void>; onAuthorize?: () => Promise<void> }) {
  return <FileCard
    asset={artifact}
    className="artifact-card"
    dataAttributes={{ "data-artifact-path": artifact.path, "data-artifact-kind": artifact.kind }}
    onPreview={artifact.preview_supported && onPreview ? async (mode) => onPreview(mode) : undefined}
    onOpen={onOpen}
    onReveal={onReveal}
    onCopyPath={onCopyPath}
    onAuthorize={onAuthorize}
    onOpenDocument={onOpenDocument}
  />;
}

function artifactPlaceholder(path: string, label: string): ArtifactDescriptor {
  const name = path.split(/[\\/]/u).filter(Boolean).at(-1) || label || "artifact";
  const extension = fileExtension({ name });
  const kind = fileKind({ name, mime_type: "application/octet-stream" });
  const previewSupported = kind === "image" || kind === "markdown" || kind === "code" || kind === "text";
  const mimeType = kind === "image"
    ? ({ avif: "image/avif", bmp: "image/bmp", gif: "image/gif", ico: "image/x-icon", jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png", tif: "image/tiff", tiff: "image/tiff", webp: "image/webp" } as Record<string, string>)[extension] ?? "image/*"
    : kind === "markdown" ? "text/markdown"
      : kind === "code" || kind === "text" ? "text/plain"
        : "application/octet-stream";
  return {
    path,
    name,
    kind,
    mime_type: mimeType,
    size_bytes: 0,
    default_action: "open",
    preview_supported: previewSupported,
  };
}

function UnresolvedArtifactCard({
  path,
  label,
  artifact,
  options,
}: {
  path: string;
  label: string;
  artifact?: ArtifactDescriptor;
  options: MarkdownRenderOptions;
}) {
  const [resolved, setResolved] = useState<ArtifactDescriptor | null>(artifact ?? null);
  const resolve = async (): Promise<ArtifactDescriptor> => {
    if (resolved) return resolved;
    const described = await options.onDescribeArtifact?.(path);
    if (!described) {
      const error = new Error("Artifact descriptor is unavailable") as Error & { kind?: string };
      error.kind = "artifact_unavailable";
      throw error;
    }
    setResolved(described);
    return described;
  };
  const asset = resolved ?? artifactPlaceholder(path, label);
  const open = options.onOpenArtifact || options.onDescribeArtifact
    ? async () => { const described = await resolve(); await options.onOpenArtifact?.(described.path); }
    : undefined;
  const reveal = options.onRevealArtifact
    ? async () => { const described = await resolve(); await options.onRevealArtifact?.(described.path); }
    : undefined;
  const preview = options.onPreviewArtifact
    ? async (mode?: FilePreviewMode) => {
      const described = await resolve();
      return await options.onPreviewArtifact?.(described.path, mode) ?? described;
    }
    : undefined;
  const authorize = options.onAuthorizeArtifact
    ? async () => {
      const described = await options.onAuthorizeArtifact?.(path);
      if (described) setResolved(described);
    }
    : undefined;
  return <ArtifactCard
    artifact={asset}
    onOpen={open}
    onReveal={reveal}
    onPreview={preview}
    onAuthorize={authorize}
    onOpenDocument={options.onOpenDocument}
    onCopyPath={options.onCopyPath ? async () => options.onCopyPath?.(path) : undefined}
  />;
}

interface InlineToken {
  start: number;
  end: number;
  kind: "link" | "code" | "strong" | "em";
  label?: string;
  target?: string;
}

function decodeMarkdownTarget(value: string): string {
  const trimmed = value.trim();
  const enclosed = trimmed.startsWith("<") && trimmed.endsWith(">") ? trimmed.slice(1, -1) : trimmed;
  const unescaped = enclosed.replace(/\\([\\()\[\]])/gu, "$1");
  try {
    return decodeURIComponent(unescaped);
  } catch {
    return unescaped;
  }
}

function parseMarkdownLink(source: string, labelStart: number, targetStart: number): InlineToken | null {
  let index = targetStart;
  let depth = 0;
  let targetEnd = -1;
  while (index < source.length) {
    const character = source[index];
    if (character === "\\") {
      index += 2;
      continue;
    }
    if (character === "(") {
      depth += 1;
    } else if (character === ")") {
      if (depth === 0) {
        targetEnd = index;
        break;
      }
      depth -= 1;
    }
    index += 1;
  }
  if (targetEnd < 0) return null;
  const labelEnd = source.indexOf("]", labelStart + 1);
  if (labelEnd < 0 || source[labelEnd + 1] !== "(") return null;
  return {
    start: labelStart,
    end: targetEnd + 1,
    kind: "link",
    label: source.slice(labelStart + 1, labelEnd),
    target: decodeMarkdownTarget(source.slice(targetStart, targetEnd)),
  };
}

function nextInlineToken(source: string, from: number): InlineToken | null {
  for (let index = from; index < source.length; index += 1) {
    if (source[index] === "[") {
      const labelEnd = source.indexOf("]", index + 1);
      if (labelEnd >= 0 && source[labelEnd + 1] === "(") {
        const link = parseMarkdownLink(source, index, labelEnd + 2);
        if (link) return link;
      }
    }
    if (source[index] === "`") {
      const end = source.indexOf("`", index + 1);
      if (end >= 0) return { start: index, end: end + 1, kind: "code" };
    }
    if (source.startsWith("**", index)) {
      const end = source.indexOf("**", index + 2);
      if (end > index + 2) return { start: index, end: end + 2, kind: "strong" };
    }
    if (source[index] === "*" && source[index + 1] !== "*") {
      const end = source.indexOf("*", index + 1);
      if (end > index + 1) return { start: index, end: end + 1, kind: "em" };
    }
  }
  return null;
}

export function renderInline(source: string, options: MarkdownRenderOptions = {}): ReactNode[] {
  const nodes: ReactNode[] = [];
  let last = 0;
  let index = 0;
  while (last < source.length) {
    const token = nextInlineToken(source, last);
    if (!token) {
      nodes.push(source.slice(last));
      break;
    }
    if (token.start > last) nodes.push(source.slice(last, token.start));
    if (token.kind === "link") {
      const target = token.target ?? "";
      if (target.startsWith("artifact:") && (options.onDescribeArtifact || options.onOpenArtifact || options.artifacts?.[target.slice("artifact:".length)])) {
        const path = target.slice("artifact:".length);
        nodes.push(<UnresolvedArtifactCard key={`artifact-card-${index}`} path={path} label={token.label ?? path} artifact={options.artifacts?.[path]} options={options} />);
      } else {
        const href = safeHref(target);
        nodes.push(href ? <a key={`link-${index}`} href={href} target="_blank" rel="noreferrer">{token.label}</a> : <span key={`link-${index}`}>{token.label}</span>);
      }
    } else if (token.kind === "code") {
      nodes.push(<code key={`code-${index}`}>{source.slice(token.start + 1, token.end - 1)}</code>);
    } else if (token.kind === "strong") {
      nodes.push(<strong key={`strong-${index}`}>{source.slice(token.start + 2, token.end - 2)}</strong>);
    } else {
      nodes.push(<em key={`em-${index}`}>{source.slice(token.start + 1, token.end - 1)}</em>);
    }
    last = token.end;
    index += 1;
  }
  return nodes;
}

function isTableDivider(line: string): boolean {
  const cells = line.trim().replace(/^\||\|$/gu, "").split("|");
  return cells.length > 0 && cells.every((cell) => /^\s*:?-{3,}:?\s*$/u.test(cell));
}

function tableCells(line: string): string[] {
  return line.trim().replace(/^\||\|$/gu, "").split("|").map((cell) => cell.trim());
}

function fenceLanguage(info: string): string {
  const value = info.trim().split(/\s+/u)[0] ?? "";
  // The label is plain text rendered by React; normalize unusual whitespace
  // so it cannot become a second visual block or an accidental HTML surface.
  return value.replace(/[^a-zA-Z0-9_+#.-]/gu, "") || "text";
}

interface MarkdownLine {
  text: string;
  start: number;
  next: number;
}

function splitMarkdownLines(source: string): MarkdownLine[] {
  const lines: MarkdownLine[] = [];
  const separator = /\r\n?|\n/gu;
  let start = 0;
  let match: RegExpExecArray | null;
  while ((match = separator.exec(source)) !== null) {
    lines.push({ text: source.slice(start, match.index), start, next: match.index + match[0].length });
    start = match.index + match[0].length;
  }
  lines.push({ text: source.slice(start), start, next: source.length });
  return lines;
}

export interface CodeFenceProps {
  code: string;
  language: string;
  onCopyText?: (text: string) => Promise<void>;
}

export function CodeFence({ code, language, onCopyText }: CodeFenceProps) {
  const { t } = useTranslation();
  const [copyState, setCopyState] = useState<"idle" | "success" | "failed">("idle");
  const copy = async () => {
    try {
      if (!onCopyText) throw new Error("Clipboard unavailable");
      await onCopyText(code);
      setCopyState("success");
    } catch {
      setCopyState("failed");
    }
  };
  const copyLabel = copyState === "success" ? t("copiedCode") : copyState === "failed" ? t("copyCodeFailed") : t("copyCode");
  return <div className="markdown-code-fence" data-language={language}>
    <div className="markdown-code-fence__toolbar" role="toolbar" aria-label={t("codeBlock")}>
      <span className="markdown-code-fence__language">{language}</span>
      <button type="button" className="markdown-code-fence__copy" onClick={() => void copy()} aria-label={copyLabel} title={copyLabel}>{copyLabel}</button>
    </div>
    <pre><code>{code}</code></pre>
  </div>;
}

function renderMarkdownBlocks(source: string, options: MarkdownRenderOptions): ReactNode {
  const lineRecords = splitMarkdownLines(source);
  const lines = lineRecords.map((line) => line.text);
  const blocks: ReactNode[] = [];
  let index = 0;
  let blockIndex = 0;
  while (index < lines.length) {
    const line = lines[index] ?? "";
    if (!line.trim()) {
      index += 1;
      continue;
    }
    const fence = line.match(/^\s*(`{3,}|~{3,})([^\r\n]*)$/u);
    if (fence) {
      const marker = fence[1];
      const bodyStart = lineRecords[index]?.next ?? source.length;
      index += 1;
      let closingIndex = -1;
      while (index < lines.length) {
        const candidate = lines[index] ?? "";
        if (new RegExp(`^\\s*${marker[0]}{${marker.length},}\\s*$`, "u").test(candidate)) {
          closingIndex = index;
          break;
        }
        index += 1;
      }
      // Parse normalized line text for safety, but copy the exact original
      // body slice so CRLF, blank lines, trailing whitespace, and an unclosed
      // fence retain the user's source bytes. The separator after the opening
      // line is not body content; the separator before a closing marker is.
      const bodyEnd = closingIndex >= 0 ? lineRecords[closingIndex]?.start ?? source.length : source.length;
      const code = source.slice(bodyStart, bodyEnd);
      if (closingIndex >= 0) index += 1;
      blocks.push(<CodeFence key={`fence-${blockIndex}`} code={code} language={fenceLanguage(fence[2] ?? "")} onCopyText={options.onCopyText} />);
      blockIndex += 1;
      continue;
    }
    const heading = line.match(/^\s*(#{1,6})\s+(.+?)\s*#*\s*$/u);
    if (heading) {
      const level = heading[1].length;
      const Heading = `h${level}` as ElementType;
      blocks.push(<Heading key={`heading-${blockIndex}`}>{renderInline(heading[2], options)}</Heading>);
      index += 1;
      blockIndex += 1;
      continue;
    }
    if (index + 1 < lines.length && line.includes("|") && isTableDivider(lines[index + 1] ?? "")) {
      const header = tableCells(line);
      const rows: string[][] = [];
      index += 2;
      while (index < lines.length && (lines[index] ?? "").includes("|") && (lines[index] ?? "").trim()) {
        rows.push(tableCells(lines[index] ?? ""));
        index += 1;
      }
      blocks.push(<table key={`table-${blockIndex}`}><thead><tr>{header.map((cell, cellIndex) => <th key={`th-${cellIndex}`}>{renderInline(cell, options)}</th>)}</tr></thead><tbody>{rows.map((row, rowIndex) => <tr key={`tr-${rowIndex}`}>{header.map((_cell, cellIndex) => <td key={`td-${cellIndex}`}>{renderInline(row[cellIndex] ?? "", options)}</td>)}</tr>)}</tbody></table>);
      blockIndex += 1;
      continue;
    }
    if (/^\s*>/u.test(line)) {
      const quote: string[] = [];
      while (index < lines.length && /^\s*>/u.test(lines[index] ?? "")) {
        quote.push((lines[index] ?? "").replace(/^\s*>\s?/u, ""));
        index += 1;
      }
      blocks.push(<blockquote key={`quote-${blockIndex}`}>{renderMarkdownBlocks(quote.join("\n"), options)}</blockquote>);
      blockIndex += 1;
      continue;
    }
    const unordered = line.match(/^\s*[-*+]\s+(.+)$/u);
    const ordered = line.match(/^\s*\d+[.]\s+(.+)$/u);
    if (unordered || ordered) {
      const items: string[] = [];
      const orderedList = !!ordered;
      while (index < lines.length) {
        const candidate = lines[index] ?? "";
        const match = orderedList ? candidate.match(/^\s*\d+[.]\s+(.+)$/u) : candidate.match(/^\s*[-*+]\s+(.+)$/u);
        if (!match) break;
        items.push(match[1]);
        index += 1;
      }
      const List = orderedList ? "ol" : "ul";
      blocks.push(<List key={`list-${blockIndex}`}>{items.map((item, itemIndex) => <li key={`li-${itemIndex}`}>{renderInline(item, options)}</li>)}</List>);
      blockIndex += 1;
      continue;
    }
    const paragraph: string[] = [line];
    index += 1;
    while (index < lines.length && (lines[index] ?? "").trim()) {
      const next = lines[index] ?? "";
      if (/^\s*(#{1,6})\s+|^\s*(`{3,}|~{3,})|^\s*>|^\s*[-*+]\s+|^\s*\d+[.]\s+/u.test(next)) break;
      paragraph.push(next);
      index += 1;
    }
    const artifactOnly = paragraph.length === 1 && /^\s*\[[^\]]+\]\(artifact:[^)\s]+\)\s*$/u.test(paragraph[0] ?? "");
    if (artifactOnly) {
      blocks.push(<div key={`paragraph-${blockIndex}`} className="markdown-artifact-block">{renderInline(paragraph[0] ?? "", options)}</div>);
    } else {
      blocks.push(<p key={`paragraph-${blockIndex}`}>{paragraph.map((part, partIndex) => <span key={`line-${partIndex}`}>{renderInline(part, options)}{partIndex < paragraph.length - 1 && <br />}</span>)}</p>);
    }
    blockIndex += 1;
  }
  return blocks;
}

/** Render the deliberately small safe Markdown subset without raw HTML. */
export function renderMarkdown(source: string, options: MarkdownRenderOptions = {}): ReactNode {
  return renderMarkdownBlocks(source, options);
}
