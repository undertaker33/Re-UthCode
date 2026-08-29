import type { Configuration } from "webpack";
import { fileURLToPath } from "node:url";

const typeScriptConfig = fileURLToPath(new URL("./tsconfig.json", import.meta.url));

const configuration: Configuration = {
  entry: "./src/renderer/main.tsx",
  target: "web",
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
      {
        test: /\.css$/u,
        type: "asset/source",
      },
    ],
  },
  resolve: { extensions: [".js", ".ts", ".tsx"] },
  externals: { electron: "commonjs2 electron" },
};

export default configuration;
