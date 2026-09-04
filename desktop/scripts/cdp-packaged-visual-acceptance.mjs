#!/usr/bin/env node

/**
 * Run the existing CDP acceptance flows against a packaged Electron executable.
 *
 * This runner owns every process and temporary profile it creates.  It uses
 * the launcher context API instead of putting a launcher wrapper between the
 * runner and Electron, so cleanup remains reachable even when a child is
 * stopped on Windows.  The report is assembled from the driver's actual CDP
 * events, screenshots, and process exit results.
 */

import { spawn, spawnSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { access, mkdir, mkdtemp, readFile, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { join, resolve as resolvePath, win32 } from "node:path";
import { createIsolatedCdpContext } from "./cdp-launcher.mjs";

const desktopRoot = fileURLToPath(new URL("../", import.meta.url));
const workspaceRoot = resolvePath(fileURLToPath(new URL("../../", import.meta.url)));
const driverPath = fileURLToPath(new URL("./cdp-driver.mjs", import.meta.url));
const fixturePath = fileURLToPath(new URL("./cdp-openai-fixture.mjs", import.meta.url));
const providerFlows = new Set(["stream", "tool", "todo", "ask", "ask-one", "permission", "plan", "failure", "delay", "sessions"]);
const commandFlows = new Set(["commands"]);

function option(name, fallback = undefined) {
  const index = process.argv.indexOf(`--${name}`);
  return index >= 0 ? process.argv[index + 1] ?? fallback : fallback;
}

function requiredOption(name, fallback = undefined) {
  const value = option(name, fallback);
  if (!value) throw new Error(`--${name} is required`);
  return value;
}

function normalized(value) {
  return win32.normalize(win32.resolve(value)).toLowerCase();
}

function isWithin(candidate, root) {
  const candidateKey = normalized(candidate);
  const rootKey = normalized(root).replace(/[\\]+$/u, "");
  return candidateKey === rootKey || candidateKey.startsWith(`${rootKey}\\`);
}

function assertWorkspaceOutput(path) {
  if (!isWithin(path, workspaceRoot)) throw new Error(`acceptance output must be under the workspace: ${path}`);
}

function windowsDrivePair(path) {
  const normalizedPath = win32.normalize(path);
  const parsed = win32.parse(normalizedPath);
  return { drive: parsed.root.slice(0, 2), path: normalizedPath.slice(2) || "\\" };
}

async function exists(path) {
  try {
    await access(path);
    return true;
  } catch {
    return false;
  }
}

function childExited(child) {
  return !child || (child.exitCode !== null || child.signalCode !== null);
}

function waitForChild(child, timeoutMs) {
  if (childExited(child)) return Promise.resolve({ code: child?.exitCode ?? null, signal: child?.signalCode ?? null });
  return new Promise((resolveExit, reject) => {
    const timer = setTimeout(() => reject(new Error(`child did not exit within ${timeoutMs}ms`)), timeoutMs);
    const onError = (error) => {
      clearTimeout(timer);
      reject(error);
    };
    child.once("error", onError);
    child.once("exit", (code, signal) => {
      clearTimeout(timer);
      resolveExit({ code, signal });
    });
  });
}

async function terminateChild(child) {
  if (childExited(child)) return { code: child?.exitCode ?? null, signal: child?.signalCode ?? null, forced: false };
  if (process.platform === "win32" && child.pid) {
    // The PID is the exact process spawned by this runner; /T only handles
    // its own descendants and never searches or terminates unrelated trees.
    spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore", windowsHide: true });
  } else if (!child.kill("SIGTERM")) {
    child.kill("SIGKILL");
  }
  try {
    return { ...(await waitForChild(child, 5_000)), forced: true };
  } catch {
    return { code: child.exitCode ?? null, signal: child.signalCode ?? null, forced: true };
  }
}

function collectOutput(child, hooks = {}) {
  const stdout = [];
  const stderr = [];
  child.stdout?.on("data", (chunk) => {
    const value = Buffer.from(chunk);
    stdout.push(value);
    hooks.onStdout?.(value.toString("utf8"));
  });
  child.stderr?.on("data", (chunk) => {
    const value = Buffer.from(chunk);
    stderr.push(value);
    hooks.onStderr?.(value.toString("utf8"));
  });
  return {
    stdout: () => Buffer.concat(stdout),
    stderr: () => Buffer.concat(stderr),
  };
}

async function writeLogArtifact(path, content) {
  await writeFile(path, content);
  const bytes = content.byteLength;
  return { path, bytes, sha256: createHash("sha256").update(content).digest("hex") };
}

async function fileArtifact(path) {
  const content = await readFile(path);
  return writeLogArtifact(path, content);
}

function splitStderr(buffer) {
  return buffer.toString("utf8").split(/\r?\n/u).map((line) => line.trim()).filter(Boolean);
}

function escapeRegex(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&");
}

function packagedRendererEntryUri(executablePath) {
  const rendererEntry = win32.normalize(join(
    win32.dirname(executablePath),
    "resources",
    "app.asar",
    ".webpack",
    "renderer",
    "main_window",
    "index.html",
  ));
  return `file:///${rendererEntry.replaceAll("\\", "/")}`;
}

function classifyStderr(name, buffer, expectedPort, rendererEntryUri = null) {
  const lines = splitStderr(buffer);
  const allowlistPatterns = name === "electron"
    ? [
      new RegExp(`^DevTools listening on ws://127\\.0\\.0\\.1:${expectedPort}/devtools/browser/[0-9a-f-]+$`, "iu"),
      // Chromium emits this single layout diagnostic from the packaged
      // renderer during a resize. Match the exact message and this run's
      // packaged renderer entry only; unrelated renderer stderr remains fatal.
      ...(process.platform === "win32" && rendererEntryUri
        ? [new RegExp(`^\\[\\d+:\\d{4}/\\d{6}\\.\\d{3}:INFO:CONSOLE:0\\] \"ResizeObserver loop completed with undelivered notifications\\.\", source: ${escapeRegex(rendererEntryUri)} \\(0\\)$`, "u")]
        : []),
    ]
    : [];
  const allowlisted = lines.filter((line) => allowlistPatterns.some((pattern) => pattern.test(line)));
  const unexplained = lines.filter((line) => !allowlisted.includes(line));
  return { lines, allowlisted, unexplained };
}

async function createSafeHostProfile() {
  const root = await mkdtemp(join(tmpdir(), "uthcode-t10-host-"));
  const profile = join(root, "profile");
  const appData = join(root, "appdata");
  const localAppData = join(root, "localappdata");
  await Promise.all([mkdir(profile, { recursive: true }), mkdir(appData, { recursive: true }), mkdir(localAppData, { recursive: true })]);
  const homePair = windowsDrivePair(profile);
  const env = {
    ...process.env,
    HOME: profile,
    USERPROFILE: profile,
    APPDATA: appData,
    LOCALAPPDATA: localAppData,
    HOMEDRIVE: homePair.drive,
    HOMEPATH: homePair.path,
  };
  return { root, env };
}

function restoreEnvironment(previous) {
  for (const [name, value] of Object.entries(previous)) {
    if (value === undefined) delete process.env[name];
    else process.env[name] = value;
  }
}

async function readJsonIfPresent(path) {
  if (!(await exists(path))) return null;
  return JSON.parse(await readFile(path, "utf8"));
}

async function waitForJsonFile(path, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const value = await readJsonIfPresent(path);
      if (value) return value;
    } catch {
      // The fixture writes the small receipt atomically enough for normal
      // operation; tolerate a transient read during the write boundary.
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error(`fixture ready file did not appear within ${timeoutMs}ms: ${path}`);
}

async function waitForPackagedTarget(port, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  let lastError = "not queried";
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/list`, { signal: AbortSignal.timeout(Math.min(1_000, Math.max(1, deadline - Date.now()))) });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const targets = await response.json();
      if (targets.some((target) => target.type === "page" && target.webSocketDebuggerUrl && target.url.includes("main_window"))) return;
      lastError = `targets=${targets.length}`;
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`packaged Electron target did not appear on fixed port ${port}: ${lastError}`);
}

function fixtureConfiguration(baseUrl) {
  return [
    'default_model = "fixture/fixture-model"',
    'default_permission_mode = "default"',
    "",
    "[providers.fixture]",
    'kind = "openai_compat"',
    `base_url = "${baseUrl}"`,
    'api_key = "env:UTHCODE_CDP_FIXTURE_KEY"',
    "",
    '[models."fixture/fixture-model"]',
    'provider = "fixture"',
    'remote_id = "fixture-model"',
    'display_name = "CDP fixture"',
    // The Desktop bootstrap prompt is larger than the smallest legal test
    // window. Keep the fixture model generous enough to reach the Provider
    // request so each acceptance flow exercises the intended boundary.
    "context_window = 128000",
    "max_output_tokens = 256",
    "",
  ].join("\n");
}

function errorEvidence(error) {
  return { message: error instanceof Error ? error.message : String(error), stack: error instanceof Error ? error.stack ?? null : null };
}

async function main() {
  const language = requiredOption("language");
  if (!["en", "zh"].includes(language)) throw new Error("--language must be en or zh");
  const preferenceLanguage = language === "zh" ? "zh-CN" : "en";
  const executableOption = requiredOption("exe", "out/UthCode-win32-x64/UthCode.exe");
  const executable = win32.isAbsolute(executableOption) ? executableOption : resolvePath(desktopRoot, executableOption);
  const executablePath = win32.normalize(executable);
  const flow = option("flow", "visual");
  const isProviderFlow = providerFlows.has(flow) || commandFlows.has(flow);
  if (flow !== "visual" && flow !== "shell" && !isProviderFlow) throw new Error(`unsupported packaged CDP flow: ${flow}`);
  const fixtureScenario = option("scenario", commandFlows.has(flow) ? "stream" : providerFlows.has(flow) ? flow : "stream");
  if (isProviderFlow && !providerFlows.has(fixtureScenario)) throw new Error(`unsupported fixture scenario: ${fixtureScenario}`);
  const planChoice = option("plan-choice", "approve");
  const delayAction = option("delay-action", "pause");
  const planChunkDelayMs = Number(option("plan-chunk-delay-ms", "250"));
  if (!["approve", "revise", "cancel"].includes(planChoice)) throw new Error(`unsupported plan choice: ${planChoice}`);
  if (!["pause", "cancel"].includes(delayAction)) throw new Error(`unsupported delay action: ${delayAction}`);
  if (!Number.isFinite(planChunkDelayMs) || planChunkDelayMs < 250) throw new Error(`plan chunk delay must be at least 250ms: ${planChunkDelayMs}`);
  const outputOption = option("output", `dist/ui-acceptance/t10-electron-${flow}-${language}-${Date.now()}-${randomUUID().slice(0, 8)}`);
  const output = win32.isAbsolute(outputOption) ? outputOption : resolvePath(desktopRoot, outputOption);
  const port = Number(option("port", language === "en" ? "9345" : "9346"));
  const timeoutMs = Number(option("timeout-ms", "60000"));
  const requestTimeoutMs = Number(option("request-timeout-ms", "5000"));
  if (!Number.isInteger(port) || port <= 0 || port === 7897) throw new Error(`invalid CDP port: ${port}`);
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) throw new Error(`invalid timeout: ${timeoutMs}`);
  if (!Number.isFinite(requestTimeoutMs) || requestTimeoutMs <= 0) throw new Error(`invalid CDP request timeout: ${requestTimeoutMs}`);
  assertWorkspaceOutput(output);
  const executableStat = await stat(executablePath);
  const executableBytes = await readFile(executablePath);
  const packagedExeEvidence = { path: executablePath, bytes: executableStat.size, sha256: createHash("sha256").update(executableBytes).digest("hex") };
  await mkdir(output, { recursive: true });

  const runId = randomUUID();
  const startedAt = new Date().toISOString();
  const logPaths = {
    electronStdout: join(output, "electron.stdout.log"),
    electronStderr: join(output, "electron.stderr.log"),
    driverStdout: join(output, "driver.stdout.log"),
    driverStderr: join(output, "driver.stderr.log"),
    fixtureStdout: join(output, "fixture.stdout.log"),
    fixtureStderr: join(output, "fixture.stderr.log"),
  };
  let host;
  let electronContext;
  let driverContext;
  let fixtureContext;
  let electronChild;
  let driverChild;
  let fixtureChild;
  let electronOutput;
  let driverOutput;
  let fixtureOutput;
  let electronExit;
  let driverExit;
  let fixtureExit;
  let failure;
  let rawDriverReport;
  let seededPreferencePath;
  const managedEnvNames = ["HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOMEDRIVE", "HOMEPATH"];
  const previousEnv = Object.fromEntries(managedEnvNames.map((name) => [name, process.env[name]]));

  try {
    host = await createSafeHostProfile();
    Object.assign(process.env, host.env);
    electronContext = await createIsolatedCdpContext({ mode: "electron", prefix: `uthcode-cdp-electron-${runId.slice(0, 8)}-` });
    await mkdir(electronContext.userDataDir, { recursive: true });
    const desktopPreferences = JSON.stringify({
      language: preferenceLanguage,
      recentProjects: [{ path: workspaceRoot, alias: "Re-UthCode", pinned: false }],
      projectAliases: { [workspaceRoot]: "Re-UthCode" },
      pinnedProjectKeys: [],
      pinnedSessions: [],
      expandedProjects: { [workspaceRoot]: true },
      selectedProjectKey: workspaceRoot,
      selectedSessionId: null,
    });
    // Electron resolves app.getPath("userData") to the exact launcher-owned
    // --user-data-dir. Seed only that path and retain it while the Renderer
    // performs its normal atomic preference writes.
    seededPreferencePath = join(electronContext.userDataDir, "desktop-preferences.json");
    await mkdir(resolvePath(seededPreferencePath, ".."), { recursive: true });
    await writeFile(seededPreferencePath, desktopPreferences, "utf8");
    let fixtureReady;
    if (isProviderFlow) {
      fixtureContext = await createIsolatedCdpContext({ mode: "isolated", prefix: `uthcode-cdp-fixture-${runId.slice(0, 8)}-` });
      const fixtureReadyPath = join(fixtureContext.root, "ready.json");
      fixtureChild = spawn(process.execPath, [
        fixturePath,
        "--port", "0",
        "--scenario", fixtureScenario,
        "--ready-file", fixtureReadyPath,
        "--plan-chunk-delay-ms", String(planChunkDelayMs),
        ...(flow === "plan" ? ["--plan-choice", planChoice] : []),
      ], {
        cwd: desktopRoot,
        env: fixtureContext.env,
        stdio: ["ignore", "pipe", "pipe"],
        windowsHide: true,
      });
      fixtureOutput = collectOutput(fixtureChild);
      fixtureReady = await waitForJsonFile(fixtureReadyPath, Math.min(timeoutMs, 15_000));
      if (!fixtureReady?.baseUrl) throw new Error("packaged CDP fixture did not report a base URL");
      const configuration = fixtureConfiguration(fixtureReady.baseUrl);
      await writeFile(electronContext.configPath, configuration, "utf8");
      // The packaged Runtime resolves its user config from HOME. Keep that
      // path inside the runner-owned host profile as well; the launcher-owned
      // UTHCODE_CONFIG_PATH remains a separate guard/receipt path.
      const hostConfigDirectory = join(host.env.HOME, ".uthcode");
      await mkdir(hostConfigDirectory, { recursive: true });
      await writeFile(join(hostConfigDirectory, "config.toml"), configuration, "utf8");
      electronContext.env.UTHCODE_CDP_FIXTURE_KEY = "fixture-test-key";
    } else {
      // Visual/shell flows still bootstrap the real Runtime status path. Give
      // them the same valid user-config shape without starting a Provider
      // server or making any network request.
      const configuration = fixtureConfiguration("http://127.0.0.1:1/v1");
      await writeFile(electronContext.configPath, configuration, "utf8");
      const hostConfigDirectory = join(host.env.HOME, ".uthcode");
      await mkdir(hostConfigDirectory, { recursive: true });
      await writeFile(join(hostConfigDirectory, "config.toml"), configuration, "utf8");
      electronContext.env.UTHCODE_CDP_FIXTURE_KEY = "fixture-test-key";
    }
    electronChild = spawn(executablePath, ["--no-sandbox", `--remote-debugging-port=${port}`, "--disable-gpu", "--enable-logging=stderr", `--user-data-dir=${electronContext.userDataDir}`], {
      cwd: workspaceRoot,
      env: electronContext.env,
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
    });
    electronOutput = collectOutput(electronChild);
    await waitForPackagedTarget(port, Math.min(timeoutMs, 15_000));

    driverContext = await createIsolatedCdpContext({ mode: "isolated", prefix: `uthcode-cdp-driver-${runId.slice(0, 8)}-` });
    const rawReportPath = join(driverContext.root, "driver-report.json");
    driverChild = spawn(process.execPath, [
      driverPath,
      "--port", String(port),
      "--flow", flow,
      "--language", preferenceLanguage,
      "--screenshot-dir", output,
      "--report", rawReportPath,
      "--packaged-exe", executablePath,
      "--timeout-ms", String(timeoutMs),
      "--request-timeout-ms", String(requestTimeoutMs),
      "--plan-chunk-delay-ms", String(planChunkDelayMs),
      ...(isProviderFlow ? ["--scenario", fixtureScenario] : []),
      ...(flow === "ask-one" ? ["--ask-question-count", "1"] : []),
      ...(flow === "plan" ? ["--plan-choice", planChoice] : []),
      ...(flow === "delay" ? ["--delay-action", delayAction] : []),
    ], { cwd: desktopRoot, env: driverContext.env, stdio: ["ignore", "pipe", "pipe"], windowsHide: true });
    driverOutput = collectOutput(driverChild);
    driverExit = await waitForChild(driverChild, timeoutMs + 15_000);
    rawDriverReport = await readJsonIfPresent(rawReportPath);
    if (driverExit.code !== 0 || rawDriverReport?.status !== "passed") {
      throw new Error(`packaged CDP driver failed: code=${driverExit.code} status=${rawDriverReport?.status ?? "missing"}`);
    }
    electronExit = await waitForChild(electronChild, 15_000);
    if (electronExit.code !== 0) throw new Error(`packaged Electron exited abnormally: code=${electronExit.code} signal=${electronExit.signal}`);
    if (fixtureChild) {
      fixtureExit = await terminateChild(fixtureChild);
    }
  } catch (error) {
    failure = errorEvidence(error);
  } finally {
    if (!childExited(driverChild)) {
      const stopped = await terminateChild(driverChild);
      driverExit ??= stopped;
    }
    if (!childExited(electronChild)) {
      const stopped = await terminateChild(electronChild);
      electronExit ??= stopped;
    }
    if (!childExited(fixtureChild)) {
      const stopped = await terminateChild(fixtureChild);
      fixtureExit ??= stopped;
    }
    if (driverOutput) {
      await writeLogArtifact(logPaths.driverStdout, driverOutput.stdout());
      await writeLogArtifact(logPaths.driverStderr, driverOutput.stderr());
    }
    if (electronOutput) {
      await writeLogArtifact(logPaths.electronStdout, electronOutput.stdout());
      await writeLogArtifact(logPaths.electronStderr, electronOutput.stderr());
    }
    if (fixtureOutput) {
      await writeLogArtifact(logPaths.fixtureStdout, fixtureOutput.stdout());
      await writeLogArtifact(logPaths.fixtureStderr, fixtureOutput.stderr());
    }
    if (!rawDriverReport && driverContext) {
      try { rawDriverReport = await readJsonIfPresent(join(driverContext.root, "driver-report.json")); } catch { rawDriverReport = null; }
    }
    if (driverContext) await driverContext.cleanup();
    if (electronContext) await electronContext.cleanup();
    if (fixtureContext) await fixtureContext.cleanup();
    if (host) await rm(host.root, { recursive: true, force: true });
    restoreEnvironment(previousEnv);
  }

  const reportLogs = {};
  for (const [name, path] of Object.entries(logPaths)) {
    if (!(await exists(path))) await writeFile(path, Buffer.alloc(0));
    reportLogs[name] = await fileArtifact(path);
  }
  const rendererEntryUri = packagedRendererEntryUri(executablePath);
  const electronStderr = classifyStderr("electron", electronOutput?.stderr() ?? Buffer.alloc(0), port, rendererEntryUri);
  const driverStderr = classifyStderr("driver", driverOutput?.stderr() ?? Buffer.alloc(0), port);
  const fixtureStderr = classifyStderr("fixture", fixtureOutput?.stderr() ?? Buffer.alloc(0), port);
  const fixtureRequests = splitStderr(fixtureOutput?.stdout() ?? Buffer.alloc(0))
    .flatMap((line) => {
      try {
        const event = JSON.parse(line);
        return event?.event === "request" ? [event] : [];
      } catch {
        return [];
      }
    });
  const consoleErrors = rawDriverReport?.consoleErrors ?? [];
  const consoleDiagnostics = rawDriverReport?.consoleDiagnostics ?? [];
  const rendererExceptions = rawDriverReport?.rendererExceptions ?? [];
  const driverPassed = driverExit?.code === 0 && rawDriverReport?.status === "passed";
  const electronPassed = electronExit?.code === 0;
  const signalFailures = [];
  if (consoleErrors.length > 0) signalFailures.push(`Renderer console errors: ${consoleErrors.length}`);
  if (consoleDiagnostics.length > 0) signalFailures.push(`Electron console diagnostics: ${consoleDiagnostics.length}`);
  if (rendererExceptions.length > 0) signalFailures.push(`Renderer exceptions: ${rendererExceptions.length}`);
  if (electronStderr.unexplained.length > 0) signalFailures.push(`Electron stderr: ${electronStderr.unexplained.length} unexplained line(s)`);
  if (driverStderr.unexplained.length > 0) signalFailures.push(`Driver stderr: ${driverStderr.unexplained.length} unexplained line(s)`);
  if (fixtureStderr.unexplained.length > 0) signalFailures.push(`Fixture stderr: ${fixtureStderr.unexplained.length} unexplained line(s)`);
  const persistedSecretMarkers = ["fixture-test-key", "raw-native-secret"];
  const secretLeakArtifacts = [
    electronOutput?.stdout() ?? Buffer.alloc(0),
    electronOutput?.stderr() ?? Buffer.alloc(0),
    driverOutput?.stdout() ?? Buffer.alloc(0),
    driverOutput?.stderr() ?? Buffer.alloc(0),
    fixtureOutput?.stdout() ?? Buffer.alloc(0),
    fixtureOutput?.stderr() ?? Buffer.alloc(0),
  ].flatMap((buffer) => persistedSecretMarkers.filter((marker) => buffer.toString("utf8").includes(marker)));
  if (secretLeakArtifacts.length > 0) signalFailures.push(`Fixture secret persisted in process artifacts: ${[...new Set(secretLeakArtifacts)].join(", ")}`);
  const expectedFixtureRequests = flow === "sessions" ? 8 : null;
  if (expectedFixtureRequests !== null && fixtureRequests.length !== expectedFixtureRequests) {
    signalFailures.push(`Fixture request count: expected ${expectedFixtureRequests}, observed ${fixtureRequests.length}`);
  }
  const status = !failure && driverPassed && electronPassed && signalFailures.length === 0 ? "passed" : "failed";
  const finalFailure = failure ?? (signalFailures.length > 0 ? { message: signalFailures.join("; "), stack: null } : null);
  const report = {
    schemaVersion: 1,
    kind: "uthcode.packaged-electron.acceptance",
    runId,
    flow,
    fixture: isProviderFlow ? { scenario: fixtureScenario, expectedRequestCount: expectedFixtureRequests, requestCount: fixtureRequests.length, requestCountOk: expectedFixtureRequests === null || fixtureRequests.length === expectedFixtureRequests, exit: { code: fixtureExit?.code ?? null, signal: fixtureExit?.signal ?? null } } : null,
    packagedExe: packagedExeEvidence,
    timestamp: { startedAt, finishedAt: new Date().toISOString() },
    language: { requested: language, preferenceValue: preferenceLanguage, observed: rawDriverReport?.observed?.languages ?? [] },
    themes: rawDriverReport?.observed?.themes ?? [],
    viewports: rawDriverReport?.observed?.viewports ?? [],
    runtimePanelLayouts: rawDriverReport?.observed?.runtimePanelLayouts ?? [],
    screenshots: rawDriverReport?.screenshots ?? [],
    consoleErrors,
    consoleDiagnostics,
    rendererExceptions,
    stderr: {
      electron: electronStderr,
      driver: driverStderr,
      fixture: fixtureStderr,
    },
    exit: {
      status,
      driver: { code: driverExit?.code ?? null, signal: driverExit?.signal ?? null },
      electron: { code: electronExit?.code ?? null, signal: electronExit?.signal ?? null },
    },
    logs: reportLogs,
    cleanup: {
      seededPreferencePath,
      electronRoot: electronContext?.root ?? null,
      driverRoot: driverContext?.root ?? null,
      fixtureRoot: fixtureContext?.root ?? null,
      hostRoot: host?.root ?? null,
      electronRootRemoved: electronContext ? !(await exists(electronContext.root)) : null,
      driverRootRemoved: driverContext ? !(await exists(driverContext.root)) : null,
      fixtureRootRemoved: fixtureContext ? !(await exists(fixtureContext.root)) : null,
      hostRootRemoved: host ? !(await exists(host.root)) : null,
    },
    failure: finalFailure,
  };
  const reportPath = join(output, "acceptance-report.json");
  await writeFile(reportPath, JSON.stringify(report, null, 2), "utf8");
  process.stdout.write(`${JSON.stringify({ status, report: reportPath, runId })}\n`);
  if (status !== "passed") process.exitCode = 1;
}

main().catch((error) => {
  process.stderr.write(`${errorEvidence(error).message}\n`);
  process.exitCode = 1;
});
