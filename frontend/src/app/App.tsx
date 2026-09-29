import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { useBackButton } from "../bridge/useBackButton";
import { LoginProvider } from "../components/LoginDialog";
import { DraftPage } from "../pages/DraftPage";
import { EventPage } from "../pages/EventPage";
import { HomePage } from "../pages/HomePage";
import { ModerationEventPage } from "../pages/ModerationEventPage";
import { ModerationPage } from "../pages/ModerationPage";
import { MyEventsPage } from "../pages/MyEventsPage";
import { NewEventPage } from "../pages/NewEventPage";
import { InvitePage } from "../pages/InvitePage";
import { LegalPage } from "../pages/LegalPage";
import { OrgPage } from "../pages/OrgPage";
import { OrgsPage } from "../pages/OrgsPage";
import { SavedPage } from "../pages/SavedPage";
import { SettingsPage } from "../pages/SettingsPage";
import { ToastProvider } from "../ui/Toast";
import { AppShell } from "./AppShell";
import { startParamToPath } from "./deeplink";
import { SessionProvider } from "./SessionProvider";
import { useSession } from "./session";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

/**
 * Диплинк start_param (§3.1) → экран. В MAX параметр приходит после входа, в браузере —
 * из ?startapp=. Переходим один раз и только с главной, чтобы не сбить уже открытый экран.
 */
function DeeplinkRedirect() {
  const { startParam } = useSession();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const handled = useRef<string | null>(null);

  useEffect(() => {
    if (!startParam || handled.current === startParam) return;
    handled.current = startParam;
    const path = startParamToPath(startParam);
    if (path && pathname === "/") navigate(path, { replace: true });
  }, [startParam, pathname, navigate]);
  return null;
}

/** Системная «Назад» MAX; вне MAX ничего не делает. */
function BackButton() {
  useBackButton();
  return null;
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter>
          <SessionProvider>
            <LoginProvider>
            <BackButton />
            <DeeplinkRedirect />
            <AppShell>
              <Routes>
                <Route path="/" element={<HomePage />} />
                <Route path="/event/:id" element={<EventPage />} />
                <Route path="/saved" element={<SavedPage />} />
                <Route path="/org/:id" element={<OrgPage />} />
                <Route path="/orgs" element={<OrgsPage />} />
                <Route path="/draft/:id" element={<DraftPage />} />
                <Route path="/new" element={<NewEventPage />} />
                <Route path="/my" element={<MyEventsPage />} />
                <Route path="/moderation" element={<ModerationPage />} />
                <Route path="/moderation/:id" element={<ModerationEventPage />} />
                <Route path="/invite/:token" element={<InvitePage />} />
                <Route path="/settings" element={<SettingsPage />} />
                <Route path="/legal/:doc" element={<LegalPage />} />
                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </AppShell>
            </LoginProvider>
          </SessionProvider>
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  );
}
