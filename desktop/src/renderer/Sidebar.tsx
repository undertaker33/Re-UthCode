import { useCallback, useEffect, useId, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent, type RefObject, type SyntheticEvent } from "react";
import type { ProjectState, SessionSummary } from "./state";
import { sessionLabel } from "./state";
import { UiIcon, type UiIconName } from "./UiIcon";
import { useTranslation } from "./i18n";

export const MAX_VISIBLE_SESSIONS = 5;

export interface SidebarProps {
  projects: ProjectState[];
  selectedProjectKey: string | null;
  selectedSessionId: string | null;
  activeTurn: boolean;
  sessionMutationBusy?: boolean;
  expandedProjects: Record<string, boolean>;
  onProjectExpandedChange: (projectKey: string, expanded: boolean) => void;
  onNewSession: () => void;
  onOpenProject: () => void;
  onOpenProjectSession: (project: ProjectState) => void;
  onResumeSession: (project: ProjectState, sessionId: string) => void;
  onAliasChange: (projectKey: string, alias: string) => void;
  onTogglePin: (project: ProjectState) => void;
  onOpenExplorer: (project: ProjectState) => void;
  onRemoveProject: (project: ProjectState) => void | Promise<void>;
  onToggleSessionPin: (project: ProjectState, session: SessionSummary) => void;
  onRenameSession: (project: ProjectState, session: SessionSummary, title: string) => void | Promise<void>;
  onMoveSession: (project: ProjectState, session: SessionSummary, target: ProjectState) => void | Promise<void>;
  onCopySessionId: (session: SessionSummary) => void | Promise<void>;
  onOpenSettings: () => void;
}

type MenuTarget =
  | { kind: "project"; projectKey: string }
  | { kind: "session"; projectKey: string; sessionId: string; variant: "project" | "recent" };

interface MenuAction {
  id: string;
  label: string;
  icon?: UiIconName;
  danger?: boolean;
  disabled?: boolean;
  disabledReason?: string;
  separatorBefore?: boolean;
  onSelect: () => void;
}

interface FloatingMenuProps {
  label: string;
  actions: MenuAction[];
  anchorRef: RefObject<HTMLElement | null>;
  onClose: () => void;
}

const MENU_WIDTH = 244;
const MENU_MARGIN = 8;

function menuPosition(anchor: HTMLElement, actionCount: number): CSSProperties {
  const rect = anchor.getBoundingClientRect();
  const viewportWidth = Math.max(document.documentElement.clientWidth, window.innerWidth);
  const viewportHeight = Math.max(document.documentElement.clientHeight, window.innerHeight);
  const estimatedHeight = Math.min(380, Math.max(48, actionCount * 40 + 12));
  const topBelow = rect.bottom + 5;
  const top = topBelow + estimatedHeight <= viewportHeight - MENU_MARGIN
    ? topBelow
    : Math.max(MENU_MARGIN, rect.top - estimatedHeight - 5);
  const rightOfAnchor = rect.right + 5;
  const leftOfAnchor = rect.left - MENU_WIDTH - 5;
  const left = rightOfAnchor + MENU_WIDTH <= viewportWidth - MENU_MARGIN
    ? rightOfAnchor
    : Math.max(MENU_MARGIN, Math.min(leftOfAnchor, viewportWidth - MENU_WIDTH - MENU_MARGIN));
  return { top, left };
}

function FloatingMenu({ label, actions, anchorRef, onClose }: FloatingMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const [position, setPosition] = useState<CSSProperties | null>(null);
  const menuId = useId();
  const enabledIndexes = useMemo(
    () => actions.flatMap((action, index) => action.disabled ? [] : [index]),
    [actions],
  );

  useEffect(() => {
    const updatePosition = () => {
      const anchor = anchorRef.current;
      if (anchor) setPosition(menuPosition(anchor, actions.length));
    };
    updatePosition();
    window.addEventListener("resize", updatePosition);
    document.addEventListener("scroll", updatePosition, true);
    const focusTimer = window.setTimeout(() => {
      const first = enabledIndexes[0];
      if (first !== undefined) itemRefs.current[first]?.focus();
    }, 0);
    return () => {
      window.clearTimeout(focusTimer);
      window.removeEventListener("resize", updatePosition);
      document.removeEventListener("scroll", updatePosition, true);
    };
  }, [actions.length, anchorRef, enabledIndexes]);

  const closeMenu = useCallback((restoreFocus = true) => {
    onClose();
    // Restore focus to the single menu trigger before the parent unmounts the
    // popover; a rename action can then move focus to its input through
    // autoFocus.
    if (restoreFocus) anchorRef.current?.querySelector<HTMLButtonElement>(".menu-trigger")?.focus();
  }, [anchorRef, onClose]);

  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (target && !menuRef.current?.contains(target) && !anchorRef.current?.contains(target)) closeMenu();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeMenu();
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [closeMenu, anchorRef]);

  const moveFocus = (current: number, direction: 1 | -1) => {
    if (!enabledIndexes.length) return;
    const currentPosition = enabledIndexes.indexOf(current);
    const start = currentPosition < 0 ? (direction > 0 ? 0 : enabledIndexes.length - 1) : currentPosition;
    const next = enabledIndexes[(start + direction + enabledIndexes.length) % enabledIndexes.length];
    itemRefs.current[next]?.focus();
  };

  const leaveMenu = (event: ReactKeyboardEvent<HTMLDivElement>, direction: 1 | -1) => {
    const trigger = anchorRef.current?.querySelector<HTMLButtonElement>(".menu-trigger");
    const menu = menuRef.current;
    const focusable = Array.from(document.querySelectorAll<HTMLElement>(
      "button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), a[href], [tabindex]:not([tabindex='-1'])",
    )).filter((element) => !menu?.contains(element));
    const triggerIndex = trigger ? focusable.indexOf(trigger) : -1;
    const next = triggerIndex < 0 ? undefined : focusable[triggerIndex + direction];
    closeMenu(false);
    if (next) {
      // This is the browser's normal document order made explicit so closing
      // the popover does not leave focus on the soon-to-be-removed menu item.
      event.preventDefault();
      next.focus();
    }
  };

  const onMenuKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    const current = itemRefs.current.findIndex((item) => item === target);
    if (event.key === "ArrowDown") {
      event.preventDefault();
      moveFocus(current, 1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      moveFocus(current, -1);
    } else if (event.key === "Home") {
      event.preventDefault();
      const first = enabledIndexes[0];
      if (first !== undefined) itemRefs.current[first]?.focus();
    } else if (event.key === "End") {
      event.preventDefault();
      const last = enabledIndexes.at(-1);
      if (last !== undefined) itemRefs.current[last]?.focus();
    } else if (event.key === "Tab") {
      leaveMenu(event, event.shiftKey ? -1 : 1);
    }
  };

  const style = position ?? { visibility: "hidden" as const };
  return <div
    ref={menuRef}
    id={menuId}
    className="sidebar-menu"
    role="menu"
    aria-label={label}
    style={style}
    onKeyDown={onMenuKeyDown}
  >
    {actions.map((action, index) => <div className={action.separatorBefore ? "sidebar-menu__separator" : undefined} key={action.id}>
      <button
        ref={(node) => { itemRefs.current[index] = node; }}
        type="button"
        role="menuitem"
        className={`sidebar-menu__item${action.danger ? " danger" : ""}`}
        disabled={action.disabled}
        title={action.disabled ? action.disabledReason : action.label}
        aria-label={action.disabled && action.disabledReason ? `${action.label}: ${action.disabledReason}` : action.label}
        onClick={() => {
          if (action.disabled) return;
          closeMenu();
          action.onSelect();
        }}
      >
        {action.icon && <UiIcon name={action.icon} />}
        <span>{action.label}</span>
      </button>
    </div>)}
  </div>;
}

function sessionInfo(project: ProjectState, session: SessionSummary): string {
  const label = sessionLabel(session);
  const title = session.title?.trim() || label;
  return `${title} · ${session.session_id} · ${project.alias} · ${project.path}`;
}

export function sessionGroups(sessions: SessionSummary[], showMore: boolean) {
  const pinned = sessions.filter((session) => session.pinned);
  const ordinary = sessions.filter((session) => !session.pinned);
  const visibleOrdinary = showMore ? ordinary : ordinary.slice(0, MAX_VISIBLE_SESSIONS);
  return {
    pinned,
    ordinary,
    visibleOrdinary,
    hiddenCount: Math.max(0, ordinary.length - MAX_VISIBLE_SESSIONS),
  };
}

interface ProjectEntryProps {
  project: ProjectState;
  props: SidebarProps;
  menuTarget: MenuTarget | null;
  onMenuTarget: (target: MenuTarget | null) => void;
}

function ProjectEntry({ project, props, menuTarget, onMenuTarget }: ProjectEntryProps) {
  const { t } = useTranslation();
  const active = project.projectKey === props.selectedProjectKey;
  const [expanded, setExpanded] = useState(active);
  const [showMore, setShowMore] = useState(props.expandedProjects[project.projectKey] === true);
  const [editing, setEditing] = useState(false);
  const [alias, setAlias] = useState(project.alias);
  const [confirming, setConfirming] = useState(false);
  const menuAnchorRef = useRef<HTMLDivElement>(null);
  const menuOpen = menuTarget?.kind === "project" && menuTarget.projectKey === project.projectKey;

  useEffect(() => { if (active) setExpanded(true); }, [active]);
  useEffect(() => {
    setShowMore(props.expandedProjects[project.projectKey] === true);
  }, [project.projectKey, props.expandedProjects]);
  useEffect(() => { if (!editing) setAlias(project.alias); }, [editing, project.alias]);

  const commitAlias = () => {
    const next = alias.trim();
    if (next && next !== project.alias) props.onAliasChange(project.projectKey, next);
    else setAlias(project.alias);
    setEditing(false);
  };

  const actions: MenuAction[] = [
    {
      id: "toggle-pin",
      label: project.pinned ? t("unpin") : t("pin"),
      icon: "pin",
      onSelect: () => props.onTogglePin(project),
    },
    {
      id: "rename",
      label: t("rename"),
      icon: "edit",
      onSelect: () => setEditing(true),
    },
    {
      id: "explorer",
      label: t("explorer"),
      icon: "external",
      separatorBefore: true,
      onSelect: () => props.onOpenExplorer(project),
    },
    {
      id: "remove",
      label: t("remove"),
      icon: "trash",
      danger: true,
      separatorBefore: true,
      onSelect: () => setConfirming(true),
    },
  ];
  const groups = sessionGroups(project.sessions, showMore);
  const selectedInProject = props.selectedSessionId !== null
    && project.sessions.some((session) => session.session_id === props.selectedSessionId);
  const selectedVisibleInCollapsedList = selectedInProject
    && (groups.pinned.some((session) => session.session_id === props.selectedSessionId)
      || groups.visibleOrdinary.some((session) => session.session_id === props.selectedSessionId));
  // Keep the selected row visible without changing the authoritative session
  // order.  The derived flag is intentionally not persisted as a pin or a
  // catalog mutation; the user's explicit "show more" choice remains stable.
  const visibleShowMore = showMore || (selectedInProject && !selectedVisibleInCollapsedList);
  const visibleGroups = sessionGroups(project.sessions, visibleShowMore);
  const visibleExpanded = expanded || selectedInProject;
  useEffect(() => {
    if (selectedInProject && !selectedVisibleInCollapsedList && !showMore) {
      // Persist the stable expansion chosen by the selection itself.  This
      // keeps a selected sixth row visible across the next catalog refresh or
      // component remount without changing the catalog order.
      setShowMore(true);
      props.onProjectExpandedChange(project.projectKey, true);
    }
  }, [project.projectKey, props.onProjectExpandedChange, selectedInProject, selectedVisibleInCollapsedList, showMore]);
  const openMenu = (event?: SyntheticEvent) => {
    event?.preventDefault();
    onMenuTarget(menuOpen ? null : { kind: "project", projectKey: project.projectKey });
  };

  return <li className={`project-item${active ? " is-active" : ""}`}>
    <div
      ref={menuAnchorRef}
      className="project-menu-anchor"
      onContextMenu={(event) => {
        if ((event.target as HTMLElement).closest('[role="menu"]')) return;
        openMenu(event);
      }}
    >
      <div className="project-line">
        <button
          type="button"
          className="icon-button disclosure"
          title={`${expanded ? t("collapse") : t("expand")} ${project.alias}`}
          aria-label={`${expanded ? t("collapse") : t("expand")} ${project.alias}`}
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
        ><UiIcon name="chevron" /></button>
        {editing ? <input
          className="alias-input"
          aria-label={`${t("edit")} ${project.alias}`}
          autoFocus
          value={alias}
          onChange={(event) => setAlias(event.target.value)}
          onBlur={commitAlias}
          onKeyDown={(event) => {
            if (event.key === "Enter") { event.preventDefault(); commitAlias(); }
            if (event.key === "Escape") { event.preventDefault(); setAlias(project.alias); setEditing(false); }
          }}
        /> : <button
          type="button"
          className="project-select"
          title={project.path}
          aria-label={`${project.alias} · ${project.path}`}
          aria-current={active ? "page" : undefined}
          onClick={() => props.onOpenProjectSession(project)}
        ><UiIcon name="folder" /><span>{project.alias}</span>{!project.catalogFresh && <small>{t("cached")}</small>}</button>}
        <button
          type="button"
          className="icon-button menu-trigger"
          title={`${t("more")} ${project.alias}`}
          aria-label={`${t("more")} ${project.alias}`}
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          onClick={openMenu}
        ><UiIcon name="more" /></button>
      </div>
      {menuOpen && <FloatingMenu label={`${project.alias} ${t("more")}`} actions={actions} anchorRef={menuAnchorRef} onClose={() => onMenuTarget(null)} />}
    </div>
    {confirming && <div className="remove-confirm" role="alertdialog" aria-label={`${t("remove")} ${project.alias}`}>
      <p>{t("removeProjectQuestion")}</p>
      <div>
        <button type="button" title={t("keep")} onClick={() => setConfirming(false)}>{t("keep")}</button>
        <button type="button" className="danger" title={t("remove")} onClick={() => { setConfirming(false); void props.onRemoveProject(project); }}>{t("remove")}</button>
      </div>
    </div>}
    {visibleExpanded && <ul className="session-list" aria-label={`${project.alias} ${t("session")}`}>
      <li><button type="button" className="session-line new-session-line" title={t("newSession")} onClick={() => props.onResumeSession(project, "")}><UiIcon name="plus" />{t("newSession")}</button></li>
      {visibleGroups.pinned.map((session) => <SessionEntry key={session.session_id} project={project} session={session} props={props} menuTarget={menuTarget} onMenuTarget={onMenuTarget} />)}
      {visibleGroups.visibleOrdinary.map((session) => <SessionEntry key={session.session_id} project={project} session={session} props={props} menuTarget={menuTarget} onMenuTarget={onMenuTarget} />)}
      {groups.hiddenCount > 0 && <li><button
        type="button"
        className="session-more"
        title={visibleShowMore ? t("showLess") : `${t("showMore")} (${groups.hiddenCount})`}
        aria-expanded={visibleShowMore}
        onClick={() => {
          const next = !visibleShowMore;
          setShowMore(next);
          props.onProjectExpandedChange(project.projectKey, next);
        }}
      >{visibleShowMore ? t("showLess") : `${t("showMore")} (${groups.hiddenCount})`}</button></li>}
      {project.catalogFresh && project.sessions.length === 0 && <li className="empty-line">{t("noSessions")}</li>}
    </ul>}
  </li>;
}

interface SessionEntryProps {
  project: ProjectState;
  session: SessionSummary;
  props: SidebarProps;
  menuTarget: MenuTarget | null;
  onMenuTarget: (target: MenuTarget | null) => void;
  variant?: "project" | "recent";
}

function SessionEntry({ project, session, props, menuTarget, onMenuTarget, variant = "project" }: SessionEntryProps) {
  const { t } = useTranslation();
  const menuAnchorRef = useRef<HTMLDivElement>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(session.title ?? session.preview ?? "");
  const menuOpen = menuTarget?.kind === "session"
    && menuTarget.projectKey === project.projectKey
    && menuTarget.sessionId === session.session_id
    && menuTarget.variant === variant;
  // A selected Session may be moved while it is idle.  The Application is
  // the authority for the mutation; an active Turn and another pending
  // mutation both block the action.
  const busy = props.activeTurn || props.sessionMutationBusy === true;
  const moveTargets = props.projects.filter((item) => item.projectKey !== project.projectKey);
  const moveDisabledReason = props.activeTurn
    ? t("sessionMoveActive")
    : props.sessionMutationBusy
      ? t("sessionMutationBusy")
      : undefined;
  const canMutate = !session.corrupt;
  const renameDisabledReason = !canMutate
    ? t("sessionCorrupt")
    : props.activeTurn
      ? t("sessionRenameActive")
      : props.sessionMutationBusy
        ? t("sessionMutationBusy")
        : undefined;
  const actions: MenuAction[] = [
    {
      id: "toggle-pin",
      label: session.pinned ? t("unpin") : t("pin"),
      icon: "pin",
      // W06 established single ownership: a pinned Project owns the visible
      // child list, so its Sessions cannot also create independent pins.
      disabled: !canMutate || project.pinned,
      disabledReason: !canMutate ? t("sessionCorrupt") : project.pinned ? t("sessionPinProject") : undefined,
      onSelect: () => props.onToggleSessionPin(project, session),
    },
    {
      id: "rename",
      label: t("rename"),
      icon: "edit",
      disabled: !canMutate || busy,
      disabledReason: renameDisabledReason,
      onSelect: () => {
        setDraft(session.title ?? session.preview ?? "");
        setEditing(true);
      },
    },
    ...((moveTargets.length ? moveTargets : [null]).map((target, index): MenuAction => ({
      id: target ? `move:${target.projectKey}` : "move:none",
      label: target ? `${t("moveToProject")} ${target.alias}` : t("moveToProject"),
      icon: "folder",
      separatorBefore: index === 0,
      disabled: !target || busy || !canMutate,
      disabledReason: !canMutate ? t("sessionCorrupt") : moveDisabledReason ?? t("noOtherProjects"),
      onSelect: () => { if (target) void props.onMoveSession(project, session, target); },
    }))),
    {
      id: "copy-id",
      label: t("copySessionId"),
      icon: "copy",
      separatorBefore: true,
      onSelect: () => void props.onCopySessionId(session),
    },
  ];

  useEffect(() => { if (!editing) setDraft(session.title ?? session.preview ?? ""); }, [editing, session.preview, session.title]);

  const commitTitle = () => {
    const next = draft.trim();
    const current = session.title?.trim() || session.preview?.trim() || "";
    if (next && next !== current) void props.onRenameSession(project, session, next);
    setEditing(false);
  };
  const openMenu = (event?: SyntheticEvent) => {
    event?.preventDefault();
    onMenuTarget(menuOpen ? null : { kind: "session", projectKey: project.projectKey, sessionId: session.session_id, variant });
  };
  const rowClass = variant === "recent" ? "recent-line" : "session-line";
  return <li className={`session-item${variant === "recent" ? " recent-session-item" : ""}`}>
    <div
      ref={menuAnchorRef}
      className="session-menu-anchor"
      onContextMenu={(event) => {
        if ((event.target as HTMLElement).closest('[role="menu"]')) return;
        openMenu(event);
      }}
    >
      {editing ? <input
        className="session-title-input"
        autoFocus
        disabled={props.sessionMutationBusy === true}
        aria-busy={props.sessionMutationBusy === true ? "true" : undefined}
        aria-label={`${t("rename")} ${sessionLabel(session)}`}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commitTitle}
        onKeyDown={(event) => {
          if (event.key === "Enter") { event.preventDefault(); commitTitle(); }
          if (event.key === "Escape") { event.preventDefault(); setEditing(false); }
        }}
      /> : <button
        type="button"
        className={`${rowClass}${session.session_id === props.selectedSessionId ? " is-selected" : ""}`}
        title={sessionInfo(project, session)}
        aria-label={sessionInfo(project, session)}
        disabled={session.corrupt === true}
        onClick={() => props.onResumeSession(project, session.session_id)}
      ><span className="session-dot" /> <span>{sessionLabel(session)}</span>{session.corrupt && <small>{t("recovery")}</small>}{variant === "recent" && <small>{project.alias}</small>}</button>}
      <button
        type="button"
        className="icon-button menu-trigger session-menu-trigger"
        title={`${t("more")} ${sessionLabel(session)}`}
        aria-label={`${t("more")} ${sessionLabel(session)}`}
        aria-haspopup="menu"
        aria-expanded={menuOpen}
        onClick={openMenu}
      ><UiIcon name="more" /></button>
      {menuOpen && <FloatingMenu label={`${sessionLabel(session)} ${t("more")}`} actions={actions} anchorRef={menuAnchorRef} onClose={() => onMenuTarget(null)} />}
    </div>
  </li>;
}

function Group({ title, projects, props, menuTarget, onMenuTarget }: { title: string; projects: ProjectState[]; props: SidebarProps; menuTarget: MenuTarget | null; onMenuTarget: (target: MenuTarget | null) => void }) {
  if (!projects.length) return null;
  const id = `nav-${title.toLowerCase().replace(/\s+/gu, "-")}`;
  return <section className="nav-group" aria-labelledby={id}><h2 id={id}>{title}</h2><ul className="project-list">{projects.map((project) => <ProjectEntry key={project.projectKey} project={project} props={props} menuTarget={menuTarget} onMenuTarget={onMenuTarget} />)}</ul></section>;
}

function Recent({ entries, props, menuTarget, onMenuTarget }: { entries: Array<{ project: ProjectState; session: SessionSummary }>; props: SidebarProps; menuTarget: MenuTarget | null; onMenuTarget: (target: MenuTarget | null) => void }) {
  const { t } = useTranslation();
  if (!entries.length) return null;
  return <section className="nav-group recent" aria-labelledby="nav-recent"><h2 id="nav-recent">{t("recent")}</h2><ul>{entries.map(({ project, session }) => <SessionEntry key={`${project.projectKey}:${session.session_id}`} project={project} session={session} props={props} menuTarget={menuTarget} onMenuTarget={onMenuTarget} variant="recent" />)}</ul></section>;
}

export function Sidebar(props: SidebarProps) {
  const { t } = useTranslation();
  const [menuTarget, setMenuTarget] = useState<MenuTarget | null>(null);
  const pinned = props.projects.filter((project) => project.pinned);
  const projects = props.projects.filter((project) => !project.pinned);
  const recent = useMemo(
    // A pinned Project owns its child list.  Keep those Sessions out of
    // Recent so selecting/expanding a Project never duplicates or reorders
    // its rows in a second navigation section.
    () => {
      const all = props.projects.flatMap((project) => project.pinned ? [] : project.sessions.filter((session) => !session.corrupt && !session.pinned).map((session) => ({ project, session })));
      const visible = all.slice(0, 5);
      const selected = props.selectedSessionId === null ? undefined : all.find(({ session }) => session.session_id === props.selectedSessionId);
      if (!selected || visible.some(({ project, session }) => project.projectKey === selected.project.projectKey && session.session_id === selected.session.session_id)) return visible;
      // Recent has no separate expand control.  Append a hidden selected row
      // in its stable catalog position instead of moving it to the head.
      return [...visible, selected];
    },
    [props.projects, props.selectedSessionId],
  );
  return <aside className="sidebar" aria-label={t("projects")} aria-busy={props.sessionMutationBusy === true ? "true" : undefined}><header className="sidebar-brand"><span className="brand-mark">U</span><strong>UthCode</strong></header><div className="sidebar-primary"><button type="button" className="primary-row" title={t("newChat")} onClick={props.onNewSession}><UiIcon name="plus" />{t("newChat")}</button><button type="button" className="secondary-row" title={t("openProject")} onClick={props.onOpenProject}><UiIcon name="folder" />{t("openProject")}</button></div><nav className="sidebar-scroll"><Group title={t("pinned")} projects={pinned} props={props} menuTarget={menuTarget} onMenuTarget={setMenuTarget} /><Group title={t("projects")} projects={projects} props={props} menuTarget={menuTarget} onMenuTarget={setMenuTarget} /><Recent entries={recent} props={props} menuTarget={menuTarget} onMenuTarget={setMenuTarget} />{props.projects.length === 0 && <p className="empty-line">{t("openProject")}</p>}</nav><footer className="sidebar-footer"><button type="button" title={t("openSettings")} onClick={props.onOpenSettings}><UiIcon name="settings" />{t("settings")}</button></footer></aside>;
}
