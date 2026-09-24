// Фильтры ленты живут в query-строке: «Назад» из карточки возвращает ту же выдачу,
// а диплинк feed_<preset> (§3.1) превращается в обычные фильтры.

import type { DatePreset, EventQuery, Radius, Tier } from '../api/client'

export interface FeedFilters {
  tier: Tier
  date: DatePreset | null
  free: boolean
  pushkin: boolean
  categories: string[]
  priceMax: number | null
  format: 'all' | 'offline' | 'online'
  sort: 'date' | 'distance' | null
  radius: Radius | null
  q: string
}

const DATES = new Set<string>(['today', 'tomorrow', 'weekend'])
const RADII = new Set<number>([5, 15, 30, 50])

export function parseFeed(params: URLSearchParams): FeedFilters {
  const date = params.get('date')
  const format = params.get('format')
  const sort = params.get('sort')
  const radius = Number(params.get('radius'))
  const priceMax = Number(params.get('price_max'))
  return {
    tier: params.get('tier') === 'community' ? 'community' : 'official',
    date: date && DATES.has(date) ? (date as DatePreset) : null,
    free: params.get('free') === '1',
    pushkin: params.get('pushkin') === '1',
    categories: params.getAll('cat').filter((c) => /^[a-z_]{1,32}$/.test(c)),
    priceMax: params.has('price_max') && Number.isInteger(priceMax) && priceMax >= 0 ? priceMax : null,
    format: format === 'offline' || format === 'online' ? format : 'all',
    sort: sort === 'date' || sort === 'distance' ? sort : null,
    radius: RADII.has(radius) ? (radius as Radius) : null,
    q: (params.get('q') ?? '').slice(0, 200),
  }
}

export function feedToParams(f: FeedFilters): URLSearchParams {
  const params = new URLSearchParams()
  if (f.tier !== 'official') params.set('tier', f.tier)
  if (f.date) params.set('date', f.date)
  if (f.free) params.set('free', '1')
  if (f.pushkin) params.set('pushkin', '1')
  f.categories.forEach((c) => params.append('cat', c))
  if (f.priceMax !== null) params.set('price_max', String(f.priceMax))
  if (f.format !== 'all') params.set('format', f.format)
  if (f.sort) params.set('sort', f.sort)
  if (f.radius) params.set('radius', String(f.radius))
  if (f.q) params.set('q', f.q)
  return params
}

/** ?feed=today|weekend|pushkin из диплинка → фильтры; null, если параметра нет. */
export function deeplinkFeed(params: URLSearchParams): URLSearchParams | null {
  const feed = params.get('feed')
  if (feed === null) return null
  const next = new URLSearchParams(params)
  next.delete('feed')
  if (feed === 'today' || feed === 'weekend') next.set('date', feed)
  if (feed === 'pushkin') next.set('pushkin', '1')
  return next
}

export const FEED_PAGE = 20

export function toEventQuery(f: FeedFilters, localityId: number, radius: Radius): EventQuery {
  return {
    locality_id: localityId,
    radius_km: f.radius ?? radius,
    tier: f.tier,
    date: f.date ?? undefined,
    free: f.free || undefined,
    pushkin: f.pushkin || undefined,
    category: f.categories.length ? f.categories : undefined,
    price_max: f.priceMax ?? undefined,
    format: f.format === 'all' ? undefined : f.format,
    q: f.q || undefined,
    sort: f.sort ?? (f.q ? 'relevance' : 'date'),
    limit: FEED_PAGE,
  }
}

/** Сколько фильтров из «шторки» включено — для счётчика на кнопке. */
export function sheetFilterCount(f: FeedFilters): number {
  return (
    f.categories.length +
    (f.priceMax !== null ? 1 : 0) +
    (f.format !== 'all' ? 1 : 0) +
    (f.sort ? 1 : 0)
  )
}
