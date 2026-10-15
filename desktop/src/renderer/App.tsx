import { useCallback, useEffect, useLayoutEffect, useReducer, useRef, useState, type CSSProperties, type PointerEvent as ReactPointerEvent, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { isDesktopCommandResult } from "../desktop-api";
import {
  DEFAULT_RUNTIME_PANEL_WIDTH,
  DEFAULT_SIDEBAR_WIDTH,
  RUNTIME_PANEL_WIDTH_MAX,
  RUNTIME_PANEL_WIDTH_MIN,
  SIDEBAR_WIDTH_MAX,
  SIDEBAR_WIDTH_MIN,
} from "../desktop-api";
import type { AgentEvent, ArtifactDescriptor, DesktopApi, DesktopAttachmentDraft, DesktopAttachmentInput, DesktopPreferences, JsonObject, JsonValue, LanguagePreference, PanelModePreference, ThemePreference, TimelineAttachment } from "../desktop-api";
import { ChatTimeline } from "./ChatTimeline";
import { Composer } from "./Composer";
import { type FilePreviewMode } from "./FileCard";
import { ReviewPanel, type DocumentPreview, type DocumentPreviewOwner, type ReviewPanelTab, type WorkspaceDiffView } from "./DocumentPreviewPanel";
import { RendererErrorBoundary } from "./RendererErrorBoundary";
import { RuntimePanel } from "./RuntimePanel";
import { Sidebar, type SessionSearchHit } from "./Sidebar";
import { InteractionSurface, interactionSurfaceKey } from "./InteractionSurface";
import { SettingsView, type ArchivedSettingsSession, type ConfigurationWrite, type PendingConfigurationWrite } from "./SettingsView";
import { configurationWriteIdentities } from "./settings-draft";
import { composerDraftOwnerKey, createInitialState, reduceRendererState, type RendererAction, type RendererState, type ProjectState, type SessionSummary, type ConfigurationView, type PendingInteraction } from "./state";
import {
  eventIdentity,
  eventMatchesIdentity,
  hasCompleteTurnIdentity,
  hasTurnIdentity,
  identityFromRun,
  knownIdentityMatches,
  RuntimeOperationCancelled,
  StaleRuntimeOperation,
  stringValue,
  useRuntimeLifecycle,
  type RuntimeOwnershipCheck,
} from "./useRuntimeLifecycle";
import { sessionRuntimeKey, type SessionOrderReason } from "./state-session";
import { UiIcon } from "./UiIcon";
import { LanguageProvider, translate } from "./i18n";

export interface AppProps {
  api?: DesktopApi;
  initialState?: RendererState;
}

const RUNTIME_PANEL_ID = "runtime-panel";
export const CONVERSATION_MIN_WIDTH = 240;

export interface LayoutWidthBounds {
  sidebar: { min: number; max: number };
  runtime: { min: number; max: number };
}

export function clampLayoutWidth(value: number, bounds: { min: number; max: number }): number {
  if (!Number.isFinite(value)) return bounds.min;
  return Math.round(Math.min(bounds.max, Math.max(bounds.min, value)));
}

/** Calculate CSS-pixel limits while leaving a readable Conversation column. */
export function layoutWidthBounds(
  viewportWidth: number,
  panelMode: PanelModePreference,
  sidebarWidth = DEFAULT_SIDEBAR_WIDTH,
  runtimePanelWidth = DEFAULT_RUNTIME_PANEL_WIDTH,
): LayoutWidthBounds {
  const viewport = Number.isFinite(viewportWidth) ? Math.max(0, viewportWidth) : 1280;
  const runtimeBudget = panelMode === "docked"
    ? viewport - SIDEBAR_WIDTH_MIN - CONVERSATION_MIN_WIDTH
    : viewport - 16;
  const runtimeMax = Math.min(RUNTIME_PANEL_WIDTH_MAX, Math.max(RUNTIME_PANEL_WIDTH_MIN, runtimeBudget));
  const runtime = clampLayoutWidth(runtimePanelWidth, { min: RUNTIME_PANEL_WIDTH_MIN, max: runtimeMax });
  const sidebarBudget = viewport - CONVERSATION_MIN_WIDTH - (panelMode === "docked" ? runtime : 0);
  const sidebarMax = Math.min(SIDEBAR_WIDTH_MAX, Math.max(SIDEBAR_WIDTH_MIN, sidebarBudget));
  const sidebar = clampLayoutWidth(sidebarWidth, { min: SIDEBAR_WIDTH_MIN, max: sidebarMax });
  // A very narrow wide-mode viewport may leave no room for both minimums. In
  // that case the explicit narrow media query takes over at 680 CSS pixels;
  // keeping the bounded values here prevents a negative grid track.
  const finalRuntimeBudget = panelMode === "docked"
    ? viewport - sidebar - CONVERSATION_MIN_WIDTH
    : viewport - 16;
  const finalRuntimeMax = Math.min(RUNTIME_PANEL_WIDTH_MAX, Math.max(RUNTIME_PANEL_WIDTH_MIN, finalRuntimeBudget));
  return {
    sidebar: { min: SIDEBAR_WIDTH_MIN, max: sidebarMax },
    runtime: { min: RUNTIME_PANEL_WIDTH_MIN, max: finalRuntimeMax },
  };
}

export function clampedLayoutWidths(
  viewportWidth: number,
  panelMode: PanelModePreference,
  sidebarWidth: number,
  runtimePanelWidth: number,
): { sidebarWidth: number; runtimePanelWidth: number } {
  const bounds = layoutWidthBounds(viewportWidth, panelMode, sidebarWidth, runtimePanelWidth);
  const nextSidebar = clampLayoutWidth(sidebarWidth, bounds.sidebar);
  const nextRuntime = clampLayoutWidth(runtimePanelWidth, bounds.runtime);
  return { sidebarWidth: nextSidebar, runtimePanelWidth: nextRuntime };
}

interface ResizeSeparatorProps {
  side: "sidebar" | "runtime";
  value: number;
  bounds: { min: number; max: number };
  label: string;
  disabled?: boolean;
  onPreview: (value: number) => void;
  onCommit: (value: number) => void;
}

function ResizeSeparator({ side, value, bounds, label, disabled = false, onPreview, onCommit }: ResizeSeparatorProps) {
  const drag = useRef<{ pointerId: number; origin: number; originValue: number; lastValue: number } | null>(null);
  const valueForPointer = (clientX: number) => clampLayoutWidth(side === "sidebar"
    ? (drag.current?.originValue ?? value) + (clientX - (drag.current?.origin ?? clientX))
    : (drag.current?.originValue ?? value) - (clientX - (drag.current?.origin ?? clientX)), bounds);
  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (disabled || event.button !== 0) return;
    event.preventDefault();
    drag.current = { pointerId: event.pointerId, origin: event.clientX, originValue: value, lastValue: value };
    try { event.currentTarget.setPointerCapture(event.pointerId); } catch { /* jsdom and older WebViews may not implement capture */ }
  };
  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!drag.current || drag.current.pointerId !== event.pointerId) return;
    const next = valueForPointer(event.clientX);
    drag.current.lastValue = next;
    onPreview(next);
  };
  const finishPointer = (event: ReactPointerEvent<HTMLDivElement>, commit: boolean) => {
    if (!drag.current || drag.current.pointerId !== event.pointerId) return;
    const current = drag.current;
    drag.current = null;
    try { event.currentTarget.releasePointerCapture(event.pointerId); } catch { /* capture is optional */ }
    if (commit) onCommit(current.lastValue);
  };
  const onKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (disabled) return;
    const step = event.shiftKey ? 48 : 16;
    let next: number | null = null;
    if (event.key === "Home") next = bounds.min;
    else if (event.key === "End") next = bounds.max;
    else if (side === "sidebar" && event.key === "ArrowLeft") next = value - step;
    else if (side === "sidebar" && event.key === "ArrowRight") next = value + step;
    else if (side === "runtime" && event.key === "ArrowLeft") next = value + step;
    else if (side === "runtime" && event.key === "ArrowRight") next = value - step;
    if (next === null) return;
    event.preventDefault();
    const clamped = clampLayoutWidth(next, bounds);
    onPreview(clamped);
    onCommit(clamped);
  };
  return <div
    className={`layout-separator layout-separator--${side}`}
    role="separator"
    aria-orientation="vertical"
    aria-label={label}
    aria-valuemin={bounds.min}
    aria-valuemax={bounds.max}
    aria-valuenow={value}
    aria-controls="workspace-main"
    aria-disabled={disabled || undefined}
    data-resize-side={side}
    tabIndex={disabled ? -1 : 0}
    onPointerDown={onPointerDown}
    onPointerMove={onPointerMove}
    onPointerUp={(event) => finishPointer(event, true)}
    onPointerCancel={(event) => finishPointer(event, false)}
    onKeyDown={onKeyDown}
  />;
}

function runtimeApi(explicit?: DesktopApi): DesktopApi | undefined {
  if (explicit) return explicit;
  if (typeof window !== "undefined" && window.uthcode) return window.uthcode;
  return undefined;
}

function asObject(value: unknown): JsonObject {
  if (value && typeof value === "object" && !Array.isArray(value)) return value as JsonObject;
  return {};
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, Math.min(offset + chunkSize, bytes.length)));
  }
  return btoa(binary);
}

function attachmentDraftFromResult(value: unknown): DesktopAttachmentDraft | null {
  const source = asObject(value);
  const ref = stringValue(source.ref);
  const displayName = stringValue(source.display_name) || stringValue(source.name);
  const mimeType = stringValue(source.mime_type);
  const sizeBytes = typeof source.size_bytes === "number" && Number.isSafeInteger(source.size_bytes) && source.size_bytes >= 0 ? source.size_bytes : null;
  if (!ref || !displayName || !mimeType || sizeBytes === null) return null;
  const width = typeof source.width === "number" && Number.isSafeInteger(source.width) && source.width > 0 ? source.width : null;
  const height = typeof source.height === "number" && Number.isSafeInteger(source.height) && source.height > 0 ? source.height : null;
  const dataUrl = typeof source.data_url === "string" && /^data:[^,]+,/.test(source.data_url) ? source.data_url : undefined;
  const assetRef = stringValue(source.asset_ref);
  const type = stringValue(source.type);
  const previewKind = stringValue(source.preview_kind);
  const previewText = typeof source.text === "string" ? source.text : undefined;
  return {
    ...(type ? { type } : {}),
    ...(source.available === true ? { available: true as const } : {}),
    ref,
    ...(assetRef ? { asset_ref: assetRef } : {}),
    display_name: displayName,
    mime_type: mimeType,
    size_bytes: sizeBytes,
    ...(width !== null ? { width } : {}),
    ...(height !== null ? { height } : {}),
    ...(previewKind ? { preview_kind: previewKind } : {}),
    ...(previewText !== undefined ? { text: previewText } : {}),
    ...(source.truncated === true ? { truncated: true } : {}),
    ...(dataUrl ? { data_url: dataUrl } : {}),
  };
}

function timelineAttachmentFromDraft(attachment: DesktopAttachmentDraft): TimelineAttachment {
  return {
    ref: attachment.ref,
    ...(attachment.asset_ref ? { asset_ref: attachment.asset_ref } : {}),
    display_name: attachment.display_name,
    mime_type: attachment.mime_type,
    size_bytes: attachment.size_bytes,
    ...(attachment.width !== undefined && attachment.width !== null ? { width: attachment.width } : {}),
    ...(attachment.height !== undefined && attachment.height !== null ? { height: attachment.height } : {}),
  };
}

function workspaceDiffFromEvent(value: unknown, expectedProjectKey: string): WorkspaceDiffView | null {
  const source = asObject(value);
  const status = asObject(source.status);
  const staged = asObject(source.staged_diff);
  const unstaged = asObject(source.unstaged_diff);
  if (source.source !== "current_working_tree"
    || source.project_key !== expectedProjectKey
    || typeof source.viewed_at !== "string"
    || !Number.isFinite(Date.parse(source.viewed_at))
    || typeof status.unborn !== "boolean"
    || typeof status.truncated !== "boolean"
    || !Array.isArray(status.entries)
    || typeof staged.text !== "string"
    || typeof staged.truncated !== "boolean"
    || !Number.isSafeInteger(staged.size_bytes) || (staged.size_bytes as number) < 0
    || typeof unstaged.text !== "string"
    || typeof unstaged.truncated !== "boolean"
    || !Number.isSafeInteger(unstaged.size_bytes) || (unstaged.size_bytes as number) < 0
    || typeof source.truncated !== "boolean") return null;
  if (status.branch !== null && typeof status.branch !== "string") return null;
  const entries = status.entries.flatMap((value): WorkspaceDiffView["status"]["entries"] => {
    const entry = asObject(value);
    if (typeof entry.xy !== "string" || typeof entry.path !== "string" || !entry.path) return [];
    if (entry.original_path !== undefined && typeof entry.original_path !== "string") return [];
    if (entry.review_error !== undefined && entry.review_error !== "unavailable") return [];
    return [{ xy: entry.xy, path: entry.path, ...(typeof entry.original_path === "string" ? { original_path: entry.original_path } : {}), ...(entry.review_error === "unavailable" ? { review_error: "unavailable" as const } : {}) }];
  });
  if (entries.length !== status.entries.length) return null;
  return {
    source: "current_working_tree",
    project_key: expectedProjectKey,
    viewed_at: source.viewed_at,
    status: { branch: typeof status.branch === "string" ? status.branch : null, entries, unborn: status.unborn, truncated: status.truncated },
    staged_diff: { text: staged.text, truncated: staged.truncated, size_bytes: staged.size_bytes as number },
    unstaged_diff: { text: unstaged.text, truncated: unstaged.truncated, size_bytes: unstaged.size_bytes as number },
    truncated: source.truncated,
  };
}

interface PendingProcessPermission {
  projectKey: string;
  sessionId: string;
  processId: string;
  request: JsonObject;
  submitting: boolean;
}

interface PendingModelImageSwitch {
  generation: number;
  mode: RendererState["mode"];
  projectKey: string | null;
  sessionId: string;
  viewRevision: number;
  modelRef: string;
  operationId: string | null;
  handling: "placeholder" | "summarize" | null;
  busy: boolean;
  error: string | null;
}

interface SessionSearchContext {
  sequence: number;
  operationId: string;
  ownerKey: string;
  mode: RendererState["mode"];
  projectKey: string;
  sessionId: string | null;
  sessionViewRevision: number;
  runtimeGeneration: number;
}

interface WorkspaceDiffContext {
  sequence: number;
  operationId: string | null;
  ownerKey: string;
  owner: DocumentPreviewOwner & { ownerKey: string };
  tabId: string;
}

interface WorkspaceDiffSummaryContext {
  sequence: number;
  operationId: string | null;
  ownerKey: string;
  owner: DocumentPreviewOwner & { ownerKey: string };
  requestKey: string;
}

interface WorkspaceDiffSummaryState {
  owner: DocumentPreviewOwner & { ownerKey: string };
  requestKey: string;
  state: "reviewing" | "completed" | "failed";
  diff?: WorkspaceDiffView;
}

interface ReviewPanelState {
  tabs: ReviewPanelTab[];
  activeTabId: string | null;
}

interface SessionSearchView {
  results: SessionSearchHit[];
  pending: boolean;
  error: boolean;
}

const GENERAL_PROJECT_KEY = "uthcode:general";

function processPermissionFromResult(value: unknown, projectKey: string, sessionId: string, processId: string): PendingProcessPermission | null {
  const permission = asObject(asObject(value).permission_required);
  const permissionId = stringValue(permission.permission_id);
  const choices = Array.isArray(permission.choices)
    ? permission.choices.filter((choice): choice is string => typeof choice === "string" && choice.length > 0)
    : [];
  if (!permissionId || choices.length === 0) return null;
  const request: JsonObject = { permission_id: permissionId, choices };
  for (const key of ["tool", "action", "reason", "run_id", "turn_id", "tool_call_id"] as const) {
    if (typeof permission[key] === "string") request[key] = permission[key];
  }
  return { projectKey, sessionId, processId, request, submitting: false };
}

function runtimeRequestKind(error: unknown): string {
  if (!error || typeof error !== "object") return "";
  const kind = (error as { kind?: unknown }).kind;
  return typeof kind === "string" ? kind : "";
}

function runtimeBusinessErrorKind(value: unknown): string {
  const payload = asObject(asObject(value).__uthcode_runtime_error);
  return stringValue(payload.kind);
}

/**
 * Project every failed Desktop call to a renderer-owned localized message.
 *
 * Main/transport errors deliberately retain their internal kind and message
 * for diagnostics, and a RuntimeRequestError may include an IPC method,
 * native exception class, or filesystem detail.  None of those values are a
 * renderer contract.  Call sites already provide the action-specific,
 * localized fallback, so an unknown failure must never be promoted to UI.
 */
export function safeErrorMessage(_error: unknown, fallback: string): string {
  return fallback;
}

/**
 * Translate the Bridge's semantic command result without ever consuming
 * Application output/error text.  Params are used only as typed flags; the
 * visible copy remains owned by the current Renderer locale.
 */
export function commandResultNotice(
  value: unknown,
  localize: (key: Parameters<typeof translate>[1]) => string,
): string | null {
  const source = asObject(value);
  const code = stringValue(source.code);
  switch (code) {
    case "status_ready":
      return localize("runtimeInformation");
    case "help_ready":
      return localize("commandHelp");
    case "compact_started":
    case "compact_completed":
    case "compact_no_change":
    case "compact_cancelled":
    case "compact_failed":
      // Compaction status and its durable timeline row own these outcomes.
      return null;
    case "session_created":
      return null;
    case "session_resumed":
      // Session resume is navigation; do not leave a persistent success
      // notice in the Composer after every ordinary Session selection.
      return null;
    case "model_selected":
    case "behavior_mode_selected":
      return null;
    case "permission_mode_selected": {
      const params = asObject(source.params);
      return params.warning === true
        ? localize("commandPermissionWarning")
        : null;
    }
    case "model_picker_opened":
    case "permission_picker_opened":
    case "session_picker_opened":
      return null;
    case "transcript_cleared":
      return null;
    case "command_unavailable":
    case "command_usage_error":
    case "command_failed":
      return localize("commandFailed");
    case "interface_quit":
      return null;
    case "command_completed":
      return localize("commandCompleted");
    default:
      // A future Bridge code must remain safe and localized even before this
      // Renderer version learns its detailed presentation.
      return source.status === "success" ? localize("commandCompleted") : localize("commandFailed");
  }
}

function projectPreferences(projects: ProjectState[]): DesktopPreferences["recentProjects"] {
  return projects.filter((project) => project.projectKey !== "uthcode:general").map((project) => ({
    path: project.path,
    alias: project.alias,
    pinned: project.pinned,
    ...(project.lastOpenedAt ? { lastOpenedAt: project.lastOpenedAt } : {}),
  }));
}

/** Remove every Desktop-local reference to a project without touching disk. */
export function projectNavigationPreferences(
  projects: readonly ProjectState[],
  pinnedSessions: DesktopPreferences["pinnedSessions"],
  expandedProjects: DesktopPreferences["expandedProjects"] = {},
): Pick<DesktopPreferences, "recentProjects" | "projectAliases" | "pinnedProjectKeys" | "pinnedSessions" | "expandedProjects"> {
  const projectKeys = new Set(projects.map((project) => project.projectKey));
  return {
    recentProjects: projectPreferences([...projects]),
    projectAliases: Object.fromEntries(projects.map((project) => [project.projectKey, project.alias])),
    pinnedProjectKeys: projects.filter((project) => project.pinned).map((project) => project.projectKey),
    pinnedSessions: pinnedSessions.filter((item) => projectKeys.has(item.projectKey)),
    expandedProjects: Object.fromEntries(Object.entries(expandedProjects).filter(([projectKey]) => projectKeys.has(projectKey))),
  };
}

export function projectRemovalPlan(projects: readonly ProjectState[], selectedProjectKey: string | null, removedProjectKey: string): {
  remaining: ProjectState[];
  current: boolean;
  replacement: ProjectState | null;
} {
  const remaining = projects.filter((project) => project.projectKey !== removedProjectKey);
  return {
    remaining,
    current: selectedProjectKey === removedProjectKey,
    replacement: remaining[0] ?? null,
  };
}

export function projectPinPlan(projects: readonly ProjectState[], pinnedSessions: DesktopPreferences["pinnedSessions"], projectKey: string) {
  const projectsNext = projects.map((item) => item.projectKey === projectKey ? { ...item, pinned: !item.pinned } : item);
  const pinned = projectsNext.find((item) => item.projectKey === projectKey)?.pinned === true;
  return { projects: projectsNext, pinnedSessions: pinned ? pinnedSessions.filter((item) => item.projectKey !== projectKey) : [...pinnedSessions] };
}

export function App({ api: explicitApi, initialState }: AppProps) {
  const [state, dispatch] = useReducer(reduceRendererState, initialState ?? createInitialState());
  const stateRef = useRef(state);
  stateRef.current = state;
  const api = runtimeApi(explicitApi);
  const [narrowViewport, setNarrowViewport] = useState(() => typeof window !== "undefined" && window.innerWidth <= 680);
  const [viewportWidth, setViewportWidth] = useState(() => typeof window !== "undefined" ? window.innerWidth : 1280);
  const narrowViewportRef = useRef(narrowViewport);
  const runtimeToggleRef = useRef<HTMLButtonElement>(null);
  const focusModeToggleRef = useRef<HTMLButtonElement>(null);
  const runtimeFocusHandoffRef = useRef(false);
  const settingsSaveInFlightRef = useRef(false);
  const settingsSaveCountRef = useRef(0);
  const settingsSaveTailRef = useRef<Promise<void>>(Promise.resolve());
  const settingsRequestRevisionRef = useRef(0);
  const settingsWriteRevisionsRef = useRef(new Map<string, number>());
  const settingsFailedWritesRef = useRef(new Map<string, PendingConfigurationWrite>());
  const sessionMutationGenerationRef = useRef(0);
  const sessionMutationSequenceRef = useRef(0);
  const sessionMutationInFlightRef = useRef<number | null>(null);
  const commandInFlightRef = useRef(false);
  const interactionSubmitRef = useRef<string | null>(null);
  const cancelInFlightRef = useRef(false);
  const [pendingProcessPermission, setPendingProcessPermission] = useState<PendingProcessPermission | null>(null);
  const [pendingModelImageSwitch, setPendingModelImageSwitch] = useState<PendingModelImageSwitch | null>(null);
  const [reviewPanel, setReviewPanel] = useState<ReviewPanelState>({ tabs: [], activeTabId: null });
  const reviewPanelRef = useRef(reviewPanel);
  reviewPanelRef.current = reviewPanel;
  const [workspaceDiffSummary, setWorkspaceDiffSummary] = useState<WorkspaceDiffSummaryState | null>(null);
  const [documentPreviewWidth, setDocumentPreviewWidth] = useState(460);
  const pendingProcessPermissionRef = useRef<PendingProcessPermission | null>(null);
  const pendingModelImageSwitchRef = useRef<PendingModelImageSwitch | null>(null);
  const modelSwitchSequenceRef = useRef(0);
  const processStopInFlightRef = useRef<string | null>(null);
  const processPermissionSubmitRef = useRef<string | null>(null);
  const processPermissionReleaseRef = useRef<string | null>(null);
  const runtimeStatusPollRef = useRef<Promise<boolean> | null>(null);
  const [sessionSearch, setSessionSearch] = useState<SessionSearchView>({ results: [], pending: false, error: false });
  const sessionSearchSequenceRef = useRef(0);
  const sessionSearchContextRef = useRef<SessionSearchContext | null>(null);
  const earlySessionSearchEventsRef = useRef<Map<string, AgentEvent>>(new Map());
  const workspaceDiffSequenceRef = useRef(0);
  const workspaceDiffContextRef = useRef<WorkspaceDiffContext | null>(null);
  const earlyWorkspaceDiffEventsRef = useRef<Map<string, AgentEvent>>(new Map());
  const workspaceDiffSummarySequenceRef = useRef(0);
  const workspaceDiffSummaryContextRef = useRef<WorkspaceDiffSummaryContext | null>(null);
  const earlyWorkspaceDiffSummaryEventsRef = useRef<Map<string, AgentEvent>>(new Map());
  const workspaceDiffSummaryRefreshTimerRef = useRef<number | null>(null);
  const workspaceDiffSummaryRequestKeyRef = useRef<string | null>(null);
  const workspaceDiffSummaryOwnerRef = useRef<string | null>(null);
  const historyRequestsRef = useRef<Map<string, { token: symbol; promise: Promise<void> }>>(new Map());
  const projectCatalogRequestSequenceRef = useRef(new Map<string, number>());
  const projectCatalogAppliedSequenceRef = useRef(new Map<string, number>());
  const preparationPollSequenceRef = useRef(0);
  const preparationPollRef = useRef<Map<string, number>>(new Map());
  const t = useCallback((key: Parameters<typeof translate>[1]) => translate(stateRef.current.language, key), []);
  const updateReviewPanel = useCallback((update: (current: ReviewPanelState) => ReviewPanelState) => {
    const next = update(reviewPanelRef.current);
    reviewPanelRef.current = next;
    setReviewPanel(next);
  }, []);
  const updateReviewTab = useCallback((id: string, update: (tab: ReviewPanelTab) => ReviewPanelTab) => {
    updateReviewPanel((current) => ({
      ...current,
      tabs: current.tabs.map((tab) => tab.id === id ? update(tab) : tab),
    }));
  }, [updateReviewPanel]);

  const send = useCallback(async (method: Parameters<DesktopApi["requestRuntime"]>[0], params: JsonObject = {}) => {
    if (!api) throw new Error(t("desktopApiUnavailable"));
    const result = await api.requestRuntime(method, params);
    const businessKind = runtimeBusinessErrorKind(result);
    if (businessKind && (method.startsWith("artifact.") || method.startsWith("attachment."))) {
      const error = new Error("Desktop file action failed") as Error & { kind?: string };
      error.kind = businessKind;
      throw error;
    }
    return result;
  }, [api, t]);
  const lifecycle = useRuntimeLifecycle({ api, stateRef, dispatch });
  const {
    isMounted,
    hasOwner,
    runtimeGeneration,
    waitForRuntimeLifecycleIdle,
    waitForRuntimeUserAccess,
    enqueueRuntimeOperation,
    cancelTerminalStatusPoll,
    startTerminalStatusConvergence,
    hasTerminalStatusPoll,
    terminalStatusPollFor,
    latestTurnIdentity,
    setLatestTurnIdentity,
    beginPendingTurnStart,
    pendingTurnStart,
    bufferPendingTurnEvent,
    finishPendingTurnStart,
    clearPendingTurnStart,
  } = lifecycle;

  const reviewOwner = useCallback((): DocumentPreviewOwner & { ownerKey: string } => {
    const current = stateRef.current;
    return {
      generation: runtimeGeneration(),
      mode: current.mode,
      projectKey: current.selectedProjectKey,
      sessionId: current.selectedSessionId,
      viewRevision: current.sessionViewRevision,
      ownerKey: current.selectedProjectKey ?? "",
    };
  }, [runtimeGeneration]);
  const reviewOwnerMatches = useCallback((owner: DocumentPreviewOwner & { ownerKey?: string }, current = stateRef.current): boolean =>
    isMounted()
      && runtimeGeneration() === owner.generation
      && current.mode === owner.mode
      && current.selectedProjectKey === owner.projectKey
      && current.selectedSessionId === owner.sessionId
      && current.sessionViewRevision === owner.viewRevision,
  [isMounted, runtimeGeneration]);

  const sessionSearchEventOwned = useCallback((context: SessionSearchContext): boolean => {
    const current = stateRef.current;
    return isMounted()
      && runtimeGeneration() === context.runtimeGeneration
      && current.mode === context.mode
      && current.selectedProjectKey === context.projectKey
      && current.selectedSessionId === context.sessionId
      && current.sessionViewRevision === context.sessionViewRevision;
  }, [isMounted, runtimeGeneration]);

  const acceptSessionSearchEvent = useCallback((context: SessionSearchContext, event: AgentEvent): void => {
    if (sessionSearchContextRef.current !== context) return;
    const payload = asObject(event);
    const operationId = stringValue(payload.operation_id);
    if (!operationId || operationId !== context.operationId) return;
    if (!sessionSearchEventOwned(context)) {
      sessionSearchContextRef.current = null;
      return;
    }
    if (stringValue(payload.owner_key) !== context.ownerKey) {
      sessionSearchContextRef.current = null;
      setSessionSearch({ results: [], pending: false, error: true });
      return;
    }
    const state = stringValue(payload.state);
    if (state !== "completed" && state !== "cancelled" && state !== "stale" && state !== "failed") return;
    sessionSearchContextRef.current = null;
    if (state === "completed") {
      const allowedProjects = new Set(stateRef.current.projects.map((project) => project.projectKey));
      allowedProjects.add(GENERAL_PROJECT_KEY);
      const results = (Array.isArray(payload.hits) ? payload.hits : []).flatMap((value): SessionSearchHit[] => {
        const hit = asObject(value);
        const sessionId = stringValue(hit.session_id);
        const projectKey = stringValue(hit.project_key);
        if (!sessionId || !allowedProjects.has(projectKey) || typeof hit.snippet !== "string" || typeof hit.archived !== "boolean") return [];
        return [{
          session_id: sessionId,
          project_key: projectKey,
          title: typeof hit.title === "string" ? hit.title : null,
          snippet: hit.snippet.slice(0, 160),
          archived: hit.archived,
          last_used_at: typeof hit.last_used_at === "string" ? hit.last_used_at : null,
        }];
      }).slice(0, 20);
      setSessionSearch({ results, pending: false, error: false });
    } else {
      setSessionSearch({ results: [], pending: false, error: state === "failed" });
    }
  }, [sessionSearchEventOwned]);

  const receiveSessionSearchEvent = useCallback((event: AgentEvent): boolean => {
    if (stringValue(asObject(event).type) !== "session_search_result") return false;
    const payload = asObject(event);
    const operationId = stringValue(payload.operation_id);
    const current = sessionSearchContextRef.current;
    if (!current || !operationId) return true;
    if (!current.operationId) {
      const buffered = earlySessionSearchEventsRef.current;
      if (buffered.size >= 4) buffered.delete(buffered.keys().next().value as string);
      buffered.set(operationId, event);
      return true;
    }
    if (current.operationId === operationId) acceptSessionSearchEvent(current, event);
    return true;
  }, [acceptSessionSearchEvent]);

  const acceptWorkspaceDiffEvent = useCallback((context: WorkspaceDiffContext, event: AgentEvent) => {
    if (workspaceDiffContextRef.current !== context) return;
    const payload = asObject(event);
    if (stringValue(payload.operation_id) !== context.operationId) return;
    if (!reviewOwnerMatches(context.owner)) {
      workspaceDiffContextRef.current = null;
      return;
    }
    if (stringValue(payload.owner_key) !== context.ownerKey) {
      workspaceDiffContextRef.current = null;
      updateReviewTab(context.tabId, (tab) => tab.kind === "workspace-diff"
        ? { ...tab, state: "failed", error: t("workspaceDiffUnavailable") }
        : tab);
      return;
    }
    const state = stringValue(payload.state);
    if (state !== "completed" && state !== "cancelled" && state !== "stale" && state !== "failed") return;
    workspaceDiffContextRef.current = null;
    earlyWorkspaceDiffEventsRef.current.delete(context.operationId ?? "");
    updateReviewTab(context.tabId, (tab) => {
      if (tab.kind !== "workspace-diff") return tab;
      if (state === "completed") {
        const diff = workspaceDiffFromEvent(payload, context.ownerKey);
        return diff
          ? { ...tab, state: "completed", diff, error: undefined }
          : { ...tab, state: "failed", diff: undefined, error: t("workspaceDiffUnavailable") };
      }
      if (state === "failed") return { ...tab, state, diff: undefined, error: t("workspaceDiffUnavailable") };
      return { ...tab, state, diff: undefined, error: undefined };
    });
  }, [reviewOwnerMatches, t, updateReviewTab]);

  const acceptWorkspaceDiffSummaryEvent = useCallback((context: WorkspaceDiffSummaryContext, event: AgentEvent) => {
    if (workspaceDiffSummaryContextRef.current !== context) return;
    const payload = asObject(event);
    if (stringValue(payload.operation_id) !== context.operationId) return;
    if (!reviewOwnerMatches(context.owner)) {
      workspaceDiffSummaryContextRef.current = null;
      return;
    }
    if (stringValue(payload.owner_key) !== context.ownerKey) {
      workspaceDiffSummaryContextRef.current = null;
      setWorkspaceDiffSummary((current) => current?.requestKey === context.requestKey ? { ...current, state: "failed", diff: undefined } : current);
      return;
    }
    const resultState = stringValue(payload.state);
    if (resultState !== "completed" && resultState !== "cancelled" && resultState !== "stale" && resultState !== "failed") return;
    workspaceDiffSummaryContextRef.current = null;
    if (context.operationId) {
      earlyWorkspaceDiffSummaryEventsRef.current.delete(context.operationId);
      earlyWorkspaceDiffEventsRef.current.delete(context.operationId);
    }
    if (resultState === "completed") {
      const diff = workspaceDiffFromEvent(payload, context.ownerKey);
      setWorkspaceDiffSummary((current) => current?.requestKey === context.requestKey
        ? diff ? { ...current, state: "completed", diff } : { ...current, state: "failed", diff: undefined }
        : current);
    } else {
      setWorkspaceDiffSummary((current) => current?.requestKey === context.requestKey
        ? { ...current, state: "failed", diff: undefined }
        : current);
    }
  }, [reviewOwnerMatches]);

  const receiveWorkspaceDiffEvent = useCallback((event: AgentEvent): boolean => {
    if (stringValue(asObject(event).type) !== "workspace_diff_result") return false;
    const payload = asObject(event);
    const operationId = stringValue(payload.operation_id);
    if (!operationId) return true;
    const ownerKey = stringValue(payload.owner_key);
    const reviewContext = workspaceDiffContextRef.current;
    const summaryContext = workspaceDiffSummaryContextRef.current;
    if (reviewContext?.operationId === operationId) {
      acceptWorkspaceDiffEvent(reviewContext, event);
      earlyWorkspaceDiffSummaryEventsRef.current.delete(operationId);
      return true;
    }
    if (summaryContext?.operationId === operationId) {
      acceptWorkspaceDiffSummaryEvent(summaryContext, event);
      earlyWorkspaceDiffEventsRef.current.delete(operationId);
      return true;
    }
    if (reviewContext && !reviewContext.operationId && ownerKey === reviewContext.ownerKey) {
      const buffered = earlyWorkspaceDiffEventsRef.current;
      if (buffered.size >= 4) buffered.delete(buffered.keys().next().value as string);
      buffered.set(operationId, event);
    }
    if (summaryContext && !summaryContext.operationId && ownerKey === summaryContext.ownerKey) {
      const buffered = earlyWorkspaceDiffSummaryEventsRef.current;
      if (buffered.size >= 4) buffered.delete(buffered.keys().next().value as string);
      buffered.set(operationId, event);
    }
    return true;
  }, [acceptWorkspaceDiffEvent, acceptWorkspaceDiffSummaryEvent]);

  const cancelWorkspaceDiffSummary = useCallback((context = workspaceDiffSummaryContextRef.current) => {
    if (context && workspaceDiffSummaryContextRef.current !== context) return;
    if (workspaceDiffSummaryRefreshTimerRef.current !== null) {
      window.clearTimeout(workspaceDiffSummaryRefreshTimerRef.current);
      workspaceDiffSummaryRefreshTimerRef.current = null;
    }
    workspaceDiffSummaryContextRef.current = null;
    workspaceDiffSummarySequenceRef.current += 1;
    earlyWorkspaceDiffSummaryEventsRef.current.clear();
    if (context?.operationId) void send("workspace.diff.cancel", { operation_id: context.operationId }).catch(() => undefined);
  }, [send]);

  const refreshWorkspaceDiffSummary = useCallback(async (owner: DocumentPreviewOwner & { ownerKey: string }, requestKey: string) => {
    if (!api || owner.mode !== "coding" || !owner.projectKey || owner.projectKey !== owner.ownerKey || !reviewOwnerMatches(owner)) return;
    const previous = workspaceDiffSummaryContextRef.current;
    const context: WorkspaceDiffSummaryContext = {
      sequence: workspaceDiffSummarySequenceRef.current + 1,
      operationId: null,
      ownerKey: owner.ownerKey,
      owner,
      requestKey,
    };
    workspaceDiffSummarySequenceRef.current = context.sequence;
    workspaceDiffSummaryContextRef.current = context;
    earlyWorkspaceDiffSummaryEventsRef.current.clear();
    setWorkspaceDiffSummary({ owner, requestKey, state: "reviewing" });
    try {
      if (previous?.operationId) {
        try { await send("workspace.diff.cancel", { operation_id: previous.operationId }); } catch { /* the replacement kickoff reports the remaining operation limit */ }
      }
      if (workspaceDiffSummaryContextRef.current !== context || !reviewOwnerMatches(owner)) return;
      const response = asObject(await send("workspace.diff", { project_key: owner.ownerKey }));
      const operationId = stringValue(response.operation_id);
      if (workspaceDiffSummaryContextRef.current !== context || !reviewOwnerMatches(owner)) {
        if (operationId) void send("workspace.diff.cancel", { operation_id: operationId }).catch(() => undefined);
        return;
      }
      if (!operationId || stringValue(response.owner_key) !== owner.ownerKey || stringValue(response.state) !== "reviewing") {
        workspaceDiffSummaryContextRef.current = null;
        setWorkspaceDiffSummary((current) => current?.requestKey === requestKey ? { ...current, state: "failed", diff: undefined } : current);
        return;
      }
      context.operationId = operationId;
      const early = earlyWorkspaceDiffSummaryEventsRef.current.get(operationId);
      earlyWorkspaceDiffSummaryEventsRef.current.delete(operationId);
      earlyWorkspaceDiffEventsRef.current.delete(operationId);
      if (early) acceptWorkspaceDiffSummaryEvent(context, early);
    } catch {
      if (workspaceDiffSummaryContextRef.current !== context || !reviewOwnerMatches(owner)) return;
      workspaceDiffSummaryContextRef.current = null;
      setWorkspaceDiffSummary((current) => current?.requestKey === requestKey ? { ...current, state: "failed", diff: undefined } : current);
    }
  }, [acceptWorkspaceDiffSummaryEvent, api, reviewOwnerMatches, send]);

  const scheduleWorkspaceDiffSummaryRefresh = useCallback((owner: DocumentPreviewOwner & { ownerKey: string }, requestKey: string) => {
    if (!api || owner.mode !== "coding" || !owner.projectKey || owner.projectKey !== owner.ownerKey || !reviewOwnerMatches(owner)
      || workspaceDiffSummaryRequestKeyRef.current === requestKey) return;
    workspaceDiffSummaryOwnerRef.current = [owner.generation, owner.mode, owner.projectKey, owner.sessionId, owner.viewRevision].join(":");
    workspaceDiffSummaryRequestKeyRef.current = requestKey;
    if (workspaceDiffSummaryRefreshTimerRef.current !== null) window.clearTimeout(workspaceDiffSummaryRefreshTimerRef.current);
    workspaceDiffSummaryRefreshTimerRef.current = window.setTimeout(() => {
      workspaceDiffSummaryRefreshTimerRef.current = null;
      void refreshWorkspaceDiffSummary(owner, requestKey);
    }, 120);
  }, [api, refreshWorkspaceDiffSummary, reviewOwnerMatches]);

  const cancelSessionSearch = useCallback(() => {
    const current = sessionSearchContextRef.current;
    sessionSearchContextRef.current = null;
    sessionSearchSequenceRef.current += 1;
    earlySessionSearchEventsRef.current.clear();
    setSessionSearch({ results: [], pending: false, error: false });
    if (current?.operationId) void send("session.search.cancel", { operation_id: current.operationId }).catch(() => undefined);
  }, [send]);

  const searchSessions = useCallback(async (query: string) => {
    const current = stateRef.current;
    const ownerKey = current.mode === "general" ? GENERAL_PROJECT_KEY : current.selectedProjectKey;
    if (!api || !ownerKey || current.selectedProjectKey !== ownerKey) {
      setSessionSearch({ results: [], pending: false, error: true });
      return;
    }
    const previous = sessionSearchContextRef.current;
    if (previous?.operationId) void send("session.search.cancel", { operation_id: previous.operationId }).catch(() => undefined);
    const sequence = sessionSearchSequenceRef.current + 1;
    sessionSearchSequenceRef.current = sequence;
    earlySessionSearchEventsRef.current.clear();
    const context: SessionSearchContext = {
      sequence,
      operationId: "",
      ownerKey,
      mode: current.mode,
      projectKey: current.selectedProjectKey,
      sessionId: current.selectedSessionId,
      sessionViewRevision: current.sessionViewRevision,
      runtimeGeneration: runtimeGeneration(),
    };
    sessionSearchContextRef.current = context;
    setSessionSearch({ results: [], pending: true, error: false });
    try {
      const result = asObject(await send("session.search", { query: query.slice(0, 512), max_results: 20 }));
      const operationId = stringValue(result.operation_id);
      if (sessionSearchContextRef.current !== context || sessionSearchSequenceRef.current !== sequence) {
        if (operationId) void send("session.search.cancel", { operation_id: operationId }).catch(() => undefined);
        return;
      }
      if (!operationId || stringValue(result.owner_key) !== ownerKey || stringValue(result.state) !== "searching") {
        sessionSearchContextRef.current = null;
        setSessionSearch({ results: [], pending: false, error: true });
        return;
      }
      const owned = { ...context, operationId };
      sessionSearchContextRef.current = owned;
      const earlyEvent = earlySessionSearchEventsRef.current.get(operationId);
      earlySessionSearchEventsRef.current.clear();
      if (earlyEvent) acceptSessionSearchEvent(owned, earlyEvent);
    } catch {
      if (sessionSearchContextRef.current === context && sessionSearchSequenceRef.current === sequence) {
        sessionSearchContextRef.current = null;
        setSessionSearch({ results: [], pending: false, error: true });
      }
    }
  }, [acceptSessionSearchEvent, api, runtimeGeneration, send]);

  useEffect(() => {
    const current = sessionSearchContextRef.current;
    if (current && !sessionSearchEventOwned(current)) cancelSessionSearch();
  }, [cancelSessionSearch, sessionSearchEventOwned, state.mode, state.selectedProjectKey, state.selectedSessionId, state.sessionViewRevision]);

  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const updateViewport = () => {
      const nextNarrow = window.innerWidth <= 680;
      const wasNarrow = narrowViewportRef.current;
      const activeElement = document.activeElement;
      if (wasNarrow && !nextNarrow && activeElement?.closest("[data-runtime-error-owner='timeline']")) {
        // The Timeline owner is removed in the same commit that reveals a
        // docked RuntimePanel.  Preserve an explicit user focus boundary so
        // that the DOM mutation cannot strand focus on <body>.
        runtimeFocusHandoffRef.current = true;
      }
      narrowViewportRef.current = nextNarrow;
      setViewportWidth(window.innerWidth);
      setNarrowViewport(nextNarrow);
    };
    updateViewport();
    window.addEventListener("resize", updateViewport);
    return () => window.removeEventListener("resize", updateViewport);
  }, []);

  // Keep the rendered tracks inside the current CSS-pixel viewport. This is
  // a presentation clamp only: the stable user-selected width is persisted
  // by the separator's commit callback, never by resize/zoom churn.
  useEffect(() => {
    if (typeof window === "undefined" || narrowViewport) return;
    const next = clampedLayoutWidths(viewportWidth, state.panelMode, state.sidebarWidth, state.runtimePanelWidth);
    if (next.sidebarWidth !== state.sidebarWidth) dispatch({ type: "set_sidebar_width", width: next.sidebarWidth });
    if (next.runtimePanelWidth !== state.runtimePanelWidth) dispatch({ type: "set_runtime_panel_width", width: next.runtimePanelWidth });
  }, [narrowViewport, viewportWidth, state.panelMode, state.runtimePanelWidth, state.sidebarWidth]);

  const persist = useCallback(async (key: "theme" | "language" | "panelMode" | "sidebarWidth" | "runtimePanelWidth" | "recentProjects" | "projectAliases" | "pinnedProjectKeys" | "pinnedSessions" | "expandedProjects" | "selectedProjectKey" | "selectedSessionId", value: unknown) => {
    if (!api) return;
    try {
      await api.writePreference(key as never, value as never);
    } catch (error) {
      // Desktop metadata is advisory; a temporary preference failure must not
      // replace the Application's authoritative state.  It may still be
      // actionable for the user, but only through the localized renderer
      // fallback; native EPERM/path details stay outside the UI boundary.
      dispatch({ type: "notice", text: safeErrorMessage(error, t("preferencesUnavailable")) });
    }
  }, [api, t]);

  const beginSessionMutation = useCallback((): { sequence: number; generation: number } | null => {
    if (sessionMutationInFlightRef.current !== null) {
      dispatch({ type: "notice", text: t("sessionMutationBusy") });
      return null;
    }
    const generation = sessionMutationGenerationRef.current + 1;
    sessionMutationGenerationRef.current = generation;
    const sequence = sessionMutationSequenceRef.current + 1;
    sessionMutationSequenceRef.current = sequence;
    sessionMutationInFlightRef.current = sequence;
    // One gate covers both durable Session mutation methods.
    dispatch({ type: "session_mutation_busy", value: true });
    return { sequence, generation };
  }, [t]);

  const endSessionMutation = useCallback((sequence: number) => {
    if (sessionMutationInFlightRef.current !== sequence) return;
    sessionMutationInFlightRef.current = null;
    if (isMounted()) dispatch({ type: "session_mutation_busy", value: false });
  }, [isMounted]);

  const refreshCatalog = useCallback(async (projectKey: string, reason: SessionOrderReason = "catalog_refresh", focusSessionId?: string, reportFailure = true, isOwned?: RuntimeOwnershipCheck): Promise<boolean> => {
    if (isOwned) {
      if (!isOwned()) return false;
    } else if (!(await waitForRuntimeLifecycleIdle()) || hasOwner() || stateRef.current.runtimeState === "restarting") return false;
    try {
      const result = asObject(await send("project.sessions", { project_key: projectKey }));
      if (isOwned && !isOwned()) return false;
      if (!isOwned && (hasOwner() || stateRef.current.runtimeState === "restarting")) return false;
      const sessions = Array.isArray(result.sessions) ? result.sessions : [];
      dispatch({ type: "catalog_refreshed", projectKey, sessions, reason, focusSessionId });
      return true;
    } catch (error) {
      if ((!isOwned || isOwned()) && reportFailure) dispatch({ type: "notice", text: safeErrorMessage(error, t("sessionCatalogUnavailable")) });
      return false;
    }
  }, [hasOwner, send, t, waitForRuntimeLifecycleIdle]);

  const refreshProjectCatalog = useCallback(async (projectKey: string, isOwned?: RuntimeOwnershipCheck): Promise<boolean> => {
    const generation = runtimeGeneration();
    if (isOwned && !isOwned()) return false;
    const registeredProjectKeys = new Set(stateRef.current.projects.map((project) => project.projectKey));
    for (const key of projectCatalogRequestSequenceRef.current.keys()) {
      if (!registeredProjectKeys.has(key)) {
        projectCatalogRequestSequenceRef.current.delete(key);
        projectCatalogAppliedSequenceRef.current.delete(key);
      }
    }
    const requestSequence = (projectCatalogRequestSequenceRef.current.get(projectKey) ?? 0) + 1;
    projectCatalogRequestSequenceRef.current.set(projectKey, requestSequence);
    try {
      const result = asObject(await send("project.sessions", { project_key: projectKey }));
      if (!isMounted() || runtimeGeneration() !== generation || (isOwned && !isOwned())) return false;
      // Startup projects came from Main's registered-only preference
      // projection and its catalog action follows the preference hydration
      // dispatch. Other late reads must not recreate a removed Project.
      if (!isOwned && !stateRef.current.projects.some((project) => project.projectKey === projectKey)) return false;
      if (requestSequence < (projectCatalogAppliedSequenceRef.current.get(projectKey) ?? 0)) return false;
      projectCatalogAppliedSequenceRef.current.set(projectKey, requestSequence);
      dispatch({
        type: "catalog_refreshed",
        projectKey,
        sessions: Array.isArray(result.sessions) ? result.sessions : [],
      });
      return true;
    } catch {
      // A read-only background catalog refresh must not interrupt the active
      // Session or surface an unrelated Project error in its Runtime panel.
      return false;
    }
  }, [isMounted, runtimeGeneration, send]);

  const reconcileSessionMutation = useCallback(async (projectKey: string, sequence: number): Promise<void> => {
    // This reconciliation belongs to the Project mutation that started it;
    // do not apply a selected-project refresh after its owner has changed.
    if (!isMounted() || sessionMutationInFlightRef.current !== sequence) return;
    if (stateRef.current.selectedProjectKey !== projectKey) return;
    await refreshCatalog(projectKey, "catalog_refresh", undefined, false);
  }, [isMounted, refreshCatalog]);

  const refreshRuntimeStatus = useCallback(async (isOwned?: RuntimeOwnershipCheck, skipIfOwned = false): Promise<boolean> => {
    if (isOwned) {
      if (!isOwned()) return false;
    } else {
      if (skipIfOwned && (hasOwner() || stateRef.current.runtimeState === "restarting")) return false;
      if (!(await waitForRuntimeLifecycleIdle())) return false;
      if (hasOwner() || stateRef.current.runtimeState === "restarting") return false;
    }
    try {
      const result = await send("status.get", {});
      if (isOwned && !isOwned()) return false;
      if (!isOwned && (hasOwner() || stateRef.current.runtimeState === "restarting")) return false;
      dispatch({ type: "status_loaded", result });
      return true;
    } catch {
      // Runtime status is supplementary safe projection; command and Run
      // authority remain usable when it is temporarily unavailable.
      return false;
    }
  }, [hasOwner, send, waitForRuntimeLifecycleIdle]);

  const loadHistoryPage = useCallback((projectKey: string, sessionId: string, cursor: string | null, replace: boolean, refresh = false): Promise<void> => {
    const key = sessionRuntimeKey(projectKey, sessionId);
    const existing = historyRequestsRef.current.get(key);
    if (existing) return refresh
      ? existing.promise.then(() => loadHistoryPage(projectKey, sessionId, cursor, replace, refresh))
      : existing.promise;
    dispatch({ type: "history_page_loading", projectKey, sessionId });
    const token = Symbol("history-page");
    const request = (async () => {
      try {
        const params: JsonObject = { session_id: sessionId, page_size: 30 };
        if (cursor !== null) params.cursor = cursor;
        const result = await send("history.page", params);
        if (historyRequestsRef.current.get(key)?.token !== token) return;
        dispatch({ type: "history_page_loaded", projectKey, sessionId, result, replace, refresh });
      } catch (error) {
        if (historyRequestsRef.current.get(key)?.token !== token) return;
        dispatch({ type: "history_page_error", projectKey, sessionId, message: safeErrorMessage(error, t("sessionCatalogUnavailable")) });
      } finally {
        if (historyRequestsRef.current.get(key)?.token === token) historyRequestsRef.current.delete(key);
      }
    })();
    historyRequestsRef.current.set(key, { token, promise: request });
    return request;
  }, [send, t]);

  const historyPageLoaderRef = useRef(loadHistoryPage);
  historyPageLoaderRef.current = loadHistoryPage;

  const beginSessionPresentation = useCallback((projectKey: string, sessionId: string) => {
    const previousProjectKey = stateRef.current.selectedProjectKey;
    const previousSessionId = stateRef.current.selectedSessionId;
    if (previousSessionId && (previousProjectKey !== projectKey || previousSessionId !== sessionId)) {
      preparationPollRef.current.delete(sessionRuntimeKey(previousProjectKey, previousSessionId));
    }
    dispatch({ type: "history_page_started", projectKey, sessionId });
    const key = sessionRuntimeKey(projectKey, sessionId);
    const history = stateRef.current.sessionHistory[key];
    // Keep a cached first page visible immediately, then refresh it when a
    // parked Session is presented again so results committed in the
    // background can hydrate their durable output references.
    if (!history || history.error) void loadHistoryPage(projectKey, sessionId, null, true);
    else void loadHistoryPage(projectKey, sessionId, null, false, true);
  }, [loadHistoryPage]);

  const pollSessionPreparation = useCallback((projectKey: string, sessionId: string) => {
    const key = sessionRuntimeKey(projectKey, sessionId);
    const token = preparationPollSequenceRef.current + 1;
    preparationPollSequenceRef.current = token;
    preparationPollRef.current.set(key, token);
    let initialPresentationCheck = true;
    const schedule = () => {
      if (typeof window === "undefined") return;
      window.setTimeout(() => { void poll(); }, 100);
    };
    const poll = async (): Promise<void> => {
      const current = stateRef.current;
      if (!isMounted() || preparationPollRef.current.get(key) !== token) return;
      // The selected Session dispatch and this observer are started in the
      // same React turn. A synchronous bridge response can reach here before
      // stateRef observes that commit; keep the keyed observer alive for the
      // next presentation tick. A later navigation removes the old key, so a
      // stale observer cannot poll forever.
      if (current.selectedProjectKey !== projectKey || current.selectedSessionId !== sessionId) {
        // The first poll is deferred until the navigation dispatch commits,
        // but React may still be between the dispatch and its state commit.
        // Allow exactly one bounded retry for that presentation race; any
        // later mismatch is a real stale observer (for example a project-only
        // open) and must terminate rather than retry forever.
        if (initialPresentationCheck) {
          initialPresentationCheck = false;
          schedule();
        } else if (preparationPollRef.current.get(key) === token) {
          preparationPollRef.current.delete(key);
        }
        return;
      }
      initialPresentationCheck = false;
      if (hasOwner() || current.runtimeState === "restarting") {
        schedule();
        return;
      }
      const generation = runtimeGeneration();
      try {
        const result = asObject(await send("session.resume", { session_id: sessionId }));
        const after = stateRef.current;
        if (preparationPollRef.current.get(key) !== token) return;
        if (!isMounted() || runtimeGeneration() !== generation || hasOwner()
          || after.selectedProjectKey !== projectKey || after.selectedSessionId !== sessionId) {
          // Keep polling only when this is still the selected target. A new
          // navigation removes its token; an unrelated lifecycle owner merely
          // asks us to try again after that owner releases the Runtime.
          if (preparationPollRef.current.get(key) === token
            && after.selectedProjectKey === projectKey && after.selectedSessionId === sessionId) schedule();
          return;
        }
        if (result.preparing === true || asObject(result.session_state).status === "preparing") {
          schedule();
          return;
        }
        preparationPollRef.current.delete(key);
        if (result.preparation_failed === true || result.session_id !== sessionId) {
          dispatch({ type: "session_preparation", projectKey, sessionId, status: "failed" });
          return;
        }
        dispatch({ type: "session_resumed", result, preserveRuntimeState: true, preserveSessionRuntime: true, preserveTimeline: true });
        await refreshRuntimeStatus();
      } catch (error) {
        const after = stateRef.current;
        if (preparationPollRef.current.get(key) !== token) return;
        if (!isMounted() || runtimeGeneration() !== generation || hasOwner()
          || after.selectedProjectKey !== projectKey || after.selectedSessionId !== sessionId) {
          if (preparationPollRef.current.get(key) === token
            && after.selectedProjectKey === projectKey && after.selectedSessionId === sessionId) schedule();
          return;
        }
        preparationPollRef.current.delete(key);
        dispatch({ type: "session_preparation", projectKey, sessionId, status: "failed" });
        dispatch({ type: "notice", text: safeErrorMessage(error, t("sessionResumeFailed")) });
      }
    };
    // Navigation dispatches the selected Session and preparation marker in
    // the same React turn that starts this observer.  Defer the first check
    // until that presentation commit is visible through stateRef; otherwise
    // the observer would mistake the previous Session for a stale target and
    // exit before the background preparation can be polled.
    if (typeof window !== "undefined") window.setTimeout(() => { void poll(); }, 0);
  }, [hasOwner, isMounted, refreshRuntimeStatus, runtimeGeneration, send, t]);

  const publishTerminalStatus = useCallback((result: JsonValue) => {
    dispatch({ type: "status_loaded", result });
  }, []);

  // Context and compaction are live Run facts, not just terminal summaries.
  // Poll at a modest cadence while work is active so provider usage and the
  // lock state stay visible even when no semantic AgentEvent is emitted.
  useEffect(() => {
    // Terminal convergence already owns the short active->idle polling loop.
    // Keep this supplementary cadence for live Turns/compaction only, so a
    // terminal event cannot race a convergence response with a second status
    // writer.
    if (!api || (!state.activeTurn && state.compactionStatus.state !== "running")) return undefined;
    let cancelled = false;
    const refresh = () => {
      if (cancelled || runtimeStatusPollRef.current) return;
      const pending = refreshRuntimeStatus(undefined, true);
      runtimeStatusPollRef.current = pending;
      void pending.then(
        () => {
          if (runtimeStatusPollRef.current === pending) runtimeStatusPollRef.current = null;
        },
        () => {
          if (runtimeStatusPollRef.current === pending) runtimeStatusPollRef.current = null;
        },
      );
    };
    const timer = window.setInterval(refresh, 1000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [api, refreshRuntimeStatus, state.activeTurn, state.compactionStatus.state]);

  const processAgentEvent = useCallback((
    event: AgentEvent,
    acceptedSession?: { sessionId: string; projectKey: string; runId: string; turnId: string; runtimeGeneration: number; viewRevision: number },
  ) => {
    if (event.type === "settings_applications") {
      const counts = [event.applied, event.pending, event.failed];
      if (counts.every((count) => typeof count === "number" && Number.isSafeInteger(count) && count >= 0)) {
        dispatch({ type: "settings_applications", value: {
          applied: event.applied as number,
          pending: event.pending as number,
          failed: event.failed as number,
        } });
      }
      return;
    }
    // Runtime lifecycle envelopes are transport-level facts. While an App
    // operation owns a restart, its explicit terminal state must not be
    // replaced by the shutdown/initialization envelopes emitted by the old
    // owner (notably `stopping`/`stopped`).
    if (event.type === "runtime_state" && hasOwner()) return;
    const eventSessionId = stringValue(event.session_id);
    const eventProjectKey = stringValue(event.project_key);
    const currentState = stateRef.current;
    const { runId: eventRunId, turnId: eventTurnId } = eventIdentity(event);
    if (eventProjectKey && eventSessionId
      && hasCompleteTurnIdentity({ runId: eventRunId, turnId: eventTurnId })
      && (event.type === "turn_started" || event.type === "user_steering_applied")) {
      // In the normal path, Application persists this UUID-bound user entry
      // before releasing the event and before Provider work can block. The
      // catalog query reads Transcript timestamps; the event itself never
      // fabricates Recent ordering.
      void refreshProjectCatalog(eventProjectKey);
    }
    const acceptedSessionIsVisible = Boolean(acceptedSession
      && eventSessionId === acceptedSession.sessionId
      && eventProjectKey === acceptedSession.projectKey
      && eventRunId === acceptedSession.runId
      && eventTurnId === acceptedSession.turnId
      && currentState.selectedProjectKey === acceptedSession.projectKey
      && (currentState.selectedSessionId === acceptedSession.sessionId
        || (currentState.selectedSessionId === null
          && currentState.sessionViewRevision === acceptedSession.viewRevision
          && runtimeGeneration() === acceptedSession.runtimeGeneration)));
    const backgroundSession = !acceptedSessionIsVisible && Boolean(eventSessionId && (
      !currentState.selectedSessionId
      || eventSessionId !== currentState.selectedSessionId
      || Boolean(eventProjectKey && eventProjectKey !== currentState.selectedProjectKey)
    ));
    // A background runtime has its own Run/Turn identity.  The reducer keeps
    // that projection in the per-session cache; it must not be filtered by the
    // visible session's latest identity or start a visible terminal poll.
    if (backgroundSession) {
      dispatch({ type: "agent_event", event });
      return;
    }
    const latestMatches = () => {
      const latest = latestTurnIdentity();
      if (hasTurnIdentity(latest.runId, latest.turnId)) return knownIdentityMatches(latest.runId, latest.turnId, eventRunId, eventTurnId);
      const current = stateRef.current.run;
      const currentRunId = current?.run_id ?? "";
      const currentTurnId = current?.turn_id ?? "";
      return hasTurnIdentity(currentRunId, currentTurnId) && knownIdentityMatches(currentRunId, currentTurnId, eventRunId, eventTurnId);
    };
    if (event.type === "turn_started") {
      // A Core turn_started event is not itself an accepted boundary. Only
      // an already accepted run/turn (or the current known Run) may replace
      // poll ownership; a mismatched event must not cancel a live poll.
      if (!hasCompleteTurnIdentity({ runId: eventRunId, turnId: eventTurnId }) || !latestMatches()) return;
      setLatestTurnIdentity({ runId: eventRunId, turnId: eventTurnId });
      cancelTerminalStatusPoll();
    }
    const terminal = event.type === "turn_completed" || event.type === "turn_failed" || event.type === "turn_cancelled";
    if (terminal && (!hasCompleteTurnIdentity({ runId: eventRunId, turnId: eventTurnId }) || !latestMatches())) return;
    dispatch({ type: "agent_event", event });
    const toolName = stringValue(event.tool_name);
    const toolStatus = stringValue(event.status).toLowerCase();
    const failedTool = event.is_error === true || ["failed", "error", "rejected", "cancelled", "canceled"].includes(toolStatus)
      || stringValue(event.termination_reason) === "user_cancelled";
    const eventSessionIsCurrent = eventSessionId === currentState.selectedSessionId || acceptedSessionIsVisible;
    if (event.type === "tool_finished" && !failedTool && ["WriteFile", "EditFile", "ApplyPatch"].includes(toolName)
      && eventProjectKey && eventProjectKey === currentState.selectedProjectKey && eventSessionIsCurrent) {
      const owner = reviewOwner();
      const requestKey = [owner.generation, owner.mode, owner.projectKey, owner.sessionId, owner.viewRevision, eventRunId, eventTurnId, stringValue(event.tool_call_id)].join(":");
      scheduleWorkspaceDiffSummaryRefresh(owner, requestKey);
    }
    if (terminal) {
      // The terminal event is published before the Bridge releases its
      // active handle. Keep one cancellable, backoff poll alive until the
      // Application status explicitly reports active_turn=false.
      void startTerminalStatusConvergence(eventRunId, eventTurnId, false, async (result) => {
        publishTerminalStatus(result);
        const current = stateRef.current;
        const latest = latestTurnIdentity();
        if (knownIdentityMatches(latest.runId, latest.turnId, eventRunId, eventTurnId) && current.selectedProjectKey) {
          await refreshCatalog(current.selectedProjectKey, "message", current.selectedSessionId ?? undefined);
          if (eventProjectKey && eventSessionId) {
            // Live tool events carry only the bounded inline preview. Once the
            // Application releases the completed Turn, replay supplies the
            // durable output reference for externalized results.
            await loadHistoryPage(eventProjectKey, eventSessionId, null, false, true);
          }
        }
      });
    }
  }, [cancelTerminalStatusPoll, hasOwner, latestTurnIdentity, loadHistoryPage, publishTerminalStatus, refreshCatalog, refreshProjectCatalog, reviewOwner, runtimeGeneration, scheduleWorkspaceDiffSummaryRefresh, setLatestTurnIdentity, startTerminalStatusConvergence, t]);

  const readProcess = useCallback(async (processId: string, cursor: number) => {
    const projectKey = stateRef.current.selectedProjectKey;
    const sessionId = stateRef.current.selectedSessionId;
    if (!projectKey || !sessionId || !Number.isSafeInteger(cursor) || cursor < 0) return;
    dispatch({ type: "process_read_started", projectKey, sessionId, processId });
    try {
      const result = await send("process.read", { process_id: processId, cursor });
      const current = stateRef.current;
      // A late response is discarded at the ownership boundary.  The
      // reducer also keys data by this exact Session, so background replies
      // cannot be attached to the visible Session by process id alone.
      if (current.selectedProjectKey !== projectKey || current.selectedSessionId !== sessionId) {
        // Clear the loading flag in the parked Session cache without exposing
        // the stale result in the newly selected Session.  Returning to the
        // old Session must leave its reader retryable.
        dispatch({ type: "process_read_error", projectKey, sessionId, processId, message: t("runtimeError") });
        return;
      }
      dispatch({ type: "process_read_loaded", projectKey, sessionId, processId, result });
    } catch (error) {
      const current = stateRef.current;
      if (current.selectedProjectKey === projectKey && current.selectedSessionId === sessionId) {
        dispatch({ type: "process_read_error", projectKey, sessionId, processId, message: safeErrorMessage(error, t("runtimeError")) });
      } else {
        dispatch({ type: "process_read_error", projectKey, sessionId, processId, message: t("runtimeError") });
      }
    }
  }, [send, t]);

  const releaseProcessPermission = useCallback(async (pending: PendingProcessPermission) => {
    const permissionId = stringValue(pending.request.permission_id);
    if (!permissionId || processPermissionReleaseRef.current === permissionId) return;
    processPermissionReleaseRef.current = permissionId;
    try {
      await send("process.permission.release", {
        permission_id: permissionId,
        process_id: pending.processId,
      });
    } catch {
      // Cleanup is best effort at the transport boundary.  The Bridge also
      // clears all prepared approvals on shutdown; never retry a request that
      // could be racing a Session/Application replacement.
      if (isMounted() && stateRef.current.selectedProjectKey === pending.projectKey && stateRef.current.selectedSessionId === pending.sessionId) {
        dispatch({ type: "notice", text: t("processStopFailed") });
      }
    } finally {
      if (processPermissionReleaseRef.current === permissionId) processPermissionReleaseRef.current = null;
    }
  }, [isMounted, send, t]);

  useEffect(() => {
    // Runtime lifecycle teardown marks the App unmounted before this cleanup
    // runs. Release the Bridge-owned prepared approval directly from the ref;
    // the release helper suppresses UI dispatch while unmounted and its
    // permission-id guard keeps StrictMode/unmount cleanup idempotent.
    return () => {
      const pending = pendingProcessPermissionRef.current;
      if (!pending) return;
      pendingProcessPermissionRef.current = null;
      processPermissionSubmitRef.current = null;
      void releaseProcessPermission(pending);
    };
  }, [releaseProcessPermission]);

  const stopProcess = useCallback(async (processId: string) => {
    const projectKey = stateRef.current.selectedProjectKey;
    const sessionId = stateRef.current.selectedSessionId;
    if (!projectKey || !sessionId || !processId || pendingProcessPermissionRef.current || processStopInFlightRef.current) return;
    const operationKey = `${projectKey}\u0000${sessionId}\u0000${processId}`;
    processStopInFlightRef.current = operationKey;
    try {
      const result = await send("process.stop", { process_id: processId });
      const permission = processPermissionFromResult(result, projectKey, sessionId, processId);
      const current = stateRef.current;
      if (!isMounted() || current.selectedProjectKey !== projectKey || current.selectedSessionId !== sessionId) {
        if (permission) void releaseProcessPermission(permission);
        return;
      }
      if (!permission) {
        if (asObject(result).permission_required !== undefined) {
          dispatch({ type: "notice", text: t("processStopFailed") });
        }
        return;
      }
      // Set the ref before React commits the modal so a second click in the
      // same task cannot issue another destructive stop request.
      pendingProcessPermissionRef.current = permission;
      setPendingProcessPermission(permission);
    } catch (error) {
      const current = stateRef.current;
      if (current.selectedProjectKey === projectKey && current.selectedSessionId === sessionId) {
        dispatch({ type: "notice", text: runtimeRequestKind(error) === "permission_denied" ? t("processStopRejected") : t("processStopFailed") });
      }
    } finally {
      if (processStopInFlightRef.current === operationKey) processStopInFlightRef.current = null;
    }
  }, [isMounted, releaseProcessPermission, send, t]);

  const cancelProcessPermission = useCallback(() => {
    const pending = pendingProcessPermissionRef.current;
    if (!pending || processPermissionSubmitRef.current) return;
    pendingProcessPermissionRef.current = null;
    setPendingProcessPermission(null);
    void releaseProcessPermission(pending);
  }, [releaseProcessPermission]);

  const submitProcessPermission = useCallback(async (response: JsonObject) => {
    const pending = pendingProcessPermissionRef.current;
    const permissionId = stringValue(response.permission_id);
    const choice = stringValue(response.choice);
    if (!pending || !permissionId || permissionId !== stringValue(pending.request.permission_id) || !choice || processPermissionSubmitRef.current) return;
    const current = stateRef.current;
    if (current.selectedProjectKey !== pending.projectKey || current.selectedSessionId !== pending.sessionId) {
      pendingProcessPermissionRef.current = null;
      setPendingProcessPermission(null);
      return;
    }
    const submissionKey = `${permissionId}\u0000${choice}`;
    processPermissionSubmitRef.current = submissionKey;
    setPendingProcessPermission({ ...pending, submitting: true });
    try {
      const result = await send("process.stop", {
        process_id: pending.processId,
        permission_id: permissionId,
        permission_choice: choice,
      });
      const after = stateRef.current;
      if (!isMounted() || after.selectedProjectKey !== pending.projectKey || after.selectedSessionId !== pending.sessionId) return;
      const repeatedRequest = processPermissionFromResult(result, pending.projectKey, pending.sessionId, pending.processId);
      if (repeatedRequest) {
        pendingProcessPermissionRef.current = repeatedRequest;
        setPendingProcessPermission(repeatedRequest);
        return;
      }
      pendingProcessPermissionRef.current = null;
      setPendingProcessPermission(null);
    } catch (error) {
      const after = stateRef.current;
      pendingProcessPermissionRef.current = null;
      if (isMounted() && after.selectedProjectKey === pending.projectKey && after.selectedSessionId === pending.sessionId) {
        setPendingProcessPermission(null);
        dispatch({ type: "notice", text: choice === "reject" && runtimeRequestKind(error) === "permission_denied" ? t("processStopRejected") : t("processStopFailed") });
      }
    } finally {
      if (processPermissionSubmitRef.current === submissionKey) processPermissionSubmitRef.current = null;
    }
  }, [isMounted, send, t]);

  const refreshConfiguration = useCallback(async (isOwned?: RuntimeOwnershipCheck) => {
    if (isOwned) {
      if (!isOwned()) return;
    } else if (!(await waitForRuntimeLifecycleIdle()) || hasOwner() || stateRef.current.runtimeState === "restarting") return;
    try {
      const result = asObject(await send("settings.get", {}));
      if (isOwned && !isOwned()) return;
      if (!isOwned && (hasOwner() || stateRef.current.runtimeState === "restarting")) return;
      dispatch({ type: "settings_loaded", configuration: asObject(result.configuration) as ConfigurationView });
    } catch {
      // An unconfigured Runtime is expected to reject this supplementary read;
      // the explicit Settings flow still reports the actionable error.
    }
  }, [hasOwner, send, waitForRuntimeLifecycleIdle]);

  const revealSettingsApiKey = useCallback(async (providerId: string): Promise<string | null> => {
    if (!(await waitForRuntimeUserAccess()) || hasOwner() || stateRef.current.runtimeState === "restarting") return null;
    const result = asObject(await send("settings.reveal_api_key", { provider_profile_id: providerId }));
    const value = result.api_key;
    if (value === null || typeof value === "string") return value;
    throw new Error("Invalid API key reveal response");
  }, [hasOwner, send, waitForRuntimeUserAccess]);

  const openProjectPath = useCallback(async (path: string) => {
    if (!api) return;
    // Project-only navigation clears the selected Session, so every pending
    // preparation observer belongs to an obsolete visible target.  Remove
    // their tokens before the asynchronous project.open boundary can return.
    preparationPollRef.current.clear();
    await enqueueRuntimeOperation("navigation", async (isOwned) => {
      const result = await send("project.open", { path });
      if (!isOwned()) throw new StaleRuntimeOperation();
      dispatch({ type: "project_opened", result, preserveRuntimeState: true, preserveSessionRuntime: true });
      const next = stateRef.current.projects.some((project) => project.projectKey === path)
        ? stateRef.current.projects
        : [...stateRef.current.projects, { path, projectKey: path, alias: path.split(/[\\/]/u).filter(Boolean).pop() || path, pinned: false, sessions: [], catalogFresh: true }];
      await persist("recentProjects", projectPreferences(next));
      await persist("selectedProjectKey", path);
      if (!isOwned()) throw new StaleRuntimeOperation();
      await refreshCatalog(path, "project_open", undefined, true, isOwned);
      if (!isOwned()) throw new StaleRuntimeOperation();
      await refreshRuntimeStatus(isOwned);
      await refreshConfiguration(isOwned);
    }, async (error, isOwned) => {
      if (!isOwned()) return;
      const existing = stateRef.current.projects.find((project) => project.projectKey === path);
      const project = existing ?? { path, projectKey: path, alias: path.split(/[\\/]/u).filter(Boolean).pop() || path, pinned: false, sessions: [], catalogFresh: false };
      const projects = existing ? stateRef.current.projects : [...stateRef.current.projects, project];
      dispatch({ type: "hydrate_preferences", preferences: { recentProjects: projectPreferences(projects), selectedProjectKey: path, selectedSessionId: null } });
      await persist("recentProjects", projectPreferences(projects));
      await persist("selectedProjectKey", path);
      if (!isOwned()) return;
      dispatch({ type: "runtime_error", message: safeErrorMessage(error, t("projectOpenFailed")), state: "configuration_required" });
      dispatch({ type: "set_view", view: "settings" });
    });
  }, [api, enqueueRuntimeOperation, persist, refreshCatalog, refreshConfiguration, refreshRuntimeStatus, send, t]);

  useEffect(() => {
    if (!api) {
      dispatch({ type: "runtime_state", state: "ready" });
      return undefined;
    }
    let cancelled = false;
    const unsubscribe = api.subscribeAgentEvents((event) => {
      if (cancelled) return;
      if (receiveSessionSearchEvent(event)) return;
      if (receiveWorkspaceDiffEvent(event)) return;
      const pendingStart = pendingTurnStart();
      const pendingEventIdentity = eventIdentity(event);
      if (pendingStart && hasTurnIdentity(pendingEventIdentity.runId, pendingEventIdentity.turnId)) {
        // Python Runtime can resolve turn.start and synchronously deliver the
        // following stdout events before the Promise continuation records the
        // accepted flat identity. Hold scoped events until that boundary is
        // known; unrelated identities are filtered when the response arrives.
        bufferPendingTurnEvent(event);
        return;
      }
      processAgentEvent(event);
    });
    void Promise.all([
      api.readPreference("theme"),
      api.readPreference("language"),
      api.readPreference("panelMode"),
      api.readPreference("sidebarWidth"),
      api.readPreference("runtimePanelWidth"),
      api.readPreference("recentProjects"),
      api.readPreference("projectAliases"),
      api.readPreference("pinnedProjectKeys"),
      api.readPreference("pinnedSessions"),
      api.readPreference("expandedProjects"),
      api.readPreference("selectedProjectKey"),
      api.readPreference("selectedSessionId"),
    ]).then(async ([theme, language, panelMode, sidebarWidth, runtimePanelWidth, recentProjects, projectAliases, pinnedProjectKeys, pinnedSessions, expandedProjects, selectedProjectKey, selectedSessionId]) => {
      // A user save/navigation may have become the current lifecycle owner
      // while Desktop preferences were still loading. Do not let this late
      // bootstrap callback supersede that newer generation.
      if (cancelled || hasOwner()) return;
      dispatch({ type: "hydrate_preferences", preferences: { theme, language, panelMode, sidebarWidth, runtimePanelWidth, recentProjects, projectAliases, pinnedProjectKeys, pinnedSessions, expandedProjects, selectedProjectKey, selectedSessionId } });
      const selected = (recentProjects as DesktopPreferences["recentProjects"]).find((project) => project.path === selectedProjectKey);
      const bootstrapProject = selected ?? (recentProjects as DesktopPreferences["recentProjects"])[0];
      if (bootstrapProject) {
        void enqueueRuntimeOperation("startup", async (isOwned) => {
          const result = await send("runtime.initialize", { workdir: bootstrapProject.path });
          if (cancelled || !isOwned()) throw new StaleRuntimeOperation();
          if (selected) {
            dispatch({ type: "runtime_initialized", result, preserveRuntimeState: true });
            await refreshConfiguration(isOwned);
            await refreshRuntimeStatus(isOwned);
          } else {
            // A registered Project can host the metadata Application when a
            // saved selection is stale or empty. Keep that bootstrap choice
            // out of the visible selection and Runtime projection.
            dispatch({ type: "runtime_state", state: "ready" });
          }
          for (const project of recentProjects as DesktopPreferences["recentProjects"]) {
            if (selected && project.path === selected.path) {
              await refreshCatalog(project.path, "catalog_refresh", undefined, true, isOwned);
            } else {
              await refreshProjectCatalog(project.path, isOwned);
            }
          }
          if (selected && selectedSessionId) {
            beginSessionPresentation(selected.path, selectedSessionId);
            const resumed = await send("session.resume", { session_id: selectedSessionId });
            if (cancelled || !isOwned()) throw new StaleRuntimeOperation();
            const source = asObject(resumed);
            const preparing = source.preparing === true || asObject(source.session_state).status === "preparing";
            if (preparing) {
              dispatch({ type: "session_preparation", projectKey: selected.path, sessionId: selectedSessionId, status: "preparing" });
              pollSessionPreparation(selected.path, selectedSessionId);
            } else if (source.preparation_failed === true) {
              dispatch({ type: "session_preparation", projectKey: selected.path, sessionId: selectedSessionId, status: "failed" });
            } else {
              dispatch({ type: "session_resumed", result: resumed, preserveRuntimeState: true, preserveSessionRuntime: true, preserveTimeline: true });
              await refreshRuntimeStatus(isOwned);
            }
          }
        }, (error, isOwned) => {
          if (!cancelled && isOwned()) dispatch({ type: "runtime_error", message: safeErrorMessage(error, t("runtimeStartFailed")), state: "configuration_required" });
        });
      } else {
        dispatch({ type: "runtime_state", state: "ready" });
      }
    }).catch((error) => {
      if (!cancelled) dispatch({ type: "runtime_error", message: safeErrorMessage(error, t("preferencesUnavailable")), state: "ready" });
    });
    return () => {
      cancelled = true;
      clearPendingTurnStart();
      cancelTerminalStatusPoll();
      unsubscribe();
    };
  }, [api, beginSessionPresentation, bufferPendingTurnEvent, cancelTerminalStatusPoll, clearPendingTurnStart, enqueueRuntimeOperation, hasOwner, pendingTurnStart, pollSessionPreparation, processAgentEvent, receiveSessionSearchEvent, receiveWorkspaceDiffEvent, refreshCatalog, refreshProjectCatalog, refreshConfiguration, refreshRuntimeStatus, send, t]);

  const openProject = useCallback(async () => {
    if (!api) return;
    try {
      const path = await api.openProject();
      if (path) await openProjectPath(path);
    } catch (error) {
      dispatch({ type: "notice", text: safeErrorMessage(error, t("projectPickerUnavailable")) });
    }
  }, [api, openProjectPath]);

  const closeActiveTurn = useCallback(async (): Promise<boolean> => {
    if (!api) return false;
    if (pendingTurnStart()) return false;
    const beforeCancel = stateRef.current;
    const beforeRunId = beforeCancel.run?.run_id ?? "";
    const beforeTurnId = beforeCancel.run?.turn_id ?? "";
    const stillOwnsTurn = () => {
      const current = stateRef.current;
      if (beforeRunId || beforeTurnId) {
        return (!beforeRunId || current.run?.run_id === beforeRunId)
          && (!beforeTurnId || current.run?.turn_id === beforeTurnId);
      }
      // An active state without identity is not expected from the Application
      // DTO, but if it appears, object identity still prevents an old wait
      // from authorizing a newly started Run.
      return current.run === beforeCancel.run;
    };
    if (!beforeCancel.activeTurn && !beforeCancel.terminalStatusPending) return true;
    if (beforeCancel.terminalStatusPending && !hasTerminalStatusPoll()) {
      dispatch({ type: "notice", text: t("terminalStatusPending") });
      return false;
    }
    try {
      if (beforeCancel.activeTurn && !beforeCancel.terminalStatusPending) await send("turn.cancel", {});
    } catch {
      // The Bridge owns the terminal error. We still wait for its state before
      // asking it to replace a Session/Application.
    }
    if (!stillOwnsTurn()) return false;
    const ownedPoll = terminalStatusPollFor(beforeRunId, beforeTurnId);
    if (!ownedPoll && hasTerminalStatusPoll()) return false;
    const idle = await (ownedPoll
      ?? startTerminalStatusConvergence(beforeRunId, beforeTurnId, true, publishTerminalStatus));
    if (!stillOwnsTurn()) return false;
    if (idle.state !== "idle") {
      dispatch({ type: "notice", text: t("terminalStatusPending") });
      return false;
    }
    return true;
  }, [api, hasTerminalStatusPoll, pendingTurnStart, publishTerminalStatus, send, startTerminalStatusConvergence, t, terminalStatusPollFor]);

  const resumeSession = useCallback(async (project: ProjectState, sessionId: string) => {
    if (!api) return;
    const targetIsGeneral = project.projectKey === GENERAL_PROJECT_KEY;
    // Clicking the already-visible row is a presentation no-op.  In
    // particular, never enqueue a lifecycle operation that waits for its own
    // active Turn to become idle.
    if (sessionId
      && stateRef.current.mode === (targetIsGeneral ? "general" : "coding")
      && stateRef.current.selectedProjectKey === project.projectKey
      && stateRef.current.selectedSessionId === sessionId
      && stateRef.current.sessionPreparation[sessionRuntimeKey(project.projectKey, sessionId)] !== "failed") return;
    await enqueueRuntimeOperation("navigation", async (isOwned) => {
      // The bridge keeps an independent runtime per durable Session. Project
      // navigation also preserves the old runtime, so switching rows/projects
      // never cancels a background Turn.
      if (!isOwned()) throw new StaleRuntimeOperation();
      if (targetIsGeneral && stateRef.current.mode !== "general") {
        const opened = await send("general.open", {});
        if (!isOwned()) throw new StaleRuntimeOperation();
        dispatch({ type: "general_opened", result: opened, sessionId: sessionId || null });
        dispatch({ type: "runtime_state", state: "ready", error: null });
      } else if (!targetIsGeneral && (stateRef.current.mode !== "coding" || stateRef.current.selectedProjectKey !== project.projectKey)) {
        const opened = await send("project.open", { path: project.path });
        if (!isOwned()) throw new StaleRuntimeOperation();
        dispatch({ type: "project_opened", result: opened, preserveRuntimeState: true, preserveSessionRuntime: true });
        await persist("selectedProjectKey", project.projectKey);
      }
      let preparing = false;
      if (sessionId) {
        beginSessionPresentation(project.projectKey, sessionId);
        const result = await send("session.resume", { session_id: sessionId, project_key: project.projectKey });
        if (!isOwned()) throw new StaleRuntimeOperation();
        const source = asObject(result);
        preparing = source.preparing === true || asObject(source.session_state).status === "preparing";
        if (source.preparation_failed === true) {
          dispatch({ type: "session_preparation", projectKey: project.projectKey, sessionId, status: "failed" });
        } else if (preparing) {
          dispatch({ type: "session_preparation", projectKey: project.projectKey, sessionId, status: "preparing" });
          pollSessionPreparation(project.projectKey, sessionId);
        } else {
          setLatestTurnIdentity(identityFromRun(source.run));
          cancelTerminalStatusPoll();
          dispatch({ type: "session_resumed", result, preserveRuntimeState: true, preserveSessionRuntime: true, preserveTimeline: true });
        }
        if (!targetIsGeneral) await persist("selectedSessionId", sessionId);
      } else {
        const result = await send("session.new", {});
        if (!isOwned()) throw new StaleRuntimeOperation();
        const source = asObject(result);
        const nextId = typeof source.session_id === "string" ? source.session_id : "";
        if (nextId) {
          setLatestTurnIdentity(identityFromRun(source.run));
          cancelTerminalStatusPoll();
          dispatch({ type: "session_new", sessionId: nextId, run: source.run, modelRef: typeof source.model_ref === "string" ? source.model_ref : null, preserveSessionRuntime: true });
          if (!targetIsGeneral) await persist("selectedSessionId", nextId);
        }
      }
      if (!isOwned()) throw new StaleRuntimeOperation();
      await refreshCatalog(project.projectKey, sessionId ? "session_resume" : "session_new", sessionId || undefined, true, isOwned);
      if (!sessionId || !preparing) {
        await refreshRuntimeStatus(isOwned);
      }
    }, (error, isOwned) => {
      if (isOwned()) dispatch({ type: "runtime_error", message: safeErrorMessage(error, t("sessionOpenFailed")), state: "ready" });
    });
  }, [api, beginSessionPresentation, cancelTerminalStatusPoll, enqueueRuntimeOperation, persist, pollSessionPreparation, refreshCatalog, refreshRuntimeStatus, send, setLatestTurnIdentity, t]);

  const newSession = useCallback(async () => {
    const project = stateRef.current.projects.find((item) => item.projectKey === stateRef.current.selectedProjectKey);
    if (project) await resumeSession(project, "");
  }, [resumeSession]);

  const switchMode = useCallback(async (mode: RendererState["mode"]) => {
    const current = stateRef.current;
    if (current.mode === mode) return;
    cancelSessionSearch();
    if (mode === "coding") {
      const saved = current.modeSelections.coding;
      const project = saved.projectKey
        ? current.projects.find((item) => item.projectKey === saved.projectKey && item.projectKey !== GENERAL_PROJECT_KEY)
        : null;
      if (project) {
        if (saved.sessionId) await resumeSession(project, saved.sessionId);
        else await openProjectPath(project.path);
        return;
      }
      await enqueueRuntimeOperation("navigation", async (isOwned) => {
        if (!isOwned()) throw new StaleRuntimeOperation();
        dispatch({ type: "mode_empty", mode: "coding" });
      }, () => undefined, "stopped");
      return;
    }

    await enqueueRuntimeOperation("navigation", async (isOwned) => {
      const sessionId = stateRef.current.modeSelections.general.sessionId;
      const opened = await send("general.open", {});
      if (!isOwned()) throw new StaleRuntimeOperation();
      dispatch({ type: "general_opened", result: opened, sessionId });
      dispatch({ type: "runtime_state", state: "ready", error: null });
      let preparing = false;
      if (sessionId) {
        beginSessionPresentation(GENERAL_PROJECT_KEY, sessionId);
        const resumed = await send("session.resume", { session_id: sessionId, project_key: GENERAL_PROJECT_KEY });
        if (!isOwned()) throw new StaleRuntimeOperation();
        const source = asObject(resumed);
        preparing = source.preparing === true || asObject(source.session_state).status === "preparing";
        if (source.preparation_failed === true) {
          dispatch({ type: "session_preparation", projectKey: GENERAL_PROJECT_KEY, sessionId, status: "failed" });
        } else if (preparing) {
          dispatch({ type: "session_preparation", projectKey: GENERAL_PROJECT_KEY, sessionId, status: "preparing" });
          pollSessionPreparation(GENERAL_PROJECT_KEY, sessionId);
        } else {
          setLatestTurnIdentity(identityFromRun(source.run));
          cancelTerminalStatusPoll();
          dispatch({ type: "session_resumed", result: resumed, preserveRuntimeState: true, preserveSessionRuntime: true });
        }
      }
      if (!isOwned()) throw new StaleRuntimeOperation();
      await refreshCatalog(GENERAL_PROJECT_KEY, sessionId ? "session_resume" : "catalog_refresh", sessionId || undefined, true, isOwned);
      if (!sessionId || !preparing) {
        await refreshRuntimeStatus(isOwned);
        await refreshConfiguration(isOwned);
      }
    }, (error, isOwned) => {
      if (isOwned()) dispatch({ type: "runtime_error", message: safeErrorMessage(error, t("sessionOpenFailed")), state: "ready" });
    });
  }, [beginSessionPresentation, cancelSessionSearch, cancelTerminalStatusPoll, enqueueRuntimeOperation, openProjectPath, pollSessionPreparation, refreshCatalog, refreshConfiguration, refreshRuntimeStatus, resumeSession, send, setLatestTurnIdentity, t]);

  const loadOlderHistory = useCallback(() => {
    const current = stateRef.current;
    if (!current.selectedProjectKey || !current.selectedSessionId) return;
    const key = sessionRuntimeKey(current.selectedProjectKey, current.selectedSessionId);
    const history = current.sessionHistory[key];
    if (!history || history.loading || !history.hasMore || !history.nextCursor) return;
    void loadHistoryPage(current.selectedProjectKey, current.selectedSessionId, history.nextCursor, false);
  }, [loadHistoryPage]);

  const retryHistory = useCallback(() => {
    const current = stateRef.current;
    if (!current.selectedProjectKey || !current.selectedSessionId) return;
    const key = sessionRuntimeKey(current.selectedProjectKey, current.selectedSessionId);
    const history = current.sessionHistory[key];
    if (!history || history.loading || !history.error) return;
    const replace = history.records.length === 0;
    const cursor = replace ? null : history.nextCursor;
    if (!replace && !cursor) return;
    void loadHistoryPage(current.selectedProjectKey, current.selectedSessionId, cursor, replace);
  }, [loadHistoryPage]);

  const executeCommand = useCallback(async (text: string) => {
    if (!text.trim() || !api || commandInFlightRef.current) return;
    const owner = {
      generation: runtimeGeneration(),
      mode: stateRef.current.mode,
      projectKey: stateRef.current.selectedProjectKey,
      sessionId: stateRef.current.selectedSessionId,
      viewRevision: stateRef.current.sessionViewRevision,
    };
    const ownsCommand = () => {
      const current = stateRef.current;
      return isMounted()
        && runtimeGeneration() === owner.generation
        && current.mode === owner.mode
        && current.selectedProjectKey === owner.projectKey
        && current.selectedSessionId === owner.sessionId
        && current.sessionViewRevision === owner.viewRevision
        && !hasOwner();
    };
    if ((hasOwner() || stateRef.current.runtimeState === "restarting")
      && (!(await waitForRuntimeUserAccess()) || hasOwner() || stateRef.current.runtimeState === "restarting")) return;
    const isCurrent = ownsCommand;
    if (!isCurrent() || commandInFlightRef.current) return;
    commandInFlightRef.current = true;
    try {
      const result = await send("command.execute", { text });
      if (!isCurrent()) return;
      if (!isDesktopCommandResult(result)) {
        dispatch({ type: "notice", text: t("commandFailed") });
        return;
      }
      const source = asObject(result);
      const ownerSessionId = owner.sessionId;
      if (source.code === "image_input_unsupported" && source.command === "model" && ownerSessionId) {
        const match = text.trim().match(/^\/model\s+([^\s]+)(?:\s|$)/i);
        if (match?.[1]) {
          const pending: PendingModelImageSwitch = {
            ...owner,
            sessionId: ownerSessionId,
            modelRef: match[1],
            operationId: null,
            handling: null,
            busy: false,
            error: null,
          };
          pendingModelImageSwitchRef.current = pending;
          setPendingModelImageSwitch(pending);
          return;
        }
      }
      dispatch({ type: "command_result", result, notice: commandResultNotice(result, t) });
      if (source.code === "compact_started") {
        const params = asObject(source.params);
        const operationId = stringValue(params.operation_id);
        const sessionId = stringValue(params.session_id);
        if (operationId && sessionId) {
          dispatch({
            type: "compaction_started",
            trigger: "manual",
            operationId,
            sessionId,
            projectKey: stateRef.current.selectedProjectKey ?? undefined,
          });
        }
      }
      // `/status` is a read-only query, but its typed facts must be visible
      // even when the user previously hid the optional Runtime panel.  Open
      // only the existing panel for this response and do not persist the
      // temporary presentation choice.
      if (source.code === "status_ready" && stateRef.current.panelMode === "hidden") {
        dispatch({ type: "set_panel_mode", panelMode: narrowViewportRef.current ? "floating" : "docked" });
      }
      const action = asObject(source.ui_action);
      // Command outcomes are explicit Application boundaries.  Refresh the
      // safe Context/Compaction projection once here; completion deltas never
      // trigger status RPCs.
      // `/status` already carries the exact same safe projection as
      // `status.get`; avoid a second request that could replace the freshly
      // rendered facts with an empty/late response.
      if (source.code !== "status_ready") await refreshRuntimeStatus();
      if (!isCurrent()) return;
      if (action.type === "open_model_picker") {
        try {
          const completion = asObject(await send("command.complete", { prefix: "/model " }));
          if (!isCurrent()) return;
          const values = Array.isArray(completion.argument_candidates) ? completion.argument_candidates.filter((value): value is string => typeof value === "string") : [];
          dispatch({ type: "model_candidates", values });
        } catch {
          dispatch({ type: "model_candidates", values: [] });
        }
      }
      if (action.type === "session_changed" && typeof action.session_id === "string") {
        await persist("selectedSessionId", action.session_id);
        if (!isCurrent()) return;
        const reason: SessionOrderReason = action.restored === true ? "session_resume" : "session_new";
        await refreshCatalog(stateRef.current.selectedProjectKey ?? "", reason, action.session_id);
        if (!isCurrent()) return;
        await refreshRuntimeStatus();
      }
      if (action.type === "quit_interface") {
        if (!isCurrent()) return;
        await api.closeShell();
      }
    } catch (error) {
      if (isCurrent()) dispatch({ type: "notice", text: safeErrorMessage(error, t("commandFailed")) });
    } finally {
      commandInFlightRef.current = false;
    }
  }, [api, hasOwner, isMounted, persist, refreshCatalog, refreshRuntimeStatus, runtimeGeneration, send, t, waitForRuntimeUserAccess]);

  const cancelCompaction = useCallback(async () => {
    if (cancelInFlightRef.current) return;
    const current = stateRef.current;
    const operationId = current.compactionStatus.operation_id;
    const sessionId = current.selectedSessionId;
    if (!api || current.compactionStatus.state !== "running" || !operationId || !sessionId) return;
    if ((hasOwner() || current.runtimeState === "restarting")
      && (!(await waitForRuntimeUserAccess()) || hasOwner() || stateRef.current.runtimeState === "restarting")) return;
    const latest = stateRef.current;
    if (latest.compactionStatus.state !== "running"
      || latest.compactionStatus.operation_id !== operationId
      || latest.selectedSessionId !== sessionId) return;
    cancelInFlightRef.current = true;
    try {
      const result = asObject(await send("compaction.cancel", { session_id: sessionId, operation_id: operationId }));
      if (result.accepted !== true && isMounted()) {
        dispatch({ type: "notice", text: t("compactionCancelFailed") });
      }
    } catch (error) {
      if (isMounted()) dispatch({ type: "notice", text: safeErrorMessage(error, t("compactionCancelFailed")) });
    } finally {
      cancelInFlightRef.current = false;
    }
  }, [api, hasOwner, isMounted, send, t, waitForRuntimeUserAccess]);

  const importAttachmentInput = useCallback(async (input: DesktopAttachmentInput) => {
    if (!api || !isMounted() || stateRef.current.activeTurn) return;
    const owner = {
      generation: runtimeGeneration(),
      projectKey: stateRef.current.selectedProjectKey,
      sessionId: stateRef.current.selectedSessionId,
      viewRevision: stateRef.current.sessionViewRevision,
    };
    const ownsAttachment = () => {
      const current = stateRef.current;
      return isMounted()
        && runtimeGeneration() === owner.generation
        && current.selectedProjectKey === owner.projectKey
        && current.sessionViewRevision === owner.viewRevision
        && (owner.sessionId === null || current.selectedSessionId === owner.sessionId);
    };
    try {
      const result = asObject(await send("attachment.import", {
        name: input.name,
        mime_type: input.mime_type,
        data_base64: input.data_base64,
      }));
      if (!ownsAttachment()) return;
      const draft = attachmentDraftFromResult(asObject(result).attachment);
      if (!draft) {
        dispatch({ type: "notice", text: t("attachmentImportFailed") });
        return;
      }
      // Preview is a separate bounded request.  A preview failure must not
      // discard the durable imported original or make the draft uneditable.
      try {
        const preview = asObject(await send("attachment.preview", { ref: draft.ref }));
        if (!ownsAttachment()) return;
        const withPreview = attachmentDraftFromResult({ ...draft, ...asObject(asObject(preview).attachment) });
        dispatch({ type: "composer_attachment_added", attachment: withPreview ?? draft });
      } catch {
        if (!ownsAttachment()) return;
        dispatch({ type: "composer_attachment_added", attachment: draft });
      }
    } catch (error) {
      if (ownsAttachment()) dispatch({ type: "notice", text: safeErrorMessage(error, t("attachmentImportFailed")) });
    }
  }, [api, isMounted, runtimeGeneration, send, t]);

  const chooseAttachment = useCallback(async () => {
    if (!api || stateRef.current.activeTurn) return;
    try {
      const input = await api.chooseAttachment();
      if (input) await importAttachmentInput(input);
    } catch (error) {
      if (isMounted()) dispatch({ type: "notice", text: safeErrorMessage(error, t("attachmentImportFailed")) });
    }
  }, [api, importAttachmentInput, isMounted, t]);

  const pasteAttachment = useCallback(async () => {
    if (!api || stateRef.current.activeTurn) return;
    try {
      const input = await api.pasteAttachment();
      if (input) await importAttachmentInput(input);
    } catch (error) {
      if (isMounted()) dispatch({ type: "notice", text: safeErrorMessage(error, t("attachmentImportFailed")) });
    }
  }, [api, importAttachmentInput, isMounted, t]);

  const importDroppedAttachment = useCallback(async (file: File) => {
    if (stateRef.current.activeTurn || file.size <= 0) return;
    try {
      const data = new Uint8Array(await file.arrayBuffer());
      await importAttachmentInput({
        name: file.name || "attachment",
        mime_type: file.type || "application/octet-stream",
        data_base64: bytesToBase64(data),
      });
    } catch (error) {
      if (isMounted()) dispatch({ type: "notice", text: safeErrorMessage(error, t("attachmentImportFailed")) });
    }
  }, [importAttachmentInput, isMounted, t]);

  const removeAttachment = useCallback(async (ref: string) => {
    if (!api || !ref || stateRef.current.activeTurn) return;
    try {
      await send("attachment.remove", { ref });
      dispatch({ type: "composer_attachment_removed", ref });
    } catch (error) {
      // FileCard owns attachment action errors so the draft remains visible
      // beside the action that failed.  Do not turn this local failure into a
      // global timeline notice.
      throw error;
    }
  }, [api, send]);

  const previewAttachment = useCallback(async (ref: string, mode: FilePreviewMode = "thumbnail"): Promise<DesktopAttachmentDraft | null> => {
    if (!api || !ref) return null;
    const owner = {
      generation: runtimeGeneration(),
      projectKey: stateRef.current.selectedProjectKey,
      sessionId: stateRef.current.selectedSessionId,
      viewRevision: stateRef.current.sessionViewRevision,
    };
    try {
      const result = asObject(await send("attachment.preview", { ref, mode }));
      const current = stateRef.current;
      if (!isMounted() || runtimeGeneration() !== owner.generation || current.selectedProjectKey !== owner.projectKey || current.selectedSessionId !== owner.sessionId || current.sessionViewRevision !== owner.viewRevision) return null;
      return attachmentDraftFromResult(asObject(result).attachment);
    } catch (error) {
      const current = stateRef.current;
      if (!isMounted() || current.selectedProjectKey !== owner.projectKey || current.selectedSessionId !== owner.sessionId || current.sessionViewRevision !== owner.viewRevision) return null;
      throw error;
    }
  }, [api, isMounted, runtimeGeneration, send]);

  const openAttachment = useCallback(async (ref: string) => {
    if (!api || !ref) return;
    await send("attachment.open", { ref });
  }, [api, send]);

  const revealAttachment = useCallback(async (ref: string) => {
    if (!api || !ref) return;
    await send("attachment.reveal", { ref });
  }, [api, send]);

  const submitComposer = useCallback(async (text: string) => {
    const invokedState = stateRef.current;
    const submissionOwner = {
      mode: invokedState.mode,
      projectKey: invokedState.selectedProjectKey,
      sessionId: invokedState.selectedSessionId,
      viewRevision: invokedState.sessionViewRevision,
      runtimeGeneration: runtimeGeneration(),
    };
    const selectedAttachments = invokedState.mode === "coding" && !invokedState.activeTurn
      ? invokedState.composerAttachments.map((attachment) => ({ ...attachment }))
      : [];
    const ownsSubmissionOwner = () => {
      const current = stateRef.current;
      return isMounted()
        && runtimeGeneration() === submissionOwner.runtimeGeneration
        && current.mode === submissionOwner.mode
        && current.selectedProjectKey === submissionOwner.projectKey
        && current.selectedSessionId === submissionOwner.sessionId
        && current.sessionViewRevision === submissionOwner.viewRevision;
    };
    const isCompactionRunning = () => (stateRef.current.compactionStatus.state as string) === "running";
    if (!api || !isMounted() || (!text.trim() && selectedAttachments.length === 0) || pendingTurnStart() || invokedState.pendingInteraction || invokedState.terminalStatusPending || isCompactionRunning()) return;
    const selectedProjectKey = submissionOwner.projectKey;
    const selectedSessionId = submissionOwner.sessionId;
    const preparation = selectedProjectKey && selectedSessionId
      ? stateRef.current.sessionPreparation[sessionRuntimeKey(selectedProjectKey, selectedSessionId)]
      : undefined;
    // Slash commands remain available for status/recovery while a cold
    // Session is preparing. Ordinary Turns must wait for its Application/Run
    // owner to finish recovery so they cannot race a second writer.
    if (!text.trimStart().startsWith("/") && preparation !== undefined && preparation !== "ready") return;
    if ((hasOwner() || stateRef.current.runtimeState === "restarting")
      && (!(await waitForRuntimeUserAccess()) || hasOwner() || stateRef.current.runtimeState === "restarting" || !ownsSubmissionOwner())) return;
    if (!ownsSubmissionOwner() || pendingTurnStart() || stateRef.current.pendingInteraction || stateRef.current.terminalStatusPending || isCompactionRunning()) return;
    if (text.trimStart().startsWith("/")) {
      await executeCommand(text.trim());
      return;
    }
    const submissionProjectKey = submissionOwner.projectKey;
    const submissionSessionId = submissionOwner.sessionId;
    const submissionGeneration = submissionOwner.runtimeGeneration;
    const submissionViewRevision = submissionOwner.viewRevision;
    const submissionMode = submissionOwner.mode;
    const submissionText = text;
    const submissionAttachmentRefs = selectedAttachments.map((attachment) => attachment.ref);
    const submissionDraftRevision = stateRef.current.composerDraftRevisions[composerDraftOwnerKey(submissionMode, submissionProjectKey, submissionSessionId)] ?? 0;
    const steering = invokedState.activeTurn;
    const steeringIdentity = steering ? identityFromRun(invokedState.run) : null;
    const clearPendingSteeringIdentity = () => {
      if (steering && steeringIdentity && hasCompleteTurnIdentity(steeringIdentity)) {
        dispatch({ type: "steering_submission_failed", runId: steeringIdentity.runId, turnId: steeringIdentity.turnId });
      }
    };
    const pendingStart = steering ? null : beginPendingTurnStart();
    const replayPendingBackgroundEvents = () => {
      if (!pendingStart || pendingTurnStart() !== pendingStart) return;
      finishPendingTurnStart(pendingStart).forEach((event) => {
        const eventSessionId = stringValue(event.session_id);
        const eventProjectKey = stringValue(event.project_key);
        if ((eventSessionId && eventSessionId !== submissionSessionId)
          || (eventProjectKey && eventProjectKey !== submissionProjectKey)) processAgentEvent(event);
      });
    };
    try {
      const result = steering
        ? await send("turn.steer", { text })
        : await send("turn.start", {
          prompt: text,
          ...(selectedAttachments.length > 0 ? {
            attachments: selectedAttachments.map((attachment) => ({
              ref: attachment.ref,
              kind: attachment.mime_type.startsWith("image/") ? "image" : "file",
            })),
          } : {}),
        });
      if (!isMounted() || (pendingStart && pendingTurnStart() !== pendingStart)) return;
      const acceptedRun = steering ? asObject(result).run : result;
      const acceptedIdentity = identityFromRun(acceptedRun);
      const latestState = stateRef.current;
      const stillOwnsSubmission = latestState.selectedProjectKey === submissionProjectKey
        && latestState.selectedSessionId === submissionSessionId
        && latestState.mode === submissionMode
        && latestState.sessionViewRevision === submissionViewRevision
        && runtimeGeneration() === submissionGeneration;
      const returnedSessionId = !steering ? stringValue(asObject(result).session_id) : null;
      const selectedSessionMismatch = Boolean(returnedSessionId && submissionSessionId && returnedSessionId !== submissionSessionId);
      if (!stillOwnsSubmission || selectedSessionMismatch) {
        // Navigation may move the visible composer while turn.start is in
        // flight. Retire only the exact draft version that this accepted Run
        // captured; never project its Run or clear the newly selected owner.
        if (!steering
          && runtimeBusinessErrorKind(result) !== "image_input_unsupported"
          && hasCompleteTurnIdentity(acceptedIdentity)) {
          dispatch({
            type: "submission_committed_offscreen",
            submission: {
              mode: submissionMode,
              projectKey: submissionProjectKey,
              sessionId: submissionSessionId,
              draftRevision: submissionDraftRevision,
              text: submissionText,
              attachmentRefs: submissionAttachmentRefs,
              ...(!submissionSessionId && submissionProjectKey && returnedSessionId ? { acceptedSessionId: returnedSessionId } : {}),
            },
          });
        }
        if (pendingStart && pendingTurnStart() === pendingStart) {
          finishPendingTurnStart(pendingStart).forEach((event) => processAgentEvent(event));
        }
        if (steering) clearPendingSteeringIdentity();
        if (returnedSessionId && submissionProjectKey && latestState.selectedProjectKey === submissionProjectKey) {
          void refreshCatalog(submissionProjectKey, "session_new", returnedSessionId);
        }
        return;
      }
      if (!steering && runtimeBusinessErrorKind(result) === "image_input_unsupported") {
        replayPendingBackgroundEvents();
        dispatch({ type: "notice", text: t("turnImageInputUnsupported") });
        return;
      }
      // Bridge `turn.start` returns a flat Run DTO; only `turn.steer` wraps
      // that DTO under `run`. Keep the shapes separate and require both
      // identity components before taking poll ownership.
      if (!hasCompleteTurnIdentity(acceptedIdentity)) {
        replayPendingBackgroundEvents();
        clearPendingSteeringIdentity();
        dispatch({ type: "notice", text: t("turnStartFailed") });
        return;
      }
      const lazySessionId = !steering && !submissionSessionId && submissionProjectKey ? returnedSessionId : null;
      const acceptedSession = lazySessionId
        ? {
          sessionId: lazySessionId,
          projectKey: submissionProjectKey as string,
          runId: acceptedIdentity.runId,
          turnId: acceptedIdentity.turnId,
          runtimeGeneration: submissionGeneration,
          viewRevision: submissionViewRevision,
        }
        : undefined;
      const bufferedEvents = pendingStart ? finishPendingTurnStart(pendingStart) : [];
      // This is the accepted Application boundary. Establish ownership
      // before Core events arrive, then retire any poll for the replaced Run;
      // an arbitrary turn_started event cannot do this job safely.
      setLatestTurnIdentity(acceptedIdentity);
      cancelTerminalStatusPoll();
      dispatch({
        type: "turn_accepted",
        run: acceptedRun,
        steering,
        text,
        submission: {
          mode: submissionMode,
          projectKey: submissionProjectKey,
          sessionId: submissionSessionId,
          viewRevision: submissionViewRevision,
          draftRevision: submissionDraftRevision,
          text: submissionText,
          attachmentRefs: submissionAttachmentRefs,
        },
        ...(lazySessionId ? { sessionId: lazySessionId } : {}),
        ...(!steering && selectedAttachments.length > 0
          ? {
            attachments: selectedAttachments.map(timelineAttachmentFromDraft),
            submittedAttachmentRefs: selectedAttachments.map((attachment) => attachment.ref),
          }
          : {}),
      });
      if (lazySessionId) {
        if (submissionMode === "coding") void persist("selectedSessionId", lazySessionId);
        void refreshCatalog(submissionProjectKey as string, "session_new", lazySessionId);
      }
      // Replaying after the accepted action preserves the exact stdout order
      // while the reducer queue applies turn_accepted before its events.
      bufferedEvents.forEach((event) => processAgentEvent(
        event,
        acceptedSession && eventMatchesIdentity(event, acceptedIdentity) ? acceptedSession : undefined,
      ));
    } catch (error) {
      if (!isMounted() || (pendingStart && pendingTurnStart() !== pendingStart)) return;
      replayPendingBackgroundEvents();
      clearPendingSteeringIdentity();
      const latestState = stateRef.current;
      const stillOwnsSubmission = latestState.selectedProjectKey === submissionProjectKey
        && latestState.selectedSessionId === submissionSessionId
        && latestState.mode === submissionMode
        && latestState.sessionViewRevision === submissionViewRevision
        && runtimeGeneration() === submissionGeneration;
      if (stillOwnsSubmission) dispatch({ type: "notice", text: safeErrorMessage(error, t("turnStartFailed")) });
    }
  }, [api, beginPendingTurnStart, cancelTerminalStatusPoll, clearPendingTurnStart, executeCommand, finishPendingTurnStart, hasOwner, isMounted, pendingTurnStart, persist, processAgentEvent, refreshCatalog, runtimeGeneration, send, setLatestTurnIdentity, t, waitForRuntimeUserAccess]);

  const completeCommand = useCallback(async (prefix: string) => {
    if (!api || !prefix.trimStart().startsWith("/")) return;
    if ((hasOwner() || stateRef.current.runtimeState === "restarting")
      && (!(await waitForRuntimeUserAccess()) || hasOwner() || stateRef.current.runtimeState === "restarting")) return;
    const generation = runtimeGeneration();
    const isCurrent = () => isMounted() && runtimeGeneration() === generation && !hasOwner();
    if (!isCurrent()) return;
    try {
      const result = await send("command.complete", { prefix });
      if (!isCurrent()) return;
      dispatch({ type: "command_candidates", result });
    } catch {
      if (isCurrent()) dispatch({ type: "command_candidates", result: { candidates: [], argument_candidates: [] } });
    }
  }, [api, hasOwner, isMounted, runtimeGeneration, send, waitForRuntimeUserAccess]);

  const sendInteraction = useCallback(async (response: JsonObject) => {
    const pending = stateRef.current.pendingInteraction;
    if (!api || !pending || interactionSubmitRef.current === pending.pauseId) return;
    if ((hasOwner() || stateRef.current.runtimeState === "restarting")
      && (!(await waitForRuntimeUserAccess()) || hasOwner() || stateRef.current.runtimeState === "restarting")) return;
    if (!stateRef.current.pendingInteraction || stateRef.current.pendingInteraction.pauseId !== pending.pauseId) return;
    interactionSubmitRef.current = pending.pauseId;
    dispatch({ type: "interaction_submitting", value: true });
    try {
      await send("turn.resume", { response });
    } catch (error) {
      dispatch({ type: "interaction_submitting", value: false });
      dispatch({ type: "notice", text: safeErrorMessage(error, t("interactionSubmitFailed")) });
    } finally {
      if (interactionSubmitRef.current === pending.pauseId) interactionSubmitRef.current = null;
    }
  }, [api, hasOwner, send, waitForRuntimeUserAccess]);

  const cancelTurn = useCallback(async () => {
    if (cancelInFlightRef.current) return;
    clearPendingTurnStart();
    if (!api) return;
    if ((hasOwner() || stateRef.current.runtimeState === "restarting")
      && (!(await waitForRuntimeUserAccess()) || hasOwner() || stateRef.current.runtimeState === "restarting")) return;
    if (cancelInFlightRef.current) return;
    cancelInFlightRef.current = true;
    try {
      await send("turn.cancel", {});
    } catch (error) {
      dispatch({ type: "notice", text: safeErrorMessage(error, t("turnCancelFailed")) });
    } finally {
      cancelInFlightRef.current = false;
    }
  }, [api, clearPendingTurnStart, hasOwner, send, waitForRuntimeUserAccess]);

  const pauseTurn = useCallback(async () => {
    if (!api) return;
    if ((hasOwner() || stateRef.current.runtimeState === "restarting")
      && (!(await waitForRuntimeUserAccess()) || hasOwner() || stateRef.current.runtimeState === "restarting")) return;
    try {
      await send("turn.pause", {});
    } catch (error) {
      dispatch({ type: "notice", text: safeErrorMessage(error, t("turnPauseFailed")) });
    }
  }, [api, hasOwner, send, waitForRuntimeUserAccess]);

  const setTheme = useCallback((theme: ThemePreference) => {
    if (stateRef.current.settingsSaving || settingsSaveInFlightRef.current) return;
    dispatch({ type: "set_theme", theme });
    void persist("theme", theme);
  }, [persist]);

  const setPanelMode = useCallback((panelMode: PanelModePreference) => {
    dispatch({ type: "set_panel_mode", panelMode });
    // Focus Mode is transient. Any defensive presentation callback that
    // arrives while it is active must not turn that transient state into a
    // durable panel preference.
    if (!stateRef.current.focusMode) void persist("panelMode", panelMode);
  }, [persist]);

  const setSidebarWidth = useCallback((width: number, commit = false) => {
    const bounds = typeof window === "undefined"
      ? { min: SIDEBAR_WIDTH_MIN, max: SIDEBAR_WIDTH_MAX }
      : layoutWidthBounds(window.innerWidth, stateRef.current.panelMode, stateRef.current.sidebarWidth, stateRef.current.runtimePanelWidth).sidebar;
    const next = clampLayoutWidth(width, bounds);
    dispatch({ type: "set_sidebar_width", width: next });
    if (commit && !stateRef.current.focusMode) void persist("sidebarWidth", next);
  }, [persist]);

  const setRuntimePanelWidth = useCallback((width: number, commit = false) => {
    const bounds = typeof window === "undefined"
      ? { min: RUNTIME_PANEL_WIDTH_MIN, max: RUNTIME_PANEL_WIDTH_MAX }
      : layoutWidthBounds(window.innerWidth, stateRef.current.panelMode, stateRef.current.sidebarWidth, stateRef.current.runtimePanelWidth).runtime;
    const next = clampLayoutWidth(width, bounds);
    dispatch({ type: "set_runtime_panel_width", width: next });
    if (commit && !stateRef.current.focusMode) void persist("runtimePanelWidth", next);
  }, [persist]);

  const setFocusMode = useCallback((value: boolean) => {
    dispatch({ type: "set_focus_mode", value });
  }, []);

  const restoreRuntimeToggleFocus = useCallback(() => {
    runtimeToggleRef.current?.focus();
  }, []);

  const closeRuntimeDrawer = useCallback(() => {
    setPanelMode("hidden");
    restoreRuntimeToggleFocus();
  }, [restoreRuntimeToggleFocus, setPanelMode]);

  const setProjectExpanded = useCallback((projectKey: string, expanded: boolean) => {
    // Expansion is navigation metadata only.  Accept updates from rendered
    // Project rows, but never let an arbitrary key become a trusted Project.
    if (!stateRef.current.projects.some((project) => project.projectKey === projectKey)) return;
    const expandedProjects = { ...stateRef.current.expandedProjects, [projectKey]: expanded };
    dispatch({ type: "hydrate_preferences", preferences: { expandedProjects } });
    void persist("expandedProjects", expandedProjects);
  }, [persist]);

  const setProjectDisclosure = useCallback((projectKey: string, expanded: boolean) => {
    if (expanded) void refreshProjectCatalog(projectKey);
  }, [refreshProjectCatalog]);

  const aliasChange = useCallback((projectKey: string, alias: string) => {
    const projects = stateRef.current.projects.map((project) => project.projectKey === projectKey ? { ...project, alias } : project);
    dispatch({ type: "hydrate_preferences", preferences: { recentProjects: projectPreferences(projects), projectAliases: Object.fromEntries(projects.map((project) => [project.projectKey, project.alias])) } });
    void persist("recentProjects", projectPreferences(projects));
    void persist("projectAliases", Object.fromEntries(projects.map((project) => [project.projectKey, project.alias])));
  }, [persist]);

  const togglePin = useCallback((project: ProjectState) => {
    const { projects, pinnedSessions } = projectPinPlan(stateRef.current.projects, stateRef.current.pinnedSessions, project.projectKey);
    dispatch({ type: "hydrate_preferences", preferences: { recentProjects: projectPreferences(projects), pinnedProjectKeys: projects.filter((item) => item.pinned).map((item) => item.projectKey), pinnedSessions } });
    void persist("recentProjects", projectPreferences(projects));
    void persist("pinnedProjectKeys", projects.filter((item) => item.pinned).map((item) => item.projectKey));
    void persist("pinnedSessions", pinnedSessions);
  }, [persist]);
  const setLanguage = useCallback((language: LanguagePreference) => {
    if (stateRef.current.settingsSaving || settingsSaveInFlightRef.current) return;
    dispatch({ type: "hydrate_preferences", preferences: { language } });
    void persist("language", language);
  }, [persist]);

  const toggleSessionPin = useCallback((project: ProjectState, session: SessionSummary) => {
    // A pinned Project is the sole navigation owner of its child Sessions;
    // keep the preference invariant even if a caller bypasses the menu.
    if (project.pinned) return;
    const current = stateRef.current.pinnedSessions;
    const exists = current.some((item) => item.projectKey === project.projectKey && item.sessionId === session.session_id);
    const pinnedSessions = exists
      ? current.filter((item) => item.projectKey !== project.projectKey || item.sessionId !== session.session_id)
      : [...current, { projectKey: project.projectKey, sessionId: session.session_id }];
    dispatch({ type: "hydrate_preferences", preferences: { pinnedSessions } });
    void persist("pinnedSessions", pinnedSessions);
  }, [persist]);

  const renameSession = useCallback(async (project: ProjectState, session: SessionSummary, title: string) => {
    if (stateRef.current.activeTurn || stateRef.current.terminalStatusPending) {
      dispatch({ type: "notice", text: t("sessionRenameActive") });
      return;
    }
    const mutation = beginSessionMutation();
    if (!mutation) return;
    const { sequence, generation: mutationGeneration } = mutation;
    const runtimeGenerationAtStart = runtimeGeneration();
    try {
      if ((hasOwner() || stateRef.current.runtimeState === "restarting")
        && (!(await waitForRuntimeUserAccess()) || hasOwner() || stateRef.current.runtimeState === "restarting")) return;
      if (!isMounted() || sessionMutationInFlightRef.current !== sequence || sessionMutationGenerationRef.current !== mutationGeneration || runtimeGeneration() !== runtimeGenerationAtStart) {
        await reconcileSessionMutation(project.projectKey, sequence);
        return;
      }
      const result = await send("session.rename", { session_id: session.session_id, title });
      const current = isMounted()
        && sessionMutationInFlightRef.current === sequence
        && sessionMutationGenerationRef.current === mutationGeneration
        && runtimeGeneration() === runtimeGenerationAtStart
        && !hasOwner();
      if (current) dispatch({ type: "session_mutated", sourceProjectKey: project.projectKey, result });
      else await reconcileSessionMutation(project.projectKey, sequence);
    } catch (error) {
      await reconcileSessionMutation(project.projectKey, sequence);
      if (isMounted() && sessionMutationInFlightRef.current === sequence) {
        dispatch({ type: "notice", text: safeErrorMessage(error, t("sessionRenameFailed")) });
      }
    } finally {
      endSessionMutation(sequence);
    }
  }, [beginSessionMutation, endSessionMutation, hasOwner, isMounted, reconcileSessionMutation, runtimeGeneration, send, t, waitForRuntimeUserAccess]);

  const moveSession = useCallback(async (project: ProjectState, session: SessionSummary, target: ProjectState) => {
    if (stateRef.current.activeTurn || stateRef.current.terminalStatusPending) {
      dispatch({ type: "notice", text: t("sessionMoveActive") });
      return;
    }
    const mutation = beginSessionMutation();
    if (!mutation) return;
    const { sequence, generation: mutationGeneration } = mutation;
    const runtimeGenerationAtStart = runtimeGeneration();
    try {
      if ((hasOwner() || stateRef.current.runtimeState === "restarting")
        && (!(await waitForRuntimeUserAccess()) || hasOwner() || stateRef.current.runtimeState === "restarting")) return;
      if (!isMounted() || sessionMutationInFlightRef.current !== sequence || sessionMutationGenerationRef.current !== mutationGeneration || runtimeGeneration() !== runtimeGenerationAtStart) {
        await reconcileSessionMutation(project.projectKey, sequence);
        return;
      }
      const result = await send("session.move", { session_id: session.session_id, target_project_key: target.projectKey });
      const current = isMounted()
        && sessionMutationInFlightRef.current === sequence
        && sessionMutationGenerationRef.current === mutationGeneration
        && runtimeGeneration() === runtimeGenerationAtStart
        && !hasOwner();
      if (!current) {
        await reconcileSessionMutation(project.projectKey, sequence);
        return;
      }
      dispatch({ type: "session_mutated", sourceProjectKey: project.projectKey, result });
      const pinnedSessions = stateRef.current.pinnedSessions.map((item) => item.projectKey === project.projectKey && item.sessionId === session.session_id ? { ...item, projectKey: target.projectKey } : item);
      await persist("pinnedSessions", pinnedSessions);
      if (!isMounted() || sessionMutationInFlightRef.current !== sequence || sessionMutationGenerationRef.current !== mutationGeneration || runtimeGeneration() !== runtimeGenerationAtStart || hasOwner()) {
        await reconcileSessionMutation(project.projectKey, sequence);
        return;
      }
      if (stateRef.current.selectedProjectKey === project.projectKey) await refreshCatalog(project.projectKey);
    } catch (error) {
      await reconcileSessionMutation(project.projectKey, sequence);
      if (isMounted() && sessionMutationInFlightRef.current === sequence) {
        dispatch({ type: "notice", text: safeErrorMessage(error, t("sessionMoveFailed")) });
      }
    } finally {
      endSessionMutation(sequence);
    }
  }, [beginSessionMutation, endSessionMutation, hasOwner, isMounted, persist, reconcileSessionMutation, refreshCatalog, runtimeGeneration, send, t, waitForRuntimeUserAccess]);

  const archiveSession = useCallback(async (project: ProjectState, session: SessionSummary, archived: boolean): Promise<boolean> => {
    if (!api || !session.session_id) return false;
    const before = stateRef.current;
    const selectedTarget = before.selectedProjectKey === project.projectKey && before.selectedSessionId === session.session_id;
    if (session.runtime_status === "running" || session.runtime_status === "waiting"
      || (selectedTarget && (before.activeTurn || before.terminalStatusPending))) {
      dispatch({ type: "notice", text: t("sessionMutationBusy") });
      return false;
    }
    const mutation = beginSessionMutation();
    if (!mutation) return false;
    const { sequence, generation: mutationGeneration } = mutation;
    const runtimeGenerationAtStart = runtimeGeneration();
    const expected = {
      mode: before.mode,
      projectKey: before.selectedProjectKey,
      sessionId: before.selectedSessionId,
      revision: before.sessionViewRevision,
    };
    const ownsNavigation = () => {
      const current = stateRef.current;
      return runtimeGeneration() === runtimeGenerationAtStart
        && current.mode === expected.mode
        && current.selectedProjectKey === expected.projectKey
        && current.selectedSessionId === expected.sessionId
        && current.sessionViewRevision === expected.revision;
    };
    let navigateTo: { project: ProjectState; sessionId: string } | null = null;
    let clearArchivedCurrent = false;
    try {
      if ((hasOwner() || stateRef.current.runtimeState === "restarting")
        && (!(await waitForRuntimeUserAccess()) || hasOwner() || stateRef.current.runtimeState === "restarting")) return false;
      if (!isMounted() || sessionMutationInFlightRef.current !== sequence || sessionMutationGenerationRef.current !== mutationGeneration || runtimeGeneration() !== runtimeGenerationAtStart) return false;
      const result = await send("session.archive", {
        session_id: session.session_id,
        project_key: project.projectKey,
        archived,
      });
      if (!isMounted() || sessionMutationInFlightRef.current !== sequence) return false;
      dispatch({ type: "session_mutated", sourceProjectKey: project.projectKey, result });
      // The archive/restore has already committed. Refresh that project's
      // durable catalog even if navigation changed while the request ran;
      // only the optional follow-up navigation belongs to the captured view.
      const catalog = asObject(await send("project.sessions", { project_key: project.projectKey, archived: false }));
      if (!isMounted() || sessionMutationInFlightRef.current !== sequence) return true;
      const sessions = Array.isArray(catalog.sessions) ? catalog.sessions : [];
      dispatch({ type: "catalog_refreshed", projectKey: project.projectKey, sessions, reason: "catalog_refresh" });
      if (!ownsNavigation()) return true;
      if (selectedTarget && archived) {
        const nextId = sessions.map((value) => asObject(value)).find((value) => value.archived !== true && value.corrupt !== true && typeof value.session_id === "string")?.session_id;
        if (typeof nextId === "string") {
          navigateTo = { project, sessionId: nextId };
        } else {
          clearArchivedCurrent = true;
        }
      }
      return true;
    } catch (error) {
      if (isMounted() && sessionMutationInFlightRef.current === sequence) {
        dispatch({ type: "notice", text: safeErrorMessage(error, t("sessionArchiveFailed")) });
      }
      return false;
    } finally {
      endSessionMutation(sequence);
      if (clearArchivedCurrent && isMounted() && ownsNavigation()) {
        dispatch({ type: "session_archived_current", projectKey: project.projectKey, sessionId: session.session_id });
      }
      if (navigateTo && isMounted() && ownsNavigation()) await resumeSession(navigateTo.project, navigateTo.sessionId);
    }
  }, [api, beginSessionMutation, endSessionMutation, hasOwner, isMounted, resumeSession, runtimeGeneration, send, t, waitForRuntimeUserAccess]);

  const restoreSearchHit = useCallback(async (hit: SessionSearchHit) => {
    const before = stateRef.current;
    const expected = {
      mode: before.mode,
      projectKey: before.selectedProjectKey,
      sessionId: before.selectedSessionId,
      revision: before.sessionViewRevision,
      generation: runtimeGeneration(),
    };
    const ownsNavigation = () => {
      const current = stateRef.current;
      return isMounted()
        && runtimeGeneration() === expected.generation
        && current.mode === expected.mode
        && current.selectedProjectKey === expected.projectKey
        && current.selectedSessionId === expected.sessionId
        && current.sessionViewRevision === expected.revision;
    };
    const existing = stateRef.current.projects.find((item) => item.projectKey === hit.project_key);
    const project: ProjectState | null = existing ?? (hit.project_key === GENERAL_PROJECT_KEY ? {
      path: GENERAL_PROJECT_KEY,
      projectKey: GENERAL_PROJECT_KEY,
      alias: t("generalMode"),
      pinned: false,
      sessions: [],
      catalogFresh: false,
    } : null);
    if (!project) return;
    const session = project.sessions.find((item) => item.session_id === hit.session_id) ?? {
      session_id: hit.session_id,
      project_key: hit.project_key,
      archived: true,
    };
    if (await archiveSession(project, session, false) && ownsNavigation()) await resumeSession(project, hit.session_id);
  }, [archiveSession, isMounted, resumeSession, runtimeGeneration, t]);

  const copyText = useCallback(async (text: string) => {
    if (!api) throw new Error("Desktop API is unavailable");
    await api.copyText(text);
  }, [api]);

  const copyAttachmentPath = useCallback(async (ref: string) => {
    // Attachment refs are opaque Session identities.  Ask the Bridge to
    // resolve the current Session-owned derived copy and let Main write the
    // trusted path to the clipboard; the Renderer never receives or copies a
    // filesystem path for an attachment.
    await send("attachment.copy_path", { ref });
  }, [send]);

  const copySessionId = useCallback(async (session: SessionSummary) => {
    try {
      await copyText(session.session_id);
      dispatch({ type: "notice", text: t("copiedSessionId") });
    } catch (error) {
      dispatch({ type: "notice", text: safeErrorMessage(error, t("copySessionIdFailed")) });
    }
  }, [copyText, t]);

  const openArtifact = useCallback(async (path: string) => {
    await send("artifact.open", { path });
  }, [send]);

  const artifactDescriptor = useCallback((value: unknown): ArtifactDescriptor | null => {
    const result = asObject(value);
    const artifact = asObject(result.artifact);
    if (typeof artifact.path !== "string" || typeof artifact.name !== "string" || typeof artifact.kind !== "string" || typeof artifact.mime_type !== "string" || typeof artifact.size_bytes !== "number" || typeof artifact.preview_supported !== "boolean") return null;
    return {
      path: artifact.path,
      name: artifact.name,
      kind: artifact.kind,
      mime_type: artifact.mime_type,
      size_bytes: artifact.size_bytes,
      default_action: typeof artifact.default_action === "string" ? artifact.default_action : "open",
      preview_supported: artifact.preview_supported,
      ...(typeof artifact.preview_kind === "string" ? { preview_kind: artifact.preview_kind } : {}),
      ...(typeof artifact.text === "string" ? { text: artifact.text } : {}),
      ...(artifact.truncated === true ? { truncated: true } : {}),
      ...(typeof artifact.data_url === "string" && /^data:[^,]+,/.test(artifact.data_url) ? { data_url: artifact.data_url } : {}),
    };
  }, []);

  const describeArtifact = useCallback(async (path: string): Promise<ArtifactDescriptor | null> => {
    try {
      const descriptor = artifactDescriptor(await send("artifact.describe", { path }));
      if (!descriptor) throw new Error("invalid artifact descriptor");
      return descriptor;
    } catch {
      return null;
    }
  }, [artifactDescriptor, send]);

  const authorizeExternalArtifact = useCallback(async (_path: string): Promise<ArtifactDescriptor | null> => {
    if (!api?.authorizeExternalArtifact) return null;
    try {
      const selected = await api.authorizeExternalArtifact();
      if (!selected) return null;
      const descriptor = artifactDescriptor(await send("artifact.describe", { path: selected }));
      if (!descriptor) throw new Error("invalid authorized artifact descriptor");
      return descriptor;
    } catch {
      return null;
    }
  }, [api, artifactDescriptor, send]);

  const revealArtifact = useCallback(async (path: string) => {
    await send("artifact.reveal", { path });
  }, [send]);

  const previewArtifact = useCallback(async (path: string, mode?: FilePreviewMode): Promise<ArtifactDescriptor | null> => {
    const descriptor = artifactDescriptor(await send("artifact.preview", { path, mode: mode ?? "full" }));
    if (!descriptor) throw new Error("invalid artifact preview");
    return descriptor;
  }, [artifactDescriptor, send]);

  const openDocumentPreview = useCallback((preview: DocumentPreview) => {
    const owner = reviewOwner();
    const onOpen = preview.onOpen;
    const ownedPreview: DocumentPreview = {
      ...preview,
      owner,
      onOpen: onOpen
        ? async () => {
          if (!reviewOwnerMatches(owner)) return;
          await onOpen();
        }
        : undefined,
    };
    const id = `document:${String(preview.asset.ref ?? preview.asset.path ?? preview.asset.display_name ?? preview.asset.name ?? "file")}`;
    const tab: ReviewPanelTab = { kind: "document", id, title: String(preview.asset.display_name ?? preview.asset.name ?? preview.asset.path ?? t("filePreview")), owner, preview: ownedPreview };
    updateReviewPanel((current) => ({ tabs: [...current.tabs.filter((item) => item.id !== id), tab], activeTabId: id }));
  }, [reviewOwner, reviewOwnerMatches, t, updateReviewPanel]);

  const cancelWorkspaceDiff = useCallback((context = workspaceDiffContextRef.current) => {
    if (!context || workspaceDiffContextRef.current !== context) return;
    workspaceDiffContextRef.current = null;
    earlyWorkspaceDiffEventsRef.current.clear();
    if (context.operationId) void send("workspace.diff.cancel", { operation_id: context.operationId }).catch(() => undefined);
  }, [send]);

  const closeReviewTab = useCallback((id: string) => {
    const tab = reviewPanelRef.current.tabs.find((item) => item.id === id);
    if (tab?.kind === "workspace-diff" && workspaceDiffContextRef.current?.tabId === id) cancelWorkspaceDiff();
    updateReviewPanel((current) => {
      const tabs = current.tabs.filter((item) => item.id !== id);
      const activeTabId = current.activeTabId === id ? tabs.at(-1)?.id ?? null : current.activeTabId;
      return { tabs, activeTabId };
    });
  }, [cancelWorkspaceDiff, updateReviewPanel]);

  const closeReviewPanel = useCallback(() => {
    cancelWorkspaceDiff();
    earlyWorkspaceDiffEventsRef.current.clear();
    updateReviewPanel(() => ({ tabs: [], activeTabId: null }));
  }, [cancelWorkspaceDiff, updateReviewPanel]);

  const toggleRuntime = useCallback(() => {
    if (stateRef.current.focusMode) return;
    const current = stateRef.current.panelMode;
    if (reviewPanelRef.current.tabs.length > 0) {
      // Review and Runtime share the right column. Reveal the preferred
      // Runtime layout by closing its owner-bound ReviewPanel through the
      // existing cancellation and focus-preserving path.
      if (current === "hidden" || (current === "docked" && narrowViewport)) setPanelMode("floating");
      closeReviewPanel();
      return;
    }
    setPanelMode(current === "hidden" || (current === "docked" && narrowViewport) ? "floating" : "hidden");
  }, [closeReviewPanel, narrowViewport, setPanelMode]);

  const openWorkspaceDiff = useCallback(async (path?: string) => {
    const current = stateRef.current;
    if (!api || current.mode !== "coding" || !current.selectedProjectKey) return;
    const owner = reviewOwner();
    const id = `workspace-diff:${owner.ownerKey}:${path ?? "all"}`;
    const previous = workspaceDiffContextRef.current;
    const context: WorkspaceDiffContext = {
      sequence: workspaceDiffSequenceRef.current + 1,
      operationId: null,
      ownerKey: owner.ownerKey,
      owner,
      tabId: id,
    };
    workspaceDiffSequenceRef.current = context.sequence;
    workspaceDiffContextRef.current = context;
    earlyWorkspaceDiffEventsRef.current.clear();
    const tab: ReviewPanelTab = { kind: "workspace-diff", id, title: path ? path.split(/[\\/]/u).at(-1) || path : t("currentWorkingTree"), owner, path, state: "reviewing" };
    updateReviewPanel((panel) => ({ tabs: [...panel.tabs.filter((item) => item.id !== id), tab], activeTabId: id }));
    try {
      if (previous?.operationId) {
        try { await send("workspace.diff.cancel", { operation_id: previous.operationId }); } catch { /* the next kickoff reports the remaining operation limit */ }
      }
      if (workspaceDiffContextRef.current !== context || !reviewOwnerMatches(owner)) return;
      const params: JsonObject = { project_key: owner.ownerKey, ...(path ? { path } : {}) };
      const result = asObject(await send("workspace.diff", params));
      const operationId = stringValue(result.operation_id);
      if (workspaceDiffContextRef.current !== context || !reviewOwnerMatches(owner)) {
        if (operationId) void send("workspace.diff.cancel", { operation_id: operationId }).catch(() => undefined);
        return;
      }
      if (!operationId || stringValue(result.owner_key) !== owner.ownerKey || stringValue(result.state) !== "reviewing") {
        workspaceDiffContextRef.current = null;
        const errorKind = runtimeBusinessErrorKind(result);
        updateReviewTab(id, (existing) => existing.kind === "workspace-diff"
          ? { ...existing, state: "failed", error: errorKind === "workspace_diff_busy" ? t("workspaceDiffUnavailable") : t("workspaceDiffUnavailable") }
          : existing);
        return;
      }
      context.operationId = operationId;
      const early = earlyWorkspaceDiffEventsRef.current.get(operationId);
      earlyWorkspaceDiffEventsRef.current.clear();
      if (early) acceptWorkspaceDiffEvent(context, early);
    } catch {
      if (workspaceDiffContextRef.current !== context || !reviewOwnerMatches(owner)) return;
      workspaceDiffContextRef.current = null;
      updateReviewTab(id, (existing) => existing.kind === "workspace-diff"
        ? { ...existing, state: "failed", error: t("workspaceDiffUnavailable") }
        : existing);
    }
  }, [acceptWorkspaceDiffEvent, api, reviewOwner, reviewOwnerMatches, send, t, updateReviewTab, updateReviewPanel]);

  const readToolOutputPage = useCallback(async (id: string) => {
    const tab = reviewPanelRef.current.tabs.find((candidate) => candidate.id === id);
    if (!tab || tab.kind !== "tool-output" || !tab.ref || tab.nextOffset === null || tab.loading
      || !tab.owner.projectKey || !tab.owner.sessionId || !reviewOwnerMatches(tab.owner)) return;
    const requestedOffset = tab.nextOffset;
    const sessionId = tab.owner.sessionId;
    const projectKey = tab.owner.projectKey;
    updateReviewTab(id, (current) => current.kind === "tool-output" ? { ...current, loading: true, error: undefined } : current);
    try {
      const response = asObject(await send("tool_result.read", {
        session_id: sessionId,
        project_key: projectKey,
        ref: tab.ref,
        offset: requestedOffset,
        limit: 64 * 1024,
      }));
      const current = reviewPanelRef.current.tabs.find((candidate) => candidate.id === id);
      if (!reviewOwnerMatches(tab.owner) || !current || current.kind !== "tool-output" || current.ref !== tab.ref) return;
      const content = response.content;
      const offset = response.offset;
      const nextOffset = response.next_offset;
      const totalBytes = response.total_bytes;
      const eof = response.eof;
      const sha256 = response.sha256;
      const byteLength = typeof content === "string" ? new TextEncoder().encode(content).byteLength : Number.MAX_SAFE_INTEGER;
      const valid = response.ref === tab.ref
        && typeof content === "string"
        && byteLength <= 64 * 1024
        && offset === requestedOffset
        && Number.isSafeInteger(nextOffset) && (nextOffset as number) >= requestedOffset
        && Number.isSafeInteger(totalBytes) && (totalBytes as number) >= (nextOffset as number)
        && typeof eof === "boolean"
        && typeof sha256 === "string";
      if (!valid || (!eof && nextOffset === requestedOffset)) {
        updateReviewTab(id, (currentTab) => currentTab.kind === "tool-output" ? { ...currentTab, loading: false, error: t("toolOutputUnavailable") } : currentTab);
        return;
      }
      updateReviewTab(id, (currentTab) => currentTab.kind === "tool-output" ? {
        ...currentTab,
        text: requestedOffset === 0 ? content as string : currentTab.text + (content as string),
        loading: false,
        error: undefined,
        offset: requestedOffset,
        nextOffset: eof ? null : nextOffset as number,
        totalBytes: totalBytes as number,
        sha256,
        eof,
        truncated: !eof,
      } : currentTab);
    } catch {
      if (!reviewOwnerMatches(tab.owner)) return;
      updateReviewTab(id, (currentTab) => currentTab.kind === "tool-output" ? { ...currentTab, loading: false, error: t("toolOutputUnavailable") } : currentTab);
    }
  }, [reviewOwnerMatches, send, t, updateReviewTab]);

  const openToolOutput = useCallback((entry: RendererState["timeline"][number]) => {
    const owner = reviewOwner();
    const id = `tool-output:${owner.sessionId ?? "none"}:${entry.outputRef ?? entry.id}`;
    const hasRef = Boolean(entry.outputRef && owner.projectKey && owner.sessionId);
    const tab: ReviewPanelTab = {
      kind: "tool-output",
      id,
      title: `${entry.toolName || t("viewToolOutput")}`,
      owner,
      ...(hasRef ? { ref: entry.outputRef } : {}),
      text: entry.outputPreview ?? "",
      loading: false,
      truncated: entry.outputPreviewTruncated === true || hasRef,
      offset: 0,
      nextOffset: hasRef ? 0 : null,
      totalBytes: null,
      sha256: null,
      eof: !hasRef && entry.outputPreviewTruncated !== true,
      ...(!hasRef && entry.outputPreviewTruncated ? { error: t("toolOutputUnavailable") } : {}),
    };
    updateReviewPanel((current) => ({ tabs: [...current.tabs.filter((item) => item.id !== id), tab], activeTabId: id }));
    if (hasRef) void readToolOutputPage(id);
  }, [readToolOutputPage, reviewOwner, t, updateReviewPanel]);

  const openProcessLog = useCallback((processId: string) => {
    const owner = reviewOwner();
    const key = owner.projectKey && owner.sessionId ? sessionRuntimeKey(owner.projectKey, owner.sessionId) : "";
    const logs = stateRef.current.processLogs[key] ?? [];
    const reader = stateRef.current.processReaders[key]?.[processId] ?? {
      nextCursor: 0, earliestCursor: 0, cursorExpired: false, state: null, expired: false, loading: false, error: null,
    };
    const id = `process-log:${owner.ownerKey}:${owner.sessionId ?? "none"}:${processId}`;
    const tab: ReviewPanelTab = { kind: "process-log", id, title: `${t("processLog")}: ${processId}`, owner, processId, entries: logs.filter((entry) => entry.processId === processId), reader };
    updateReviewPanel((current) => ({ tabs: [...current.tabs.filter((item) => item.id !== id), tab], activeTabId: id }));
  }, [reviewOwner, t, updateReviewPanel]);

  const removeProject = useCallback(async (project: ProjectState) => {
    const current = stateRef.current;
    const removal = projectRemovalPlan(current.projects, current.selectedProjectKey, project.projectKey);
    const navigation = projectNavigationPreferences(removal.remaining, current.pinnedSessions, current.expandedProjects);
    if (!removal.current) {
      dispatch({ type: "hydrate_preferences", preferences: navigation });
      await persist("recentProjects", navigation.recentProjects);
      await persist("projectAliases", navigation.projectAliases);
      await persist("pinnedProjectKeys", navigation.pinnedProjectKeys);
      await persist("pinnedSessions", navigation.pinnedSessions);
      await persist("expandedProjects", navigation.expandedProjects);
      return;
    }

    await enqueueRuntimeOperation("navigation", async (isOwned) => {
      if (!(await closeActiveTurn())) throw new RuntimeOperationCancelled();
      if (!isOwned()) throw new StaleRuntimeOperation();
      const replacement = removal.replacement;
      if (replacement) {
        const opened = await send("project.open", { path: replacement.path });
        if (!isOwned()) throw new StaleRuntimeOperation();
        dispatch({ type: "project_opened", result: opened, preserveRuntimeState: true });
        dispatch({ type: "hydrate_preferences", preferences: { ...navigation, selectedProjectKey: replacement.projectKey, selectedSessionId: null } });
        await persist("recentProjects", navigation.recentProjects);
        await persist("projectAliases", navigation.projectAliases);
        await persist("pinnedProjectKeys", navigation.pinnedProjectKeys);
        await persist("pinnedSessions", navigation.pinnedSessions);
        await persist("expandedProjects", navigation.expandedProjects);
        await persist("selectedProjectKey", replacement.projectKey);
        await persist("selectedSessionId", null);
        if (!isOwned()) throw new StaleRuntimeOperation();
        await refreshCatalog(replacement.projectKey, "project_open", undefined, true, isOwned);
      } else {
        await send("runtime.shutdown", {});
        if (!isOwned()) throw new StaleRuntimeOperation();
        dispatch({ type: "workspace_cleared" });
        dispatch({ type: "hydrate_preferences", preferences: { ...navigation, selectedProjectKey: null, selectedSessionId: null } });
        await persist("recentProjects", []);
        await persist("projectAliases", {});
        await persist("pinnedProjectKeys", []);
        await persist("pinnedSessions", []);
        await persist("expandedProjects", {});
        await persist("selectedProjectKey", null);
        await persist("selectedSessionId", null);
      }
    }, (error, isOwned) => {
      if (isOwned()) dispatch({ type: "runtime_error", message: safeErrorMessage(error, t("projectRemoveFailed")), state: "ready" });
    }, removal.replacement ? "ready" : "stopped");
  }, [closeActiveTurn, enqueueRuntimeOperation, persist, refreshCatalog, send, t]);

  const openExplorer = useCallback((project: ProjectState) => {
    if (!api) return;
    void api.openProjectInExplorer(project.path).catch((error) => dispatch({ type: "notice", text: safeErrorMessage(error, t("explorerOpenFailed")) }));
  }, [api]);

  const loadSettings = useCallback(async () => {
    if (!api) {
      dispatch({ type: "settings_loaded", configuration: {} });
      return;
    }
    dispatch({ type: "set_focus_mode", value: false });
    dispatch({ type: "set_view", view: "settings" });
    try {
      const result = asObject(await send("settings.get", {}));
      dispatch({ type: "settings_loaded", configuration: (asObject(result.configuration) as ConfigurationView) });
      const applications = asObject(result.applications);
      dispatch({ type: "settings_applications", value: {
        applied: typeof applications.applied === "number" ? applications.applied : 0,
        pending: typeof applications.pending === "number" ? applications.pending : 0,
        failed: typeof applications.failed === "number" ? applications.failed : 0,
      } });
    } catch (error) {
      dispatch({ type: "settings_error", message: safeErrorMessage(error, t("configUnavailable")) });
    }
  }, [api, send, t]);

  const saveSettings = useCallback((request: ConfigurationWrite): Promise<ConfigurationView> => {
    if (!api) return Promise.reject(new Error(t("desktopApiUnavailable")));
    const autoSaveRequest = Object.keys(request.providers ?? {}).length === 0
      && Object.keys(request.models ?? {}).length === 0
      && Object.keys(request.provider_renames ?? {}).length === 0;
    const identities = autoSaveRequest
      ? configurationWriteIdentities(request).filter((identity) => identity !== "search.api_key"
        && (identity === "default_model" || identity === "default_permission_mode" || identity.startsWith("search.") || identity.startsWith("tool_limits.")))
      : [];
    const revisions = new Map<string, number>();
    for (const identity of identities) {
      const revision = (settingsWriteRevisionsRef.current.get(identity) ?? 0) + 1;
      settingsWriteRevisionsRef.current.set(identity, revision);
      settingsFailedWritesRef.current.delete(identity);
      revisions.set(identity, revision);
    }
    if (identities.length) dispatch({ type: "settings_write_failures", value: settingsFailedWritesRef.current.size });
    const revision = ++settingsRequestRevisionRef.current;
    settingsSaveCountRef.current += 1;
    settingsSaveInFlightRef.current = true;
    dispatch({ type: "settings_saving", value: true });
    const operation = settingsSaveTailRef.current.then(async () => {
      const result = asObject(await send("settings.save", { request: request as unknown as JsonObject }));
      const configuration = asObject(result.configuration) as ConfigurationView;
      for (const [identity, writeRevision] of revisions) {
        if (settingsWriteRevisionsRef.current.get(identity) === writeRevision) settingsFailedWritesRef.current.delete(identity);
      }
      if (identities.length) dispatch({ type: "settings_write_failures", value: settingsFailedWritesRef.current.size });
      if (!isMounted() || revision !== settingsRequestRevisionRef.current) return configuration;
      dispatch({ type: "settings_loaded", configuration });
      const applications = asObject(result.applications);
      dispatch({ type: "settings_applications", value: {
        applied: typeof applications.applied === "number" ? applications.applied : 0,
        pending: typeof applications.pending === "number" ? applications.pending : 0,
        failed: typeof applications.failed === "number" ? applications.failed : 0,
      } });
      return configuration;
    }).catch((error: unknown) => {
      if (isMounted() && identities.length) {
        const search = request.search
          ? Object.fromEntries(Object.entries(request.search).filter(([field]) => field !== "api_key"))
          : undefined;
        const safeRequest: ConfigurationWrite = {
          ...(Object.hasOwn(request, "default_model") ? { default_model: request.default_model } : {}),
          ...(Object.hasOwn(request, "default_permission_mode") ? { default_permission_mode: request.default_permission_mode } : {}),
          ...(search && Object.keys(search).length ? { search } : {}),
          ...(request.tool_limits ? { tool_limits: request.tool_limits } : {}),
        };
        for (const [identity, writeRevision] of revisions) {
          if (settingsWriteRevisionsRef.current.get(identity) !== writeRevision) continue;
          let patch: ConfigurationWrite = safeRequest;
          if (identity === "default_model") patch = { default_model: safeRequest.default_model };
          else if (identity === "default_permission_mode") patch = { default_permission_mode: safeRequest.default_permission_mode };
          else if (identity.startsWith("search.")) {
            const field = identity.slice("search.".length);
            patch = { search: { [field]: safeRequest.search?.[field] } };
          } else if (identity.startsWith("tool_limits.")) {
            const field = identity.slice("tool_limits.".length);
            patch = { tool_limits: { [field]: safeRequest.tool_limits?.[field] } };
          }
          settingsFailedWritesRef.current.set(identity, { identity, request: patch, revision: writeRevision });
        }
        dispatch({ type: "settings_write_failures", value: settingsFailedWritesRef.current.size });
      }
      if (isMounted() && revision === settingsRequestRevisionRef.current) {
        dispatch({ type: "settings_error", message: safeErrorMessage(error, t("settingsSaveFailed")) });
      }
      throw error;
    }).finally(() => {
      settingsSaveCountRef.current = Math.max(0, settingsSaveCountRef.current - 1);
      settingsSaveInFlightRef.current = settingsSaveCountRef.current > 0;
      if (isMounted()) dispatch({ type: "settings_saving", value: settingsSaveInFlightRef.current });
    });
    settingsSaveTailRef.current = operation.then(() => undefined, () => undefined);
    return operation;
  }, [api, isMounted, send, t]);

  const retrySettingsSave = useCallback(async () => {
    for (const [identity, failed] of Array.from(settingsFailedWritesRef.current)) {
      if (settingsFailedWritesRef.current.get(identity) !== failed
        || settingsWriteRevisionsRef.current.get(identity) !== failed.revision) continue;
      await saveSettings(failed.request).catch(() => undefined);
    }
  }, [saveSettings]);

  const retrySettingsApply = useCallback(async () => {
    const result = asObject(await send("settings.retry_apply", {}));
    const applications = asObject(result.applications);
    dispatch({ type: "settings_applications", value: {
      applied: typeof applications.applied === "number" ? applications.applied : 0,
      pending: typeof applications.pending === "number" ? applications.pending : 0,
      failed: typeof applications.failed === "number" ? applications.failed : 0,
    } });
  }, [send]);

  const loadArchivedSettingsSessions = useCallback(async (): Promise<ArchivedSettingsSession[]> => {
    const projects = stateRef.current.projects.filter((project) => project.projectKey !== GENERAL_PROJECT_KEY);
    const owners = [
      ...projects.map((project) => ({ projectKey: project.projectKey, projectLabel: project.alias || project.path })),
      { projectKey: GENERAL_PROJECT_KEY, projectLabel: t("generalMode") },
    ];
    const groups = await Promise.all(owners.map(async (owner) => {
      const result = asObject(await send("project.sessions", { project_key: owner.projectKey, archived: true }));
      const sessions = Array.isArray(result.sessions) ? result.sessions : [];
      return sessions.map((value) => asObject(value))
        .filter((session) => session.archived === true && typeof session.session_id === "string")
        .map((session) => ({
          projectKey: owner.projectKey,
          projectLabel: owner.projectLabel,
          session: session as unknown as SessionSummary,
        }));
    }));
    return groups.flat().sort((left, right) => {
      const a = left.session.last_used_at ?? left.session.created_at ?? "";
      const b = right.session.last_used_at ?? right.session.created_at ?? "";
      return b.localeCompare(a);
    });
  }, [send, t]);

  const restoreArchivedSettingsSession = useCallback(async (item: ArchivedSettingsSession): Promise<boolean> => {
    const before = stateRef.current;
    const expected = {
      mode: before.mode,
      projectKey: before.selectedProjectKey,
      sessionId: before.selectedSessionId,
      revision: before.sessionViewRevision,
      generation: runtimeGeneration(),
    };
    const ownsNavigation = () => {
      const current = stateRef.current;
      return isMounted()
        && current.view === "settings"
        && runtimeGeneration() === expected.generation
        && current.mode === expected.mode
        && current.selectedProjectKey === expected.projectKey
        && current.selectedSessionId === expected.sessionId
        && current.sessionViewRevision === expected.revision;
    };
    const project = stateRef.current.projects.find((entry) => entry.projectKey === item.projectKey)
      ?? (item.projectKey === GENERAL_PROJECT_KEY ? {
        path: GENERAL_PROJECT_KEY,
        projectKey: GENERAL_PROJECT_KEY,
        alias: t("generalMode"),
        pinned: false,
        sessions: [],
        catalogFresh: false,
      } : null);
    if (!project || !(await archiveSession(project, { ...item.session, archived: true }, false))) return false;
    if (ownsNavigation()) {
      dispatch({ type: "set_view", view: "chat" });
      await resumeSession(project, item.session.session_id);
    }
    return true;
  }, [archiveSession, isMounted, resumeSession, runtimeGeneration, t]);

  const backFromSettings = useCallback(() => {
    // Include the ref so a same-turn Back/Cancel event cannot slip through
    // before React commits settingsSaving=true for the durable request.
    if (stateRef.current.settingsSaving || settingsSaveInFlightRef.current) return;
    dispatch({ type: "set_view", view: "chat" });
  }, []);

  useEffect(() => {
    if (!state.focusMode || typeof document === "undefined") return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setFocusMode(false);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [setFocusMode, state.focusMode]);
  useLayoutEffect(() => {
    if (state.focusMode || typeof document === "undefined") return;
    if (document.activeElement === document.body) focusModeToggleRef.current?.focus();
  }, [state.focusMode]);

  useEffect(() => {
    const diff = workspaceDiffContextRef.current;
    if (diff && !reviewOwnerMatches(diff.owner)) cancelWorkspaceDiff(diff);
    updateReviewPanel((current) => {
      const tabs = current.tabs.filter((tab) => reviewOwnerMatches(tab.owner));
      const activeTabId = tabs.some((tab) => tab.id === current.activeTabId) ? current.activeTabId : tabs.at(-1)?.id ?? null;
      return { tabs, activeTabId };
    });
  }, [cancelWorkspaceDiff, reviewOwnerMatches, state.mode, state.runtimeState, state.selectedProjectKey, state.selectedSessionId, state.sessionViewRevision, updateReviewPanel]);

  useEffect(() => {
    const owner = reviewOwner();
    const ownerKey = [owner.generation, owner.mode, owner.projectKey, owner.sessionId, owner.viewRevision].join(":");
    if (workspaceDiffSummaryOwnerRef.current !== ownerKey) {
      workspaceDiffSummaryOwnerRef.current = ownerKey;
      workspaceDiffSummaryRequestKeyRef.current = null;
      cancelWorkspaceDiffSummary();
    }
    const context = workspaceDiffSummaryContextRef.current;
    if (context && !reviewOwnerMatches(context.owner)) cancelWorkspaceDiffSummary(context);
    if (workspaceDiffSummary && !reviewOwnerMatches(workspaceDiffSummary.owner)) {
      workspaceDiffSummaryRequestKeyRef.current = null;
      setWorkspaceDiffSummary(null);
    }
  }, [cancelWorkspaceDiffSummary, reviewOwner, reviewOwnerMatches, state.mode, state.runtimeState, state.selectedProjectKey, state.selectedSessionId, state.sessionViewRevision, workspaceDiffSummary]);
  useEffect(() => () => cancelWorkspaceDiffSummary(), [cancelWorkspaceDiffSummary]);

  const visibleReviewTabs = reviewPanel.tabs.flatMap((tab): ReviewPanelTab[] => {
    if (!reviewOwnerMatches(tab.owner)) return [];
    if (tab.kind !== "process-log") return [tab];
    const key = tab.owner.projectKey && tab.owner.sessionId ? sessionRuntimeKey(tab.owner.projectKey, tab.owner.sessionId) : "";
    return [{
      ...tab,
      entries: (state.processLogs[key] ?? []).filter((entry) => entry.processId === tab.processId),
      reader: state.processReaders[key]?.[tab.processId] ?? tab.reader,
    }];
  });
  const activeReviewTabId = visibleReviewTabs.some((tab) => tab.id === reviewPanel.activeTabId) ? reviewPanel.activeTabId! : visibleReviewTabs.at(-1)?.id ?? "";
  const reviewPanelVisible = state.view === "chat" && !state.focusMode && visibleReviewTabs.length > 0;
  const visibleWorkspaceDiffSummary = state.mode === "coding" && state.view === "chat" && workspaceDiffSummary && reviewOwnerMatches(workspaceDiffSummary.owner)
    ? workspaceDiffSummary
    : undefined;
  const documentPreviewMinWidth = 220;
  const documentSidebarWidth = state.focusMode || (reviewPanelVisible && viewportWidth <= 620)
    ? 0
    : narrowViewport
      ? Math.max(112, Math.min(154, viewportWidth * 0.3))
      : state.sidebarWidth;
  const documentPreviewMaxWidth = Math.max(documentPreviewMinWidth, viewportWidth - documentSidebarWidth - CONVERSATION_MIN_WIDTH);
  const effectiveDocumentPreviewWidth = Math.min(documentPreviewWidth, documentPreviewMaxWidth);

  const runtimeVisible = state.mode === "coding" && !state.focusMode && !reviewPanelVisible && state.panelMode !== "hidden" && !(narrowViewport && state.panelMode === "docked");
  useLayoutEffect(() => {
    if (!runtimeVisible || !runtimeFocusHandoffRef.current) return;
    runtimeFocusHandoffRef.current = false;
    runtimeToggleRef.current?.focus();
  }, [runtimeVisible]);
  const runtimeToggleLabel = runtimeVisible ? t("closeRuntime") : t("openRuntime");
  const activityKey = sessionRuntimeKey(state.selectedProjectKey, state.selectedSessionId ?? "");
  const activity = state.sessionActivity?.[activityKey];
  const displayedCompaction = state.compactionStatus.state === "running" ? state.compactionStatus : activity?.compaction ?? state.compactionStatus;
  useEffect(() => {
    if (state.selectedProjectKey && state.selectedSessionId && state.compactionStatus.changed === true && state.compactionStatus.state !== "running") {
      void historyPageLoaderRef.current(state.selectedProjectKey, state.selectedSessionId, null, false, true);
    }
  }, [state.selectedProjectKey, state.selectedSessionId, state.compactionStatus.state, state.compactionStatus.changed, state.compactionStatus.operation_id]);
  const markLatestSeen = useCallback(() => {
    if (activity?.unread) dispatch({ type: "session_result_seen", key: activityKey, revision: activity.revision });
  }, [activityKey, activity?.unread, activity?.revision]);
  const visibleHistory = state.selectedProjectKey && state.selectedSessionId
    ? state.sessionHistory[sessionRuntimeKey(state.selectedProjectKey, state.selectedSessionId)]
    : undefined;
  const visiblePreparation = state.selectedProjectKey && state.selectedSessionId
    ? state.sessionPreparation[sessionRuntimeKey(state.selectedProjectKey, state.selectedSessionId)]
    : undefined;
  useEffect(() => {
    const pending = pendingProcessPermissionRef.current;
    if (!pending) return;
    if (pending.projectKey === state.selectedProjectKey && pending.sessionId === state.selectedSessionId) return;
    // A permission request is bound to the Application/Session that prepared
    // it. Navigation invalidates it locally; no approval is replayed for the
    // newly selected Session and a late response cannot re-open the dialog.
    pendingProcessPermissionRef.current = null;
    processPermissionSubmitRef.current = null;
    setPendingProcessPermission(null);
    void releaseProcessPermission(pending);
  }, [releaseProcessPermission, state.selectedProjectKey, state.selectedSessionId]);

  const cancelModelImageSwitch = useCallback((close = true) => {
    const pending = pendingModelImageSwitchRef.current;
    if (!pending) return;
    if (close) {
      pendingModelImageSwitchRef.current = null;
      setPendingModelImageSwitch(null);
    }
    if (pending.operationId) {
      void send("model.switch.cancel", {
        session_id: pending.sessionId,
        operation_id: pending.operationId,
      }).catch(() => undefined);
    }
  }, [send]);

  useEffect(() => {
    const pending = pendingModelImageSwitchRef.current;
    if (!pending) return;
    if (
      pending.generation === runtimeGeneration()
      && pending.mode === state.mode
      && pending.projectKey === state.selectedProjectKey
      && pending.sessionId === state.selectedSessionId
      && pending.viewRevision === state.sessionViewRevision
    ) return;
    cancelModelImageSwitch();
  }, [cancelModelImageSwitch, runtimeGeneration, state.mode, state.selectedProjectKey, state.selectedSessionId, state.sessionViewRevision]);

  useEffect(() => () => {
    const pending = pendingModelImageSwitchRef.current;
    pendingModelImageSwitchRef.current = null;
    if (pending?.operationId) {
      void send("model.switch.cancel", {
        session_id: pending.sessionId,
        operation_id: pending.operationId,
      }).catch(() => undefined);
    }
  }, [send]);

  const chooseModelImageSwitch = useCallback(async (imageHandling: "placeholder" | "summarize") => {
    let pending = pendingModelImageSwitchRef.current;
    if (!pending || pending.busy || !api || !pending.sessionId) return;
    const ownsPending = () => {
      const current = stateRef.current;
      return pendingModelImageSwitchRef.current?.operationId === pending?.operationId
        && isMounted()
        && runtimeGeneration() === pending?.generation
        && current.mode === pending?.mode
        && current.selectedProjectKey === pending?.projectKey
        && current.selectedSessionId === pending?.sessionId
        && current.sessionViewRevision === pending?.viewRevision
        && !hasOwner();
    };
    if ((hasOwner() || stateRef.current.runtimeState === "restarting")
      && (!(await waitForRuntimeUserAccess()) || hasOwner() || stateRef.current.runtimeState === "restarting")) return;
    if (!ownsPending()) return;
    modelSwitchSequenceRef.current += 1;
    const operationId = `model-switch-${Date.now()}-${modelSwitchSequenceRef.current}`;
    pending = { ...pending, operationId, handling: imageHandling, busy: true, error: null };
    pendingModelImageSwitchRef.current = pending;
    setPendingModelImageSwitch(pending);
    try {
      const started = asObject(await send("command.execute", {
        text: `/model ${pending.modelRef}`,
        image_handling: imageHandling,
        expected_session_id: pending.sessionId,
        operation_id: operationId,
      }));
      if (!ownsPending()) {
        void send("model.switch.cancel", {
          session_id: pending.sessionId,
          operation_id: operationId,
        }).catch(() => undefined);
        return;
      }
      if (started.code !== "model_switch_started") {
        throw new Error("model switch was not started");
      }
      while (ownsPending()) {
        await new Promise<void>((resolve) => window.setTimeout(resolve, 120));
        if (!ownsPending()) break;
        const statusValue = await send("model.switch.status", {
          session_id: pending.sessionId,
          operation_id: operationId,
        });
        if (!ownsPending()) return;
        const status = asObject(statusValue);
        if (status.state === "running") continue;
        const result = asObject(status.result);
        if (status.state === "completed" && isDesktopCommandResult(result) && result.code === "model_selected") {
          pendingModelImageSwitchRef.current = null;
          setPendingModelImageSwitch(null);
          dispatch({ type: "command_result", result, notice: commandResultNotice(result, t) });
          await refreshRuntimeStatus();
          return;
        }
        if (status.state === "cancelled") {
          pendingModelImageSwitchRef.current = null;
          setPendingModelImageSwitch(null);
          return;
        }
        const failed = {
          ...pending,
          operationId: null,
          handling: null,
          busy: false,
          error: t("modelImageSwitchFailed"),
        };
        pendingModelImageSwitchRef.current = failed;
        setPendingModelImageSwitch(failed);
        return;
      }
    } catch {
      if (ownsPending()) {
        // A renderer timeout only releases its waiter; the Bridge operation
        // can still finish. Cancel this captured Session/operation and keep
        // the dialog busy until its terminal state or authoritative model is
        // known. Never clear the operation identity while it may still run.
        try {
          await send("model.switch.cancel", {
            session_id: pending.sessionId,
            operation_id: operationId,
          });
        } catch {
          // A stale operation may already have completed and been consumed;
          // status below distinguishes that race from a live operation.
        }
        while (ownsPending()) {
          await new Promise<void>((resolve) => window.setTimeout(resolve, 180));
          if (!ownsPending()) return;
          let recoveryStatus: JsonObject;
          try {
            recoveryStatus = asObject(await send("model.switch.status", {
              session_id: pending.sessionId,
              operation_id: operationId,
            }));
          } catch {
            continue;
          }
          if (!ownsPending()) return;
          const recoveryError = runtimeBusinessErrorKind(recoveryStatus);
          if (recoveryError === "stale_operation") {
            let currentStatus: unknown;
            try {
              currentStatus = await send("status.get", {});
            } catch {
              continue;
            }
            if (!ownsPending()) return;
            const currentModel = stringValue(asObject(asObject(currentStatus).application).current_model);
            if (!currentModel) continue;
            dispatch({ type: "status_loaded", result: currentStatus });
            if (currentModel === pending.modelRef) {
              pendingModelImageSwitchRef.current = null;
              setPendingModelImageSwitch(null);
              return;
            }
            const failed = {
              ...pending,
              operationId: null,
              handling: null,
              busy: false,
              error: t("modelImageSwitchFailed"),
            };
            pendingModelImageSwitchRef.current = failed;
            setPendingModelImageSwitch(failed);
            return;
          }
          if (recoveryStatus.state === "running") continue;
          const recoveryResult = asObject(recoveryStatus.result);
          if (recoveryStatus.state === "completed" && isDesktopCommandResult(recoveryResult) && recoveryResult.code === "model_selected") {
            pendingModelImageSwitchRef.current = null;
            setPendingModelImageSwitch(null);
            dispatch({ type: "command_result", result: recoveryResult, notice: commandResultNotice(recoveryResult, t) });
            await refreshRuntimeStatus();
            return;
          }
          if (recoveryStatus.state === "cancelled") {
            pendingModelImageSwitchRef.current = null;
            setPendingModelImageSwitch(null);
            return;
          }
          if (recoveryStatus.state === "failed") {
            const failed = {
              ...pending,
              operationId: null,
              handling: null,
              busy: false,
              error: t("modelImageSwitchFailed"),
            };
            pendingModelImageSwitchRef.current = failed;
            setPendingModelImageSwitch(failed);
            return;
          }
        }
      }
    }
  }, [api, hasOwner, isMounted, refreshRuntimeStatus, runtimeGeneration, send, t, waitForRuntimeUserAccess]);

  const processPermissionInteraction: PendingInteraction | null = pendingProcessPermission
    ? {
      kind: "permission_required",
      pauseId: `process-stop:${pendingProcessPermission.projectKey}:${pendingProcessPermission.sessionId}:${stringValue(pendingProcessPermission.request.permission_id)}`,
      runId: stringValue(pendingProcessPermission.request.run_id),
      turnId: stringValue(pendingProcessPermission.request.turn_id),
      toolCallId: stringValue(pendingProcessPermission.request.tool_call_id),
      request: pendingProcessPermission.request,
      submitting: pendingProcessPermission.submitting,
    }
    : null;
  const content = state.view === "settings" ? (
    <SettingsView state={state} pendingWrites={Array.from(settingsFailedWritesRef.current.values())} onRevealApiKey={revealSettingsApiKey} onBack={backFromSettings} onSave={saveSettings} onRetrySave={retrySettingsSave} onRetryApply={retrySettingsApply} onLoadArchivedSessions={loadArchivedSettingsSessions} onRestoreArchivedSession={restoreArchivedSettingsSession} onThemeChange={setTheme} onLanguageChange={setLanguage} />
  ) : (
    <>
      <header className="conversation-bar">
        <div className="conversation-title">
          <span className="conversation-presence" aria-hidden="true" />
          <h1>{state.selectedSessionId ? `${t("session")} ${state.selectedSessionId.slice(0, 8)}` : t("newConversation")}</h1>
        </div>
        <div className="conversation-actions">
          {state.mode === "coding" && state.selectedProjectKey && <button type="button" className="icon-button" title={t("reviewCurrentDiff")} aria-label={t("reviewCurrentDiff")} onClick={() => void openWorkspaceDiff()}><UiIcon name="file" /></button>}
          {state.mode === "coding" && !state.focusMode && <button ref={runtimeToggleRef} type="button" className="icon-button" title={runtimeToggleLabel} aria-label={runtimeToggleLabel} aria-expanded={runtimeVisible} aria-controls={RUNTIME_PANEL_ID} onClick={toggleRuntime}><UiIcon name="panel" /><span className="sr-only">{runtimeVisible ? t("runtimePanelOpen") : t("runtimePanelClosed")}</span></button>}
          <button ref={focusModeToggleRef} type="button" className="icon-button focus-mode-toggle" title={state.focusMode ? t("exitFocusMode") : t("enterFocusMode")} aria-label={state.focusMode ? t("exitFocusMode") : t("enterFocusMode")} aria-pressed={state.focusMode} onClick={() => setFocusMode(!state.focusMode)}><UiIcon name="focus" /><span className="sr-only">{state.focusMode ? t("exitFocusMode") : t("enterFocusMode")}</span></button>
        </div>
      </header>
       <RendererErrorBoundary name="timeline"><ChatTimeline
        entries={state.timeline}
        // TodoWrite is anchored to the composer; keep the timeline focused on
        // conversation and durable replay records.
        todo={[]}
        notice={[...new Set([
          state.notice,
          state.runtimeState === "restarting" ? t("runtimeRestarting") : null,
          state.terminalStatusPending ? t("terminalStatusPending") : null,
        ].filter((text) => Boolean(text) && text !== state.runtimeError))].join(" · ") || null}
        onLatestSeen={markLatestSeen}
        compactionAnchor={activity?.compactionAnchor}
        compactionRunning={displayedCompaction.state === "running"}
        compactionCompleted={displayedCompaction.state === "completed"}
        compactionNotice={displayedCompaction.state === "running"
          ? t(displayedCompaction.trigger === "manual" ? "compactingManually" : "compactingAutomatically")
          : displayedCompaction.state === "completed" ? t("contextCompacted")
          : displayedCompaction.state === "no_change" ? t("contextCompactionUnneeded")
          : displayedCompaction.state === "cancelled" ? t("contextCompactionCancelled")
          : displayedCompaction.state === "failed" ? t("contextCompactionFailed") : null}
        runtimeError={state.runtimeError}
        runtimeErrorVisible={runtimeVisible}
        onOpenSettings={state.runtimeError ? () => void loadSettings() : undefined}
        onCopyText={copyText}
        onOpenArtifact={openArtifact}
        onDescribeArtifact={describeArtifact}
        onAuthorizeArtifact={authorizeExternalArtifact}
        onRevealArtifact={revealArtifact}
        onPreviewArtifact={previewArtifact}
        onCopyPath={copyText}
        onOpenDocument={openDocumentPreview}
        onViewToolOutput={openToolOutput}
        onReviewCurrentDiff={(path) => void openWorkspaceDiff(path)}
        workspaceDiffSummary={visibleWorkspaceDiffSummary}
        onReviewProcessLog={openProcessLog}
        onPreviewAttachment={previewAttachment}
        onOpenAttachment={openAttachment}
        onRevealAttachment={revealAttachment}
        onCopyAttachmentPath={copyAttachmentPath}
        onLoadOlder={loadOlderHistory}
        onRetryOlder={retryHistory}
        historyHasMore={visibleHistory?.hasMore ?? false}
        historyLoading={visibleHistory?.loading ?? false}
        historyError={visibleHistory?.error ?? null}
        historyRevision={visibleHistory?.revision ?? 0}
        preparationStatus={visiblePreparation}
        processLogs={state.selectedProjectKey && state.selectedSessionId
          ? state.processLogs[sessionRuntimeKey(state.selectedProjectKey, state.selectedSessionId)] ?? []
          : []}
        processReaders={state.selectedProjectKey && state.selectedSessionId
          ? state.processReaders[sessionRuntimeKey(state.selectedProjectKey, state.selectedSessionId)] ?? {}
          : {}}
        onReadProcess={readProcess}
        onStopProcess={stopProcess}
         sessionKey={`${state.selectedProjectKey ?? ""}:${state.selectedSessionId ?? ""}:${state.sessionViewRevision}`}
       /></RendererErrorBoundary>
      {processPermissionInteraction
        ? <InteractionSurface key={interactionSurfaceKey(processPermissionInteraction)} interaction={processPermissionInteraction} onSubmit={submitProcessPermission} onCancel={cancelProcessPermission} showCancel />
        : state.pendingInteraction && <InteractionSurface key={interactionSurfaceKey(state.pendingInteraction)} interaction={state.pendingInteraction} onSubmit={sendInteraction} onCancel={cancelTurn} />}
      <RendererErrorBoundary name="composer"><Composer state={state} sessionPreparationStatus={visiblePreparation} onChange={(text) => { dispatch({ type: "composer_text", text }); void completeCommand(text); }} onDismissCompletion={() => dispatch({ type: "command_candidates", result: { candidates: [], argument_candidates: [] } })} onSubmit={submitComposer} onCommand={executeCommand} onPause={pauseTurn} onCancel={cancelTurn} onCompactCancel={cancelCompaction} onChooseAttachment={chooseAttachment} onPasteAttachment={pasteAttachment} onImportFile={importDroppedAttachment} onRemoveAttachment={removeAttachment} onPreviewAttachment={previewAttachment} onOpenAttachment={openAttachment} onRevealAttachment={revealAttachment} onCopyAttachmentPath={copyAttachmentPath} onOpenDocument={openDocumentPreview} /></RendererErrorBoundary>
    </>
  );

  const themeClass = `theme-${state.theme}`;
  const shellPanelMode = state.mode === "general" ? "hidden" : state.panelMode;
  const wideLayout = !narrowViewport && state.view === "chat" && !state.focusMode;
  const widthBounds = layoutWidthBounds(
    typeof window === "undefined" ? 1280 : window.innerWidth,
    state.panelMode,
    state.sidebarWidth,
    state.runtimePanelWidth,
  );
  const shellStyle = {
    "--sidebar-width": narrowViewport ? "clamp(112px, 30vw, 154px)" : `${state.sidebarWidth}px`,
    "--runtime-width": narrowViewport ? "0px" : `${state.runtimePanelWidth}px`,
    "--document-preview-width": `${effectiveDocumentPreviewWidth}px`,
  } as CSSProperties;
  return <LanguageProvider value={state.language}>
    <div className={`app-shell ${themeClass} panel-${shellPanelMode}${state.focusMode ? " focus-mode" : ""}${state.view === "settings" ? " settings-shell" : ""}${reviewPanelVisible ? " document-preview-visible" : ""}`} style={shellStyle}>
      {state.view === "chat" && !state.focusMode && <RendererErrorBoundary name="sidebar"><Sidebar mode={state.mode} projects={state.projects} selectedProjectKey={state.selectedProjectKey} selectedSessionId={state.selectedSessionId} activeTurn={state.activeTurn || state.terminalStatusPending || state.compactionStatus.state === "running"} sessionMutationBusy={state.sessionMutationBusy} expandedProjects={state.expandedProjects} onProjectExpandedChange={setProjectExpanded} onProjectDisclosureChange={setProjectDisclosure} onNewSession={newSession} onOpenProject={openProject} onResumeSession={(project, sessionId) => void resumeSession(project, sessionId)} onAliasChange={aliasChange} onTogglePin={togglePin} onToggleSessionPin={toggleSessionPin} onRenameSession={renameSession} onMoveSession={moveSession} onCopySessionId={copySessionId} onOpenExplorer={openExplorer} onRemoveProject={removeProject} onOpenSettings={() => void loadSettings()} onSwitchMode={(mode) => void switchMode(mode)} onSearch={(query) => void searchSessions(query)} onCancelSearch={cancelSessionSearch} searchResults={sessionSearch.results} searchPending={sessionSearch.pending} searchError={sessionSearch.error} onRestoreSearchHit={(hit) => void restoreSearchHit(hit)} onArchiveSession={(project, session, archived) => void archiveSession(project, session, archived)} /></RendererErrorBoundary>}
      <main id="workspace-main" aria-label={t("workspace")}>{content}</main>
      {pendingModelImageSwitch && <div className="model-image-switch-backdrop">
        <section
          id="model-image-switch-dialog"
          className="model-image-switch-dialog"
          role="dialog"
          aria-modal="true"
          aria-labelledby="model-image-switch-title"
          aria-describedby="model-image-switch-description"
          aria-busy={pendingModelImageSwitch.busy}
        >
          <h2 id="model-image-switch-title">{t("modelImageSwitchTitle")}</h2>
          <p id="model-image-switch-description">{t("modelImageSwitchPrompt")}</p>
          {pendingModelImageSwitch.error && <p className="model-image-switch-error" role="alert">{pendingModelImageSwitch.error}</p>}
          <div className="model-image-switch-actions">
            <button
              id="model-image-switch-summarize"
              className="accent-button"
              type="button"
              disabled={pendingModelImageSwitch.busy}
              onClick={() => void chooseModelImageSwitch("summarize")}
            >
              {pendingModelImageSwitch.busy && pendingModelImageSwitch.handling === "summarize" && <span className="model-image-switch-spinner" aria-hidden="true" />}
              {pendingModelImageSwitch.busy && pendingModelImageSwitch.handling === "summarize" ? t("modelImageSwitchWorking") : t("modelImageSwitchSummarize")}
            </button>
            <button
              id="model-image-switch-placeholder"
              className="model-image-switch-secondary"
              type="button"
              disabled={pendingModelImageSwitch.busy}
              onClick={() => void chooseModelImageSwitch("placeholder")}
            >
              {pendingModelImageSwitch.busy && pendingModelImageSwitch.handling === "placeholder" && <span className="model-image-switch-spinner" aria-hidden="true" />}
              {pendingModelImageSwitch.busy && pendingModelImageSwitch.handling === "placeholder" ? t("modelImageSwitchWorking") : t("modelImageSwitchPlaceholder")}
            </button>
            <button
              id="model-image-switch-cancel"
              className="model-image-switch-cancel"
              type="button"
              onClick={() => cancelModelImageSwitch(!pendingModelImageSwitchRef.current?.operationId)}
            >
              {t("cancel")}
            </button>
          </div>
        </section>
      </div>}
      {state.view === "chat" && state.mode === "coding" && !state.focusMode && !reviewPanelVisible && <RendererErrorBoundary name="runtime-panel"><RuntimePanel id={RUNTIME_PANEL_ID} state={state} visible={runtimeVisible} drawer={narrowViewport && state.panelMode === "floating"} onPanelModeChange={setPanelMode} onClose={closeRuntimeDrawer} onRestoreToggleFocus={restoreRuntimeToggleFocus} /></RendererErrorBoundary>}
      {reviewPanelVisible && <RendererErrorBoundary name="review-panel"><ReviewPanel tabs={visibleReviewTabs} activeTabId={activeReviewTabId} width={effectiveDocumentPreviewWidth} minWidth={documentPreviewMinWidth} maxWidth={documentPreviewMaxWidth} onWidthChange={setDocumentPreviewWidth} onSelectTab={(id) => updateReviewPanel((current) => ({ ...current, activeTabId: id }))} onCloseTab={closeReviewTab} onClose={closeReviewPanel} onReadToolOutput={(id) => void readToolOutputPage(id)} onReadProcess={readProcess} /></RendererErrorBoundary>}
      {wideLayout && <ResizeSeparator side="sidebar" value={state.sidebarWidth} bounds={widthBounds.sidebar} label={t("resizeSidebar")} onPreview={(value) => setSidebarWidth(value)} onCommit={(value) => setSidebarWidth(value, true)} />}
      {wideLayout && state.mode === "coding" && state.panelMode === "docked" && !reviewPanelVisible && <ResizeSeparator side="runtime" value={state.runtimePanelWidth} bounds={widthBounds.runtime} label={t("resizeRuntimePanel")} onPreview={(value) => setRuntimePanelWidth(value)} onCommit={(value) => setRuntimePanelWidth(value, true)} />}
    </div>
  </LanguageProvider>;
}
