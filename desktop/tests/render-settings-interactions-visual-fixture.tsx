import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { InteractionSurface } from "../src/renderer/InteractionSurface";
import { SettingsView } from "../src/renderer/SettingsView";
import { createInitialState, type PendingInteraction } from "../src/renderer/state";

const configuration = {
  default_model: "openai/codex",
  default_permission_mode: "default",
  providers: {
    openai: { kind: "openai_responses", base_url: null, api_key_configured: true },
    local: { kind: "openai_compat", base_url: "http://127.0.0.1:11434/v1", api_key_configured: false },
  },
  models: {
    "openai/codex": { provider_profile_id: "openai", remote_id: "gpt-5.6-codex", display_name: "Codex", context_window: 128000, max_output_tokens: 8192, reasoning_effort: "low" },
    "local/qwen": { provider_profile_id: "local", remote_id: "qwen3-coder", display_name: "Local Qwen", context_window: 32768, max_output_tokens: 4096, reasoning_effort: "none" },
  },
};

const interactions = [
  {
    kind: "user_input_required", pauseId: "visual-question", runId: "visual-run", turnId: "visual-turn", toolCallId: "ask-1",
    request: { questions: [
      { question_id: "scope", header: "Scope", question: "Which surface should be updated first?", kind: "single_select", options: [{ label: "Settings", description: "Configuration and appearance" }, { label: "Interaction", description: "Typed approvals and questions" }], allow_other: true },
      { question_id: "details", header: "Details", question: "Add any constraints.", kind: "text" },
    ] },
  },
  { kind: "permission_required", pauseId: "visual-permission", runId: "visual-run", turnId: "visual-turn", request: { permission_id: "perm-1", tool: "Bash", action: "execute npm test", reason: "The command reads the workspace and runs the existing test suite.", choices: ["once", "session", "reject"] } },
  { kind: "plan_review_required", pauseId: "visual-plan", runId: "visual-run", turnId: "visual-turn", request: { revision: 3, plan_text: "1. Preserve typed response authority\n2. Rebuild continuous settings layout\n3. Verify dark, light, and narrow states" } },
  { kind: "provider_unavailable", pauseId: "visual-retry", runId: "visual-run", turnId: "visual-turn", reason: "rate_limited" },
  { kind: "user_requested", pauseId: "visual-pause", runId: "visual-run", turnId: "visual-turn", reason: "user_requested" },
] satisfies PendingInteraction[];

function documentFor(body: React.ReactNode, css: string, theme: "dark" | "light", fixtureCss = "") {
  return `<!doctype html>\n<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"><style>${css}\n${fixtureCss}</style></head><body><div class="theme-${theme}" id="root">${renderToStaticMarkup(body)}</div></body></html>`;
}

async function main() {
  const outputDirectory = process.argv[2];
  if (!outputDirectory) throw new Error("output directory is required");
  await mkdir(outputDirectory, { recursive: true });
  const css = await readFile(new URL("../src/renderer/app.css", import.meta.url), "utf8");
  for (const theme of ["dark", "light"] as const) {
    const state = createInitialState({ runtimeState: "ready", theme, configuration, settingsLoaded: true });
    const view = <SettingsView state={state} api={undefined} onBack={() => undefined} onSave={() => undefined} onThemeChange={() => undefined} />;
    await writeFile(join(outputDirectory, `settings-${theme}.html`), documentFor(view, css, theme), "utf8");
  }
  const interactionMarkup = <main className="interaction-fixture" aria-label="Typed interaction visual fixture"><header><p className="eyebrow">Test-only visual fixture</p><h1>Typed interaction states</h1></header>{interactions.map((interaction) => <InteractionSurface key={interaction.pauseId} interaction={interaction} onSubmit={() => undefined} onCancel={() => undefined} />)}</main>;
  const fixtureCss = ".interaction-fixture{min-height:100vh;padding:32px;background:var(--bg)}.interaction-fixture>header,.interaction-fixture>.interaction-surface{width:min(820px,100%);margin:0 auto 22px}.interaction-fixture>header h1{margin:6px 0 24px}.interaction-fixture>.interaction-surface{position:relative;inset:auto;max-height:none}";
  await writeFile(join(outputDirectory, "interactions-dark.html"), documentFor(interactionMarkup, css, "dark", fixtureCss), "utf8");
}

void main();
