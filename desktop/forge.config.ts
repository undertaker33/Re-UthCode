import type { ForgeConfig } from "@electron-forge/shared-types";

const config: ForgeConfig = {
  packagerConfig: {
    asar: true,
  },
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
  ],
};

export default config;
