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
const lifecycleStage = option("stage");
const generalFlows = new Set(["general-real", "general-cancel", "general-invalid-config"]);
const projectOne = option("project-one");
const projectTwo = option("project-two");
const diffProject = option("diff-project");
const diffUnbornProject = option("diff-unborn-project");
const artifactPath = option("artifact-path");
const reviewMarkdownPath = option("review-markdown-path");
const reviewTextPath = option("review-text-path");
const reviewCodePath = option("review-code-path");
const reviewImagePath = option("review-image-path");
const expectedSessions = option("expected-sessions");
const generalApiPrompt = "Reply with only this exact token: T12_GENERAL_API_ACCEPTED";
const generalApiToken = "T12_GENERAL_API_ACCEPTED";
const planChoice = option("plan-choice", "approve");
const delayAction = option("delay-action", flow === "general-cancel" ? "cancel" : "pause");
const askQuestionCount = Number(option("ask-question-count", "4"));
const planChunkDelayMs = Number(option("plan-chunk-delay-ms", "250"));
const skipQuit = process.argv.includes("--no-quit");
const computerUse = process.argv.includes("--computer-use");
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
const flowEvidence = {};
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

// Keep the runner-owned real window alive for native visual inspection. The
// operator releases each checkpoint explicitly; ordinary CDP runs do not wait.
async function computerUseCheckpoint(phase) {
  if (!computerUse) return;
  if (!screenshotDir) throw new Error("computer-use requires a screenshot directory");
  const prefix = resolve(screenshotDir, `computer-use-${phase}`);
  await writeFile(`${prefix}.ready.json`, JSON.stringify({ phase, port: cdpPort, packagedExe, continuePath: `${prefix}.continue` }, null, 2), "utf8");
  writeLog("computer-use-ready", { phase, continuePath: `${prefix}.continue` });
  while (Date.now() < flowDeadline) {
    try { await readFile(`${prefix}.continue`); return; }
    catch (error) { if (error.code !== "ENOENT") throw error; }
    await sleep(250);
  }
  throw new Error(`computer-use checkpoint timed out: ${phase}`);
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
      flow: flowEvidence,
    },
    failure: error ? { message: error instanceof Error ? error.message : String(error), stack: error instanceof Error ? error.stack ?? null : null } : null,
  };
  await mkdir(dirname(resolve(reportPath)), { recursive: true });
  await writeFile(resolve(reportPath), JSON.stringify(report, null, 2), "utf8");
}

async function recordScreenshot(session, name, result) {
  if (!screenshotDir) return;
  await mkdir(screenshotDir, { recursive: true });
  const screenshot = Buffer.from(result.data, "base64");
  const path = resolve(screenshotDir, `${name}.png`);
  await writeFile(path, screenshot);
  const state = await session.evaluate(`(async () => {
    const shell = document.querySelector('.app-shell');
    const classes = shell ? [...shell.classList] : [];
    const layout = classes.includes('panel-floating') ? 'floating' : classes.includes('panel-hidden') ? 'hidden' : classes.includes('panel-docked') ? 'docked' : null;
    const theme = classes.includes('theme-dark') ? 'dark' : classes.includes('theme-light') ? 'light' : null;
    const preferenceLanguage = typeof window.uthcode?.readPreference === 'function' ? await window.uthcode.readPreference('language') : null;
    const messageLabel = document.querySelector('.composer textarea')?.getAttribute('aria-label') || null;
    const uiLanguage = messageLabel === 'Message UthCode' ? 'en' : messageLabel === '发送给 UthCode' ? 'zh-CN' : null;
    const documentLanguage = document.documentElement?.getAttribute('lang') || document.body?.dataset?.language || null;
    return { language: preferenceLanguage || uiLanguage || documentLanguage, preferenceLanguage, uiLanguage, documentLanguage, theme, runtimePanelLayout: layout, viewport: { width: window.innerWidth, height: window.innerHeight, deviceScaleFactor: window.devicePixelRatio } };
  })()`);
  if (requestedLanguage && ((state.preferenceLanguage && state.preferenceLanguage !== requestedLanguage) || (state.uiLanguage && state.uiLanguage !== requestedLanguage))) {
    throw new Error(`screenshot language does not match requested language: ${JSON.stringify({ requestedLanguage, preferenceLanguage: state.preferenceLanguage, uiLanguage: state.uiLanguage, documentLanguage: state.documentLanguage })}`);
  }
  const evidence = { name, path, bytes: screenshot.byteLength, sha256: createHash("sha256").update(screenshot).digest("hex"), ...state };
  screenshots.push(evidence);
  writeLog("screenshot_saved", { ...evidence, screenshotDir });
}

async function capture(session, name) {
  if (!screenshotDir) return;
  await session.send("Page.bringToFront");
  const result = await session.send("Page.captureScreenshot", { format: "png", fromSurface: true });
  await recordScreenshot(session, name, result);
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
    this.debuggerPauseWaiters = [];
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
        } else if (message.method === "Debugger.paused") {
          writeLog("debugger_paused", { reason: message.params?.reason ?? null });
          const waiter = this.debuggerPauseWaiters.shift();
          if (waiter) waiter.resolve(message.params ?? {});
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
      for (const waiter of this.debuggerPauseWaiters.splice(0)) waiter.reject(new Error("CDP WebSocket closed"));
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

  async waitForDebuggerPause(timeoutMs) {
    await this.open;
    return new Promise((resolve, reject) => {
      let waiter;
      const timer = setTimeout(() => {
        const index = this.debuggerPauseWaiters.indexOf(waiter);
        if (index >= 0) this.debuggerPauseWaiters.splice(index, 1);
        reject(new Error(`Debugger pause timed out after ${timeoutMs}ms`));
      }, Math.max(1, timeoutMs));
      waiter = {
        resolve: (value) => {
          clearTimeout(timer);
          resolve(value);
        },
        reject: (error) => {
          clearTimeout(timer);
          reject(error);
        },
      };
      this.debuggerPauseWaiters.push(waiter);
    });
  }

  close() {
    this.socket.close();
  }
}

async function waitFor(session, description, predicate) {
  let lastValue;
  const deadline = Math.min(flowDeadline, Date.now() + (computerUse ? 30_000 : timeoutMs));
  while (true) {
    if (Date.now() >= deadline) throw new Error(`CDP condition timed out: ${description}`);
    const remaining = remainingBudget(description);
    lastValue = await session.evaluate(predicate);
    if (lastValue) {
      writeLog("assertion_pass", { description, value: lastValue });
      return lastValue;
    }
    await sleep(Math.min(100, remaining));
  }
}

async function waitForStableObservation(session, description, expression, stableSamples = 3) {
  let previousSignature = null;
  let previousDiagnosticSignature = null;
  let stableCount = 0;
  let lastValue = null;
  const deadline = Math.min(flowDeadline, Date.now() + (computerUse ? 30_000 : timeoutMs));
  while (true) {
    if (Date.now() >= deadline) throw new Error(`CDP observation timed out: ${description}`);
    const remaining = remainingBudget(description);
    lastValue = await session.evaluate(expression);
    const diagnosticSignature = lastValue ? JSON.stringify(lastValue) : null;
    if (diagnosticSignature && diagnosticSignature !== previousDiagnosticSignature) {
      writeLog("acceptance_diagnostic", { description, observation: lastValue });
      previousDiagnosticSignature = diagnosticSignature;
    }
    const signature = lastValue && lastValue.ready !== false ? diagnosticSignature : null;
    if (signature && signature === previousSignature) stableCount += 1;
    else {
      previousSignature = signature;
      stableCount = signature ? 1 : 0;
    }
    if (stableCount >= stableSamples) {
      writeLog("assertion_pass", { description, value: lastValue, stableSamples });
      return lastValue;
    }
    await sleep(Math.min(100, remaining));
  }
}

async function waitForStableObservationWithin(session, description, expression, timeoutMs = 12_000, stableSamples = 3) {
  const deadline = Math.min(flowDeadline, Date.now() + timeoutMs);
  let previousSignature = null;
  let previousDiagnosticSignature = null;
  let stableCount = 0;
  let lastValue = null;
  while (true) {
    const remaining = deadline - Date.now();
    if (remaining <= 0) throw new Error(`${description} timed out after ${timeoutMs}ms; last observation=${JSON.stringify(lastValue)}`);
    lastValue = await session.evaluate(expression);
    const diagnosticSignature = lastValue ? JSON.stringify(lastValue) : null;
    if (diagnosticSignature && diagnosticSignature !== previousDiagnosticSignature) {
      writeLog("acceptance_diagnostic", { description, observation: lastValue });
      previousDiagnosticSignature = diagnosticSignature;
    }
    const signature = lastValue && lastValue.ready !== false ? diagnosticSignature : null;
    if (signature && signature === previousSignature) stableCount += 1;
    else {
      previousSignature = signature;
      stableCount = signature ? 1 : 0;
    }
    if (stableCount >= stableSamples) {
      writeLog("assertion_pass", { description, value: lastValue, stableSamples });
      return lastValue;
    }
    await sleep(Math.min(100, deadline - Date.now()));
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
  if (selector === ".composer-send") {
    const target = await evaluateAction(session, `inspect visible ${selector}`, `(() => {
      const elements = [...document.querySelectorAll(${JSON.stringify(selector)})];
      const describe = (element) => {
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return { disabled: element.disabled, text: (element.innerText || '').trim(), aria: element.getAttribute('aria-label'), display: style.display, visibility: style.visibility, rect: rect.toJSON() };
      };
      const element = elements.find((item) => {
        const style = getComputedStyle(item);
        const rect = item.getBoundingClientRect();
        return !item.disabled && style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
      });
      if (!element) return { elements: elements.map(describe), target: null };
      window.__t12ComposerSendProbe = { clickCount: 0 };
      element.addEventListener('click', () => { window.__t12ComposerSendProbe.clickCount += 1; }, { capture: true, once: true });
      const rect = element.getBoundingClientRect();
      return { elements: elements.map(describe), target: { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2, ...describe(element) } };
    })()`);
    if (!target?.target || !Number.isFinite(target.target.x) || !Number.isFinite(target.target.y)) {
      throw new Error(`visible enabled composer Send control not found: ${JSON.stringify(target)}`);
    }
    writeLog("acceptance_diagnostic", { description: "visible composer Send target before click", evidence: target });
    const clicked = await evaluateAction(session, `click enabled ${selector}`, `(() => {
      const element = document.querySelector(${JSON.stringify(selector)});
      if (!element || element.disabled) return false;
      element.click();
      return { clicked: true, clickCount: window.__t12ComposerSendProbe?.clickCount ?? null };
    })()`);
    if (!clicked?.clicked) throw new Error(`visible composer Send control became unavailable: ${JSON.stringify(clicked)}`);
    writeLog("acceptance_diagnostic", { description: "composer Send click event delivered", evidence: clicked });
    return;
  }
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

async function assertResponsiveLayout(session, label) {
  // Device-metric changes and CSS track clamps repaint on separate renderer
  // turns. Wait for the document geometry to settle before evaluating the
  // strict overflow assertion; a persistent overflow still exhausts the same
  // fixed flow deadline and remains a failure.
  await waitFor(session, `${label} geometry stable`, "(() => Boolean(document.querySelector('.app-shell') && document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1 && document.body.scrollWidth <= document.body.clientWidth + 1))()");
  const evidence = await evaluateAction(session, label, `(() => {
    const visible = (element) => {
      if (!element) return false;
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
    };
    const rect = (element) => element ? element.getBoundingClientRect().toJSON() : null;
    const within = (value) => Boolean(value) && value.left >= -1 && value.top >= -1 && value.right <= window.innerWidth + 1 && value.bottom <= window.innerHeight + 1;
    const overlaps = (left, right) => Boolean(left && right) && left.left < right.right && left.right > right.left && left.top < right.bottom && left.bottom > right.top;
    const composer = document.querySelector('.composer');
    // The Composer aria-label is localized; its structural landmark is part
    // of the renderer contract and remains stable across en/zh acceptance.
    const input = document.querySelector('.composer textarea');
    const send = composer?.querySelector('.composer-actions button:last-child');
    const settings = [...document.querySelectorAll('.sidebar-footer button')].find((item) => visible(item));
    const settingsView = document.querySelector('.settings-view');
    input?.focus();
    const composerRect = rect(composer);
    const inputRect = rect(input);
    const sendRect = rect(send);
    const settingsRect = rect(settings);
    const settingsViewRect = rect(settingsView);
    const overflow = document.documentElement.scrollWidth > document.documentElement.clientWidth + 1 || document.body.scrollWidth > document.body.clientWidth + 1;
    const focusOk = document.activeElement === input;
    const visibleSettingsRect = settingsViewRect ?? settingsRect;
    return { ok: Boolean(visible(composer) && visible(input) && visible(send) && within(composerRect) && within(inputRect) && within(sendRect) && (!visibleSettingsRect || within(visibleSettingsRect)) && !overlaps(sendRect, visibleSettingsRect) && !overflow && focusOk), viewport: { width: window.innerWidth, height: window.innerHeight }, overflow, focus: document.activeElement?.getAttribute('aria-label') ?? null, composer: composerRect, input: inputRect, send: sendRect, settings: visibleSettingsRect };
  })()`);
  if (!evidence?.ok) throw new Error(`${label} failed: ${JSON.stringify(evidence)}`);
  writeLog("assertion_pass", { description: label, value: evidence });
  return evidence;
}

async function assertSingleDomEntity(session, label, selector, expectedCount = 1) {
  const count = await evaluateAction(session, label, `document.querySelectorAll(${JSON.stringify(selector)}).length`);
  if (count !== expectedCount) throw new Error(`${label} expected ${expectedCount} DOM entit${expectedCount === 1 ? 'y' : 'ies'}, observed ${count}`);
  writeLog("assertion_pass", { description: label, value: { selector, count } });
}

async function assertCommandCandidate(session, inputValue, expectedPrefix = inputValue.trim()) {
  const label = expectedPrefix || inputValue.trim();
  await setInput(session, "Message UthCode", inputValue);
  await waitFor(session, `${label} completion`, `Boolean([...document.querySelectorAll('.command-menu button')].find((item) => (item.textContent || '').trim().startsWith(${JSON.stringify(expectedPrefix)})))`);
  const candidate = await evaluateAction(session, `read ${label} completion`, `(() => { const item = [...document.querySelectorAll('.command-menu button')].find((entry) => (entry.textContent || '').trim().startsWith(${JSON.stringify(expectedPrefix)})); return item ? (item.textContent || '').trim() : null; })()`);
  if (!candidate) throw new Error(`${label} completion candidate was not readable`);
  await evaluateAction(session, `keyboard navigate ${label} completion`, `(() => { const input = document.querySelector('textarea[aria-label="Message UthCode"], textarea[aria-label="发送给 UthCode"]'); if (!input) return false; input.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', code: 'ArrowDown', bubbles: true })); return true; })()`);
  await waitFor(session, `${label} keyboard completion focus`, "Boolean(document.querySelector('.command-menu button.is-active'))");
  await evaluateAction(session, `dismiss ${label} completion`, `(() => { const input = document.querySelector('textarea[aria-label="Message UthCode"], textarea[aria-label="发送给 UthCode"]'); if (!input) return false; input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', bubbles: true })); return true; })()`);
  await waitFor(session, `${label} completion dismissed`, "!document.querySelector('.command-menu')");
  await setInput(session, "Message UthCode", "");
  writeLog("assertion_pass", { description: `${label} completion candidate and keyboard path`, value: candidate });
}

function commandDescriptionExpectations() {
  return requestedLanguage === "zh-CN"
    ? { "/compact": "压缩上下文", "/status": "显示当前 Application 状态" }
    : { "/compact": "Compact context", "/status": "Show current Application status" };
}

async function assertLocalizedCommandMenu(session) {
  const expected = commandDescriptionExpectations();
  await setInput(session, "Message UthCode", "/");
  await waitFor(session, "localized slash command menu", "Boolean(document.querySelector('.command-menu'))");
  const menu = await evaluateAction(session, "read localized slash command menu", `(() => {
    const expectedValues = ${JSON.stringify(Object.keys(expected))};
    const rows = [...document.querySelectorAll('.command-menu button')].map((item) => ({
      value: item.querySelector('span')?.textContent?.trim() || '',
      description: item.querySelector('small')?.textContent?.trim() || '',
      text: (item.textContent || '').trim(),
    }));
    const selected = rows.filter((row) => expectedValues.includes(row.value));
    return { rows, selected };
  })()`);
  const counts = Object.fromEntries(Object.keys(expected).map((value) => [value, menu.selected.filter((row) => row.value === value).length]));
  const descriptions = Object.fromEntries(menu.selected.map((row) => [row.value, row.description]));
  const menuText = menu.selected.map((row) => row.text).join(" ");
  const forbiddenDescriptions = requestedLanguage === "zh-CN"
    ? ["Compact context", "Show current Application status"]
    : ["压缩上下文", "显示当前 Application 状态"];
  const duplicate = Object.entries(counts).find(([, count]) => count !== 1);
  if (duplicate) throw new Error(`slash candidate ${duplicate[0]} expected exactly one canonical row, observed ${duplicate[1]}`);
  for (const [value, description] of Object.entries(expected)) {
    if (descriptions[value] !== description) throw new Error(`slash candidate ${value} description mismatch: ${JSON.stringify(descriptions[value])}`);
  }
  if (forbiddenDescriptions.some((value) => menuText.includes(value))) throw new Error(`slash command menu mixed locales: ${menuText}`);
  await evaluateAction(session, "keyboard navigate localized slash command menu", `(() => {
    const input = document.querySelector('textarea[aria-label="Message UthCode"], textarea[aria-label="发送给 UthCode"]');
    if (!input) return false;
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', code: 'ArrowDown', bubbles: true }));
    return true;
  })()`);
  await waitFor(session, "localized slash command keyboard focus", "Boolean(document.querySelector('.command-menu button.is-active'))");
  await evaluateAction(session, "dismiss localized slash command menu", `(() => {
    const input = document.querySelector('textarea[aria-label="Message UthCode"], textarea[aria-label="发送给 UthCode"]');
    if (!input) return false;
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', bubbles: true }));
    return true;
  })()`);
  await waitFor(session, "localized slash command menu dismissed", "!document.querySelector('.command-menu')");
  await setInput(session, "Message UthCode", "");
  writeLog("assertion_pass", { description: `canonical slash candidates localized without duplicates (${requestedLanguage})`, value: { counts, descriptions } });
}

async function runResponsiveHealthFlow(session) {
  await session.send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
  for (const width of [1280, 800, 680, 520]) {
    await session.send("Emulation.setDeviceMetricsOverride", { width, height: 800, deviceScaleFactor: 1, mobile: false });
    // Chromium's CSS viewport override does not emit a Window resize event;
    // this is an explicit synthetic boundary for the responsive DOM probe,
    // not evidence of a native window resize.
    await evaluateAction(session, "dispatch synthetic resize for CSS viewport probe", "window.dispatchEvent(new Event('resize'))");
    for (const pageScaleFactor of [1, 1.25, 1.5]) {
      await session.send("Emulation.setPageScaleFactor", { pageScaleFactor });
      await assertResponsiveLayout(session, `responsive layout ${width}px @ ${pageScaleFactor}x reduced motion`);
    }
  }
  await session.send("Emulation.setPageScaleFactor", { pageScaleFactor: 1 });
  await restoreWideCssViewport(session, "responsive health CSS viewport reset");
  await session.send("Emulation.setEmulatedMedia", { features: [] });
  writeLog("assertion_pass", { description: "responsive health restored" });
}

async function restoreWideCssViewport(session, label) {
  await session.send("Emulation.clearDeviceMetricsOverride");
  // Clearing the DevTools CSS override also does not emit a Window resize
  // event.  Dispatch the same explicit synthetic boundary used for the
  // narrow probes, then wait for the live wide layout before another action
  // or screenshot can observe the Renderer.
  await evaluateAction(session, `${label}: dispatch synthetic resize`, "window.dispatchEvent(new Event('resize'))");
  const evidence = await waitFor(session, `${label}: wait wide layout`, `(() => {
    const shell = document.querySelector('.app-shell');
    const wideChat = window.innerWidth > 680 && !shell?.classList.contains('focus-mode') && !shell?.classList.contains('settings-shell');
    const docked = shell?.classList.contains('panel-docked') === true;
    const separators = [...document.querySelectorAll('[data-resize-side]')];
    const valuesReady = separators.every((element) => Number.parseInt(element.getAttribute('aria-valuenow') || '0', 10) > 0);
    const expectedSeparators = wideChat ? (docked ? 2 : 1) : 0;
    return wideChat && separators.length === expectedSeparators && valuesReady;
  })()`);
  const observed = await evaluateAction(session, `${label}: inspect restored wide layout`, `(() => {
    const shell = document.querySelector('.app-shell');
    const separators = [...document.querySelectorAll('[data-resize-side]')];
    return {
      viewportWidth: window.innerWidth,
      panelMode: shell?.className || null,
      separatorCount: separators.length,
      separatorValues: separators.map((element) => Number.parseInt(element.getAttribute('aria-valuenow') || '0', 10)),
    };
  })()`);
  writeLog("assertion_pass", { description: `${label}: wide layout restored after synthetic resize`, value: { evidence, observed } });
}

async function assertLayoutFocusAndResize(session) {
  const initial = await evaluateAction(session, "read layout preference baseline", `(async () => ({
    panelMode: window.uthcode?.readPreference ? await window.uthcode.readPreference("panelMode") : null,
    sidebarWidth: window.uthcode?.readPreference ? await window.uthcode.readPreference("sidebarWidth") : null,
    runtimePanelWidth: window.uthcode?.readPreference ? await window.uthcode.readPreference("runtimePanelWidth") : null,
  }))()`);
  if (!initial || initial.panelMode !== "docked" || !Number.isInteger(initial.sidebarWidth) || !Number.isInteger(initial.runtimePanelWidth)) {
    throw new Error(`layout preference API did not expose the docked baseline: ${JSON.stringify(initial)}`);
  }

  // Keep the real pointer path before any Emulation metrics changes.  The
  // packaged Electron renderer has one stable native input surface for this
  // assertion; responsive metric checks below are a separate presentation
  // probe and must not leave pointer capture in a different renderer state.
  const separatorEvidence = await evaluateAction(session, "inspect layout separators", `(() => {
    const separators = [...document.querySelectorAll('[data-resize-side]')];
    return separators.map((element) => ({
      side: element.getAttribute('data-resize-side'),
      role: element.getAttribute('role'),
      orientation: element.getAttribute('aria-orientation'),
      min: element.getAttribute('aria-valuemin'),
      max: element.getAttribute('aria-valuemax'),
      now: element.getAttribute('aria-valuenow'),
      label: element.getAttribute('aria-label'),
      controls: element.getAttribute('aria-controls'),
    }));
  })()`);
  const sidebarSeparator = separatorEvidence?.find((item) => item.side === "sidebar");
  const runtimeSeparator = separatorEvidence?.find((item) => item.side === "runtime");
  if (!sidebarSeparator || !runtimeSeparator || sidebarSeparator.role !== "separator" || runtimeSeparator.role !== "separator" || sidebarSeparator.orientation !== "vertical" || runtimeSeparator.orientation !== "vertical" || sidebarSeparator.controls !== "workspace-main" || runtimeSeparator.controls !== "workspace-main") {
    throw new Error(`wide separators did not expose the ARIA contract: ${JSON.stringify(separatorEvidence)}`);
  }
  writeLog("assertion_pass", { description: "wide separators expose Pointer/keyboard ARIA contract", value: separatorEvidence });

  const pointerGeometry = await evaluateAction(session, "read sidebar resize geometry", `(() => {
    const element = document.querySelector('[data-resize-side="sidebar"]');
    if (!element) return null;
    const rect = element.getBoundingClientRect();
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
  })()`);
  if (!pointerGeometry || !Number.isFinite(pointerGeometry.x) || !Number.isFinite(pointerGeometry.y)) throw new Error(`sidebar separator did not expose pointer geometry: ${JSON.stringify(pointerGeometry)}`);
  await session.send("Page.bringToFront");
  await session.send("Input.dispatchMouseEvent", { type: "mousePressed", x: pointerGeometry.x, y: pointerGeometry.y, button: "left", buttons: 1, clickCount: 1 });
  await session.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: pointerGeometry.x + 24, y: pointerGeometry.y, button: "left", buttons: 1 });
  const pointerResult = await evaluateAction(session, "read sidebar resize preview", `(() => {
    const element = document.querySelector('[data-resize-side="sidebar"]');
    if (!element) return null;
    return { value: Number.parseInt(element.getAttribute('aria-valuenow') || '0', 10), style: getComputedStyle(document.querySelector('.app-shell')).getPropertyValue('--sidebar-width').trim() };
  })()`);
  if (!pointerResult || pointerResult.value <= initial.sidebarWidth) throw new Error(`sidebar separator did not accept pointer preview: ${JSON.stringify(pointerResult)}`);
  await sleep(100);
  const duringPointer = await evaluateAction(session, "read sidebar preference during pointer preview", "window.uthcode.readPreference('sidebarWidth')");
  if (duringPointer !== initial.sidebarWidth) throw new Error(`pointer preview wrote a preference before release: ${duringPointer}`);
  const committedWidth = Math.round(Math.min(Number.parseInt(sidebarSeparator.max, 10), initial.sidebarWidth + 24));
  await session.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: pointerGeometry.x + 24, y: pointerGeometry.y, button: "left", buttons: 0, clickCount: 1 });
  await waitFor(session, "sidebar pointer preference commit", `(async () => (await window.uthcode.readPreference('sidebarWidth')) === ${committedWidth})()`);
  writeLog("assertion_pass", { description: "pointer move stays visual and release commits one sidebar width", value: { before: initial.sidebarWidth, after: committedWidth, duringPointer } });

  const pointerReloadOrigin = await evaluateAction(session, "read document origin before pointer width reload", "performance.timeOrigin");
  await session.send("Page.reload", { ignoreCache: true });
  await waitFor(session, "layout shell after pointer width reload", `performance.timeOrigin !== ${JSON.stringify(pointerReloadOrigin)} && document.readyState === 'complete' && Boolean(document.querySelector('.app-shell')) && Boolean(document.querySelector('.composer textarea'))`);
  await waitFor(session, "sidebar width rehydrated", `(async () => (await window.uthcode.readPreference('sidebarWidth')) === ${committedWidth} && document.querySelector('[data-resize-side="sidebar"]')?.getAttribute('aria-valuenow') === ${JSON.stringify(String(committedWidth))})()`);
  writeLog("assertion_pass", { description: "sidebar width survives a fresh Renderer reload", value: { sidebarWidth: committedWidth, documentReloaded: true } });

  const seededWideWidths = await evaluateAction(session, "seed wide-to-wide clamp widths", `(async () => {
    if (typeof window.uthcode?.writePreference !== "function") return false;
    await window.uthcode.writePreference("sidebarWidth", 420);
    await window.uthcode.writePreference("runtimePanelWidth", 520);
    return true;
  })()`);
  if (!seededWideWidths) throw new Error("layout preference API did not expose width writes for the wide-to-wide clamp assertion");
  await waitFor(session, "wide-to-wide seed persisted", `(async () => (await window.uthcode.readPreference("sidebarWidth")) === 420 && (await window.uthcode.readPreference("runtimePanelWidth")) === 520)()`);
  const seedDocumentOrigin = await evaluateAction(session, "read document origin before wide-to-wide reload", "performance.timeOrigin");
  await session.send("Page.reload", { ignoreCache: true });
  await waitFor(session, "wide-to-wide seed rehydrated", `performance.timeOrigin !== ${JSON.stringify(seedDocumentOrigin)} && document.readyState === 'complete' && Boolean(document.querySelector('.app-shell')) && Boolean(document.querySelector('.composer textarea'))`);
  await waitFor(session, "wide-to-wide DOM seed rehydrated", `(async () => (await window.uthcode.readPreference("sidebarWidth")) === 420 && (await window.uthcode.readPreference("runtimePanelWidth")) === 520 && document.querySelector('[data-resize-side="sidebar"]')?.getAttribute('aria-valuenow') === "420" && document.querySelector('[data-resize-side="runtime"]')?.getAttribute('aria-valuenow') === "520")()`);
  await session.send("Emulation.setDeviceMetricsOverride", { width: 800, height: 800, deviceScaleFactor: 1, mobile: false });
  await evaluateAction(session, "dispatch synthetic resize after CSS viewport override", "window.dispatchEvent(new Event('resize'))");
  await sleep(250);
  const wideToWideObserved = await evaluateAction(session, "inspect wide-to-wide clamp state", `(async () => {
    const shell = document.querySelector('.app-shell');
    const sidebar = document.querySelector('[data-resize-side="sidebar"]');
    const runtime = document.querySelector('[data-resize-side="runtime"]');
    return {
      viewportWidth: window.innerWidth,
      devicePixelRatio: window.devicePixelRatio,
      sidebarWidth: Number.parseInt(sidebar?.getAttribute('aria-valuenow') || '0', 10),
      runtimePanelWidth: Number.parseInt(runtime?.getAttribute('aria-valuenow') || '0', 10),
      sidebarStyle: shell ? getComputedStyle(shell).getPropertyValue('--sidebar-width').trim() : null,
      runtimeStyle: shell ? getComputedStyle(shell).getPropertyValue('--runtime-width').trim() : null,
      documentWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
      panelMode: shell?.className || null,
      sidebarPresent: Boolean(sidebar),
      runtimePresent: Boolean(runtime),
    };
  })()`);
  writeLog("assertion_info", { description: "wide-to-wide clamp state after synthetic resize", value: wideToWideObserved });
  await waitFor(session, "wide-to-wide viewport clamp", `(() => {
    const sidebar = Number.parseInt(document.querySelector('[data-resize-side="sidebar"]')?.getAttribute('aria-valuenow') || '0', 10);
    const runtime = Number.parseInt(document.querySelector('[data-resize-side="runtime"]')?.getAttribute('aria-valuenow') || '0', 10);
    return window.innerWidth === 800 && sidebar === 180 && runtime === 380 && sidebar + runtime + 240 <= window.innerWidth;
  })()`);
  const wideToWideEvidence = await evaluateAction(session, "read wide-to-wide viewport clamp", `(() => {
    const sidebar = Number.parseInt(document.querySelector('[data-resize-side="sidebar"]')?.getAttribute('aria-valuenow') || '0', 10);
    const runtime = Number.parseInt(document.querySelector('[data-resize-side="runtime"]')?.getAttribute('aria-valuenow') || '0', 10);
    return { viewportWidth: window.innerWidth, sidebarWidth: sidebar, runtimePanelWidth: runtime, conversationWidth: window.innerWidth - sidebar - runtime };
  })()`);
  writeLog("assertion_pass", { description: "wide-to-wide CSS viewport clamp after synthetic resize event", value: wideToWideEvidence });
  await restoreWideCssViewport(session, "wide-to-wide CSS viewport reset");
  await evaluateAction(session, "restore layout preference baseline", `(async () => {
    await window.uthcode.writePreference("sidebarWidth", ${initial.sidebarWidth});
    await window.uthcode.writePreference("runtimePanelWidth", ${initial.runtimePanelWidth});
    return true;
  })()`);
  const restoredDocumentOrigin = await evaluateAction(session, "read document origin before baseline reload", "performance.timeOrigin");
  await session.send("Page.reload", { ignoreCache: true });
  await waitFor(session, "layout baseline after wide-to-wide assertion", `performance.timeOrigin !== ${JSON.stringify(restoredDocumentOrigin)} && document.readyState === 'complete' && Boolean(document.querySelector('.app-shell')) && Boolean(document.querySelector('.composer textarea'))`);
  await waitFor(session, "layout preference baseline restored", `(async () => (await window.uthcode.readPreference("sidebarWidth")) === ${initial.sidebarWidth} && (await window.uthcode.readPreference("runtimePanelWidth")) === ${initial.runtimePanelWidth} && document.querySelector('[data-resize-side="sidebar"]')?.getAttribute('aria-valuenow') === ${JSON.stringify(String(initial.sidebarWidth))} && document.querySelector('[data-resize-side="runtime"]')?.getAttribute('aria-valuenow') === ${JSON.stringify(String(initial.runtimePanelWidth))})()`);

  await evaluateAction(session, "keyboard resize Runtime panel", `(() => {
    const element = document.querySelector('[data-resize-side="runtime"]');
    if (!element) return false;
    element.focus();
    element.dispatchEvent(new KeyboardEvent('keydown', { key: 'Home', code: 'Home', bubbles: true, cancelable: true }));
    return true;
  })()`);
  await waitFor(session, "Runtime keyboard preference commit", "(async () => (await window.uthcode.readPreference('runtimePanelWidth')) === 260)()");
  writeLog("assertion_pass", { description: "keyboard Runtime resize commits at the stable key boundary", value: { runtimePanelWidth: 260 } });

  const focusBaseline = await evaluateAction(session, "read Focus Mode baseline", `(async () => ({
    panelMode: await window.uthcode.readPreference("panelMode"),
    sidebarWidth: await window.uthcode.readPreference("sidebarWidth"),
    runtimePanelWidth: await window.uthcode.readPreference("runtimePanelWidth"),
  }))()`);
  await clickSelector(session, ".focus-mode-toggle");
  await waitFor(session, "Focus Mode active", "document.querySelector('.app-shell')?.classList.contains('focus-mode') && !document.querySelector('.sidebar') && !document.querySelector('#runtime-panel')");
  const focusPreferences = await evaluateAction(session, "read Focus Mode preferences", `(async () => ({
    panelMode: await window.uthcode.readPreference("panelMode"),
    sidebarWidth: await window.uthcode.readPreference("sidebarWidth"),
    runtimePanelWidth: await window.uthcode.readPreference("runtimePanelWidth"),
  }))()`);
  if (JSON.stringify(focusPreferences) !== JSON.stringify(focusBaseline)) throw new Error(`Focus Mode changed durable preferences: ${JSON.stringify({ focusBaseline, focusPreferences })}`);
  await capture(session, "main-focus-mode");
  const escaped = await evaluateAction(session, "exit Focus Mode with Escape", `(() => { const event = new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', bubbles: true, cancelable: true }); document.dispatchEvent(event); return event.defaultPrevented; })()`);
  if (!escaped) throw new Error("Focus Mode Escape was not consumed");
  await waitFor(session, "Focus Mode restored", "!document.querySelector('.app-shell')?.classList.contains('focus-mode') && Boolean(document.querySelector('.sidebar')) && Boolean(document.querySelector('#runtime-panel'))");
  const restoredPreferences = await evaluateAction(session, "read restored Focus Mode preferences", `(async () => ({
    panelMode: await window.uthcode.readPreference("panelMode"),
    sidebarWidth: await window.uthcode.readPreference("sidebarWidth"),
    runtimePanelWidth: await window.uthcode.readPreference("runtimePanelWidth"),
  }))()`);
  if (JSON.stringify(restoredPreferences) !== JSON.stringify(focusBaseline)) throw new Error(`Focus Mode restore changed durable preferences: ${JSON.stringify({ focusBaseline, restoredPreferences })}`);
  writeLog("assertion_pass", { description: "Focus Mode is transient and restores panel mode and widths", value: restoredPreferences });

  const usage = await evaluateAction(session, "inspect split Runtime usage projection", `(() => {
    const current = document.querySelector('[data-runtime-usage="current-context"]');
    const last = document.querySelector('[data-runtime-usage="last-provider-request"]');
    return { current: current?.textContent?.trim() || null, currentStatus: current?.getAttribute('data-usage-status') || null, last: last?.textContent?.trim() || null, lastStatus: last?.getAttribute('data-usage-status') || null };
  })()`);
  if (!usage?.current || !usage?.last || !["available", "unavailable"].includes(usage.currentStatus) || usage.lastStatus !== "available" && usage.lastStatus !== "not_available") {
    throw new Error(`Runtime usage projections were not separated: ${JSON.stringify(usage)}`);
  }
  writeLog("assertion_pass", { description: "RuntimePanel separates Current Context and Last Provider Request Usage", value: usage });

  await session.send("Emulation.setDeviceMetricsOverride", { width: 520, height: 800, deviceScaleFactor: 1, mobile: false });
  // The DevTools metric command changes CSS layout without notifying the
  // renderer; make that synthetic boundary explicit before the narrow check.
  await evaluateAction(session, "dispatch synthetic resize before narrow layout probe", "window.dispatchEvent(new Event('resize'))");
  await waitFor(session, "narrow layout disables separators", "window.innerWidth <= 680 && document.querySelectorAll('[data-resize-side]').length === 0 && document.querySelector('.app-shell')?.classList.contains('panel-docked')");
  const narrow = await evaluateAction(session, "inspect narrow overlay boundary", `(() => ({ runtime: document.querySelector('#runtime-panel')?.getAttribute('aria-hidden') || null, separators: document.querySelectorAll('[data-resize-side]').length, overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1 }))()`);
  if (narrow.separators !== 0 || narrow.overflow) throw new Error(`narrow layout retained resize or overflow: ${JSON.stringify(narrow)}`);
  writeLog("assertion_pass", { description: "narrow layout disables resize and keeps overlay boundary", value: narrow });
  await restoreWideCssViewport(session, "narrow layout CSS viewport reset");
}

async function submitAskUserFlow(session) {
  await waitForInteraction(session, "AskUser questions", '[aria-label="Questions"]');
  await waitFor(session, "AskUser first question", "document.querySelector('[aria-label=\"Questions\"] h2')?.textContent?.includes('Fixture choice')");
  await assertSingleDomEntity(session, "AskUser questions single DOM entity", '[aria-label="Questions"]');
  await capture(session, "ask-user-questions");
  if (![1, 2, 3, 4].includes(askQuestionCount)) throw new Error(`AskUser question count must be 1-4, got ${askQuestionCount}`);
  await setQuestionFreeInput(session, "custom fixture path");
  if (askQuestionCount > 1) {
    await waitFor(session, "AskUser choice complete", "Boolean([...document.querySelectorAll('button')].find((item) => item.textContent?.includes('Next') && !item.disabled))");
    await clickText(session, "Next");
  } else {
    await waitFor(session, "AskUser one-question review enabled", "Boolean([...document.querySelectorAll('button')].find((item) => item.textContent?.includes('Review') && !item.disabled))");
  }

  if (askQuestionCount >= 2) {
    await waitFor(session, "AskUser text question", "Boolean(document.querySelector('input[aria-label=\"Fixture note\"]'))");
    await setInput(session, "Fixture note", "CDP note");
    if (askQuestionCount > 2) {
      await waitFor(session, "AskUser text complete", "Boolean([...document.querySelectorAll('button')].find((item) => item.textContent?.includes('Next') && !item.disabled))");
      await clickText(session, "Next");
    } else {
      await waitFor(session, "AskUser two-question review enabled", "Boolean([...document.querySelectorAll('button')].find((item) => item.textContent?.includes('Review') && !item.disabled))");
    }
  }

  if (askQuestionCount >= 3) {
    await waitFor(session, "AskUser multi-select question", "Boolean(document.querySelector('input.question-free-input')) && document.querySelector('[aria-label=\"Questions\"] h2')?.textContent?.includes('Fixture tags')");
    await clickLabelText(session, "README");
    await clickLabelText(session, "tests");
    await setQuestionFreeInput(session, "docs");
    if (askQuestionCount > 3) {
      await waitFor(session, "AskUser multi-select complete", "Boolean([...document.querySelectorAll('button')].find((item) => item.textContent?.includes('Next') && !item.disabled))");
      await clickText(session, "Next");
    } else {
      await waitFor(session, "AskUser review enabled", "Boolean([...document.querySelectorAll('button')].find((item) => item.textContent?.includes('Review') && !item.disabled))");
    }
  }

  if (askQuestionCount === 4) {
    await waitFor(session, "AskUser final text question", "Boolean(document.querySelector('input[aria-label=\"Fixture summary\"]'))");
    await setInput(session, "Fixture summary", "CDP acceptance");
    await waitFor(session, "AskUser review enabled", "Boolean([...document.querySelectorAll('button')].find((item) => item.textContent?.includes('Review') && !item.disabled))");
  }
  await clickText(session, "Review");
  await waitFor(session, "AskUser answer review", "document.querySelector('[aria-label=\"Questions\"] h2')?.textContent?.includes('Review answers')");
  await assertSingleDomEntity(session, "AskUser review single DOM entity", '[aria-label="Questions"]');
  await capture(session, "ask-user-review");
  await clickText(session, "Submit answers");
  await waitFor(session, `AskUser same-turn continuation ${expectedText}`, `document.body?.innerText?.includes(${JSON.stringify(expectedText)})`);
  await capture(session, "ask-user-complete");
}

async function submitToolFlow(session, expectedToolText, expectedToolRows = 1) {
  await waitFor(session, "Tool completion or permission", `document.body?.innerText?.includes(${JSON.stringify(expectedToolText)}) || Boolean(document.querySelector('[aria-label=\"Permission approval\"]'))`);
  await capture(session, "tool-result");
  const permissionShown = await evaluateAction(session, "inspect Permission surface", "Boolean(document.querySelector('[aria-label=\"Permission approval\"]'))");
  if (permissionShown) {
    writeLog("assertion_pass", { description: "dynamic Permission surface" });
    await clickText(session, "Allow once");
  }
  await waitFor(session, `Tool result ${expectedToolText}`, `document.body?.innerText?.includes(${JSON.stringify(expectedToolText)})`);
  await assertSingleDomEntity(session, "Tool activity rows", '.timeline-activity-item', expectedToolRows);
  await waitFor(session, "nested tool disclosures start collapsed", `(() => { const group = document.querySelector('details.timeline-activity-group'); const item = group?.querySelector('details.timeline-activity-item'); return Boolean(group && item && !group.open && !item.open); })()`);
  const groupExpanded = await evaluateAction(session, "expand tool activity group", `(() => { const summary = document.querySelector('details.timeline-activity-group > summary'); if (!summary) return false; summary.click(); return true; })()`);
  if (!groupExpanded) throw new Error("tool activity group summary was not available");
  await waitFor(session, "tool activity group expanded", "document.querySelector('details.timeline-activity-group')?.open === true && document.querySelector('details.timeline-activity-item')?.open === false");
  await capture(session, "tool-group-expanded");
  const detailExpanded = await evaluateAction(session, "expand individual tool activity", `(() => { const summary = document.querySelector('details.timeline-activity-item > summary'); if (!summary) return false; summary.click(); return true; })()`);
  if (!detailExpanded) throw new Error("individual tool activity summary was not available");
  await waitFor(session, "individual tool activity expanded", "document.querySelector('details.timeline-activity-group')?.open === true && document.querySelector('details.timeline-activity-item')?.open === true");
  await capture(session, "tool-detail-expanded");
  await evaluateAction(session, "collapse individual tool activity", "document.querySelector('details.timeline-activity-item > summary')?.click(); true");
  await waitFor(session, "individual tool activity collapsed", "document.querySelector('details.timeline-activity-item')?.open === false");
  await evaluateAction(session, "collapse tool activity group", "document.querySelector('details.timeline-activity-group > summary')?.click(); true");
  await waitFor(session, "tool activity group collapsed", "document.querySelector('details.timeline-activity-group')?.open === false");
  await capture(session, "tool-folds-collapsed");
}

async function clickReviewTab(session, label) {
  const clicked = await evaluateAction(session, `select Review tab ${label}`, `(() => {
    const tab = [...document.querySelectorAll('.review-panel__tabs [role="tab"]')].find((item) => (item.textContent || '').trim().includes(${JSON.stringify(label)}));
    if (!tab) return false;
    tab.click();
    return true;
  })()`);
  if (!clicked) throw new Error(`Review tab was not available: ${label}`);
  await waitFor(session, `Review tab selected ${label}`, `(() => {
    const tab = [...document.querySelectorAll('.review-panel__tabs [role="tab"]')].find((item) => (item.textContent || '').trim().includes(${JSON.stringify(label)}));
    return tab?.getAttribute('aria-selected') === 'true';
  })()`);
}

async function doubleClickReviewArtifact(session, fileName) {
  const scrolled = await evaluateAction(session, `scroll Review FileCard ${fileName} into the Timeline viewport`, `(() => {
    const card = [...document.querySelectorAll('.markdown-artifact-attachments .file-card[data-artifact-path]')]
      .find((item) => (item.getAttribute('data-artifact-path') || '').replaceAll('\\\\', '/').split('/').at(-1) === ${JSON.stringify(fileName)});
    if (!card) return false;
    card.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' });
    return true;
  })()`);
  if (!scrolled) throw new Error(`Review FileCard was not available to scroll: ${fileName}`);
  const target = await evaluateAction(session, `inspect Review FileCard ${fileName}`, `(() => {
    const card = [...document.querySelectorAll('.markdown-artifact-attachments .file-card[data-artifact-path]')]
      .find((item) => (item.getAttribute('data-artifact-path') || '').replaceAll('\\\\', '/').split('/').at(-1) === ${JSON.stringify(fileName)});
    if (!card) return null;
    const rect = card.getBoundingClientRect();
    const style = getComputedStyle(card);
    const x = rect.left + rect.width / 2;
    const y = rect.top + rect.height / 2;
    const hit = document.elementFromPoint(x, y);
    return { x, y, width: rect.width, height: rect.height, visible: style.display !== 'none' && style.visibility !== 'hidden', inViewport: x >= 0 && y >= 0 && x < innerWidth && y < innerHeight, hitTarget: hit === card || card.contains(hit) };
  })()`);
  if (!target?.visible || !target.inViewport || !target.hitTarget || !(target.width > 0 && target.height > 0)) throw new Error(`Review FileCard was not clickable in the Timeline viewport: ${fileName} ${JSON.stringify(target)}`);
  await session.send("Page.bringToFront");
  for (const clickCount of [1, 2]) {
    await session.send("Input.dispatchMouseEvent", { type: "mousePressed", x: target.x, y: target.y, button: "left", buttons: 1, clickCount });
    await session.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: target.x, y: target.y, button: "left", buttons: 0, clickCount });
    if (clickCount === 1) await sleep(80);
  }
  writeLog("action", { action: "double_click_artifact_file_card", fileName, target: { x: target.x, y: target.y } });
}

async function dropReviewImageAttachment(session) {
  if (!reviewImagePath) throw new Error("review flow requires a runner-owned image attachment path");
  const fileBytes = await readFile(reviewImagePath);
  if (fileBytes.length === 0) throw new Error("runner-owned Review image attachment was empty");
  const base64 = fileBytes.toString("base64");
  const dropped = await evaluateAction(session, "drop a controlled image through the real Composer", `(() => {
    const target = document.querySelector('.composer');
    if (!target || typeof DataTransfer !== 'function') return { accepted: false, reason: 'composer-or-datatransfer-unavailable' };
    const binary = atob(${JSON.stringify(base64)});
    const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
    const file = new File([bytes], 'review-attachment.png', { type: 'image/png' });
    const transfer = new DataTransfer();
    transfer.items.add(file);
    target.dispatchEvent(new DragEvent('dragover', { bubbles: true, cancelable: true, dataTransfer: transfer }));
    const drop = new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: transfer });
    target.dispatchEvent(drop);
    return { accepted: drop.defaultPrevented, name: file.name, size: file.size, mimeType: file.type, fileCount: transfer.files.length };
  })()`);
  if (!dropped?.accepted || dropped.fileCount !== 1 || dropped.size !== fileBytes.length) {
    throw new Error(`controlled image did not enter the Composer drop route: ${JSON.stringify(dropped)}`);
  }
  const card = await waitFor(session, "imported Session-owned image draft", `(() => {
    const item = [...document.querySelectorAll('.composer-attachments .file-card[data-file-ref]')].find((candidate) => (candidate.getAttribute('aria-label') || '').startsWith('review-attachment.png'));
    if (!item) return false;
    const ref = item.getAttribute('data-file-ref') || '';
    return { label: item.getAttribute('aria-label'), kind: item.getAttribute('data-file-kind'), refPresent: Boolean(ref), refLooksLikePath: /(?:[A-Za-z]:[\\/]|\\\\)/u.test(ref), hasThumbnail: Boolean(item.querySelector('img')) };
  })()`);
  if (card.kind !== "image" || !card.refPresent || card.refLooksLikePath || !card.hasThumbnail) {
    throw new Error(`image attachment draft did not retain a safe opaque reference and preview: ${JSON.stringify(card)}`);
  }
  writeLog("assertion_pass", { description: "a controlled image enters through the actual Composer drop and Attachment RPC, and the draft exposes only an opaque ref/name/thumbnail", value: { ...card, byteLength: dropped.size } });
  return { ...card, byteLength: dropped.size };
}

async function doubleClickUserImageAttachment(session) {
  const target = await evaluateAction(session, "inspect the real sent image Attachment FileCard", `(() => {
    const card = [...document.querySelectorAll('.timeline-entry--user .timeline-attachments .file-card[data-file-ref]')]
      .find((item) => (item.getAttribute('aria-label') || '').startsWith('review-attachment.png'));
    if (!card) return null;
    card.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' });
    const rect = card.getBoundingClientRect();
    const style = getComputedStyle(card);
    return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2, width: rect.width, height: rect.height, visible: style.display !== 'none' && style.visibility !== 'hidden', label: card.getAttribute('aria-label'), kind: card.getAttribute('data-file-kind'), refPresent: Boolean(card.getAttribute('data-file-ref')) };
  })()`);
  if (!target?.visible || target.kind !== "image" || !target.refPresent || !(target.width > 0 && target.height > 0)) {
    throw new Error(`sent image Attachment FileCard was missing or unsafe: ${JSON.stringify(target)}`);
  }
  await session.send("Page.bringToFront");
  for (const clickCount of [1, 2]) {
    await session.send("Input.dispatchMouseEvent", { type: "mousePressed", x: target.x, y: target.y, button: "left", buttons: 1, clickCount });
    await session.send("Input.dispatchMouseEvent", { type: "mouseReleased", x: target.x, y: target.y, button: "left", buttons: 0, clickCount });
    if (clickCount === 1) await sleep(80);
  }
  await waitFor(session, "safe image Attachment opened in Review", `(() => { const image = document.querySelector('.review-panel .document-review-image img'); return Boolean(image?.getAttribute('src')?.startsWith('data:image/') && image.complete && image.naturalWidth > 0 && image.naturalHeight > 0); })()`);
  const opened = await evaluateAction(session, "record safe image Attachment Review source", `(() => {
    const card = [...document.querySelectorAll('.timeline-entry--user .timeline-attachments .file-card[data-file-ref]')].find((item) => (item.getAttribute('aria-label') || '').startsWith('review-attachment.png'));
    const preview = document.querySelector('.review-panel .document-review-image img');
    return { label: card?.getAttribute('aria-label') || null, kind: card?.getAttribute('data-file-kind') || null, refPresent: Boolean(card?.getAttribute('data-file-ref')), previewLoaded: Boolean(preview?.getAttribute('src')?.startsWith('data:image/') && preview.complete && preview.naturalWidth > 0 && preview.naturalHeight > 0), previewMime: preview?.getAttribute('src')?.slice(0, preview.getAttribute('src')?.indexOf(';') ?? undefined) || null };
  })()`);
  const modalOpened = await evaluateAction(session, "open the Attachment image preview from Review", `(() => {
    const button = document.querySelector('.review-panel .document-review-image button');
    if (!button) return false;
    button.click();
    return true;
  })()`);
  if (!modalOpened) throw new Error("Review did not expose the image preview action for the Session attachment");
  await waitFor(session, "Session attachment full-image modal", `(() => { const image = document.querySelector('.image-preview-modal[role="dialog"] img'); return Boolean(image?.getAttribute('src')?.startsWith('data:image/') && image.complete && image.naturalWidth > 0 && image.naturalHeight > 0); })()`);
  await capture(session, "review-session-image-attachment-modal");
  const closed = await evaluateAction(session, "close the Attachment image modal", `(() => {
    const button = document.querySelector('.image-preview-modal[role="dialog"] > header button');
    if (!button) return false;
    button.click();
    return true;
  })()`);
  if (!closed) throw new Error("Session attachment image modal did not expose its close action");
  await waitFor(session, "Attachment modal closed back to its Review owner", `Boolean(!document.querySelector('.image-preview-modal') && document.querySelector('.review-panel .document-review-image img[src^="data:image/"]'))`);
  return { ...opened, modalOpened: true, modalClosedToReview: true };
}

async function submitPackagedReviewFlow(session) {
  if (!reviewMarkdownPath || !reviewTextPath || !reviewImagePath) throw new Error("review flow requires controlled Markdown, text, and image paths");
  await clickText(session, "New chat");
  const sessionIdentity = await waitFor(session, "explicit Coding Review Session", `(() => {
    const row = document.querySelector('button.session-line.is-selected:not(.new-session-line)');
    const label = row?.getAttribute('aria-label') || '';
    return row && label ? { label, id: label.split(' · ')[1] || null } : false;
  })()`);
  if (!sessionIdentity?.id) throw new Error(`explicit Coding Review Session did not expose an identity: ${JSON.stringify(sessionIdentity)}`);
  const ownerReady = await waitForStableObservation(session, "public Coding Review Session owner ready", `(async () => {
    const status = await window.uthcode.requestRuntime('status.get', {});
    const selected = document.querySelector('button.session-line.is-selected:not(.new-session-line)')?.getAttribute('aria-label') || '';
    const selectedId = selected.split(' · ')[1] || null;
    const mode = document.querySelector('.sidebar-brand-menu-trigger')?.dataset.mode || null;
    const projectLabel = document.querySelector('button.project-select')?.textContent?.trim() || null;
    const ready = mode === 'coding' && projectLabel?.includes('T12 Review project') && selectedId === ${JSON.stringify(sessionIdentity.id)} && status?.session_id === selectedId && status?.runtime?.state === 'ready' && status?.active_turn === false;
    return { ready, mode, projectLabel, selectedSessionId: selectedId, publicSessionId: status?.session_id ?? null, runtimeState: status?.runtime?.state ?? null, activeTurn: status?.active_turn ?? null };
  })()`);
  const imageAttachment = await dropReviewImageAttachment(session);
  await setInput(session, "Message UthCode", "Review the controlled files and process output.");
  await waitFor(session, "controlled Review prompt ready", `(() => { const input = document.querySelector('textarea[aria-label="Message UthCode"], textarea[aria-label="发送给 UthCode"]'); const button = document.querySelector('.composer-send'); return Boolean(input?.value.trim()) && Boolean(button && !button.disabled); })()`);
  await clickSelector(session, ".composer-send");
  await submitToolFlow(session, expectedText, 2);
  await waitFor(session, "Review fixture artifacts and process log", `(() => {
    const timeline = document.querySelector('[aria-label="Chat timeline"]')?.innerText || '';
    const cards = [...document.querySelectorAll('.markdown-artifact-attachments .file-card[data-artifact-path]')];
    const paths = cards.map((item) => (item.getAttribute('data-artifact-path') || '').replaceAll('\\\\', '/').toLowerCase());
    const names = cards.map((item) => (item.getAttribute('aria-label') || '').split(' · ')[0]);
    const processLogs = [...document.querySelectorAll('[data-process-id]')].some((item) => (item.textContent || '').includes('W05_REVIEW_PROCESS_LOG'));
    return timeline.includes(${JSON.stringify(expectedText)}) && cards.length === ${reviewCodePath ? 3 : 2} && names.includes('review.md') && names.includes('review.txt')
      && paths.some((path) => path.endsWith('/review.md')) && paths.some((path) => path.endsWith('/review.txt')) && processLogs;
  })()`);
  const artifactCards = await evaluateAction(session, "record formal Review artifact cards", `(() => [...document.querySelectorAll('.markdown-artifact-attachments .file-card[data-artifact-path]')].map((item) => ({ path: item.getAttribute('data-artifact-path'), name: (item.getAttribute('aria-label') || '').split(' · ')[0], kind: item.getAttribute('data-artifact-kind') })))()`);
  if (artifactCards.length !== (reviewCodePath ? 3 : 2) || !artifactCards.some((item) => item.name === "review.md") || !artifactCards.some((item) => item.name === "review.txt")) throw new Error(`formal Review Markdown did not resolve the controlled artifacts: ${JSON.stringify(artifactCards)}`);
  const expectedArtifactPaths = [reviewMarkdownPath, reviewTextPath, reviewCodePath].filter(Boolean).map((path) => String(path).replaceAll("\\", "/").toLowerCase());
  if (artifactCards.some((item) => !expectedArtifactPaths.includes(String(item.path).replaceAll("\\", "/").toLowerCase()))) throw new Error(`Review FileCards resolved outside the exact runner-owned artifact paths: ${JSON.stringify(artifactCards)}`);
  await waitFor(session, "sent image attachment belongs to the controlled Review Session", `(() => {
    const entry = [...document.querySelectorAll('.timeline-entry--user')].find((item) => (item.innerText || '').includes('Review the controlled files and process output.'));
    const card = [...(entry?.querySelectorAll('.timeline-attachments .file-card[data-file-ref]') || [])].find((item) => (item.getAttribute('aria-label') || '').startsWith('review-attachment.png'));
    return card ? { label: card.getAttribute('aria-label'), kind: card.getAttribute('data-file-kind'), refPresent: Boolean(card.getAttribute('data-file-ref')), hasThumbnail: Boolean(card.querySelector('img')) } : false;
  })()`);
  const sentImageAttachment = await doubleClickUserImageAttachment(session);

  const processLogOpened = await evaluateAction(session, "open Process logs from the real Timeline", `(() => {
    const details = document.querySelector('details.timeline-process-log');
    if (!details) return false;
    if (!details.open) details.querySelector('summary')?.click();
    const process = [...details.querySelectorAll('.timeline-process-log__process')].find((item) => (item.textContent || '').includes('W05_REVIEW_PROCESS_LOG'));
    const button = [...(process?.querySelectorAll('button') || [])].find((item) => (item.textContent || '').includes('Review process log'));
    if (!button) return false;
    button.click();
    return true;
  })()`);
  if (!processLogOpened) throw new Error("actual Process output was not available from the Timeline Review action");
  await waitFor(session, "Process Review tab contains real process output", `Boolean(document.querySelector('.review-panel__process-output')?.textContent?.includes('W05_REVIEW_PROCESS_LOG'))`);
  const processTab = await evaluateAction(session, "record Process Review tab", `(() => ({ tab: [...document.querySelectorAll('.review-panel__tabs [role="tab"]')].find((item) => item.getAttribute('aria-selected') === 'true')?.textContent?.trim() || null, sequences: [...document.querySelectorAll('.review-panel__process-output [data-process-sequence]')].map((item) => item.getAttribute('data-process-sequence')), markerVisible: (document.querySelector('.review-panel__process-output')?.textContent || '').includes('W05_REVIEW_PROCESS_LOG') }))()`);
  await capture(session, "review-process-log");

  await computerUseCheckpoint("process-log-observation");

  const groupOpened = await evaluateAction(session, "expand the real ReadFile activity group", `(() => {
    const group = document.querySelector('details.timeline-activity-group');
    if (!group) return { found: false };
    if (!group.open) group.querySelector('summary')?.click();
    return { found: true, open: group.open };
  })()`);
  if (!groupOpened?.found) throw new Error(`Tool Timeline did not expose its actual activity group: ${JSON.stringify(groupOpened)}`);
  await waitFor(session, "outer ReadFile activity group expanded", `Boolean(document.querySelector('details.timeline-activity-group')?.open)`);
  const readFileOpened = await evaluateAction(session, "expand the real ReadFile activity row", `(() => {
    const item = [...document.querySelectorAll('details.timeline-activity-group details.timeline-activity-item')].find((candidate) => (candidate.getAttribute('aria-label') || '').startsWith('ReadFile:'));
    if (!item) return { found: false, labels: [...document.querySelectorAll('details.timeline-activity-group .timeline-activity-item')].map((candidate) => candidate.getAttribute('aria-label')) };
    if (!item.open) item.querySelector('summary')?.click();
    return { found: true, open: item.open, label: item.getAttribute('aria-label') };
  })()`);
  if (!readFileOpened?.found) throw new Error(`ReadFile activity row was not present in the real outer group: ${JSON.stringify(readFileOpened)}`);
  await waitFor(session, "ReadFile activity row expanded", `(() => [...document.querySelectorAll('details.timeline-activity-group details.timeline-activity-item')].some((item) => (item.getAttribute('aria-label') || '').startsWith('ReadFile:') && item.open))()`);
  await capture(session, "review-readfile-activity-expanded");
  const outputAction = await evaluateAction(session, "inspect the real ReadFile output action and its public history DTO", `(async () => {
    const item = [...document.querySelectorAll('details.timeline-activity-group details.timeline-activity-item')].find((candidate) => (candidate.getAttribute('aria-label') || '').startsWith('ReadFile:'));
    const button = item?.querySelector('button.timeline-tool-output');
    const observation = { label: item?.getAttribute('aria-label') || null, status: item?.querySelector('[data-status]')?.getAttribute('data-status') || null, outputButtons: [...(item?.querySelectorAll('button') || [])].map((candidate) => ({ className: candidate.className, text: candidate.textContent?.trim() || '' })), hasOutputPreview: Boolean(item?.querySelector('button.timeline-tool-output')) };
    if (!button) {
      const status = await window.uthcode.requestRuntime('status.get', {});
      const page = await window.uthcode.requestRuntime('history.page', { session_id: status?.session_id, page_size: 50 });
      const records = Array.isArray(page?.records) ? page.records.filter((record) => record?.tool_name === 'ReadFile').map((record) => ({ sessionId: record.session_id ?? null, toolCallId: record.tool_call_id ?? null, outputRefPresent: typeof record.output_ref === 'string' && record.output_ref.length > 0, outputPreviewLength: typeof record.output_preview === 'string' ? record.output_preview.length : null, previewTruncated: record.output_preview_truncated === true })) : [];
      return { clicked: false, ...observation, publicHistory: { sessionId: page?.session_id ?? null, recordCount: records.length, records } };
    }
    button.click();
    return { clicked: true, ...observation };
  })()`);
  if (!outputAction?.clicked) throw new Error(`ReadFile Timeline row did not expose its real safe output action: ${JSON.stringify(outputAction)}`);
  await waitFor(session, "bounded ReadFile Review first page", `(() => {
    const output = document.querySelector('.review-panel__output')?.textContent || '';
    return output.includes('W05_REVIEW_OUTPUT_BEGIN') && Boolean(document.querySelector('.review-panel__more'));
  })()`);
  const firstPage = await evaluateAction(session, "record bounded ReadFile Review page", `(() => ({ tab: document.querySelector('.review-panel__content')?.getAttribute('aria-label') || null, chars: document.querySelector('.review-panel__output')?.textContent?.length || 0, hasStart: (document.querySelector('.review-panel__output')?.textContent || '').includes('W05_REVIEW_OUTPUT_BEGIN'), hasMore: Boolean(document.querySelector('.review-panel__more')) }))()`);
  await computerUseCheckpoint("tool-output-first-page");
  const moreOutput = await evaluateAction(session, "read next bounded Review page", `(() => { const button = document.querySelector('.review-panel__more'); if (!button || button.disabled) return false; button.click(); return true; })()`);
  const readByComputerUse = computerUse && !moreOutput && await session.evaluate("(document.querySelector('.review-panel__output')?.textContent || '').includes('W05_REVIEW_OUTPUT_END') && !document.querySelector('.review-panel__more')");
  if (!moreOutput && !readByComputerUse) throw new Error("bounded ReadFile Review did not expose its next page");
  await waitFor(session, "ReadFile Review reaches final output page", `(() => (document.querySelector('.review-panel__output')?.textContent || '').includes('W05_REVIEW_OUTPUT_END') && !document.querySelector('.review-panel__more'))()`);
  const finalOutput = await evaluateAction(session, "record complete bounded Review output", `(() => ({ chars: document.querySelector('.review-panel__output')?.textContent?.length || 0, hasEnd: (document.querySelector('.review-panel__output')?.textContent || '').includes('W05_REVIEW_OUTPUT_END'), hasMore: Boolean(document.querySelector('.review-panel__more')) }))()`);
  await capture(session, "review-tool-output");

  await doubleClickReviewArtifact(session, "review.md");
  await waitFor(session, "Markdown artifact opened in Review", `Boolean([...document.querySelectorAll('.review-panel__tabs [role="tab"]')].find((item) => (item.textContent || '').trim() === 'review.md')) && Boolean(document.querySelector('.document-preview-markdown')?.textContent?.includes('W05_REVIEW_MARKDOWN_BODY'))`);
  await clickText(session, "View source");
  await waitFor(session, "Markdown Review source mode", `Boolean(document.querySelector('.review-panel [role="tabpanel"] .document-preview-code')?.textContent?.includes('# W05 Review Markdown'))`);
  await clickText(session, "View rendered");
  await waitFor(session, "Markdown Review rendered mode", `Boolean(document.querySelector('.review-panel [role="tabpanel"] .document-preview-markdown')?.textContent?.includes('W05_REVIEW_MARKDOWN_BODY'))`);
  const markdownTab = await evaluateAction(session, "record Markdown Review modes", `(() => ({ rendered: Boolean(document.querySelector('.review-panel [role="tabpanel"] .document-preview-markdown')?.textContent?.includes('W05_REVIEW_MARKDOWN_BODY')), sourceButton: [...document.querySelectorAll('.review-panel [role="tabpanel"] button')].some((item) => (item.textContent || '').includes('View source')) }))()`);

  if (reviewCodePath) {
    await doubleClickReviewArtifact(session, "review.py");
    await waitFor(session, "Python source artifact opened with line numbers and highlighting", `(() => { const code = document.querySelector('.review-panel .document-preview-code[data-language="python"]'); return Boolean(code?.textContent?.includes('def describe_file') && code.querySelector('.document-preview-code__line-number') && code.querySelector('.token')); })()`);
    await capture(session, "review-python-source");
  }

  await doubleClickReviewArtifact(session, "review.txt");
  await waitFor(session, "text artifact opened in Review", `Boolean([...document.querySelectorAll('.review-panel__tabs [role="tab"]')].find((item) => (item.textContent || '').trim() === 'review.txt')) && Boolean(document.querySelector('.review-panel [role="tabpanel"] .document-preview-code')?.textContent?.includes('W05_REVIEW_TEXT_BODY'))`);
  const tabsBeforeClose = await evaluateAction(session, "record all actual Review tabs", `(() => [...document.querySelectorAll('.review-panel__tabs [role="tab"]')].map((item) => ({ label: item.textContent?.trim() || '', selected: item.getAttribute('aria-selected') === 'true' })))()`);
  if (!["ReadFile", "Process log", "review.md", "review.txt"].every((label) => tabsBeforeClose.some((tab) => tab.label.includes(label)))) throw new Error(`Review did not retain all real output/document tabs: ${JSON.stringify(tabsBeforeClose)}`);
  const documentChrome = await waitFor(session, "active document tab stays visible without a duplicate embedded close", `(() => {
    const nav = document.querySelector('.review-panel__tabs');
    const selected = nav?.querySelector('[role="tab"][aria-selected="true"]')?.parentElement;
    if (!nav || !selected) return false;
    const bounds = nav.getBoundingClientRect(); const tab = selected.getBoundingClientRect();
    const duplicateClose = Boolean(document.querySelector('.document-preview-content > header button[aria-label="Close file preview"]'));
    return tab.left >= bounds.left - 1 && tab.right <= bounds.right + 1 && !duplicateClose ? { visible: true, duplicateClose: false, selected: selected.textContent?.trim() } : false;
  })()`);
  await computerUseCheckpoint("documents-and-logs");
  await clickReviewTab(session, "ReadFile");
  await waitFor(session, "switch back to safe bounded output tab", `Boolean(document.querySelector('.review-panel__output')?.textContent?.includes('W05_REVIEW_OUTPUT_BEGIN'))`);
  await clickReviewTab(session, "Process log");
  await waitFor(session, "switch back to process log tab", `Boolean(document.querySelector('.review-panel__process-output')?.textContent?.includes('W05_REVIEW_PROCESS_LOG'))`);
  await clickReviewTab(session, "review.md");
  await clickReviewTab(session, "review.txt");
  const closeOneTab = await evaluateAction(session, "close only the text Review tab", `(() => {
    const wrapper = [...document.querySelectorAll('.review-panel__tab')].find((item) => item.querySelector('[role="tab"]')?.textContent?.trim() === 'review.txt');
    const button = wrapper?.querySelector('button[aria-label^="Close"]');
    if (!button) return false;
    button.click();
    return true;
  })()`);
  if (!closeOneTab) throw new Error("text Review tab did not expose its own close control");
  await waitFor(session, "closing one Review tab retains the others", `(() => {
    const labels = [...document.querySelectorAll('.review-panel__tabs [role="tab"]')].map((item) => item.textContent?.trim() || '');
    return !labels.includes('review.txt') && ['ReadFile', 'Process log', 'review.md'].every((label) => labels.some((value) => value.includes(label))) && Boolean(document.querySelector('.review-panel'));
  })()`);
  const remainingTabs = await evaluateAction(session, "record tabs after one close", `(() => [...document.querySelectorAll('.review-panel__tabs [role="tab"]')].map((item) => item.textContent?.trim() || ''))()`);
  const closePanel = await evaluateAction(session, "close the complete Review panel", `(() => { const button = document.querySelector('.review-panel__header button'); if (!button) return false; button.click(); return true; })()`);
  if (!closePanel) throw new Error("Review panel did not expose its close control");
  await waitFor(session, "Review panel closed", "!document.querySelector('.review-panel') && !document.querySelector('.review-panel__tabs')");
  await doubleClickReviewArtifact(session, "review.md");
  await waitFor(session, "reopen document for owner isolation", `Boolean(document.querySelector('.review-panel') && document.querySelector('.review-panel [role="tabpanel"] .document-preview-markdown')?.textContent?.includes('W05_REVIEW_MARKDOWN_BODY'))`);
  const oldSessionId = sessionIdentity.id;
  await clickText(session, "New chat");
  const newIdentity = await waitFor(session, "new explicit Coding Review Session owner", `(() => {
    const row = document.querySelector('button.session-line.is-selected:not(.new-session-line)');
    const label = row?.getAttribute('aria-label') || '';
    const id = label.split(' · ')[1] || null;
    return row && id && id !== ${JSON.stringify(oldSessionId)} ? { label, id } : false;
  })()`);
  const newOwnerReady = await waitForStableObservation(session, "new public Coding owner with no stale Review content", `(async () => {
    const status = await window.uthcode.requestRuntime('status.get', {});
    const selected = document.querySelector('button.session-line.is-selected:not(.new-session-line)')?.getAttribute('aria-label') || '';
    const selectedId = selected.split(' · ')[1] || null;
    const review = document.querySelector('.review-panel');
    const timeline = document.querySelector('[aria-label="Chat timeline"]')?.innerText || '';
    const staleImageAttachment = [...document.querySelectorAll('.timeline-attachments .file-card[aria-label^="review-attachment.png"]')].length > 0;
    const ready = selectedId === ${JSON.stringify(newIdentity.id)} && status?.session_id === selectedId && status?.runtime?.state === 'ready' && status?.active_turn === false && !review && !timeline.includes('W05_REVIEW_') && !staleImageAttachment;
    return { ready, publicSessionId: status?.session_id ?? null, selectedSessionId: selectedId, runtimeState: status?.runtime?.state ?? null, activeTurn: status?.active_turn ?? null, staleReviewVisible: Boolean(review) || timeline.includes('W05_REVIEW_') || staleImageAttachment };
  })()`);
  flowEvidence.review = {
    originalOwner: { mode: ownerReady.mode, projectLabel: ownerReady.projectLabel, sessionId: sessionIdentity.id },
    output: { firstPage, finalPage: finalOutput },
    processLog: processTab,
    artifacts: artifactCards,
    sourceCode: reviewCodePath ? { name: "review.py", language: "python", lineNumbers: true, highlighted: true } : null,
    attachment: { draft: imageAttachment, sentAndReviewed: sentImageAttachment },
    markdown: markdownTab,
    tabsBeforeClose,
    documentChrome,
    tabsAfterClose: remainingTabs,
    ownerSwitch: { previousSessionId: oldSessionId, currentSessionId: newIdentity.id, observation: newOwnerReady },
  };
  await capture(session, "review-owner-switched");
  writeLog("assertion_pass", { description: "packaged Coding Review opens real bounded tool output, process output, Markdown and text artifacts; tabs switch/close and old content clears on explicit Session owner change" });
  if (!skipQuit) await evaluateAction(session, "close UthCode shell", "window.uthcode.closeShell()");
}

async function submitTodoFlow(session, expectedToolText) {
  await waitFor(session, "Todo projection", "Boolean(document.querySelector('.todo-strip')) && document.querySelector('.todo-strip')?.innerText?.includes('Inspect fixture evidence')");
  await capture(session, "todo-strip");
  await waitFor(session, `Todo continuation ${expectedToolText}`, `document.body?.innerText?.includes(${JSON.stringify(expectedToolText)})`);
  await assertSingleDomEntity(session, "Todo single DOM strip", '.todo-strip');
  await capture(session, "todo-complete");
}

async function installPlanDraftBreakpoint(session) {
  await session.send("Debugger.enable");
  await session.evaluate(`(() => {
    window.__uthcodePlanDraftObserver?.disconnect?.();
    window.__uthcodePlanDraftHit = false;
    const isPartialDraft = () => {
      const entry = document.querySelector('.timeline-entry--plan');
      const text = entry?.textContent || '';
      return Boolean(entry && entry.getAttribute('aria-busy') === 'true' && text.includes('Read the fi') && !document.querySelector('[aria-label="Plan review"]'));
    };
    const observer = new MutationObserver(() => {
      if (window.__uthcodePlanDraftHit || !isPartialDraft()) return;
      window.__uthcodePlanDraftHit = true;
      // The CDP debugger pause freezes the real renderer immediately after
      // the draft commit, before the adjacent Review pause can repaint.
      debugger;
    });
    observer.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true });
    window.__uthcodePlanDraftObserver = observer;
    return true;
  })()`);
}

async function capturePlanDraftAtBreakpoint(session) {
  const remaining = remainingBudget("Plan partial draft visible");
  try {
    const paused = await session.waitForDebuggerPause(remaining);
    writeLog("assertion_pass", { description: "Plan partial draft visible", value: { debuggerPaused: true, reason: paused.reason ?? null } });
    if (screenshotDir) {
      await session.send("Page.bringToFront");
      const screenshot = await session.send("Page.captureScreenshot", { format: "png", fromSurface: true });
      await session.send("Debugger.resume");
      await recordScreenshot(session, "plan-draft-partial", screenshot);
    } else {
      await session.send("Debugger.resume");
    }
    return true;
  } catch (error) {
    writeLog("assertion_info", { description: "Plan draft debugger pause unavailable; using DOM wait", reason: error instanceof Error ? error.message : String(error) });
    return false;
  } finally {
    try { await session.send("Debugger.disable"); } catch { /* page may already be closing */ }
    try { await session.evaluate("window.__uthcodePlanDraftObserver?.disconnect?.(); delete window.__uthcodePlanDraftObserver;"); } catch { /* page may already be closing */ }
  }
}

async function submitPlanFlow(session, expectedToolText) {
  const capturedAtBreakpoint = await capturePlanDraftAtBreakpoint(session);
  if (!capturedAtBreakpoint) {
    await waitFor(session, "Plan partial draft visible", "(() => { const entry = document.querySelector('.timeline-entry--plan'); const text = entry?.textContent || ''; return Boolean(entry && entry.getAttribute('aria-busy') === 'true' && text.includes('Read the fi') && !document.querySelector('[aria-label=\"Plan review\"]')); })()");
    await capture(session, "plan-draft-partial");
  }
  await assertSingleDomEntity(session, "Plan draft single DOM row", '.timeline-entry--plan');
  writeLog("assertion_pass", { description: "Plan partial prefix is visible before Review" });
  await waitForInteraction(session, "Plan review", '[aria-label="Plan review"]');
  await assertSingleDomEntity(session, "Plan review single DOM surface", '[aria-label="Plan review"]');
  await capture(session, "plan-review");
  if (planChoice === "revise") {
    await setInput(session, "Revision feedback", "Use the fixture README only");
    await clickText(session, "Revise plan");
    await waitFor(session, "revised plan review", "(() => { const surface = document.querySelector('[aria-label=\"Plan review\"]'); const revision = surface?.querySelector('h2')?.textContent || ''; const approve = [...(surface?.querySelectorAll('button') || [])].find((item) => (item.textContent || '').includes('Approve and execute')); return Boolean(surface && surface.getAttribute('aria-busy') !== 'true' && revision.includes('2') && approve && !approve.disabled); })()");
    await capture(session, "plan-review-revised");
    await clickText(session, "Approve and execute");
  } else if (planChoice === "cancel") {
    await clickText(session, "Cancel turn");
    await waitFor(session, "plan cancellation", "!document.querySelector('[aria-label=\"Plan review\"]') && !document.querySelector('button.cancel-button')");
    return;
  } else {
    await clickText(session, "Approve and execute");
  }
  await assertSingleDomEntity(session, "Plan visual rows per ProposePlan call", '.timeline-entry--plan', planChoice === "revise" ? 2 : 1);
  await submitToolFlow(session, expectedToolText, planChoice === "revise" ? 2 : 1);
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

async function submitDelayedFlow(session, { general = false } = {}) {
  const controls = general
    ? "Boolean(document.querySelector('button[aria-label=\"Cancel\"], button[aria-label=\"取消\"]'))"
    : "Boolean(document.querySelector('button[aria-label=\"Pause\"]')) && Boolean(document.querySelector('button[aria-label=\"Cancel\"]'))";
  await waitFor(session, "delayed turn controls", controls);
  if (!general) {
  await waitFor(session, "accepted active draft cleared", "document.querySelector('.composer textarea')?.value === ''");
  const emptyAction = await evaluateAction(session, "observe empty active Composer action", `(() => { const input = document.querySelector('.composer textarea'); const button = document.querySelector('.composer-send'); return { empty: input?.value === '', disabled: button?.disabled, label: button?.getAttribute('aria-label'), pause: Boolean(document.querySelector('button[aria-label="Pause"]')), cancel: Boolean(document.querySelector('button[aria-label="Cancel" ]')) }; })()`);
  if (!emptyAction.empty || !emptyAction.disabled || /Steer|引导/u.test(emptyAction.label || '')) throw new Error(`empty active Composer exposed Steering: ${JSON.stringify(emptyAction)}`);
  const emptyAlignment = await verifyComposerRightAlignment(session, "active empty Composer right alignment");
  await capture(session, "active-composer-empty-disabled");
  await setInput(session, "Message UthCode", "   ");
  await waitFor(session, "whitespace active Composer cannot steer", "document.querySelector('.composer-send')?.disabled === true && !/Steer|引导/u.test(document.querySelector('.composer-send')?.getAttribute('aria-label') || '')");
  await setInput(session, "Message UthCode", "Inspect this additional context");
  await waitFor(session, "text enables actual Steering control", "document.querySelector('.composer-send')?.disabled === false && /Steer|引导/u.test(document.querySelector('.composer-send')?.getAttribute('aria-label') || '')");
  const textAlignment = await verifyComposerRightAlignment(session, "active text Composer right alignment");
  await capture(session, "active-composer-text-steering");
  await setInput(session, "Message UthCode", "");
  await waitFor(session, "clearing draft removes Steering", "document.querySelector('.composer-send')?.disabled === true && !/Steer|引导/u.test(document.querySelector('.composer-send')?.getAttribute('aria-label') || '')");
  flowEvidence.steeringDraft = { emptyAction, emptyAlignment, textAlignment, whitespaceDisabled: true, textEnabled: true, clearedDisabled: true };
  }
  await capture(session, "delayed-controls");
  if (delayAction === "cancel") {
    writeLog("action", { action: "click_text", text: "Cancel" });
    const cancelLabel = general && requestedLanguage === "zh-CN" ? "取消" : "Cancel";
    await clickText(session, cancelLabel);
    await waitFor(session, "delayed turn cancellation", "!document.querySelector('button[aria-label=\"Cancel\"], button[aria-label=\"取消\"]') && /cancelled|已取消/u.test(document.body?.innerText || '')");
    return;
  }
  await clickText(session, "Pause");
  await waitForInteraction(session, "turn pause surface", '[aria-label="Turn paused"]');
  await clickText(session, "Continue");
  await waitFor(session, `continued output ${expectedText}`, `document.body?.innerText?.includes(${JSON.stringify(expectedText)})`);
}

async function submitSessionsFlow(session) {
  const sessionRows = [];
  await waitFor(session, `first session output ${expectedText}`, `(() => { const text = document.querySelector('[aria-label=\"Chat timeline\"]')?.innerText || ''; return text.includes('cdp fixture request') && text.includes(${JSON.stringify(expectedText)}); })()`);

  const sessionPrompts = ["cdp fixture session two", "cdp fixture session three", "cdp fixture session four", "cdp fixture session five", "cdp fixture session six"];
  await waitFor(session, "first session displays its first user message", "document.querySelector('button.session-line.is-selected')?.innerText?.includes('cdp fixture request')");
  sessionRows.push(await evaluateAction(session, "remember first session identity", "document.querySelector('button.session-line.is-selected')?.getAttribute('aria-label')"));
  for (const [index, prompt] of sessionPrompts.entries()) {
    const ordinal = index + 2;
    await clickText(session, "New chat");
    await waitFor(session, `${ordinal}th conversation header`, "['Session', 'New conversation', '会话', '新对话'].some((value) => document.querySelector('h1')?.textContent?.includes(value))");
    await waitFor(session, `${ordinal}th composer ready`, "Boolean(document.querySelector('textarea[aria-label=\"Message UthCode\"], textarea[aria-label=\"发送给 UthCode\"]'))");
    await setInput(session, "Message UthCode", prompt);
    await waitFor(session, `${ordinal}th message ready`, "(() => { const input = document.querySelector('textarea[aria-label=\"Message UthCode\"], textarea[aria-label=\"发送给 UthCode\"]'); const button = document.querySelector('.composer-actions button:last-child'); return Boolean(input?.value.trim()) && Boolean(button && !button.disabled); })()");
    await clickSelector(session, ".composer-send");
    await waitFor(session, `${ordinal}th session output ${expectedText}`, `(() => { const text = document.querySelector('[aria-label=\"Chat timeline\"]')?.innerText || ''; return text.includes(${JSON.stringify(prompt)}) && text.includes(${JSON.stringify(expectedText)}); })()`);
    await waitFor(session, `${ordinal}th Session persisted after first turn`, `document.querySelector('button.session-line.is-selected:not(.new-session-line)')?.innerText?.includes(${JSON.stringify(prompt)})`);
    sessionRows.push(await evaluateAction(session, "remember session identity", "document.querySelector('button.session-line.is-selected')?.getAttribute('aria-label')"));
  }
  const expandedSessions = await evaluateAction(session, "expand older session rows", `(() => {
    const button = [...document.querySelectorAll('button')].find((item) => /^(Show more|显示更多)/u.test(item.textContent?.trim() || ''));
    button?.click();
    return Boolean(button) || Boolean(document.querySelector('.session-more[aria-expanded="true"]'));
  })()`);
  if (!expandedSessions || sessionRows.some(value => !value) || new Set(sessionRows).size !== 6) throw new Error("six distinct session identities were not observed");
  await waitFor(session, "session rows beyond five", `(() => { const labels = [...document.querySelectorAll('button.session-line:not(.new-session-line)')].map(item => item.getAttribute('aria-label')); return ${JSON.stringify(sessionRows)}.every(label => labels.includes(label)); })()`);
  await capture(session, "sessions-over-five");

  writeLog("action", { action: "select_session", label: "cdp fixture session two" });
  const switched = await evaluateAction(session, "select second session", `(() => {
    const rows = [...document.querySelectorAll('button.session-line:not(.new-session-line)')];
    const row = rows.find((item) => item.getAttribute('aria-label') === ${JSON.stringify(sessionRows[1])});
    if (!row) return false;
    row.click();
    return true;
  })()`);
  if (!switched) throw new Error("second session row not found");
  await waitFor(session, "second session replay", "document.querySelector('[aria-label=\"Chat timeline\"]')?.innerText?.includes('cdp fixture session two')");

  writeLog("action", { action: "select_session", label: "cdp fixture request" });
  const replayed = await evaluateAction(session, "select first session for replay", `(() => {
    const rows = [...document.querySelectorAll('button.session-line:not(.new-session-line)')];
    const row = rows.find((item) => item.getAttribute('aria-label') === ${JSON.stringify(sessionRows[0])});
    if (!row) return false;
    row.click();
    return true;
  })()`);
  if (!replayed) throw new Error("first session row not found");
  await waitFor(session, "first session replay", "document.querySelector('[aria-label=\"Chat timeline\"]')?.innerText?.includes('cdp fixture request')");

  await setInput(session, "Message UthCode", "cdp fixture replay continuation");
  await waitFor(session, "replayed message ready", "(() => { const input = document.querySelector('textarea[aria-label=\"Message UthCode\"], textarea[aria-label=\"发送给 UthCode\"]'); const button = document.querySelector('.composer-actions button:last-child'); return Boolean(input?.value.trim()) && Boolean(button && !button.disabled); })()");
  await clickSelector(session, ".composer-send");
  await waitFor(session, `replayed session continuation ${expectedText}`, `(() => { const text = document.querySelector('[aria-label=\"Chat timeline\"]')?.innerText || ''; return text.includes('cdp fixture replay continuation') && text.includes(${JSON.stringify(expectedText)}); })()`);
  await submitCompactCommand(session);
}

async function setQuestionFreeInput(session, value) {
  remainingBudget("set AskUser free-text answer");
  writeLog("action", { action: "set_question_free_input", valueLength: value.length });
  const changed = await evaluateAction(session, "set AskUser free-text answer", `(() => {
    const element = document.querySelector('input.question-free-input');
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
  if (!changed) throw new Error("AskUser free-text input not found");
}

async function submitCompactCommand(session) {
  await setInput(session, "Message UthCode", "/compact");
  await waitFor(session, "compact command completion", "Boolean([...document.querySelectorAll('.command-menu button')].find((item) => (item.textContent || '').includes('/compact')))");
  await capture(session, "compact-command-menu");
  const selected = await evaluateAction(session, "select compact command", `(() => {
    const option = [...document.querySelectorAll('.command-menu button')].find((item) => (item.textContent || '').includes('/compact'));
    if (!option) return false;
    option.click();
    return true;
  })()`);
  if (!selected) throw new Error("/compact completion was not available");
  await waitFor(session, "compact command selected", "document.querySelector('textarea[aria-label=\"Message UthCode\"], textarea[aria-label=\"发送给 UthCode\"]')?.value.trim() === '/compact' && !document.querySelector('.command-menu')");
  await evaluateAction(session, "execute compact command", `(() => {
    const element = document.querySelector('textarea[aria-label="Message UthCode"], textarea[aria-label="发送给 UthCode"]');
    if (!element) return false;
    element.focus();
    element.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", bubbles: true }));
    return true;
  })()`);
  await waitFor(session, "compact command settled", "document.querySelector('textarea[aria-label=\"Message UthCode\"], textarea[aria-label=\"发送给 UthCode\"]')?.value.trim() === '' && !document.querySelector('.composer[aria-disabled=\"true\"]')");
  const expected = requestedLanguage === "zh-CN"
    ? { heading: "上下文压缩", states: ["已完成", "无变化", "已取消", "失败"], forbidden: ["Compaction", "completed", "No change", "cancelled"] }
    : { heading: "Compaction", states: ["completed", "No change", "cancelled", "failed"], forbidden: ["上下文压缩", "已完成", "无变化", "已取消"] };
  await waitFor(session, "localized compact terminal", `(() => { const element = document.querySelector('[data-compaction-state]'); return element && ['completed', 'no_change', 'cancelled', 'failed'].includes(element.dataset.compactionState); })()`);
  const terminal = await evaluateAction(session, "read localized compact terminal", `(() => ({ text: document.querySelector('[data-compaction-state]')?.parentElement?.textContent?.trim() || '', count: document.querySelectorAll('[data-compaction-state]').length }))()`);
  if (terminal.count !== 1 || !terminal.text.includes(expected.heading) || expected.forbidden.some((value) => terminal.text.includes(value))) {
    throw new Error(`compact terminal is not a single localized notice: ${JSON.stringify(terminal)}`);
  }
  await capture(session, "compact-terminal");
  writeLog("assertion_pass", { description: `typed /compact has one localized terminal (${requestedLanguage})`, value: terminal });
}

async function submitSettingsRevealFlow(session) {
  await waitFor(session, "Settings provider row", "Boolean(document.querySelector('.provider-row'))");
  const opened = await evaluateAction(session, "open fixture provider settings", "(() => { const row = document.querySelector('.provider-row'); if (!row) return false; row.click(); return true; })()");
  if (!opened) throw new Error("fixture provider row not found");
  await waitFor(session, "Provider API key control", "Boolean(document.querySelector('#modal-api-key')) && Boolean(document.querySelector('button.api-key-toggle'))");
  await assertSingleDomEntity(session, "Provider settings single DOM modal", '.provider-modal');
  await waitFor(session, "saved API key reveal enabled", "Boolean(document.querySelector('button.api-key-toggle:not([disabled])'))");
  await evaluateAction(session, "reveal saved API key", "(() => { const button = document.querySelector('button.api-key-toggle'); if (!button) return false; button.click(); return true; })()");
  await waitFor(session, "saved API key revealed", "document.querySelector('#modal-api-key')?.type === 'text' && document.querySelector('#modal-api-key')?.value === 'env:UTHCODE_CDP_FIXTURE_KEY'");
  await capture(session, "settings-api-key-revealed");
  await evaluateAction(session, "hide saved API key", "(() => { const button = document.querySelector('button.api-key-toggle'); if (!button) return false; button.click(); return true; })()");
  await waitFor(session, "saved API key hidden", "document.querySelector('#modal-api-key')?.type === 'password' && document.querySelector('#modal-api-key')?.value === ''");
  await evaluateAction(session, "close provider settings", "(() => { const button = document.querySelector('.provider-modal header button'); if (!button) return false; button.click(); return true; })()");
  await waitFor(session, "Provider settings closed", "!document.querySelector('.provider-modal')");
  await capture(session, "settings-api-key-hidden");
  writeLog("assertion_pass", { description: "saved API key reveal/hide uses narrow Settings path" });
}

async function submitStatusCommand(session) {
  await setInput(session, "Message UthCode", "/status");
  await waitFor(session, "status command completion", "Boolean([...document.querySelectorAll('.command-menu button')].find((item) => (item.textContent || '').includes('/status')))" );
  const selected = await evaluateAction(session, "select status command", `(() => {
    const option = [...document.querySelectorAll('.command-menu button')].find((item) => (item.textContent || '').includes('/status'));
    if (!option) return false;
    option.click();
    return true;
  })()`);
  if (!selected) throw new Error("/status completion was not available");
  await waitFor(session, "status command selected", "document.querySelector('textarea[aria-label=\"Message UthCode\"], textarea[aria-label=\"发送给 UthCode\"]')?.value.trim() === '/status' && !document.querySelector('.command-menu')");
  await waitFor(session, "status command ready for Send", `(() => {
    const input = document.querySelector('textarea[aria-label="Message UthCode"], textarea[aria-label="发送给 UthCode"]');
    const button = document.querySelector('.composer-send');
    return input?.value.trim() === '/status' && Boolean(button && !button.disabled);
  })()`);
  const submitted = await evaluateAction(session, "execute status command with Send", `(() => {
    const button = document.querySelector('.composer-send');
    if (!button || button.disabled) return false;
    const menuOpen = Boolean(document.querySelector('.command-menu'));
    button.click();
    return { submitted: true, menuOpen };
  })()`);
  if (!submitted?.submitted) throw new Error("/status Send control was not available");
  const expectedNotice = requestedLanguage === "zh-CN" ? "运行时信息" : "Runtime information";
  await waitFor(session, "localized status command output", `Boolean(document.querySelector('.timeline-notice')?.textContent?.includes(${JSON.stringify(expectedNotice)}))`);
  const statusView = await evaluateAction(session, "read typed status projection", `(() => {
    const visible = (element) => {
      if (!element) return false;
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
    };
    const facts = [...document.querySelectorAll('.runtime-facts > div')].map((row) => ({
      label: row.querySelector('dt')?.textContent?.trim() || '',
      value: row.querySelector('dd')?.textContent?.trim() || '',
    }));
    const projectionText = [...document.querySelectorAll('.timeline-notice, .runtime-facts dt, .runtime-facts dd')]
      .filter(visible)
      .map((element) => (element.textContent || '').trim())
      .filter(Boolean)
      .join(' ');
    return {
      notice: document.querySelector('.timeline-notice')?.textContent?.trim() || '',
      noticeCount: document.querySelectorAll('.timeline-notice').length,
      facts,
      projectionText,
    };
  })()`);
  const statusWire = await evaluateAction(session, "read typed status wire identity", `(async () => {
    const value = await window.uthcode.requestRuntime("status.get", {});
    const application = value && typeof value === "object" && value.application && typeof value.application === "object" ? value.application : {};
    return {
      providerProfile: typeof application.provider_profile === "string" ? application.provider_profile : null,
      currentModel: typeof application.current_model === "string" ? application.current_model : null,
    };
  })()`);
  const modelLabel = requestedLanguage === "zh-CN" ? "模型" : "Model";
  const model = statusView.facts.find((item) => item.label === modelLabel)?.value;
  if (statusView.noticeCount !== 1 || statusView.notice !== expectedNotice) throw new Error(`typed /status notice is not a single localized message: ${JSON.stringify(statusView.notice)}`);
  if (model !== "CDP fixture") throw new Error(`typed /status display model was not projected: ${JSON.stringify(model)}`);
  if (statusWire?.providerProfile !== "fixture" || statusWire?.currentModel !== "fixture/fixture-model") throw new Error(`typed /status wire identity was not projected: ${JSON.stringify(statusWire)}`);
  const forbidden = /RuntimeRequestError|EPERM|native|diagnostic|configuration[_ ]?(?:source|path)|file:\/\/|[A-Za-z]:[\\/]/iu;
  if (forbidden.test(statusView.projectionText)) throw new Error(`typed /status exposed a native/free-form/path/diagnostic value: ${statusView.projectionText}`);
  writeLog("assertion_pass", { description: `typed /status shows localized display and safe wire identity (${requestedLanguage})`, value: { notice: statusView.notice, displayModel: model, wire: statusWire, facts: statusView.facts } });
}

async function setInput(session, label, value) {
  remainingBudget(`set input ${label}`);
  writeLog("action", { action: "set_input", label, valueLength: value.length });
  const changed = await evaluateAction(session, `set input ${label}`, `(() => {
    const wanted = ${JSON.stringify(label)};
    const aliases = { "Message UthCode": ["Message UthCode", "发送给 UthCode"] };
    const labels = aliases[wanted] ?? [wanted];
    const element = [...document.querySelectorAll("input,textarea")].find((item) => item.id === wanted || labels.includes(item.getAttribute("aria-label") || ""));
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
  if (!changed) throw new Error(`input id / aria-label not found: ${label}`);
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
    if (normalizedLabelKey === "runtime panel layout") {
      const group = [...document.querySelectorAll('.runtime-layout-controls[role="group"]')].find((item) => normalizedLabels.has((item.getAttribute("aria-label") || "").trim().toLowerCase()));
      const button = [...(group?.querySelectorAll("button") ?? [])].find((item) => labels.has((item.getAttribute("aria-label") || "").trim().toLowerCase()));
      if (!button) return false;
      button.click();
      return true;
    }
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
  // Settings persistence is intentionally fire-and-forget in the renderer.
  // Let each real preference write finish before the next DOM control change;
  // otherwise the packaged Windows profile can receive concurrent atomic
  // renames and report an EPERM that is caused by this driver burst.
  await sleep(300);
}

async function bodyText(session) {
  return evaluateAction(session, "read Renderer body", "document.body?.innerText || \"\"");
}

async function clickButtonContaining(session, text, selector = "button") {
  const aliases = {
    "New chat": ["New chat", "新聊天"],
    "Search Sessions": ["Search Sessions", "搜索会话"],
    Rename: ["Rename", "重命名"],
    Pin: ["Pin", "置顶"],
    Unpin: ["Unpin", "取消置顶"],
    "Archive Session": ["Archive Session", "归档会话"],
    "Restore and open": ["Restore and open", "恢复并打开"],
    "Open Session": ["Open Session", "打开会话"],
  };
  const wanted = aliases[text] ?? [text];
  const clicked = await evaluateAction(session, `click button containing ${text}`, `(() => {
    const wanted = ${JSON.stringify(wanted)};
    const button = [...document.querySelectorAll(${JSON.stringify(selector)})].find((item) => wanted.some((candidate) => (item.textContent || "").includes(candidate)));
    if (!button || button.disabled) return false;
    button.click();
    return true;
  })()`);
  if (!clicked) {
    const observed = await evaluateAction(session, `diagnose button containing ${text}`, `(() => [...document.querySelectorAll(${JSON.stringify(selector)})].map((item) => ({ text: (item.textContent || '').trim(), disabled: Boolean(item.disabled), ariaLabel: item.getAttribute('aria-label'), title: item.getAttribute('title') })))()`);
    throw new Error(`button containing text was not found or was disabled: ${JSON.stringify({ text, wanted, observed })}`);
  }
}

async function switchMode(session, mode) {
  const current = await evaluateAction(session, `read ${mode} mode`, `document.querySelector('.sidebar-brand-menu-trigger')?.dataset.mode`);
  if (current === mode) return;
  const opened = await evaluateAction(session, "open mode menu", `(() => { const button = document.querySelector('.sidebar-brand-menu-trigger'); if (!button) return false; button.click(); return true; })()`);
  if (!opened) throw new Error("mode menu trigger is missing");
  await waitFor(session, "mode menu", "Boolean(document.querySelector('[role=menu]'))");
  await clickButtonContaining(session, mode === "coding" ? "Coding" : "General", "[role=menu] button");
  await waitFor(session, `${mode} mode selected`, `document.querySelector('.sidebar-brand-menu-trigger')?.dataset.mode === ${JSON.stringify(mode)} && document.querySelector('.sidebar')?.getAttribute('aria-label') === ${JSON.stringify(mode === "coding" ? "Projects" : "General")}`);
}

async function startProjectSession(session, alias) {
  const projectState = await evaluateAction(session, `inspect Coding project ${alias}`, `(() => {
    const project = [...document.querySelectorAll('.project-item')].find((item) => item.querySelector('.project-select')?.textContent?.includes(${JSON.stringify(alias)}));
    if (!project) return null;
    const disclosure = project.querySelector('button.disclosure');
    return {
      alias: project.querySelector('.project-select')?.textContent?.trim() || null,
      expanded: disclosure?.getAttribute('aria-expanded') === 'true',
      hasSessionList: Boolean(project.querySelector('.session-list')),
    };
  })()`);
  if (!projectState) {
    const projects = await evaluateAction(session, 'diagnose visible Coding projects', `([...document.querySelectorAll('.project-item')].map((item) => ({ alias: item.querySelector('.project-select')?.textContent?.trim() || null, disclosure: item.querySelector('button.disclosure')?.getAttribute('aria-expanded') || null })))`);
    throw new Error(`registered Coding project was not found: ${alias}; visible projects=${JSON.stringify(projects)}`);
  }
  if (!projectState.expanded || !projectState.hasSessionList) {
    const expanded = await evaluateAction(session, `expand Coding project ${alias}`, `(() => {
      const project = [...document.querySelectorAll('.project-item')].find((item) => item.querySelector('.project-select')?.textContent?.includes(${JSON.stringify(alias)}));
      const disclosure = project?.querySelector('button.disclosure');
      if (!project || !disclosure) return false;
      if (disclosure.getAttribute('aria-expanded') === 'true') return true;
      disclosure.click();
      return true;
    })()`);
    if (!expanded) throw new Error(`Coding project disclosure was not available: ${alias}`);
    await waitFor(session, `expanded Coding project ${alias}`, `(() => {
      const project = [...document.querySelectorAll('.project-item')].find((item) => item.querySelector('.project-select')?.textContent?.includes(${JSON.stringify(alias)}));
      return project?.querySelector('button.disclosure')?.getAttribute('aria-expanded') === 'true' && Boolean(project.querySelector('.session-list'));
    })()`);
  }
  const started = await evaluateAction(session, `start new session in ${alias}`, `(() => {
    const project = [...document.querySelectorAll('.project-item')].find((item) => item.querySelector('.project-select')?.textContent?.includes(${JSON.stringify(alias)}));
    const button = project?.querySelector('button.new-session-line');
    if (!button) return false;
    button.click();
    return true;
  })()`);
  if (!started) throw new Error(`New Session action was unavailable after expanding Coding project ${alias}`);
  await waitFor(session, `new conversation in ${alias}`, "['Session', 'New conversation', '会话', '新对话'].some((value) => document.querySelector('h1')?.textContent?.includes(value))");
  await waitFor(session, `selected project ${alias}`, `document.querySelector('.project-item.is-active .project-select')?.textContent?.includes(${JSON.stringify(alias)})`);
  await waitFor(session, `selected draft Session row in ${alias}`, `(() => {
    const project = [...document.querySelectorAll('.project-item')].find((item) => item.querySelector('.project-select')?.textContent?.includes(${JSON.stringify(alias)}));
    const row = project?.querySelector('button.session-line.is-selected:not(.new-session-line)');
    return Boolean(row?.getAttribute('aria-label')?.includes(${JSON.stringify(alias)}));
  })()`);
  const owner = await waitForStableObservation(session, `selected Session and public Runtime owner ready in ${alias}`, `(async () => {
    const project = [...document.querySelectorAll('.project-item')].find((item) => item.querySelector('.project-select')?.textContent?.includes(${JSON.stringify(alias)}));
    const row = project?.querySelector('button.session-line.is-selected:not(.new-session-line)');
    const label = row?.getAttribute('aria-label') || '';
    const sessionId = label.split(' · ')[1] || null;
    const input = document.querySelector('.composer textarea');
    const composerReady = Boolean(input && !input.disabled);
    const mode = document.querySelector('.sidebar-brand-menu-trigger')?.dataset.mode || null;
    const status = row && sessionId ? await window.uthcode.requestRuntime('status.get', {}) : null;
    const observation = {
      sessionId,
      selectedSession: label || null,
      publicSessionId: status?.session_id ?? null,
      runtimeState: status?.runtime?.state ?? null,
      activeTurn: status?.active_turn ?? null,
      sessionStatus: status?.session_state?.status ?? null,
      composerReady,
      mode,
    };
    observation.ready = Boolean(row && sessionId && composerReady && mode === 'coding'
      && status?.session_id === sessionId
      && status?.active_turn === false
      && status?.session_state?.status === 'idle'
      && status?.runtime?.state === 'ready');
    return observation;
  })()`);
  flowEvidence.lifecycleSessionOwners ??= [];
  flowEvidence.lifecycleSessionOwners.push(owner);
}

async function lifecycleTimeoutDiagnostic(session, prompt) {
  const previousDeadline = flowDeadline;
  // Preserve a small independent diagnostic window after the user-visible
  // flow deadline. The main acceptance remains bounded by timeoutMs; this
  // tail only reads the public UI/Runtime state and captures the failure.
  flowDeadline = Math.max(flowDeadline, Date.now() + 8_000);
  let evidence;
  try {
    evidence = await session.evaluate(`(async () => {
    const input = document.querySelector('textarea[aria-label="Message UthCode"], textarea[aria-label="发送给 UthCode"]');
    const timeline = document.querySelector('[aria-label="Chat timeline"]');
    const row = document.querySelector('button.session-line.is-selected:not(.new-session-line), button.recent-line.is-selected');
    const runtime = document.querySelector('#runtime-panel');
    let publicStatus = null;
    let publicStatusError = null;
    try { publicStatus = await window.uthcode?.requestRuntime('status.get', {}); }
    catch (error) { publicStatusError = String(error?.message || error); }
    const alerts = [...document.querySelectorAll('[role="alert"]')].map((item) => (item.innerText || '').trim().slice(0, 180));
    const assistant = [...document.querySelectorAll('.timeline-entry--assistant .timeline-content')].map((item) => (item.innerText || '').trim().slice(0, 180));
    const monitor = window.__t12LifecycleEventMonitor;
    monitor?.unsubscribe?.();
    delete window.__t12LifecycleEventMonitor;
    return {
      promptVisible: Boolean(timeline?.innerText?.includes(${JSON.stringify(prompt)})),
      composerValueLength: input?.value?.length ?? null,
      composerDisabled: Boolean(input?.disabled || input?.closest('.composer')?.getAttribute('aria-disabled') === 'true'),
      selectedSession: row?.getAttribute('aria-label') || null,
      selectedSessionId: row?.getAttribute('aria-label')?.split(' · ')[1] || null,
      mode: document.querySelector('.sidebar-brand-menu-trigger')?.dataset.mode || null,
      runtimeText: (runtime?.innerText || '').trim().slice(0, 240),
      publicStatus: publicStatus ? {
        sessionId: publicStatus.session_id ?? null,
        sessionStatus: publicStatus.session_state?.status ?? null,
        activeTurn: publicStatus.active_turn ?? null,
        runtimeState: publicStatus.runtime?.state ?? null,
      } : null,
      publicStatusError,
      alerts,
      assistant,
      cancelControlVisible: Boolean(document.querySelector('button[aria-label="Cancel"]')),
      permissionSurfaceVisible: Boolean(document.querySelector('[aria-label="Interaction surface"]')),
      eventTypes: monitor?.eventTypes ?? [],
      terminalEvents: monitor?.terminalEvents ?? [],
      sendProbeClickCount: window.__t12ComposerSendProbe?.clickCount ?? null,
      sendButtons: [...document.querySelectorAll('.composer-send')].map((button) => {
        const rect = button.getBoundingClientRect();
        const style = getComputedStyle(button);
        return { disabled: button.disabled, text: (button.innerText || '').trim(), aria: button.getAttribute('aria-label'), display: style.display, visibility: style.visibility, rect: rect.toJSON() };
      }),
    };
  })()`);
  } catch (error) {
    evidence = { diagnosticFailure: error instanceof Error ? error.message : String(error) };
  }
  flowEvidence.lifecycleTimeoutDiagnostic = { prompt, ...evidence };
  try {
    await capture(session, "lifecycle-provider-timeout");
  } catch (error) {
    flowEvidence.lifecycleTimeoutDiagnostic.screenshotFailure = error instanceof Error ? error.message : String(error);
  } finally {
    flowDeadline = previousDeadline;
  }
  writeLog("acceptance_diagnostic", { description: "lifecycle provider response timed out", evidence: flowEvidence.lifecycleTimeoutDiagnostic });
  return evidence;
}

async function waitForGeneralDraftReady(session) {
  const owner = await waitForStableObservation(session, "General New chat and public Runtime owner ready", `(async () => {
    const mode = document.querySelector('.sidebar-brand-menu-trigger')?.dataset.mode || null;
    const sidebar = document.querySelector('.sidebar')?.getAttribute('aria-label') || null;
    const input = document.querySelector('.composer textarea');
    const composerReady = Boolean(input && !input.disabled && input.closest('.composer')?.getAttribute('aria-disabled') !== 'true');
    const row = document.querySelector('button.session-line.is-selected:not(.new-session-line), button.recent-line.is-selected');
    const selectedSession = row?.getAttribute('aria-label') || null;
    const selectedSessionId = selectedSession?.split(' · ')[1] || null;
    const status = await window.uthcode.requestRuntime('status.get', {});
    const observation = {
      mode,
      sidebar,
      selectedSession,
      selectedSessionId,
      publicSessionId: status?.session_id ?? null,
      runtimeState: status?.runtime?.state ?? null,
      activeTurn: status?.active_turn ?? null,
      sessionStatus: status?.session_state?.status ?? null,
      composerReady,
    };
    observation.ready = mode === 'general'
      && sidebar === 'General'
      && composerReady
      && status?.runtime?.state === 'ready'
      && status?.active_turn === false
      && (!selectedSessionId || !status?.session_id || selectedSessionId === status.session_id);
    return observation;
  })()`);
  return owner;
}

async function waitForLifecycleSessionOwner(session, description, { sessionId, projectAlias, prompt }) {
  return waitForStableObservation(session, description, `(async () => {
    const row = document.querySelector('button.session-line.is-selected:not(.new-session-line), button.recent-line.is-selected');
    const label = row?.getAttribute('aria-label') || null;
    const selectedSessionId = label?.split(' · ')[1] || null;
    const selectedProject = document.querySelector('.project-item.is-active .project-select')?.textContent?.trim() || null;
    const mode = document.querySelector('.sidebar-brand-menu-trigger')?.dataset.mode || null;
    const status = await window.uthcode.requestRuntime('status.get', {});
    const sidebarBusy = document.querySelector('.sidebar')?.getAttribute('aria-busy') || null;
    const cancelVisible = Boolean(document.querySelector('button[aria-label="Cancel"], button[aria-label="取消"]'));
    const timelineText = document.querySelector('[aria-label="Chat timeline"]')?.innerText || '';
    const observation = {
      selectedSession: label,
      selectedSessionId,
      selectedProject,
      mode,
      publicSessionId: status?.session_id ?? null,
      runtimeState: status?.runtime?.state ?? null,
      activeTurn: status?.active_turn ?? null,
      sessionStatus: status?.session_state?.status ?? null,
      sidebarBusy,
      cancelVisible,
      promptVisible: timelineText.includes(${JSON.stringify(prompt)}),
    };
    observation.ready = selectedSessionId === ${JSON.stringify(sessionId)}
      && (!${JSON.stringify(projectAlias)} || selectedProject === ${JSON.stringify(projectAlias)})
      && mode === 'coding'
      && status?.session_id === ${JSON.stringify(sessionId)}
      && status?.runtime?.state === 'ready'
      && status?.active_turn === false
      && ['idle', 'completed'].includes(status?.session_state?.status)
      && sidebarBusy !== 'true'
      && !cancelVisible
      && observation.promptVisible;
    return observation;
  })()`);
}

async function submitLifecyclePrompt(session, prompt, response = expectedText) {
  await session.evaluate(`(() => {
    window.__t12LifecycleEventMonitor?.unsubscribe?.();
    const eventTypes = [];
    const terminalEvents = [];
    const terminalTypes = new Set(['turn_completed', 'turn_failed', 'turn_cancelled']);
    const unsubscribe = window.uthcode?.subscribeAgentEvents?.((event) => {
      if (typeof event?.type !== 'string') return;
      eventTypes.push(event.type);
      if (terminalTypes.has(event.type)) terminalEvents.push({
        type: event.type,
        runId: typeof event.run_id === 'string' ? event.run_id : null,
        turnId: typeof event.turn_id === 'string' ? event.turn_id : null,
        sessionId: typeof event.session_id === 'string' ? event.session_id : null,
        projectKey: typeof event.project_key === 'string' ? event.project_key : null,
        terminationReason: typeof event.termination_reason === 'string' ? event.termination_reason : null,
        failureReason: typeof event.failure_reason === 'string' ? event.failure_reason : null,
      });
    }) || null;
    window.__t12LifecycleEventMonitor = { eventTypes, terminalEvents, unsubscribe };
    return Boolean(unsubscribe);
  })()`);
  await setInput(session, "Message UthCode", prompt);
  await waitFor(session, "lifecycle message ready", "(() => { const input = document.querySelector('textarea[aria-label=\"Message UthCode\"], textarea[aria-label=\"发送给 UthCode\"]'); const button = document.querySelector('.composer-actions button:last-child'); return Boolean(input?.value.trim()) && Boolean(button && !button.disabled); })()");
  await clickSelector(session, ".composer-send");
  let sendState;
  try {
    sendState = await waitFor(session, "lifecycle Send acknowledgment", `(() => {
      const input = document.querySelector('textarea[aria-label="Message UthCode"], textarea[aria-label="发送给 UthCode"]');
      const promptVisible = Boolean(document.querySelector('[aria-label="Chat timeline"]')?.innerText?.includes(${JSON.stringify(prompt)}));
      const cancelControlVisible = Boolean(document.querySelector('button[aria-label="Cancel"], button[aria-label="取消"]'));
      const sendButtons = [...document.querySelectorAll('.composer-send')].map((button) => ({ disabled: button.disabled, text: (button.innerText || '').trim(), aria: button.getAttribute('aria-label') }));
      const composerValueLength = input?.value?.length ?? null;
      if (!promptVisible && composerValueLength !== 0 && !cancelControlVisible && !sendButtons.some((button) => button.disabled)) return false;
      return { promptVisible, composerValueLength, cancelControlVisible, sendProbeClickCount: window.__t12ComposerSendProbe?.clickCount ?? null, sendButtons };
    })()`);
  } catch (error) {
    const diagnostic = await lifecycleTimeoutDiagnostic(session, prompt);
    throw new Error(`${error instanceof Error ? error.message : String(error)}; lifecycle Send acknowledgment state=${JSON.stringify(diagnostic)}`);
  }
  try {
    await waitFor(session, `lifecycle response for ${prompt}`, `(() => { const text = document.querySelector('[aria-label=\"Chat timeline\"]')?.innerText || ''; return text.includes(${JSON.stringify(prompt)}) && text.includes(${JSON.stringify(response)}); })()`);
  } catch (error) {
    const diagnostic = await lifecycleTimeoutDiagnostic(session, prompt);
    throw new Error(`${error instanceof Error ? error.message : String(error)}; lifecycle send state=${JSON.stringify({ sendState, diagnostic })}`);
  }
  await waitFor(session, `persistent Session for ${prompt}`, "Boolean(document.querySelector('button.session-line.is-selected:not(.new-session-line), button.recent-line.is-selected'))");
  const terminal = await waitFor(session, `terminal AgentEvent for ${prompt}`, `(() => {
    const events = window.__t12LifecycleEventMonitor?.terminalEvents || [];
    return events.find((event) => ['turn_completed', 'turn_failed', 'turn_cancelled'].includes(event.type)) || false;
  })()`);
  if (terminal.type !== 'turn_completed') throw new Error(`lifecycle Turn ended without successful completion: ${JSON.stringify(terminal)}`);
  const identity = await selectedSessionIdentity(session);
  const terminalStatus = await waitForStableObservation(session, `public Runtime confirms terminal idle for ${prompt}`, `(async () => {
    const status = await window.uthcode.requestRuntime('status.get', {});
    const cancelVisible = Boolean(document.querySelector('button[aria-label="Cancel"], button[aria-label="取消"]'));
    const sessionStatus = status?.session_state?.status ?? null;
    const runtimeState = status?.runtime?.state ?? null;
    const ready = status?.active_turn === false
      && ['idle', 'completed'].includes(sessionStatus)
      && status?.session_id === ${JSON.stringify(identity?.id)}
      && runtimeState === 'ready'
      && !cancelVisible;
    return { ready, activeTurn: status?.active_turn ?? null, sessionStatus, sessionId: status?.session_id ?? null, runtimeState, cancelVisible };
  })()`);
  flowEvidence.lifecycleTurns ??= [];
  flowEvidence.lifecycleTurns.push({ prompt, selectedSessionId: identity?.id ?? null, terminal, terminalStatus });
  await session.evaluate("window.__t12LifecycleEventMonitor?.unsubscribe?.(); delete window.__t12LifecycleEventMonitor;");
}

async function selectedSessionIdentity(session) {
  return evaluateAction(session, "read selected Session identity", `(() => {
    const row = document.querySelector('button.session-line.is-selected:not(.new-session-line), button.recent-line.is-selected');
    return row ? { label: row.getAttribute('aria-label'), text: row.innerText, id: row.getAttribute('aria-label')?.split(' · ')[1] || null } : null;
  })()`);
}

async function mutateSelectedSession(session, actionText) {
  const opened = await evaluateAction(session, "open selected Session menu", `(() => {
    const row = document.querySelector('button.session-line.is-selected:not(.new-session-line), button.recent-line.is-selected');
    const trigger = row?.closest('.session-menu-anchor')?.querySelector('.session-menu-trigger');
    if (!trigger) return false;
    trigger.click();
    return true;
  })()`);
  if (!opened) throw new Error("selected Session menu trigger was not found");
  await waitFor(session, "selected Session menu", "Boolean(document.querySelector('[role=menu]'))");
  const actionAliases = {
    Rename: ["Rename", "重命名"],
    Pin: ["Pin", "置顶"],
    Unpin: ["Unpin", "取消置顶"],
    "Archive Session": ["Archive Session", "归档会话"],
  };
  const actionLabels = actionAliases[actionText] ?? [actionText];
  await waitFor(session, `enabled ${actionText} Session action`, `(() => {
    const labels = ${JSON.stringify(actionLabels)};
    return [...document.querySelectorAll('[role=menu] button')].some((item) => !item.disabled && labels.some((label) => (item.textContent || '').includes(label)));
  })()`);
  if (actionText === "Pin") {
    const clickEvidence = await evaluateAction(session, "deliver real Pin Session menu click", `(() => {
      const labels = ${JSON.stringify(actionAliases.Pin)};
      const button = [...document.querySelectorAll('[role=menu] button')].find((item) => labels.some((label) => (item.textContent || '').trim() === label));
      if (!button || button.disabled) return { clicked: false, text: button?.textContent?.trim() || null, ariaLabel: button?.getAttribute('aria-label') || null };
      window.__t12PinActionProbe = { clickCount: 0 };
      button.addEventListener('click', () => { window.__t12PinActionProbe.clickCount += 1; }, { capture: true, once: true });
      const evidence = { clicked: true, text: button.textContent.trim(), ariaLabel: button.getAttribute('aria-label'), disabled: button.disabled };
      button.click();
      evidence.clickCount = window.__t12PinActionProbe.clickCount;
      return evidence;
    })()`);
    if (!clickEvidence?.clicked || clickEvidence.clickCount !== 1) throw new Error(`real Pin menu click was not delivered: ${JSON.stringify(clickEvidence)}`);
    flowEvidence.lifecyclePinAction = clickEvidence;
    return clickEvidence;
  }
  await clickButtonContaining(session, actionText, "[role=menu] button");
}

async function renameSelectedSession(session, title) {
  await mutateSelectedSession(session, "Rename");
  await waitFor(session, "Session title input", "Boolean(document.querySelector('input.session-title-input'))");
  const changed = await evaluateAction(session, "set Session title", `(() => {
    const input = document.querySelector('input.session-title-input');
    if (!input) return false;
    input.focus();
    const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(input), 'value')?.set;
    if (setter) setter.call(input, ${JSON.stringify(title)}); else input.value = ${JSON.stringify(title)};
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true }));
    return true;
  })()`);
  if (!changed) throw new Error("Session title input disappeared");
  await waitFor(session, "renamed Session title", `document.querySelector('button.session-line.is-selected:not(.new-session-line), button.recent-line.is-selected')?.textContent?.includes(${JSON.stringify(title)})`);
  const settled = await waitForStableObservation(session, "Session rename mutation settled", `(() => {
    const sidebar = document.querySelector('.sidebar');
    const selected = document.querySelector('button.session-line.is-selected:not(.new-session-line), button.recent-line.is-selected');
    const observation = {
      sidebarBusy: sidebar?.getAttribute('aria-busy') || null,
      selectedSession: selected?.getAttribute('aria-label') || null,
      selectedText: selected?.innerText?.trim() || null,
    };
    observation.ready = observation.sidebarBusy !== 'true' && Boolean(selected?.textContent?.includes(${JSON.stringify(title)}));
    return observation;
  })()`);
  flowEvidence.lifecycleRenameSettlements ??= [];
  flowEvidence.lifecycleRenameSettlements.push(settled);
}

async function setSelectedSessionPin(session) {
  const before = await evaluateAction(session, "read pinned Session preference before Pin", "window.uthcode.readPreference('pinnedSessions')");
  const click = await mutateSelectedSession(session, "Pin");
  const identity = await selectedSessionIdentity(session);
  const sessionId = identity?.id;
  if (!sessionId) throw new Error("selected Session identity was unavailable after Pin");
  const persisted = await waitForStableObservationWithin(session, "Session pin persisted through the real UI", `(async () => {
    const preferences = await window.uthcode.readPreference('pinnedSessions');
    const pins = Array.isArray(preferences) ? preferences : [];
    const selected = document.querySelector('button.session-line.is-selected:not(.new-session-line), button.recent-line.is-selected');
    const notices = [...document.querySelectorAll('[role="alert"], [role="status"]')].map((item) => (item.innerText || '').trim().slice(0, 160));
    return {
      ready: pins.some((entry) => entry?.sessionId === ${JSON.stringify(sessionId)}),
      sessionId: ${JSON.stringify(sessionId)},
      pins,
      selectedLabel: selected?.getAttribute('aria-label') || null,
      selectedText: selected?.innerText?.trim() || null,
      menuOpen: Boolean(document.querySelector('[role=menu]')),
      notices,
    };
  })()`);
  flowEvidence.lifecyclePin = { sessionId, before: Array.isArray(before) ? before : null, click, persisted };
  return persisted;
}

async function openSessionSearch(session, query) {
  const alreadyOpen = await evaluateAction(session, "check Session search dialog", "Boolean(document.querySelector('[role=dialog][aria-label=\"Search Sessions\"], [role=dialog][aria-label=\"搜索会话\"]'))");
  if (!alreadyOpen) await clickButtonContaining(session, "Search Sessions", ".sidebar-primary button");
  await waitFor(session, "Session search dialog", "Boolean(document.querySelector('[role=dialog][aria-label=\"Search Sessions\"], [role=dialog][aria-label=\"搜索会话\"]'))");
  const changed = await evaluateAction(session, "set Session search query", `(() => {
    const input = document.querySelector('[role=dialog] input[aria-label=\"Search Session titles or content\"], [role=dialog] input[aria-label=\"搜索会话标题或内容\"]');
    if (!input) return false;
    input.focus();
    const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(input), 'value')?.set;
    if (setter) setter.call(input, ${JSON.stringify(query)}); else input.value = ${JSON.stringify(query)};
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
    const form = input.closest('form');
    if (!form) return false;
    form.requestSubmit();
    return true;
  })()`);
  if (!changed) throw new Error("Session search input or form was not found");
  await waitFor(session, `Session search results for ${query}`, "document.querySelectorAll('[role=dialog] ul > li').length > 0");
  return evaluateAction(session, "read Session search results", `(() => [...document.querySelectorAll('[role=dialog] ul > li')].map((item) => ({ title: item.querySelector('strong')?.textContent?.trim() || '', owner: item.querySelector('small')?.textContent?.trim() || '', snippet: item.querySelector('p')?.textContent?.trim() || '', action: item.querySelector('button')?.textContent?.trim() || '', archived: /Archived|已归档/u.test(item.querySelector('small')?.textContent || '') })))()`);
}

async function openSearchHit(session, predicate, actionLabel) {
  const opened = await evaluateAction(session, `open ${actionLabel} Search result`, `(() => {
    const hit = [...document.querySelectorAll('[role=dialog] ul > li')].find((item) => ${predicate});
    const button = hit?.querySelector('button');
    if (!button || button.disabled || !button.textContent?.includes(${JSON.stringify(actionLabel)})) return false;
    button.click();
    return true;
  })()`);
  if (!opened) throw new Error(`matching Search result action not found: ${actionLabel}`);
}

async function runLifecycleFlow(session) {
  if (!projectOne || !projectTwo || !lifecycleStage) throw new Error("lifecycle requires --stage, --project-one, and --project-two");
  const title = "T12 Shared Session";
  const onePrompt = "T12_CODING_ONE_CONTENT";
  const twoPrompt = "T12_CODING_TWO_CONTENT";
  const generalPrompt = "T12_GENERAL_CONTENT";
  if (lifecycleStage === "seed") {
    await switchMode(session, "coding");
    await startProjectSession(session, "T12 Coding One");
    await submitLifecyclePrompt(session, onePrompt);
    await renameSelectedSession(session, title);
    const one = await selectedSessionIdentity(session);

    await startProjectSession(session, "T12 Coding Two");
    await submitLifecyclePrompt(session, twoPrompt);
    await renameSelectedSession(session, title);
    const two = await selectedSessionIdentity(session);
    const pin = await setSelectedSessionPin(session);

    await switchMode(session, "general");
    const generalUi = await evaluateAction(session, "verify General mode has no project selection", `({ mode: document.querySelector('.sidebar-brand-menu-trigger')?.dataset.mode, sidebar: document.querySelector('.sidebar')?.getAttribute('aria-label'), projectButtons: document.querySelectorAll('.project-select').length })`);
    if (generalUi.mode !== "general" || generalUi.sidebar !== "General" || generalUi.projectButtons !== 0) throw new Error(`General UI exposed a Coding project selection: ${JSON.stringify(generalUi)}`);
    await clickButtonContaining(session, "New chat", ".sidebar-primary button");
    await waitFor(session, "new General conversation header", "['Session', 'New conversation', '会话', '新对话'].some((value) => document.querySelector('h1')?.textContent?.includes(value))");
    const generalOwner = await waitForGeneralDraftReady(session);
    await submitLifecyclePrompt(session, generalPrompt);
    const general = await selectedSessionIdentity(session);
    await capture(session, "lifecycle-general-created");

    await switchMode(session, "coding");
    const hits = await openSessionSearch(session, title);
    const oneHit = hits.find((hit) => hit.owner.includes("T12 Coding One"));
    const twoHit = hits.find((hit) => hit.owner.includes("T12 Coding Two"));
    if (hits.length !== 2 || !oneHit || !twoHit || hits.some((hit) => hit.title !== title || hit.archived)) throw new Error(`same-title Coding Session search did not return both owners: ${JSON.stringify(hits)}`);
    await openSearchHit(session, `item.querySelector('small')?.textContent?.includes('T12 Coding Two')`, "Open Session");
    const openedForArchive = await waitForLifecycleSessionOwner(session, "second Coding Session selected owner ready before archive", { sessionId: two.id, projectAlias: "T12 Coding Two", prompt: twoPrompt });
    await mutateSelectedSession(session, "Archive Session");
    const archived = await waitForStableObservationWithin(session, "second Coding Session archived through the UI", `(async () => {
      const matchingRows = [...document.querySelectorAll('button.session-line:not(.new-session-line), button.recent-line')]
        .filter((item) => item.getAttribute('aria-label')?.includes(${JSON.stringify(two.id)}));
      const preferences = await window.uthcode.readPreference('pinnedSessions');
      const pins = Array.isArray(preferences) ? preferences : [];
      const observation = {
        sessionId: ${JSON.stringify(two.id)},
        remainingVisibleRows: matchingRows.map((item) => ({ label: item.getAttribute('aria-label'), text: item.innerText?.trim() || null })),
        sidebarBusy: document.querySelector('.sidebar')?.getAttribute('aria-busy') || null,
        stillPinned: pins.some((entry) => entry?.sessionId === ${JSON.stringify(two.id)}),
        notices: [...document.querySelectorAll('[role="alert"], [role="status"]')].map((item) => (item.innerText || '').trim().slice(0, 160)),
      };
      observation.ready = matchingRows.length === 0 && observation.sidebarBusy !== 'true' && observation.stillPinned;
      return observation;
    })()`, 20_000);
    flowEvidence.lifecycle = { stage: "seed", title, projectOne: "T12 Coding One", projectTwo: "T12 Coding Two", sessions: { one, two, general }, generalOwner, pinned: pin.sessionId, searchBeforeArchive: hits, generalUi, openedForArchive, archived };
    await capture(session, "lifecycle-after-archive");
  } else if (lifecycleStage === "restore") {
    const expected = expectedSessions ? JSON.parse(expectedSessions) : null;
    await switchMode(session, "general");
    const generalUi = await evaluateAction(session, "verify General mode after restart", `({ mode: document.querySelector('.sidebar-brand-menu-trigger')?.dataset.mode, sidebar: document.querySelector('.sidebar')?.getAttribute('aria-label'), projectButtons: document.querySelectorAll('.project-select').length, recent: [...document.querySelectorAll('button.recent-line')].map((item) => ({ label: item.getAttribute('aria-label'), text: item.textContent })) })`);
    if (generalUi.mode !== "general" || generalUi.sidebar !== "General" || generalUi.projectButtons !== 0 || !generalUi.recent.some((item) => item.text.includes(generalPrompt))) throw new Error(`General owner or recent activity was not restored: ${JSON.stringify(generalUi)}`);
    const generalHits = await openSessionSearch(session, generalPrompt);
    if (generalHits.length !== 1 || !generalHits[0].owner.includes("General") || !generalHits[0].snippet.includes(generalPrompt)) throw new Error(`General search did not remain isolated to its Session: ${JSON.stringify(generalHits)}`);
    await openSearchHit(session, `item.querySelector('small')?.textContent?.includes('General')`, "Open Session");
    await waitFor(session, "General Session content after restart", `document.querySelector('[aria-label=\"Chat timeline\"]')?.innerText?.includes(${JSON.stringify(generalPrompt)})`);
    const generalIdentity = await selectedSessionIdentity(session);
    if (expected?.general?.id && generalIdentity?.id !== expected.general.id) throw new Error(`General Session identity changed across restart: ${JSON.stringify({ expected: expected.general.id, observed: generalIdentity })}`);
    await switchMode(session, "coding");
    const activeHits = await openSessionSearch(session, title);
    const activeOne = activeHits.find((hit) => hit.owner.includes("T12 Coding One") && !hit.archived);
    const archivedTwo = activeHits.find((hit) => hit.owner.includes("T12 Coding Two") && hit.archived);
    if (activeHits.length !== 2 || !activeOne || !archivedTwo || activeHits.some((hit) => hit.title !== title)) throw new Error(`Coding Session owner/title/archive search state changed across restart: ${JSON.stringify(activeHits)}`);
    await openSearchHit(session, `item.querySelector('small')?.textContent?.includes('T12 Coding Two') && /Archived|已归档/u.test(item.querySelector('small')?.textContent || '')`, "Restore and open");
    await waitFor(session, "restored Coding Session content", `document.querySelector('[aria-label=\"Chat timeline\"]')?.innerText?.includes(${JSON.stringify(twoPrompt)})`);
    if (!expected?.two?.id) throw new Error("lifecycle restore is missing the seeded Coding Session identity");
    await waitForLifecycleSessionOwner(session, "restored Coding Session owner ready", { sessionId: expected.two.id, projectAlias: "T12 Coding Two", prompt: twoPrompt });
    const restored = await selectedSessionIdentity(session);
    if (!restored?.id || (expected?.two?.id && restored.id !== expected.two.id) || !restored.label?.includes("T12 Coding Two")) throw new Error(`restored Session owner or id changed: ${JSON.stringify({ expected: expected?.two?.id ?? null, restored })}`);
    const pins = await evaluateAction(session, "verify restored Session pin preference", `window.uthcode.readPreference('pinnedSessions')`);
    if (!Array.isArray(pins) || !pins.some((entry) => entry?.sessionId === restored.id)) throw new Error(`restored Session lost its pin: ${JSON.stringify({ restored: restored.id, pins })}`);
    const recentOrder = await evaluateAction(session, "verify restored Coding user activity order", `(() => [...document.querySelectorAll('.recent button.recent-line')].map((item) => item.getAttribute('aria-label') || item.textContent || ''))()`);
    const twoIndex = recentOrder.findIndex((label) => label.includes(restored.id));
    const oneId = expected?.one?.id;
    const oneIndex = oneId ? recentOrder.findIndex((label) => label.includes(oneId)) : -1;
    if (twoIndex < 0 || (oneIndex >= 0 && twoIndex >= oneIndex)) throw new Error(`restored Session did not retain newer user-activity order: ${JSON.stringify(recentOrder)}`);
    const finalHits = await openSessionSearch(session, title);
    if (finalHits.length !== 2 || finalHits.some((hit) => hit.archived || hit.title !== title) || !finalHits.some((hit) => hit.owner.includes("T12 Coding One")) || !finalHits.some((hit) => hit.owner.includes("T12 Coding Two"))) throw new Error(`restored title/owner state did not return to active Coding search: ${JSON.stringify(finalHits)}`);
    await openSearchHit(session, `item.querySelector('small')?.textContent?.includes('T12 Coding Two')`, "Open Session");
    await waitFor(session, "reopened restored Session content", `document.querySelector('[aria-label=\"Chat timeline\"]')?.innerText?.includes(${JSON.stringify(twoPrompt)})`);
    await capture(session, "lifecycle-restored-after-restart");
    flowEvidence.lifecycle = { stage: "restore", title, activeSearchAfterRestore: finalHits, generalSearch: generalHits, generalUi, restored, pinnedSessionId: restored.id, recentOrder, expectedSessions: expected };
  } else {
    throw new Error(`unsupported lifecycle stage: ${lifecycleStage}`);
  }
  if (!skipQuit) await evaluateAction(session, "close UthCode shell", "window.uthcode.closeShell()");
  writeLog("assertion_pass", { description: `packaged Session lifecycle stage ${lifecycleStage} completed through real UI` });
}

async function verifyComposerRightAlignment(session, label) {
  const observed = await waitForStableObservationWithin(session, label, `(() => {
    const toolbar = document.querySelector('.composer-toolbar')?.getBoundingClientRect();
    const model = document.querySelector('.composer-model')?.getBoundingClientRect();
    const selector = document.querySelector('.composer-model .custom-select')?.getBoundingClientRect();
    const context = document.querySelector('.composer-model .context-ring')?.getBoundingClientRect();
    const send = document.querySelector('.composer-send')?.getBoundingClientRect();
    return { ready: Boolean(toolbar?.width && model?.width && selector?.width && send?.width), toolbarRight: toolbar?.right, modelLeft: model?.left, modelRight: model?.right, selectorRight: selector?.right, contextLeft: context?.left ?? null, contextRight: context?.right ?? null, sendLeft: send?.left, sendRight: send?.right };
  })()`, 3_000);
  if (Math.abs(observed.toolbarRight - observed.sendRight) > 1 || observed.modelRight > observed.sendLeft + 1 || (observed.contextLeft !== null && (observed.selectorRight > observed.contextLeft + 1 || observed.contextRight > observed.modelRight + 1))) throw new Error(`Composer right controls were not aligned: ${JSON.stringify(observed)}`);
  return observed;
}

async function verifyEmptyComposer(session) {
  await waitFor(session, "empty Composer ready", "document.querySelector('.composer textarea')?.value === '' && !document.querySelector('.settings-view')");
  const observations = [];
  for (const width of [1280, 900, 720]) {
    await session.send("Emulation.setDeviceMetricsOverride", { width, height: 900, deviceScaleFactor: 1, mobile: false });
    const observed = await waitForStableObservationWithin(session, "stable empty Composer " + width, `(() => {
      const composer = document.querySelector('.composer');
      const input = composer?.querySelector('textarea');
      const selectors = [...(composer?.querySelectorAll('.custom-select') || [])];
      const rect = composer?.getBoundingClientRect();
      const style = composer ? getComputedStyle(composer) : null;
      const verticalPadding = style ? parseFloat(style.paddingTop) + parseFloat(style.paddingBottom) : 0;
      const contentWidth = composer ? composer.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight) : 0;
      const visibleLabels = selectors.filter((node) => { const value = node.querySelector('.custom-select__value'); return value && getComputedStyle(value).display !== 'none' && value.getBoundingClientRect().width > 0; }).length;
      return { ready: Boolean(input && input.value === '' && rect?.height), width: innerWidth, contentWidth, visibleLabels, height: rect?.height, verticalPadding, contentHeight: rect ? rect.height - verticalPadding : null, inputHeight: input?.getBoundingClientRect().height, resize: input ? getComputedStyle(input).resize : null, iconSelectors: selectors.filter((node) => node.querySelector('.custom-select__trigger > svg')).length };
    })()`, 3_000);
    if (observed.resize !== "none" || observed.iconSelectors !== 2 || observed.visibleLabels !== (observed.contentWidth >= 600 ? 2 : 0)) throw new Error(`empty Composer responsive controls were incorrect: ${JSON.stringify(observed)}`);
    observed.rightAlignment = await verifyComposerRightAlignment(session, "empty Composer right alignment " + width);
    observations.push(observed);
    await capture(session, "empty-composer-" + width);
  }
  if (Math.max(...observations.map((item) => item.height)) - Math.min(...observations.map((item) => item.height)) > 1) throw new Error(`empty Composer height changed across widths: ${JSON.stringify(observations)}`);
  await session.send("Emulation.clearDeviceMetricsOverride");
  await setSelect(session, "Runtime panel layout", "hidden");
  const wideSend = await waitForStableObservationWithin(session, "wide empty Composer Send fits visible text", `(() => {
    const button = document.querySelector('.composer-send');
    const label = button?.querySelector('.composer-send__label');
    const icon = button?.querySelector('svg');
    const rect = button?.getBoundingClientRect();
    const labelRect = label?.getBoundingClientRect();
    const iconRect = icon?.getBoundingClientRect();
    const visible = label && getComputedStyle(label).display !== 'none';
    return { ready: document.querySelector('.app-shell')?.classList.contains('panel-hidden') && Boolean(button && label && icon), labelVisible: Boolean(visible), buttonWidth: rect?.width, labelWidth: labelRect?.width, iconWidth: iconRect?.width, fits: Boolean(rect && labelRect && iconRect && (!visible || (labelRect.left >= rect.left && labelRect.right <= rect.right && iconRect.left >= rect.left && iconRect.right <= rect.right && iconRect.right <= labelRect.left))) };
  })()`, 3_000);
  if (!wideSend.labelVisible || !wideSend.fits) throw new Error(`wide empty Send label did not fit: ${JSON.stringify(wideSend)}`);
  const wideAlignment = await verifyComposerRightAlignment(session, "wide empty Composer right alignment");
  await capture(session, "empty-composer-wide-visible-send");
  const wideSelectors = await evaluateAction(session, "wide Composer exposes complete selected labels", `(() => {
    const nodes = [...document.querySelectorAll('.composer .custom-select__value')];
    return { count: nodes.length, labels: nodes.map((node) => ({ text: node.textContent, visible: getComputedStyle(node).display !== 'none', fits: node.scrollWidth <= node.clientWidth + 1 })) };
  })()`);
  const wideLabelsComplete = wideSelectors.count === 2 && wideSelectors.labels.every((item) => item.visible && item.fits) && wideSelectors.labels.some((item) => item.text === 'qwen3.7-flash-openai-responses');
  await setInput(session, "Message UthCode", "Responsive draft");
  await waitFor(session, "filled wide Composer retains complete selected labels", "[...document.querySelectorAll('.composer .custom-select__value')].every((node) => getComputedStyle(node).display !== 'none' && node.scrollWidth <= node.clientWidth + 1)");
  const filledWideAlignment = await verifyComposerRightAlignment(session, "filled wide Composer right alignment");
  await capture(session, "filled-composer-wide-labels");
  await setInput(session, "Message UthCode", "");
  await setSelect(session, "Runtime panel layout", "docked");
  await session.send("Emulation.setDeviceMetricsOverride", { width: 720, height: 900, deviceScaleFactor: 1, mobile: false });
  await setInput(session, "Message UthCode", "Responsive draft");
  await waitFor(session, "filled narrow Composer uses icon triggers", "[...document.querySelectorAll('.composer .custom-select__value')].every((node) => getComputedStyle(node).display === 'none')");
  const filledNarrowAlignment = await verifyComposerRightAlignment(session, "filled narrow Composer right alignment");
  await capture(session, "filled-composer-narrow-icons");
  await setInput(session, "Message UthCode", "");
  const before = observations[0].inputHeight;
  const menus = [];
  for (const selector of [".composer-selectors .custom-select__trigger", ".composer-model .custom-select__trigger"]) {
    await clickSelector(session, selector);
    await waitFor(session, "icon selector opens actual options", "Boolean(document.querySelector('[role=listbox] [role=option]'))");
    const height = await evaluateAction(session, "empty textarea height with options open", "document.querySelector('.composer textarea').getBoundingClientRect().height");
    if (Math.abs(height - before) > 1) throw new Error("empty input height changed when a selector opened");
    const menu = await waitForStableObservationWithin(session, "readable narrow Composer menu", `(() => {
      const list = document.querySelector('[role=listbox]');
      const rect = list?.getBoundingClientRect();
      const options = [...(list?.querySelectorAll('[role=option]') || [])];
      return { ready: Boolean(rect?.width && options.length), width: rect?.width, height: rect?.height, top: rect?.top, bottom: rect?.bottom, left: rect?.left, right: rect?.right, viewport: innerWidth, viewportHeight: innerHeight, optionWidths: options.map((node) => node.getBoundingClientRect().width), optionHeights: options.map((node) => node.getBoundingClientRect().height), overflow: options.some((node) => node.scrollWidth > node.clientWidth + 1), labels: options.map((node) => node.textContent) };
    })()`, 3_000);
    const requiredWidth = selector.includes('composer-model') ? 320 : 210;
    if (menu.width < Math.min(requiredWidth, menu.viewport - 16) - 1 || menu.left < 7 || menu.right > menu.viewport - 7 || menu.top < 7 || menu.bottom > menu.viewportHeight - 7 || menu.height > 221 || menu.overflow || menu.optionHeights.some((value) => value > 96)) throw new Error(`Composer menu collapsed or overflowed: ${JSON.stringify(menu)}`);
    menus.push({ selector, ...menu });
    await capture(session, selector.includes('composer-model') ? "composer-narrow-model-menu" : "composer-narrow-permission-menu");
    await session.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
    await session.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
    await waitFor(session, "icon selector Escape restores focus", `!document.querySelector('[role=listbox]') && document.activeElement === document.querySelector(${JSON.stringify(selector)})`);
  }
  await session.send("Emulation.clearDeviceMetricsOverride");
  if (!wideLabelsComplete) throw new Error(`wide Composer labels were missing or clipped: ${JSON.stringify(wideSelectors)}`);
  return { observations, wideSend, wideSelectors, menus, wideAlignment, filledWideAlignment, filledNarrowAlignment, filledResponsive: true, menuHeightStable: true, keyboardEscape: true };
}

async function verifyPermissionActivity(session) {
  const evidence = await waitForStableObservationWithin(session, "completed Turn activity ownership", `(() => {
    const groups = [...document.querySelectorAll('details.timeline-activity-group')];
    const group = groups[0];
    const final = document.querySelector('.timeline-entry--assistant');
    const failed = group?.querySelector('details.timeline-activity-item.is-failed');
    const interactions = [...document.querySelectorAll('.timeline-activity-event')];
    const composer = document.querySelector('.composer');
    const groupRect = group?.getBoundingClientRect();
    const composerRect = composer?.getBoundingClientRect();
    const ready = groups.length === 1 && Boolean(final && failed) && Number(group?.dataset.reasoningCount) === 3 && Number(group?.dataset.toolCount) === 2 && interactions.length >= 2 && interactions.every((item) => group.contains(item)) && Boolean(group.compareDocumentPosition(final) & Node.DOCUMENT_POSITION_FOLLOWING) && !document.querySelector('[aria-label="Permission approval"]');
    return { ready, groupCount: groups.length, reasoningCount: Number(group?.dataset.reasoningCount), toolCount: Number(group?.dataset.toolCount), failureCount: Number(group?.dataset.failureCount), groupCollapsed: group?.open === false, failedCollapsed: failed?.open === false, reasoningDisclosures: group?.querySelectorAll('details.timeline-reasoning').length || 0, interactionTexts: interactions.map((item) => item.textContent), widthDifference: groupRect && composerRect ? Math.abs(groupRect.width - composerRect.width) : null };
  })()`, 5_000);
  if (!evidence.groupCollapsed || !evidence.failedCollapsed || evidence.reasoningDisclosures || evidence.widthDifference > 2) throw new Error(`Turn folding or width was incorrect: ${JSON.stringify(evidence)}`);
  await capture(session, "permission-turn-collapsed");
  await clickSelector(session, ".timeline-activity-group > summary");
  await capture(session, "permission-turn-expanded");
  await clickSelector(session, ".timeline-activity-item.is-failed > summary");
  await capture(session, "permission-failed-command-expanded");
  await clickSelector(session, ".timeline-activity-item.is-failed > summary");
  await clickSelector(session, ".timeline-activity-group > summary");
  flowEvidence.permissionActivity = evidence;
}

async function runSettingsUiFlow(session) {
  if (requestedLanguage !== "en" || !projectOne || !projectTwo) throw new Error("settings-ui requires English and two isolated projects");
  // Seed only runner-owned sessions through the real public Application API.
  const archives = await evaluateAction(session, "seed isolated archived Settings examples", `(async () => {
    const result = [];
    for (const owner of [{ path: ${JSON.stringify(projectOne)}, title: 'UI_ARCHIVE_ONE' }, { path: ${JSON.stringify(projectTwo)}, title: 'UI_ARCHIVE_TWO' }, { path: null, title: 'UI_ARCHIVE_GENERAL' }]) {
      await window.uthcode.requestRuntime(owner.path ? 'project.open' : 'general.open', owner.path ? { path: owner.path } : {});
      const created = await window.uthcode.requestRuntime('session.new', {});
      if (!created?.session_id) throw new Error('isolated Session creation failed');
      await window.uthcode.requestRuntime('session.rename', { session_id: created.session_id, title: owner.title });
      await window.uthcode.requestRuntime('session.archive', { session_id: created.session_id, project_key: owner.path || 'uthcode:general', archived: true });
      result.push({ title: owner.title, sessionId: created.session_id });
    }
    await window.uthcode.requestRuntime('project.open', { path: ${JSON.stringify(projectOne)} });
    return result;
  })()`);
  await clickText(session, "Settings");
  await waitFor(session, "Settings search ready", "Boolean(document.querySelector('#settings-global-search-input'))");
  const searchPlacement = await evaluateAction(session, "observe Settings sidebar search", `(() => {
    const nav = document.querySelector('.settings-nav');
    const title = nav?.querySelector('h1');
    const search = nav?.querySelector('.settings-global-search');
    const categories = nav?.querySelector('nav');
    const input = search?.querySelector('input');
    const rules = (items) => [...items].flatMap((item) => [item, ...(item.cssRules ? rules(item.cssRules) : [])]);
    const nativeCancelRule = [...document.styleSheets].some((sheet) => rules(sheet.cssRules).some((rule) => rule.selectorText === '.settings-global-search input[type="search"]::-webkit-search-cancel-button' && rule.style?.display === 'none'));
    const ready = Boolean(title && search && categories && title.getBoundingClientRect().bottom <= search.getBoundingClientRect().top && search.getBoundingClientRect().bottom <= categories.getBoundingClientRect().top);
    window.__settingsSuccessFlashes = [];
    window.__settingsSaveObserver = new MutationObserver(() => {
      const text = document.querySelector('.settings-autosave-status')?.textContent || '';
      if (/settings saved|saved;|设置已保存/i.test(text) && window.__settingsSuccessFlashes.length < 20) window.__settingsSuccessFlashes.push(text);
    });
    window.__settingsSaveObserver.observe(document.querySelector('.settings-view'), { subtree: true, childList: true, characterData: true });
    return { ready, inSidebar: Boolean(search), nativeCancelSuppressionRule: input?.type !== 'search' || nativeCancelRule };
  })()`);
  if (!searchPlacement.ready || !searchPlacement.nativeCancelSuppressionRule) throw new Error(`Settings sidebar search or native clear was incorrect: ${JSON.stringify(searchPlacement)}`);
  const category = async (name) => clickSelector(session, `.settings-nav a[href='#settings-${name}']`);
  const clearSearch = async () => {
    await clickSelector(session, ".settings-global-search__clear");
    await waitFor(session, "Settings search cleared", "document.querySelector('#settings-global-search-input')?.value === '' && !document.querySelector('.settings-global-search__results')");
  };
  const settleSettingsScreenshot = (description, { modal = false, switchId = null, expectedChecked = null } = {}) => waitForStableObservationWithin(session, description, `(() => {
    const backdrop = document.querySelector('.provider-modal-backdrop');
    const providerModal = document.querySelector('.provider-modal');
    const input = ${JSON.stringify(Boolean(switchId))} ? document.getElementById(${JSON.stringify(switchId)}) : null;
    const track = input?.parentElement?.querySelector('.settings-switch__track') ?? null;
    const knob = track?.querySelector(':scope > span') ?? null;
    const nodes = [backdrop, providerModal, track, knob].filter(Boolean);
    const animations = [...new Set(nodes.flatMap((node) => node.getAnimations({ subtree: true })))];
    const animationStates = animations.map((animation) => ({ kind: animation.transitionProperty ? 'transition' : 'animation', property: animation.transitionProperty || animation.animationName || '', state: animation.playState }));
    const backdropOpacity = backdrop ? getComputedStyle(backdrop).opacity : null;
    const modalOpacity = providerModal ? getComputedStyle(providerModal).opacity : null;
    const checked = input ? input.checked : null;
    const trackStyle = track ? getComputedStyle(track) : null;
    const knobStyle = knob ? getComputedStyle(knob) : null;
    const modalReady = !${JSON.stringify(modal)} || Boolean(backdrop && providerModal && backdropOpacity === '1' && modalOpacity === '1');
    const switchReady = !${JSON.stringify(Boolean(switchId))} || Boolean(input && track && knob && (${JSON.stringify(expectedChecked === null)} || checked === ${JSON.stringify(expectedChecked)}));
    const motionReady = animations.every((animation) => animation.playState === 'finished' || animation.playState === 'idle');
    return {
      ready: modalReady && switchReady && motionReady,
      modal: { present: Boolean(providerModal), backdropPresent: Boolean(backdrop), backdropOpacity, modalOpacity },
      switch: input ? { id: input.id, checked, expectedChecked: ${JSON.stringify(expectedChecked)}, trackBackground: trackStyle?.backgroundColor ?? null, knobTransform: knobStyle?.transform ?? null } : null,
      animations: animationStates,
    };
  })()`, 3_000);
  const themes = [];
  for (const theme of ["light", "dark", "system"]) {
    await category("appearance");
    await setSelect(session, "settings-theme", theme);
    await category("providers");
    const defaultModelControl = "#settings-default-model .custom-select__trigger";
    await clickSelector(session, defaultModelControl);
    for (const media of theme === "system" ? ["light", "dark"] : [theme]) {
      await session.send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: media }] });
      const expression = `(() => {
        const documentRoot = document.documentElement;
        const themeRoot = document.querySelector('.app-shell');
        const scope = document.querySelector('.custom-select__portal-scope');
        const list = document.querySelector('.custom-select__list');
        const trigger = document.querySelector(${JSON.stringify(defaultModelControl)});
        const styleOf = (element) => {
          if (!element) return null;
          const style = getComputedStyle(element);
          return { colorScheme: style.colorScheme, surface: style.getPropertyValue('--surface').trim(), text: style.getPropertyValue('--text').trim(), background: style.backgroundColor, color: style.color };
        };
        const documentStyle = styleOf(documentRoot);
        const themeStyle = styleOf(themeRoot);
        const scopeStyle = styleOf(scope);
        const listStyle = styleOf(list);
        const triggerStyle = styleOf(trigger);
        let resolvedSurface = null;
        let resolvedText = null;
        if (scope) {
          const probe = document.createElement('span');
          probe.style.cssText = 'position:fixed;left:-10000px;top:-10000px;width:0;height:0;visibility:hidden;pointer-events:none;background-color:var(--surface);color:var(--text)';
          scope.appendChild(probe);
          const probeStyle = getComputedStyle(probe);
          resolvedSurface = probeStyle.backgroundColor;
          resolvedText = probeStyle.color;
          probe.remove();
        }
        const expectedClass = ${JSON.stringify(`theme-${theme}`)};
        const expectedScheme = ${JSON.stringify(media)};
        const ready = Boolean(list && trigger && themeRoot && scope)
          && themeRoot.classList.contains(expectedClass)
          && scope.classList.contains(expectedClass)
          && themeStyle.colorScheme === expectedScheme
          && scopeStyle.colorScheme === expectedScheme
          && scopeStyle.surface === themeStyle.surface
          && scopeStyle.text === themeStyle.text
          && listStyle.background === resolvedSurface
          && listStyle.color === resolvedText;
        return { ready, theme: ${JSON.stringify(theme)}, media: ${JSON.stringify(media)}, listPresent: Boolean(list), documentRoot: { className: documentRoot.className, ...documentStyle }, themeRoot: { className: themeRoot?.className ?? null, ...themeStyle }, portal: { className: scope?.className ?? null, ...scopeStyle }, list: listStyle, trigger: triggerStyle, resolvedSurface, resolvedText };
      })()`;
      const evidence = await evaluateAction(session, "observe Settings dropdown theme tokens", expression);
      writeLog("acceptance_diagnostic", { description: "Settings dropdown theme token observation before assertion", observation: evidence });
      await capture(session, "settings-" + theme + "-" + media + "-menu");
      if (!evidence?.ready) throw new Error(`Settings dropdown theme tokens did not match ${theme}/${media}: ${JSON.stringify(evidence)}`);
      const colors = await waitForStableObservationWithin(session, "dropdown follows active theme tokens", expression, 3_000);
      themes.push({ theme: colors.theme, media: colors.media, menu: colors.list.background, resolvedSurface: colors.resolvedSurface, colorScheme: colors.portal.colorScheme, portal: colors.portal, list: colors.list });
    }
    await session.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
    await session.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
    await waitFor(session, "dropdown Escape restores focus", `(() => { const trigger = document.querySelector(${JSON.stringify(defaultModelControl)}); return !document.querySelector('[role=listbox]') && Boolean(trigger) && document.activeElement === trigger; })()`);
  }
  const lightMenu = themes.find((item) => item.theme === "light");
  const darkMenu = themes.find((item) => item.theme === "dark");
  const systemLightMenu = themes.find((item) => item.theme === "system" && item.media === "light");
  const systemDarkMenu = themes.find((item) => item.theme === "system" && item.media === "dark");
  if (!lightMenu || !darkMenu || lightMenu.menu === darkMenu.menu) throw new Error("light and dark menu surfaces did not differ");
  if (systemLightMenu?.menu !== lightMenu.menu || systemDarkMenu?.menu !== darkMenu.menu) throw new Error("system menu did not follow the active light/dark color scheme");
  await category("appearance");
  await setSelect(session, "settings-theme", "light");
  const fields = [];
  for (const [query, selector, step] of [["Base URL", "#modal-base-url", "provider"], ["Context window", '[id$="-context"]', "model"], ["Reasoning effort", '[id$="-reasoning"]', "model"], ["Supports image input", '[id$="-supports"]', "model"], ["API Key", "#modal-api-key", "provider"]]) {
    await setInput(session, "settings-global-search-input", query);
    await waitFor(session, "Settings field result " + query, "Boolean(document.querySelector('.settings-global-search__results button'))");
    const opened = await evaluateAction(session, "open exact Settings field result", `(() => { const button = [...document.querySelectorAll('.settings-global-search__results button')].find((item) => item.querySelector('span')?.textContent?.trim() === ${JSON.stringify(query)}); if (!button) return false; button.click(); return true; })()`);
    if (!opened) throw new Error("exact Settings field result was absent: " + query);
    const focused = await waitFor(session, "search focuses exact editor field", `(() => { const modal = document.querySelector('[data-settings-editor-step=${step}]'); const target = modal?.querySelector(${JSON.stringify(selector)}); return target && target === document.activeElement ? { query: ${JSON.stringify(query)}, id: target.id, type: target.type || null, keyHidden: target.id === 'modal-api-key' ? target.type === 'password' && target.value === '' : null } : false; })()`);
    if (query === "API Key" && !focused.keyHidden) throw new Error("API Key search exposed a credential");
    fields.push(focused);
    if (query === "Context window") {
      await settleSettingsScreenshot("Settings model-search modal reaches settled visual state", { modal: true });
      await capture(session, "settings-search-model-field");
    }
    if (query === "Reasoning effort") {
      await clickSelector(session, selector);
      await waitFor(session, "modal dropdown uses light theme", "Boolean(document.querySelector('.custom-select__portal-scope.theme-light [role=listbox]'))");
      await settleSettingsScreenshot("Settings modal dropdown reaches settled visual state", { modal: true });
      await capture(session, "settings-light-modal-menu");
      await session.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
      await session.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Escape", code: "Escape", windowsVirtualKeyCode: 27 });
      await waitFor(session, "Escape closes menu before editor", "!document.querySelector('[role=listbox]') && Boolean(document.querySelector('[data-settings-editor-step=model]'))");
    }
    await clickButtonContaining(session, "Cancel", ".settings-editor-modal footer button");
    await waitFor(session, "editor cancelled", "!document.querySelector('.settings-editor-modal')");
    await clearSearch();
  }
  await setInput(session, "settings-global-search-input", "ZZZ_NO_SETTING_RESULT");
  await waitFor(session, "Settings search empty result", "document.querySelector('.settings-global-search__results')?.innerText.includes('No matching settings')");
  const clearCount = await evaluateAction(session, "count Settings clear controls", "document.querySelectorAll('.settings-global-search button.settings-global-search__clear').length");
  if (clearCount !== 1) throw new Error("Settings search did not have exactly one clear control");
  await capture(session, "settings-sidebar-search-single-clear");
  await clearSearch();
  await category("tools");
  const toolsSummary = await evaluateAction(session, "removed tools effective-summary rows and retained editable settings", `(() => {
    const tools = document.querySelector('#settings-tools');
    const fields = ['settings-search-enabled', 'settings-search-key', 'settings-tool-timeout', 'settings-tool-output', 'settings-tool-attachment'];
    return { summaryAbsent: !tools?.querySelector('.settings-effective'), editableFields: fields.filter((id) => tools?.querySelector('#' + id)).length, fieldCount: fields.length };
  })()`);
  if (!toolsSummary.summaryAbsent || toolsSummary.editableFields !== toolsSummary.fieldCount) throw new Error(`Tools settings retained removed rows or lost editable fields: ${JSON.stringify(toolsSummary)}`);
  const before = await evaluateAction(session, "focus web search switch", "(() => { const input = document.querySelector('#settings-search-enabled[role=switch]'); if (!input) throw new Error('switch missing'); input.focus(); return input.checked; })()");
  await session.send("Input.dispatchKeyEvent", { type: "keyDown", key: " ", code: "Space", windowsVirtualKeyCode: 32 });
  await session.send("Input.dispatchKeyEvent", { type: "keyUp", key: " ", code: "Space", windowsVirtualKeyCode: 32 });
  const savedSwitch = await waitFor(session, "keyboard switch autosave", `(async () => { const input = document.querySelector('#settings-search-enabled'); const saved = await window.uthcode.requestRuntime('settings.get', {}); return input?.checked === ${JSON.stringify(!before)} && saved?.configuration?.search?.enabled === ${JSON.stringify(!before)} && !document.querySelector('.settings-autosave-status') ? { checked: input.checked, saved: true, successBannerAbsent: true } : false; })()`);
  const switchVisual = await settleSettingsScreenshot("Settings keyboard switch reaches settled visual state", { switchId: "settings-search-enabled", expectedChecked: !before });
  writeLog("acceptance_diagnostic", { description: "stable Settings switch appearance before screenshot", observation: switchVisual });
  await capture(session, "settings-light-tools-switch");
  await category("archive");
  await waitFor(session, "three actual archived Sessions", "document.querySelectorAll('.settings-archive__item').length === 3");
  await clickSelector(session, "#settings-archive-project-filter");
  const projects = await evaluateAction(session, "archive project dropdown labels", "[...document.querySelectorAll('[role=option]')].map((item) => item.textContent.trim())");
  if (projects.filter((item) => item.startsWith("UI Same project · ")).length !== 2 || !projects.includes("General") || !projects.includes("All projects")) throw new Error("archive dropdown did not distinguish actual same-name owners");
  await capture(session, "settings-archive-project-menu");
  await clickButtonContaining(session, "General", "[role=option]");
  await waitFor(session, "General archive filter", "document.querySelectorAll('.settings-archive__item').length === 1 && document.querySelector('.settings-archive__item')?.textContent.includes('UI_ARCHIVE_GENERAL')");
  await setSelect(session, "settings-archive-project-filter", projects.find((item) => item.includes("coding-one")));
  await waitFor(session, "exact Coding owner archive filter", "document.querySelectorAll('.settings-archive__item').length === 1 && document.querySelector('.settings-archive__item')?.textContent.includes('UI_ARCHIVE_ONE')");
  await setSelect(session, "settings-archive-project-filter", "All projects");
  await session.send("Emulation.setDeviceMetricsOverride", { width: 720, height: 900, deviceScaleFactor: 1, mobile: false });
  await capture(session, "settings-narrow-archive");
  await session.send("Emulation.clearDeviceMetricsOverride");
  const successFlashes = await evaluateAction(session, "stop Settings save observation", "(() => { window.__settingsSaveObserver?.disconnect(); return window.__settingsSuccessFlashes; })()");
  if (successFlashes.length) throw new Error(`Settings success message flashed during actual saves: ${JSON.stringify(successFlashes)}`);
  await clickText(session, "Back to chat");
  const emptyComposer = await verifyEmptyComposer(session);
  flowEvidence.settingsUi = { archives, themes, fields, savedSwitch, toolsSummary, searchPlacement, clearCount, successFlashes, emptyComposer, archiveProjects: projects, generalFilter: true, exactOwnerFilter: true, emptySearch: true, modalEscape: true };
  if (!skipQuit) await evaluateAction(session, "close isolated Settings shell", "window.uthcode.closeShell()");
  writeLog("assertion_pass", { description: "actual packaged Settings themes, field search, keyboard switch, archive owner filtering and narrow rendering" });
}

async function verifyDefaultDiffFiles(session, label) {
  const observed = await waitForStableObservationWithin(session, label, `(() => {
    const files = [...document.querySelectorAll('details.review-panel__diff-file')];
    return { ready: files.length > 0, files: files.map((file) => ({ path: file.dataset.filePath, open: file.open, title: file.querySelector('summary')?.textContent?.trim() || '' })) };
  })()`, 3_000);
  if (!observed.files[0]?.open || observed.files.slice(1).some((file) => file.open) || observed.files.some((file) => !file.path || !file.title) || new Set(observed.files.map((file) => file.path)).size !== observed.files.length) throw new Error(`Diff did not default to one open file with independent named headers: ${JSON.stringify(observed)}`);
  return observed;
}

async function revealDiffFile(session, path) {
  await evaluateAction(session, "expand actual Diff file " + path, `(() => {
    const file = [...document.querySelectorAll('details.review-panel__diff-file')].find((item) => item.dataset.filePath === ${JSON.stringify(path)});
    if (!file) throw new Error('Diff file header missing');
    if (!file.open) file.querySelector('summary')?.click();
  })()`);
  await waitFor(session, "Diff file is open " + path, `[...document.querySelectorAll('details.review-panel__diff-file')].some((file) => file.dataset.filePath === ${JSON.stringify(path)} && file.open)`);
}

async function runDiffFlow(session) {
  if (!diffProject) throw new Error("diff requires --diff-project");
  const opened = await evaluateAction(session, "open current workspace diff from chat", `(() => { const button = document.querySelector('button[aria-label=\"Review current diff\"], button[aria-label=\"查看当前差异\"]'); if (!button) return false; button.click(); return true; })()`);
  if (!opened) throw new Error("chat entry for the current workspace diff was not available");
  await waitFor(session, "current diff review panel", "Boolean(document.querySelector('.review-panel .review-panel__diff'))");
  const defaultFiles = await verifyDefaultDiffFiles(session, "initial Diff defaults to the first file only");
  await capture(session, "current-workspace-diff-initial");
  await computerUseCheckpoint("workspace-diff");
  await evaluateAction(session, "open the second Diff file independently", "document.querySelectorAll('details.review-panel__diff-file')[1]?.querySelector('summary')?.click()");
  await waitFor(session, "first two Diff files open independently", "(() => { const files = [...document.querySelectorAll('details.review-panel__diff-file')]; return files.length > 1 && files[0].open && files[1].open && files.slice(2).every((file) => !file.open); })()");
  await capture(session, "current-workspace-diff-independent-files");
  await session.send("Page.bringToFront");
  await evaluateAction(session, "close only the second Diff file and focus the first header", "(() => { const files = document.querySelectorAll('details.review-panel__diff-file'); files[1]?.querySelector('summary')?.click(); files[0]?.querySelector('summary')?.focus(); })()");
  await session.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13, text: "\r", unmodifiedText: "\r" });
  await session.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 });
  await waitFor(session, "keyboard collapses the first Diff file", "[...document.querySelectorAll('details.review-panel__diff-file')].every((file) => !file.open)");
  await session.send("Input.dispatchKeyEvent", { type: "keyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13, text: "\r", unmodifiedText: "\r" });
  await session.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 });
  await verifyDefaultDiffFiles(session, "keyboard restores the first file independently");
  for (const file of defaultFiles.files) await revealDiffFile(session, file.path);
  const evidence = await evaluateAction(session, "inspect real current workspace diff", `(() => {
    const panel = document.querySelector('.review-panel');
    const paths = [...(panel?.querySelectorAll('details.review-panel__diff-file') || [])].map((item) => ({ status: item.querySelector('summary code')?.textContent?.trim() || '', path: item.dataset.filePath || '', original: item.querySelector('summary small')?.textContent?.replace(/^←\\s*/u, '').trim() || '' }));
    const sections = [...(panel?.querySelectorAll('.review-panel__diff-section') || [])].map((item) => ({ scope: item.dataset.diffScope, title: item.querySelector('h3')?.textContent?.trim() || '', text: [...item.querySelectorAll('.review-panel__diff-line code')].map((line) => line.textContent || '').join('\\n') }));
    const rows = [...(panel?.querySelectorAll('[data-diff-kind]') || [])].map((item) => ({ kind: item.dataset.diffKind, text: item.querySelector('code')?.textContent, numbers: [...item.querySelectorAll('.review-panel__diff-line-number')].map((number) => number.textContent), background: getComputedStyle(item).backgroundColor }));
    const trigger = panel?.querySelector('.review-panel__content-header .custom-select__trigger');
    const rect = trigger?.getBoundingClientRect();
    return { paths, sections, rows, viewedAt: panel?.querySelector('.review-panel__content-header time')?.dateTime || '', selectorInHeader: Boolean(trigger), selectorSize: rect ? { width: rect.width, height: rect.height } : null, emptyParagraphs: panel?.querySelectorAll('.review-panel__diff-empty').length || 0, text: panel?.innerText || '' };
  })()`);
  await capture(session, "current-workspace-diff-all-expanded");
  writeLog("acceptance_diagnostic", {
    description: "initial packaged Diff evidence from controlled Git fixture",
    evidence: {
      paths: evidence.paths,
      sections: evidence.sections,
      rows: evidence.rows,
      viewedAt: evidence.viewedAt,
      selectorInHeader: evidence.selectorInHeader,
    },
  });
  const paths = evidence.paths;
  const required = ["modified.txt", "added.txt", "deleted.txt", "重命名.txt", "long.txt"];
  for (const path of required) if (!paths.some((entry) => entry.path === path)) throw new Error(`tracked Git change is missing from actual diff status: ${path}; ${JSON.stringify(paths)}`);
  if (!paths.some((entry) => entry.path === "重命名.txt" && entry.original === "rename-source.txt")) throw new Error(`tracked rename original path was not shown: ${JSON.stringify(paths)}`);
  const untrackedStatus = paths.filter((entry) => entry.path === "untracked.txt" || entry.original === "untracked.txt");
  if (untrackedStatus.length !== 1 || untrackedStatus[0].path !== "untracked.txt" || untrackedStatus[0].status !== "??" || untrackedStatus[0].original !== "") throw new Error(`All uncommitted scope must show exactly one untracked.txt entry with Git status ??: ${JSON.stringify(untrackedStatus)}`);
  const allDiff = evidence.sections.map((section) => section.text).join("\n");
  if (!allDiff.includes("UNTRACKED_DIFF_BODY")) throw new Error("untracked file change content was absent from the actual diff");
  const removedRow = evidence.rows.find((row) => row.kind === "removed" && row.text === "old tracked line" && row.numbers[0] === "1" && row.numbers[1] === "");
  const addedRow = evidence.rows.find((row) => row.kind === "added" && row.text === "new tracked line" && row.numbers[0] === "" && row.numbers[1] === "1");
  if (!removedRow || !addedRow) {
    const changedRowSample = evidence.rows.filter((row) => row.kind === "removed" || row.kind === "added").slice(0, 8);
    const rowSample = evidence.rows.slice(0, 8);
    throw new Error(`actual removed/added rows or old/new line numbers were absent; changed rows=${JSON.stringify(changedRowSample)}; initial rows=${JSON.stringify(rowSample)}`);
  }
  const removedColor = evidence.rows.find((row) => row.kind === "removed")?.background;
  const addedColor = evidence.rows.find((row) => row.kind === "added")?.background;
  if (!removedColor || !addedColor || removedColor === addedColor || [removedColor, addedColor].includes("rgba(0, 0, 0, 0)")) throw new Error("actual diff rows did not have distinct colored backgrounds");
  if (!allDiff.includes("DIFF_CONTEXT_ROW_497") || !allDiff.includes("DIFF_CHANGED_ROW_500") || allDiff.includes("DIFF_CONTEXT_ROW_1\n") || evidence.rows.filter((row) => row.kind === "context").length > 12) throw new Error("1000-line file was not restricted to change hunks and nearby context");
  if (!evidence.selectorInHeader || !evidence.sections.some((section) => section.scope === "staged") || !evidence.sections.some((section) => section.scope === "unstaged")) throw new Error("actual scope selector or sourced patch sections were absent");
  if (evidence.viewedAt || evidence.emptyParagraphs || !evidence.selectorSize || evidence.selectorSize.width > 145 || evidence.selectorSize.height > 32) throw new Error(`Diff header was not compact or retained removed content: ${JSON.stringify(evidence)}`);
  flowEvidence.diff = { project: resolve(diffProject), defaultFiles, independentDisclosure: true, keyboardDisclosure: true, statusPaths: paths, untrackedStatusPaths: untrackedStatus, untrackedContentInDiff: true, sections: evidence.sections.map((section) => ({ title: section.title, lines: section.text.split(/\r?\n/u).length })), visibleTimestampAbsent: true, emptyParagraphsAbsent: true, selectorSize: evidence.selectorSize };
  await capture(session, "current-workspace-diff");
  const scopeEvidence = [];
  for (const [value, labels] of [["staged", ["Staged", "已暂存"]], ["unstaged", ["Unstaged", "未暂存"]]]) {
    const chosen = await evaluateAction(session, "choose Diff scope " + value, `(() => { document.querySelector('.review-panel__content-header .custom-select__trigger')?.click(); return true; })()`);
    if (!chosen) throw new Error("Diff header selector was absent");
    await waitFor(session, "Diff scope options", "Boolean(document.querySelector('[role=listbox]'))");
    const selected = await evaluateAction(session, "select Diff scope option", `(() => { const button = [...document.querySelectorAll('[role=option]')].find((item) => ${JSON.stringify(labels)}.includes(item.textContent?.trim())); if (!button) return false; button.click(); return true; })()`);
    if (!selected) throw new Error("Diff scope option was absent: " + value);
    const scoped = await waitFor(session, "only selected Diff scope", `(() => { const scopes = [...document.querySelectorAll('.review-panel__diff-section')].map((item) => item.dataset.diffScope); return scopes.length > 0 && scopes.every((scope) => scope === ${JSON.stringify(value)}) ? { scopes, paths: [...document.querySelectorAll('details.review-panel__diff-file')].map((item) => item.dataset.filePath || '') } : false; })()`);
    const expectedPaths = value === "staged" ? ["added.txt", "deleted.txt", "重命名.txt"] : ["long.txt", "modified.txt", "untracked.txt"];
    const actualPaths = [...scoped.paths].sort();
    if (JSON.stringify(actualPaths) !== JSON.stringify(expectedPaths)) throw new Error(`${value} Diff scope paths were missing, extra, or out of contract: ${JSON.stringify({ expectedPaths, actualPaths })}`);
    const scopedDefaults = await verifyDefaultDiffFiles(session, value + " Diff defaults to the first file only");
    scopeEvidence.push({ value, ...scoped, defaultFiles: scopedDefaults });
    await capture(session, "current-workspace-diff-" + value);
  }
  flowEvidence.diff = { ...flowEvidence.diff, selectorInHeader: true, removedColor, addedColor, longFileLines: 1000, renderedContextRows: evidence.rows.filter((row) => row.kind === "context").length, scopes: scopeEvidence };
  const previousOwner = await evaluateAction(session, "record owner before changing the current Diff Session", `(() => {
    const label = document.querySelector('button.session-line.is-selected:not(.new-session-line)')?.getAttribute('aria-label') || '';
    return { sessionId: label.split(' · ')[1] || null, projectLabel: document.querySelector('button.project-select')?.textContent?.trim() || null };
  })()`);
  await clickText(session, "New chat");
  const nextOwner = await waitFor(session, "new Coding Session selected while Diff is open", `(() => {
    const row = document.querySelector('button.session-line.is-selected:not(.new-session-line)');
    const label = row?.getAttribute('aria-label') || '';
    const sessionId = label.split(' · ')[1] || null;
    return row && sessionId && sessionId !== ${JSON.stringify(previousOwner.sessionId)} ? { label, sessionId } : false;
  })()`);
  const ownerSwitch = await waitForStableObservation(session, "new public Coding owner has no previous Diff tab", `(async () => {
    const status = await window.uthcode.requestRuntime('status.get', {});
    const selected = document.querySelector('button.session-line.is-selected:not(.new-session-line)')?.getAttribute('aria-label') || '';
    const selectedSessionId = selected.split(' · ')[1] || null;
    const reviewVisible = Boolean(document.querySelector('.review-panel'));
    const staleDiffVisible = Boolean(document.querySelector('.review-panel .review-panel__diff'));
    const ready = selectedSessionId === ${JSON.stringify(nextOwner.sessionId)} && status?.session_id === selectedSessionId && status?.runtime?.state === 'ready' && status?.active_turn === false && !reviewVisible && !staleDiffVisible;
    return { ready, selectedSessionId, publicSessionId: status?.session_id ?? null, runtimeState: status?.runtime?.state ?? null, activeTurn: status?.active_turn ?? null, staleDiffVisible: reviewVisible || staleDiffVisible };
  })()`);
  flowEvidence.diff.ownerSwitch = { previousOwner, selectedSessionId: nextOwner.sessionId, observation: ownerSwitch };
  await capture(session, "diff-owner-switched");
  if (!diffUnbornProject) throw new Error("unborn Diff project was not provided");
  const unbornProjectLabel = `T12 Unborn Diff · ${diffUnbornProject}`;
  const selectedUnborn = await evaluateAction(session, "expand runner-owned unborn Git project", `(() => { const button = [...document.querySelectorAll('button.project-select')].find((item) => item.getAttribute('aria-label') === ${JSON.stringify(unbornProjectLabel)}); if (!button) return false; if (button.getAttribute('aria-expanded') !== 'true') button.click(); return true; })()`);
  if (!selectedUnborn) throw new Error("unborn Git project was not available in the actual sidebar");
  await waitFor(session, "unborn project New session entry", `(() => { const button = [...document.querySelectorAll('button.project-select')].find((item) => item.getAttribute('aria-label') === ${JSON.stringify(unbornProjectLabel)}); return Boolean(button?.closest('.project-item')?.querySelector('button.new-session-line')); })()`);
  await evaluateAction(session, "open actual new Session in unborn project", `(() => { const button = [...document.querySelectorAll('button.project-select')].find((item) => item.getAttribute('aria-label') === ${JSON.stringify(unbornProjectLabel)})?.closest('.project-item')?.querySelector('button.new-session-line'); if (!button) throw new Error('unborn project New session entry missing'); button.click(); })()`);
  await waitFor(session, "unborn Coding project ready", `(async () => { const status = await window.uthcode.requestRuntime('status.get', {}); return status?.project_key === ${JSON.stringify(diffUnbornProject)} && status?.runtime?.state === 'ready'; })()`);
  await clickSelector(session, 'button[aria-label="Review current diff"], button[aria-label="查看当前差异"]');
  const unbornDefaults = await verifyDefaultDiffFiles(session, "unborn Diff defaults to the first file only");
  await revealDiffFile(session, "new-file.txt");
  const unborn = await waitFor(session, "actual new-file-only Git patch", `(() => {
    const panel = document.querySelector('.review-panel');
    const row = [...(panel?.querySelectorAll('[data-diff-kind="added"] code') || [])].find((item) => item.textContent === 'UNBORN_NEW_FILE_BODY');
    return row && row.getBoundingClientRect().height > 0 ? { content: row.textContent, paths: [...panel.querySelectorAll('details.review-panel__diff-file')].map((item) => item.dataset.filePath), emptyParagraphs: panel.querySelectorAll('.review-panel__diff-empty').length, visibleTimestamp: Boolean(panel.querySelector('time')) } : false;
  })()`);
  if (unborn.emptyParagraphs || unborn.visibleTimestamp || !unborn.paths.includes("new-file.txt")) throw new Error(`unborn Diff was incorrect: ${JSON.stringify(unborn)}`);
  flowEvidence.diff.unborn = { ...unborn, defaultFiles: unbornDefaults };
  await capture(session, "diff-unborn-new-file");
  await computerUseCheckpoint("workspace-unborn");
  await setSelect(session, requestedLanguage === "en" ? "Diff scope" : "Diff 范围", requestedLanguage === "en" ? "Staged" : "已暂存");
  await waitFor(session, "unborn staged scope has no new-file body or empty paragraph", "!document.querySelector('.review-panel__diff')?.textContent.includes('UNBORN_NEW_FILE_BODY') && !document.querySelector('.review-panel__diff-empty') && document.querySelectorAll('details.review-panel__diff-file').length === 0");
  await setSelect(session, requestedLanguage === "en" ? "Diff scope" : "Diff 范围", requestedLanguage === "en" ? "Unstaged" : "未暂存");
  await verifyDefaultDiffFiles(session, "unborn unstaged Diff defaults to the first file only");
  await revealDiffFile(session, "new-file.txt");
  await waitFor(session, "unborn unstaged scope restores actual new-file body", "document.querySelector('.review-panel__diff')?.textContent.includes('UNBORN_NEW_FILE_BODY')");
  flowEvidence.diff.unborn.scopeFiltering = true;
  if (!skipQuit) await evaluateAction(session, "close UthCode shell", "window.uthcode.closeShell()");
  writeLog("assertion_pass", { description: "packaged chat entry shows tracked and untracked Git changes with a compact scope selector, then a real Coding Session switch clears the old Diff panel" });
}

async function runGeneralRealProviderFlow(session) {
  await switchMode(session, "general");
  const generalUi = await evaluateAction(session, "verify General mode before real Provider request", `({ mode: document.querySelector('.sidebar-brand-menu-trigger')?.dataset.mode, sidebar: document.querySelector('.sidebar')?.getAttribute('aria-label'), projectButtons: document.querySelectorAll('.project-select').length })`);
  if (generalUi.mode !== "general" || generalUi.sidebar !== "General" || generalUi.projectButtons !== 0) throw new Error(`real Provider request is not in isolated General mode: ${JSON.stringify(generalUi)}`);
  await clickButtonContaining(session, "New chat", ".sidebar-primary button");
  await waitFor(session, "new General conversation header", "['Session', 'New conversation', '会话', '新对话'].some((value) => document.querySelector('h1')?.textContent?.includes(value))");
  const owner = await waitForGeneralDraftReady(session);
  const subscribed = await evaluateAction(session, "subscribe through public AgentEvent API", `(() => {
    if (typeof window.uthcode?.subscribeAgentEvents !== 'function') return false;
    const eventTypes = [];
    const unsubscribe = window.uthcode.subscribeAgentEvents((event) => { if (event && typeof event.type === 'string') eventTypes.push(event.type); });
    window.__t12GeneralProviderEvents = { eventTypes, unsubscribe };
    return true;
  })()`);
  if (!subscribed) throw new Error("public subscribeAgentEvents API is unavailable");
  await submitLifecyclePrompt(session, generalApiPrompt, generalApiToken);
  const final = await waitFor(session, "real General Provider final message", `(() => {
    const entries = [...document.querySelectorAll('.timeline-entry--assistant .timeline-content')];
    return entries.at(-1)?.innerText?.trim() === ${JSON.stringify(generalApiToken)};
  })()`);
  const evidence = await evaluateAction(session, "inspect real General Provider event names only", `(() => {
    const eventTypes = window.__t12GeneralProviderEvents?.eventTypes ?? [];
    const counts = Object.fromEntries([...new Set(eventTypes)].map((type) => [type, eventTypes.filter((item) => item === type).length]));
    const assistant = [...document.querySelectorAll('.timeline-entry--assistant .timeline-content')].at(-1)?.innerText?.trim() || '';
    const row = document.querySelector('button.recent-line.is-selected');
    const toolActivity = document.querySelectorAll('.timeline-activity-item, .timeline-activity-group').length;
    const identity = row ? { label: row.getAttribute('aria-label'), id: row.getAttribute('aria-label')?.split(' · ')[1] || null } : null;
    window.__t12GeneralProviderEvents?.unsubscribe?.();
    delete window.__t12GeneralProviderEvents;
    return { eventTypes, counts, assistantExact: assistant === ${JSON.stringify(generalApiToken)}, identity, toolActivity };
  })()`);
  const requiredEvents = ["assistant_message_delta", "assistant_message_completed", "turn_completed"];
  const missing = requiredEvents.filter((type) => !evidence.eventTypes.includes(type));
  const toolEvents = evidence.eventTypes.filter((type) => /tool|permission/u.test(type));
  if (!evidence.assistantExact || missing.length > 0 || !evidence.identity?.id || evidence.toolActivity !== 0 || toolEvents.length > 0) {
    throw new Error(`real General Provider acceptance did not meet this prompt's stream/final/no-tool-activity requirements: ${JSON.stringify({ assistantExact: evidence.assistantExact, missingEvents: missing, toolEventCount: toolEvents.length, toolActivity: evidence.toolActivity, hasPersistentSession: Boolean(evidence.identity?.id) })}`);
  }
  flowEvidence.generalReal = { mode: generalUi.mode, sidebar: generalUi.sidebar, projectButtons: generalUi.projectButtons, owner, eventCounts: evidence.counts, requiredEvents, toolEventCount: toolEvents.length, toolActivity: evidence.toolActivity, finalExact: evidence.assistantExact, sessionId: evidence.identity.id };
  await capture(session, "general-real-provider-final");
  if (!skipQuit) await evaluateAction(session, "close UthCode shell", "window.uthcode.closeShell()");
  writeLog("assertion_pass", { description: "actual configured Provider produced streamed AgentEvent delta and final response in General mode without invoking Tools" });
}

async function runGeneralCancelFlow(session) {
  await switchMode(session, "general");
  const generalUi = await evaluateAction(session, "verify General mode before controlled cancellation", `({ mode: document.querySelector('.sidebar-brand-menu-trigger')?.dataset.mode, sidebar: document.querySelector('.sidebar')?.getAttribute('aria-label'), projectButtons: document.querySelectorAll('.project-select').length })`);
  if (generalUi.mode !== "general" || generalUi.sidebar !== "General" || generalUi.projectButtons !== 0) throw new Error(`controlled cancellation did not run in isolated General mode: ${JSON.stringify(generalUi)}`);
  await clickButtonContaining(session, "New chat", ".sidebar-primary button");
  await waitFor(session, "new General conversation header", "['Session', 'New conversation', '会话', '新对话'].some((value) => document.querySelector('h1')?.textContent?.includes(value))");
  const owner = await waitForGeneralDraftReady(session);
  const monitorInstalled = await evaluateAction(session, "subscribe to public General cancellation events", `(() => {
    if (typeof window.uthcode?.subscribeAgentEvents !== 'function') return false;
    window.__t12GeneralCancelEvents?.unsubscribe?.();
    const eventTypes = [];
    const unsubscribe = window.uthcode.subscribeAgentEvents((event) => {
      if (typeof event?.type === 'string' && ['turn_started', 'turn_completed', 'turn_failed', 'turn_cancelled'].includes(event.type)) eventTypes.push(event.type);
    });
    window.__t12GeneralCancelEvents = { eventTypes, unsubscribe };
    return true;
  })()`);
  if (!monitorInstalled) throw new Error("public AgentEvent subscription is unavailable for General cancellation");
  const prompt = "T12 controlled General cancellation";
  await setInput(session, "Message UthCode", prompt);
  await waitFor(session, "General cancellation message ready", "(() => { const input = document.querySelector('textarea[aria-label=\"Message UthCode\"], textarea[aria-label=\"发送给 UthCode\"]'); const button = document.querySelector('.composer-send'); return Boolean(input?.value.trim()) && Boolean(button && !button.disabled); })()");
  await clickSelector(session, ".composer-send");
  let started;
  try {
    started = await waitForStableObservationWithin(session, "General delayed turn accepted with public Runtime owner", `(async () => {
      const status = await window.uthcode.requestRuntime('status.get', {});
      const row = document.querySelector('button.recent-line.is-selected, button.session-line.is-selected:not(.new-session-line)');
      const selectedSessionId = row?.getAttribute('aria-label')?.split(' · ')[1] || null;
      const cancelVisible = Boolean(document.querySelector('button[aria-label="Cancel"], button[aria-label="取消"]'));
      const terminal = (window.__t12GeneralCancelEvents?.eventTypes || []).find((type) => ['turn_completed', 'turn_failed', 'turn_cancelled'].includes(type)) || null;
      const eventTypes = [...(window.__t12GeneralCancelEvents?.eventTypes || [])];
      const observation = {
        mode: document.querySelector('.sidebar-brand-menu-trigger')?.dataset.mode || null,
        publicSessionId: status?.session_id ?? null,
        selectedSessionId,
        runtimeState: status?.runtime?.state ?? null,
        activeTurn: status?.active_turn ?? null,
        sessionStatus: status?.session_state?.status ?? null,
        promptVisible: (document.querySelector('[aria-label="Chat timeline"]')?.innerText || '').includes(${JSON.stringify(prompt)}),
        cancelVisible,
        terminal,
        eventTypes,
      };
      observation.ready = terminal !== null || (observation.mode === 'general' && observation.promptVisible && observation.activeTurn === true && cancelVisible);
      return observation;
    })()`, 15_000);
  } catch (error) {
    const diagnostic = await evaluateAction(session, "inspect General turn start after Send", `(async () => {
      const status = await window.uthcode.requestRuntime('status.get', {});
      const input = document.querySelector('textarea[aria-label="Message UthCode"], textarea[aria-label="发送给 UthCode"]');
      const row = document.querySelector('button.recent-line.is-selected, button.session-line.is-selected:not(.new-session-line)');
      return {
        mode: document.querySelector('.sidebar-brand-menu-trigger')?.dataset.mode || null,
        publicSessionId: status?.session_id ?? null,
        selectedSessionId: row?.getAttribute('aria-label')?.split(' · ')[1] || null,
        runtimeState: status?.runtime?.state ?? null,
        activeTurn: status?.active_turn ?? null,
        sessionStatus: status?.session_state?.status ?? null,
        promptVisible: (document.querySelector('[aria-label="Chat timeline"]')?.innerText || '').includes(${JSON.stringify(prompt)}),
        composerValueLength: input?.value?.length ?? null,
        sendClickCount: window.__t12ComposerSendProbe?.clickCount ?? null,
        cancelVisible: Boolean(document.querySelector('button[aria-label="Cancel"], button[aria-label="取消"]')),
        eventTypes: [...(window.__t12GeneralCancelEvents?.eventTypes || [])],
      };
    })()`);
    flowEvidence.generalCancelStartFailure = { owner, diagnostic };
    try { await capture(session, "general-cancel-start-failure"); } catch (captureError) { flowEvidence.generalCancelStartFailure.screenshotFailure = captureError instanceof Error ? captureError.message : String(captureError); }
    throw new Error(`${error instanceof Error ? error.message : String(error)}; General public turn-start diagnostic=${JSON.stringify(diagnostic)}`);
  }
  if (started.terminal !== null) throw new Error(`General delayed Provider turn reached a terminal event before cancellation controls: ${JSON.stringify(started)}`);
  if (started.mode !== "general" || !started.promptVisible || started.activeTurn !== true || !started.cancelVisible) throw new Error(`General delayed Provider turn did not expose its real active/cancel state: ${JSON.stringify(started)}`);
  flowEvidence.generalCancelStarted = { owner, observation: started };
  await submitDelayedFlow(session, { general: true });
  const terminal = await waitFor(session, "public General cancellation terminal event", `(() => (window.__t12GeneralCancelEvents?.eventTypes || []).includes('turn_cancelled') ? { type: 'turn_cancelled' } : false)()`);
  const terminalIdle = await waitForStableObservation(session, "public Runtime confirms cancelled General turn is idle", `(async () => {
    const status = await window.uthcode.requestRuntime('status.get', {});
    const cancelVisible = Boolean(document.querySelector('button[aria-label="Cancel"], button[aria-label="取消"]'));
    const observation = { runtimeState: status?.runtime?.state ?? null, activeTurn: status?.active_turn ?? null, sessionStatus: status?.session_state?.status ?? null, sessionId: status?.session_id ?? null, cancelVisible };
    observation.ready = observation.runtimeState === 'ready' && observation.activeTurn === false && !cancelVisible;
    return observation;
  })()`);
  const evidence = await evaluateAction(session, "inspect controlled General cancellation", `(() => {
    const text = document.querySelector('[aria-label="Chat timeline"]')?.innerText || '';
    const row = document.querySelector('button.recent-line.is-selected');
    const identity = row ? { label: row.getAttribute('aria-label'), id: row.getAttribute('aria-label')?.split(' · ')[1] || null } : null;
    const assistant = [...document.querySelectorAll('.timeline-entry--assistant .timeline-content')].map((item) => item.innerText || '');
    return { promptVisible: text.includes(${JSON.stringify(prompt)}), identity, assistant, activeCancelControls: document.querySelectorAll('button[aria-label="Cancel"], button[aria-label="取消"]').length };
  })()`);
  if (!evidence.promptVisible || !evidence.identity?.id || evidence.assistant.some((text) => text.includes(expectedText)) || evidence.activeCancelControls !== 0) {
    throw new Error(`controlled General cancellation did not settle without a final answer: ${JSON.stringify({ promptVisible: evidence.promptVisible, hasPersistentSession: Boolean(evidence.identity?.id), finalVisible: evidence.assistant.some((text) => text.includes(expectedText)), activeCancelControls: evidence.activeCancelControls })}`);
  }
  await evaluateAction(session, "remove General cancellation event listener", "window.__t12GeneralCancelEvents?.unsubscribe?.(); delete window.__t12GeneralCancelEvents; true");
  flowEvidence.generalCancel = { mode: generalUi.mode, sidebar: generalUi.sidebar, projectButtons: generalUi.projectButtons, promptVisible: evidence.promptVisible, sessionId: evidence.identity.id, terminal, terminalIdle, finalVisible: false, activeCancelControls: evidence.activeCancelControls };
  await capture(session, "general-controlled-cancellation");
  if (!skipQuit) await evaluateAction(session, "close UthCode shell", "window.uthcode.closeShell()");
  writeLog("assertion_pass", { description: "controlled delayed Provider request was cancelled in General after a real public owner and active-turn readiness check" });
}

async function runGeneralInvalidConfigFlow(session) {
  const menuOpened = await evaluateAction(session, "open mode menu for invalid General configuration", `(() => { const button = document.querySelector('.sidebar-brand-menu-trigger'); if (!button) return false; button.click(); return true; })()`);
  if (!menuOpened) throw new Error("mode menu trigger is missing before invalid General configuration check");
  await waitFor(session, "mode menu for invalid General configuration", "Boolean(document.querySelector('[role=menu]'))");
  await clickButtonContaining(session, "General", "[role=menu] button");
  const openErrorText = requestedLanguage === "zh-CN" ? "无法打开会话，请重试。" : "Session could not be opened. Try again.";
  const settingsGuidanceText = requestedLanguage === "zh-CN" ? "配置尚未初始化，请配置协议后重试。" : "Configuration is not initialized. Configure a provider and save settings.";
  await waitFor(session, "General configuration error guidance", `document.body?.innerText?.includes(${JSON.stringify(openErrorText)})`);
  const failure = await evaluateAction(session, "inspect rejected General mode and error guidance", `(() => ({ mode: document.querySelector('.sidebar-brand-menu-trigger')?.dataset.mode, error: document.querySelector('[data-runtime-error-owner="timeline"]')?.innerText || document.querySelector('.runtime-panel')?.innerText || '', assistantCount: document.querySelectorAll('.timeline-entry--assistant').length }))()`);
  if (failure.mode === "general" || failure.assistantCount !== 0 || !failure.error.includes(openErrorText)) throw new Error(`invalid configuration was incorrectly presented as a working General chat: ${JSON.stringify(failure)}`);
  await clickButtonContaining(session, "Settings", ".sidebar-footer button");
  await waitFor(session, "Settings configuration guidance", `Boolean(document.querySelector('.settings-view')) && document.querySelector('.settings-view__error')?.innerText?.includes(${JSON.stringify(settingsGuidanceText)})`);
  const settingsGuidance = await evaluateAction(session, "inspect Settings recovery guidance", `document.querySelector('.settings-view__error')?.innerText?.trim() || ''`);
  const addProvider = await evaluateAction(session, "open a cancellable provider draft", `(() => { const button = document.querySelector('.settings-view .row-add--inline'); if (!button || button.disabled) return false; button.click(); return true; })()`);
  if (!addProvider) throw new Error("Settings did not offer its existing provider editor for invalid-configuration recovery");
  await waitFor(session, "provider editor for cancellation", "Boolean(document.querySelector('.settings-editor-modal[role=dialog]'))");
  const cancelLabel = requestedLanguage === "zh-CN" ? "取消" : "Cancel";
  await clickButtonContaining(session, cancelLabel, ".settings-editor-modal footer button");
  await waitFor(session, "provider draft cancelled", "!document.querySelector('.settings-editor-modal') && Boolean(document.querySelector('.settings-view__error'))");
  const cancelState = await evaluateAction(session, "verify cancelled provider draft", `({ providerRows: document.querySelectorAll('.settings-view .provider-row').length, errorStillVisible: Boolean(document.querySelector('.settings-view__error')), editorVisible: Boolean(document.querySelector('.settings-editor-modal')) })`);
  if (cancelState.providerRows !== 0 || !cancelState.errorStillVisible || cancelState.editorVisible) throw new Error(`cancelled provider draft changed the invalid Settings projection: ${JSON.stringify(cancelState)}`);
  const backClicked = await evaluateAction(session, "cancel invalid-configuration recovery", `(() => { const button = document.querySelector('.settings-view__back'); if (!button || button.disabled) return false; button.click(); return true; })()`);
  if (!backClicked) throw new Error("Settings Back action was unavailable after cancelling the provider draft");
  await waitFor(session, "return from cancelled invalid-configuration recovery", "!document.querySelector('.settings-view') && Boolean(document.querySelector('.composer textarea'))");
  flowEvidence.generalInvalidConfig = { attemptedMode: "general", rejectedMode: failure.mode, assistantCount: failure.assistantCount, settingsGuidance, providerDraftCancelled: true, providerRowsAfterCancel: cancelState.providerRows, returnedToChat: true };
  await capture(session, "general-invalid-config-cancelled");
  if (!skipQuit) await evaluateAction(session, "close UthCode shell", "window.uthcode.closeShell()");
  writeLog("assertion_pass", { description: "invalid General configuration remains a visible failure, Settings offers recovery guidance, and the new provider draft can be cancelled" });
}

async function runModelImageSwitchFlow(session) {
  const textModelRef = "fixture/menu-model-0";
  const textModelLabel = "Fixture model 0 with a readable long display name";
  const visionModelRef = "fixture/fixture-model";
  const dialogSelector = '#model-image-switch-dialog, .model-image-switch-dialog, [data-testid="model-image-switch-dialog"]';
  const buttonSelector = (name) => `#${name}, .${name}, [data-testid="${name}"]`;
  const readModel = async () => evaluateAction(session, "read authoritative model and Session", `(async () => {
    const status = await window.uthcode.requestRuntime('status.get', {});
    return { model: status?.application?.current_model, sessionId: status?.session?.session_id ?? status?.session_id ?? null };
  })()`);
  const awaitModel = async (ref) => waitFor(session, `model committed: ${ref}`, `(async () => {
    const status = await window.uthcode.requestRuntime('status.get', {});
    const label = document.querySelector('.composer-model .custom-select__value')?.textContent || '';
    return status?.application?.current_model === ${JSON.stringify(ref)}
      && label.includes(${JSON.stringify(ref === textModelRef ? textModelLabel : "Vision fixture")})
      && !document.querySelector(${JSON.stringify(dialogSelector)});
  })()`);
  const selectModel = async (label) => {
    await clickSelector(session, '.composer-model .custom-select__trigger');
    await waitFor(session, `model option: ${label}`, `Boolean(document.querySelector('[role="option"][title=${JSON.stringify(label)}]'))`);
    await clickSelector(session, `[role="option"][title=${JSON.stringify(label)}]`);
  };
  const sendMessage = async (prompt) => {
    const before = await evaluateAction(session, "count assistant messages before real Turn", "document.querySelectorAll('.timeline-entry--assistant .timeline-content').length");
    await setInput(session, "Message UthCode", prompt);
    await waitFor(session, "real Turn input ready", "Boolean(document.querySelector('.composer-send') && !document.querySelector('.composer-send').disabled)");
    await clickSelector(session, '.composer-send');
    await waitFor(session, "real Turn completed", `(() => {
      const entries = [...document.querySelectorAll('.timeline-entry--assistant .timeline-content')];
      return entries.length > ${before} && entries.at(-1)?.innerText.includes('fixture response')
      && !document.querySelector('.composer-actions button[aria-label="Cancel"], .composer-actions button[aria-label="取消"]');
    })()`);
  };
  const newImageSession = async () => {
    const previous = await selectedSessionIdentity(session);
    await clickText(session, "New chat");
    await waitForStableObservation(session, "new image Session owner and attachment input ready", `(async () => {
      const row = document.querySelector('button.session-line.is-selected:not(.new-session-line), button.recent-line.is-selected');
      const selectedId = row?.getAttribute('aria-label')?.split(' · ')[1] || null;
      const status = await window.uthcode.requestRuntime('status.get', {});
      const input = document.querySelector('.composer textarea');
      const attach = document.querySelector('.composer-attachment-actions button');
      const ready = Boolean(selectedId && selectedId !== ${JSON.stringify(previous?.id ?? null)}
        && status?.session_id === selectedId && status?.active_turn === false
        && document.querySelector('.sidebar')?.getAttribute('aria-busy') !== 'true'
        && input && !input.disabled && input.closest('.composer')?.getAttribute('aria-disabled') !== 'true'
        && attach && !attach.disabled);
      return { ready, selectedId, publicSessionId: status?.session_id ?? null };
    })()`);
    await dropReviewImageAttachment(session);
    await sendMessage('MODEL_IMAGE_ORIGINAL_PROMPT: describe this controlled image and retain this text.');
    const identity = await selectedSessionIdentity(session);
    if (!identity?.id) throw new Error("image fixture Session has no durable identity");
    return identity;
  };
  const awaitDialog = async () => waitFor(session, "image-history model choice modal", `(() => {
    const dialog = document.querySelector(${JSON.stringify(dialogSelector)});
    return Boolean(dialog && dialog.getAttribute('role') === 'dialog'
      && document.querySelector(${JSON.stringify(buttonSelector('model-image-switch-summarize'))})
      && document.querySelector(${JSON.stringify(buttonSelector('model-image-switch-placeholder'))}));
  })()`);

  const placeholderOwner = await newImageSession();
  await selectModel(textModelLabel);
  await awaitDialog();
  await capture(session, 'model-image-choice-placeholder');
  await computerUseCheckpoint('model-image-placeholder');
  if (!computerUse) await clickSelector(session, buttonSelector('model-image-switch-placeholder'));
  await awaitModel(textModelRef);
  await sendMessage('MODEL_IMAGE_PLACEHOLDER_CONTINUATION');
  const placeholderIdentity = await selectedSessionIdentity(session);
  if (placeholderIdentity?.id !== placeholderOwner.id) throw new Error('placeholder switch changed Session ownership');
  await capture(session, 'model-image-placeholder-committed');

  await selectModel('Vision fixture');
  await awaitModel(visionModelRef);
  const summaryOwner = await newImageSession();
  await selectModel(textModelLabel);
  await awaitDialog();
  await capture(session, 'model-image-choice-summarize');
  await computerUseCheckpoint('model-image-summarize');
  if (!computerUse) await clickSelector(session, buttonSelector('model-image-switch-summarize'));
  const busy = await waitFor(session, "image summary confirm button is busy", `(() => {
    const button = document.querySelector(${JSON.stringify(buttonSelector('model-image-switch-summarize'))});
    const dialog = document.querySelector(${JSON.stringify(dialogSelector)});
    if (!button || dialog?.getAttribute('aria-busy') !== 'true' || !button.disabled) return false;
    const animated = [...button.querySelectorAll('*')].some((item) => getComputedStyle(item).animationName !== 'none');
    return animated ? { disabled: button.disabled, ariaBusy: dialog.getAttribute('aria-busy'), animated: true } : false;
  })()`);
  await capture(session, 'model-image-summarizing-spinner');
  await computerUseCheckpoint('model-image-summarizing');
  if (computerUse) await writeFile(resolve(screenshotDir, 'caption.continue'), 'release controlled caption response\n', 'utf8');
  await awaitModel(textModelRef);
  await sendMessage('MODEL_IMAGE_SUMMARY_CONTINUATION');
  const summaryIdentity = await selectedSessionIdentity(session);
  if (summaryIdentity?.id !== summaryOwner.id) throw new Error('summary switch changed Session ownership');
  const retainedImage = await evaluateAction(session, "original image remains in chat after summary", "Boolean(document.querySelector('.timeline-attachments .file-card[data-file-kind=\"image\"][data-file-ref]'))");
  if (!retainedImage) throw new Error('summary switch removed the original image attachment');
  await capture(session, 'model-image-summary-committed');

  await switchMode(session, 'general');
  await sendMessage('MODEL_GENERAL_SEARCH_TOOLS_VISIBLE');
  await capture(session, 'general-network-tools-chat');
  flowEvidence.modelImages = { placeholderOwner, placeholderIdentity, summaryOwner, summaryIdentity, busy, retainedImage, finalModel: (await readModel()).model, generalToolsWithOwnedResultRead: true };
  if (!skipQuit) await evaluateAction(session, 'close controlled model switch shell', 'window.uthcode.closeShell()');
}

async function run() {
  flowDeadline = Date.now() + timeoutMs;
  writeLog("driver_start", { argv: process.argv.slice(2), cdpPort, timeoutMs, requestTimeoutMs, flow, planChoice, delayAction, askQuestionCount });
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
    if (flow !== "visual-fixture" && flow !== "visual" && flow !== "general-invalid-config") {
      await waitFor(session, "Runtime ready", "(() => { const text = document.querySelector('.runtime-panel h2')?.textContent || ''; return text.includes('Ready') || text.includes('就绪'); })()");
    }

    if (requestedLanguage) {
      const currentLanguage = await evaluateAction(session, "read initial language", "typeof window.uthcode?.readPreference === \"function\" ? window.uthcode.readPreference(\"language\") : null");
      if (currentLanguage !== requestedLanguage) {
        const languageSet = await evaluateAction(session, "set requested language", `(async()=>{if(typeof window.uthcode?.writePreference !== "function") return false; await window.uthcode.writePreference("language", ${JSON.stringify(requestedLanguage)}); return true})()`);
        if (!languageSet) throw new Error("language preference API is unavailable in the packaged Renderer");
      } else {
        observedLanguage = currentLanguage;
        writeLog("assertion_pass", { description: "requested language already initialized by fixture preferences", value: currentLanguage });
      }
      // Reload even when the requested language is already present.  This
      // keeps the packaged acceptance boundary identical for en/zh.
      const previousDocumentOrigin = await evaluateAction(session, "read document origin before language reload", "performance.timeOrigin");
      await session.send("Page.reload", { ignoreCache: true });
      await waitFor(session, "UthCode shell after language reload", `performance.timeOrigin !== ${JSON.stringify(previousDocumentOrigin)} && document.readyState === 'complete' && Boolean(document.querySelector('.sidebar'))`);
      await waitFor(session, "Composer after language reload", "document.readyState === 'complete' && Boolean(document.querySelector('.composer textarea'))");
      observedLanguage = await evaluateAction(session, "read requested language", "typeof window.uthcode?.readPreference === \"function\" ? window.uthcode.readPreference(\"language\") : null");
      if (!observedLanguage) throw new Error("language preference read API is unavailable in the packaged Renderer");
      if (observedLanguage !== requestedLanguage) throw new Error(`requested language ${requestedLanguage} was not observed: ${observedLanguage}`);
      writeLog("assertion_pass", { description: "read requested language", value: observedLanguage });
      if (flow !== "visual-fixture" && flow !== "visual" && flow !== "general-invalid-config") {
        await waitFor(session, "Runtime ready after language reload", "(() => { const text = document.querySelector('.runtime-panel h2')?.textContent || ''; return text.includes('Ready') || text.includes('就绪'); })()");
        if (!generalFlows.has(flow)) {
          await waitFor(session, "restored Project", "Boolean(document.querySelector('button.project-select'))");
          await waitFor(session, "new Session action", "Boolean(document.querySelector('button.new-session-line'))");
        }
      }
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
      await assertLayoutFocusAndResize(session);
      await assertResponsiveLayout(session, "dark wide layout");
      await runResponsiveHealthFlow(session);
      await setSelect(session, "Runtime panel layout", "floating");
      await capture(session, "main-dark-floating");
      await setSelect(session, "Runtime panel layout", "hidden");
      await capture(session, "main-dark-hidden");
      await clickText(session, "Settings");
      await setSelect(session, "theme", "light");
      await clickText(session, "Back to chat");
      await capture(session, "main-light");
      await assertResponsiveLayout(session, "light wide layout");
      await runResponsiveHealthFlow(session);
      await session.send("Emulation.setDeviceMetricsOverride", { width: 760, height: 640, deviceScaleFactor: 1, mobile: false });
      await capture(session, "main-narrow");
      await restoreWideCssViewport(session, "final narrow screenshot CSS viewport reset");
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

    if (flow === "lifecycle") {
      await runLifecycleFlow(session);
      return;
    }
    if (flow === "diff") {
      await runDiffFlow(session);
      return;
    }
    if (flow === "settings-ui") {
      await runSettingsUiFlow(session);
      return;
    }
    if (flow === "general-real") {
      await runGeneralRealProviderFlow(session);
      return;
    }
    if (flow === "general-cancel") {
      await runGeneralCancelFlow(session);
      return;
    }
    if (flow === "general-invalid-config") {
      await runGeneralInvalidConfigFlow(session);
      return;
    }
    if (flow === "model-images") {
      await runModelImageSwitchFlow(session);
      return;
    }
    if (flow === "review") {
      await submitPackagedReviewFlow(session);
      return;
    }

    // New Session -> real Provider request -> streamed AgentEvent projection.
    await clickText(session, "New chat");
    await waitFor(session, "new conversation header", "['Session', 'New conversation', '会话', '新对话'].some((value) => document.querySelector('h1')?.textContent?.includes(value))");
    if (flow === "artifact-card") {
      if (!artifactPath) throw new Error("artifact-card requires --artifact-path");
      await setInput(session, "Message UthCode", "Please show the controlled image preview.");
      await waitFor(session, "artifact preview request ready", "(() => { const input = document.querySelector('textarea[aria-label=\"Message UthCode\"], textarea[aria-label=\"发送给 UthCode\"]'); const button = document.querySelector('.composer-send'); return Boolean(input?.value.trim()) && Boolean(button && !button.disabled); })()");
      await clickSelector(session, ".composer-send");
      await waitFor(session, "assistant Markdown artifact link and FileCard", `(() => { const entry = [...document.querySelectorAll('.timeline-entry--assistant .timeline-content')].at(-1); return Boolean(entry?.querySelector('.markdown-artifact-link') && entry?.querySelector('.markdown-artifact-attachments .file-card[data-artifact-path]')); })()`);
      const artifact = await evaluateAction(session, "inspect rendered artifact link and card", `(() => {
        const entry = [...document.querySelectorAll('.timeline-entry--assistant .timeline-content')].at(-1);
        const link = entry?.querySelector('.markdown-artifact-link');
        const card = entry?.querySelector('.markdown-artifact-attachments .file-card');
        return { linkText: link?.textContent?.trim() || null, cardPath: card?.getAttribute('data-artifact-path') || null, cardKind: card?.getAttribute('data-artifact-kind') || null, cardActionCount: card?.querySelectorAll('.file-card__menu [role="menuitem"]').length ?? 0 };
      })()`);
      if (artifact.linkText !== "T12 native image" || artifact.cardPath !== artifactPath || artifact.cardKind !== "image") {
        throw new Error(`formal Markdown artifact link did not resolve to the expected image FileCard: ${JSON.stringify(artifact)}`);
      }
      flowEvidence.artifactCard = artifact;
      await capture(session, "native-artifact-filecard");
      writeLog("assertion_pass", { description: "actual Provider Renderer flow produced a Markdown artifact link and bottom image FileCard" });
      if (!skipQuit) await evaluateAction(session, "close UthCode shell", "window.uthcode.closeShell()");
      return;
    }
    await assertCommandCandidate(session, "/new");
    await assertCommandCandidate(session, "/do");
    await assertCommandCandidate(session, "/mod", "/model");
    // Model completion keeps the canonical wire ref in the selected value,
    // while the current Renderer contract deliberately presents its friendly
    // display_name to the user.
    await assertCommandCandidate(session, "/model ", "CDP fixture");
    await assertLocalizedCommandMenu(session);
    if (flow === "plan") {
      await setInput(session, "Message UthCode", "/plan");
      await waitFor(session, "plan command completion", "Boolean([...document.querySelectorAll('.command-menu button')].find((item) => (item.textContent || '').includes('/plan'))) ");
      const selectedPlanCommand = await evaluateAction(session, "select plan command", `(() => {
        const option = [...document.querySelectorAll('.command-menu button')].find((item) => (item.textContent || '').includes('/plan'));
        if (!option) return false;
        option.click();
        return true;
      })()`);
      if (!selectedPlanCommand) throw new Error("/plan completion was not available");
      await waitFor(session, "plan command selected", "document.querySelector('textarea[aria-label=\"Message UthCode\"], textarea[aria-label=\"发送给 UthCode\"]')?.value.trim() === '/plan' && !document.querySelector('.command-menu')");
      await evaluateAction(session, "execute plan command", `(() => {
        const element = document.querySelector('textarea[aria-label="Message UthCode"], textarea[aria-label="发送给 UthCode"]');
        if (!element) return false;
        element.focus();
        element.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", bubbles: true }));
        return true;
      })()`);
      await waitFor(session, "plan mode selected", "[...document.querySelectorAll('.runtime-facts dd')].some((item) => (item.textContent || '').trim() === 'PLAN')");
    }
    await setInput(session, "Message UthCode", "cdp fixture request");
    await waitFor(session, "message ready", "(() => { const input = document.querySelector('textarea[aria-label=\"Message UthCode\"], textarea[aria-label=\"发送给 UthCode\"]'); const button = document.querySelector('.composer-actions button:last-child'); return Boolean(input?.value.trim()) && Boolean(button && !button.disabled); })()");
    if (flow === "plan") await installPlanDraftBreakpoint(session);
    await clickSelector(session, ".composer-send");
    if (flow === "ask" || flow === "ask-one") {
      await submitAskUserFlow(session);
    } else if (flow === "tool") {
      await submitToolFlow(session, expectedText);
    } else if (flow === "todo") {
      await submitTodoFlow(session, expectedText);
    } else if (flow === "permission") {
      await waitForInteraction(session, "dynamic Permission surface", '[aria-label="Permission approval"]');
      await capture(session, "permission-pending-control");
      await clickText(session, "Allow once");
      await waitFor(session, `Permission continuation ${expectedText}`, `document.body?.innerText?.includes(${JSON.stringify(expectedText)})`);
      await verifyPermissionActivity(session);
      // This flow verifies the real interaction/activity chain. The other
      // flows retain the broader shell-resize and Settings acceptance matrix.
      if (!skipQuit) await evaluateAction(session, "close isolated permission shell", "window.uthcode.closeShell()");
      return;
    } else if (flow === "plan") {
      await submitPlanFlow(session, expectedText);
    } else if (flow === "failure") {
      await submitFailureFlow(session);
    } else if (flow === "delay") {
      await submitDelayedFlow(session);
    } else if (flow === "sessions") {
      await submitSessionsFlow(session);
    } else if (flow === "commands") {
      await waitFor(session, `Provider output ${expectedText}`, `document.body?.innerText?.includes(${JSON.stringify(expectedText)})`);
      await submitCompactCommand(session);
    } else {
      await waitFor(session, `Provider output ${expectedText}`, `document.body?.innerText?.includes(${JSON.stringify(expectedText)})`);
    }

    await waitFor(session, "Session persisted after first submitted turn", `(() => { const row = document.querySelector('button.session-line.is-selected:not(.new-session-line)'); return Boolean(row && row.innerText.includes('cdp fixture request')); })()`);
    writeLog("assertion_pass", { description: "first user turn created the persistent Session row" });

    // Settings, theme, and runtime panel are exercised through actual DOM
    // controls; no renderer state or IPC protocol is injected by the driver.
    await assertLayoutFocusAndResize(session);
    await clickText(session, "Settings");
    await waitFor(session, "Settings view", "Boolean(document.querySelector('.settings-view'))");
    if (flow !== "visual" && flow !== "shell") await submitSettingsRevealFlow(session);
    await setSelect(session, "theme", "dark");
    await waitFor(session, "dark theme", "document.querySelector('.app-shell')?.classList.contains('theme-dark')");
    await clickText(session, "Back to chat");
    await waitFor(session, "chat after settings", "Boolean(document.querySelector('.composer textarea'))");
    await setSelect(session, "Runtime panel layout", "floating");
    await waitFor(session, "floating runtime panel", "document.querySelector('.app-shell')?.classList.contains('panel-floating')");
    await setSelect(session, "Runtime panel layout", "hidden");
    await waitFor(session, "hidden runtime panel", "document.querySelector('.app-shell')?.classList.contains('panel-hidden')");
    await setSelect(session, "Runtime panel layout", "docked");
    await waitFor(session, "docked runtime panel", "document.querySelector('.app-shell')?.classList.contains('panel-docked')");
    await runResponsiveHealthFlow(session);
    await submitStatusCommand(session);
    await sleep(750);
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
