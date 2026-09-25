import { Fragment, useEffect, useLayoutEffect, useRef, useState, type UIEvent } from "react";
import type { ProcessLogEntry, ProcessReaderState, TimelineEntry, TodoItem } from "./state";
import type { ArtifactDescriptor, DesktopAttachmentDraft, TimelineAttachment, TimelineUnavailableAttachment } from "../desktop-api";
import { useTranslation, type TranslationKey } from "./i18n";
import { UiIcon, type UiIconName } from "./UiIcon";
import { renderMarkdown } from "./safe-markdown";
import { FileCard, type FilePreviewMode } from "./FileCard";
import type { DocumentPreview } from "./DocumentPreviewPanel";

/** Pixels from the end that still count as being at the bottom. */
export const TIMELINE_NEAR_BOTTOM_THRESHOLD = 72;

export function isNearBottom(
  element: Pick<HTMLElement, "scrollTop" | "scrollHeight" | "clientHeight">,
  threshold = TIMELINE_NEAR_BOTTOM_THRESHOLD,
): boolean {
  const remaining = element.scrollHeight - element.clientHeight - element.scrollTop;
  return remaining <= Math.max(0, threshold);
}
export function scrollTimelineToBottom(element: Pick<HTMLElement, "scrollTop" | "scrollHeight" | "clientHeight">): void {
  element.scrollTop = Math.max(0, element.scrollHeight - element.clientHeight);
}

export interface ChatTimelineProps {
  entries: TimelineEntry[];
  todo: TodoItem[];
  notice?: string | null;
  compactionNotice?: string | null;
  compactionAnchor?: Pick<TimelineEntry, "id" | "messageId" | "kind"> | null;
  compactionRunning?: boolean;
  compactionCompleted?: boolean;
  onLatestSeen?: () => void;
  /** Runtime errors are rendered here only when RuntimePanel is not visible. */
  runtimeError?: string | null;
  runtimeErrorVisible?: boolean;
  onOpenSettings?: () => void;
  /** Narrow main-process clipboard adapter shared with Session ID copy. */
  onCopyText?: (text: string) => Promise<void>;
  onOpenArtifact?: (path: string) => Promise<void>;
  onDescribeArtifact?: (path: string) => Promise<ArtifactDescriptor | null>;
  onAuthorizeArtifact?: (path: string) => Promise<ArtifactDescriptor | null>;
  onRevealArtifact?: (path: string) => Promise<void>;
  onPreviewArtifact?: (path: string, mode?: FilePreviewMode) => Promise<ArtifactDescriptor | null>;
  onCopyPath?: (path: string) => Promise<void>;
  onOpenDocument?: (preview: DocumentPreview) => void;
  onPreviewAttachment?: (ref: string, mode?: FilePreviewMode) => Promise<DesktopAttachmentDraft | null>;
  onOpenAttachment?: (ref: string) => Promise<void>;
  onRevealAttachment?: (ref: string) => Promise<void>;
  onCopyAttachmentPath?: (ref: string, assetRef?: string) => Promise<void>;
  /** Changes only when a Session/Project view is replaced, not on streaming. */
  sessionKey?: string;
  /** Request an older durable page when the reader reaches the top. */
  onLoadOlder?: () => void;
  /** Retry only the failed older-page request. */
  onRetryOlder?: () => void;
  historyHasMore?: boolean;
  historyLoading?: boolean;
  historyError?: string | null;
  /** Changes after a successful durable page prepend. */
  historyRevision?: number;
  /** Cold runtime preparation is independent from the visible history page. */
  preparationStatus?: "preparing" | "ready" | "failed";
  /** Bounded process observations for the selected Session. */
  processLogs?: ProcessLogEntry[];
  /** Authoritative process.read continuation state for the selected Session. */
  processReaders?: Record<string, ProcessReaderState>;
  onReadProcess?: (processId: string, cursor: number) => void;
  onStopProcess?: (processId: string) => void;
}

function entryLabel(entry: TimelineEntry, t: (key: TranslationKey) => string): string {
  if (entry.kind === "user") return t("you");
  if (entry.kind === "steering") return t("steering");
  if (entry.kind === "reasoning") return t("reasoningLabel");
  if (entry.kind === "tool") return entry.toolName || t("toolLabel");
  if (entry.kind === "plan") return t("plan");
  if (entry.kind === "status") return t("statusLabel");
  return t("assistantLabel");
}

function localText(value: string, t: (key: TranslationKey) => string): string {
  const exact: Partial<Record<string, TranslationKey>> = { "Session resumed": "sessionResumed", running: "running", failed: "failed", completed: "completed", cancelled: "cancelled", pending: "pending", in_progress: "inProgress", "Steering requested": "steeringRequested", "Steering applied": "steeringApplied", "Pausing…": "pausing", "Interaction answered": "interactionAnswered", "Turn cancelled": "turnCancelled", "New Session": "newSessionNotice" };
  if (exact[value]) return t(exact[value]!);
  const waiting = value.match(/^Waiting for (permission|plan review|provider retry|user input|turn pause)$/u);
  if (waiting) {
    const keys = { permission: "permissionInteraction", "plan review": "planReviewInteraction", "provider retry": "providerRetryInteraction", "user input": "userInputInteraction", "turn pause": "turnPauseInteraction" } as const;
    return `${t("waitingFor")} ${t(keys[waiting[1] as keyof typeof keys])}`;
  }
  if (value.startsWith("Turn failed: ")) {
    const reason = value.slice("Turn failed: ".length);
    return `${t("turnFailed")}: ${reason === "runtime error" ? t("runtimeError") : reason}`;
  }
  return value;
}

function toolStatusIcon(status: string): UiIconName {
  if (status === "failed") return "warning";
  if (status === "completed") return "check";
  if (status === "cancelled") return "warning";
  return "status";
}

function elapsedSeconds(entry: TimelineEntry, now: number): number | null {
  if (entry.startedAt === undefined) return null;
  const end = entry.endedAt ?? now;
  return Math.max(0, Math.floor((end - entry.startedAt) / 1000));
}

function todoStatusLabel(status: TodoItem["status"], t: (key: TranslationKey) => string): string {
  return status === "completed" ? t("completed") : status === "in_progress" ? t("inProgress") : t("pending");
}

function isUnavailableAttachment(attachment: TimelineAttachment): attachment is TimelineUnavailableAttachment {
  return "available" in attachment && attachment.available === false;
}

function renderAttachmentRows(entry: TimelineEntry, t: (key: TranslationKey) => string, previews: Readonly<Record<string, DesktopAttachmentDraft>>, onPreviewAttachment?: (ref: string, mode?: FilePreviewMode) => Promise<DesktopAttachmentDraft | null>, onOpenAttachment?: (ref: string) => Promise<void>, onRevealAttachment?: (ref: string) => Promise<void>, onCopyAttachmentPath?: (ref: string, assetRef?: string) => Promise<void>) {
  if (!entry.attachments || entry.attachments.length === 0) return null;
  return <div className="timeline-attachments" aria-label={t("attachments")}>
    {entry.attachments.map((attachment, index) => {
      const identity = attachment.ref ?? attachment.asset_ref ?? `${entry.id}:${index}`;
      if (isUnavailableAttachment(attachment)) {
        return <div className="timeline-attachment timeline-attachment--unavailable" key={`${entry.id}:${identity}`} role="note" aria-label={t("attachmentUnavailable")} data-attachment-unavailable="true">
          <UiIcon name="warning" />
          <span><strong>{t("attachmentUnavailable")}</strong><small>{attachment.mime_type || t("unavailable")}</small></span>
        </div>;
      }
      const hydrated = { ...attachment, ...(previews[attachment.ref] ?? {}) };
      return <div className="timeline-attachment" key={`${entry.id}:${attachment.ref}`}>
        <FileCard
          asset={hydrated}
          onPreview={onPreviewAttachment ? async (mode) => onPreviewAttachment(attachment.ref, mode) : undefined}
          onOpen={onOpenAttachment ? async () => onOpenAttachment(attachment.ref) : undefined}
          onReveal={onRevealAttachment ? async () => onRevealAttachment(attachment.ref) : undefined}
          onCopyPath={onCopyAttachmentPath ? async () => onCopyAttachmentPath(attachment.ref, hydrated.asset_ref) : undefined}
        />
      </div>;
    })}
  </div>;
}

function timelineContentFingerprint(entries: TimelineEntry[], notice: string | null | undefined, runtimeError: string | null | undefined, runtimeErrorVisible: boolean): string {
  return JSON.stringify({
    entries: entries.map((entry) => [entry.id, entry.kind, entry.text, entry.status, entry.streaming, entry.endedAt]),
    notice: notice ?? null,
    runtimeError: runtimeError ?? null,
    runtimeErrorVisible,
  });
}

function attachmentPreviewFingerprint(entries: TimelineEntry[]): string {
  return entries
    .flatMap((entry) => entry.attachments ?? [])
    .filter((attachment): attachment is DesktopAttachmentDraft => !isUnavailableAttachment(attachment) && attachment.mime_type.startsWith("image/") && !attachment.data_url)
    .map((attachment) => `${attachment.ref}:${attachment.mime_type}`)
    .filter((value, index, all) => all.indexOf(value) === index)
    .join("|");
}

export function ChatTimeline({ entries, todo, notice, compactionNotice, compactionAnchor, compactionRunning = false, compactionCompleted = false, onLatestSeen, runtimeError, runtimeErrorVisible = false, onOpenSettings, onCopyText, onOpenArtifact, onDescribeArtifact, onAuthorizeArtifact, onRevealArtifact, onPreviewArtifact, onCopyPath, onOpenDocument, onPreviewAttachment, onOpenAttachment, onRevealAttachment, onCopyAttachmentPath, sessionKey = "default", onLoadOlder, onRetryOlder, historyHasMore = false, historyLoading = false, historyError = null, historyRevision = 0, preparationStatus, processLogs = [], processReaders = {}, onReadProcess, onStopProcess }: ChatTimelineProps) {
  const { t } = useTranslation();
  const [now, setNow] = useState(() => Date.now());
  const [showNewMessages, setShowNewMessages] = useState(false);
  const [artifacts, setArtifacts] = useState<Record<string, ArtifactDescriptor>>({});
  const [attachmentPreviews, setAttachmentPreviews] = useState<Record<string, DesktopAttachmentDraft>>({});
  const timelineRef = useRef<HTMLElement>(null);
  const followTail = useRef(true);
  const previousSessionKey = useRef<string | null>(null);
  const previousContentFingerprint = useRef<string | null>(null);
  const previousHistoryRevision = useRef(historyRevision);
  const prependAnchor = useRef<{ scrollHeight: number; scrollTop: number } | null>(null);
  const attachmentPreviewOwner = useRef(sessionKey);
  const requestedAttachmentPreviews = useRef(new Set<string>());
  const hydratedAttachmentPreviews = useRef(new Set<string>());
  const contentFingerprint = timelineContentFingerprint(entries, JSON.stringify([notice, compactionNotice]), runtimeError, runtimeErrorVisible);
  const attachmentCandidatesKey = attachmentPreviewFingerprint(entries);

  useEffect(() => {
    attachmentPreviewOwner.current = sessionKey;
    requestedAttachmentPreviews.current.clear();
    hydratedAttachmentPreviews.current.clear();
    setArtifacts({});
    setAttachmentPreviews({});
  }, [sessionKey]);

  // History pages carry attachment metadata first. Hydrate only cards entering
  // the visible timeline viewport and guard every response by this Session
  // view so a late preview cannot paint into a newly selected Session.
  useEffect(() => {
    if (!onPreviewAttachment || !attachmentCandidatesKey) return undefined;
    let cancelled = false;
    const ownerSessionKey = sessionKey;
    const pending = new Set<string>();
    const candidates = new Map<string, DesktopAttachmentDraft>();
    for (const entry of entries) {
      for (const attachment of entry.attachments ?? []) {
        if (!isUnavailableAttachment(attachment) && attachment.mime_type.startsWith("image/") && !attachment.data_url && !candidates.has(attachment.ref)) candidates.set(attachment.ref, attachment);
      }
    }
    const load = (attachment: DesktopAttachmentDraft) => {
      if (cancelled || requestedAttachmentPreviews.current.has(attachment.ref) || hydratedAttachmentPreviews.current.has(attachment.ref)) return;
      requestedAttachmentPreviews.current.add(attachment.ref);
      pending.add(attachment.ref);
      void onPreviewAttachment(attachment.ref, "thumbnail").then((preview) => {
        pending.delete(attachment.ref);
        if (!cancelled && attachmentPreviewOwner.current === ownerSessionKey && preview) {
          hydratedAttachmentPreviews.current.add(attachment.ref);
          setAttachmentPreviews((current) => current[attachment.ref] ? current : { ...current, [attachment.ref]: { ...attachment, ...preview } });
        } else if (!preview) {
          requestedAttachmentPreviews.current.delete(attachment.ref);
        }
      }).catch(() => {
        // A missing or expired thumbnail leaves the file fallback and can be
        // retried if the card becomes visible again.
        pending.delete(attachment.ref);
        requestedAttachmentPreviews.current.delete(attachment.ref);
      });
    };
    const observer = typeof IntersectionObserver === "undefined"
      ? null
      : new IntersectionObserver((observations) => {
        for (const observation of observations) {
          if (!observation.isIntersecting) continue;
          const ref = (observation.target as HTMLElement).dataset.fileRef;
          const attachment = ref ? candidates.get(ref) : undefined;
          if (attachment) load(attachment);
        }
      }, { root: timelineRef.current, rootMargin: "160px" });
    if (observer) {
      for (const card of Array.from(timelineRef.current?.querySelectorAll<HTMLElement>(".file-card[data-file-ref]") ?? [])) {
        const attachment = candidates.get(card.dataset.fileRef ?? "");
        if (attachment) observer.observe(card);
      }
    } else {
      // Embedded/test shells without IntersectionObserver have no visibility
      // signal. Load every candidate rather than silently starving later
      // history cards behind an arbitrary prefix limit.
      for (const attachment of candidates.values()) load(attachment);
    }
    return () => {
      cancelled = true;
      for (const ref of pending) requestedAttachmentPreviews.current.delete(ref);
      observer?.disconnect();
    };
  }, [attachmentCandidatesKey, onPreviewAttachment, sessionKey]);

  const describeArtifact = async (path: string): Promise<ArtifactDescriptor | null> => {
    const cached = artifacts[path];
    if (cached) return cached;
    const descriptor = await onDescribeArtifact?.(path);
    if (descriptor) setArtifacts((current) => ({ ...current, [path]: descriptor }));
    return descriptor ?? null;
  };

  const authorizeArtifact = async (path: string): Promise<ArtifactDescriptor | null> => {
    const descriptor = await onAuthorizeArtifact?.(path);
    if (descriptor) setArtifacts((current) => ({ ...current, [descriptor.path]: descriptor }));
    return descriptor ?? null;
  };

  const previewArtifact = async (path: string, mode?: FilePreviewMode): Promise<ArtifactDescriptor | null> => {
    const descriptor = await onPreviewArtifact?.(path, mode);
    if (descriptor) setArtifacts((current) => ({ ...current, [path]: { ...current[path], ...descriptor } }));
    return descriptor ?? null;
  };

  useLayoutEffect(() => {
    const element = timelineRef.current;
    if (!element) return;
    const sessionChanged = previousSessionKey.current !== sessionKey;
    const contentChanged = previousContentFingerprint.current !== contentFingerprint;
    const historyChanged = previousHistoryRevision.current !== historyRevision;
    previousSessionKey.current = sessionKey;
    previousContentFingerprint.current = contentFingerprint;
    previousHistoryRevision.current = historyRevision;
    if (sessionChanged) {
      followTail.current = true;
      setShowNewMessages(false);
      scrollTimelineToBottom(element);
    } else if (historyChanged && prependAnchor.current) {
      const anchor = prependAnchor.current;
      prependAnchor.current = null;
      // Inserting older records increases scrollHeight above the existing
      // viewport. Restore the same first visible pixel instead of jumping.
      element.scrollTop = Math.max(0, anchor.scrollTop + (element.scrollHeight - anchor.scrollHeight));
      setShowNewMessages(false);
    } else if (contentChanged && followTail.current) {
      setShowNewMessages(false);
      scrollTimelineToBottom(element);
    } else if (contentChanged) {
      // A reader who intentionally moved away from the tail keeps their
      // position while streaming/new entries arrive. The explicit button is
      // the only action that re-arms follow-tail.
      setShowNewMessages(true);
    } else if (followTail.current) {
      scrollTimelineToBottom(element);
    }
  }, [contentFingerprint, historyRevision, sessionKey]);
  useEffect(() => {
    const element = timelineRef.current;
    const markSeen = () => {
      if (element && document.visibilityState === "visible" && document.hasFocus() && isNearBottom(element)) onLatestSeen?.();
    };
    const timer = window.setTimeout(markSeen, 0);
    element?.addEventListener("scroll", markSeen);
    window.addEventListener("focus", markSeen);
    document.addEventListener("visibilitychange", markSeen);
    return () => {
      window.clearTimeout(timer);
      element?.removeEventListener("scroll", markSeen);
      window.removeEventListener("focus", markSeen);
      document.removeEventListener("visibilitychange", markSeen);
    };
  }, [onLatestSeen, contentFingerprint, sessionKey]);

  useEffect(() => {
    const element = timelineRef.current;
    if (!element) return undefined;
    let frame = 0;
    const schedule = (callback: FrameRequestCallback) => {
      if (typeof window.requestAnimationFrame === "function") return window.requestAnimationFrame(callback);
      // Test shells and older embedded documents may not expose rAF. There is
      // no ResizeObserver delivery cycle there, so an immediate fallback keeps
      // the existing scroll contract without queuing an unbounded timer.
      callback(Date.now());
      return 0;
    };
    const cancel = (handle: number) => typeof window.cancelAnimationFrame === "function" ? window.cancelAnimationFrame(handle) : window.clearTimeout(handle);
    const syncTail = () => {
      if (frame) return;
      frame = schedule(() => {
        frame = 0;
        if (followTail.current) scrollTimelineToBottom(element);
      });
    };
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(syncTail);
    observer?.observe(element);
    // ResizeObserver covers layout changes from the docked/floating panel. The
    // window listener is only a local geometry update fallback for older shells.
    window.addEventListener("resize", syncTail);
    return () => {
      observer?.disconnect();
      if (frame) cancel(frame);
      window.removeEventListener("resize", syncTail);
    };
  }, []);

  const onScroll = (event: UIEvent<HTMLElement>) => {
    const nearBottom = isNearBottom(event.currentTarget);
    followTail.current = nearBottom;
    if (nearBottom) setShowNewMessages(false);
    if (event.currentTarget.scrollTop <= TIMELINE_NEAR_BOTTOM_THRESHOLD
      && historyHasMore
      && !historyLoading
      && onLoadOlder) {
      prependAnchor.current = {
        scrollHeight: event.currentTarget.scrollHeight,
        scrollTop: event.currentTarget.scrollTop,
      };
      onLoadOlder();
    }
  };

  const retryOlder = () => {
    const element = timelineRef.current;
    if (element) prependAnchor.current = { scrollHeight: element.scrollHeight, scrollTop: element.scrollTop };
    onRetryOlder?.();
  };

  const jumpToLatest = () => {
    const element = timelineRef.current;
    if (!element) return;
    followTail.current = true;
    setShowNewMessages(false);
    scrollTimelineToBottom(element);
  };

  // A Runtime failure has one owner in the rendered tree. If a caller also
  // leaves the same text in the generic status channel, suppress that exact
  // duplicate instead of creating two visual/ARIA entities for one failure.
  const visibleNotice = notice && notice !== runtimeError ? notice : null;
  const compactionIndex = compactionAnchor == null ? -1 : entries.findIndex(entry => entry.id === compactionAnchor.id || (compactionAnchor.messageId && entry.messageId === compactionAnchor.messageId && entry.kind === compactionAnchor.kind));
  const durableCompactionAtAnchor = compactionCompleted
    && compactionIndex >= 0 && entries[compactionIndex + 1]?.kind === "compaction";
  const compactionLine = compactionNotice && (compactionRunning || !durableCompactionAtAnchor) && <p className={`timeline-compaction${compactionRunning ? " is-running" : ""}`} role="status" aria-live="polite">
    {compactionRunning && <span className="compaction-spinner" aria-hidden="true" />}
    <span className="compaction-message">{compactionNotice}</span>
    {compactionRunning && <span className="compaction-dots" aria-hidden="true"><span>.</span><span>.</span><span>.</span></span>}
  </p>;

  useEffect(() => {
    if (!entries.some((entry) => entry.kind === "tool" && entry.status === "running")) return undefined;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [entries]);

  return (
    <section ref={timelineRef} className="timeline" aria-label={t("chatTimeline")} data-session-key={sessionKey} onScroll={onScroll}>
      {runtimeError && !runtimeErrorVisible && <div className="timeline-runtime-error" data-runtime-error-owner="timeline" role="alert">
        <span>{runtimeError}</span>
        {onOpenSettings && <button type="button" onClick={onOpenSettings}>{t("openSettings")}</button>}
      </div>}
      {preparationStatus === "preparing" && <p className="timeline-preparation" role="status">{t("sessionPreparing")}</p>}
      {preparationStatus === "failed" && <p className="timeline-preparation timeline-preparation--failed" role="alert">{t("sessionPreparationFailed")}</p>}
      {historyError && <div className="timeline-history-error" role="alert"><span>{historyError}</span>{onRetryOlder && <button type="button" onClick={retryOlder}>{t("retry")}</button>}</div>}
      {historyLoading && <p className="timeline-history-loading" role="status">{t("loadOlder")}…</p>}
      {historyHasMore && !historyLoading && onLoadOlder && entries.length > 0 && <button type="button" className="timeline-load-older" onClick={() => { const element = timelineRef.current; if (element) prependAnchor.current = { scrollHeight: element.scrollHeight, scrollTop: element.scrollTop }; onLoadOlder(); }}>{t("loadOlder")}</button>}
      {visibleNotice && <p id="composer-state" className="timeline-notice" role="status">{localText(visibleNotice, t)}</p>}
      {showNewMessages && <button type="button" className="timeline-new-messages" data-new-messages="true" aria-label={t("jumpToLatest")} title={t("jumpToLatest")} onClick={jumpToLatest}>{t("newMessages")}</button>}
      {entries.length === 0 && <div className="timeline-empty"><span>U</span><p>{t("emptyConversation")}</p></div>}
      {processLogs.length > 0 && <details className="timeline-process-log" data-process-log="true">
        <summary>Process logs ({processLogs.length})</summary>
        <div className="timeline-process-log__body">
          {Array.from(new Set(processLogs.map((entry) => entry.processId))).map((processId) => {
            const reader = processReaders[processId];
            const processEntries = processLogs.filter((entry) => entry.processId === processId);
            return <section className="timeline-process-log__process" key={processId} data-process-session={sessionKey} data-process-owner={processId}>
              <header><strong>{processId.slice(0, 8)}</strong>{reader?.state && <span>{reader.state}</span>}{onReadProcess && <>
                <button type="button" onClick={() => onReadProcess(processId, reader?.nextCursor ?? (processEntries.at(-1)?.nextCursor ?? 0))} disabled={reader?.loading === true}>{reader?.loading ? "Reading…" : "Read newer"}</button>
                {(reader?.earliestCursor ?? 0) > 0 && <button type="button" onClick={() => onReadProcess(processId, 0)} disabled={reader?.loading === true}>Load earliest</button>}
              </>}{onStopProcess && reader?.state === "running" && <button type="button" onClick={() => onStopProcess(processId)}>Stop</button>}</header>
              {reader?.cursorExpired && <p className="timeline-process-log__notice" role="status">Cursor expired; earliest cursor: {reader.earliestCursor}. Read from the earliest available output.</p>}
              {reader?.expired && <p className="timeline-process-log__notice" role="status">Process output expired from the Session quota.</p>}
              {reader?.error && <p className="timeline-process-log__notice" role="alert">{reader.error}</p>}
              {processEntries.map((entry) => <pre key={`${entry.processId}:${entry.sequence}`} data-process-id={entry.processId} data-process-sequence={entry.sequence}>{entry.text || `[${entry.stream}] ${entry.state ?? ""}`}</pre>)}
            </section>;
          })}
        </div>
      </details>}
      {compactionAnchor === null && !historyHasMore && compactionLine}
      {entries.map((entry, index) => {
        if (entry.kind === "compaction") return <Fragment key={entry.id}><p className="timeline-compaction" role="status">{t("contextCompacted")}</p>{index === compactionIndex && compactionLine}</Fragment>;
        const status = entry.status || "running";
        const elapsed = entry.kind === "tool" ? elapsedSeconds(entry, now) : null;
        return <Fragment key={entry.id}><article className={`timeline-entry timeline-entry--${entry.kind}${entry.kind === "tool" && status === "running" ? " is-running" : ""}`} aria-label={`${entryLabel(entry, t)}${entry.kind === "tool" ? `: ${localText(status, t)}` : ""}`} aria-busy={entry.streaming || status === "running" || undefined}>
          <header><span>{entryLabel(entry, t)}</span>{entry.kind === "tool" && <small className="tool-status" data-status={status} data-error={entry.isError || undefined}><UiIcon name={toolStatusIcon(status)} /><span>{localText(status, t)}</span>{elapsed !== null && <span className="tool-elapsed" aria-label={`${elapsed}s`}> · {elapsed}s</span>}</small>}{entry.streaming && <small>{t("writing")}</small>}</header>
          <div className="timeline-content">{entry.kind === "user" && renderAttachmentRows(entry, t, attachmentPreviews, onPreviewAttachment, onOpenAttachment, onRevealAttachment, onCopyAttachmentPath)}{entry.kind === "tool" ? <p><span className="tool-summary-icon" aria-hidden="true"><UiIcon name={toolStatusIcon(status)} /></span><span>{entry.text}</span><span className="sr-only"> · {localText(status, t)}{elapsed !== null ? ` · ${elapsed}s` : ""}</span></p> : entry.kind === "status" ? renderMarkdown(localText(entry.text, t), { onCopyText, onOpenArtifact, onDescribeArtifact: describeArtifact, onAuthorizeArtifact: authorizeArtifact, authorizeArtifactLabel: t("artifactAuthorize"), onRevealArtifact, onPreviewArtifact: previewArtifact, onOpenDocument, onCopyPath, artifacts }) : renderMarkdown(entry.text, { onCopyText, onOpenArtifact, onDescribeArtifact: describeArtifact, onAuthorizeArtifact: authorizeArtifact, authorizeArtifactLabel: t("artifactAuthorize"), onRevealArtifact, onPreviewArtifact: previewArtifact, onOpenDocument, onCopyPath, artifacts })}{entry.kind !== "user" && renderAttachmentRows(entry, t, attachmentPreviews, onPreviewAttachment, onOpenAttachment, onRevealAttachment, onCopyAttachmentPath)}</div>
        </article>{index === compactionIndex && compactionLine}</Fragment>;
      })}
      {todo.length > 0 && <section className="todo-strip" tabIndex={0} aria-label={t("tasks")}><header><h2><UiIcon name="todo" />{t("tasks")}</h2><span className="todo-strip__count">{todo.filter((item) => item.status === "completed").length}/{todo.length}</span></header><ul>{todo.map((item, index) => <li key={`${item.content}-${index}`} data-status={item.status} title={item.content} aria-label={`${item.content}: ${todoStatusLabel(item.status, t)}`}><span className="todo-status-icon" aria-hidden="true"><UiIcon name={item.status === "completed" ? "check" : item.status === "in_progress" ? "status" : "todo"} /></span><span>{item.content}</span><span className="sr-only">{todoStatusLabel(item.status, t)}</span></li>)}</ul></section>}
    </section>
  );
}
