// MAX Bridge (§9): скрипт https://st.max.ru/js/max-web-app.js создаёт window.WebApp.
// Это прогрессивное улучшение: сайт работает и без него, в обычном браузере.
// Описаны только используемые поля; всё вызывается через optional chaining — вне MAX объекта нет.

const BRIDGE_SRC = "https://st.max.ru/js/max-web-app.js";
const BRIDGE_TIMEOUT_MS = 3000;

export interface WebAppBackButton {
  show(): void;
  hide(): void;
  onClick(callback: () => void): void;
  offClick(callback: () => void): void;
}

// Сигнатуры openLink, shareMaxContent и HapticFeedback взяты из §9/§4.3 техдока;
// по документации dev.max.ru/docs/webapps/bridge НЕ сверены (страница была недоступна) —
// поэтому каждый вызов защищён проверкой наличия метода и fallback (см. actions.ts).
export interface WebAppHaptic {
  impactOccurred?(style: "light" | "medium" | "heavy" | "rigid" | "soft"): void;
  notificationOccurred?(type: "error" | "success" | "warning"): void;
}

export interface WebApp {
  initData?: string;
  initDataUnsafe?: {
    start_param?: string;
    user?: { id: number; first_name?: string };
  };
  platform?: string;
  ready?(): void;
  BackButton?: WebAppBackButton;
  openLink?(url: string): void;
  shareMaxContent?(params: { text?: string; link?: string; mid?: string; chatType?: "DIALOG" | "CHAT" }): unknown;
  HapticFeedback?: WebAppHaptic;
}

declare global {
  interface Window {
    WebApp?: WebApp;
  }
}

export function getWebApp(): WebApp | undefined {
  return window.WebApp;
}

let bridgePromise: Promise<void> | null = null;

/** Загружает Bridge в фоне: не дольше таймаута, ошибка загрузки не ломает сайт. */
export function loadBridge(): Promise<void> {
  if (window.WebApp) return Promise.resolve();
  bridgePromise ??= new Promise((resolve) => {
    const script = document.createElement("script");
    script.src = BRIDGE_SRC;
    script.async = true;
    const timer = window.setTimeout(resolve, BRIDGE_TIMEOUT_MS);
    const done = () => {
      window.clearTimeout(timer);
      resolve();
    };
    script.onload = done;
    script.onerror = done;
    document.head.appendChild(script);
  });
  return bridgePromise;
}

/** Подписанная initData, если сайт открыт внутри MAX; иначе null. */
export function maxInitData(): string | null {
  return getWebApp()?.initData || null;
}

/**
 * Фейковая initData без подписи для локальной разработки (?dev_user=<id>).
 * Бэкенд примет её только при DEV_AUTH=1 (в проде запрещено) — иначе 401.
 */
export function devInitData(userId: number, startParam?: string | null): string {
  const fake = new URLSearchParams({
    user: JSON.stringify({ id: userId, first_name: "Гость" }),
    auth_date: String(Math.floor(Date.now() / 1000)),
    hash: "dev",
  });
  if (startParam) fake.set("start_param", startParam);
  return fake.toString();
}
