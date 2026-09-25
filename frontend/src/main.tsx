import "@maxhub/max-ui/dist/styles.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app/App";
import "./app/index.css";
import { loadBridge } from "./bridge/webApp";

// Bridge нужен до входа: из него берётся initData.
void loadBridge().then(() => {
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
});
