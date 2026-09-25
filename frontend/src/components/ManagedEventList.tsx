import { CellList, CellSimple, Typography } from "@maxhub/max-ui";
import { useNavigate } from "react-router-dom";
import {
  STATUS_FILTERS,
  STATUS_LABELS,
  type MyEventItem,
} from "../api/organizer";
import { formatWhen } from "../lib/format";
import { Chip } from "./Chip";

export function StatusChips({
  value,
  onChange,
}: {
  value: string | null;
  onChange: (s: string | null) => void;
}) {
  return (
    <div className="chips chips--scroll">
      {STATUS_FILTERS.map((s) => (
        <Chip
          key={s ?? "all"}
          selected={value === s}
          onClick={() => onChange(s)}
        >
          {s ? STATUS_LABELS[s] : "Все"}
        </Chip>
      ))}
    </div>
  );
}

/** События автора или организации по статусам; нажатие открывает форму редактирования. */
export function ManagedEventList({ items }: { items: MyEventItem[] }) {
  const navigate = useNavigate();
  if (items.length === 0) {
    return (
      <Typography.Body variant="medium" className="muted empty">
        Событий пока нет.
      </Typography.Body>
    );
  }
  return (
    <CellList mode="island" filled>
      {items.map((e) => {
        const when = e.next_starts_at
          ? formatWhen(e.next_starts_at, e.timezone)
          : "без будущих сеансов";
        const reason =
          e.moderation_reason && ["rejected", "hidden"].includes(e.status)
            ? ` · ${e.moderation_reason}`
            : "";
        return (
          <CellSimple
            key={e.id}
            title={e.title || "Без названия"}
            subtitle={`${STATUS_LABELS[e.status] ?? e.status} · ${when}${reason}`}
            showChevron
            onClick={() => navigate(`/draft/${e.id}`)}
          />
        );
      })}
    </CellList>
  );
}
