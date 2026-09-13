import { useState, type ElementType, type ReactNode } from "react";
import { useTranslation } from "./i18n";
import type { ArtifactDescriptor } from "../desktop-api";

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
  /** Request a controlled image preview for a formal artifact DTO. */
  onPreviewArtifact?: (path: string) => Promise<ArtifactDescriptor | null>;
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

export function ArtifactCard({ artifact, onOpen, onReveal, onPreview }: { artifact: ArtifactDescriptor; onOpen?: () => Promise<void>; onReveal?: () => Promise<void>; onPreview?: () => Promise<void> }) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const run = async (action?: () => Promise<void>) => {
    if (!action || busy) return;
    setBusy(true);
    try { await action(); } finally { setBusy(false); }
  };
  return <span className="artifact-card" data-artifact-kind={artifact.kind} data-artifact-path={artifact.path} role="group">
    {artifact.data_url && artifact.kind === "image" ? <img src={artifact.data_url} alt={artifact.name} loading="lazy" /> : null}
    <span className="artifact-card__meta"><strong>{artifact.name}</strong><small>{artifact.mime_type} · {artifact.size_bytes.toLocaleString()} B</small></span>
    <span className="artifact-card__actions">
      {artifact.preview_supported && onPreview && <button type="button" onClick={() => void run(onPreview)} disabled={busy}>{t("artifactPreview")}</button>}
      {onOpen && artifact.kind !== "executable" && <button type="button" onClick={() => void run(onOpen)} disabled={busy}>{t("artifactOpen")}</button>}
      {onReveal && <button type="button" onClick={() => void run(onReveal)} disabled={busy}>{t("artifactReveal")}</button>}
    </span>
  </span>;
}

export function renderInline(source: string, options: MarkdownRenderOptions = {}): ReactNode[] {
  const nodes: ReactNode[] = [];
  const pattern = /(\[[^\]]+\]\(([^)\s]+)\)|`[^`]*`|\*\*[^*]+\*\*|\*[^*]+\*)/gu;
  let last = 0;
  let index = 0;
  for (const match of source.matchAll(pattern)) {
    const token = match[0];
    const start = match.index ?? 0;
    if (start > last) nodes.push(source.slice(last, start));
    if (token.startsWith("[") && match[2]) {
      const label = token.slice(1, token.indexOf("]("));
      const target = match[2];
      if (target.startsWith("artifact:") && (options.onDescribeArtifact || options.onOpenArtifact)) {
        const path = target.slice("artifact:".length);
        const artifact = options.artifacts?.[path];
        if (artifact) {
          nodes.push(<ArtifactCard
            key={`artifact-card-${index}`}
            artifact={artifact}
            onOpen={options.onOpenArtifact ? async () => { await options.onOpenArtifact?.(path); } : undefined}
            onReveal={options.onRevealArtifact ? async () => { await options.onRevealArtifact?.(path); } : undefined}
            onPreview={options.onPreviewArtifact ? async () => { await options.onPreviewArtifact?.(path); } : undefined}
          />);
        } else {
          const describe = options.onDescribeArtifact ?? options.onOpenArtifact;
          nodes.push(<span key={`artifact-${index}`} className="artifact-link-group">
            <button type="button" className="artifact-link" onClick={() => void describe?.(path)}>{label}</button>
            {options.onAuthorizeArtifact && <button type="button" className="artifact-authorize" onClick={() => void options.onAuthorizeArtifact?.(path)}>{options.authorizeArtifactLabel ?? "Authorize external file"}</button>}
          </span>);
        }
      } else {
        const href = safeHref(target);
        nodes.push(href ? <a key={`link-${index}`} href={href} target="_blank" rel="noreferrer">{label}</a> : <span key={`link-${index}`}>{label}</span>);
      }
    } else if (token.startsWith("`") && token.endsWith("`")) {
      nodes.push(<code key={`code-${index}`}>{token.slice(1, -1)}</code>);
    } else if (token.startsWith("**")) {
      nodes.push(<strong key={`strong-${index}`}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("*")) {
      nodes.push(<em key={`em-${index}`}>{token.slice(1, -1)}</em>);
    }
    last = start + token.length;
    index += 1;
  }
  if (last < source.length) nodes.push(source.slice(last));
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
    blocks.push(<p key={`paragraph-${blockIndex}`}>{paragraph.map((part, partIndex) => <span key={`line-${partIndex}`}>{renderInline(part, options)}{partIndex < paragraph.length - 1 && <br />}</span>)}</p>);
    blockIndex += 1;
  }
  return blocks;
}

/** Render the deliberately small safe Markdown subset without raw HTML. */
export function renderMarkdown(source: string, options: MarkdownRenderOptions = {}): ReactNode {
  return renderMarkdownBlocks(source, options);
}
