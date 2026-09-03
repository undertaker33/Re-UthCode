import { spawn, spawnSync } from "node:child_process";
import { mkdir, mkdtemp, rm, stat, writeFile } from "node:fs/promises";
import net from "node:net";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import WebSocket from "ws";

const root = resolve(import.meta.dirname, "..");
const output = resolve(root, "dist/ui-acceptance/prompt-2");
const browser = process.env.UTHCODE_ACCEPTANCE_BROWSER || "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const failureStage = process.argv.includes("--fail-after-connect");
const cleanupReportIndex = process.argv.indexOf("--cleanup-report");
const cleanupReport = cleanupReportIndex >= 0 ? process.argv[cleanupReportIndex + 1] : undefined;
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const freePort = () => new Promise((done, fail) => {
  const server = net.createServer();
  server.once("error", fail);
  server.listen(0, "127.0.0.1", () => {
    const address = server.address();
    server.close((error) => error ? fail(error) : done(address.port));
  });
});

const port = await freePort();
const profile = await mkdtemp(resolve(tmpdir(), "uthcode-t04-cdp-"));
const fixtureUrl = (theme = "dark", language, harness) => {
  const query = new URLSearchParams({ theme });
  if (language) query.set("lang", language);
  if (harness) query.set("harness", harness);
  return `${pathToFileURL(resolve(output, "index.html")).href}?${query}`;
};
let child;
let socket;
let sequence = 0;
const pending = new Map();
const consoleErrors = [];
let browserClosed = false;
let cleanupError;

function rejectPending(error) { for (const request of pending.values()) request.reject(error); pending.clear(); }
function waitForExit(process, timeoutMs) {
  if (!process || process.exitCode !== null || process.signalCode !== null) return Promise.resolve(true);
  return new Promise((done) => {
    const timer = setTimeout(() => { process.off("exit", exited); done(false); }, timeoutMs);
    const exited = () => { clearTimeout(timer); done(true); };
    process.once("exit", exited);
  });
}
function send(method, params = {}, timeoutMs = 5_000) {
  if (!socket || socket.readyState !== WebSocket.OPEN) return Promise.reject(new Error(`CDP socket is not open for ${method}`));
  return new Promise((resolveRequest, rejectRequest) => {
    const id = ++sequence;
    const timer = setTimeout(() => { pending.delete(id); rejectRequest(new Error(`CDP request timed out: ${method}`)); }, timeoutMs);
    pending.set(id, { resolve: (value) => { clearTimeout(timer); resolveRequest(value); }, reject: (error) => { clearTimeout(timer); rejectRequest(error); } });
    socket.send(JSON.stringify({ id, method, params }), (error) => {
      if (!error) return;
      const request = pending.get(id);
      pending.delete(id);
      request?.reject(error);
    });
  });
}
async function evaluate(expression) {
  const response = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (response.exceptionDetails) throw new Error(response.exceptionDetails.text);
  return response.result.value;
}
async function wait(expression) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (await evaluate(`Boolean(${expression})`)) return;
    await sleep(50);
  }
  throw new Error(`condition failed: ${expression}`);
}
async function navigate(theme, language, harness) {
  await send("Page.navigate", { url: fixtureUrl(theme, language, harness) });
  const readySelector = harness === "select" ? "document.querySelector('[aria-label=\\\"Acceptance select\\\"]')" : harness === "chat" ? "document.querySelector('.timeline')" : "document.querySelector('.settings-view')";
  await wait(`document.documentElement.dataset.fixture==='prompt-2-settings' && ${readySelector}`);
}
async function click(selector) {
  await evaluate(`document.querySelector(${JSON.stringify(selector)})?.click()`);
  await sleep(80);
}
async function setInput(selector, value) {
  await evaluate(`(()=>{const element=document.querySelector(${JSON.stringify(selector)});if(!element)throw new Error('missing input');const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')?.set;if(!setter)throw new Error('input setter unavailable');element.focus();setter.call(element,${JSON.stringify(value)});element.dispatchEvent(new Event('input',{bubbles:true}));element.dispatchEvent(new Event('change',{bubbles:true}));element.dispatchEvent(new KeyboardEvent('keyup',{bubbles:true,key:'Unidentified'}));})()`);
  await sleep(60);
}
async function capture(name, width, height, condition = "true") {
  await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
  await wait(condition);
  await sleep(100);
  const shot = await send("Page.captureScreenshot", { format: "png", fromSurface: true });
  const path = resolve(output, `${name}.png`);
  await writeFile(path, Buffer.from(shot.data, "base64"));
  process.stdout.write(`screenshot ${name}.png ${width}x${height} ${(await stat(path)).size} bytes\n`);
}
async function openProvider(name) {
  await evaluate(`([...document.querySelectorAll('.provider-row')].find((row)=>row.querySelector('strong')?.textContent===${JSON.stringify(name)})||document.querySelector('.provider-row'))?.click()`);
  await wait("document.querySelector('.settings-editor-modal[data-settings-editor-step=provider]') && document.activeElement?.id==='modal-provider-display-name'");
}
async function closeWorkerBrowser() {
  if (socket?.readyState === WebSocket.OPEN) {
    try { await send("Browser.close", {}, 1_000); browserClosed = true; } catch {}
  }
  rejectPending(new Error("CDP acceptance cleanup"));
  if (socket && socket.readyState !== WebSocket.CLOSED) socket.terminate();
  if (process.platform === "win32" && child?.pid) spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { windowsHide: true, stdio: "ignore" });
  const exited = await waitForExit(child, 1_500);
  if (!exited && child && child.exitCode === null && child.signalCode === null) {
    child.kill("SIGTERM");
    if (!(await waitForExit(child, 1_500))) child.kill("SIGKILL");
  }
}
async function removeProfile() {
  let lastError;
  for (let attempt = 0; attempt < 30; attempt += 1) {
    try { await rm(profile, { recursive: true, force: true }); return; }
    catch (error) { lastError = error; await sleep(100); }
  }
  throw lastError;
}

try {
  await mkdir(output, { recursive: true });
  child = spawn(browser, [`--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, "--no-first-run", "--disable-default-apps", "--disable-extensions", "--edge-skip-compat-layer-relaunch", "--headless=new", fixtureUrl()], { stdio: ["ignore", "pipe", "pipe"] });
  let stderr = "";
  child.stderr.on("data", (chunk) => { stderr += String(chunk); });
  let target;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (child.exitCode !== null) throw new Error(`acceptance browser exited early (${child.exitCode}): ${stderr}`);
    try {
      const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`, { signal: AbortSignal.timeout(500) })).json();
      target = targets.find((item) => item.type === "page" && item.url.includes("index.html"));
      if (target) break;
    } catch {}
    await sleep(100);
  }
  if (!target) throw new Error(`acceptance target unavailable on dynamic port ${port}: ${stderr}`);
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((done, fail) => { socket.once("open", done); socket.once("error", fail); });
  socket.on("message", (raw) => {
    const message = JSON.parse(String(raw));
    if (message.id) {
      const request = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) request?.reject(new Error(message.error.message)); else request?.resolve(message.result);
    } else if (message.method === "Runtime.consoleAPICalled" && message.params.type === "error") consoleErrors.push(message.params.args.map((item) => item.value || item.description).join(" "));
    else if (message.method === "Runtime.exceptionThrown") consoleErrors.push(message.params.exceptionDetails.text);
  });
  socket.once("close", () => rejectPending(new Error("CDP socket closed")));
  socket.once("error", (error) => rejectPending(error));
  if (failureStage) throw new Error("injected failure after CDP connect");
  await send("Runtime.enable");
  await send("Page.enable");

  await wait("document.querySelector('.settings-view')");
  await capture("settings-dark-zh", 1280, 900);
  await navigate("light", "en");
  await capture("settings-light-en", 1280, 900);
  await navigate("dark", "zh-CN");
  await capture("settings-narrow-zh", 720, 900);

  await openProvider("multi");
  await capture("provider-modal-dark-zh", 1280, 900, "document.querySelector('.settings-editor-modal')");
  const modalA11y = await evaluate(`(()=>{const modal=document.querySelector('.settings-editor-modal');return{oneRoot:document.querySelectorAll('.settings-editor-modal').length===1,oneDialog:document.querySelectorAll('[role=dialog]').length===1,ariaModal:modal?.getAttribute('aria-modal')==='true',backgroundInert:[...document.querySelectorAll('.settings-nav,.settings-content')].every(x=>x.hasAttribute('inert')&&x.getAttribute('aria-hidden')==='true'),focus:document.activeElement?.id==='modal-provider-display-name'}})()`);
  if (Object.values(modalA11y).some((value) => !value)) throw new Error(`modal a11y failed ${JSON.stringify(modalA11y)}`);
  await click('button[aria-label$="Slash"]');
  await wait("document.querySelector('.settings-editor-modal[data-settings-editor-step=model]')");
  const modelStep = await evaluate(`(()=>({oneRoot:document.querySelectorAll('.settings-editor-modal').length===1,oneDialog:document.querySelectorAll('[role=dialog]').length===1,modelStep:document.querySelector('.settings-editor-modal')?.getAttribute('data-settings-editor-step')==='model',remote:!!document.querySelector('.settings-editor-modal input[id$='+'"-remote"'+']')}))()`);
  if (Object.values(modelStep).some((value) => !value)) throw new Error(`model step failed ${JSON.stringify(modelStep)}`);
  await click('.settings-editor-modal[data-settings-editor-step=model] footer button:nth-child(2)');
  await wait("document.querySelector('.settings-editor-modal[data-settings-editor-step=provider]')");
  await setInput("#modal-base-url", " https://draft.invalid ");
  await evaluate("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}))");
  await wait("!document.querySelector('.settings-editor-modal')");
  const cancelRollback = await evaluate("document.activeElement?.classList.contains('provider-row')");
  if (!cancelRollback) throw new Error("Provider transaction did not return focus after Escape");
  await openProvider("multi");
  const rollbackValue = await evaluate("document.querySelector('#modal-base-url')?.value");
  if (rollbackValue !== "") throw new Error(`Cancel did not roll back Provider draft: ${rollbackValue}`);
  await click('.settings-editor-modal[data-settings-editor-step=provider] footer button:nth-last-child(2)');

  await openProvider("openai");
  await click('#modal-api-key + button');
  await wait("document.querySelector('#modal-api-key')?.value==='env:W04_FIXTURE_KEY'");
  await evaluate("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}))");
  await wait("!document.querySelector('.settings-editor-modal')");
  await openProvider("openai");
  const revealLifecycle = await evaluate("document.querySelector('#modal-api-key')?.value==='' && document.querySelector('#modal-api-key')?.type==='password'");
  if (!revealLifecycle) throw new Error("revealed API key survived modal close");
  await click('.settings-editor-modal[data-settings-editor-step=provider] footer button:nth-last-child(2)');

  await openProvider("empty");
  await setInput("#modal-api-key", "replacement-key");
  await click('.settings-editor-modal[data-settings-editor-step=provider] footer button:last-child');
  await click('.settings-actions .save-button');
  await wait("window.fixtureEvidence.saves.some((item)=>item?.providers?.empty?.api_key==='replacement-key')");
  const replacementWrite = await evaluate("window.fixtureEvidence.saves.some((item)=>item?.providers?.empty?.api_key==='replacement-key') && !JSON.stringify(window.fixtureEvidence.saves.at(-1)).includes('env:W04_FIXTURE_KEY')");
  if (!replacementWrite) throw new Error("explicit replacement did not produce the narrow key-bearing write");

  await navigate("dark", "en", "chat");
  await wait("document.querySelector('.timeline')?.scrollHeight > document.querySelector('.timeline')?.clientHeight + 100");
  const chatScroll = await evaluate("(()=>{const timeline=document.querySelector('.timeline');if(!timeline)throw new Error('chat timeline missing');timeline.scrollTop=500;timeline.dispatchEvent(new Event('scroll',{bubbles:true}));return{scrollTop:timeline.scrollTop,scrollHeight:timeline.scrollHeight,clientHeight:timeline.clientHeight}})()");
  await click("#fixture-chat-add");
  await wait("document.querySelector('[data-new-messages]')");
  const chatGeometry = await evaluate("(()=>{const timeline=document.querySelector('.timeline');const button=document.querySelector('[data-new-messages]');if(!timeline||!button)throw new Error('new-message button missing');const timelineRect=timeline.getBoundingClientRect();const buttonRect=button.getBoundingClientRect();const style=getComputedStyle(button);return{scrollTop:timeline.scrollTop,remaining:timeline.scrollHeight-timeline.clientHeight-timeline.scrollTop,top:style.top,bottom:style.bottom,buttonTop:buttonRect.top,buttonBottom:buttonRect.bottom,timelineTop:timelineRect.top,timelineBottom:timelineRect.bottom,visible:buttonRect.top>=timelineRect.top&&buttonRect.bottom<=timelineRect.bottom}})()");
  if (chatScroll.scrollTop < 500 || chatGeometry.remaining <= 72 || chatGeometry.top === "auto" || chatGeometry.buttonTop < chatGeometry.timelineTop || chatGeometry.buttonBottom > chatGeometry.timelineBottom || !chatGeometry.visible) throw new Error(`new-message geometry failed ${JSON.stringify({ chatScroll, chatGeometry })}`);

  await navigate("dark", undefined, "app");
  const languagePersisted = await evaluate(`(async()=>{const tick=()=>new Promise(r=>setTimeout(r,0));const trigger=[...document.querySelectorAll('.custom-select__trigger')].find(x=>x.getAttribute('aria-label')==='语言');if(!trigger)return false;const initial=window.fixtureEvidence.preferences.language==='zh-CN';trigger.click();await tick();[...document.querySelectorAll('[role=option]')].find(x=>x.textContent==='English')?.click();await tick();return initial&&window.fixtureEvidence.writes.some(x=>x[0]==='language'&&x[1]==='en')})()`);
  if (!languagePersisted) throw new Error("DesktopApi language write did not reach the fixture");
  const structure = await evaluate(`({sidebars:document.querySelectorAll('.settings-nav').length,providers:document.querySelectorAll('.provider-row').length,modal:document.querySelectorAll('.settings-editor-modal').length,rawHtml:document.body.innerHTML.includes('<script>'),replacement:document.body.innerText.includes('�')})`);
  if (structure.sidebars !== 1 || structure.providers !== 3 || structure.modal !== 0 || structure.rawHtml || structure.replacement) throw new Error(`structure failed ${JSON.stringify(structure)}`);
  if (consoleErrors.length) throw new Error(`console errors ${JSON.stringify(consoleErrors)}`);
  process.stdout.write(`dynamic_port ${port}\nmodal_a11y ${JSON.stringify(modalA11y)}\nmodel_step ${JSON.stringify(modelStep)}\ncancel_rollback ${cancelRollback}\nreveal_lifecycle ${revealLifecycle}\nreplacement_write ${replacementWrite}\nchat_scroll ${JSON.stringify(chatScroll)}\nchat_geometry ${JSON.stringify(chatGeometry)}\nlanguage_hydrate ${languagePersisted}\nstructure ${JSON.stringify(structure)}\nconsole_errors []\n`);
  await writeFile(resolve(output, "acceptance-report.json"), JSON.stringify({ browser, port, profile, modalA11y, modelStep, cancelRollback, revealLifecycle, replacementWrite, chatScroll, chatGeometry, languagePersisted, structure, consoleErrors }, null, 2));
} finally {
  try { await closeWorkerBrowser(); } catch (error) { cleanupError = error; }
  try { await removeProfile(); } catch (error) { cleanupError ??= error; }
  if (cleanupReport) await writeFile(cleanupReport, JSON.stringify({ profile, profileRemoved: true, childExited: !child || child.exitCode !== null || child.signalCode !== null, socketClosed: !socket || socket.readyState === WebSocket.CLOSED, pendingRequests: pending.size, browserClosed, cleanupError: cleanupError ? String(cleanupError) : null }));
  if (cleanupError) throw cleanupError;
}
