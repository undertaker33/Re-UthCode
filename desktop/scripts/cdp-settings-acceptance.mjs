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
const failureStage = process.argv.includes("--fail-after-connect") ? "after-connect" : undefined;
const cleanupReportIndex = process.argv.indexOf("--cleanup-report");
const cleanupReport = cleanupReportIndex >= 0 ? process.argv[cleanupReportIndex + 1] : undefined;
const requestTimeoutMs = 5_000;
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const freePort = () => new Promise((done, fail) => {
  const server = net.createServer();
  server.once("error", fail);
  server.listen(0, "127.0.0.1", () => {
    const address = server.address();
    server.close((error) => error ? fail(error) : done(address.port));
  });
});

await mkdir(output, { recursive: true });
const port = await freePort();
const profile = await mkdtemp(resolve(tmpdir(), "uthcode-prompt2-cdp-"));
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

function rejectPending(error) {
  for (const request of pending.values()) request.reject(error);
  pending.clear();
}
function waitForExit(process, timeoutMs) {
  if (!process || process.exitCode !== null || process.signalCode !== null) return Promise.resolve(true);
  return new Promise((done) => {
    const timer = setTimeout(() => { process.off("exit", exited); done(false); }, timeoutMs);
    const exited = () => { clearTimeout(timer); done(true); };
    process.once("exit", exited);
  });
}
function send(method, params = {}, timeoutMs = requestTimeoutMs) {
  if (!socket || socket.readyState !== WebSocket.OPEN) return Promise.reject(new Error(`CDP socket is not open for ${method}`));
  return new Promise((resolveRequest, rejectRequest) => {
    const id = ++sequence;
    const timer = setTimeout(() => {
      pending.delete(id);
      rejectRequest(new Error(`CDP request timed out: ${method}`));
    }, timeoutMs);
    pending.set(id, {
      resolve: (value) => { clearTimeout(timer); resolveRequest(value); },
      reject: (error) => { clearTimeout(timer); rejectRequest(error); },
    });
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
  await wait(`document.documentElement.dataset.fixture==='prompt-2-settings' && ${harness === "select" ? "document.querySelector('[aria-label=\\\"Acceptance select\\\"]')" : "document.querySelector('.settings-view')"}`);
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
async function closeWorkerBrowser() {
  if (socket?.readyState === WebSocket.OPEN) {
    try { await send("Browser.close", {}, 1_000); browserClosed = true; } catch {}
  }
  rejectPending(new Error("CDP acceptance cleanup"));
  if (socket && socket.readyState !== WebSocket.CLOSED) socket.terminate();
  if (process.platform === "win32" && child?.pid) {
    // PID is the process spawned above with this worker's exact temporary
    // profile. /T cannot select or affect an unrelated browser tree.
    spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { windowsHide: true, stdio: "ignore" });
  }
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
  if (failureStage === "after-connect") throw new Error("injected failure after CDP connect");

  await send("Runtime.enable"); await send("Page.enable"); await wait("document.querySelector('.settings-view')");
  await capture("settings-dark-zh", 1280, 900); await navigate("dark", "en"); await capture("settings-dark-en", 1280, 900);
  await navigate("light", "zh-CN"); await capture("settings-light-zh", 1280, 900); await navigate("dark", "zh-CN"); await capture("settings-narrow-zh", 720, 900);
  await navigate("dark", undefined, "select");
  const select = await evaluate(`(async()=>{const tick=()=>new Promise(r=>setTimeout(r,0)),key=async(el,k,shiftKey=false)=>{el.dispatchEvent(new KeyboardEvent('keydown',{key:k,shiftKey,bubbles:true}));await tick()},trigger=document.querySelector('[aria-label="Acceptance select"]'),identity=trigger;trigger.focus();trigger.click();await tick();const initialEnabled=document.activeElement?.textContent==='Alpha';const ids=[...document.querySelectorAll('[role=listbox]')].map(x=>x.id);await key(document.activeElement,'End');const end=document.activeElement?.textContent==='Omega';await key(document.activeElement,'Home');const home=document.activeElement?.textContent==='Alpha';await key(document.activeElement,'Escape');await key(trigger,'Enter');const enterOpen=trigger.getAttribute('aria-expanded')==='true';await key(document.activeElement,'ArrowDown');await key(document.activeElement,'Enter');const selectedFocus=document.activeElement===trigger&&trigger.textContent.includes('Beta');await key(trigger,' ');const spaceOpen=trigger.getAttribute('aria-expanded')==='true';await key(document.activeElement,'Escape');const escapeClosed=trigger.getAttribute('aria-expanded')==='false'&&document.activeElement===trigger;trigger.click();await tick();document.activeElement.dispatchEvent(new FocusEvent('blur',{bubbles:true,relatedTarget:document.querySelector('#after')}));document.querySelector('#after').focus();await tick();const focusoutClosed=trigger.getAttribute('aria-expanded')==='false'&&document.activeElement.id==='after';trigger.click();await tick();document.body.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}));await tick();const outsideClosed=trigger.getAttribute('aria-expanded')==='false';trigger.focus();trigger.click();await tick();await key(document.activeElement,'Tab');document.querySelector('#after').focus();await tick();const tabClosed=trigger.getAttribute('aria-expanded')==='false'&&document.activeElement.id==='after';trigger.focus();trigger.click();await tick();await key(document.activeElement,'Tab',true);document.querySelector('#before').focus();await tick();const shiftTabClosed=trigger.getAttribute('aria-expanded')==='false'&&document.activeElement.id==='before';return{initialEnabled,end,home,enterOpen,selectedFocus,spaceOpen,escapeClosed,focusoutClosed,outsideClosed,tabClosed,shiftTabClosed,uniqueIds:new Set(ids).size===ids.length,identityStable:trigger===identity}})()`);
  if (Object.values(select).some((value) => !value)) throw new Error(`select failed ${JSON.stringify(select)}`);
  await navigate("dark", undefined, "app");
  const languagePersisted = await evaluate(`(async()=>{const tick=()=>new Promise(r=>setTimeout(r,0));await tick();const initial=window.fixtureEvidence.reads.includes('language')&&window.fixtureEvidence.preferences.language==='zh-CN',trigger=[...document.querySelectorAll('.custom-select__trigger')].find(x=>x.getAttribute('aria-label')==='语言');trigger.click();await tick();[...document.querySelectorAll('[role=option]')].find(x=>x.textContent==='English').click();await tick();return initial&&window.fixtureEvidence.writes.some(x=>x[0]==='language'&&x[1]==='en')&&document.body.innerText.includes('Settings')})()`);
  if (!languagePersisted) throw new Error("DesktopApi language read/write hydrate failed");
  await navigate("dark", undefined, "app");
  const languageRestarted = await evaluate("window.fixtureEvidence.reads.includes('language') && window.fixtureEvidence.preferences.language==='en' && document.querySelector('.settings-view')?.getAttribute('aria-label')==='Settings'");
  if (!languageRestarted) throw new Error("fixture language preference did not survive remount/reload");
  await navigate("dark", "zh-CN");
  const open = async (id = "openai") => { await evaluate(`([...document.querySelectorAll('.provider-row')].find(x=>x.querySelector('strong')?.textContent===${JSON.stringify(id)})||document.querySelector('.provider-row')).click()`); await wait("document.querySelector('.provider-modal') && document.activeElement===document.querySelector('#modal-provider')"); };
  await open(); await capture("provider-modal-dark-zh", 1280, 900, "document.querySelector('.provider-modal')");
  const modalA11y = await evaluate(`(async()=>{const tick=()=>new Promise(r=>setTimeout(r,0));document.querySelector('.provider-modal header button').click();await tick();[...document.querySelectorAll('.provider-row')].find(x=>x.querySelector('strong')?.textContent==='multi').click();await tick();const modal=document.querySelector('.provider-modal'),initial=document.activeElement===document.querySelector('#modal-provider'),inert=document.querySelector('.settings-nav').inert&&document.querySelector('.settings-content').inert&&document.querySelector('.settings-nav').getAttribute('aria-hidden')==='true';document.querySelector('.settings-advanced summary').click();await tick();const labels=[...modal.querySelectorAll('label[for]')],ids=[...modal.querySelectorAll('[id]')].map(x=>x.id),labelsValid=labels.every(x=>{const matches=modal.querySelectorAll('#'+CSS.escape(x.htmlFor));return matches.length===1})&&new Set(ids).size===ids.length,focusable=[...modal.querySelectorAll('button:not([disabled]),input:not([disabled]),summary,[tabindex]:not([tabindex="-1"])')].filter(x=>!x.hidden),first=focusable[0],last=focusable.at(-1);last.focus();document.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',bubbles:true}));await tick();const forwardTrap=document.activeElement===first;first.focus();document.dispatchEvent(new KeyboardEvent('keydown',{key:'Tab',shiftKey:true,bubbles:true}));await tick();const reverseTrap=document.activeElement===last;return{initial,inert,labelsValid,forwardTrap,reverseTrap}})()`);
  if (Object.values(modalA11y).some((value) => !value)) throw new Error(`modal a11y failed ${JSON.stringify(modalA11y)}`);
  const nestedEscape = await evaluate(`(async()=>{const tick=()=>new Promise(r=>setTimeout(r,0)),set=(el,value)=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,value);el.dispatchEvent(new Event('input',{bubbles:true}))},edit=[...document.querySelectorAll('.provider-row')].find(x=>x.querySelector('strong')?.textContent==='multi'),base=document.querySelector('#modal-base-url'),reasoning=[...document.querySelectorAll('.settings-advanced .custom-select__trigger')][0];set(base,'https://draft.invalid');reasoning.click();await tick();document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));await tick();const firstOnlyClosed=!!document.querySelector('.provider-modal')&&reasoning.getAttribute('aria-expanded')==='false'&&document.activeElement===reasoning&&document.querySelector('#modal-base-url').value==='https://draft.invalid';reasoning.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));await tick();const secondCancelled=!document.querySelector('.provider-modal')&&document.activeElement===edit;edit.click();await tick();const restored=document.querySelector('#modal-base-url').value==='';document.querySelector('.provider-modal header button').click();await tick();[...document.querySelectorAll('.provider-row')].find(x=>x.querySelector('strong')?.textContent==='openai').click();await tick();return{firstOnlyClosed,secondCancelled,restored}})()`);
  if (Object.values(nestedEscape).some((value) => !value)) throw new Error(`nested Escape failed ${JSON.stringify(nestedEscape)}`);
  const modalFocus = await evaluate(`(async()=>{const edit=[...document.querySelectorAll('.provider-row')].find(x=>x.querySelector('strong')?.textContent==='openai'),input=document.querySelector('#modal-api-key'),setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;setter.call(input,'cancel-secret');input.dispatchEvent(new Event('input',{bubbles:true}));document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));await new Promise(r=>setTimeout(r,0));const restored=!document.querySelector('.provider-modal')&&!document.querySelector('.settings-nav').inert&&document.querySelector('.settings-nav').getAttribute('aria-hidden')===null&&document.activeElement===edit;edit.click();await new Promise(r=>setTimeout(r,0));return restored&&document.querySelector('#modal-api-key').value===''})()`);
  if (!modalFocus) throw new Error("modal focus return failed");
  const modalCrud = await evaluate(`(async()=>{const tick=()=>new Promise(r=>setTimeout(r,0)),set=(el,value)=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,value);el.dispatchEvent(new Event('input',{bubbles:true}))},close=()=>document.querySelector('.provider-modal header button').click();close();await tick();const empty=[...document.querySelectorAll('.provider-row')].find(x=>x.querySelector('strong')?.textContent==='empty');empty.click();await tick();const zeroFields=!!document.querySelector('#modal-new-model-ref')&&!!document.querySelector('#modal-model');set(document.querySelector('#modal-new-model-ref'),'empty/first');set(document.querySelector('#modal-model'),'empty-model');document.querySelector('.provider-modal footer button[title="应用"]').click();await tick();const applyNoSave=window.fixtureEvidence.saves.length===0;empty.click();await tick();const created=document.querySelector('#modal-model')?.value==='empty-model';close();await tick();empty.click();await tick();set(document.querySelector('#modal-api-key'),'backdrop-secret');document.querySelector('.provider-modal-backdrop').dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));await tick();empty.click();await tick();const backdropCancel=document.querySelector('#modal-api-key').value==='';close();await tick();return{zeroFields,applyNoSave,created,backdropCancel}})()`);
  if (Object.values(modalCrud).some((value) => !value)) throw new Error(`modal CRUD failed ${JSON.stringify(modalCrud)}`);
  const advancedCrud = await evaluate(`(async()=>{const tick=()=>new Promise(r=>setTimeout(r,0)),set=(el,value)=>{Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,value);el.dispatchEvent(new Event('input',{bubbles:true}))},row=id=>[...document.querySelectorAll('.provider-row')].find(x=>x.querySelector('strong')?.textContent===id),apply=()=>document.querySelector('.provider-modal footer button:last-child').click(),save=async()=>{document.querySelector('.save-button').click();await tick();return window.fixtureEvidence.saves.at(-1)?.request||window.fixtureEvidence.saves.at(-1)?.request?.request||window.fixtureEvidence.saves.at(-1)};row('multi').click();await tick();document.querySelector('.settings-advanced summary').click();await tick();const before=[...document.querySelectorAll('.settings-advanced fieldset')].length;document.querySelector('.settings-advanced>button').click();await tick();const addBound=[...document.querySelectorAll('.settings-advanced fieldset')].length===before+1;const profile=document.querySelector('#modal-profile-id');set(profile,'multi-renamed');profile.dispatchEvent(new FocusEvent('focusout',{bubbles:true}));await tick();set(document.querySelector('#modal-api-key'),'applied-key');apply();await tick();const firstSave=await save();const renamed=firstSave?.providers?.['multi-renamed']!==undefined&&firstSave?.provider_renames?.multi==='multi-renamed';const keyApplied=firstSave?.providers?.['multi-renamed']?.api_key==='applied-key';const addedModel=Object.values(firstSave?.models||{}).some(x=>x.provider_profile_id==='multi-renamed');row('multi-renamed').click();await tick();document.querySelector('.provider-modal .danger').click();await tick();apply();await tick();const secondSave=await save();const providerDeleted=secondSave?.providers?.['multi-renamed']===undefined&&!Object.values(secondSave?.models||{}).some(x=>x.provider_profile_id==='multi-renamed')&&secondSave?.default_model==='openai/codex';return{addBound,renamed,keyApplied,addedModel,providerDeleted}})()`);
  if (Object.values(advancedCrud).some((value) => !value)) throw new Error(`advanced CRUD failed ${JSON.stringify(advancedCrud)}`);
  await navigate("light", "en"); await open(); await capture("provider-modal-light-en", 1280, 900, "document.querySelector('.provider-modal')");
  const structure = await evaluate(`({sidebars:document.querySelectorAll('.settings-nav').length,runtime:document.body.innerText.includes('Runtime'),providers:document.querySelectorAll('.provider-row').length,models:[...document.querySelectorAll('h2')].some(x=>x.textContent==='Models'),rows:document.querySelectorAll('.provider-modal__body>.settings-row').length,advanced:document.querySelector('.settings-advanced').open,subtitle:document.querySelector('.settings-content>header p')?.textContent||'',overflow:document.documentElement.scrollWidth>document.documentElement.clientWidth,replacement:document.body.innerText.includes('�')})`);
  if (structure.sidebars !== 1 || structure.runtime || structure.providers !== 3 || structure.models || structure.rows !== 4 || structure.advanced || structure.subtitle || structure.overflow || structure.replacement) throw new Error(`structure failed ${JSON.stringify(structure)}`);
  if (consoleErrors.length) throw new Error(`console errors ${JSON.stringify(consoleErrors)}`);
  process.stdout.write(`dynamic_port ${port}\ncustom-select ${JSON.stringify(select)}\nlanguage_hydrate ${languagePersisted}\nlanguage_restart ${languageRestarted}\nmodal_a11y ${JSON.stringify(modalA11y)}\nnested_escape ${JSON.stringify(nestedEscape)}\nmodal_focus ${modalFocus}\nmodal_crud ${JSON.stringify(modalCrud)}\nadvanced_crud ${JSON.stringify(advancedCrud)}\nstructure ${JSON.stringify(structure)}\nconsole_errors []\n`);
  await writeFile(resolve(output, "acceptance-report.json"), JSON.stringify({ browser, port, profile, select, languagePersisted, languageRestarted, modalA11y, nestedEscape, modalFocus, modalCrud, advancedCrud, structure, consoleErrors }, null, 2));
} finally {
  try { await closeWorkerBrowser(); } catch (error) { cleanupError = error; }
  try { await removeProfile(); } catch (error) { cleanupError ??= error; }
  if (cleanupReport) await writeFile(cleanupReport, JSON.stringify({ profile, profileRemoved: true, childExited: !child || child.exitCode !== null || child.signalCode !== null, socketClosed: !socket || socket.readyState === WebSocket.CLOSED, pendingRequests: pending.size, browserClosed, cleanupError: cleanupError ? String(cleanupError) : null }));
  if (cleanupError) throw cleanupError;
}
