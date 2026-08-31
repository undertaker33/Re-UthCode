#!/usr/bin/env node

/**
 * Reproducible CDP driver for a real UthCode Electron Renderer.
 *
 * The Electron process is intentionally launched by the caller so the exact
 * dev or packaged command, environment, port, stdout, and exit code remain
 * visible in the delivery log.  This driver only connects to the page target
 * exposed by --remote-debugging-port and uses DOM/keyboard events through CDP.
 *
 * The Electron/fixture process must be started through cdp-launcher.mjs so
 * its user-state environment and output paths are isolated before spawn.
 *
 * Example:
 *   node scripts/cdp-launcher.mjs -- node scripts/cdp-driver.mjs --port 9229 --expect-text "fixture response"
 */

import { appendFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { dirname, resolve } from "node:path";
import { assertCdpEnvironmentIsolated } from "./cdp-test-guard.mjs";

function option(name, fallback = undefined) {
  const index = process.argv.indexOf(`--${name}`);
  return index >= 0 ? process.argv[index + 1] ?? fallback : fallback;
}

const cdpPort = Number(option("port", "9229"));
const expectedText = option("expect-text", "fixture response");
const logPath = option("log");
const targetContains = option("target-contains", "main_window");
const timeoutMs = Number(option("timeout-ms", "30000"));
const requestTimeoutMs = Number(option("request-timeout-ms", "5000"));
const flow = option("flow", "basic");
const planChoice = option("plan-choice", "approve");
const delayAction = option("delay-action", "pause");
const skipQuit = process.argv.includes("--no-quit");
const screenshotDir = option("screenshot-dir");
const fixtureHtml = option("fixture-html");
const reportPath = option("report");
const packagedExe = option("packaged-exe");
const requestedLanguage = option("language");
let flowDeadline = 0;
let isolationError;
const startedAt = new Date().toISOString();
const consoleErrors = [];
const consoleDiagnostics = [];
const rendererExceptions = [];
const screenshots = [];
let targetEvidence;
let observedLanguage;
try {
  assertCdpEnvironmentIsolated({ label: "cdp-driver", outputPaths: [logPath, screenshotDir, reportPath].filter(Boolean) });
} catch (error) {
  isolationError = error instanceof Error ? error : new Error(String(error));
}

function writeLog(event, details = {}) {
  const line = JSON.stringify({ at: new Date().toISOString(), event, ...details });
  process.stdout.write(`${line}\n`);
  if (logPath) void appendFile(logPath, `${line}\n`, "utf8");
}

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function writeAcceptanceReport(status, error) {
  if (!reportPath) return;
  const report = {
    schemaVersion: 1,
    kind: "uthcode.cdp.acceptance",
    flow,
    status,
    exitCode: status === "passed" ? 0 : 1,
    startedAt,
    finishedAt: new Date().toISOString(),
    requestedLanguage: requestedLanguage ?? null,
    packagedExe: packagedExe ? resolve(packagedExe) : null,
    target: targetEvidence ?? null,
    consoleErrors,
    consoleDiagnostics,
    rendererExceptions,
    screenshots,
    observed: {
      languages: [...new Set(screenshots.map((item) => item.language).filter(Boolean))],
      themes: [...new Set(screenshots.map((item) => item.theme).filter(Boolean))],
      viewports: [...new Map(screenshots.map((item) => [JSON.stringify(item.viewport), item.viewport])).values()],
      runtimePanelLayouts: [...new Set(screenshots.map((item) => item.runtimePanelLayout).filter(Boolean))],
    },
    failure: error ? { message: error instanceof Error ? error.message : String(error), stack: error instanceof Error ? error.stack ?? null : null } : null,
  };
  await mkdir(dirname(resolve(reportPath)), { recursive: true });
  await writeFile(resolve(reportPath), JSON.stringify(report, null, 2), "utf8");
}

async function capture(session, name) {
  if (!screenshotDir) return;
  await mkdir(screenshotDir, { recursive: true });
  const result = await session.send("Page.captureScreenshot", { format: "png", fromSurface: true });
  const screenshot = Buffer.from(result.data, "base64");
  const path = resolve(screenshotDir, `${name}.png`);
  await writeFile(path, screenshot);
  const state = await session.evaluate(`(() => {
    const shell = document.querySelector('.app-shell');
    const classes = shell ? [...shell.classList] : [];
    const layout = classes.includes('panel-floating') ? 'floating' : classes.includes('panel-hidden') ? 'hidden' : classes.includes('panel-docked') ? 'docked' : null;
    const theme = classes.includes('theme-dark') ? 'dark' : classes.includes('theme-light') ? 'light' : null;
    return { language: document.documentElement?.getAttribute('lang') || document.body?.dataset?.language || null, theme, runtimePanelLayout: layout, viewport: { width: window.innerWidth, height: window.innerHeight, deviceScaleFactor: window.devicePixelRatio } };
  })()`);
  const evidence = { name, path, bytes: screenshot.byteLength, sha256: createHash("sha256").update(screenshot).digest("hex"), ...state, language: observedLanguage ?? state.language };
  screenshots.push(evidence);
  writeLog("screenshot_saved", { ...evidence, screenshotDir });
}

function remainingBudget(label) {
  const remaining = flowDeadline - Date.now();
  if (remaining <= 0) throw new Error(`Global CDP flow deadline exceeded at ${label}`);
  return remaining;
}

async function listTargets(timeoutLimitMs) {
  const requestTimeout = Math.min(requestTimeoutMs, timeoutLimitMs ?? remainingBudget("CDP target list"));
  const response = await fetch(`http://127.0.0.1:${cdpPort}/json/list`, { signal: AbortSignal.timeout(Math.max(1, requestTimeout)) });
  if (!response.ok) throw new Error(`CDP target list returned HTTP ${response.status}`);
  return response.json();
}

async function waitForTarget() {
  let lastError = "not queried";
  while (Date.now() < flowDeadline) {
    try {
      const targets = await listTargets(Math.min(requestTimeoutMs, remainingBudget("CDP target discovery")));
      const target = targets.find((item) => item.type === "page" && item.webSocketDebuggerUrl && (!targetContains || item.url.includes(targetContains)));
      if (target) {
        writeLog("target_ready", { port: cdpPort, targetId: target.id, url: target.url, websocket: target.webSocketDebuggerUrl });
        return target;
      }
      lastError = `targets=${targets.length}`;
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await sleep(Math.min(100, remainingBudget("CDP target retry")));
  }
  throw new Error(`CDP target did not appear on fixed port ${cdpPort}: ${lastError}`);
}

class CdpSession {
  constructor(webSocketUrl) {
    if (typeof globalThis.WebSocket !== "function") throw new Error("Node WebSocket is unavailable; use Node 20+");
    this.socket = new globalThis.WebSocket(webSocketUrl);
    this.nextId = 1;
    this.pending = new Map();
    const openTimeoutMs = Math.min(requestTimeoutMs, remainingBudget("CDP WebSocket open"));
    this.open = new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error(`CDP WebSocket open timed out after ${openTimeoutMs}ms`)), openTimeoutMs);
      this.socket.addEventListener("open", () => {
        clearTimeout(timer);
        resolve();
      }, { once: true });
      this.socket.addEventListener("error", () => {
        clearTimeout(timer);
        reject(new Error("CDP WebSocket failed to open"));
      }, { once: true });
      this.socket.addEventListener("close", () => {
        clearTimeout(timer);
        reject(new Error("CDP WebSocket closed before opening"));
      }, { once: true });
    });
    this.socket.addEventListener("message", (event) => {
      let message;
      try {
        message = JSON.parse(String(event.data));
      } catch {
        return;
      }
      if (message.method) {
        if (message.method === "Runtime.consoleAPICalled") {
          const source = message.params?.stackTrace?.callFrames?.[0]?.url ?? null;
          const eventEvidence = {
            type: message.params?.type ?? "unknown",
            argCount: Array.isArray(message.params?.args) ? message.params.args.length : 0,
            source,
          };
          if (["error", "assert"].includes(eventEvidence.type)) {
            const diagnosticText = Array.isArray(message.params?.args)
              ? message.params.args.map((argument) => String(argument?.value ?? argument?.description ?? "")).join(" ")
              : "";
            const electronDiagnostic = source?.startsWith("node:electron/js2c/sandbox_bundle")
              || /sandboxed_renderer\.bundle\.js script failed to run|startupData.*null/iu.test(diagnosticText);
            (electronDiagnostic ? consoleDiagnostics : consoleErrors).push(eventEvidence);
          }
          writeLog("console_event", eventEvidence);
        } else if (message.method === "Runtime.exceptionThrown") {
          const exceptionEvidence = {
            text: message.params?.exceptionDetails?.text ?? "exception",
            description: message.params?.exceptionDetails?.exception?.description ?? "",
          };
          rendererExceptions.push(exceptionEvidence);
          writeLog("renderer_exception", exceptionEvidence);
        }
        return;
      }
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      if (message.error) pending.reject(new Error(`CDP ${message.error.message ?? "request failed"}`));
      else pending.resolve(message.result ?? {});
    });
    this.socket.addEventListener("close", () => {
      for (const pending of this.pending.values()) pending.reject(new Error("CDP WebSocket closed"));
      this.pending.clear();
    });
  }

  async send(method, params = {}) {
    await this.open;
    const requestTimeout = Math.min(requestTimeoutMs, remainingBudget(`CDP ${method}`));
    const id = this.nextId++;
    const request = { id, method, params };
    writeLog("cdp_request", { id, method, params });
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`CDP ${method} timed out after ${requestTimeout}ms`));
      }, requestTimeout);
      this.pending.set(id, {
        resolve: (value) => {
          clearTimeout(timer);
          resolve(value);
        },
        reject: (error) => {
          clearTimeout(timer);
          reject(error);
        },
      });
      this.socket.send(JSON.stringify(request));
    });
  }

  async evaluate(expression) {
    const result = await this.send("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
      userGesture: true,
    });
    if (result.exceptionDetails) throw new Error(`Renderer evaluation failed: ${result.exceptionDetails.text ?? "exception"}`);
    return result.result?.value;
  }

  close() {
    this.socket.close();
  }
}

async function waitFor(session, description, predicate) {
  let lastValue;
  while (true) {
    const remaining = remainingBudget(description);
    lastValue = await session.evaluate(predicate);
    if (lastValue) {
      writeLog("assertion_pass", { description, value: lastValue });
      return lastValue;
    }
    await sleep(Math.min(100, remaining));
  }
}

async function evaluateAction(session, label, expression) {
  remainingBudget(label);
  return session.evaluate(expression);
}

async function clickText(session, text) {
  remainingBudget(`click text ${text}`);
  writeLog("action", { action: "click_text", text });
  const clicked = await evaluateAction(session, `click text ${text}`, `(() => {
    const aliases = {
      "Settings": ["Settings", "设置"],
      "Back to chat": ["Back to chat", "返回聊天"],
      "New chat": ["New chat", "新聊天"],
      "Send": ["Send", "发送"],
      "Status": ["Status", "状态"],
    };
    const wanted = aliases[${JSON.stringify(text)}] ?? [${JSON.stringify(text)}];
    const button = [...document.querySelectorAll("button")].find((item) => wanted.some((candidate) => (item.textContent || "").includes(candidate)));
    if (!button) return false;
    button.click();
    return true;
  })()`);
  if (!clicked) throw new Error(`button text not found: ${text}`);
}

async function clickSelector(session, selector) {
  remainingBudget(`click selector ${selector}`);
  writeLog("action", { action: "click_selector", selector });
  const clicked = await evaluateAction(session, `click selector ${selector}`, `(() => {
    const element = document.querySelector(${JSON.stringify(selector)});
    if (!element) return false;
    element.click();
    return true;
  })()`);
  if (!clicked) throw new Error(`selector not found: ${selector}`);
}

async function clickLabelText(session, text) {
  remainingBudget(`click label ${text}`);
  writeLog("action", { action: "click_label_text", text });
  const clicked = await evaluateAction(session, `click label ${text}`, `(() => {
    const wanted = ${JSON.stringify(text)};
    const label = [...document.querySelectorAll("label")].find((item) => (item.textContent || "").includes(wanted));
    if (!label) return false;
    label.click();
    return true;
  })()`);
  if (!clicked) throw new Error(`label text not found: ${text}`);
}

async function waitForInteraction(session, label, selector) {
  return waitFor(session, label, `Boolean(document.querySelector(${JSON.stringify(selector)}))`);
}

async function submitAskUserFlow(session) {
  await waitForInteraction(session, "AskUser questions", '[aria-label="Questions"]');
  await waitFor(session, "AskUser first question", "document.querySelector('[aria-label=\"Questions\"] h2')?.textContent?.includes('Fixture choice')");
  await setInput(session, "Fixture choice other", "custom fixture path");
  await clickLabelText(session, "Other");
  await waitFor(session, "AskUser choice complete", "Boolean([...document.querySelectorAll('button')].find((item) => item.textContent?.includes('Next') && !item.disabled))");
  await clickText(session, "Next");

  await waitFor(session, "AskUser text question", "Boolean(document.querySelector('input[aria-label=\"Fixture note\"]'))");
  await setInput(session, "Fixture note", "CDP note");
  await waitFor(session, "AskUser text complete", "Boolean([...document.querySelectorAll('button')].find((item) => item.textContent?.includes('Next') && !item.disabled))");
  await clickText(session, "Next");

  await waitFor(session, "AskUser multi-select question", "Boolean(document.querySelector('input[aria-label=\"Fixture tags other\"]'))");
  await clickLabelText(session, "README");
  await clickLabelText(session, "tests");
  await setInput(session, "Fixture tags other", "docs");
  await clickLabelText(session, "Other");
  await waitFor(session, "AskUser review enabled", "Boolean([...document.querySelectorAll('button')].find((item) => item.textContent?.includes('Review') && !item.disabled))");
  await clickText(session, "Review");
  await waitFor(session, "AskUser answer review", "document.querySelector('[aria-label=\"Questions\"] h2')?.textContent?.includes('Review answers')");
  await clickText(session, "Submit answers");
  await waitFor(session, `AskUser same-turn continuation ${expectedText}`, `document.body?.innerText?.includes(${JSON.stringify(expectedText)})`);
}

async function submitToolFlow(session, expectedToolText) {
  await waitFor(session, "Tool completion or permission", `document.body?.innerText?.includes(${JSON.stringify(expectedToolText)}) || Boolean(document.querySelector('[aria-label=\"Permission approval\"]'))`);
  const permissionShown = await evaluateAction(session, "inspect Permission surface", "Boolean(document.querySelector('[aria-label=\"Permission approval\"]'))");
  if (permissionShown) {
    writeLog("assertion_pass", { description: "dynamic Permission surface" });
    await clickText(session, "Allow once");
  }
  await waitFor(session, `Tool result ${expectedToolText}`, `document.body?.innerText?.includes(${JSON.stringify(expectedToolText)})`);
}

async function submitPlanFlow(session, expectedToolText) {
  await waitForInteraction(session, "Plan review", '[aria-label="Plan review"]');
  if (planChoice === "revise") {
    await setInput(session, "Revision feedback", "Use the fixture README only");
    await clickText(session, "Revise plan");
    await waitFor(session, "revised plan review", "Boolean(document.querySelector('[aria-label=\"Plan review\"]'))");
    await clickText(session, "Approve and execute");
  } else if (planChoice === "cancel") {
    await clickText(session, "Cancel turn");
    await waitFor(session, "plan cancellation", "!document.querySelector('[aria-label=\"Plan review\"]') && !document.querySelector('button.cancel-button')");
    return;
  } else {
    await clickText(session, "Approve and execute");
  }
  await submitToolFlow(session, expectedToolText);
}

async function submitFailureFlow(session) {
  await waitFor(session, "Provider retry surface or output", `Boolean(document.querySelector('[aria-label=\"Provider retry\"]')) || document.body?.innerText?.includes(${JSON.stringify(expectedText)})`);
  const retryShown = await evaluateAction(session, "inspect Provider retry surface", "Boolean(document.querySelector('[aria-label=\"Provider retry\"]'))");
  if (retryShown) {
    writeLog("assertion_pass", { description: "Provider retry surface" });
    await clickText(session, "Retry");
  }
  await waitFor(session, `Retry output ${expectedText}`, `document.body?.innerText?.includes(${JSON.stringify(expectedText)})`);
}

async function submitDelayedFlow(session) {
  await waitFor(session, "delayed turn controls", "Boolean(document.querySelector('button.pause-button')) && Boolean(document.querySelector('button.cancel-button'))");
  if (delayAction === "cancel") {
    writeLog("action", { action: "click_text", text: "Cancel" });
    await clickText(session, "Cancel");
    await waitFor(session, "delayed turn cancellation", "!document.querySelector('button.cancel-button') && document.body?.innerText?.includes('cancelled')");
    return;
  }
  await clickText(session, "Pause");
  await waitForInteraction(session, "turn pause surface", '[aria-label="Turn paused"]');
  await clickText(session, "Continue");
  await waitFor(session, `continued output ${expectedText}`, `document.body?.innerText?.includes(${JSON.stringify(expectedText)})`);
}

async function submitSessionsFlow(session) {
  await waitFor(session, `first session output ${expectedText}`, `(() => { const text = document.querySelector('[aria-label=\"Chat timeline\"]')?.innerText || ''; return text.includes('cdp fixture request') && text.includes(${JSON.stringify(expectedText)}); })()`);

  await clickText(session, "New chat");
  await waitFor(session, "second conversation header", "document.querySelector('h1')?.textContent?.includes('Session') || document.querySelector('h1')?.textContent?.includes('New conversation')");
  await waitFor(session, "second composer ready", "Boolean(document.querySelector('textarea[aria-label=\"Message UthCode\"]'))");
  await setInput(session, "Message UthCode", "cdp fixture session two");
  await waitFor(session, "second message ready", "!document.querySelector('button.send-button')?.disabled");
  await clickText(session, "Send");
  await waitFor(session, `second session output ${expectedText}`, `(() => { const text = document.querySelector('[aria-label=\"Chat timeline\"]')?.innerText || ''; return text.includes('cdp fixture session two') && text.includes(${JSON.stringify(expectedText)}); })()`);

  await clickText(session, "New chat");
  await waitFor(session, "third conversation header", "document.querySelector('h1')?.textContent?.includes('Session') || document.querySelector('h1')?.textContent?.includes('New conversation')");
  await waitFor(session, "third composer ready", "Boolean(document.querySelector('textarea[aria-label=\"Message UthCode\"]'))");
  await setInput(session, "Message UthCode", "cdp fixture session three");
  await waitFor(session, "third message ready", "!document.querySelector('button.send-button')?.disabled");
  await clickText(session, "Send");
  await waitFor(session, `third session output ${expectedText}`, `(() => { const text = document.querySelector('[aria-label=\"Chat timeline\"]')?.innerText || ''; return text.includes('cdp fixture session three') && text.includes(${JSON.stringify(expectedText)}); })()`);
  await waitFor(session, "three session rows", "document.querySelectorAll('button.session-row:not(.session-row--new)').length >= 3 && [...document.querySelectorAll('button.session-row:not(.session-row--new)')].some((item) => (item.textContent || '').includes('cdp fixture session two')) && [...document.querySelectorAll('button.session-row:not(.session-row--new)')].some((item) => (item.textContent || '').includes('cdp fixture request'))");

  writeLog("action", { action: "select_session", label: "cdp fixture session two" });
  const switched = await evaluateAction(session, "select second session", `(() => {
    const rows = [...document.querySelectorAll('button.session-row:not(.session-row--new)')];
    const row = rows.find((item) => (item.textContent || '').includes('cdp fixture session two'));
    if (!row) return false;
    row.click();
    return true;
  })()`);
  if (!switched) throw new Error("second session row not found");
  await waitFor(session, "second session replay", "document.querySelector('[aria-label=\"Chat timeline\"]')?.innerText?.includes('cdp fixture session two')");

  writeLog("action", { action: "select_session", label: "cdp fixture request" });
  const replayed = await evaluateAction(session, "select first session for replay", `(() => {
    const rows = [...document.querySelectorAll('button.session-row:not(.session-row--new)')];
    const row = rows.find((item) => (item.textContent || '').includes('cdp fixture request'));
    if (!row) return false;
    row.click();
    return true;
  })()`);
  if (!replayed) throw new Error("first session row not found");
  await waitFor(session, "first session replay", "document.querySelector('[aria-label=\"Chat timeline\"]')?.innerText?.includes('cdp fixture request')");

  await setInput(session, "Message UthCode", "cdp fixture replay continuation");
  await waitFor(session, "replayed message ready", "!document.querySelector('button.send-button')?.disabled");
  await clickText(session, "Send");
  await waitFor(session, `replayed session continuation ${expectedText}`, `(() => { const text = document.querySelector('[aria-label=\"Chat timeline\"]')?.innerText || ''; return text.includes('cdp fixture replay continuation') && text.includes(${JSON.stringify(expectedText)}); })()`);
}

async function setInput(session, label, value) {
  remainingBudget(`set input ${label}`);
  writeLog("action", { action: "set_input", label, valueLength: value.length });
  const changed = await evaluateAction(session, `set input ${label}`, `(() => {
    const wanted = ${JSON.stringify(label)};
    const element = [...document.querySelectorAll("input,textarea")].find((item) => item.getAttribute("aria-label") === wanted);
    if (!element) return false;
    element.focus();
    const prototype = Object.getPrototypeOf(element);
    const descriptor = Object.getOwnPropertyDescriptor(prototype, "value");
    if (descriptor?.set) descriptor.set.call(element, ${JSON.stringify(value)});
    else element.value = ${JSON.stringify(value)};
    element.dispatchEvent(new Event("input", { bubbles: true }));
    element.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  })()`);
  if (!changed) throw new Error(`input aria-label not found: ${label}`);
}

async function setSelect(session, label, value) {
  remainingBudget(`set select ${label}`);
  writeLog("action", { action: "set_select", label, value });
  const changed = await evaluateAction(session, `set select ${label}`, `(() => {
    const wantedLabel = ${JSON.stringify(label)};
    const labelAliases = {
      theme: ["theme", "主题"],
      "runtime panel layout": ["runtime panel layout", "runtime 面板布局"],
    };
    const normalizedLabelKey = wantedLabel.trim().toLowerCase();
    const normalizedLabels = new Set((labelAliases[normalizedLabelKey] ?? [wantedLabel]).map((item) => item.trim().toLowerCase()));
    const wantedValue = ${JSON.stringify(value)};
    const native = [...document.querySelectorAll("select")].find((item) => normalizedLabels.has((item.getAttribute("aria-label") || "").trim().toLowerCase()) || item.id === wantedLabel);
    if (native) {
      native.value = wantedValue;
      native.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    }
    const aliases = {
      dark: ["dark", "深色"],
      light: ["light", "浅色"],
      system: ["system", "跟随系统", "系统"],
      docked: ["docked", "停靠"],
      floating: ["floating", "浮动"],
      hidden: ["hidden", "隐藏"],
    };
    const labels = new Set([wantedValue.toLowerCase(), ...(aliases[wantedValue] ?? [])].map((item) => item.toLowerCase()));
    const trigger = [...document.querySelectorAll(".custom-select__trigger")].find((item) => normalizedLabels.has((item.getAttribute("aria-label") || "").trim().toLowerCase()) || normalizedLabels.has((item.title || "").trim().toLowerCase()) || item.id === wantedLabel);
    if (!trigger) return false;
    trigger.click();
    return new Promise((resolve) => setTimeout(() => {
      const option = [...document.querySelectorAll('[role="option"]')].find((item) => labels.has((item.textContent || "").trim().toLowerCase()) || labels.has((item.getAttribute("title") || "").trim().toLowerCase()));
      if (!option) { resolve(false); return; }
      option.click();
      resolve(true);
    }, 0));
  })()`);
  if (!changed) throw new Error(`select not found: ${label}`);
}

async function bodyText(session) {
  return evaluateAction(session, "read Renderer body", "document.body?.innerText || \"\"");
}

async function run() {
  flowDeadline = Date.now() + timeoutMs;
  writeLog("driver_start", { argv: process.argv.slice(2), cdpPort, timeoutMs, requestTimeoutMs, flow, planChoice, delayAction });
  const target = await waitForTarget();
  targetEvidence = { id: target.id, url: target.url, type: target.type };
  const session = new CdpSession(target.webSocketDebuggerUrl);
  try {
    await session.send("Runtime.enable");
    await session.send("Page.enable");
    // The sidebar label is localized (and the renderer contract deliberately
    // does not expose the retired "Project navigation" label).  Use the
    // stable structural landmark so CDP acceptance works in both zh-CN/en.
    await waitFor(session, "UthCode shell", "Boolean(document.querySelector('.sidebar'))");
    await waitFor(session, "Composer", "Boolean(document.querySelector('.composer textarea'))");

    if (requestedLanguage) {
      const languageSet = await evaluateAction(session, "set requested language", `(async()=>{if(typeof window.uthcode?.writePreference !== "function") return false; await window.uthcode.writePreference("language", ${JSON.stringify(requestedLanguage)}); return true})()`);
      if (!languageSet) throw new Error("language preference API is unavailable in the packaged Renderer");
      await session.send("Page.reload", { ignoreCache: true });
      await waitFor(session, "UthCode shell after language reload", "Boolean(document.querySelector('.sidebar'))");
      await waitFor(session, "Composer after language reload", "Boolean(document.querySelector('.composer textarea'))");
      observedLanguage = await evaluateAction(session, "read requested language", "typeof window.uthcode?.readPreference === \"function\" ? window.uthcode.readPreference(\"language\") : null");
      if (!observedLanguage) throw new Error("language preference read API is unavailable in the packaged Renderer");
    }

    if (flow === "visual-fixture") {
      if (!fixtureHtml) throw new Error("visual-fixture requires --fixture-html");
      const html = await readFile(fixtureHtml, "utf8");
      await evaluateAction(session, "install test-only populated markup", `document.open(); document.write(${JSON.stringify(html)}); document.close(); true`);
      await waitFor(session, "populated fixture", "document.body?.innerText?.includes('Acceptance project') && document.body?.innerText?.includes('Inspecting the authoritative') && document.body?.innerText?.includes('Tasks')");
      await session.send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 1000, deviceScaleFactor: 1, mobile: false });
      await capture(session, "main-populated-fixture");
      if (skipQuit) {
        await session.send("Emulation.clearDeviceMetricsOverride");
        await session.send("Page.reload", { ignoreCache: true });
        await waitFor(session, "production shell restored", "Boolean(document.querySelector('.sidebar'))");
      } else await evaluateAction(session, "close UthCode shell", "window.uthcode.closeShell()");
      writeLog("driver_complete", { exitCode: 0, evidence: "test-only visual fixture; not runtime E2E" });
      return;
    }

    if (flow === "visual") {
      await clickText(session, "Settings");
      await waitFor(session, "Settings view", "Boolean(document.querySelector('.settings-view'))");
      await setSelect(session, "theme", "dark");
      await clickText(session, "Back to chat");
      await capture(session, "main-dark-docked");
      await setSelect(session, "Runtime panel layout", "floating");
      await capture(session, "main-dark-floating");
      await setSelect(session, "Runtime panel layout", "hidden");
      await capture(session, "main-dark-hidden");
      await clickText(session, "Settings");
      await setSelect(session, "theme", "light");
      await clickText(session, "Back to chat");
      await capture(session, "main-light");
      await session.send("Emulation.setDeviceMetricsOverride", { width: 760, height: 640, deviceScaleFactor: 1, mobile: false });
      await capture(session, "main-narrow");
      await session.send("Emulation.clearDeviceMetricsOverride");
      if (!skipQuit) await evaluateAction(session, "close UthCode shell", "window.uthcode.closeShell()");
      writeLog("driver_complete", { exitCode: 0 });
      return;
    }

    if (flow === "shell") {
      const rendererReady = await evaluateAction(session, "Renderer ready", "JSON.stringify({ readyState: document.readyState, title: document.title, bodyReady: Boolean(document.body) })");
      writeLog("assertion_pass", { description: "Renderer ready", value: rendererReady });
      writeLog("action", { action: "close_shell" });
      await evaluateAction(session, "close UthCode shell", "window.uthcode.closeShell()");
      writeLog("quit_requested", { port: cdpPort });
      writeLog("driver_complete", { exitCode: 0 });
      return;
    }

    // New Session -> real Provider request -> streamed AgentEvent projection.
    await clickText(session, "New chat");
    await waitFor(session, "new conversation header", "document.querySelector('h1')?.textContent?.includes('Session') || document.querySelector('h1')?.textContent?.includes('New conversation')");
    if (flow === "plan") {
      await clickText(session, "DEFAULT");
      await waitFor(session, "plan mode selected", "document.querySelector('button.mode-button')?.textContent?.includes('PLAN')");
    }
    await setInput(session, "Message UthCode", "cdp fixture request");
    await clickText(session, "Send");
    if (flow === "ask") {
      await submitAskUserFlow(session);
    } else if (flow === "tool") {
      await submitToolFlow(session, expectedText);
    } else if (flow === "permission") {
      await waitForInteraction(session, "dynamic Permission surface", '[aria-label="Permission approval"]');
      await clickText(session, "Allow once");
      await waitFor(session, `Permission continuation ${expectedText}`, `document.body?.innerText?.includes(${JSON.stringify(expectedText)})`);
    } else if (flow === "plan") {
      await submitPlanFlow(session, expectedText);
    } else if (flow === "failure") {
      await submitFailureFlow(session);
    } else if (flow === "delay") {
      await submitDelayedFlow(session);
    } else if (flow === "sessions") {
      await submitSessionsFlow(session);
    } else {
      await waitFor(session, `Provider output ${expectedText}`, `document.body?.innerText?.includes(${JSON.stringify(expectedText)})`);
    }

    // Settings, theme, and runtime panel are exercised through actual DOM
    // controls; no renderer state or IPC protocol is injected by the driver.
    await clickText(session, "Settings");
    await waitFor(session, "Settings view", "Boolean(document.querySelector('.settings-view'))");
    await setSelect(session, "theme", "dark");
    await waitFor(session, "dark theme", "document.querySelector('.app-shell')?.classList.contains('theme-dark')");
    await clickSelector(session, '[aria-label="Toggle Runtime panel"]');
    await waitFor(session, "floating runtime panel", "document.querySelector('.app-shell')?.classList.contains('panel-floating')");
    await clickSelector(session, '[aria-label="Toggle Runtime panel"]');
    await waitFor(session, "hidden runtime panel", "document.querySelector('.app-shell')?.classList.contains('panel-hidden')");
    await clickText(session, "Back to chat");
    await waitFor(session, "chat after settings", "Boolean(document.querySelector('.composer textarea'))");
    await clickText(session, "Status");
    await waitFor(session, "status output", "document.body?.innerText?.includes('Runtime') || document.body?.innerText?.includes('status')");
    const visibleText = await bodyText(session);
    if (/fixture-secret|raw-native-secret|api[_ -]?key\s*[:=]\s*fixture/i.test(visibleText)) throw new Error("secret-like fixture value appeared in Renderer text");
    writeLog("assertion_pass", { description: "Renderer contains no fixture secret" });
    if (!skipQuit) {
      writeLog("action", { action: "close_shell" });
      await evaluateAction(session, "close UthCode shell", "window.uthcode.closeShell()");
      writeLog("quit_requested", { port: cdpPort });
    }
  } finally {
    session.close();
  }
  writeLog("driver_complete", { exitCode: 0 });
}

if (isolationError) {
  process.stderr.write(`cdp-driver isolation_failure: ${isolationError.message}\n`);
  process.exitCode = 1;
} else {
  run()
    .then(async () => {
      await writeAcceptanceReport("passed");
    })
    .catch(async (error) => {
      writeLog("driver_failure", { message: error instanceof Error ? error.stack ?? error.message : String(error) });
      await writeAcceptanceReport("failed", error);
      process.exitCode = 1;
    });
}
