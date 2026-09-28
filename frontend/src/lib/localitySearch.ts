// Автоподстановка населённого пункта: чистые функции для LocalityPicker.

import type { Locality } from "../api/client";

export const MIN_QUERY = 2;
export const MAX_OPTIONS = 10;

/** Виды пунктов из ck_localities_kind; other в подписи не показываем. */
const KIND_LABELS: Record<string, string> = {
  city: "город",
  town: "город",
  pgt: "пгт",
  village: "село",
  settlement: "посёлок",
  other: "",
};

/** Подпись варианта: вид пункта, район и регион, чтобы различать тёзок. */
export function localitySubtitle(locality: Locality): string {
  const kind = KIND_LABELS[locality.kind] ?? locality.kind;
  const parts = [kind, locality.municipality, locality.region];
  return parts.filter((part, i) => part && parts.indexOf(part) === i).join(" · ");
}

export interface TextPart {
  text: string;
  match: boolean;
}

/** Делит название на куски для подсветки совпадения (без учёта регистра и ё/е). */
export function highlightParts(text: string, query: string): TextPart[] {
  const norm = (s: string) => s.toLowerCase().replace(/ё/g, "е");
  const needle = norm(query.trim());
  if (!needle) return [{ text, match: false }];
  const hay = norm(text);
  const parts: TextPart[] = [];
  let from = 0;
  for (let at = hay.indexOf(needle); at !== -1; at = hay.indexOf(needle, from)) {
    if (at > from) parts.push({ text: text.slice(from, at), match: false });
    parts.push({ text: text.slice(at, at + needle.length), match: true });
    from = at + needle.length;
  }
  if (from < text.length) parts.push({ text: text.slice(from), match: false });
  return parts;
}

/** Стрелки по списку по кругу; -1 — ничего не выбрано. */
export function moveActive(active: number, delta: 1 | -1, count: number): number {
  if (count === 0) return -1;
  if (active < 0) return delta === 1 ? 0 : count - 1;
  return (active + delta + count) % count;
}

/** Понятная причина, почему геолокация не сработала. */
export function geoErrorText(error: unknown): string {
  const code = (error as { code?: number } | null)?.code;
  if (code === 1) return "Доступ к геолокации закрыт. Напиши название пункта.";
  if (code === 3) return "Геолокация не ответила вовремя. Напиши название пункта.";
  if (error instanceof Error && error.message === "unsupported")
    return "Здесь геолокация недоступна. Напиши название пункта.";
  return "Не получилось определить место. Напиши название пункта.";
}
