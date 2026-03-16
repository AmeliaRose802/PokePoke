import "./index.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App.tsx";

// Global error handler — ensures uncaught errors are visible on the page
// instead of silently producing a black screen in pywebview.
window.addEventListener("error", (event) => {
  console.error("[GLOBAL ERROR]", event.error);
  const root = document.getElementById("root");
  if (root && root.children.length === 0) {
    root.innerHTML = `<div style="color:#ff6b6b;padding:2rem;font-family:monospace;">
      <h2>Uncaught Error</h2><pre>${event.error?.stack ?? event.message}</pre>
    </div>`;
  }
});

window.addEventListener("unhandledrejection", (event) => {
  console.error("[UNHANDLED REJECTION]", event.reason);
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
