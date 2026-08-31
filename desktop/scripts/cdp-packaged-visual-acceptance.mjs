#!/usr/bin/env node

/**
 * Run the visual CDP flow against a packaged Electron executable.
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
const workspaceRoot = fileURLToPath(new URL("../../", import.meta.url));
const driverPath = fileURLToPath(new URL("./cdp-driver.mjs", import.meta.url));

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

function collectOutput(child) {
  const stdout = [];
  const stderr = [];
  child.stdout?.on("data", (chunk) => stdout.push(Buffer.from(chunk)));
  child.stderr?.on("data", (chunk) => stderr.push(Buffer.from(chunk)));
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
  const outputOption = option("output", `dist/ui-acceptance/t10-electron-visual-${language}-${Date.now()}-${randomUUID().slice(0, 8)}`);
  const output = win32.isAbsolute(outputOption) ? outputOption : resolvePath(desktopRoot, outputOption);
  const port = Number(option("port", language === "en" ? "9345" : "9346"));
  const timeoutMs = Number(option("timeout-ms", "60000"));
  if (!Number.isInteger(port) || port <= 0 || port === 7897) throw new Error(`invalid CDP port: ${port}`);
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) throw new Error(`invalid timeout: ${timeoutMs}`);
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
  };
  let host;
  let electronContext;
  let driverContext;
  let electronChild;
  let driverChild;
  let electronOutput;
  let driverOutput;
  let electronExit;
  let driverExit;
  let failure;
  let rawDriverReport;
  const managedEnvNames = ["HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOMEDRIVE", "HOMEPATH"];
  const previousEnv = Object.fromEntries(managedEnvNames.map((name) => [name, process.env[name]]));

  try {
    host = await createSafeHostProfile();
    Object.assign(process.env, host.env);
    electronContext = await createIsolatedCdpContext({ mode: "electron", prefix: `uthcode-cdp-electron-${runId.slice(0, 8)}-` });
    electronChild = spawn(executablePath, [`--remote-debugging-port=${port}`, "--disable-gpu", "--enable-logging=stderr", `--user-data-dir=${electronContext.userDataDir}`], {
      cwd: workspaceRoot,
      env: electronContext.env,
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
    });
    electronOutput = collectOutput(electronChild);

    driverContext = await createIsolatedCdpContext({ mode: "isolated", prefix: `uthcode-cdp-driver-${runId.slice(0, 8)}-` });
    const rawReportPath = join(driverContext.root, "driver-report.json");
    driverChild = spawn(process.execPath, [
      driverPath,
      "--port", String(port),
      "--flow", "visual",
      "--language", preferenceLanguage,
      "--screenshot-dir", output,
      "--report", rawReportPath,
      "--packaged-exe", executablePath,
      "--timeout-ms", String(timeoutMs),
      "--request-timeout-ms", "5000",
    ], { cwd: desktopRoot, env: driverContext.env, stdio: ["ignore", "pipe", "pipe"], windowsHide: true });
    driverOutput = collectOutput(driverChild);
    driverExit = await waitForChild(driverChild, timeoutMs + 15_000);
    rawDriverReport = await readJsonIfPresent(rawReportPath);
    if (driverExit.code !== 0 || rawDriverReport?.status !== "passed") {
      throw new Error(`packaged CDP driver failed: code=${driverExit.code} status=${rawDriverReport?.status ?? "missing"}`);
    }
    electronExit = await waitForChild(electronChild, 15_000);
    if (electronExit.code !== 0) throw new Error(`packaged Electron exited abnormally: code=${electronExit.code} signal=${electronExit.signal}`);
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
    if (driverOutput) {
      await writeLogArtifact(logPaths.driverStdout, driverOutput.stdout());
      await writeLogArtifact(logPaths.driverStderr, driverOutput.stderr());
    }
    if (electronOutput) {
      await writeLogArtifact(logPaths.electronStdout, electronOutput.stdout());
      await writeLogArtifact(logPaths.electronStderr, electronOutput.stderr());
    }
    if (!rawDriverReport && driverContext) {
      try { rawDriverReport = await readJsonIfPresent(join(driverContext.root, "driver-report.json")); } catch { rawDriverReport = null; }
    }
    if (driverContext) await driverContext.cleanup();
    if (electronContext) await electronContext.cleanup();
    if (host) await rm(host.root, { recursive: true, force: true });
    restoreEnvironment(previousEnv);
  }

  const reportLogs = {};
  for (const [name, path] of Object.entries(logPaths)) {
    if (!(await exists(path))) await writeFile(path, Buffer.alloc(0));
    reportLogs[name] = await fileArtifact(path);
  }
  const consoleErrors = rawDriverReport?.consoleErrors ?? [];
  const consoleDiagnostics = rawDriverReport?.consoleDiagnostics ?? [];
  const rendererExceptions = rawDriverReport?.rendererExceptions ?? [];
  const driverPassed = driverExit?.code === 0 && rawDriverReport?.status === "passed";
  const electronPassed = electronExit?.code === 0;
  const status = !failure && driverPassed && electronPassed && consoleErrors.length === 0 && rendererExceptions.length === 0 ? "passed" : "failed";
  const report = {
    schemaVersion: 1,
    kind: "uthcode.packaged-electron.visual-acceptance",
    runId,
    flow: "visual",
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
    exit: {
      status,
      driver: { code: driverExit?.code ?? null, signal: driverExit?.signal ?? null },
      electron: { code: electronExit?.code ?? null, signal: electronExit?.signal ?? null },
    },
    logs: reportLogs,
    cleanup: {
      electronRoot: electronContext?.root ?? null,
      driverRoot: driverContext?.root ?? null,
      hostRoot: host?.root ?? null,
      electronRootRemoved: electronContext ? !(await exists(electronContext.root)) : null,
      driverRootRemoved: driverContext ? !(await exists(driverContext.root)) : null,
      hostRootRemoved: host ? !(await exists(host.root)) : null,
    },
    failure,
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
