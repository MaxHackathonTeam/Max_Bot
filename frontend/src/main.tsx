import "@fontsource-variable/onest";
import "@fontsource-variable/unbounded";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app/App";
import "./app/index.css";

// Рендерим сразу: MAX Bridge грузится в фоне (SessionProvider) и сайт от него не зависит.
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
