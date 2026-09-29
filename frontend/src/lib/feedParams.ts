// Фильтры ленты живут в query-строке: «Назад» из карточки возвращает ту же выдачу,
// а диплинк feed_<preset> (§3.1) превращается в обычные фильтры.

import type { DatePreset, EventQuery, Radius, Tier } from "../api/client";

/** «week» — 7 дней с сегодняшнего, «range» — свои даты from–to. */
export type FeedDate = DatePreset | "week" | "range";

export interface FeedFilters {
  tier: Tier;
  date: FeedDate | null;
  from: string | null;
  to: string | null;
  free: boolean;
  kids: boolean;
  pushkin: boolean;
  categories: string[];
  priceMax: number | null;
  format: "all" | "offline" | "online";
  sort: "date" | "distance" | null;
  radius: Radius | null;
  q: string;
}

const DATES = new Set<string>(["today", "tomorrow", "weekend", "week", "range"]);
const RADII = new Set<number>([5, 15, 30, 50]);
const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;
/** «Для детей»: события с возрастом не выше 6+ (и без метки). */
export const KIDS_AGE = 6;

function day(raw: string | null): string | null {
  return raw && ISO_DAY.test(raw) && !Number.isNaN(Date.parse(raw)) ? raw : null;
}

/** Сегодняшняя дата в поясе пункта, ГГГГ-ММ-ДД. */
export function localDay(now: Date, timeZone: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).format(
    now,
  );
}

export function addDays(isoDay: string, days: number): string {
  const d = new Date(`${isoDay}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

export function parseFeed(params: URLSearchParams): FeedFilters {
  const date = params.get("date");
  const format = params.get("format");
  const sort = params.get("sort");
  const radius = Number(params.get("radius"));
  const priceMax = Number(params.get("price_max"));
  let from = day(params.get("from"));
  let to = day(params.get("to"));
  if (from && to && from > to) [from, to] = [to, from];
  let parsedDate = date && DATES.has(date) ? (date as FeedDate) : null;
  if (parsedDate === "range" && !from && !to) parsedDate = null;
  if (parsedDate !== "range") from = to = null;
  return {
    tier: params.get("tier") === "community" ? "community" : "official",
    date: parsedDate,
    from,
    to,
    free: params.get("free") === "1",
    kids: params.get("kids") === "1",
    pushkin: params.get("pushkin") === "1",
    categories: params.getAll("cat").filter((c) => /^[a-z_]{1,32}$/.test(c)),
    priceMax:
      params.has("price_max") && Number.isInteger(priceMax) && priceMax >= 0
        ? priceMax
        : null,
    format: format === "offline" || format === "online" ? format : "all",
    sort: sort === "date" || sort === "distance" ? sort : null,
    radius: RADII.has(radius) ? (radius as Radius) : null,
    q: (params.get("q") ?? "").slice(0, 200),
  };
}

export function feedToParams(f: FeedFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (f.tier !== "official") params.set("tier", f.tier);
  if (f.date) params.set("date", f.date);
  if (f.date === "range" && f.from) params.set("from", f.from);
  if (f.date === "range" && f.to) params.set("to", f.to);
  if (f.free) params.set("free", "1");
  if (f.kids) params.set("kids", "1");
  if (f.pushkin) params.set("pushkin", "1");
  f.categories.forEach((c) => params.append("cat", c));
  if (f.priceMax !== null) params.set("price_max", String(f.priceMax));
  if (f.format !== "all") params.set("format", f.format);
  if (f.sort) params.set("sort", f.sort);
  if (f.radius) params.set("radius", String(f.radius));
  if (f.q) params.set("q", f.q);
  return params;
}

/** ?feed=today|weekend|pushkin|kids|free из диплинка → фильтры; null, если параметра нет. */
export function deeplinkFeed(params: URLSearchParams): URLSearchParams | null {
  const feed = params.get("feed");
  if (feed === null) return null;
  const next = new URLSearchParams(params);
  next.delete("feed");
  if (feed === "today" || feed === "weekend") next.set("date", feed);
  if (feed === "pushkin") next.set("pushkin", "1");
  if (feed === "kids") next.set("kids", "1");
  if (feed === "free") next.set("free", "1");
  return next;
}

export const FEED_PAGE = 20;

/** Даты для API: пресеты бэкенда как есть, неделя и свой период — через date_from/date_to. */
function dateQuery(f: FeedFilters, timeZone: string, now: Date): Pick<EventQuery, "date" | "date_from" | "date_to"> {
  if (f.date === "week") {
    const today = localDay(now, timeZone);
    return { date_from: today, date_to: addDays(today, 6) };
  }
  if (f.date === "range") return { date_from: f.from ?? undefined, date_to: f.to ?? undefined };
  return { date: f.date ?? undefined };
}

export function toEventQuery(
  f: FeedFilters,
  localityId: number,
  radius: Radius,
  timeZone = "Europe/Moscow",
  now = new Date(),
): EventQuery {
  return {
    locality_id: localityId,
    radius_km: f.radius ?? radius,
    tier: f.tier,
    ...dateQuery(f, timeZone, now),
    free: f.free || undefined,
    age: f.kids ? KIDS_AGE : undefined,
    pushkin: f.pushkin || undefined,
    category: f.categories.length ? f.categories : undefined,
    price_max: f.priceMax ?? undefined,
    format: f.format === "all" ? undefined : f.format,
    q: f.q || undefined,
    sort: f.sort ?? (f.q ? "relevance" : "date"),
    limit: FEED_PAGE,
  };
}

/** Сколько фильтров из «шторки» включено — для счётчика на кнопке. */
export function sheetFilterCount(f: FeedFilters): number {
  return (
    f.categories.length +
    (f.radius !== null ? 1 : 0) +
    (f.priceMax !== null ? 1 : 0) +
    (f.format !== "all" ? 1 : 0) +
    (f.sort ? 1 : 0) +
    (f.date === "range" ? 1 : 0)
  );
}

/** Сбросить фильтры из панели (и свой период), не трогая вкладку, быстрые даты и поиск. */
export function resetPanel(f: FeedFilters): FeedFilters {
  const date = f.date === "range" ? null : f.date;
  return { ...f, date, from: null, to: null, categories: [], priceMax: null, format: "all", sort: null, radius: null };
}
