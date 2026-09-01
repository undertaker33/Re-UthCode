import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import css from "../src/renderer/app.css";
import type { DesktopApi, DesktopPreferences, LanguagePreference, PreferenceKey, ThemePreference } from "../src/desktop-api";
import { App } from "../src/renderer/App";
import { CustomSelect } from "../src/renderer/CustomSelect";
import { LanguageProvider } from "../src/renderer/i18n";
import { SettingsView } from "../src/renderer/SettingsView";
import { createInitialState } from "../src/renderer/state";

const configuration = {
  default_model: "openai/codex", default_permission_mode: "default" as const,
  providers: { openai: { kind: "openai_responses", base_url: null, api_key_configured: true }, empty: { kind: "openai_compat", base_url: null, api_key_configured: false }, multi: { kind: "anthropic", base_url: null, api_key_configured: false } },
  models: { "openai/codex": { provider_profile_id: "openai", remote_id: "gpt-5.6-codex", display_name: "Codex", context_window: 128000, max_output_tokens: 8192, reasoning_effort: "low" }, "a/b": { provider_profile_id: "multi", remote_id: "claude-sonnet", display_name: "Slash", context_window: 200000, max_output_tokens: 8192, reasoning_effort: "low" }, "a-b": { provider_profile_id: "multi", remote_id: "claude-haiku", display_name: "Dash", context_window: 200000, max_output_tokens: 4096, reasoning_effort: null }, "中文/模型": { provider_profile_id: "multi", remote_id: "claude-chinese", display_name: "中文", context_window: 200000, max_output_tokens: 4096, reasoning_effort: "medium" } },
};
declare global { interface Window { fixtureEvidence: { reads: string[]; writes: Array<[string, unknown]>; saves: unknown[]; preferences: DesktopPreferences } } }
const preferences: DesktopPreferences = { theme: "dark", language: sessionStorage.getItem("uthcode.fixture.api.language") === "en" ? "en" : "zh-CN", windowBounds: { width: 1200, height: 800, maximized: false }, panelMode: "hidden", recentProjects: [], projectAliases: {}, pinnedProjectKeys: [], pinnedSessions: [], expandedProjects: {}, selectedProjectKey: null, selectedSessionId: null };
window.fixtureEvidence = { reads: [], writes: [], saves: [], preferences };
const fakeApi: DesktopApi = {
  openProject: async () => null, openProjectInExplorer: async () => undefined, copySessionId: async () => undefined, closeShell: async () => undefined,
  requestRuntime: async (method, params) => method === "settings.save" ? (window.fixtureEvidence.saves.push(params), { configuration }) : method === "settings.get" ? { configuration } : method === "settings.reveal_api_key" ? { api_key: "env:W04_FIXTURE_KEY" } : {},
  subscribeAgentEvents: () => () => undefined,
  readPreference: async <K extends PreferenceKey>(key: K) => { window.fixtureEvidence.reads.push(key); return window.fixtureEvidence.preferences[key]; },
  writePreference: async <K extends PreferenceKey>(key: K, value: DesktopPreferences[K]) => { window.fixtureEvidence.writes.push([key, value]); window.fixtureEvidence.preferences[key] = value as never; if (key === "language") sessionStorage.setItem("uthcode.fixture.api.language", String(value)); return { ...window.fixtureEvidence.preferences }; },
};
function Fixture() {
  const query = new URLSearchParams(location.search);
  const [theme, setTheme] = useState<ThemePreference>(query.get("theme") === "light" ? "light" : "dark");
  const requestedLanguage = query.get("lang");
  const [language, setLanguage] = useState<LanguagePreference>(() => requestedLanguage === "en" || requestedLanguage === "zh-CN" ? requestedLanguage : "zh-CN");
  const state = createInitialState({ runtimeState: "ready", theme, language, configuration, settingsLoaded: true });
  return <LanguageProvider value={language}><div className={`theme-${theme}`}><SettingsView state={state} onRevealApiKey={async () => "env:W04_FIXTURE_KEY"} onBack={() => undefined} onSave={(request) => { window.fixtureEvidence.saves.push(request); }} onThemeChange={setTheme} onLanguageChange={setLanguage} /></div></LanguageProvider>;
}
function SelectHarness() {
  const [value, setValue] = useState("");
  return <main><button id="before">Before</button><CustomSelect label="Acceptance select" value={value} options={[{ value: "", label: "Choose", disabled: true }, { value: "alpha", label: "Alpha" }, { value: "beta", label: "Beta" }, { value: "omega", label: "Omega" }]} onChange={setValue} /><CustomSelect label="Second select" value="alpha" options={[{ value: "alpha", label: "Alpha" }]} onChange={() => undefined} /><button id="after">After</button></main>;
}
function AppHarness() {
  const initialState = createInitialState({ runtimeState: "ready", view: "settings", configuration, settingsLoaded: true, theme: "dark", language: "zh-CN" });
  return <App api={fakeApi} initialState={initialState} />;
}
const style = document.createElement("style"); style.textContent = css; document.head.append(style);
const harness = new URLSearchParams(location.search).get("harness");
createRoot(document.getElementById("root")!).render(harness === "select" ? <SelectHarness /> : harness === "app" ? <AppHarness /> : <Fixture />);
document.documentElement.dataset.fixture = "prompt-2-settings";
