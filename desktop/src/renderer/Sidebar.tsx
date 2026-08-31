import { useEffect, useMemo, useState } from "react";
import type { ProjectState, SessionSummary } from "./state";
import { sessionLabel } from "./state";
import { UiIcon } from "./UiIcon";
import { useTranslation } from "./i18n";

export interface SidebarProps {
  projects: ProjectState[]; selectedProjectKey: string | null; selectedSessionId: string | null;
  onNewSession: () => void; onOpenProject: () => void; onOpenProjectSession: (project: ProjectState) => void;
  onResumeSession: (project: ProjectState, sessionId: string) => void; onAliasChange: (projectKey: string, alias: string) => void;
  onTogglePin: (project: ProjectState) => void; onOpenExplorer: (project: ProjectState) => void; onRemoveProject: (project: ProjectState) => void | Promise<void>;
  onToggleSessionPin: (project: ProjectState, session: SessionSummary) => void;
  onOpenSettings: () => void;
}

function ProjectEntry({ project, props }: { project: ProjectState; props: SidebarProps }) {
  const { t } = useTranslation();
  const active = project.projectKey === props.selectedProjectKey;
  const [expanded, setExpanded] = useState(active);
  const [editing, setEditing] = useState(false);
  const [alias, setAlias] = useState(project.alias);
  const [confirming, setConfirming] = useState(false);
  useEffect(() => { if (active) setExpanded(true); }, [active]);
  useEffect(() => { if (!editing) setAlias(project.alias); }, [editing, project.alias]);
  const commit = () => { const next = alias.trim(); if (next && next !== project.alias) props.onAliasChange(project.projectKey, next); else setAlias(project.alias); setEditing(false); };
  return <li className={`project-item${active ? " is-active" : ""}`}>
    <div className="project-line">
      <button type="button" className="icon-button disclosure" title={`${expanded ? t("collapse") : t("expand")} ${project.alias}`} aria-label={`${expanded ? t("collapse") : t("expand")} ${project.alias}`} aria-expanded={expanded} onClick={() => setExpanded((value) => !value)}><UiIcon name="chevron" /></button>
      {editing ? <input className="alias-input" aria-label={`${t("edit")} ${project.alias}`} autoFocus value={alias} onChange={(event) => setAlias(event.target.value)} onBlur={commit} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); commit(); } if (event.key === "Escape") { event.preventDefault(); setAlias(project.alias); setEditing(false); } }} /> : <button type="button" className="project-select" aria-current={active ? "page" : undefined} onClick={() => props.onOpenProjectSession(project)}><UiIcon name="folder" /><span>{project.alias}</span>{!project.catalogFresh && <small>{t("cached")}</small>}</button>}
      <div className="row-actions"><button type="button" className="icon-button" title={`${t("rename")} ${project.alias}`} aria-label={`${t("rename")} ${project.alias}`} onClick={() => setEditing(true)}><UiIcon name="edit" /></button><button type="button" className="icon-button" title={project.pinned ? `${t("unpin")} ${project.alias}` : `${t("pin")} ${project.alias}`} aria-label={project.pinned ? `${t("unpin")} ${project.alias}` : `${t("pin")} ${project.alias}`} onClick={() => props.onTogglePin(project)}><UiIcon name="pin" /></button><button type="button" className="icon-button" title={`${t("explorer")} ${project.alias}`} aria-label={`${t("explorer")} ${project.alias}`} onClick={() => props.onOpenExplorer(project)}><UiIcon name="external" /></button><button type="button" className="icon-button danger" title={`${t("remove")} ${project.alias}`} aria-label={`${t("remove")} ${project.alias}`} onClick={() => setConfirming(true)}><UiIcon name="trash" /></button></div>
    </div>
    {confirming && <div className="remove-confirm" role="dialog" aria-label={`${t("remove")} ${project.alias}`}><p>{t("removeProjectQuestion")}</p><div><button type="button" onClick={() => setConfirming(false)}>{t("keep")}</button><button type="button" className="danger" onClick={() => { setConfirming(false); void props.onRemoveProject(project); }}>{t("remove")}</button></div></div>}
    {expanded && <ul className="session-list" aria-label={`${project.alias} ${t("session")}`}><li><button type="button" className="session-line new-session-line" onClick={() => props.onResumeSession(project, "")}><UiIcon name="plus" />{t("newSession")}</button></li>{project.sessions.filter((session) => project.pinned || !session.pinned).map((session) => <li className="session-item" key={session.session_id}><button type="button" className={`session-line${session.session_id === props.selectedSessionId ? " is-selected" : ""}`} disabled={session.corrupt === true} onClick={() => props.onResumeSession(project, session.session_id)}><span className="session-dot" /> <span>{sessionLabel(session)}</span>{session.corrupt && <small>{t("recovery")}</small>}</button>{!project.pinned && <button type="button" className="icon-button session-pin" title={`${session.pinned ? t("unpin") : t("pin")} ${t("session")} ${sessionLabel(session)}`} aria-label={`${session.pinned ? t("unpin") : t("pin")} ${t("session")} ${sessionLabel(session)}`} onClick={() => props.onToggleSessionPin(project, session)}><UiIcon name="pin" /></button>}</li>)}{project.catalogFresh && project.sessions.length === 0 && <li className="empty-line">{t("noSessions")}</li>}</ul>}
  </li>;
}

function Group({ title, projects, props }: { title: string; projects: ProjectState[]; props: SidebarProps }) {
  if (!projects.length) return null;
  return <section className="nav-group" aria-labelledby={`nav-${title.toLowerCase()}`}><h2 id={`nav-${title.toLowerCase()}`}>{title}</h2><ul className="project-list">{projects.map((project) => <ProjectEntry key={project.projectKey} project={project} props={props} />)}</ul></section>;
}

function Recent({ entries, props }: { entries: Array<{ project: ProjectState; session: SessionSummary }>; props: SidebarProps }) {
  const { t } = useTranslation();
  if (!entries.length) return null;
  return <section className="nav-group recent" aria-labelledby="nav-recent"><h2 id="nav-recent">{t("recent")}</h2><ul>{entries.map(({ project, session }) => <li key={`${project.projectKey}:${session.session_id}`}><button type="button" className={`recent-line${session.session_id === props.selectedSessionId ? " is-selected" : ""}`} onClick={() => props.onResumeSession(project, session.session_id)}><span className="session-dot" /><span>{sessionLabel(session)}</span><small>{project.alias}</small></button></li>)}</ul></section>;
}

function PinnedSessions({ entries, props }: { entries: Array<{ project: ProjectState; session: SessionSummary }>; props: SidebarProps }) {
  const { t } = useTranslation();
  if (!entries.length) return null;
  return <section className="nav-group pinned-sessions" aria-labelledby="nav-pinned-sessions"><h2 id="nav-pinned-sessions">{t("pinnedSessions")}</h2><ul>{entries.map(({ project, session }) => <li className="session-item" key={`${project.projectKey}:${session.session_id}`}><button type="button" className={`recent-line${session.session_id === props.selectedSessionId ? " is-selected" : ""}`} onClick={() => props.onResumeSession(project, session.session_id)}><span className="session-dot" /><span>{sessionLabel(session)}</span><small>{project.alias}</small></button><button type="button" className="icon-button session-pin" title={`${t("unpin")} ${sessionLabel(session)}`} aria-label={`${t("unpin")} ${sessionLabel(session)}`} onClick={() => props.onToggleSessionPin(project, session)}><UiIcon name="pin" /></button></li>)}</ul></section>;
}

export function Sidebar(props: SidebarProps) {
  const { t } = useTranslation();
  const pinned = props.projects.filter((project) => project.pinned);
  const projects = props.projects.filter((project) => !project.pinned);
  const pinnedSessions = useMemo(() => props.projects.flatMap((project) => project.pinned ? [] : project.sessions.filter((session) => session.pinned && !session.corrupt).map((session) => ({ project, session }))), [props.projects]);
  const recent = useMemo(() => props.projects.flatMap((project) => project.pinned ? [] : project.sessions.filter((session) => !session.corrupt && !session.pinned).map((session) => ({ project, session }))).slice(0, 5), [props.projects]);
  return <aside className="sidebar" aria-label={t("projects")}><header className="sidebar-brand"><span className="brand-mark">U</span><strong>UthCode</strong></header><div className="sidebar-primary"><button type="button" className="primary-row" title={t("newChat")} onClick={props.onNewSession}><UiIcon name="plus" />{t("newChat")}</button><button type="button" className="secondary-row" title={t("openProject")} onClick={props.onOpenProject}><UiIcon name="folder" />{t("openProject")}</button></div><nav className="sidebar-scroll"><Group title={t("pinned")} projects={pinned} props={props} /><PinnedSessions entries={pinnedSessions} props={props} /><Group title={t("projects")} projects={projects} props={props} /><Recent entries={recent} props={props} />{props.projects.length === 0 && <p className="empty-line">{t("openProject")}</p>}</nav><footer className="sidebar-footer"><button type="button" title={t("openSettings")} onClick={props.onOpenSettings}><UiIcon name="settings" />{t("settings")}</button></footer></aside>;
}
