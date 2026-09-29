// Действия с внешним миром через Bridge с fallback по платформе (§4.3 FR-EV-4, §9 риски):
// shareMaxContent/HapticFeedback работают только в мобильных клиентах MAX,
// openLink — только из обработчика нажатия. Вне MAX — обычные браузерные API
// (window.open, navigator.share, буфер обмена).

import { getWebApp } from "./webApp";

const MOBILE = new Set(["ios", "android"]);

export function isMobileMax(platform: string | undefined): boolean {
  return platform !== undefined && MOBILE.has(platform);
}

/**
 * Сайт открыт внутри MAX. Скрипт Bridge грузится и в обычном браузере, и window.WebApp там
 * тоже есть, но без initData: openLink тогда молча ничего не делает.
 */
export function insideMax(): boolean {
  return Boolean(getWebApp()?.initData);
}

/** Открыть внешнюю ссылку (карты, билеты). Вызывать только из onClick. */
export function openExternal(url: string): void {
  const webApp = getWebApp();
  if (webApp?.initData && webApp.openLink) {
    try {
      webApp.openLink(url);
      return;
    } catch {
      // Bridge отказал — открываем как обычную ссылку.
    }
  }
  window.open(url, "_blank", "noopener,noreferrer");
}

/** Ссылка «поделиться» веб-версии MAX: https://max.ru/:share?text=… */
export function webShareUrl(text: string, link?: string | null): string {
  const full = link ? `${text}\n${link}` : text;
  return `https://max.ru/:share?${new URLSearchParams({ text: full })}`;
}

export type ShareResult = "shared" | "copied" | "opened" | "cancelled" | "failed";

export interface ShareTarget {
  text: string;
  /** Диплинк в мини-приложение (https://max.ru/<bot>?startapp=…) — для MAX. */
  maxLink: string | null;
  /** Обычная ссылка на сайт — для браузера. */
  webLink: string;
}

async function copy(text: string): Promise<boolean> {
  if (!navigator.clipboard?.writeText) return false;
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Нет разрешения или не https.
    return false;
  }
}

/**
 * Поделиться событием.
 * MAX на телефоне — shareMaxContent({text, link}); MAX web/desktop — ссылка в буфер,
 * иначе max.ru/:share. Браузер — системное «Поделиться», иначе ссылка в буфер;
 * "failed" — показать ссылку пользователю.
 */
export async function shareContent({ text, maxLink, webLink }: ShareTarget): Promise<ShareResult> {
  const webApp = getWebApp();
  if (webApp?.initData) {
    if (isMobileMax(webApp.platform) && webApp.shareMaxContent) {
      try {
        await webApp.shareMaxContent(maxLink ? { text, link: maxLink } : { text });
        return "shared";
      } catch {
        // Падаем в веб-вариант ниже.
      }
    }
    if (maxLink && (await copy(maxLink))) return "copied";
    openExternal(webShareUrl(text, maxLink));
    return "opened";
  }

  if (typeof navigator.share === "function") {
    try {
      await navigator.share({ title: text, url: webLink });
      return "shared";
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") return "cancelled";
    }
  }
  return (await copy(webLink)) ? "copied" : "failed";
}

/** Лёгкая тактильная отдача на мобильных; на web/desktop ничего не делает. */
export function haptic(kind: "success" | "light" = "light"): void {
  const webApp = getWebApp();
  if (!isMobileMax(webApp?.platform)) return;
  const feedback = webApp?.HapticFeedback;
  try {
    if (kind === "success") feedback?.notificationOccurred?.("success");
    else feedback?.impactOccurred?.("light");
  } catch {
    // Не критично.
  }
}
