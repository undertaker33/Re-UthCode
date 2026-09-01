import { mkdtemp, mkdir, rm, stat, writeFile } from "node:fs/promises";
import { spawn, spawnSync } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const desktopRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = resolve(desktopRoot, "..");
const specPath = join(desktopRoot, "packaging", "uthcode-runtime.spec");
const outputRoot = join(desktopRoot, ".runtime");
const workRoot = join(desktopRoot, "packaging", ".build");
const runtimeRoot = join(outputRoot, "uthcode-runtime");
const runtimeExecutable = join(runtimeRoot, "uthcode-desktop-runtime.exe");
const condaEnvironment = "re-uthcode";
const smokeTimeoutMs = 15_000;
const smokeConfig = `default_model = "fake/ref"
default_permission_mode = "default"

[providers.fake]
kind = "fake"

[models."fake/ref"]
provider = "fake"
remote_id = "fake-model"
`;

async function assertFile(path, description) {
  try {
    const metadata = await stat(path);
    if (!metadata.isFile()) throw new Error(`${description} is not a file: ${path}`);
  } catch (error) {
    if (error instanceof Error && error.message.includes(" is not a file: ")) throw error;
    throw new Error(`${description} is missing: ${path}`);
  }
}

async function assertDirectory(path, description) {
  try {
    const metadata = await stat(path);
    if (!metadata.isDirectory()) throw new Error(`${description} is not a directory: ${path}`);
  } catch (error) {
    if (error instanceof Error && error.message.includes(" is not a directory: ")) throw error;
    throw new Error(`${description} is missing: ${path}`);
  }
}

function waitForClose(child) {
  return new Promise((resolve) => {
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill();
    }, smokeTimeoutMs);
    child.once("error", (error) => {
      clearTimeout(timer);
      resolve({ code: null, signal: null, timedOut, error });
    });
    child.once("close", (code, signal) => {
      clearTimeout(timer);
      resolve({ code, signal, timedOut });
    });
  });
}

function assertSmokeResponse(responses, id, description) {
  const response = responses.get(id);
  if (!response) throw new Error(`Runtime smoke missing ${description} response (${id})`);
  if (response.ok !== true) throw new Error(`Runtime smoke ${description} response was not ok`);
  return response;
}

async function smokeBundledRuntime({ command = runtimeExecutable, args = [] } = {}) {
  const smokeHome = await mkdtemp(join(desktopRoot, ".tmp-runtime-smoke-"));
  const child = spawn(command, args, {
    cwd: repoRoot,
    env: {
      ...process.env,
      HOME: smokeHome,
      USERPROFILE: smokeHome,
    },
    shell: false,
    stdio: ["pipe", "pipe", "pipe"],
    windowsHide: true,
  });
  const stdoutChunks = [];
  const stderrChunks = [];
  child.stdout.on("data", (chunk) => stdoutChunks.push(chunk.toString()));
  child.stderr.on("data", (chunk) => stderrChunks.push(chunk.toString()));

  try {
    await mkdir(join(smokeHome, ".uthcode"), { recursive: true });
    await writeFile(join(smokeHome, ".uthcode", "config.toml"), smokeConfig, "utf8");
    const requests = [
      ["t08-initialize", "runtime.initialize", { workdir: repoRoot }],
      ["t08-session", "session.new", {}],
      ["t08-status", "status.get", {}],
      ["t08-shutdown", "runtime.shutdown", {}],
    ];
    for (const [id, method, params] of requests) {
      child.stdin.write(`${JSON.stringify({ type: "request", id, method, params })}\n`);
    }
    child.stdin.end();
    const closed = await waitForClose(child);
    const stdout = stdoutChunks.join("").replaceAll("\r\n", "\n");
    const stderr = stderrChunks.join("");
    if (closed.error) throw new Error(`Runtime smoke process error: ${closed.error.message}`);
    if (closed.timedOut) throw new Error(`Runtime smoke exceeded ${smokeTimeoutMs}ms`);
    if (closed.code !== 0 || closed.signal !== null) {
      throw new Error(`Runtime smoke exited abnormally: code=${closed.code}, signal=${closed.signal}`);
    }
    if (stderr.trim()) throw new Error(`Runtime smoke wrote to stderr: ${stderr.trim()}`);

    const lines = stdout.split("\n");
    if (lines.at(-1) === "") lines.pop();
    if (lines.length === 0 || lines.some((line) => !line.trim())) {
      throw new Error("Runtime smoke stdout was not non-empty JSONL");
    }
    let envelopes;
    try {
      envelopes = lines.map((line) => JSON.parse(line));
    } catch (error) {
      throw new Error(`Runtime smoke stdout contained invalid JSONL: ${error.message}`);
    }
    const ready = envelopes.filter((envelope) => envelope.type === "runtime_state" && envelope.state === "ready");
    if (ready.length !== 1) throw new Error("Runtime smoke did not emit exactly one ready event");
    const responses = new Map();
    for (const envelope of envelopes.filter((item) => item.type === "response")) {
      if (typeof envelope.id !== "string" || responses.has(envelope.id)) {
        throw new Error("Runtime smoke response correlation was missing or duplicated");
      }
      responses.set(envelope.id, envelope);
    }
    const expectedIds = ["t08-initialize", "t08-session", "t08-status", "t08-shutdown"];
    if (responses.size !== expectedIds.length || expectedIds.some((id) => !responses.has(id))) {
      throw new Error("Runtime smoke response correlation did not match the request set");
    }
    assertSmokeResponse(responses, "t08-initialize", "initialize");
    assertSmokeResponse(responses, "t08-session", "session.new");
    const status = assertSmokeResponse(responses, "t08-status", "status");
    assertSmokeResponse(responses, "t08-shutdown", "shutdown");
    const applicationStatus = status.result?.application;
    const contextStatus = applicationStatus?.context_status;
    if (
      contextStatus?.available !== true ||
      contextStatus.source !== "context_compiler" ||
      typeof applicationStatus?.stable_prefix_fingerprint !== "string" ||
      applicationStatus.stable_prefix_fingerprint.length === 0
    ) {
      throw new Error("Runtime smoke did not compile an Application context from the bundled prompt asset");
    }
    console.log("Bundled Runtime smoke passed: ready/status/shutdown JSONL and importlib.resources prompt asset");
  } finally {
    if (!child.killed) child.kill();
    await rm(smokeHome, { recursive: true, force: true });
  }
}

await assertFile(specPath, "PyInstaller spec");

// This branch is private to the build-script tests.  It lets the tests run the
// exact smoke validator against a fixture without changing the production
// protocol or replacing the default bundled-exe spawn path.
const testSmokeFixture = process.env.UTHCODE_TEST_SMOKE_FIXTURE?.trim();
if (process.env.UTHCODE_TEST_SMOKE_ONLY === "1") {
  if (!testSmokeFixture) throw new Error("UTHCODE_TEST_SMOKE_ONLY requires UTHCODE_TEST_SMOKE_FIXTURE");
  await smokeBundledRuntime({ command: process.execPath, args: [testSmokeFixture] });
} else {
  // These are generated build locations owned by this script.  Removing them
  // keeps a package from accidentally reusing a previous onedir, while leaving
  // source inputs and all user/project data untouched.
  await rm(outputRoot, { recursive: true, force: true });
  await rm(workRoot, { recursive: true, force: true });

  const condaCommand = process.env.CONDA_EXE?.trim() || (process.platform === "win32" ? "conda.exe" : "conda");
  const result = spawnSync(
    condaCommand,
    [
      "run",
      "--no-capture-output",
      "-n",
      condaEnvironment,
      "python",
      "-m",
      "PyInstaller",
      "--clean",
      "--noconfirm",
      "--distpath",
      outputRoot,
      "--workpath",
      workRoot,
      specPath,
    ],
    {
      cwd: repoRoot,
      stdio: "inherit",
      shell: false,
      windowsHide: true,
    },
  );

  if (result.error) {
    console.error(`Could not run PyInstaller through Conda environment ${condaEnvironment}: ${result.error.message}`);
    process.exitCode = 1;
  } else if (result.status !== 0) {
    process.exitCode = result.status ?? 1;
  } else {
    await assertFile(runtimeExecutable, "bundled Runtime executable");
    await assertDirectory(join(runtimeRoot, "_internal"), "bundled Runtime support directory");
    console.log(`PyInstaller onedir ready: ${runtimeRoot}`);
    await smokeBundledRuntime();
  }
}
