import { useCallback, useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent, type PointerEvent as ReactPointerEvent, type WheelEvent as ReactWheelEvent } from "react";
import type { ArtifactDescriptor, DesktopAttachmentDraft } from "../desktop-api";
import { useTranslation, type TranslationKey } from "./i18n";
import type { DocumentPreview } from "./DocumentPreviewPanel";
import { UiIcon } from "./UiIcon";

/** A renderer-only view of a file. It deliberately contains no fs/shell handle. */
export type FileCardAsset = Partial<DesktopAttachmentDraft> & Partial<ArtifactDescriptor> & {
  name?: string;
  display_name?: string;
  asset_ref?: string;
  preview_kind?: string;
  text?: string;
  truncated?: boolean;
};

export type FilePreviewMode = "thumbnail" | "full";

function fileErrorKind(error: unknown): string {
  if (!error || typeof error !== "object") return "";
  const direct = (error as { kind?: unknown }).kind;
  if (typeof direct === "string") return direct;
  const payload = (error as { __uthcode_runtime_error?: unknown }).__uthcode_runtime_error;
  if (payload && typeof payload === "object" && typeof (payload as { kind?: unknown }).kind === "string") {
    return (payload as { kind: string }).kind;
  }
  return "";
}

export function fileActionMessage(error: unknown, t: (key: TranslationKey) => string): string {
  const kind = fileErrorKind(error);
  if (kind.endsWith("_not_found")) return t("fileNotFound");
  if (kind.endsWith("_not_authorized")) return t("fileNotAuthorized");
  if (kind.endsWith("_open_failed")) return t("fileOpenFailed");
  if (kind.endsWith("_invalid") || kind.endsWith("_unavailable")) return t("fileDescriptorInvalid");
  return t("fileActionFailed");
}

export function fileDisplayName(asset: FileCardAsset): string {
  return asset.display_name || asset.name || "file";
}

export function fileExtension(asset: FileCardAsset): string {
  const name = fileDisplayName(asset);
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot + 1).toLowerCase() : "file";
}

export function fileKind(asset: FileCardAsset): string {
  if (asset.mime_type === "image/svg+xml") return "unsupported";
  if (asset.kind === "text") return "text";
  if (asset.kind === "office") {
    const officeExtension = fileExtension(asset);
    if (officeExtension === "pdf") return "pdf";
    if (/^(?:doc|docx)$/u.test(officeExtension)) return "word";
    if (/^(?:xls|xlsx)$/u.test(officeExtension)) return "spreadsheet";
    if (/^(?:ppt|pptx)$/u.test(officeExtension)) return "presentation";
    return "office";
  }
  if (asset.kind && !["file", "attachment", "artifact"].includes(asset.kind)) return asset.kind;
  if (/^(?:exe|com|bat|cmd|ps1|sh|msi|vbs)$/u.test(fileExtension(asset))) return "executable";
  if (asset.mime_type?.startsWith("image/")) return "image";
  if (asset.mime_type === "application/pdf" || fileExtension(asset) === "pdf") return "pdf";
  if (/^(?:avif|bmp|gif|ico|jpe?g|png|tiff?|webp)$/u.test(fileExtension(asset))) return "image";
  if (/^(?:doc|docx)$/u.test(fileExtension(asset))) return "word";
  if (/^(?:xls|xlsx)$/u.test(fileExtension(asset))) return "spreadsheet";
  if (/^(?:ppt|pptx)$/u.test(fileExtension(asset))) return "presentation";
  if (/^(?:md|markdown)$/u.test(fileExtension(asset))) return "markdown";
  if (/^(?:py|pyw|js|jsx|ts|tsx|java|c|cc|cpp|h|hpp|rs|go|rb|php|css|html|json|yaml|yml|toml|sh|bat|ps1|xml|txt|ini|log|sql|rst|diff|env)$/u.test(fileExtension(asset))) return "code";
  return "file";
}

function isImage(asset: FileCardAsset): boolean {
  return asset.mime_type !== "image/svg+xml" && (asset.mime_type?.startsWith("image/") === true || fileKind(asset) === "image");
}

function isCode(asset: FileCardAsset): boolean {
  const kind = fileKind(asset);
  return kind === "code" || kind === "markdown" || kind === "text" || asset.preview_kind === "text" || asset.mime_type?.startsWith("text/") === true;
}

function effectiveSource(asset: FileCardAsset): string | undefined {
  if (typeof asset.data_url === "string" && asset.data_url.startsWith("data:")) return asset.data_url;
  return undefined;
}

export function fileLanguage(asset: FileCardAsset): string {
  const extension = fileExtension(asset);
  return extension === "markdown" ? "md" : extension;
}

export interface ImagePreviewModalProps {
  src: string;
  alt: string;
  onClose: () => void;
}

/** Full-image preview owns focus, zoom and panning without changing chat layout. */
export function ImagePreviewModal({ src, alt, onClose }: ImagePreviewModalProps) {
  const { t } = useTranslation();
  const dialogRef = useRef<HTMLDivElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const dragRef = useRef<{ x: number; y: number; offsetX: number; offsetY: number } | null>(null);
  const [zoom, setZoom] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });

  useEffect(() => {
    restoreFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialogRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      } else if (event.key === "Tab") {
        const focusable = dialogRef.current?.querySelectorAll<HTMLElement>("button, [tabindex]:not([tabindex='-1'])");
        if (!focusable || focusable.length === 0) return;
        const first = focusable[0]!;
        const last = focusable[focusable.length - 1]!;
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      } else if (event.key === "+" || event.key === "=") {
        event.preventDefault();
        setZoom((value) => Math.min(8, value * 1.2));
      } else if (event.key === "-" || event.key === "_") {
        event.preventDefault();
        setZoom((value) => Math.max(0.25, value / 1.2));
      } else if (event.key === "0") {
        event.preventDefault();
        setZoom(1);
        setOffset({ x: 0, y: 0 });
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      restoreFocusRef.current?.focus({ preventScroll: true });
    };
  }, [onClose]);

  const onWheel = (event: ReactWheelEvent<HTMLDivElement>) => {
    event.preventDefault();
    setZoom((value) => Math.min(8, Math.max(0.25, value * (event.deltaY < 0 ? 1.12 : 0.89))));
  };

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    dragRef.current = { x: event.clientX, y: event.clientY, offsetX: offset.x, offsetY: offset.y };
  };
  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current;
    if (!drag) return;
    setOffset({ x: drag.offsetX + event.clientX - drag.x, y: drag.offsetY + event.clientY - drag.y });
  };
  const endDrag = () => { dragRef.current = null; };

  return <div className="image-preview-backdrop" role="presentation" onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <div ref={dialogRef} className="image-preview-modal" role="dialog" aria-modal="true" aria-label={alt} tabIndex={-1}>
      <header><strong>{alt}</strong><button type="button" aria-label={t("closePreview")} onClick={onClose}>×</button></header>
      <div className="image-preview-stage" onWheel={onWheel} onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={endDrag} onPointerCancel={endDrag}><img src={src} alt={alt} draggable={false} style={{ transform: `translate(${offset.x}px, ${offset.y}px) scale(${zoom})` }} /></div>
      <footer><span>{Math.round(zoom * 100)}%</span><button type="button" onClick={() => { setZoom(1); setOffset({ x: 0, y: 0 }); }}>{t("resetPreview")}</button></footer>
    </div>
  </div>;
}

export interface FileCardProps {
  asset: FileCardAsset;
  draft?: boolean;
  className?: string;
  dataAttributes?: Readonly<Record<string, string | undefined>>;
  onPreview?: (mode?: FilePreviewMode) => Promise<FileCardAsset | null | void>;
  onOpen?: () => void | Promise<void>;
  onReveal?: () => void | Promise<void>;
  onCopyPath?: () => void | Promise<void>;
  onRemove?: () => void | Promise<void>;
  onAuthorize?: () => void | Promise<void>;
  onOpenDocument?: (preview: DocumentPreview) => void;
}

export function FileCard({ asset, draft = false, className, dataAttributes, onPreview, onOpen, onReveal, onCopyPath, onRemove, onAuthorize, onOpenDocument }: FileCardProps) {
  const { t } = useTranslation();
  const [menuOpen, setMenuOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [imageSrc, setImageSrc] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const ownMenuRef = useRef<HTMLDivElement>(null);
  const cardRef = useRef<HTMLElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const kind = fileKind(asset);
  const image = isImage(asset);
  const code = isCode(asset);
  const name = fileDisplayName(asset);
  const extension = fileExtension(asset);
  const extensionLabel = kind === "file" ? "FILE" : extension.slice(0, 5).toUpperCase();
  const menuActions = [
    image && (onPreview || effectiveSource(asset)),
    code && onPreview,
    onOpen && kind !== "executable",
    onReveal,
    onCopyPath,
    onAuthorize,
    draft && onRemove,
  ].filter(Boolean).length;
  const closeMenu = useCallback((restoreFocus = false) => {
    setMenuOpen(false);
    if (restoreFocus) cardRef.current?.focus({ preventScroll: true });
  }, []);
  const openMenu = useCallback(() => {
    if (menuActions === 0) return;
    setActionError(null);
    setMenuOpen(true);
  }, [menuActions]);
  useEffect(() => {
    if (!menuOpen) return;
    menuRef.current?.querySelector<HTMLButtonElement>("button[role='menuitem']:not([disabled])")?.focus({ preventScroll: true });
  }, [menuOpen]);
  const run = (action: (() => void | Promise<void>) | undefined) => {
    if (!action || busy) return;
    setActionError(null);
    setBusy(true);
    closeMenu();
    try {
      const result = action();
      if (result && typeof result.then === "function") {
        void result.catch((error) => setActionError(fileActionMessage(error, t))).finally(() => setBusy(false));
      } else {
        setBusy(false);
      }
    } catch (error) {
      setActionError(fileActionMessage(error, t));
      setBusy(false);
    }
  };
  const preview = async (mode: FilePreviewMode = "thumbnail") => {
    if (busy) return;
    setActionError(null);
    if (!onPreview) {
      const source = effectiveSource(asset);
      if (source) setImageSrc(source);
      return;
    }
    setBusy(true);
    setMenuOpen(false);
    try {
      const result = await onPreview(mode);
      const merged = result ? { ...asset, ...result } : asset;
      const mergedImage = isImage(merged);
      const mergedCode = isCode(merged);
      if (mergedImage && effectiveSource(merged)) setImageSrc(effectiveSource(merged)!);
      else if (mergedCode && typeof merged.text === "string") onOpenDocument?.({ asset: merged, text: merged.text, onOpen });
      else if (!mergedImage && !mergedCode) setActionError(t("filePreviewError"));
    } catch (error) {
      setActionError(fileActionMessage(error, t));
    } finally { setBusy(false); }
  };
  useEffect(() => {
    const close = (event: MouseEvent) => { if (!ownMenuRef.current?.contains(event.target as Node)) setMenuOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  const defaultAction = kind === "executable" || kind === "unsupported" ? onReveal : onOpen;
  const onDoubleClick = () => {
    if (image && (onPreview || effectiveSource(asset))) return void preview("full");
    if (code && onPreview) return void preview("full");
    return void run(defaultAction);
  };
  const onCardKeyDown = (event: ReactKeyboardEvent<HTMLElement>) => {
    if ((event.key === "F10" && event.shiftKey) || event.key === "ContextMenu") {
      event.preventDefault();
      openMenu();
    }
  };
  const onCardContextMenu = (event: ReactMouseEvent<HTMLElement>) => {
    event.preventDefault();
    openMenu();
  };
  const onMenuKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const items = Array.from(menuRef.current?.querySelectorAll<HTMLButtonElement>("button[role='menuitem']:not([disabled])") ?? []);
    if (event.key === "Escape") {
      event.preventDefault();
      closeMenu(true);
      return;
    }
    if (event.key === "Tab") {
      closeMenu();
      return;
    }
    if (items.length === 0) return;
    const current = items.indexOf(document.activeElement as HTMLButtonElement);
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      items[(current + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length]?.focus();
    } else if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      (event.key === "Home" ? items[0] : items.at(-1))?.focus();
    }
  };
  const attributes = Object.fromEntries(Object.entries(dataAttributes ?? {}).filter(([, value]) => value !== undefined));
  const hasImagePreview = image && Boolean(effectiveSource(asset));
  return <article ref={cardRef} className={`file-card${hasImagePreview ? " file-card--image-preview" : ""}${className ? ` ${className}` : ""}`} data-file-kind={kind} data-file-ref={asset.ref ?? asset.path ?? asset.asset_ref} {...attributes} onDoubleClick={onDoubleClick} onContextMenu={onCardContextMenu} onKeyDown={onCardKeyDown} tabIndex={0} aria-label={`${name} · ${kind}`} title={image ? undefined : name}>
    <div className="file-card__visual">{image && effectiveSource(asset) ? <img src={effectiveSource(asset)} alt={name} loading="lazy" /> : <><UiIcon name="file" /><span className="file-card__extension" aria-hidden="true">{extensionLabel}</span></>}</div>
    {!image && <div className="file-card__meta"><strong>{name}</strong><small>{asset.mime_type || kind} · {(asset.size_bytes ?? 0).toLocaleString()} B</small></div>}
    {draft && onRemove && <button type="button" className="file-card__remove-button" aria-label={`${t("attachmentRemove")}: ${name}`} title={`${t("attachmentRemove")}: ${name}`} onClick={(event) => { event.preventDefault(); event.stopPropagation(); void run(onRemove); }} onDoubleClick={(event) => { event.preventDefault(); event.stopPropagation(); }} disabled={busy}><span aria-hidden="true">×</span></button>}
    <div ref={ownMenuRef} className="file-card__menu-wrap">
      <div ref={menuRef} className={`file-card__menu${asset.path ? " artifact-card__actions" : ""}`} role="menu" aria-label={`${t("fileActions")}: ${name}`} hidden={!menuOpen} onKeyDown={onMenuKeyDown}>
        {((image && (onPreview || effectiveSource(asset))) || (code && onPreview)) && <button type="button" role="menuitem" onClick={() => void preview("full")} disabled={busy}>{t("filePreview")}</button>}
        {onOpen && kind !== "executable" && <button type="button" role="menuitem" onClick={() => void run(onOpen)} disabled={busy}>{t("artifactOpen")}</button>}
        {onReveal && <button type="button" role="menuitem" onClick={() => void run(onReveal)} disabled={busy}>{t("artifactReveal")}</button>}
        {onCopyPath && <button type="button" role="menuitem" onClick={() => void run(onCopyPath)} disabled={busy}>{t("copyPath")}</button>}
        {onAuthorize && <button type="button" role="menuitem" onClick={() => void run(onAuthorize)} disabled={busy}>{t("artifactAuthorize")}</button>}
        {draft && onRemove && <button type="button" role="menuitem" aria-label={`${t("remove")} attachment ${name}`} className="danger" onClick={() => void run(onRemove)} disabled={busy}>{t("remove")}</button>}
      </div>
    </div>
    {actionError && <p className="file-card__error" role="alert">{actionError}</p>}
    {imageSrc && <ImagePreviewModal src={imageSrc} alt={name} onClose={() => setImageSrc(null)} />}
  </article>;
}

export function attachmentAsset(attachment: DesktopAttachmentDraft): FileCardAsset {
  return attachment;
}
