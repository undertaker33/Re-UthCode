import { useEffect, useLayoutEffect, useRef, useState, type UIEvent } from "react";
import type { TimelineEntry, TodoItem } from "./state";
import { useTranslation, type TranslationKey } from "./i18n";
import { UiIcon, type UiIconName } from "./UiIcon";
import { renderMarkdown } from "./safe-markdown";

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
  /** Runtime errors are rendered here only when RuntimePanel is not visible. */
  runtimeError?: string | null;
  runtimeErrorVisible?: boolean;
  onOpenSettings?: () => void;
  /** Narrow main-process clipboard adapter shared with Session ID copy. */
  onCopyText?: (text: string) => Promise<void>;
  /** Changes only when a Session/Project view is replaced, not on streaming. */
  sessionKey?: string;
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

function timelineContentFingerprint(entries: TimelineEntry[], notice: string | null | undefined, runtimeError: string | null | undefined, runtimeErrorVisible: boolean): string {
  return JSON.stringify({
    entries: entries.map((entry) => [entry.id, entry.kind, entry.text, entry.status, entry.streaming, entry.endedAt]),
    notice: notice ?? null,
    runtimeError: runtimeError ?? null,
    runtimeErrorVisible,
  });
}

export function ChatTimeline({ entries, todo, notice, runtimeError, runtimeErrorVisible = false, onOpenSettings, onCopyText, sessionKey = "default" }: ChatTimelineProps) {
  const { t } = useTranslation();
  const [now, setNow] = useState(() => Date.now());
  const [showNewMessages, setShowNewMessages] = useState(false);
  const timelineRef = useRef<HTMLElement>(null);
  const followTail = useRef(true);
  const previousSessionKey = useRef<string | null>(null);
  const previousContentFingerprint = useRef<string | null>(null);
  const contentFingerprint = timelineContentFingerprint(entries, notice, runtimeError, runtimeErrorVisible);

  useLayoutEffect(() => {
    const element = timelineRef.current;
    if (!element) return;
    const sessionChanged = previousSessionKey.current !== sessionKey;
    const contentChanged = previousContentFingerprint.current !== contentFingerprint;
    previousSessionKey.current = sessionKey;
    previousContentFingerprint.current = contentFingerprint;
    if (sessionChanged) {
      followTail.current = true;
      setShowNewMessages(false);
      scrollTimelineToBottom(element);
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
  }, [contentFingerprint, sessionKey]);

  useEffect(() => {
    const element = timelineRef.current;
    if (!element) return undefined;
    const syncTail = () => {
      if (followTail.current) scrollTimelineToBottom(element);
    };
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(syncTail);
    observer?.observe(element);
    // ResizeObserver covers layout changes from the docked/floating panel. The
    // window listener is only a local geometry update fallback for older shells.
    window.addEventListener("resize", syncTail);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", syncTail);
    };
  }, []);

  const onScroll = (event: UIEvent<HTMLElement>) => {
    const nearBottom = isNearBottom(event.currentTarget);
    followTail.current = nearBottom;
    if (nearBottom) setShowNewMessages(false);
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
      {visibleNotice && <p className="timeline-notice" role="status">{localText(visibleNotice, t)}</p>}
      {showNewMessages && <button type="button" className="timeline-new-messages" data-new-messages="true" aria-label={t("jumpToLatest")} title={t("jumpToLatest")} onClick={jumpToLatest}>{t("newMessages")}</button>}
      {entries.length === 0 && <div className="timeline-empty"><span>U</span><p>{t("emptyConversation")}</p></div>}
      {entries.map((entry) => {
        const status = entry.status || "running";
        const elapsed = entry.kind === "tool" ? elapsedSeconds(entry, now) : null;
        return <article key={entry.id} className={`timeline-entry timeline-entry--${entry.kind}${entry.kind === "tool" && status === "running" ? " is-running" : ""}`} aria-label={`${entryLabel(entry, t)}${entry.kind === "tool" ? `: ${localText(status, t)}` : ""}`} aria-busy={entry.streaming || status === "running" || undefined}>
          <header><span>{entryLabel(entry, t)}</span>{entry.kind === "tool" && <small className="tool-status" data-status={status} data-error={entry.isError || undefined}><UiIcon name={toolStatusIcon(status)} /><span>{localText(status, t)}</span>{elapsed !== null && <span className="tool-elapsed" aria-label={`${elapsed}s`}> · {elapsed}s</span>}</small>}{entry.streaming && <small>{t("writing")}</small>}</header>
          <div className="timeline-content">{entry.kind === "tool" ? <p><span className="tool-summary-icon" aria-hidden="true"><UiIcon name={toolStatusIcon(status)} /></span><span>{entry.text}</span><span className="sr-only"> · {localText(status, t)}{elapsed !== null ? ` · ${elapsed}s` : ""}</span></p> : entry.kind === "status" ? renderMarkdown(localText(entry.text, t), { onCopyText }) : renderMarkdown(entry.text, { onCopyText })}</div>
        </article>;
      })}
      {todo.length > 0 && <section className="todo-strip" tabIndex={0} aria-label={t("tasks")}><header><h2><UiIcon name="todo" />{t("tasks")}</h2><span className="todo-strip__count">{todo.filter((item) => item.status === "completed").length}/{todo.length}</span></header><ul>{todo.map((item, index) => <li key={`${item.content}-${index}`} data-status={item.status} title={item.content} aria-label={`${item.content}: ${todoStatusLabel(item.status, t)}`}><span className="todo-status-icon" aria-hidden="true"><UiIcon name={item.status === "completed" ? "check" : item.status === "in_progress" ? "status" : "todo"} /></span><span>{item.content}</span><span className="sr-only">{todoStatusLabel(item.status, t)}</span></li>)}</ul></section>}
    </section>
  );
}
