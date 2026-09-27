import { CalendarPlus } from "lucide-react";
import { STATUS_FILTERS, STATUS_LABELS, type MyEventItem } from "../api/organizer";
import { formatWhen } from "../lib/format";
import { Chip } from "../ui/Chip";
import { EmptyState } from "../ui/EmptyState";
import { ListRow } from "../ui/ListRow";

export function StatusChips({ value, onChange }: { value: string | null; onChange: (s: string | null) => void }) {
  return (
    <div className="chips chips--scroll" role="group" aria-label="Статус">
      {STATUS_FILTERS.map((s) => (
        <Chip key={s ?? "all"} pressed={value === s} onClick={() => onChange(s)}>
          {s ? STATUS_LABELS[s] : "Все"}
        </Chip>
      ))}
    </div>
  );
}

/** События автора или организации по статусам; нажатие открывает форму редактирования. */
export function ManagedEventList({ items }: { items: MyEventItem[] }) {
  if (items.length === 0) {
    return <EmptyState icon={<CalendarPlus size={28} aria-hidden />} title="Событий пока нет" />;
  }
  return (
    <div className="list">
      {items.map((e) => {
        const when = e.next_starts_at ? formatWhen(e.next_starts_at, e.timezone) : "без будущих сеансов";
        const reason =
          e.moderation_reason && ["rejected", "hidden"].includes(e.status) ? ` · ${e.moderation_reason}` : "";
        return (
          <ListRow
            key={e.id}
            to={`/draft/${e.id}`}
            title={e.title || "Без названия"}
            subtitle={`${STATUS_LABELS[e.status] ?? e.status} · ${when}${reason}`}
          />
        );
      })}
    </div>
  );
}
