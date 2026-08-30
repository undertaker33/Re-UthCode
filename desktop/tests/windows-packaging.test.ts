import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { test } from "node:test";
import assert from "node:assert/strict";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import forgeConfig from "../forge.config";

const desktopRoot = new URL("../", import.meta.url);
const repoRoot = new URL("../../", import.meta.url);
const execFileAsync = promisify(execFile);
const requirePackage = createRequire(import.meta.url);

type ExecFailure = {
  code?: number | string;
  stdout?: string;
  stderr?: string;
};

async function read(relative: string, root = desktopRoot): Promise<string> {
  return readFile(new URL(relative, root), "utf8");
}

test("Forge packaging uses the installed Electron checksums without remote checksum lookup", () => {
  const packageChecksums = requirePackage("electron/checksums.json") as Record<string, string>;
  const electronPackage = requirePackage("electron/package.json") as { version: string };
  const configuredChecksums = forgeConfig.packagerConfig?.download?.checksums;
  const artifact = `electron-v${electronPackage.version}-win32-x64.zip`;

  assert.ok(configuredChecksums);
  assert.match(packageChecksums[artifact] ?? "", /^[0-9a-f]{64}$/u);
  assert.equal(configuredChecksums[artifact], packageChecksums[artifact]);
});

test("T08 checked-in build contract defines the bundled Runtime and Installer", async () => {
  const spec = await read("packaging/uthcode-runtime.spec");
  const buildScript = await read("scripts/build-python-runtime.mjs");
  const forge = await read("forge.config.ts");
  const packageJson = await read("package.json");
  const main = await read("src/main.ts");
  const pyproject = await read("pyproject.toml", repoRoot);

  assert.match(spec, /Analysis\(/u);
  assert.match(spec, /coding_agent\.md/u);
  assert.match(spec, /console\s*=\s*True/u);
  assert.match(spec, /COLLECT\(/u);
  assert.doesNotMatch(spec, /--noconsole|--windowed|collect-all\s+everything/u);
  assert.match(buildScript, /PyInstaller/u);
  assert.match(buildScript, /re-uthcode/u);
  assert.match(forge, /extraResource/u);
  assert.match(forge, /maker-squirrel/u);
  assert.match(forge, /FusesPlugin/u);
  assert.match(main, /electron-squirrel-startup/u);
  assert.match(packageJson, /build:runtime/u);
  assert.match(pyproject, /pyinstaller/u);
});

test("T08 build command blocks on a real bundled Runtime smoke", { timeout: 120_000 }, async () => {
  const result = await execFileAsync(process.execPath, ["scripts/build-python-runtime.mjs"], {
    cwd: fileURLToPath(desktopRoot),
    maxBuffer: 8 * 1024 * 1024,
  });
  assert.match(
    `${result.stdout}\n${result.stderr}`,
    /Bundled Runtime smoke passed: ready\/status\/shutdown JSONL and importlib\.resources prompt asset/u,
  );
});

test("T08 smoke failure returns nonzero before the Forge sentinel", { timeout: 60_000 }, async () => {
  const fixtureRoot = await mkdtemp(join(fileURLToPath(desktopRoot), ".tmp-runtime-smoke-fixture-"));
  const fixturePath = join(fixtureRoot, "malformed-runtime.mjs");
  const sentinelPath = join(fixtureRoot, "forge-sentinel-ran");
  const sentinelScriptPath = join(fixtureRoot, "forge-sentinel.mjs");
  await writeFile(
    fixturePath,
    [
      "process.stdin.resume();",
      "process.stdout.write('{\"type\":\"runtime_state\",\"state\":\"ready\"}\\nnot-json\\n');",
      "process.stdin.on(\"end\", () => process.exit(0));",
      "",
    ].join("\n"),
    "utf8",
  );
  await writeFile(
    sentinelScriptPath,
    `import { writeFileSync } from "node:fs";\nwriteFileSync(${JSON.stringify(sentinelPath)}, "ran");\n`,
    "utf8",
  );
  const testEnv = {
    ...process.env,
    NODE_ENV: "test",
    UTHCODE_TEST_SMOKE_ONLY: "1",
    UTHCODE_TEST_SMOKE_FIXTURE: fixturePath,
  };

  try {
    let directFailure: ExecFailure | undefined;
    try {
      await execFileAsync(process.execPath, ["scripts/build-python-runtime.mjs"], {
        cwd: fileURLToPath(desktopRoot),
        env: testEnv,
        maxBuffer: 8 * 1024 * 1024,
      });
    } catch (error) {
      directFailure = error as ExecFailure;
    }
    assert.ok(directFailure, "the malformed Runtime fixture must fail the smoke command");
    assert.notEqual(directFailure.code, 0);
    assert.match(`${directFailure.stdout ?? ""}\n${directFailure.stderr ?? ""}`, /invalid JSONL/u);

    let gateFailure: ExecFailure | undefined;
    try {
      await execFileAsync(
        process.env.ComSpec ?? "cmd.exe",
        ["/d", "/s", "/c", `npm run build:runtime && node "${sentinelScriptPath}"`],
        {
          cwd: fileURLToPath(desktopRoot),
          env: testEnv,
          maxBuffer: 8 * 1024 * 1024,
        },
      );
    } catch (error) {
      gateFailure = error as ExecFailure;
    }
    assert.ok(gateFailure, "the package-prefix chain must stop at the failed smoke");
    assert.notEqual(gateFailure.code, 0);
    assert.equal(existsSync(sentinelPath), false, "the Forge replacement must not execute after smoke failure");
  } finally {
    await rm(fixtureRoot, { recursive: true, force: true });
  }
});
