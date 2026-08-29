import type { Configuration } from "webpack";
import webpack from "webpack";
import { fileURLToPath } from "node:url";

const { DefinePlugin } = webpack;

const typeScriptConfig = fileURLToPath(new URL("./tsconfig.json", import.meta.url));

const configuration: Configuration = {
  entry: "./src/main.ts",
  target: "electron-main",
  devtool: "source-map",
  module: {
    rules: [
      {
        test: /\.tsx?$/u,
        exclude: /node_modules/u,
        use: {
          loader: "ts-loader",
          options: { configFile: typeScriptConfig },
        },
      },
    ],
  },
  resolve: { extensions: [".js", ".ts", ".tsx"] },
  externals: { electron: "commonjs2 electron" },
  node: { __dirname: false, __filename: false },
  plugins: [
    // The main bundle is the Electron process entry point.  An explicit
    // compile-time gate is reliable for Forge/Webpack output while keeping
    // helper imports inert in Node unit tests.
    new DefinePlugin({ UTHCODE_DESKTOP_MAIN_BUNDLE: "true" }),
  ],
};

export default configuration;
