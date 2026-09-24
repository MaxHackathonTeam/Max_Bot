// Действия с внешним миром через Bridge с fallback по платформе (§4.3 FR-EV-4, §9 риски):
// shareMaxContent/HapticFeedback работают только в мобильных клиентах MAX,
// openLink — только из обработчика нажатия. Вне MAX — обычные браузерные API.

import { getWebApp } from './webApp'

const MOBILE = new Set(['ios', 'android'])

export function isMobileMax(platform: string | undefined): boolean {
  return platform !== undefined && MOBILE.has(platform)
}

/** Открыть внешнюю ссылку (карты, билеты). Вызывать только из onClick. */
export function openExternal(url: string): void {
  const webApp = getWebApp()
  if (webApp?.openLink) {
    try {
      webApp.openLink(url)
      return
    } catch {
      // Bridge отказал — открываем как обычную ссылку.
    }
  }
  window.open(url, '_blank', 'noopener,noreferrer')
}

/** Ссылка «поделиться» веб-версии MAX: https://max.ru/:share?text=… */
export function webShareUrl(text: string, link?: string | null): string {
  const full = link ? `${text}\n${link}` : text
  return `https://max.ru/:share?${new URLSearchParams({ text: full })}`
}

export type ShareResult = 'shared' | 'copied' | 'opened'

/**
 * Поделиться событием. iOS/Android — shareMaxContent({text, link});
 * web/desktop — копируем ссылку в буфер, а если нельзя — открываем max.ru/:share.
 */
export async function shareContent(text: string, link: string | null): Promise<ShareResult> {
  const webApp = getWebApp()
  if (isMobileMax(webApp?.platform) && webApp?.shareMaxContent) {
    try {
      await webApp.shareMaxContent(link ? { text, link } : { text })
      return 'shared'
    } catch {
      // Падаем в веб-вариант ниже.
    }
  }
  if (link && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(link)
      return 'copied'
    } catch {
      // Буфер обмена недоступен (нет разрешения или не https).
    }
  }
  openExternal(webShareUrl(text, link))
  return 'opened'
}

/** Лёгкая тактильная отдача на мобильных; на web/desktop ничего не делает. */
export function haptic(kind: 'success' | 'light' = 'light'): void {
  const webApp = getWebApp()
  if (!isMobileMax(webApp?.platform)) return
  const feedback = webApp?.HapticFeedback
  try {
    if (kind === 'success') feedback?.notificationOccurred?.('success')
    else feedback?.impactOccurred?.('light')
  } catch {
    // Не критично.
  }
}
