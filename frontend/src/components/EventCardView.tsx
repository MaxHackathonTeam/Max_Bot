import { MapPin } from "lucide-react";
import { Link } from "react-router-dom";
import type { EventCard } from "../api/client";
import { formatDateParts, formatDistance, formatPrice } from "../lib/format";
import { cx } from "../ui/classes";
import { Skeleton } from "../ui/Skeleton";
import { EventBadges } from "./Badges";
import { CategoryLabel } from "./CategoryLabel";

/** Карточка ленты в духе афиши: крупное число слева, справа — что, где и почём. */
export function EventCardView({ card, when }: { card: EventCard; when?: string }) {
  const startsAt = when ?? card.next_session?.starts_at;
  const date = startsAt ? formatDateParts(startsAt, card.timezone) : null;
  const place = [card.venue?.name, card.locality?.name].filter(Boolean).join(", ");
  const distance = formatDistance(card.distance_km);
  const free = card.price_type === "free";
  return (
    <Link to={`/event/${card.id}`} className="ecard" data-testid="event-card">
      {card.cover_url && <img className="ecard__cover" src={card.cover_url} alt="" loading="lazy" />}
      <div className="ecard__main">
        <div className="ecard__date">
          {date ? (
            <>
              <span className="ecard__day">{date.day}</span>
              <span className="ecard__month">{date.month}</span>
              <span className="ecard__weekday">{date.weekday}</span>
              <span className="ecard__time">{date.time}</span>
            </>
          ) : (
            <span className="ecard__weekday">дата уточняется</span>
          )}
        </div>
        <div className="ecard__body">
          <CategoryLabel slug={card.category} />
          <h3 className="ecard__title">{card.title}</h3>
          {(place || distance) && (
            <p className="ecard__meta">
              <MapPin size={15} aria-hidden />
              <span>{[place || null, distance].filter(Boolean).join(" · ")}</span>
            </p>
          )}
          {card.sessions_count > 1 && <p className="ecard__meta">и ещё сеансов: {card.sessions_count - 1}</p>}
          <div className="ecard__foot">
            <span className={cx("price", free && "price--free")}>{formatPrice(card)}</span>
            <EventBadges card={card} />
          </div>
        </div>
      </div>
    </Link>
  );
}

export function EventCardSkeleton() {
  return (
    <div className="ecard" aria-hidden>
      <div className="ecard__main">
        <div className="ecard__date">
          <Skeleton width={36} height={32} />
          <Skeleton width={32} height={12} />
          <Skeleton width={44} height={18} />
        </div>
        <div className="ecard__body">
          <Skeleton width={90} height={12} />
          <Skeleton width="85%" height={20} />
          <Skeleton width="60%" height={14} />
          <Skeleton width={80} height={16} />
        </div>
      </div>
    </div>
  );
}
