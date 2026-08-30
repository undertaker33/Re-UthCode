import type { ForgeConfig } from "@electron-forge/shared-types";
import { FusesPlugin } from "@electron-forge/plugin-fuses";
import { FuseV1Options, FuseVersion } from "@electron/fuses";
import { createRequire } from "node:module";
import { resolve } from "node:path";

const require = createRequire(import.meta.url);
const electronChecksums = require("electron/checksums.json") as Record<string, string>;
const runtimeResourcePath = resolve(__dirname, ".runtime", "uthcode-runtime");

const config: ForgeConfig = {
  packagerConfig: {
    asar: true,
    extraResource: runtimeResourcePath,
    download: {
      checksums: electronChecksums,
    },
  },
  makers: [
    {
      name: "@electron-forge/maker-squirrel",
      config: {
        name: "UthCode",
        setupExe: "UthCode Setup.exe",
      },
    },
  ],
  plugins: [
    {
      name: "@electron-forge/plugin-webpack",
      config: {
        mainConfig: "./webpack.main.config.ts",
        renderer: {
          config: "./webpack.renderer.config.ts",
          nodeIntegration: false,
          entryPoints: [
            {
              name: "main_window",
              html: "./src/renderer/index.html",
              js: "./src/renderer/main.tsx",
              preload: {
                js: "./src/preload.ts",
              },
            },
          ],
        },
        devContentSecurityPolicy:
          "default-src 'self'; script-src 'self' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-src 'none'",
      },
    },
    new FusesPlugin({
      version: FuseVersion.V1,
      [FuseV1Options.RunAsNode]: false,
      [FuseV1Options.EnableNodeOptionsEnvironmentVariable]: false,
      [FuseV1Options.EnableNodeCliInspectArguments]: false,
      [FuseV1Options.EnableEmbeddedAsarIntegrityValidation]: true,
      [FuseV1Options.OnlyLoadAppFromAsar]: true,
    }),
  ],
};

export default config;
