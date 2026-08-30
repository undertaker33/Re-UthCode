import { useEffect, useState } from "react";
import type { ProjectState } from "./state";
import { sessionLabel } from "./state";

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

function ProjectEntry({ project, selectedProjectKey, selectedSessionId, onOpen, onResume, onAliasChange, onTogglePin, onOpenExplorer, onRemove }: {
  project: ProjectState;
  selectedProjectKey: string | null;
  selectedSessionId: string | null;
  onOpen: () => void;
  onResume: (sessionId: string) => void;
  onAliasChange: (alias: string) => void;
  onTogglePin: () => void;
  onOpenExplorer: () => void;
  onRemove: () => void | Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [alias, setAlias] = useState(project.alias);
  const [confirming, setConfirming] = useState(false);
  useEffect(() => { if (!editing) setAlias(project.alias); }, [editing, project.alias]);
  const commit = () => {
    const next = alias.trim();
    if (next && next !== project.alias) onAliasChange(next);
    else setAlias(project.alias);
    setEditing(false);
  };
  return (
    <li>
      <h3>
        {editing ? <input aria-label={`Edit ${project.alias}`} autoFocus value={alias} onChange={(event) => setAlias(event.target.value)} onBlur={commit} onKeyDown={(event) => {
          if (event.key === "Enter") { event.preventDefault(); commit(); }
          if (event.key === "Escape") { event.preventDefault(); setAlias(project.alias); setEditing(false); }
        }} /> : <button type="button" aria-current={project.projectKey === selectedProjectKey ? "page" : undefined} onClick={onOpen}>{project.alias}</button>}
      </h3>
      <div>
        <button type="button" onClick={() => setEditing(true)}>Rename</button>
        <button type="button" onClick={onTogglePin}>{project.pinned ? "Unpin" : "Pin"}</button>
        <button type="button" onClick={onOpenExplorer}>Open in Explorer</button>
        <button type="button" onClick={() => setConfirming(true)}>Remove from Desktop</button>
      </div>
      {confirming && <div role="dialog" aria-label={`Remove ${project.alias}`}><p>Remove this project from Desktop? Files and Sessions remain on disk.</p><button type="button" onClick={() => setConfirming(false)}>Keep</button><button type="button" onClick={() => { setConfirming(false); void onRemove(); }}>Remove</button></div>}
      <ul aria-label={`${project.alias} sessions`}>
        {project.sessions.map((session) => <li key={session.session_id}><button type="button" disabled={session.corrupt === true} aria-current={session.session_id === selectedSessionId ? "page" : undefined} onClick={() => onResume(session.session_id)}>{sessionLabel(session)}{session.corrupt ? " (recovery required)" : ""}</button></li>)}
      </ul>
    </li>
  );
}

function ProjectGroup({ label, projects, props }: { label: string; projects: ProjectState[]; props: SidebarProps }) {
  if (projects.length === 0) return null;
  return <section aria-labelledby={`project-group-${label.toLowerCase()}`}><h2 id={`project-group-${label.toLowerCase()}`}>{label}</h2><ul>{projects.map((project) => <ProjectEntry key={project.projectKey} project={project} selectedProjectKey={props.selectedProjectKey} selectedSessionId={props.selectedSessionId} onOpen={() => props.onOpenProjectSession(project)} onResume={(sessionId) => props.onResumeSession(project, sessionId)} onAliasChange={(alias) => props.onAliasChange(project.projectKey, alias)} onTogglePin={() => props.onTogglePin(project)} onOpenExplorer={() => props.onOpenExplorer(project)} onRemove={() => props.onRemoveProject(project)} />)}</ul></section>;
}

export function Sidebar(props: SidebarProps) {
  const pinned = props.projects.filter((project) => project.pinned);
  const projects = props.projects.filter((project) => !project.pinned);
  return (
    <aside aria-label="Project navigation">
      <h1>UthCode</h1>
      <div><button type="button" onClick={props.onNewSession}>New session</button><button type="button" onClick={props.onOpenProject}>Open project</button></div>
      <nav aria-label="Projects and sessions">
        <ProjectGroup label="Pinned" projects={pinned} props={props} />
        <ProjectGroup label="Projects" projects={projects} props={props} />
        {props.projects.length === 0 && <p>No projects open.</p>}
      </nav>
      <div><button type="button" onClick={props.runtimeHidden ? props.onRestoreRuntime : props.onToggleRuntime}>{props.runtimeHidden ? "Open Runtime" : props.runtimeOpen ? "Hide Runtime" : "Open Runtime"}</button><button type="button" onClick={props.onOpenSettings}>Settings</button></div>
    </aside>
  );
}
