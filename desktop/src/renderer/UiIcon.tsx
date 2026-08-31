import type { ReactNode } from "react";

export type UiIconName = "plus" | "folder" | "chevron" | "pin" | "edit" | "external" | "trash" | "copy" | "more" | "settings" | "runtime" | "panel" | "compact" | "status";

export function UiIcon({ name }: { name: UiIconName }) {
  const paths: Record<UiIconName, ReactNode> = {
    plus: <path d="M8 3.25v9.5M3.25 8h9.5" />,
    folder: <path d="M2.75 5.25h10.5v7H2.75zM3.25 5.25V3.5h3.2l1.3 1.75" />,
    chevron: <path d="m5 6.25 3 3.25 3-3.25" />,
    pin: <path d="m5.1 3.25 5.8 5.8M9.75 2.75l3.5 3.5-2.2 1.2-2.5 2.5-1.2 2.2-3.5-3.5 2.2-1.2 2.5-2.5zM5.65 10.35l-2.9 2.9" />,
    edit: <path d="m3.25 11.75.55-2.7 6.9-6.9 2.15 2.15-6.9 6.9zM9.7 3.15l2.15 2.15" />,
    external: <path d="M6.25 3.25h-3v9.5h9.5v-3M8.25 2.75h5v5M13 3 7 9" />,
    trash: <path d="M3.5 4.75h9M6 2.75h4l.75 2M4.5 4.75l.5 8h6l.5-8M7 7v3.5M9.5 7v3.5" />,
    copy: <><rect x="5" y="4.5" width="7.5" height="8" rx="1" /><path d="M3.5 10.5V3.75c0-.55.45-1 1-1h5.75" /></>,
    more: <path d="M3.25 8h.5M7.75 8h.5M12.25 8h.5" strokeWidth="2.2" />,
    settings: <><circle cx="8" cy="8" r="2.1" /><path d="M8 2.5v1.2M8 12.3v1.2M2.5 8h1.2M12.3 8h1.2M4.1 4.1l.85.85M11.05 11.05l.85.85M11.9 4.1l-.85.85M4.95 11.05l-.85.85" /></>,
    runtime: <><rect x="2.75" y="3.25" width="10.5" height="9.5" rx="1.2" /><path d="M5 8h2l1-2 1.5 4 1-2H13" /></>,
    panel: <><rect x="2.75" y="3.25" width="10.5" height="9.5" rx="1.2" /><path d="M8.5 3.25v9.5" /></>,
    compact: <path d="M3.25 5.25h9.5M5.25 8h5.5M6.5 10.75h3" />,
    status: <><circle cx="8" cy="8" r="5.25" /><path d="M8 5v3.5l2.25 1.25" /></>,
  };
  return <svg className="ui-icon" viewBox="0 0 16 16" aria-hidden="true" focusable="false">{paths[name]}</svg>;
}
