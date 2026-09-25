import { EventEmitter } from "node:events";
import { createRequire } from "node:module";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import assert from "node:assert/strict";
import webpack, { type Configuration } from "webpack";

import { DesktopPreferencesStore } from "../src/desktop-preferences";
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

  constructor(private readonly userDataPath = tmpdir()) {
    super();
  }

  whenReady(): Promise<void> {
    this.readyCalls += 1;
    return Promise.resolve();
  }

  getPath(_name: string): string {
    return this.userDataPath;
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
  const app = new FakeApp(outputPath);
  const shownMenus: Array<{ template: unknown; options: unknown }> = [];
  const ipcMain = {
    handle: (_channel: string, _handler: unknown) => undefined,
    removeHandler: (_channel: string) => undefined,
  };
  const electron = {
    app,
    BrowserWindow: FakeBrowserWindow,
    dialog: { showOpenDialog: async () => ({ canceled: true, filePaths: [] }) },
    ipcMain,
    Menu: {
      setApplicationMenu: (_menu: unknown) => undefined,
      buildFromTemplate: (template: unknown) => ({ popup: (options: unknown) => shownMenus.push({ template, options }) }),
    },
    nativeTheme: { themeSource: "system", shouldUseDarkColors: true },
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
    const deadline = Date.now() + 2_000;
    while (FakeBrowserWindow.instances.length === 0 && Date.now() < deadline) {
      await new Promise<void>((resolve) => setTimeout(resolve, 10));
    }

    assert.equal(app.readyCalls, 1);
    assert.equal(FakeBrowserWindow.instances.length, 1);
    const window = FakeBrowserWindow.instances[0];
    const webPreferences = window.options.webPreferences as Record<string, unknown>;
    assert.equal(webPreferences.nodeIntegration, false);
    assert.equal(webPreferences.contextIsolation, true);
    assert.equal(webPreferences.sandbox, true);
    assert.equal(window.options.autoHideMenuBar, true);
    assert.equal(window.options.backgroundColor, "#1d1d1f");
    assert.equal(electron.nativeTheme.themeSource, "system");
    assert.equal(window.loadedURL, "");
    let prevented = false;
    window.webContents.emit("context-menu", { preventDefault: () => { prevented = true; } }, { formControlType: "input-text", x: 12, y: 18 });
    assert.equal(prevented, false);
    assert.equal(shownMenus.length, 0);
    window.webContents.emit("context-menu", { preventDefault: () => { prevented = true; } }, { formControlType: "text-area", x: 12, y: 18 });
    assert.equal(prevented, true);
    const menuDeadline = Date.now() + 2_000;
    while (shownMenus.length < 1 && Date.now() < menuDeadline) await new Promise<void>((resolve) => setTimeout(resolve, 10));
    assert.equal(shownMenus.length, 1);
    assert.deepEqual((shownMenus[0]?.template as Array<{ role: string }>).map((item) => item.role), ["cut", "copy", "paste", "selectAll"]);
    assert.deepEqual((shownMenus[0]?.template as Array<{ label: string }>).map((item) => item.label), ["剪切", "复制", "粘贴", "全选"]);
    assert.deepEqual(shownMenus[0]?.options, { window, x: 12, y: 18 });

    await new DesktopPreferencesStore(join(outputPath, "desktop-preferences.json")).write("language", "en");
    prevented = false;
    window.webContents.emit("context-menu", { preventDefault: () => { prevented = true; } }, { formControlType: "text-area", x: 20, y: 24 });
    assert.equal(prevented, true);
    while (shownMenus.length < 2 && Date.now() < menuDeadline + 2_000) await new Promise<void>((resolve) => setTimeout(resolve, 10));
    assert.equal(shownMenus.length, 2);
    assert.deepEqual((shownMenus[1]?.template as Array<{ label: string }>).map((item) => item.label), ["Cut", "Copy", "Paste", "Select All"]);
  } finally {
    moduleLoader._load = originalLoad;
    if (previousPython === undefined) delete process.env.UTHCODE_PYTHON;
    else process.env.UTHCODE_PYTHON = previousPython;
    await rm(outputPath, { recursive: true, force: true });
  }
});
