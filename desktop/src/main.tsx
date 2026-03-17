import "./index.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App.tsx";

// Global error handler — logs uncaught errors.
// NOTE: We intentionally do NOT set innerHTML on the React root here.
// Doing so destroys React's DOM tree and causes "insertBefore" crashes
// when React tries to reconcile against nodes that no longer exist.
window.addEventListener("error", (event) => {
  console.error("[GLOBAL ERROR]", event.error);
});

window.addEventListener("unhandledrejection", (event) => {
  console.error("[UNHANDLED REJECTION]", event.reason);
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
