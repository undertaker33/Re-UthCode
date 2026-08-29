import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

function BootShell() {
  return (
    <main aria-label="UthCode Desktop">
      <h1>UthCode</h1>
      <p>Desktop shell loaded.</p>
    </main>
  );
}

const root = document.getElementById("root");
if (!root) throw new Error("Desktop root element is missing");
createRoot(root).render(
  <StrictMode>
    <BootShell />
  </StrictMode>,
);
