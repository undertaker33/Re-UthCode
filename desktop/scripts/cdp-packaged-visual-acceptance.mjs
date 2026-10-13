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
import { access, copyFile, mkdir, mkdtemp, readFile, rm, stat, writeFile } from "node:fs/promises";
import { homedir, tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { join, resolve as resolvePath, win32 } from "node:path";
import { createIsolatedCdpContext } from "./cdp-launcher.mjs";

const desktopRoot = fileURLToPath(new URL("../", import.meta.url));
const workspaceRoot = resolvePath(fileURLToPath(new URL("../../", import.meta.url)));
const driverPath = fileURLToPath(new URL("./cdp-driver.mjs", import.meta.url));
const fixturePath = fileURLToPath(new URL("./cdp-openai-fixture.mjs", import.meta.url));
const providerFlows = new Set(["stream", "tool", "review", "todo", "ask", "ask-one", "permission", "plan", "failure", "delay", "sessions", "general-cancel"]);
const commandFlows = new Set(["commands"]);
const lifecycleFlows = new Set(["lifecycle"]);
const diffFlows = new Set(["diff"]);
const realProviderFlows = new Set(["general-real"]);
const invalidConfigurationFlows = new Set(["general-invalid-config"]);
const generalCancelFlows = new Set(["general-cancel"]);

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

function expectedConfigurationErrorBlock(lines, start, executablePath) {
  const end = lines.indexOf("}", start + 1);
  if (end < 0) return null;
  const block = lines.slice(start, end + 1);
  if (!/^Error occurred in handler for 'desktop\.runtime\.request': [A-Za-z_$][\w$]* \[RuntimeRequestError\]: user configuration is invalid$/u.test(block[0])) return null;
  const mainEntryPath = win32.join(win32.dirname(executablePath), "resources", "app.asar", ".webpack", "main", "index.js");
  const mainEntry = escapeRegex(mainEntryPath);
  const mainFrames = [
    new RegExp(`^at [A-Za-z_$][\\w$]*\\.consumeLine \\(${mainEntry}:1:\\d+\\)$`, "u"),
    new RegExp(`^at [A-Za-z_$][\\w$]*\\.consumeStdout \\(${mainEntry}:1:\\d+\\)$`, "u"),
    new RegExp(`^at Socket\\.<anonymous> \\(${mainEntry}:1:\\d+\\)$`, "u"),
  ];
  const nodeFrames = [
    /^at Socket\.emit \(node:events:\d+:\d+\)$/u,
    /^at addChunk \(node:internal\/streams\/readable:\d+:\d+\)$/u,
    /^at readableAddChunkPushByteMode \(node:internal\/streams\/readable:\d+:\d+\)$/u,
    /^at Readable\.push \(node:internal\/streams\/readable:\d+:\d+\)$/u,
    /^at Pipe\.onStreamRead \(node:internal\/stream_base_commons:\d+:\d+\) \{$/u,
  ];
  const frameLines = block.slice(1, -2);
  const mainMatched = mainFrames.every((pattern) => frameLines.filter((line) => pattern.test(line)).length === 1);
  const nodeMatched = nodeFrames.every((pattern) => frameLines.filter((line) => pattern.test(line)).length === 1);
  if (!mainMatched || !nodeMatched || block.at(-2) !== "kind: 'configuration_error'" || block.at(-1) !== "}") return null;
  if (frameLines.some((line) => ![...mainFrames, ...nodeFrames].some((pattern) => pattern.test(line)))) return null;
  return block;
}

function classifyStderr(name, buffer, expectedPort, rendererEntryUri = null, allowInvalidConfigurationError = false, executablePath = null) {
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
  const allowlistedSet = new Set(lines.filter((line) => allowlistPatterns.some((pattern) => pattern.test(line))));
  if (name === "electron" && allowInvalidConfigurationError) {
    for (let index = 0; index < lines.length; index += 1) {
      if (!lines[index].startsWith("Error occurred in handler for 'desktop.runtime.request':")) continue;
      const block = expectedConfigurationErrorBlock(lines, index, executablePath);
      if (!block) continue;
      for (const line of block) allowlistedSet.add(line);
      index += block.length - 1;
    }
  }
  const allowlisted = lines.filter((line) => allowlistedSet.has(line));
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

function runGit(projectPath, args) {
  const result = spawnSync("git", ["-C", projectPath, ...args], {
    cwd: projectPath,
    env: { ...process.env, GIT_CONFIG_NOSYSTEM: "1", GIT_CONFIG_GLOBAL: "NUL" },
    encoding: "utf8",
    windowsHide: true,
  });
  if (result.error || result.status !== 0) {
    throw new Error(`controlled Git setup failed (${args.join(" ")}): ${result.error?.message ?? result.stderr ?? result.status}`);
  }
  return result.stdout.trim();
}

async function createControlledDiffProject(projectPath) {
  await mkdir(projectPath, { recursive: true });
  const longLines = Array.from({ length: 1000 }, (_, index) => `DIFF_CONTEXT_ROW_${index + 1}`);
  await writeFile(join(projectPath, "long.txt"), `${longLines.join("\n")}\n`, "utf8");
  await writeFile(join(projectPath, "modified.txt"), "old tracked line\nunchanged context\n", "utf8");
  await writeFile(join(projectPath, "deleted.txt"), "tracked delete\n", "utf8");
  await writeFile(join(projectPath, "rename-source.txt"), "tracked rename\n", "utf8");
  await writeFile(join(projectPath, ".gitignore"), "/.uthcode/permissions.toml\n", "utf8");
  runGit(projectPath, ["init", "--initial-branch=main"]);
  runGit(projectPath, ["config", "user.name", "UthCode T12 Acceptance"]);
  runGit(projectPath, ["config", "user.email", "t12-acceptance@example.invalid"]);
  runGit(projectPath, ["add", "--all"]);
  runGit(projectPath, ["commit", "-m", "seed controlled diff project"]);
  await writeFile(join(projectPath, "modified.txt"), "new tracked line\nunchanged context\n", "utf8");
  longLines[499] = "DIFF_CHANGED_ROW_500";
  await writeFile(join(projectPath, "long.txt"), `${longLines.join("\n")}\n`, "utf8");
  await writeFile(join(projectPath, "added.txt"), "new staged line\n", "utf8");
  await writeFile(join(projectPath, "untracked.txt"), "UNTRACKED_DIFF_BODY\n", "utf8");
  runGit(projectPath, ["add", "added.txt"]);
  runGit(projectPath, ["rm", "deleted.txt"]);
  runGit(projectPath, ["mv", "rename-source.txt", "renamed.txt"]);
  return projectPath;
}

async function createControlledReviewProject(projectPath) {
  await mkdir(projectPath, { recursive: true });
  const rows = Array.from({ length: 920 }, (_, index) => `W05_REVIEW_OUTPUT_ROW_${String(index + 1).padStart(4, "0")} ${"bounded review content ".repeat(4)}`);
  await writeFile(join(projectPath, "review-output.txt"), ["W05_REVIEW_OUTPUT_BEGIN", ...rows, "W05_REVIEW_OUTPUT_END", ""].join("\n"), "utf8");
  await writeFile(join(projectPath, "review.md"), "# W05 Review Markdown\n\nW05_REVIEW_MARKDOWN_BODY\n\nA controlled Markdown artifact for the packaged Review flow.\n", "utf8");
  await writeFile(join(projectPath, "review.txt"), "W05_REVIEW_TEXT_BODY\n\nA controlled text artifact for the packaged Review flow.\n", "utf8");
  await writeFile(join(projectPath, "review-attachment.png"), Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAEAAAAAwCAIAAAAuKetIAAAAgklEQVR4nNXOQQ2DABQE0WFM9FRBhDP3aiDBUhFUAVipiOanmSdgdpfPtjPpeL5G+xIncRIncRIncRIncRIncRIncRIncRIncRIncRIncRIncRK3rO9zdOB63KN9iZM4iZM4iZM4iZM4iZM4iZM4iZM4iZM4iZM4iZM4iZM4/33gV195BAXCa/9ABgAAAABJRU5ErkJggg==", "base64"));
  return projectPath;
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

function fixtureConfiguration(baseUrl, supportsImages = false, displayName = "CDP fixture", readableMenuProfiles = false) {
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
    `display_name = "${displayName}"`,
    // The Desktop bootstrap prompt is larger than the smallest legal test
    // window. Keep the fixture model generous enough to reach the Provider
    // request so each acceptance flow exercises the intended boundary.
    "context_window = 128000",
    "max_output_tokens = 256",
    ...(supportsImages ? ["supports_images = true"] : []),
    "",
    ...(readableMenuProfiles ? Array.from({ length: 4 }, (_, index) => [
      `[models."fixture/menu-model-${index}"]`,
      'provider = "fixture"',
      `remote_id = "menu-model-${index}"`,
      `display_name = "Fixture model ${index} with a readable long display name"`,
      "context_window = 128000",
      "max_output_tokens = 256",
      "",
    ]).flat() : []),
  ].join("\n");
}

function errorEvidence(error) {
  return { message: error instanceof Error ? error.message : String(error), stack: error instanceof Error ? error.stack ?? null : null };
}

async function main() {
  const language = requiredOption("language");
  const invokingUserHome = homedir();
  if (!["en", "zh"].includes(language)) throw new Error("--language must be en or zh");
  const preferenceLanguage = language === "zh" ? "zh-CN" : "en";
  const executableOption = requiredOption("exe", "out/UthCode-win32-x64/UthCode.exe");
  const executable = win32.isAbsolute(executableOption) ? executableOption : resolvePath(desktopRoot, executableOption);
  const executablePath = win32.normalize(executable);
  const flow = option("flow", "visual");
  const isLifecycleFlow = lifecycleFlows.has(flow);
  const isSettingsFlow = flow === "settings-ui";
  const isDiffFlow = diffFlows.has(flow);
  const isRealProviderFlow = realProviderFlows.has(flow);
  const isInvalidConfigurationFlow = invalidConfigurationFlows.has(flow);
  const isGeneralCancelFlow = generalCancelFlows.has(flow);
  const isProviderFlow = providerFlows.has(flow) || commandFlows.has(flow) || isLifecycleFlow;
  if (flow !== "visual" && flow !== "shell" && !isSettingsFlow && !isProviderFlow && !isDiffFlow && !isRealProviderFlow && !isInvalidConfigurationFlow) throw new Error(`unsupported packaged CDP flow: ${flow}`);
  const fixtureScenario = option("scenario", isGeneralCancelFlow ? "delay" : commandFlows.has(flow) || isLifecycleFlow ? "stream" : providerFlows.has(flow) ? flow : "stream");
  if (isProviderFlow && !providerFlows.has(fixtureScenario)) throw new Error(`unsupported fixture scenario: ${fixtureScenario}`);
  const planChoice = option("plan-choice", "approve");
  const delayAction = option("delay-action", isGeneralCancelFlow ? "cancel" : "pause");
  const planChunkDelayMs = Number(option("plan-chunk-delay-ms", "250"));
  if (!["approve", "revise", "cancel"].includes(planChoice)) throw new Error(`unsupported plan choice: ${planChoice}`);
  if (!["pause", "cancel"].includes(delayAction)) throw new Error(`unsupported delay action: ${delayAction}`);
  if (isGeneralCancelFlow && (fixtureScenario !== "delay" || delayAction !== "cancel")) throw new Error("general-cancel requires the delayed fixture and --delay-action cancel");
  if (!Number.isFinite(planChunkDelayMs) || planChunkDelayMs < 250) throw new Error(`plan chunk delay must be at least 250ms: ${planChunkDelayMs}`);
  const outputOption = option("output", `dist/ui-acceptance/w05-${flow}-${language}-${Date.now()}-${randomUUID().slice(0, 8)}`);
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
  let lifecycleProjectOne;
  let lifecycleProjectTwo;
  let diffProject;
  let diffUnbornProject;
  let permissionProject;
  let reviewProject;
  let invalidConfigPath;
  let invalidConfigBaselineHash;
  let invalidConfigUnchanged = null;
  let realProviderConfigSource;
  let realProviderConfigBaselineHash;
  let realProviderConfigUnchanged = null;
  let realProviderConfigCopied = false;
  let isolatedSessionStorageReady = false;
  const stageRuns = [];
  const stageDriverReports = [];
  const managedEnvNames = ["HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOMEDRIVE", "HOMEPATH"];
  const previousEnv = Object.fromEntries(managedEnvNames.map((name) => [name, process.env[name]]));

  try {
    host = await createSafeHostProfile();
    Object.assign(process.env, host.env);
    if (isRealProviderFlow) {
      realProviderConfigSource = join(invokingUserHome, ".uthcode", "config.toml");
      const configStat = await stat(realProviderConfigSource).catch(() => null);
      if (!configStat?.isFile()) throw new Error("real General Provider acceptance requires an existing user-level ~/.uthcode/config.toml");
      const sourceBytes = await readFile(realProviderConfigSource);
      realProviderConfigBaselineHash = createHash("sha256").update(sourceBytes).digest("hex");
      const isolatedConfigDirectory = join(host.env.HOME, ".uthcode");
      await mkdir(isolatedConfigDirectory, { recursive: true });
      const isolatedConfigPath = join(isolatedConfigDirectory, "config.toml");
      await copyFile(realProviderConfigSource, isolatedConfigPath);
      realProviderConfigCopied = true;
    }
    if (isLifecycleFlow || isSettingsFlow) {
      lifecycleProjectOne = join(host.root, "projects", "coding-one");
      lifecycleProjectTwo = join(host.root, "projects", "coding-two");
      await Promise.all([mkdir(lifecycleProjectOne, { recursive: true }), mkdir(lifecycleProjectTwo, { recursive: true })]);
      await writeFile(join(lifecycleProjectOne, "README.md"), "T12 isolated Coding project one.\n", "utf8");
      await writeFile(join(lifecycleProjectTwo, "README.md"), "T12 isolated Coding project two.\n", "utf8");
    }
    if (isDiffFlow) {
      diffProject = await createControlledDiffProject(join(host.root, "projects", "controlled-diff"));
      diffUnbornProject = join(host.root, "projects", "unborn-diff");
      await mkdir(diffUnbornProject, { recursive: true });
      runGit(diffUnbornProject, ["init", "--initial-branch=main"]);
      await writeFile(join(diffUnbornProject, "new-file.txt"), "UNBORN_NEW_FILE_BODY\n", "utf8");
    }
    if (flow === "permission") {
      permissionProject = join(host.root, "projects", "controlled-permission");
      await mkdir(permissionProject, { recursive: true });
      await writeFile(join(permissionProject, ".env"), "CDP_PERMISSION_PUBLIC_MARKER=isolated\n", "utf8");
    }
    if (flow === "review") reviewProject = await createControlledReviewProject(join(host.root, "projects", "controlled-review"));
    electronContext = await createIsolatedCdpContext({ mode: "electron", prefix: `uthcode-cdp-electron-${runId.slice(0, 8)}-` });
    await mkdir(electronContext.userDataDir, { recursive: true });
    isolatedSessionStorageReady = true;
    const recentProjects = isRealProviderFlow || isGeneralCancelFlow || isInvalidConfigurationFlow
      ? []
      : isLifecycleFlow || isSettingsFlow
      ? [
        { path: lifecycleProjectOne, alias: isSettingsFlow ? "UI Same project" : "T12 Coding One", pinned: false },
        { path: lifecycleProjectTwo, alias: isSettingsFlow ? "UI Same project" : "T12 Coding Two", pinned: false },
      ]
      : isDiffFlow
        ? [{ path: diffProject, alias: "T12 Diff project", pinned: false }, { path: diffUnbornProject, alias: "T12 Unborn Diff", pinned: false }]
        : flow === "permission"
          ? [{ path: permissionProject, alias: "T12 Permission fixture", pinned: false }]
        : flow === "review"
          ? [{ path: reviewProject, alias: "T12 Review project", pinned: false }]
          : [{ path: workspaceRoot, alias: "Re-UthCode", pinned: false }];
    const selectedProjectKey = isRealProviderFlow || isGeneralCancelFlow || isInvalidConfigurationFlow ? null : isLifecycleFlow || isSettingsFlow ? lifecycleProjectOne : isDiffFlow ? diffProject : flow === "permission" ? permissionProject : flow === "review" ? reviewProject : workspaceRoot;
    const projectAliases = Object.fromEntries(recentProjects.map((project) => [project.path, project.alias]));
    const desktopPreferences = JSON.stringify({
      language: preferenceLanguage,
      recentProjects,
      projectAliases,
      pinnedProjectKeys: [],
      pinnedSessions: [],
      expandedProjects: Object.fromEntries(recentProjects.map((project) => [project.path, true])),
      selectedProjectKey,
      selectedSessionId: null,
    });
    // Electron resolves app.getPath("userData") to the exact launcher-owned
    // --user-data-dir. Seed only that path and retain it while the Renderer
    // performs its normal atomic preference writes.
    seededPreferencePath = join(electronContext.userDataDir, "desktop-preferences.json");
    await mkdir(resolvePath(seededPreferencePath, ".."), { recursive: true });
    await writeFile(seededPreferencePath, desktopPreferences, "utf8");
    let fixtureReady;
    if (isInvalidConfigurationFlow) {
      // This deliberately malformed configuration exists only in the
      // runner-owned HOME and launcher profile. It exercises the visible
      // General recovery/cancel route without reading or modifying user data.
      const invalidConfiguration = "default_model = [\n";
      invalidConfigPath = join(host.env.HOME, ".uthcode", "config.toml");
      await mkdir(join(host.env.HOME, ".uthcode"), { recursive: true });
      await writeFile(electronContext.configPath, invalidConfiguration, "utf8");
      await writeFile(invalidConfigPath, invalidConfiguration, "utf8");
      invalidConfigBaselineHash = createHash("sha256").update(invalidConfiguration).digest("hex");
    } else if (isProviderFlow) {
      fixtureContext = await createIsolatedCdpContext({ mode: "isolated", prefix: `uthcode-cdp-fixture-${runId.slice(0, 8)}-` });
      const fixtureReadyPath = join(fixtureContext.root, "ready.json");
      fixtureChild = spawn(process.execPath, [
        fixturePath,
        "--port", "0",
        "--scenario", fixtureScenario,
        "--ready-file", fixtureReadyPath,
        "--plan-chunk-delay-ms", String(planChunkDelayMs),
        ...(flow === "delay" ? ["--delay-ms", "5000"] : []),
        ...(flow === "review" ? ["--review-markdown-path", join(reviewProject, "review.md"), "--review-text-path", join(reviewProject, "review.txt"), "--review-image-path", join(reviewProject, "review-attachment.png")] : []),
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
      const configuration = fixtureConfiguration(fixtureReady.baseUrl, flow === "review");
      await writeFile(electronContext.configPath, configuration, "utf8");
      // The packaged Runtime resolves its user config from HOME. Keep that
      // path inside the runner-owned host profile as well; the launcher-owned
      // UTHCODE_CONFIG_PATH remains a separate guard/receipt path.
      const hostConfigDirectory = join(host.env.HOME, ".uthcode");
      await mkdir(hostConfigDirectory, { recursive: true });
      await writeFile(join(hostConfigDirectory, "config.toml"), configuration, "utf8");
      electronContext.env.UTHCODE_CDP_FIXTURE_KEY = "fixture-test-key";
    } else if (!isRealProviderFlow) {
      // Visual/shell flows still bootstrap the real Runtime status path. Give
      // them the same valid user-config shape without starting a Provider
      // server or making any network request.
      const configuration = fixtureConfiguration("http://127.0.0.1:1/v1", false, isSettingsFlow ? "qwen3.7-flash-openai-responses" : "CDP fixture", isSettingsFlow);
      await writeFile(electronContext.configPath, configuration, "utf8");
      const hostConfigDirectory = join(host.env.HOME, ".uthcode");
      await mkdir(hostConfigDirectory, { recursive: true });
      await writeFile(join(hostConfigDirectory, "config.toml"), configuration, "utf8");
      electronContext.env.UTHCODE_CDP_FIXTURE_KEY = "fixture-test-key";
    }
    const stages = isLifecycleFlow ? ["seed", "restore"] : [null];
    let expectedSessions;
    for (const [stageIndex, stage] of stages.entries()) {
      electronChild = spawn(executablePath, ["--no-sandbox", `--remote-debugging-port=${port}`, "--disable-gpu", "--enable-logging=stderr", `--user-data-dir=${electronContext.userDataDir}`], {
        cwd: workspaceRoot,
        env: electronContext.env,
        stdio: ["ignore", "pipe", "pipe"],
        windowsHide: true,
      });
      electronOutput = collectOutput(electronChild);
      await waitForPackagedTarget(port, Math.min(timeoutMs, 15_000));

      driverContext = await createIsolatedCdpContext({ mode: "isolated", prefix: `uthcode-cdp-driver-${runId.slice(0, 8)}-${stage ?? "single"}-` });
      const rawReportPath = join(driverContext.root, "driver-report.json");
      const stageScreenshotDir = stage ? join(output, `stage-${stageIndex + 1}-${stage}`) : output;
      driverChild = spawn(process.execPath, [
        driverPath,
        "--port", String(port),
        "--flow", flow,
        "--language", preferenceLanguage,
        "--screenshot-dir", stageScreenshotDir,
        "--report", rawReportPath,
        "--packaged-exe", executablePath,
        "--timeout-ms", String(timeoutMs),
        "--request-timeout-ms", String(requestTimeoutMs),
        "--plan-chunk-delay-ms", String(planChunkDelayMs),
        ...(isProviderFlow ? ["--scenario", fixtureScenario] : []),
        ...(flow === "review" ? ["--expect-text", "W05_REVIEW_READY"] : []),
        ...(isLifecycleFlow ? ["--stage", stage, "--project-one", lifecycleProjectOne, "--project-two", lifecycleProjectTwo, ...(expectedSessions ? ["--expected-sessions", JSON.stringify(expectedSessions)] : [])] : []),
        ...(isSettingsFlow ? ["--project-one", lifecycleProjectOne, "--project-two", lifecycleProjectTwo] : []),
        ...(isDiffFlow ? ["--diff-project", diffProject, "--diff-unborn-project", diffUnbornProject] : []),
        ...(flow === "review" ? ["--review-markdown-path", join(reviewProject, "review.md"), "--review-text-path", join(reviewProject, "review.txt"), "--review-image-path", join(reviewProject, "review-attachment.png")] : []),
        ...(flow === "ask-one" ? ["--ask-question-count", "1"] : []),
        ...(flow === "plan" ? ["--plan-choice", planChoice] : []),
        ...(flow === "delay" || isGeneralCancelFlow ? ["--delay-action", delayAction] : []),
      ], { cwd: desktopRoot, env: driverContext.env, stdio: ["ignore", "pipe", "pipe"], windowsHide: true });
      driverOutput = collectOutput(driverChild);
      driverExit = await waitForChild(driverChild, timeoutMs + 15_000);
      rawDriverReport = await readJsonIfPresent(rawReportPath);
      const stageRun = { stage: stage ?? "single", electronOutput, driverOutput, electronExit: null, driverExit };
      stageRuns.push(stageRun);
      stageDriverReports.push(rawDriverReport);
      if (driverExit.code !== 0 || rawDriverReport?.status !== "passed") {
        throw new Error(`packaged CDP driver ${stage ?? "single"} failed: code=${driverExit.code} status=${rawDriverReport?.status ?? "missing"}`);
      }
      electronExit = await waitForChild(electronChild, 15_000);
      stageRun.electronExit = electronExit;
      if (electronExit.code !== 0) throw new Error(`packaged Electron ${stage ?? "single"} exited abnormally: code=${electronExit.code} signal=${electronExit.signal}`);
      if (isLifecycleFlow && stage === "seed") {
        expectedSessions = rawDriverReport?.observed?.flow?.lifecycle?.sessions;
        if (!expectedSessions?.one?.id || !expectedSessions?.two?.id || !expectedSessions?.general?.id) throw new Error("lifecycle seed did not return all three persistent Session identities");
      }
      if (stage) {
        for (const [name, buffer] of [
          [`stage-${stageIndex + 1}-${stage}-electron.stdout.log`, electronOutput.stdout()],
          [`stage-${stageIndex + 1}-${stage}-electron.stderr.log`, electronOutput.stderr()],
          [`stage-${stageIndex + 1}-${stage}-driver.stdout.log`, driverOutput.stdout()],
          [`stage-${stageIndex + 1}-${stage}-driver.stderr.log`, driverOutput.stderr()],
        ]) await writeLogArtifact(join(output, name), buffer);
      }
      if (isLifecycleFlow && stage === "seed") {
        await driverContext.cleanup();
        driverContext = undefined;
        electronChild = undefined;
        driverChild = undefined;
        electronExit = undefined;
        driverExit = undefined;
        electronOutput = undefined;
        driverOutput = undefined;
      }
    }
    rawDriverReport = stageDriverReports.at(-1) ?? rawDriverReport;
    if (fixtureChild) {
      fixtureExit = await terminateChild(fixtureChild);
    }
  } catch (error) {
    failure = errorEvidence(error);
  } finally {
    if (isInvalidConfigurationFlow && invalidConfigPath && invalidConfigBaselineHash) {
      try {
        const currentHash = createHash("sha256").update(await readFile(invalidConfigPath)).digest("hex");
        invalidConfigUnchanged = currentHash === invalidConfigBaselineHash;
        if (!invalidConfigUnchanged) {
          const message = "runner-owned invalid configuration changed during the recovery/cancel flow";
          failure = failure ? { ...failure, message: `${failure.message}; ${message}` } : { message, stack: null };
        }
      } catch {
        invalidConfigUnchanged = false;
        const message = "runner-owned invalid configuration could not be rechecked after the recovery/cancel flow";
        failure = failure ? { ...failure, message: `${failure.message}; ${message}` } : { message, stack: null };
      }
    }
    if (isRealProviderFlow && realProviderConfigSource && realProviderConfigBaselineHash) {
      try {
        const currentHash = createHash("sha256").update(await readFile(realProviderConfigSource)).digest("hex");
        realProviderConfigUnchanged = currentHash === realProviderConfigBaselineHash;
        if (!realProviderConfigUnchanged) {
          const message = "user-level configuration changed during the real Provider acceptance run";
          failure = failure ? { ...failure, message: `${failure.message}; ${message}` } : { message, stack: null };
        }
      } catch {
        realProviderConfigUnchanged = false;
        const message = "user-level configuration could not be rechecked after the real Provider acceptance run";
        failure = failure ? { ...failure, message: `${failure.message}; ${message}` } : { message, stack: null };
      }
    }
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
      await writeLogArtifact(logPaths.driverStdout, isRealProviderFlow ? Buffer.alloc(0) : driverOutput.stdout());
      await writeLogArtifact(logPaths.driverStderr, isRealProviderFlow ? Buffer.alloc(0) : driverOutput.stderr());
    }
    if (electronOutput) {
      await writeLogArtifact(logPaths.electronStdout, isRealProviderFlow ? Buffer.alloc(0) : electronOutput.stdout());
      await writeLogArtifact(logPaths.electronStderr, isRealProviderFlow ? Buffer.alloc(0) : electronOutput.stderr());
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
  const runSources = stageRuns.length > 0
    ? stageRuns
    : electronOutput || driverOutput ? [{ electronOutput, driverOutput }] : [];
  const combinedElectronStdout = Buffer.concat(runSources.map((stage) => stage.electronOutput?.stdout() ?? Buffer.alloc(0)));
  const combinedElectronStderr = Buffer.concat(runSources.map((stage) => stage.electronOutput?.stderr() ?? Buffer.alloc(0)));
  const combinedDriverStdout = Buffer.concat(runSources.map((stage) => stage.driverOutput?.stdout() ?? Buffer.alloc(0)));
  const combinedDriverStderr = Buffer.concat(runSources.map((stage) => stage.driverOutput?.stderr() ?? Buffer.alloc(0)));
  const electronStderrRaw = classifyStderr("electron", combinedElectronStderr, port, rendererEntryUri, isInvalidConfigurationFlow, executablePath);
  const driverStderrRaw = classifyStderr("driver", combinedDriverStderr, port);
  const electronStderr = isRealProviderFlow
    ? { lineCount: electronStderrRaw.lines.length, allowlistedCount: electronStderrRaw.allowlisted.length, unexplainedCount: electronStderrRaw.unexplained.length, detailsOmitted: true }
    : electronStderrRaw;
  const driverStderr = isRealProviderFlow
    ? { lineCount: driverStderrRaw.lines.length, allowlistedCount: driverStderrRaw.allowlisted.length, unexplainedCount: driverStderrRaw.unexplained.length, detailsOmitted: true }
    : driverStderrRaw;
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
  const allConsoleErrors = stageDriverReports.flatMap((report) => report?.consoleErrors ?? []);
  const allConsoleDiagnostics = stageDriverReports.flatMap((report) => report?.consoleDiagnostics ?? []);
  const allRendererExceptions = stageDriverReports.flatMap((report) => report?.rendererExceptions ?? []);
  const consoleErrors = isRealProviderFlow ? { count: allConsoleErrors.length, detailsOmitted: true } : allConsoleErrors;
  const consoleDiagnostics = isRealProviderFlow ? { count: allConsoleDiagnostics.length, detailsOmitted: true } : allConsoleDiagnostics;
  const rendererExceptions = isRealProviderFlow ? { count: allRendererExceptions.length, detailsOmitted: true } : allRendererExceptions;
  const driverPassed = stageRuns.length === (isLifecycleFlow ? 2 : 1)
    && stageRuns.every((stage, index) => stage.driverExit?.code === 0 && stageDriverReports[index]?.status === "passed");
  const electronPassed = stageRuns.length === (isLifecycleFlow ? 2 : 1) && stageRuns.every((stage) => stage.electronExit?.code === 0);
  const signalFailures = [];
  if (allConsoleErrors.length > 0) signalFailures.push(`Renderer console errors: ${allConsoleErrors.length}`);
  if (allConsoleDiagnostics.length > 0) signalFailures.push(`Electron console diagnostics: ${allConsoleDiagnostics.length}`);
  if (allRendererExceptions.length > 0) signalFailures.push(`Renderer exceptions: ${allRendererExceptions.length}`);
  if (electronStderrRaw.unexplained.length > 0) signalFailures.push(`Electron stderr: ${electronStderrRaw.unexplained.length} unexplained line(s)`);
  if (driverStderrRaw.unexplained.length > 0) signalFailures.push(`Driver stderr: ${driverStderrRaw.unexplained.length} unexplained line(s)`);
  if (fixtureStderr.unexplained.length > 0) signalFailures.push(`Fixture stderr: ${fixtureStderr.unexplained.length} unexplained line(s)`);
  if (isRealProviderFlow && realProviderConfigUnchanged !== true) signalFailures.push("user-level Provider configuration was not confirmed unchanged");
  const persistedSecretMarkers = ["fixture-test-key", "raw-native-secret"];
  const secretLeakArtifacts = [
    combinedElectronStdout,
    combinedElectronStderr,
    combinedDriverStdout,
    combinedDriverStderr,
    fixtureOutput?.stdout() ?? Buffer.alloc(0),
    fixtureOutput?.stderr() ?? Buffer.alloc(0),
  ].flatMap((buffer) => persistedSecretMarkers.filter((marker) => buffer.toString("utf8").includes(marker)));
  if (secretLeakArtifacts.length > 0) signalFailures.push(`Fixture secret persisted in process artifacts: ${[...new Set(secretLeakArtifacts)].join(", ")}`);
  // Six initial Turns plus one continuation; the plain-text fixture summary
  // fails validation twice before compaction reports its controlled failure.
  const expectedFixtureRequests = flow === "sessions" ? 9 : isLifecycleFlow || flow === "permission" ? 3 : isGeneralCancelFlow ? 1 : flow === "review" ? 2 : null;
  if (expectedFixtureRequests !== null && fixtureRequests.length !== expectedFixtureRequests) {
    signalFailures.push(`Fixture request count: expected ${expectedFixtureRequests}, observed ${fixtureRequests.length}`);
  }
  if (flow === "sessions" && (
    fixtureRequests.slice(0, 7).some((request) => request.toolCount <= 0)
    || fixtureRequests.slice(7).some((request) => request.toolCount !== 0)
  )) {
    signalFailures.push("Sessions fixture expected seven normal requests followed by two tool-free compaction attempts");
  }
  if (isLifecycleFlow && (
    fixtureRequests.slice(0, 2).some((request) => request.toolCount <= 0)
    || fixtureRequests.slice(2).some((request) => request.toolCount !== 0)
  )) {
    signalFailures.push("Lifecycle fixture expected two Coding requests with registered tools followed by one tool-free General request");
  }
  if (flow === "review" && (fixtureRequests[0]?.toolCount < 2 || fixtureRequests[1]?.messageRoles?.filter((role) => role === "tool").length !== 2)) {
    signalFailures.push("Review fixture expected one Coding request with two real Tools followed by their two Tool results");
  }
  if (isGeneralCancelFlow && fixtureRequests.some((request) => request.toolCount !== 0)) {
    signalFailures.push("General cancellation fixture unexpectedly exposed tools");
  }
  if (isInvalidConfigurationFlow && invalidConfigUnchanged !== true) {
    signalFailures.push("runner-owned invalid configuration was not confirmed unchanged");
  }
  const status = !failure && driverPassed && electronPassed && signalFailures.length === 0 ? "passed" : "failed";
  const finalFailure = failure ?? (signalFailures.length > 0 ? { message: signalFailures.join("; "), stack: null } : null);
  const report = {
    schemaVersion: 1,
    kind: "uthcode.packaged-electron.acceptance",
    runId,
    flow,
    fixture: isProviderFlow ? { scenario: fixtureScenario, expectedRequestCount: expectedFixtureRequests, requestCount: fixtureRequests.length, requestCountOk: expectedFixtureRequests === null || fixtureRequests.length === expectedFixtureRequests, requests: fixtureRequests, exit: { code: fixtureExit?.code ?? null, signal: fixtureExit?.signal ?? null } } : null,
    packagedExe: packagedExeEvidence,
    timestamp: { startedAt, finishedAt: new Date().toISOString() },
    language: { requested: language, preferenceValue: preferenceLanguage, observed: [...new Set(stageDriverReports.flatMap((report) => report?.observed?.languages ?? []))] },
    themes: [...new Set(stageDriverReports.flatMap((report) => report?.observed?.themes ?? []))],
    viewports: [...new Map(stageDriverReports.flatMap((report) => report?.observed?.viewports ?? []).map((viewport) => [JSON.stringify(viewport), viewport])).values()],
    runtimePanelLayouts: [...new Set(stageDriverReports.flatMap((report) => report?.observed?.runtimePanelLayouts ?? []))],
    flowEvidence: stageDriverReports.map((report) => report?.observed?.flow ?? {}),
    controlledReviewProject: reviewProject ? { path: reviewProject, alias: "T12 Review project", files: ["review-output.txt", "review.md", "review.txt", "review-attachment.png"] } : null,
    realProvider: isRealProviderFlow ? { requested: true, configCopiedIntoIsolatedHome: realProviderConfigCopied, sessionStorageIsolated: isolatedSessionStorageReady, userConfigurationUnchanged: realProviderConfigUnchanged } : null,
    configurationRecovery: isInvalidConfigurationFlow ? { input: "malformed TOML in runner-owned HOME", sessionStorageIsolated: true, configurationUnchanged: invalidConfigUnchanged } : null,
    screenshots: stageDriverReports.flatMap((report) => report?.screenshots ?? []),
    stages: stageRuns.map((stage, index) => ({
      stage: stage.stage,
      driver: { status: stageDriverReports[index]?.status ?? "missing", exitCode: stage.driverExit?.code ?? null, exitSignal: stage.driverExit?.signal ?? null },
      electron: { exitCode: stage.electronExit?.code ?? null, exitSignal: stage.electronExit?.signal ?? null },
    })),
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
