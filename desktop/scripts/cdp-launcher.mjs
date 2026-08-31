#!/usr/bin/env node

/**
 * Security preflight and bounded launcher for offline CDP commands.
 *
 * The launcher creates one unique system-temp root before spawning anything,
 * derives every Windows user-state variable from that root, and refuses an
 * override that escapes it.  It is intentionally a test harness; it does not
 * change the Desktop product's runtime configuration rules.
 *
 * CLI:
 *   node scripts/cdp-launcher.mjs -- node scripts/cdp-openai-fixture.mjs --port 0
 *   node scripts/cdp-launcher.mjs --electron -- UthCode.exe --remote-debugging-port=9229
 *
 * The default mode gives fixtures, drivers, and Python helpers a fully isolated
 * Windows profile. Electron mode deliberately preserves the host Windows
 * profile identity (Chromium uses it while bootstrapping), but redirects the
 * UthCode config and forces a unique temporary user-data directory.
 */

import { spawn } from "node:child_process";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { join, win32 } from "node:path";

const DESKTOP_ROOT = fileURLToPath(new URL("../", import.meta.url));
const WORKSPACE_ROOT = fileURLToPath(new URL("../../", import.meta.url));
const REQUIRED_PATH_ENV = ["HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA"];
const WINDOWS_PROFILE_ENV = ["HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOMEDRIVE", "HOMEPATH"];
const OUTPUT_FLAGS = new Set(["--log", "--ready-file", "--log-file", "--user-data-dir"]);
const ROOT_RECEIPT_FLAG = "--root-receipt";
const LAUNCH_MODES = new Set(["isolated", "electron"]);
const MANAGED_ENV_KEYS = new Set([...WINDOWS_PROFILE_ENV, "UTHCODE_CONFIG_PATH"].map((name) => name.toUpperCase()));

function lexicalPath(value) {
  return win32.normalize(win32.resolve(String(value))).toLowerCase();
}

function samePath(left, right) {
  return lexicalPath(left) === lexicalPath(right);
}

function isWithin(candidate, root) {
  const candidateKey = lexicalPath(candidate);
  const rootKey = lexicalPath(root).replace(/[\\]+$/u, "");
  return candidateKey === rootKey || candidateKey.startsWith(`${rootKey}\\`);
}

function assertRootedPath(label, value, root) {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${label} is required`);
  if (!isWithin(value, root)) throw new Error(`${label} escapes isolated root`);
  if (isWithin(value, WORKSPACE_ROOT) && label === "HOME") throw new Error("HOME cannot be the workspace");
}

function assertRootReceiptPath(value) {
  if (typeof value !== "string" || !value.trim()) throw new Error("root receipt is required");
  if (samePath(value, tmpdir()) || samePath(value, WORKSPACE_ROOT)) throw new Error("root receipt must be a file path");
  if (!isWithin(value, tmpdir()) && !isWithin(value, WORKSPACE_ROOT)) {
    throw new Error("root receipt must be under the system temp or workspace");
  }
}

export function assertCdpLaunchEnvironment({ root, env, outputPaths = [], mode = "isolated", userDataDir }) {
  if (!LAUNCH_MODES.has(mode)) throw new Error(`unsupported launch mode: ${mode}`);
  assertRootedPath("launch root", root, tmpdir());
  assertRootedPath("UTHCODE_CONFIG_PATH", env.UTHCODE_CONFIG_PATH, root);
  if (mode === "isolated") {
    const home = env.HOME;
    const userProfile = env.USERPROFILE;
    for (const name of REQUIRED_PATH_ENV) assertRootedPath(name, env[name], root);
    if (!samePath(home, userProfile)) throw new Error("HOME and USERPROFILE must identify the same isolated root");

    const homeFromDrivePair = `${env.HOMEDRIVE ?? ""}${env.HOMEPATH ?? ""}`;
    if (!env.HOMEDRIVE || !env.HOMEPATH || !samePath(homeFromDrivePair, userProfile)) {
      throw new Error("HOMEDRIVE/HOMEPATH must identify USERPROFILE");
    }
    if (!isWithin(homeFromDrivePair, root)) throw new Error("HOMEDRIVE/HOMEPATH escapes isolated root");
  } else {
    if (!userDataDir) throw new Error("Electron user-data-dir is required");
    assertRootedPath("Electron user-data-dir", userDataDir, root);
    if (samePath(userDataDir, env.UTHCODE_CONFIG_PATH)) throw new Error("Electron user-data-dir must be separate from config");
  }
  for (const outputPath of outputPaths) assertRootedPath("launcher output", outputPath, root);
}

function windowsDrivePair(path) {
  const normalized = win32.normalize(path);
  const parsed = win32.parse(normalized);
  return { drive: parsed.root.slice(0, 2), path: normalized.slice(2) || "\\" };
}

function validateEnvOverrides(envOverrides) {
  const seen = new Set();
  for (const name of Object.keys(envOverrides)) {
    const normalizedName = name.toUpperCase();
    if (seen.has(normalizedName)) throw new Error(`duplicate environment key: ${name}`);
    seen.add(normalizedName);
    if (MANAGED_ENV_KEYS.has(normalizedName)) {
      throw new Error(`managed environment key cannot be overridden: ${name}`);
    }
  }
}

function rejectCallerUserDataDir(args) {
  for (let index = 0; index < args.length; index += 1) {
    const argument = args[index];
    const equalsIndex = argument.indexOf("=");
    const flag = equalsIndex >= 0 ? argument.slice(0, equalsIndex) : argument;
    if (flag !== "--user-data-dir") continue;
    throw new Error("Electron --user-data-dir is launcher-managed");
  }
}

function electronArgs(args, userDataDir) {
  rejectCallerUserDataDir(args);
  return [...args, `--user-data-dir=${userDataDir}`];
}

export async function createIsolatedCdpContext({ prefix = "uthcode-cdp-launch-", envOverrides = {}, outputPaths = [], mode = "isolated" } = {}) {
  if (!LAUNCH_MODES.has(mode)) throw new Error(`unsupported launch mode: ${mode}`);
  validateEnvOverrides(envOverrides);
  const root = await mkdtemp(join(tmpdir(), prefix));
  const home = join(root, "home");
  const appData = join(root, "appdata");
  const localAppData = join(root, "localappdata");
  const configPath = join(home, ".uthcode", "config.toml");
  const userDataDir = join(root, "electron-user-data");
  const homePair = windowsDrivePair(home);
  const env = mode === "electron"
    ? { ...process.env, UTHCODE_CONFIG_PATH: configPath }
    : {
      ...process.env,
      HOME: home,
      USERPROFILE: home,
      APPDATA: appData,
      LOCALAPPDATA: localAppData,
      HOMEDRIVE: homePair.drive,
      HOMEPATH: homePair.path,
      UTHCODE_CONFIG_PATH: configPath,
    };
  Object.assign(env, envOverrides);
  try {
    assertCdpLaunchEnvironment({ root, env, outputPaths, mode, userDataDir: mode === "electron" ? userDataDir : undefined });
    await mkdir(join(home, ".uthcode"), { recursive: true });
    await mkdir(appData, { recursive: true });
    await mkdir(localAppData, { recursive: true });
    return {
      root,
      home,
      appData,
      localAppData,
      configPath,
      userDataDir,
      mode,
      env,
      cleanup: () => rm(root, { recursive: true, force: true }),
    };
  } catch (error) {
    await rm(root, { recursive: true, force: true });
    throw error;
  }
}

function outputPathsFromArgs(args) {
  const paths = [];
  for (let index = 0; index < args.length; index += 1) {
    const argument = args[index];
    const equalsIndex = argument.indexOf("=");
    const flag = equalsIndex >= 0 ? argument.slice(0, equalsIndex) : argument;
    if (!OUTPUT_FLAGS.has(flag)) continue;
    const value = equalsIndex >= 0 ? argument.slice(equalsIndex + 1) : args[index + 1];
    if (equalsIndex < 0) index += 1;
    if (value) paths.push(value);
  }
  return paths;
}

export async function spawnIsolatedCommand({ command, args = [], cwd = DESKTOP_ROOT, envOverrides = {}, stdio = "inherit", prefix, mode = "isolated", rootReceipt } = {}) {
  if (!command) throw new Error("launcher command is required");
  validateEnvOverrides(envOverrides);
  if (rootReceipt) assertRootReceiptPath(rootReceipt);
  if (mode === "electron") rejectCallerUserDataDir(args);
  const context = await createIsolatedCdpContext({ prefix, envOverrides, mode });
  const launchArgs = mode === "electron" ? electronArgs(args, context.userDataDir) : args;
  try {
    assertCdpLaunchEnvironment({
      root: context.root,
      env: context.env,
      mode,
      userDataDir: mode === "electron" ? context.userDataDir : undefined,
      outputPaths: outputPathsFromArgs(launchArgs),
    });
    if (rootReceipt) await writeFile(rootReceipt, `${context.root}\n`, "utf8");
  } catch (error) {
    await context.cleanup();
    if (rootReceipt) await rm(rootReceipt, { force: true });
    throw error;
  }
  let child;
  try {
    child = spawn(command, launchArgs, { cwd, env: context.env, stdio, windowsHide: true });
    return { child, context, rootReceipt };
  } catch (error) {
    await context.cleanup();
    if (rootReceipt) await rm(rootReceipt, { force: true });
    throw error;
  }
}

function parseEnvOverride(value) {
  const separator = value.indexOf("=");
  if (separator <= 0) throw new Error("--env requires NAME=VALUE");
  return [value.slice(0, separator), value.slice(separator + 1)];
}

function parseCli(argv) {
  const separator = argv.indexOf("--");
  if (separator < 0 || separator === argv.length - 1) throw new Error("launcher requires a command after --");
  const envOverrides = {};
  let mode = "isolated";
  let rootReceipt;
  for (let index = 0; index < separator; index += 1) {
    if (argv[index] === "--electron") {
      mode = "electron";
      continue;
    }
    if (argv[index] === ROOT_RECEIPT_FLAG) {
      rootReceipt = argv[index + 1];
      if (!rootReceipt) throw new Error("--root-receipt requires a path");
      index += 1;
      continue;
    }
    if (argv[index] !== "--env") throw new Error(`unknown launcher option: ${argv[index]}`);
    const [name, value] = parseEnvOverride(argv[index + 1] ?? "");
    envOverrides[name] = value;
    index += 1;
  }
  return { envOverrides, mode, rootReceipt, command: argv[separator + 1], args: argv.slice(separator + 2) };
}

function waitForChild(child) {
  return new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("exit", (code, signal) => resolve({ code, signal }));
  });
}

async function main() {
  const parsed = parseCli(process.argv.slice(2));
  const launched = await spawnIsolatedCommand(parsed);
  let shutdownTimer;
  const forwardSignal = (signal) => {
    if (launched.child.exitCode === null && launched.child.signalCode === null) {
      launched.child.kill(signal);
      shutdownTimer = setTimeout(() => {
        if (launched.child.exitCode === null && launched.child.signalCode === null) launched.child.kill("SIGKILL");
      }, 3_000);
    }
  };
  process.once("SIGINT", () => forwardSignal("SIGINT"));
  process.once("SIGTERM", () => forwardSignal("SIGTERM"));
  try {
    const result = await waitForChild(launched.child);
    process.exitCode = result.code ?? 1;
  } finally {
    if (shutdownTimer) clearTimeout(shutdownTimer);
    await launched.context.cleanup();
    if (parsed.rootReceipt) await rm(parsed.rootReceipt, { force: true });
  }
}

if (process.argv[1] && samePath(process.argv[1], fileURLToPath(import.meta.url))) {
  main().catch(() => {
    // Preflight failures intentionally produce no output and spawn no child.
    process.exitCode = 1;
  });
}
