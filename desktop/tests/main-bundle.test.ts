import { EventEmitter } from "node:events";
import { createRequire } from "node:module";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import assert from "node:assert/strict";
import webpack, { type Configuration } from "webpack";

import mainConfiguration from "../webpack.main.config";

class FakeWebContents extends EventEmitter {
  readonly mainFrame = { url: "" };
  readonly sent: unknown[] = [];

  send(_channel: string, payload: unknown): void {
    this.sent.push(payload);
  }

  setWindowOpenHandler(_handler: unknown): void {
    // The test only needs to prove that the bundled Main calls the policy API.
  }
}

class FakeBrowserWindow extends EventEmitter {
  static readonly instances: FakeBrowserWindow[] = [];

  readonly webContents = new FakeWebContents();
  readonly options: Record<string, unknown>;
  loadedURL: string | undefined;
  private destroyed = false;

  constructor(options: Record<string, unknown>) {
    super();
    this.options = options;
    FakeBrowserWindow.instances.push(this);
  }

  isDestroyed(): boolean {
    return this.destroyed;
  }

  loadURL(url: string): Promise<void> {
    this.loadedURL = url;
    this.webContents.mainFrame.url = url;
    return Promise.resolve();
  }

  close(): void {
    this.destroyed = true;
    this.emit("closed");
  }
}

class FakeApp extends EventEmitter {
  readonly isPackaged = false;
  readyCalls = 0;
  quitCalls = 0;

  whenReady(): Promise<void> {
    this.readyCalls += 1;
    return Promise.resolve();
  }

  getPath(_name: string): string {
    return tmpdir();
  }

  quit(): void {
    this.quitCalls += 1;
  }
}

function compileMainBundle(outputPath: string): Promise<string> {
  const configuration: Configuration = {
    ...mainConfiguration,
    mode: "production",
    output: { path: outputPath, filename: "main.js" },
  };
  return new Promise((resolve, reject) => {
    webpack(configuration, (error, stats) => {
      if (error) {
        reject(error);
        return;
      }
      if (!stats || stats.hasErrors()) {
        reject(new Error(stats?.toString({ errors: true }) ?? "Webpack Main compilation failed"));
        return;
      }
      resolve(join(outputPath, "main.js"));
    });
  });
}

test("compiled Webpack Main entry bootstraps and creates the secure window", async () => {
  const outputPath = await mkdtemp(join(tmpdir(), "uthcode-main-bundle-"));
  const app = new FakeApp();
  const ipcMain = {
    handle: (_channel: string, _handler: unknown) => undefined,
    removeHandler: (_channel: string) => undefined,
  };
  const electron = {
    app,
    BrowserWindow: FakeBrowserWindow,
    dialog: { showOpenDialog: async () => ({ canceled: true, filePaths: [] }) },
    ipcMain,
    shell: { openPath: async () => "" },
  };
  const previousPython = process.env.UTHCODE_PYTHON;
  type ModuleLoad = (request: string, parent: unknown, isMain: boolean) => unknown;
  const moduleLoader = createRequire(import.meta.url)("node:module") as {
    _load: ModuleLoad;
  };
  const originalLoad = moduleLoader._load;
  process.env.UTHCODE_PYTHON = "python.exe";
  FakeBrowserWindow.instances.length = 0;
  try {
    const bundlePath = await compileMainBundle(outputPath);
    moduleLoader._load = function load(request: string, parent: unknown, isMain: boolean) {
      if (request === "electron") return electron;
      return originalLoad(request, parent, isMain);
    };
    createRequire(bundlePath)(bundlePath);
    await new Promise<void>((resolve) => setImmediate(resolve));

    assert.equal(app.readyCalls, 1);
    assert.equal(FakeBrowserWindow.instances.length, 1);
    const window = FakeBrowserWindow.instances[0];
    const webPreferences = window.options.webPreferences as Record<string, unknown>;
    assert.equal(webPreferences.nodeIntegration, false);
    assert.equal(webPreferences.contextIsolation, true);
    assert.equal(webPreferences.sandbox, true);
    assert.equal(window.loadedURL, "");
  } finally {
    moduleLoader._load = originalLoad;
    if (previousPython === undefined) delete process.env.UTHCODE_PYTHON;
    else process.env.UTHCODE_PYTHON = previousPython;
    await rm(outputPath, { recursive: true, force: true });
  }
});
