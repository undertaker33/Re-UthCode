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
 *   node scripts/cdp-launcher.mjs --env UTHCODE_CONFIG_PATH=C:\\Users\\93445\\.uthcode\\config.toml -- node scripts/cdp-driver.mjs
 */

import { spawn } from "node:child_process";
import { mkdtemp, mkdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { join, win32 } from "node:path";

const DESKTOP_ROOT = fileURLToPath(new URL("../", import.meta.url));
const WORKSPACE_ROOT = fileURLToPath(new URL("../../", import.meta.url));
const REQUIRED_PATH_ENV = ["HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA"];
const OUTPUT_FLAGS = new Set(["--log", "--ready-file", "--log-file", "--user-data-dir"]);

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

export function assertCdpLaunchEnvironment({ root, env, outputPaths = [] }) {
  assertRootedPath("launch root", root, tmpdir());
  const home = env.HOME;
  const userProfile = env.USERPROFILE;
  for (const name of REQUIRED_PATH_ENV) assertRootedPath(name, env[name], root);
  if (!samePath(home, userProfile)) throw new Error("HOME and USERPROFILE must identify the same isolated root");

  const homeFromDrivePair = `${env.HOMEDRIVE ?? ""}${env.HOMEPATH ?? ""}`;
  if (!env.HOMEDRIVE || !env.HOMEPATH || !samePath(homeFromDrivePair, userProfile)) {
    throw new Error("HOMEDRIVE/HOMEPATH must identify USERPROFILE");
  }
  if (!isWithin(homeFromDrivePair, root)) throw new Error("HOMEDRIVE/HOMEPATH escapes isolated root");

  assertRootedPath("UTHCODE_CONFIG_PATH", env.UTHCODE_CONFIG_PATH, root);
  for (const outputPath of outputPaths) assertRootedPath("launcher output", outputPath, root);
}

function windowsDrivePair(path) {
  const normalized = win32.normalize(path);
  const parsed = win32.parse(normalized);
  return { drive: parsed.root.slice(0, 2), path: normalized.slice(2) || "\\" };
}

export async function createIsolatedCdpContext({ prefix = "uthcode-cdp-launch-", envOverrides = {}, outputPaths = [] } = {}) {
  const root = await mkdtemp(join(tmpdir(), prefix));
  const home = join(root, "home");
  const appData = join(root, "appdata");
  const localAppData = join(root, "localappdata");
  const configPath = join(home, ".uthcode", "config.toml");
  const homePair = windowsDrivePair(home);
  const env = {
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
    assertCdpLaunchEnvironment({ root, env, outputPaths });
    await mkdir(join(home, ".uthcode"), { recursive: true });
    await mkdir(appData, { recursive: true });
    await mkdir(localAppData, { recursive: true });
    return {
      root,
      home,
      appData,
      localAppData,
      configPath,
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

export async function spawnIsolatedCommand({ command, args = [], cwd = DESKTOP_ROOT, envOverrides = {}, stdio = "inherit", prefix } = {}) {
  if (!command) throw new Error("launcher command is required");
  const context = await createIsolatedCdpContext({ prefix, envOverrides, outputPaths: outputPathsFromArgs(args) });
  let child;
  try {
    child = spawn(command, args, { cwd, env: context.env, stdio, windowsHide: true });
    return { child, context };
  } catch (error) {
    await context.cleanup();
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
  for (let index = 0; index < separator; index += 1) {
    if (argv[index] !== "--env") throw new Error(`unknown launcher option: ${argv[index]}`);
    const [name, value] = parseEnvOverride(argv[index + 1] ?? "");
    envOverrides[name] = value;
    index += 1;
  }
  return { envOverrides, command: argv[separator + 1], args: argv.slice(separator + 2) };
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
  }
}

main().catch(() => {
  // Preflight failures intentionally produce no output and spawn no child.
  process.exitCode = 1;
});
