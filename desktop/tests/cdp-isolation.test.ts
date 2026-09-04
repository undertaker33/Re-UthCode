import { spawn, type ChildProcess } from "node:child_process";
import { randomUUID } from "node:crypto";
import { access, mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, win32 } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import assert from "node:assert/strict";

const desktopRoot = fileURLToPath(new URL("../", import.meta.url));
const launcherPath = fileURLToPath(new URL("../scripts/cdp-launcher.mjs", import.meta.url));
const driverPath = fileURLToPath(new URL("../scripts/cdp-driver.mjs", import.meta.url));
const fixturePath = fileURLToPath(new URL("../scripts/cdp-openai-fixture.mjs", import.meta.url));
const packagedAcceptancePath = fileURLToPath(new URL("../scripts/cdp-packaged-visual-acceptance.mjs", import.meta.url));
const realUserProfile = "C:\\Users\\93445";
const realUserConfig = "C:\\Users\\93445\\.uthcode\\config.toml";

type ExitResult = { code: number | null; signal: NodeJS.Signals | null };
type LaunchedProcess = { child: ChildProcess; stdout: () => string; stderr: () => string; rootReceipt: string };

async function temporarySentinelContent(path: string): Promise<string> {
  return readFile(path, "utf8");
}

function launch(commandPath: string, args: readonly string[], launcherOptions: readonly string[] = []): LaunchedProcess {
  const rootReceipt = join(tmpdir(), `uthcode-cdp-root-receipt-${randomUUID()}.txt`);
  const child = spawn(process.execPath, [launcherPath, "--root-receipt", rootReceipt, ...launcherOptions, "--", process.execPath, commandPath, ...args], {
    cwd: desktopRoot,
    env: process.env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  let stdout = "";
  let stderr = "";
  child.stdout?.on("data", (chunk) => { stdout += String(chunk); });
  child.stderr?.on("data", (chunk) => { stderr += String(chunk); });
  return { child, stdout: () => stdout, stderr: () => stderr, rootReceipt };
}

function launchCommand(command: string, args: readonly string[], launcherOptions: readonly string[] = []): LaunchedProcess {
  const rootReceipt = join(tmpdir(), `uthcode-cdp-root-receipt-${randomUUID()}.txt`);
  const child = spawn(process.execPath, [launcherPath, "--root-receipt", rootReceipt, ...launcherOptions, "--", command, ...args], {
    cwd: desktopRoot,
    env: process.env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  let stdout = "";
  let stderr = "";
  child.stdout?.on("data", (chunk) => { stdout += String(chunk); });
  child.stderr?.on("data", (chunk) => { stderr += String(chunk); });
  return { child, stdout: () => stdout, stderr: () => stderr, rootReceipt };
}

function isExactLauncherRoot(candidate: string): boolean {
  const normalized = win32.normalize(win32.resolve(candidate));
  const tempRoot = win32.normalize(win32.resolve(tmpdir())).replace(/[\\]+$/u, "");
  return win32.dirname(normalized).toLowerCase() === tempRoot.toLowerCase()
    && win32.basename(normalized).startsWith("uthcode-cdp-launch-");
}

async function cleanupLaunchedProcess(launched: LaunchedProcess): Promise<string | undefined> {
  let root: string | undefined;
  try {
    root = (await readFile(launched.rootReceipt, "utf8")).trim();
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
  }
  if (root) {
    assert.ok(isExactLauncherRoot(root), `launcher receipt must name one exact temp root: ${root}`);
    await rm(root, { recursive: true, force: true });
  }
  await rm(launched.rootReceipt, { force: true });
  return root;
}

async function waitForRootReceipt(launched: LaunchedProcess, timeoutMs = 3_000): Promise<string> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const root = (await readFile(launched.rootReceipt, "utf8")).trim();
      if (root) return root;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  throw new Error("launcher did not publish its exact temp-root receipt");
}

async function assertRootRemoved(root: string, receipt: string): Promise<void> {
  await assert.rejects(access(root), /ENOENT/u, "the exact launcher temp root must be absent");
  await assert.rejects(access(receipt), /ENOENT/u, "the launcher temp-root receipt must be absent");
}

function waitForExit(child: ChildProcess, timeoutMs: number): Promise<ExitResult> {
  if (child.exitCode !== null || child.signalCode !== null) {
    return Promise.resolve({ code: child.exitCode, signal: child.signalCode });
  }
  return new Promise((resolveExit, reject) => {
    const timer = setTimeout(() => reject(new Error("child did not exit within test timeout")), timeoutMs);
    child.once("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.once("exit", (code, signal) => {
      clearTimeout(timer);
      resolveExit({ code, signal });
    });
  });
}

async function stopChildProcess(child: ChildProcess): Promise<void> {
  if (child.exitCode !== null || child.signalCode !== null) return;
  const exited = waitForExit(child, 3_000);
  if (!child.kill("SIGTERM")) child.kill("SIGKILL");
  await exited;
}

async function stopChild(launched: LaunchedProcess): Promise<void> {
  try {
    await stopChildProcess(launched.child);
  } finally {
    // Windows terminates a launcher wrapper before its async finally can run.
    // The receipt is an exact path owned by this test invocation, so cleanup
    // cannot sweep unrelated launcher roots or another process's profile.
    await cleanupLaunchedProcess(launched);
  }
}

async function waitForLine(child: ChildProcess, predicate: (line: string) => boolean): Promise<string> {
  const output = child.stdout;
  assert.ok(output, "child stdout must be piped");
  return new Promise((resolveLine, reject) => {
    let buffer = "";
    const timer = setTimeout(() => {
      cleanup();
      reject(new Error("child did not emit the expected line within test timeout"));
    }, 3_000);
    const onData = (chunk: Buffer | string) => {
      buffer += String(chunk);
      const lines = buffer.split(/\r?\n/u);
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        if (predicate(line)) {
          cleanup();
          resolveLine(line);
          return;
        }
      }
    };
    const onEnd = () => {
      cleanup();
      reject(new Error("child stdout ended before the expected line"));
    };
    const cleanup = () => {
      clearTimeout(timer);
      output.off("data", onData);
      output.off("end", onEnd);
    };
    output.on("data", onData);
    output.on("end", onEnd);
  });
}

test("packaged acceptance forwards an explicit CDP request timeout to its existing driver", async () => {
  const source = await readFile(packagedAcceptancePath, "utf8");
  assert.match(source, /const requestTimeoutMs = Number\(option\("request-timeout-ms", "5000"\)\)/u);
  assert.match(source, /"--request-timeout-ms", String\(requestTimeoutMs\)/u);
});

test("CDP fixture and driver stay inside an isolated HOME without touching real config", async () => {
  const root = await mkdtemp(join(tmpdir(), "uthcode-cdp-isolation-"));
  const sentinelPath = join(root, "temporary-sentinel.txt");
  await writeFile(sentinelPath, "temporary sentinel\n", "utf8");
  const sentinelBefore = await temporarySentinelContent(sentinelPath);
  let fixture: LaunchedProcess | undefined;
  let driver: LaunchedProcess | undefined;
  try {
    const envLaunch = launchCommand(process.execPath, ["-e", "process.stdout.write(JSON.stringify({home:process.env.HOME,userProfile:process.env.USERPROFILE,appData:process.env.APPDATA,localAppData:process.env.LOCALAPPDATA,homeDrive:process.env.HOMEDRIVE,homePath:process.env.HOMEPATH}))"]);
    const envResult = await waitForExit(envLaunch.child, 3_000);
    await cleanupLaunchedProcess(envLaunch);
    assert.equal(envResult.code, 0);
    const launchEnvironment = JSON.parse(envLaunch.stdout()) as Record<string, string>;
    const tempRootKey = win32.normalize(tmpdir()).toLowerCase().replace(/[\\]+$/u, "");
    for (const name of ["home", "userProfile", "appData", "localAppData"]) {
      assert.ok(win32.isAbsolute(launchEnvironment[name]));
      assert.ok(launchEnvironment[name].toLowerCase().startsWith(`${tempRootKey}\\`));
    }
    assert.equal(launchEnvironment.home, launchEnvironment.userProfile);
    assert.equal(win32.normalize(`${launchEnvironment.homeDrive}${launchEnvironment.homePath}`).toLowerCase(), win32.normalize(launchEnvironment.home).toLowerCase());

    const fixtureLaunch = launch(fixturePath, ["--port", "0", "--scenario", "stream"]);
    fixture = fixtureLaunch;
    const readyLine = await waitForLine(fixture.child, (line) => line.includes('"event":"ready"'));
    assert.match(readyLine, /127\.0\.0\.1/u);
    await stopChild(fixture);
    fixture = undefined;

    const driverLaunch = launch(driverPath, ["--port", "29999", "--timeout-ms", "500", "--request-timeout-ms", "100"]);
    driver = driverLaunch;
    const driverExit = await waitForExit(driver.child, 3_000);
    await cleanupLaunchedProcess(driver);
    assert.notEqual(driverExit.code, 0);
    driver = undefined;

    assert.match(driverLaunch.stdout(), /driver_failure/u);
    assert.doesNotMatch(`${fixtureLaunch.stdout()}\n${driverLaunch.stdout()}`, /fixture-key|DEEPSEEK_API_KEY|raw-native-secret/u);
    assert.equal(await temporarySentinelContent(sentinelPath), sentinelBefore);
  } finally {
    if (fixture) await stopChild(fixture);
    if (driver) await stopChild(driver);
    await rm(root, { recursive: true, force: true });
  }
});

test("Electron launcher mode preserves Windows profile identity and isolates app state", async () => {
  const envLaunch = launchCommand(
    process.execPath,
    [
      "-e",
      "const names=['HOME','USERPROFILE','APPDATA','LOCALAPPDATA','HOMEDRIVE','HOMEPATH']; const values=Object.fromEntries(names.map((name)=>[name,process.env[name]])); const userDataArg=process.argv.find((value)=>value.startsWith('--user-data-dir=')); const userData=userDataArg?.slice('--user-data-dir='.length); process.stdout.write(JSON.stringify({values,config:process.env.UTHCODE_CONFIG_PATH,userData}));",
      "--",
    ],
    ["--electron"],
  );
  const result = await waitForExit(envLaunch.child, 3_000);
  await cleanupLaunchedProcess(envLaunch);
  assert.equal(result.code, 0);
  const launched = JSON.parse(envLaunch.stdout()) as {
    values: Record<string, string>;
    config: string;
    userData: string;
  };
  for (const name of ["HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOMEDRIVE", "HOMEPATH"]) {
    assert.equal(launched.values[name], process.env[name], `${name} must retain the Windows identity value`);
  }
  assert.notEqual(launched.config, realUserConfig);
  assert.ok(win32.normalize(launched.config).toLowerCase().startsWith(win32.normalize(tmpdir()).toLowerCase()));
  assert.ok(launched.userData);
  assert.ok(win32.normalize(launched.userData).toLowerCase().startsWith(win32.normalize(tmpdir()).toLowerCase()));
  assert.notEqual(win32.normalize(launched.userData).toLowerCase(), win32.normalize(launched.config).toLowerCase());
});

test("Electron launcher mode rejects profile, config, and user-data-dir escapes before spawn", async () => {
  const cases: Array<{ args: string[]; options: string[] }> = [
    { args: ["-e", "process.stdout.write('spawned')", "--"], options: ["--electron", "--env", `HOME=${realUserProfile}`] },
    { args: ["-e", "process.stdout.write('spawned')", "--"], options: ["--electron", "--env", `USERPROFILE=${realUserProfile}`] },
    { args: ["-e", "process.stdout.write('spawned')", "--"], options: ["--electron", "--env", `UTHCODE_CONFIG_PATH=${realUserConfig}`] },
    { args: ["-e", "process.stdout.write('spawned')", "--", `--user-data-dir=${realUserProfile}`], options: ["--electron"] },
  ];
  for (const { args, options } of cases) {
    const launchResult = launchCommand(process.execPath, args, options);
    const result = await waitForExit(launchResult.child, 3_000);
    await cleanupLaunchedProcess(launchResult);
    assert.notEqual(result.code, 0);
    assert.equal(launchResult.stdout(), "");
    assert.equal(launchResult.stderr(), "");
  }
});

test("launcher rejects protected environment names case-insensitively in both modes", async () => {
  const cases: string[][] = [
    ["--electron", "--env", `home=${realUserProfile}`],
    ["--electron", "--env", `uSeRpRoFiLe=${realUserProfile}`],
    ["--electron", "--env", `uThCoDe_CoNfIg_PaTh=${realUserConfig}`],
    ["--env", `home=${realUserProfile}`],
    ["--env", `uThCoDe_CoNfIg_PaTh=${realUserConfig}`],
    ["--env", "HOME=C:\\Users\\93445", "--env", "home=C:\\Users\\93445"],
  ];
  for (const options of cases) {
    const launchResult = launchCommand(process.execPath, ["-e", "process.stdout.write('spawned')"], options);
    const result = await waitForExit(launchResult.child, 3_000);
    await cleanupLaunchedProcess(launchResult);
    assert.notEqual(result.code, 0);
    assert.equal(launchResult.stdout(), "");
    assert.equal(launchResult.stderr(), "");
  }
});

test("launcher root receipt cleanup covers success, failure, and runner timeout", async () => {
  const cases = [
    { label: "success", args: ["-e", "process.exit(0)"], expectedCode: 0, forceStop: false },
    { label: "failure", args: ["-e", "process.exit(7)"], expectedCode: 7, forceStop: false },
    { label: "timeout", args: ["-e", "setTimeout(() => {}, 60000)"], expectedCode: null, forceStop: true },
  ] as const;
  const unrelatedRoot = await mkdtemp(join(tmpdir(), "uthcode-cdp-unrelated-"));
  const unrelatedSentinel = join(unrelatedRoot, "must-survive.txt");
  await writeFile(unrelatedSentinel, "unrelated sentinel\n", "utf8");
  try {
    for (const { label, args, expectedCode, forceStop } of cases) {
      const launched = launchCommand(process.execPath, args);
      const root = await waitForRootReceipt(launched);
      const topLevel = await readdir(root, { withFileTypes: true });
      assert.deepEqual(topLevel.filter((entry) => entry.isDirectory()).map((entry) => entry.name).sort(), ["appdata", "home", "localappdata"], `${label} root must contain the three isolated profile directories`);
      const homeChildren = await readdir(join(root, "home"), { withFileTypes: true });
      assert.deepEqual(homeChildren.filter((entry) => entry.isDirectory()).map((entry) => entry.name), [".uthcode"], `${label} root must contain the .uthcode skeleton`);
      if (forceStop) {
        await stopChild(launched);
      } else {
        const result = await waitForExit(launched.child, 3_000);
        await cleanupLaunchedProcess(launched);
        assert.equal(result.code, expectedCode, `${label} launcher exit code`);
      }
      await assertRootRemoved(root, launched.rootReceipt);
    }
    assert.equal(await temporarySentinelContent(unrelatedSentinel), "unrelated sentinel\n");
  } finally {
    await rm(unrelatedRoot, { recursive: true, force: true });
  }
});

test("CDP driver enforces one global deadline when target discovery cannot complete", async () => {
  const driverLaunch = launch(driverPath, ["--port", "29994", "--timeout-ms", "180", "--request-timeout-ms", "50"]);
  try {
    const startedAt = performance.now();
    const result = await waitForExit(driverLaunch.child, 3_000);
    await cleanupLaunchedProcess(driverLaunch);
    const elapsedMs = performance.now() - startedAt;
    assert.notEqual(result.code, 0);
    assert.ok(elapsedMs < 1_500, `driver exceeded bounded flow budget: ${elapsedMs}ms`);
    assert.match(driverLaunch.stdout(), /Global CDP flow deadline exceeded|target did not appear/u);
  } finally {
    if (driverLaunch.child.exitCode === null && driverLaunch.child.signalCode === null) await stopChild(driverLaunch);
  }
});

test("CDP shell flow accepts a fixed target mode and stops before provider actions when target is absent", async () => {
  const driverLaunch = launch(driverPath, ["--port", "29993", "--flow", "shell", "--timeout-ms", "180", "--request-timeout-ms", "50"]);
  try {
    const result = await waitForExit(driverLaunch.child, 3_000);
    await cleanupLaunchedProcess(driverLaunch);
    assert.notEqual(result.code, 0);
    assert.match(driverLaunch.stdout(), /"flow":"shell"/u);
    assert.doesNotMatch(driverLaunch.stdout(), /click_text|driver_complete/u);
  } finally {
    if (driverLaunch.child.exitCode === null && driverLaunch.child.signalCode === null) await stopChild(driverLaunch);
  }
});

test("CDP scripts reject real profile and exact real config/report targets before starting", async () => {
  const root = await mkdtemp(join(tmpdir(), "uthcode-cdp-guard-"));
  const sentinelPath = join(root, "temporary-sentinel.txt");
  await writeFile(sentinelPath, "temporary sentinel\n", "utf8");
  const sentinelBefore = await temporarySentinelContent(sentinelPath);
  const children: ChildProcess[] = [];
  try {
    for (const [scriptPath, args] of [
      [fixturePath, ["--port", "0"]],
      [driverPath, ["--port", "29998", "--timeout-ms", "500", "--request-timeout-ms", "100"]],
    ] as const) {
      const launchResult = launch(scriptPath, args, ["--env", `HOME=${realUserProfile}`]);
      children.push(launchResult.child);
      const result = await waitForExit(launchResult.child, 3_000);
      await cleanupLaunchedProcess(launchResult);
      assert.notEqual(result.code, 0);
      assert.equal(launchResult.stdout(), "");
      assert.equal(launchResult.stderr(), "");
    }

    const workspaceHome = launch(driverPath, ["--port", "29995", "--timeout-ms", "500", "--request-timeout-ms", "100"], ["--env", `HOME=${desktopRoot}`]);
    children.push(workspaceHome.child);
    const workspaceResult = await waitForExit(workspaceHome.child, 3_000);
    await cleanupLaunchedProcess(workspaceHome);
    assert.notEqual(workspaceResult.code, 0);
    assert.equal(workspaceHome.stdout(), "");
    assert.equal(workspaceHome.stderr(), "");

    const configGuard = launch(driverPath, ["--port", "29997", "--timeout-ms", "500", "--request-timeout-ms", "100"], ["--env", `UTHCODE_CONFIG_PATH=${realUserConfig}`]);
    children.push(configGuard.child);
    const configResult = await waitForExit(configGuard.child, 3_000);
    await cleanupLaunchedProcess(configGuard);
    assert.notEqual(configResult.code, 0);
    assert.equal(configGuard.stdout(), "");
    assert.equal(configGuard.stderr(), "");

    const insideReportPath = join(root, "inside-report.json");
    const insideReport = launch(driverPath, ["--port", "29991", "--timeout-ms", "180", "--request-timeout-ms", "50", "--report", insideReportPath]);
    children.push(insideReport.child);
    const insideResult = await waitForExit(insideReport.child, 3_000);
    await cleanupLaunchedProcess(insideReport);
    assert.notEqual(insideResult.code, 0);
    await access(insideReportPath);
    const insideReportData = JSON.parse(await readFile(insideReportPath, "utf8")) as { status?: string };
    assert.equal(insideReportData.status, "failed");
    await rm(insideReportPath, { force: true });

    for (const [scriptPath, args] of [
      [fixturePath, ["--port", "0", "--log", realUserConfig]],
      [driverPath, ["--port", "29996", "--timeout-ms", "500", "--request-timeout-ms", "100", "--log", realUserConfig]],
    ] as const) {
      const outputGuard = launch(scriptPath, args);
      children.push(outputGuard.child);
      const outputResult = await waitForExit(outputGuard.child, 3_000);
      await cleanupLaunchedProcess(outputGuard);
      assert.notEqual(outputResult.code, 0);
      assert.equal(outputGuard.stdout(), "");
      assert.equal(outputGuard.stderr(), "");
    }

    const reportGuard = launch(driverPath, ["--port", "29992", "--timeout-ms", "500", "--request-timeout-ms", "100", "--report", realUserConfig]);
    children.push(reportGuard.child);
    const reportResult = await waitForExit(reportGuard.child, 3_000);
    await cleanupLaunchedProcess(reportGuard);
    assert.notEqual(reportResult.code, 0);
    assert.equal(reportGuard.stdout(), "");
    assert.match(reportGuard.stderr(), /cdp-driver isolation_failure:.*real user profile\/config/u);
    assert.equal(await temporarySentinelContent(sentinelPath), sentinelBefore);
  } finally {
    for (const child of children) {
      if (child.exitCode === null && child.signalCode === null) await stopChildProcess(child);
    }
    await rm(root, { recursive: true, force: true });
  }
});
