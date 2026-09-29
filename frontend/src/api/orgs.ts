// Открытый профиль организации и поиск организаций — без входа.
// Схемы — backend/app/schemas/orgs.py (OrgPublic, OrgSearchPage); ИНН, телефона, почты и
// команды в ответах нет.

import { api, type EventPage, type Tier } from "./client";

export interface OrgPublic {
  id: number;
  name: string;
  kind: string;
  description: string | null;
  locality: { id: number; name: string } | null;
  address: string | null;
  website: string | null;
  vk_url: string | null;
  verified: boolean;
  is_demo: boolean;
  future_events: number;
  official_events: number;
  community_events: number;
}

export interface OrgSearchItem {
  id: number;
  name: string;
  kind: string;
  locality: { id: number; name: string } | null;
  verified: boolean;
  is_demo: boolean;
  future_events: number;
}

export interface OrgSearchPage {
  items: OrgSearchItem[];
  next_cursor: string | null;
}

export interface OrgSearchQuery {
  q?: string;
  locality_id?: number | null;
  type?: string | null;
  cursor?: string;
}

/** Все виды организаций (в форме создания — только часть из них). */
export const KIND_LABELS: Record<string, string> = {
  dk: "Дом культуры",
  library: "Библиотека",
  museum: "Музей",
  theatre: "Театр",
  cinema: "Кинотеатр",
  park: "Парк",
  sport: "Спорт",
  nko: "НКО",
  ip: "ИП",
  club: "Клуб",
  municipal: "Муниципальная организация",
  other: "Другое",
};

export const orgKindLabel = (kind: string) => KIND_LABELS[kind] ?? "Организация";

export const fetchOrgPublic = (id: number) => api<OrgPublic>(`/orgs/${id}/public`);

export function fetchOrgPublicEvents(id: number, tier: Tier, cursor?: string): Promise<EventPage> {
  const params = new URLSearchParams({ tier });
  if (cursor) params.set("cursor", cursor);
  return api<EventPage>(`/orgs/${id}/public/events?${params}`);
}

export function searchOrgs(query: OrgSearchQuery): Promise<OrgSearchPage> {
  const params = new URLSearchParams();
  if (query.q) params.set("q", query.q);
  if (query.locality_id) params.set("locality_id", String(query.locality_id));
  if (query.type) params.set("type", query.type);
  if (query.cursor) params.set("cursor", query.cursor);
  return api<OrgSearchPage>(`/orgs/search?${params}`);
}
