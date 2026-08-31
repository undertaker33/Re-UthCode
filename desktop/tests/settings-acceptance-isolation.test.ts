import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { access, mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import webpack from "webpack";

const desktopRoot = fileURLToPath(new URL("../", import.meta.url));
const fixture = "render-settings-interactions-visual-fixture.tsx";

test("Prompt 2 hydrated fixture is absent from the production entry and bundle graph", async () => {
  const rendererConfig = await readFile(resolve(desktopRoot, "webpack.renderer.config.ts"), "utf8");
  const productionEntry = await readFile(resolve(desktopRoot, "src/renderer/main.tsx"), "utf8");
  assert.match(rendererConfig, /entry:\s*["']\.\/src\/renderer\/main\.tsx["']/u);
  assert.doesNotMatch(`${rendererConfig}\n${productionEntry}`, /render-settings-interactions-visual-fixture|ui-acceptance|tests\//u);

  const compiler = webpack({
    mode: "development", target: "web", entry: resolve(desktopRoot, "src/renderer/main.tsx"),
    output: { path: resolve(desktopRoot, "dist/ui-acceptance/prompt-2/production-isolation"), filename: "renderer.js" },
    module: { rules: [
      { test: /\.tsx?$/u, exclude: /node_modules/u, use: { loader: "ts-loader", options: { configFile: resolve(desktopRoot, "tsconfig.json"), transpileOnly: true } } },
      { test: /\.css$/u, type: "asset/source" },
    ] }, resolve: { extensions: [".js", ".ts", ".tsx"] }, externals: { electron: "commonjs2 electron" },
  });
  assert.ok(compiler);
  const stats = await new Promise<webpack.Stats>((resolveStats, reject) => compiler.run((error, value) => error ? reject(error) : resolveStats(value!)));
  await new Promise<void>((resolveClose, reject) => compiler.close((error) => error ? reject(error) : resolveClose()));
  assert.equal(stats.hasErrors(), false, stats.toString({ errors: true }));
  const modules = stats.toJson({ modules: true }).modules?.map((item) => item.name ?? "").join("\n") ?? "";
  assert.doesNotMatch(modules, new RegExp(fixture.replaceAll(".", "\\."), "u"));
  const bundle = await readFile(resolve(desktopRoot, "dist/ui-acceptance/prompt-2/production-isolation/renderer.js"), "utf8");
  assert.doesNotMatch(bundle, /prompt-2-settings|Prompt 2 Settings Acceptance/u);
});

test("Prompt 2 CDP injected failure closes only its child and removes its exact temporary profile", async () => {
  const reportDirectory = await mkdtemp(resolve(tmpdir(), "uthcode-prompt2-cleanup-report-"));
  const reportPath = resolve(reportDirectory, "cleanup.json");
  try {
    const child = spawn(process.execPath, [resolve(desktopRoot, "scripts/cdp-settings-acceptance.mjs"), "--fail-after-connect", "--cleanup-report", reportPath], { cwd: desktopRoot, stdio: ["ignore", "pipe", "pipe"] });
    const result = await new Promise<{ code: number | null; stderr: string }>((done, fail) => {
      let stderr = "";
      child.stderr.on("data", (chunk) => { stderr += String(chunk); });
      child.once("error", fail);
      child.once("exit", (code) => done({ code, stderr }));
    });
    assert.notEqual(result.code, 0, "injected assertion failure must remain observable");
    assert.match(result.stderr, /injected failure after CDP connect/u);
    const report = JSON.parse(await readFile(reportPath, "utf8")) as Record<string, unknown>;
    assert.deepEqual({ childExited: report.childExited, socketClosed: report.socketClosed, pendingRequests: report.pendingRequests, cleanupError: report.cleanupError }, { childExited: true, socketClosed: true, pendingRequests: 0, cleanupError: null });
    await assert.rejects(access(String(report.profile)), /ENOENT/u, "exact temporary profile must be absent after failure cleanup");
  } finally {
    await rm(reportDirectory, { recursive: true, force: true });
  }
});
