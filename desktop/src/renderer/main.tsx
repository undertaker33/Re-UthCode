import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
// Webpack's asset/source rule turns the stylesheet into a string. Keeping the
// injection here leaves App importable by Node-based renderer tests while the
// packaged renderer receives the same CSS without Node access.
// @ts-expect-error CSS is provided by webpack's asset/source rule.
import stylesheet from "./app.css";

const root = document.getElementById("root");
if (!root) throw new Error("Desktop root element is missing");
const style = document.createElement("style");
style.setAttribute("data-uthcode-theme", "renderer");
style.textContent = stylesheet;
document.head.append(style);
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
