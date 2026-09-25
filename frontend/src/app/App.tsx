import { MaxUI, type PlatformType } from "@maxhub/max-ui";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useNavigate,
} from "react-router-dom";
import { useBackButton } from "../bridge/useBackButton";
import { getWebApp } from "../bridge/webApp";
import { EventPage } from "../pages/EventPage";
import { HomePage } from "../pages/HomePage";
import { LegalPage } from "../pages/LegalPage";
import { SavedPage } from "../pages/SavedPage";
import { SettingsPage } from "../pages/SettingsPage";
import { DraftPage } from "../pages/DraftPage";
import { InvitePage } from "../pages/InvitePage";
import { OrgPage } from "../pages/OrgPage";
import { AuthGate } from "./auth";
import { startParamToPath } from "./deeplink";
import { useSession } from "./session";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

function platform(): PlatformType {
  return getWebApp()?.platform === "ios" ? "ios" : "android";
}

function colorScheme(): "light" | "dark" {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

/** Один раз после входа переходит по диплинку start_param (§3.1). */
function DeeplinkRedirect() {
  const { startParam } = useSession();
  const navigate = useNavigate();
  const done = useRef(false);

  useEffect(() => {
    if (done.current) return;
    done.current = true;
    const path = startParamToPath(startParam);
    if (path) navigate(path, { replace: true });
  }, [startParam, navigate]);
  return null;
}

/** Системная «Назад» — на всех экранах, включая /legal вне AuthGate. */
function BackButton() {
  useBackButton();
  return null;
}

function AppRoutes() {
  return (
    <>
      <DeeplinkRedirect />
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/event/:id" element={<EventPage />} />
        <Route path="/saved" element={<SavedPage />} />
        <Route path="/org/:id" element={<OrgPage />} />
        <Route path="/draft/:id" element={<DraftPage />} />
        <Route path="/invite/:token" element={<InvitePage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  );
}

export function App() {
  useEffect(() => {
    getWebApp()?.ready?.();
  }, []);

  return (
    <MaxUI platform={platform()} colorScheme={colorScheme()}>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <BackButton />
          <Routes>
            {/* Документы доступны без входа: ссылки на них есть в сообщении бота. */}
            <Route path="/legal/:doc" element={<LegalPage />} />
            <Route
              path="*"
              element={
                <AuthGate>
                  <AppRoutes />
                </AuthGate>
              }
            />
          </Routes>
        </BrowserRouter>
      </QueryClientProvider>
    </MaxUI>
  );
}
