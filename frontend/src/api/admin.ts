// Раздел модератора (/api/v1/admin/*). Права проверяет бэкенд (AdminDep), фронт только скрывает вход.

import { api } from "./client";
import type { CheckViolation, EventManage } from "./organizer";

export type QueueFilter = "new" | "returned" | "all";
export type EventAction = "approve" | "reject" | "return";

export interface QueueEvent {
  id: number;
  title: string;
  status: string;
  trust_tier: string;
  organization_id: number | null;
  org_name: string | null;
  moderation_reason: string | null;
  reports: number;
  next_starts_at: string | null;
  updated_at: string;
  returned: boolean;
}

export interface QueueVerification {
  id: number;
  org_id: number;
  org_name: string;
  method: string;
  inn: string | null;
  site_url: string | null;
  steps: { code: string; title: string; status: string; message: string | null }[];
  created_at: string;
}

export interface QueueOut {
  events: QueueEvent[];
  verifications: QueueVerification[];
}

export interface AuditItem {
  id: number;
  created_at: string;
  actor_type: string;
  actor_user_id: number | null;
  action: string;
  entity_type: string;
  entity_id: number | null;
  diff: Record<string, unknown> | null;
  request_id: string | null;
}

export interface AdminDecision {
  id: number;
  created_at: string;
  actor_type: string;
  actor_user_id: number | null;
  verdict: string;
  reasons: string[] | null;
}

/** Карточка заявки: GET /admin/events/{id}. */
export interface AdminEventCard {
  event: EventManage;
  author: { id: number; name: string | null; max_user_id: number | null } | null;
  flags: CheckViolation[];
  decisions: AdminDecision[];
  history: AuditItem[];
}

export const fetchQueue = (filter: QueueFilter) =>
  api<QueueOut>(`/admin/queue?${new URLSearchParams({ filter })}`);

export const fetchAdminEvent = (id: number) => api<AdminEventCard>(`/admin/events/${id}`);

export const decideEvent = (id: number, action: EventAction, reason: string | null) =>
  api<void>(`/admin/events/${id}/decision`, {
    method: "POST",
    body: JSON.stringify({ action, reason }),
  });

export const decideVerification = (id: number, approve: boolean, reason: string | null) =>
  api<unknown>(`/admin/verifications/${id}/decision`, {
    method: "POST",
    body: JSON.stringify({ action: approve ? "approve" : "reject", reason }),
  });
