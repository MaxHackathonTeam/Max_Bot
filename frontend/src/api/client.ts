// Клиент API: JSON, Bearer-токен, ошибки формата {"error": {"code", "message", "details"}}.

export interface ConsentState {
  doc: "terms" | "privacy" | "org_pd";
  version: string;
  accepted: boolean;
  accepted_at: string | null;
}

export interface Me {
  id: number;
  max_user_id: number | null;
  first_name: string | null;
  last_name: string | null;
  username: string | null;
  locality_id: number | null;
  has_home_point: boolean;
  radius_km: number;
  interests: string[];
  notify_digest: boolean;
  notify_reminders: boolean;
  consents: ConsentState[];
  needs_onboarding: boolean;
  is_admin: boolean;
}

export interface TokenOut {
  access_token: string;
  expires_at: string;
  user: Me;
  start_param: string | null;
}

export interface FieldError {
  field: string;
  code: string;
  message: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown> | null;

  constructor(
    status: number,
    code: string,
    message: string,
    details: Record<string, unknown> | null = null,
  ) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }

  /** Ошибки полей формы из details.fields (422). */
  get fields(): FieldError[] {
    const fields = this.details?.fields;
    return Array.isArray(fields) ? (fields as FieldError[]) : [];
  }
}

let accessToken: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function hasAccessToken(): boolean {
  return accessToken !== null;
}

/** Вызывается, когда сервер отверг наш токен (истёк, пользователь удалён). */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  // FormData: Content-Type с boundary ставит браузер.
  if (init.body !== undefined && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const sentToken = accessToken;
  if (sentToken) headers.set("Authorization", `Bearer ${sentToken}`);

  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, "network", "Нет связи с сервером. Проверь интернет");
  }
  if (response.status === 204) return undefined as T;
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401 && sentToken && sentToken === accessToken) onUnauthorized?.();
    const error = (
      body as {
        error?: {
          code?: string;
          message?: string;
          details?: Record<string, unknown> | null;
        };
      } | null
    )?.error;
    throw new ApiError(
      response.status,
      error?.code ?? "http_error",
      error?.message ?? "Что-то пошло не так, попробуй ещё раз",
      error?.details ?? null,
    );
  }
  return body as T;
}

export function loginWithInitData(initData: string): Promise<TokenOut> {
  return api<TokenOut>("/auth/max", {
    method: "POST",
    body: JSON.stringify({ init_data: initData }),
  });
}

export function fetchMe(): Promise<Me> {
  return api<Me>("/me");
}

// --- Профиль ---------------------------------------------------------------------------

export type Radius = 5 | 15 | 30 | 50;
export const RADII: Radius[] = [5, 15, 30, 50];

export interface MeUpdate {
  locality_id?: number | null;
  radius_km?: Radius;
  interests?: string[];
  notify_digest?: boolean;
  notify_reminders?: boolean;
}

export function updateMe(patch: MeUpdate): Promise<Me> {
  return api<Me>("/me", { method: "PATCH", body: JSON.stringify(patch) });
}

export function acceptConsents(docs: ConsentState["doc"][]): Promise<Me> {
  return api<Me>("/me/consents", {
    method: "POST",
    body: JSON.stringify({ docs }),
  });
}

export function deleteMe(): Promise<void> {
  return api<void>("/me", { method: "DELETE" });
}

// --- Справочники -----------------------------------------------------------------------

export interface Locality {
  id: number;
  name: string;
  kind: string;
  region: string | null;
  municipality: string | null;
  lat: number;
  lon: number;
  timezone: string;
  distance_km: number | null;
}

export interface Category {
  slug: string;
  name: string;
  emoji: string;
}

export function searchLocalities(q: string, limit = 10): Promise<Locality[]> {
  return api<Locality[]>(`/localities?${new URLSearchParams({ q, limit: String(limit) })}`);
}

export function nearestLocalities(
  lat: number,
  lon: number,
): Promise<Locality[]> {
  const params = new URLSearchParams({ lat: String(lat), lon: String(lon) });
  return api<Locality[]>(`/localities/nearest?${params}`);
}

export function fetchLocality(id: number): Promise<Locality> {
  return api<Locality>(`/localities/${id}`);
}

export function fetchCategories(): Promise<Category[]> {
  return api<Category[]>("/categories");
}

// --- События ---------------------------------------------------------------------------

export interface SessionInfo {
  id: number;
  starts_at: string;
  ends_at: string | null;
  status: string;
}

export interface EventCard {
  id: number;
  title: string;
  short_description: string | null;
  category: string | null;
  cover_url: string | null;
  trust_tier: "official" | "community" | "demo" | string;
  is_demo: boolean;
  org: { id: number; name: string; verified: boolean } | null;
  venue: {
    id: number;
    name: string;
    address: string | null;
    lat?: number | null;
    lon?: number | null;
  } | null;
  locality: { id: number; name: string } | null;
  timezone: string;
  next_session: SessionInfo | null;
  sessions_count: number;
  distance_km: number | null;
  price_type: "free" | "paid" | "donation" | string;
  price_min: string | null;
  price_max: string | null;
  pushkin_card: boolean;
  age_rating: number | null;
  is_online: boolean;
}

export interface EventDetail extends EventCard {
  description: string | null;
  tags: string[];
  sessions: SessionInfo[];
  map_url: string | null;
  online_url: string | null;
  ticket_url: string | null;
  registration_required: boolean;
  contacts: string | null;
  indoor: string;
  source: {
    code: "organizer" | "community" | "proculture" | "demo";
    label: string;
    url: string | null;
    updated_at: string;
  };
  accessibility: Record<string, unknown> | null;
  ai_fields: string[];
  status: string;
  is_past: boolean;
  saved_session_ids: number[];
  share_url: string | null;
}

export interface EventPage {
  items: EventCard[];
  next_cursor: string | null;
  total?: number | null;
}

export type Tier = "official" | "community";
export type DatePreset = "today" | "tomorrow" | "weekend";

export interface EventQuery {
  locality_id?: number;
  radius_km?: Radius;
  date?: DatePreset;
  /** Период в днях пункта события, ГГГГ-ММ-ДД включительно. */
  date_from?: string;
  date_to?: string;
  category?: string[];
  free?: boolean;
  price_max?: number;
  pushkin?: boolean;
  age?: number;
  tier?: Tier;
  format?: "all" | "offline" | "online";
  q?: string;
  sort?: "date" | "distance" | "relevance";
  cursor?: string;
  limit?: number;
  include_total?: boolean;
}

export function eventQueryString(query: EventQuery): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (
      value === undefined ||
      value === null ||
      value === "" ||
      value === false
    )
      continue;
    if (Array.isArray(value))
      value.forEach((v) => params.append(key, String(v)));
    else params.set(key, String(value));
  }
  return params.toString();
}

export function fetchEvents(query: EventQuery): Promise<EventPage> {
  return api<EventPage>(`/events?${eventQueryString(query)}`);
}

export function fetchEvent(id: number): Promise<EventDetail> {
  return api<EventDetail>(`/events/${id}`);
}

export function prepareShareCard(id: number): Promise<{ mid: string; chat_type: "DIALOG" | "CHAT" }> {
  return api<{ mid: string; chat_type: "DIALOG" | "CHAT" }>(`/events/${id}/share-card`, { method: "POST" });
}

export interface SaveOut {
  saved_session_ids: number[];
}

export function saveEvent(id: number, sessionId?: number): Promise<SaveOut> {
  return api<SaveOut>(`/events/${id}/save`, {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId ?? null }),
  });
}

export function unsaveEvent(id: number, sessionId?: number): Promise<SaveOut> {
  const query = sessionId ? `?session_id=${sessionId}` : "";
  return api<SaveOut>(`/events/${id}/save${query}`, { method: "DELETE" });
}

export interface SavedItem {
  session: SessionInfo;
  event: EventCard;
}

export function fetchSaved(when: "upcoming" | "past"): Promise<SavedItem[]> {
  return api<SavedItem[]>(`/me/saved?when=${when}`);
}
