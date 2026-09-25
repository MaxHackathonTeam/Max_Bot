// MAX Bridge (§9): скрипт https://st.max.ru/js/max-web-app.js создаёт window.WebApp.
// Описаны только используемые поля; всё вызывается через optional chaining — вне MAX объекта нет.

const BRIDGE_SRC = "https://st.max.ru/js/max-web-app.js";
const BRIDGE_TIMEOUT_MS = 4000;

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

/** Загружает Bridge; не блокирует старт дольше таймаута (вне MAX скрипт может быть недоступен). */
export function loadBridge(): Promise<void> {
  if (window.WebApp) return Promise.resolve();
  return new Promise((resolve) => {
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
}

export interface Launch {
  /** Строка initData для POST /auth/max. */
  initData: string;
  /** Открыто внутри MAX (есть подписанная initData). */
  inMax: boolean;
}

/**
 * Вне MAX — фейковая initData без подписи. Бэкенд примет её только при DEV_AUTH=1
 * (в проде запрещено), иначе ответит 401 и приложение попросит открыть его из бота.
 * Диплинк для проверки вне MAX: ?startapp=ev_1.
 */
export function getLaunch(search: string = window.location.search): Launch {
  const initData = getWebApp()?.initData;
  if (initData) return { initData, inMax: true };

  const params = new URLSearchParams(search);
  const fake = new URLSearchParams({
    user: JSON.stringify({
      id: Number(params.get("dev_user") ?? 100000001),
      first_name: "Гость",
    }),
    auth_date: String(Math.floor(Date.now() / 1000)),
    hash: "dev",
  });
  const startParam = params.get("startapp");
  if (startParam) fake.set("start_param", startParam);
  return { initData: fake.toString(), inMax: false };
}
