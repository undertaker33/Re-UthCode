import { useState } from "react";

import type { ProjectState } from "./state";

export interface SidebarProps {
  projects: ProjectState[];
  selectedProjectKey: string | null;
  selectedSessionId: string | null;
  onNewSession: () => void;
  onOpenProject: () => void;
  onOpenProjectSession: (project: ProjectState) => void;
  onResumeSession: (project: ProjectState, sessionId: string) => void;
  onAliasChange: (projectKey: string, alias: string) => void;
  onTogglePin: (project: ProjectState) => void;
  onOpenExplorer: (project: ProjectState) => void;
  onRemoveProject: (project: ProjectState) => void | Promise<void>;
  onOpenSettings: () => void;
  runtimeHidden: boolean;
  runtimeOpen: boolean;
  onToggleRuntime: () => void;
  onRestoreRuntime: () => void;
}

function ProjectRow({ project, active, onOpen, onAliasChange, onTogglePin, onOpenExplorer, onRemoveProject, onResumeSession, selectedSessionId }: {
  project: ProjectState;
  active: boolean;
  onOpen: () => void;
  onAliasChange: (alias: string) => void;
  onTogglePin: () => void;
  onOpenExplorer: () => void;
  onRemoveProject: () => void;
  onResumeSession: (sessionId: string) => void;
  selectedSessionId: string | null;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(project.alias);
  const [confirmingRemoval, setConfirmingRemoval] = useState(false);

  const commitAlias = () => {
    const next = draft.trim();
    if (next && next !== project.alias) onAliasChange(next);
    setEditing(false);
  };

  return (
    <li className={`project-tree__item${active ? " is-active" : ""}`}>
      <div className="project-row">
        {editing ? (
          <input
            className="project-row__input"
            aria-label={`Edit ${project.alias}`}
            value={draft}
            autoFocus
            onChange={(event) => setDraft(event.target.value)}
            onBlur={commitAlias}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                commitAlias();
              }
              if (event.key === "Escape") {
                event.preventDefault();
                setDraft(project.alias);
                setEditing(false);
              }
            }}
          />
        ) : (
          <button className="project-row__button" type="button" onClick={onOpen} aria-current={active ? "page" : undefined}>
            <span className="project-row__mark" aria-hidden="true">{project.pinned ? "◆" : "◇"}</span>
            <span className="project-row__name">{project.alias}</span>
            {!project.catalogFresh && <span className="project-row__stale">cached</span>}
          </button>
        )}
        <div className="project-row__actions" aria-label={`${project.alias} actions`}>
          <button type="button" className="icon-button" onClick={() => setEditing(true)} aria-label={`Edit ${project.alias}`}>rename</button>
          <button type="button" className="icon-button" onClick={onTogglePin} aria-label={project.pinned ? `Unpin ${project.alias}` : `Pin ${project.alias}`}>{project.pinned ? "unpin" : "pin"}</button>
          <button type="button" className="icon-button" onClick={onOpenExplorer} aria-label={`Open ${project.alias} in Explorer`}>folder</button>
          <button type="button" className="icon-button danger-text" onClick={() => setConfirmingRemoval(true)} aria-label={`Remove ${project.alias}`}>remove</button>
        </div>
      </div>
      {active && (
        <ul className="session-list" aria-label={`${project.alias} sessions`}>
          <li>
            <button type="button" className="session-row session-row--new" onClick={() => onResumeSession("")}>
              <span aria-hidden="true">＋</span> New session
            </button>
          </li>
          {project.sessions.map((session) => (
            <li key={session.session_id}>
              <button type="button" className={`session-row${selectedSessionId === session.session_id ? " is-selected" : ""}`} onClick={() => onResumeSession(session.session_id)} disabled={session.corrupt === true}>
                <span className="session-row__label">{session.preview?.trim() || session.session_id.slice(0, 8)}</span>
                {session.corrupt === true && <span className="session-row__meta">recovery</span>}
              </button>
            </li>
          ))}
          {project.catalogFresh && project.sessions.length === 0 && <li className="session-list__empty">No sessions</li>}
        </ul>
      )}
      {confirmingRemoval && (
        <div className="inline-confirm" role="dialog" aria-label={`Remove ${project.alias}`}>
          <p>Remove this project from Desktop?</p>
          <div className="inline-confirm__actions">
            <button type="button" onClick={() => setConfirmingRemoval(false)}>Keep</button>
            <button type="button" className="danger-button" onClick={() => { setConfirmingRemoval(false); onRemoveProject(); }}>Remove</button>
          </div>
        </div>
      )}
    </li>
  );
}

export function Sidebar({ projects, selectedProjectKey, selectedSessionId, onNewSession, onOpenProject, onOpenProjectSession, onAliasChange, onTogglePin, onOpenExplorer, onRemoveProject, onOpenSettings, onResumeSession, runtimeHidden, runtimeOpen, onToggleRuntime, onRestoreRuntime }: SidebarProps) {
  const pinned = projects.filter((project) => project.pinned);
  const recent = projects.filter((project) => !project.pinned);
  return (
    <aside className="sidebar" aria-label="Project navigation">
      <div className="sidebar__brand">
        <div className="brand-lockup"><span className="brand-lockup__glyph" aria-hidden="true">U</span><span>UthCode</span></div>
        <span className="brand-lockup__version">DESKTOP</span>
      </div>
      <div className="sidebar__actions">
        <button type="button" className="primary-action" onClick={onNewSession}><span aria-hidden="true">＋</span> New chat</button>
        <button type="button" className="secondary-action" onClick={onOpenProject}><span aria-hidden="true">↗</span> Open project</button>
      </div>
      <nav className="project-navigation">
        {pinned.length > 0 && <ProjectGroup title="Pinned" projects={pinned} selectedProjectKey={selectedProjectKey} selectedSessionId={selectedSessionId} onOpenProjectSession={onOpenProjectSession} onAliasChange={onAliasChange} onTogglePin={onTogglePin} onOpenExplorer={onOpenExplorer} onRemoveProject={onRemoveProject} onResumeSession={onResumeSession} />}
        <ProjectGroup title="Projects" projects={recent} selectedProjectKey={selectedProjectKey} selectedSessionId={selectedSessionId} onOpenProjectSession={onOpenProjectSession} onAliasChange={onAliasChange} onTogglePin={onTogglePin} onOpenExplorer={onOpenExplorer} onRemoveProject={onRemoveProject} onResumeSession={onResumeSession} />
        {projects.length === 0 && <p className="sidebar__empty">Open a project to see its sessions.</p>}
      </nav>
      <div className="sidebar__footer">
        <button type="button" className="settings-link runtime-toggle" onClick={onToggleRuntime} aria-label="Toggle Runtime panel"><span aria-hidden="true">◈</span> {runtimeOpen ? "Hide Runtime" : "Open Runtime"}</button>
        {runtimeHidden && <button type="button" className="settings-link" onClick={onRestoreRuntime}><span aria-hidden="true">◈</span> Show Runtime</button>}
        <button type="button" className="settings-link" onClick={onOpenSettings}><span aria-hidden="true">⚙</span> Settings</button>
      </div>
    </aside>
  );
}

function ProjectGroup({ title, projects, selectedProjectKey, selectedSessionId, onOpenProjectSession, onAliasChange, onTogglePin, onOpenExplorer, onRemoveProject, onResumeSession }: {
  title: string;
  projects: ProjectState[];
  selectedProjectKey: string | null;
  selectedSessionId: string | null;
  onOpenProjectSession: (project: ProjectState) => void;
  onAliasChange: (projectKey: string, alias: string) => void;
  onTogglePin: (project: ProjectState) => void;
  onOpenExplorer: (project: ProjectState) => void;
  onRemoveProject: (project: ProjectState) => void | Promise<void>;
  onResumeSession: (project: ProjectState, sessionId: string) => void;
}) {
  if (projects.length === 0) return null;
  return (
    <section className="project-group" aria-labelledby={`project-group-${title.toLowerCase()}`}>
      <h2 id={`project-group-${title.toLowerCase()}`} className="sidebar__section-label">{title}</h2>
      <ul className="project-tree">
        {projects.map((project) => (
          <ProjectRow key={project.projectKey} project={project} active={project.projectKey === selectedProjectKey} selectedSessionId={selectedSessionId} onOpen={() => onOpenProjectSession(project)} onAliasChange={(alias) => onAliasChange(project.projectKey, alias)} onTogglePin={() => onTogglePin(project)} onOpenExplorer={() => onOpenExplorer(project)} onRemoveProject={() => onRemoveProject(project)} onResumeSession={(sessionId) => onResumeSession(project, sessionId)} />
        ))}
      </ul>
    </section>
  );
}
