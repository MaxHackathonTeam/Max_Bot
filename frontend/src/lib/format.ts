// Форматирование для карточек: время — в часовом поясе населённого пункта события (§CLAUDE),
// цена, расстояние. Чистые функции, покрыты тестами.

import type { EventCard } from '../api/client'

const WEEKDAYS = ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб']

function parts(iso: string, timeZone: string): Record<string, string> {
  const formatter = new Intl.DateTimeFormat('ru-RU', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  })
  const out: Record<string, string> = {}
  for (const part of formatter.formatToParts(new Date(iso))) out[part.type] = part.value
  return out
}

/** «Пн 27.09, 18:00» в часовом поясе события. */
export function formatWhen(iso: string, timeZone: string): string {
  const p = parts(iso, timeZone)
  // День недели считаем по локальной дате пояса события, а не по UTC.
  const weekday = new Date(Date.UTC(Number(p.year), Number(p.month) - 1, Number(p.day))).getUTCDay()
  return `${WEEKDAYS[weekday]} ${p.day}.${p.month}, ${p.hour}:${p.minute}`
}

/** «18:00» в часовом поясе события — для конца сеанса. */
export function formatTime(iso: string, timeZone: string): string {
  const p = parts(iso, timeZone)
  return `${p.hour}:${p.minute}`
}

function rub(value: string): string {
  const n = Math.round(Number(value))
  return n.toLocaleString('ru-RU').replace(/\s/g, ' ')
}

export function formatPrice(card: Pick<EventCard, 'price_type' | 'price_min' | 'price_max'>): string {
  if (card.price_type === 'free') return 'Бесплатно'
  if (card.price_type === 'donation') return 'Донат'
  if (card.price_min === null) return 'Цена не указана'
  if (card.price_max !== null && Number(card.price_max) !== Number(card.price_min)) {
    return `от ${rub(card.price_min)} ₽`
  }
  return `${rub(card.price_min)} ₽`
}

export function formatDistance(km: number | null): string | null {
  if (km === null) return null
  if (km < 1) return '<1 км'
  return `${km < 10 ? km.toFixed(1).replace('.', ',') : Math.round(km)} км`
}

/** «обновлено 25.09.2026» — дата в поясе пользователя (служебная информация). */
export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('ru-RU')
}
