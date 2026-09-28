// Статус афиши глазами автора (/my): подпись, причина и доступные действия.
// Переходы повторяют services/event_editor.py: submit — из draft|rejected, cancel — из published|pending|hidden.

import { STATUS_LABELS, type MyEventItem } from "../api/organizer";
import type { BadgeTone } from "../ui/Badge";

export interface AuthorStatus {
  label: string;
  tone: BadgeTone;
  reason: string | null;
  editable: boolean;
  resubmit: boolean;
  cancellable: boolean;
}

export function authorStatus(e: Pick<MyEventItem, "status" | "moderation_reason">): AuthorStatus {
  const reason = e.moderation_reason || null;
  const returned = e.status === "draft" && reason !== null;
  const base = {
    label: STATUS_LABELS[e.status] ?? e.status,
    tone: "plain" as BadgeTone,
    reason: null as string | null,
    editable: e.status === "draft" || e.status === "rejected",
    resubmit: returned || e.status === "rejected",
    cancellable: ["published", "pending", "hidden"].includes(e.status),
  };
  if (returned) return { ...base, label: "Вернули на доработку", tone: "accent", reason };
  if (e.status === "rejected") return { ...base, tone: "danger", reason };
  if (e.status === "hidden") return { ...base, tone: "danger", reason };
  if (e.status === "published") return { ...base, tone: "verified" };
  return base;
}
