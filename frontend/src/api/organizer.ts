// API кабинета организатора (этап 3): организации, команда, приглашения, верификация,
// площадки, обложки и управление событиями. Схемы — backend/app/schemas/{orgs,venues,manage}.py.

import { api, type SessionInfo } from "./client";

// --- Организации -----------------------------------------------------------------------

export type OrgKind =
  | "dk"
  | "museum"
  | "park"
  | "library"
  | "theatre"
  | "cinema"
  | "sport"
  | "nko"
  | "ip";
export type OrgRole = "owner" | "editor";

export const ORG_KINDS: { value: OrgKind; label: string }[] = [
  { value: "dk", label: "Дом культуры" },
  { value: "library", label: "Библиотека" },
  { value: "museum", label: "Музей" },
  { value: "theatre", label: "Театр" },
  { value: "cinema", label: "Кинотеатр" },
  { value: "park", label: "Парк" },
  { value: "sport", label: "Спорт" },
  { value: "nko", label: "НКО" },
  { value: "ip", label: "ИП" },
];

export interface Org {
  id: number;
  name: string;
  kind: OrgKind;
  inn: string | null;
  ogrn: string | null;
  registry_name: string | null;
  locality_id: number | null;
  locality_name: string | null;
  address: string | null;
  website: string | null;
  vk_url: string | null;
  description: string | null;
  phone: string | null;
  email: string | null;
  verified: boolean;
  verification_status: string;
  verification_method: string | null;
  verified_at: string | null;
  my_role: OrgRole | null;
}

export interface OrgInput {
  name?: string;
  kind?: OrgKind;
  inn?: string | null;
  locality_id?: number | null;
  address?: string | null;
  website?: string | null;
  vk_url?: string | null;
  phone?: string | null;
  email?: string | null;
  description?: string | null;
}

export const fetchMyOrgs = () => api<Org[]>("/orgs/mine");
export const fetchOrg = (id: number) => api<Org>(`/orgs/${id}`);
export const createOrg = (body: OrgInput) =>
  api<Org>("/orgs", { method: "POST", body: JSON.stringify(body) });
export const updateOrg = (id: number, body: OrgInput) =>
  api<Org>(`/orgs/${id}`, { method: "PATCH", body: JSON.stringify(body) });

// --- Команда и приглашения ---------------------------------------------------------------

export interface Member {
  user_id: number;
  name: string;
  role: OrgRole;
  joined_at: string;
  is_me: boolean;
}

export interface Invite {
  token: string;
  payload: string;
  url: string | null;
  role: OrgRole;
  grants_verification: boolean;
  expires_at: string;
}

export interface InvitePreview {
  org_id: number;
  org_name: string;
  role: OrgRole;
  grants_verification: boolean;
  expires_at: string;
  valid: boolean;
  reason: string | null;
}

export const fetchMembers = (orgId: number) =>
  api<Member[]>(`/orgs/${orgId}/members`);
export const removeMember = (orgId: number, userId: number) =>
  api<void>(`/orgs/${orgId}/members/${userId}`, { method: "DELETE" });
export const createInvite = (orgId: number, role: OrgRole) =>
  api<Invite>(`/orgs/${orgId}/invites`, {
    method: "POST",
    body: JSON.stringify({ role }),
  });
export const fetchInvite = (token: string) =>
  api<InvitePreview>(`/invites/${encodeURIComponent(token)}`);
export const acceptInvite = (token: string) =>
  api<{ org_id: number; role: OrgRole; verified: boolean }>(
    `/invites/${encodeURIComponent(token)}/accept`,
    {
      method: "POST",
    },
  );

// --- Верификация ---------------------------------------------------------------------------

export type StepStatus = "ok" | "failed" | "pending" | "skipped";

export interface VerificationStep {
  code: "registry" | "phone" | "site_code" | "page_check" | "admin";
  title: string;
  status: StepStatus;
  message: string | null;
}

export interface Verification {
  id: number;
  org_id: number;
  method: "registry_auto" | "manual" | string;
  status: string;
  code: string | null;
  site_url: string | null;
  steps: VerificationStep[];
  decision_reason: string | null;
  created_at: string;
  last_attempt_at: string | null;
  next_attempt_at: string | null;
}

export interface VerificationStart {
  method: "registry_auto" | "manual";
  inn?: string | null;
  site_url?: string | null;
  comment?: string | null;
}

/** null — заявок ещё не было. */
export const fetchVerification = (orgId: number) =>
  api<Verification | null>(`/orgs/${orgId}/verification`);
export const startVerification = (orgId: number, body: VerificationStart) =>
  api<Verification>(`/orgs/${orgId}/verification`, {
    method: "POST",
    body: JSON.stringify(body),
  });
export const recheckVerification = (orgId: number) =>
  api<Verification>(`/orgs/${orgId}/verification/recheck`, { method: "POST" });

// --- Площадки и обложки --------------------------------------------------------------------

export interface Venue {
  id: number;
  name: string;
  address: string | null;
  locality_id: number;
  locality_name: string | null;
  lat: number;
  lon: number;
  org_id: number | null;
}

export interface VenueInput {
  name: string;
  address?: string | null;
  /** Без координат площадка ставится в центр населённого пункта (тогда locality_id обязателен). */
  lat?: number | null;
  lon?: number | null;
  org_id?: number | null;
  locality_id?: number | null;
}

export interface Media {
  id: number;
  url: string;
  width: number | null;
  height: number | null;
  size: number;
}

export function searchVenues(
  q: string,
  orgId: number | null,
): Promise<Venue[]> {
  const params = new URLSearchParams();
  if (q) params.set("q", q);
  if (orgId !== null) params.set("org_id", String(orgId));
  return api<Venue[]>(`/venues?${params}`);
}

export const createVenue = (body: VenueInput) =>
  api<Venue>("/venues", { method: "POST", body: JSON.stringify(body) });

export function uploadMedia(file: File): Promise<Media> {
  const form = new FormData();
  form.append("file", file);
  return api<Media>("/media", { method: "POST", body: form });
}

// --- Управление событиями -------------------------------------------------------------------

export type EventStatus =
  | "draft"
  | "pending"
  | "published"
  | "rejected"
  | "hidden"
  | "cancelled"
  | "archived";
export type PriceType = "free" | "paid" | "donation" | "unknown";
export type AgeRating = 0 | 6 | 12 | 16 | 18;

export const STATUS_LABELS: Record<string, string> = {
  draft: "Черновик",
  pending: "На проверке",
  published: "Опубликовано",
  rejected: "Отклонено",
  hidden: "Скрыто",
  cancelled: "Отменено",
  archived: "В архиве",
};

export interface Accessibility {
  ramp: boolean;
  toilet: boolean;
  sign_language: boolean;
}

export interface SessionInput {
  id?: number | null;
  starts_at: string;
  ends_at?: string | null;
}

export interface EventFields {
  title?: string;
  description?: string | null;
  short_description?: string | null;
  category?: string | null;
  tags?: string[];
  cover_media_id?: number | null;
  venue_id?: number | null;
  locality_id?: number | null;
  is_online?: boolean;
  online_url?: string | null;
  price_type?: PriceType;
  price_min?: string | null;
  price_max?: string | null;
  pushkin_card?: boolean;
  age_rating?: AgeRating | null;
  registration_required?: boolean;
  ticket_url?: string | null;
  contacts?: string | null;
  accessibility?: Accessibility | null;
  sessions?: SessionInput[];
}

export interface EventManage {
  id: number;
  status: EventStatus;
  trust_tier: "official" | "community" | string;
  organization_id: number | null;
  org_name: string | null;
  org_verified: boolean;
  author_user_id: number | null;
  title: string;
  description: string | null;
  short_description: string | null;
  category: string | null;
  tags: string[];
  cover_media_id: number | null;
  cover_url: string | null;
  venue: { id: number; name: string; address: string | null } | null;
  locality_id: number | null;
  locality_name: string | null;
  timezone: string;
  is_online: boolean;
  online_url: string | null;
  indoor: string;
  price_type: PriceType;
  price_min: string | null;
  price_max: string | null;
  pushkin_card: boolean;
  age_rating: number | null;
  registration_required: boolean;
  ticket_url: string | null;
  contacts: string | null;
  accessibility: Partial<Accessibility> | null;
  sessions: SessionInfo[];
  locked_fields: string[];
  ai_fields: string[];
  moderation_reason: string | null;
  published_at: string | null;
  created_at: string;
  updated_at: string;
  can_pushkin: boolean;
}

export interface MyEventItem {
  id: number;
  title: string;
  status: EventStatus;
  trust_tier: string;
  category: string | null;
  cover_url: string | null;
  organization_id: number | null;
  org_name: string | null;
  next_starts_at: string | null;
  timezone: string;
  moderation_reason: string | null;
  updated_at: string;
}

export const fetchManage = (id: number) =>
  api<EventManage>(`/events/${id}/manage`);
export const createEvent = (
  body: EventFields & { title: string; organization_id?: number | null },
) =>
  api<EventManage>("/events", { method: "POST", body: JSON.stringify(body) });
export const patchEvent = (id: number, body: EventFields) =>
  api<EventManage>(`/events/${id}`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
export const submitEvent = (id: number) =>
  api<EventManage>(`/events/${id}/submit`, { method: "POST" });
export const cancelEvent = (id: number) =>
  api<EventManage>(`/events/${id}/cancel`, { method: "POST" });
export const deleteEvent = (id: number) =>
  api<void>(`/events/${id}`, { method: "DELETE" });

function statusQuery(status: string | null): string {
  return status ? `?${new URLSearchParams({ status })}` : "";
}

export const fetchMyEvents = (status: string | null) =>
  api<MyEventItem[]>(`/me/events${statusQuery(status)}`);
export const fetchOrgEvents = (orgId: number, status: string | null) =>
  api<MyEventItem[]>(`/orgs/${orgId}/events${statusQuery(status)}`);

export const STATUS_FILTERS: (string | null)[] = [
  null,
  "draft",
  "pending",
  "published",
  "rejected",
  "hidden",
  "cancelled",
];

// --- Проверка перед отправкой -----------------------------------------------------------------

export interface CheckViolation {
  code: string;
  field: string;
  message: string;
  kind: string;
}

export interface CheckOut {
  violations: CheckViolation[];
  warnings: string[];
}

/** Правила модерации (rules.py) до отправки: что помешает и что стоит поправить. */
export const checkEvent = (id: number) =>
  api<CheckOut>(`/events/${id}/check`, { method: "POST" });

