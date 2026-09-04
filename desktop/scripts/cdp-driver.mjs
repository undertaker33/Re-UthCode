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
const askQuestionCount = Number(option("ask-question-count", "4"));
const planChunkDelayMs = Number(option("plan-chunk-delay-ms", "250"));
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

async function recordScreenshot(session, name, result) {
  if (!screenshotDir) return;
  await mkdir(screenshotDir, { recursive: true });
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
    for (const pageScaleFactor of [1, 1.25, 1.5]) {
      await session.send("Emulation.setPageScaleFactor", { pageScaleFactor });
      await assertResponsiveLayout(session, `responsive layout ${width}px @ ${pageScaleFactor}x reduced motion`);
    }
  }
  await session.send("Emulation.setPageScaleFactor", { pageScaleFactor: 1 });
  await session.send("Emulation.clearDeviceMetricsOverride");
  await session.send("Emulation.setEmulatedMedia", { features: [] });
  writeLog("assertion_pass", { description: "responsive health restored" });
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
  await session.send("Emulation.clearDeviceMetricsOverride");
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
  await waitFor(session, "narrow layout disables separators", "window.innerWidth <= 680 && document.querySelectorAll('[data-resize-side]').length === 0 && document.querySelector('.app-shell')?.classList.contains('panel-docked')");
  const narrow = await evaluateAction(session, "inspect narrow overlay boundary", `(() => ({ runtime: document.querySelector('#runtime-panel')?.getAttribute('aria-hidden') || null, separators: document.querySelectorAll('[data-resize-side]').length, overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1 }))()`);
  if (narrow.separators !== 0 || narrow.overflow) throw new Error(`narrow layout retained resize or overflow: ${JSON.stringify(narrow)}`);
  writeLog("assertion_pass", { description: "narrow layout disables resize and keeps overlay boundary", value: narrow });
  await session.send("Emulation.clearDeviceMetricsOverride");
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
  await assertSingleDomEntity(session, "Tool timeline DOM rows", '.timeline-entry--tool', expectedToolRows);
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

async function submitDelayedFlow(session) {
  await waitFor(session, "delayed turn controls", "Boolean(document.querySelector('button[aria-label=\"Pause\"]')) && Boolean(document.querySelector('button[aria-label=\"Cancel\"]'))");
  await capture(session, "delayed-controls");
  if (delayAction === "cancel") {
    writeLog("action", { action: "click_text", text: "Cancel" });
    await clickText(session, "Cancel");
    await waitFor(session, "delayed turn cancellation", "!document.querySelector('button[aria-label=\"Cancel\"]') && document.body?.innerText?.includes('cancelled')");
    return;
  }
  await clickText(session, "Pause");
  await waitForInteraction(session, "turn pause surface", '[aria-label="Turn paused"]');
  await clickText(session, "Continue");
  await waitFor(session, `continued output ${expectedText}`, `document.body?.innerText?.includes(${JSON.stringify(expectedText)})`);
}

async function submitSessionsFlow(session) {
  await waitFor(session, `first session output ${expectedText}`, `(() => { const text = document.querySelector('[aria-label=\"Chat timeline\"]')?.innerText || ''; return text.includes('cdp fixture request') && text.includes(${JSON.stringify(expectedText)}); })()`);

  const sessionPrompts = ["cdp fixture session two", "cdp fixture session three", "cdp fixture session four", "cdp fixture session five", "cdp fixture session six"];
  for (const [index, prompt] of sessionPrompts.entries()) {
    const ordinal = index + 2;
    await clickText(session, "New chat");
    await waitFor(session, `${ordinal}th conversation header`, "['Session', 'New conversation', '会话', '新对话'].some((value) => document.querySelector('h1')?.textContent?.includes(value))");
    await waitFor(session, `${ordinal}th Session persisted`, "Boolean(document.querySelector('button.session-line:not(.new-session-line)'))");
    await waitFor(session, `${ordinal}th composer ready`, "Boolean(document.querySelector('textarea[aria-label=\"Message UthCode\"], textarea[aria-label=\"发送给 UthCode\"]'))");
    await setInput(session, "Message UthCode", prompt);
    await waitFor(session, `${ordinal}th message ready`, "(() => { const input = document.querySelector('textarea[aria-label=\"Message UthCode\"], textarea[aria-label=\"发送给 UthCode\"]'); const button = document.querySelector('.composer-actions button:last-child'); return Boolean(input?.value.trim()) && Boolean(button && !button.disabled); })()");
    await clickText(session, "Send");
    await waitFor(session, `${ordinal}th session output ${expectedText}`, `(() => { const text = document.querySelector('[aria-label=\"Chat timeline\"]')?.innerText || ''; return text.includes(${JSON.stringify(prompt)}) && text.includes(${JSON.stringify(expectedText)}); })()`);
  }
  await waitFor(session, "session rows beyond five", "document.querySelectorAll('button.session-line:not(.new-session-line)').length >= 6 && [...document.querySelectorAll('button.session-line:not(.new-session-line)')].some((item) => (item.textContent || '').includes('cdp fixture session six')) && [...document.querySelectorAll('button.session-line:not(.new-session-line)')].some((item) => (item.textContent || '').includes('cdp fixture request'))");
  await capture(session, "sessions-over-five");

  writeLog("action", { action: "select_session", label: "cdp fixture session two" });
  const switched = await evaluateAction(session, "select second session", `(() => {
    const rows = [...document.querySelectorAll('button.session-line:not(.new-session-line)')];
    const row = rows.find((item) => (item.textContent || '').includes('cdp fixture session two'));
    if (!row) return false;
    row.click();
    return true;
  })()`);
  if (!switched) throw new Error("second session row not found");
  await waitFor(session, "second session replay", "document.querySelector('[aria-label=\"Chat timeline\"]')?.innerText?.includes('cdp fixture session two')");

  writeLog("action", { action: "select_session", label: "cdp fixture request" });
  const replayed = await evaluateAction(session, "select first session for replay", `(() => {
    const rows = [...document.querySelectorAll('button.session-line:not(.new-session-line)')];
    const row = rows.find((item) => (item.textContent || '').includes('cdp fixture request'));
    if (!row) return false;
    row.click();
    return true;
  })()`);
  if (!replayed) throw new Error("first session row not found");
  await waitFor(session, "first session replay", "document.querySelector('[aria-label=\"Chat timeline\"]')?.innerText?.includes('cdp fixture request')");

  await setInput(session, "Message UthCode", "cdp fixture replay continuation");
  await waitFor(session, "replayed message ready", "(() => { const input = document.querySelector('textarea[aria-label=\"Message UthCode\"], textarea[aria-label=\"发送给 UthCode\"]'); const button = document.querySelector('.composer-actions button:last-child'); return Boolean(input?.value.trim()) && Boolean(button && !button.disabled); })()");
  await clickText(session, "Send");
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
  await waitFor(session, "localized compact terminal", `(() => { const text = document.querySelector('.timeline-notice')?.textContent || ''; return text.includes(${JSON.stringify(expected.heading)}) && ${JSON.stringify(expected.states)}.some((value) => text.includes(value)); })()`);
  const terminal = await evaluateAction(session, "read localized compact terminal", `(() => ({ text: document.querySelector('.timeline-notice')?.textContent?.trim() || '', count: document.querySelectorAll('.timeline-notice').length }))()`);
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
  await evaluateAction(session, "execute status command", `(() => {
    const element = document.querySelector('textarea[aria-label="Message UthCode"], textarea[aria-label="发送给 UthCode"]');
    if (!element) return false;
    element.focus();
    element.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", bubbles: true }));
    return true;
  })()`);
  const expectedNotice = requestedLanguage === "zh-CN" ? "运行时信息" : "Runtime information";
  await waitFor(session, "localized status command output", `Boolean(document.querySelector('.timeline-notice')?.textContent?.includes(${JSON.stringify(expectedNotice)}))`);
  const statusView = await evaluateAction(session, "read typed status projection", `(() => {
    const facts = [...document.querySelectorAll('.runtime-facts > div')].map((row) => ({
      label: row.querySelector('dt')?.textContent?.trim() || '',
      value: row.querySelector('dd')?.textContent?.trim() || '',
    }));
    return {
      notice: document.querySelector('.timeline-notice')?.textContent?.trim() || '',
      noticeCount: document.querySelectorAll('.timeline-notice').length,
      facts,
      body: document.body?.innerText || '',
    };
  })()`);
  const modelLabel = requestedLanguage === "zh-CN" ? "模型" : "Model";
  const model = statusView.facts.find((item) => item.label === modelLabel)?.value;
  if (statusView.noticeCount !== 1 || statusView.notice !== expectedNotice) throw new Error(`typed /status notice is not a single localized message: ${JSON.stringify(statusView.notice)}`);
  if (model !== "fixture/fixture-model") throw new Error(`typed /status safe model param was not projected: ${JSON.stringify(model)}`);
  const forbidden = /RuntimeRequestError|EPERM|native|diagnostic|configuration[_ ]?(?:source|path)|file:\/\/|[A-Za-z]:[\\/]/iu;
  if (forbidden.test(statusView.body)) throw new Error(`typed /status exposed a native/free-form/path/diagnostic value: ${statusView.body}`);
  writeLog("assertion_pass", { description: `typed /status shows safe params only (${requestedLanguage})`, value: { notice: statusView.notice, model, facts: statusView.facts } });
}

async function setInput(session, label, value) {
  remainingBudget(`set input ${label}`);
  writeLog("action", { action: "set_input", label, valueLength: value.length });
  const changed = await evaluateAction(session, `set input ${label}`, `(() => {
    const wanted = ${JSON.stringify(label)};
    const aliases = { "Message UthCode": ["Message UthCode", "发送给 UthCode"] };
    const labels = aliases[wanted] ?? [wanted];
    const element = [...document.querySelectorAll("input,textarea")].find((item) => labels.includes(item.getAttribute("aria-label") || ""));
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
  // Settings persistence is intentionally fire-and-forget in the renderer.
  // Let each real preference write finish before the next DOM control change;
  // otherwise the packaged Windows profile can receive concurrent atomic
  // renames and report an EPERM that is caused by this driver burst.
  await sleep(300);
}

async function bodyText(session) {
  return evaluateAction(session, "read Renderer body", "document.body?.innerText || \"\"");
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
    if (flow !== "visual-fixture" && flow !== "visual") {
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
      // keeps the packaged acceptance boundary identical for en/zh and lets
      // the runner remove its bootstrap seed only after the fresh document
      // has consumed it.
      const previousDocumentOrigin = await evaluateAction(session, "read document origin before language reload", "performance.timeOrigin");
      await session.send("Page.reload", { ignoreCache: true });
      await waitFor(session, "UthCode shell after language reload", `performance.timeOrigin !== ${JSON.stringify(previousDocumentOrigin)} && document.readyState === 'complete' && Boolean(document.querySelector('.sidebar'))`);
      await waitFor(session, "Composer after language reload", "document.readyState === 'complete' && Boolean(document.querySelector('.composer textarea'))");
      observedLanguage = await evaluateAction(session, "read requested language", "typeof window.uthcode?.readPreference === \"function\" ? window.uthcode.readPreference(\"language\") : null");
      if (!observedLanguage) throw new Error("language preference read API is unavailable in the packaged Renderer");
      if (observedLanguage !== requestedLanguage) throw new Error(`requested language ${requestedLanguage} was not observed: ${observedLanguage}`);
      writeLog("assertion_pass", { description: "read requested language", value: observedLanguage });
      if (flow !== "visual-fixture" && flow !== "visual") {
        await waitFor(session, "Runtime ready after language reload", "(() => { const text = document.querySelector('.runtime-panel h2')?.textContent || ''; return text.includes('Ready') || text.includes('就绪'); })()");
        await waitFor(session, "restored Project", "Boolean(document.querySelector('button.project-select'))");
        await waitFor(session, "new Session action", "Boolean(document.querySelector('button.new-session-line'))");
      }
      // Give the packaged runner time to remove its bootstrap-only preference
      // seed after the language boundary, before the first durable UI mutation.
      await sleep(250);
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
    await waitFor(session, "new conversation header", "['Session', 'New conversation', '会话', '新对话'].some((value) => document.querySelector('h1')?.textContent?.includes(value))");
    await waitFor(session, "new Session persisted", "Boolean(document.querySelector('button.session-line:not(.new-session-line)'))");
    await assertCommandCandidate(session, "/new");
    await assertCommandCandidate(session, "/do");
    await assertCommandCandidate(session, "/mod", "/model");
    await assertCommandCandidate(session, "/model ", "fixture/fixture-model");
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
    await clickText(session, "Send");
    if (flow === "ask" || flow === "ask-one") {
      await submitAskUserFlow(session);
    } else if (flow === "tool") {
      await submitToolFlow(session, expectedText);
    } else if (flow === "todo") {
      await submitTodoFlow(session, expectedText);
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
    } else if (flow === "commands") {
      await waitFor(session, `Provider output ${expectedText}`, `document.body?.innerText?.includes(${JSON.stringify(expectedText)})`);
      await submitCompactCommand(session);
    } else {
      await waitFor(session, `Provider output ${expectedText}`, `document.body?.innerText?.includes(${JSON.stringify(expectedText)})`);
    }

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
