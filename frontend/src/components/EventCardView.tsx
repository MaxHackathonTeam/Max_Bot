import { Typography } from "@maxhub/max-ui";
import { Link } from "react-router-dom";
import type { EventCard } from "../api/client";
import { formatDistance, formatPrice, formatWhen } from "../lib/format";
import { EventBadges } from "./Badges";

export function EventCardView({
  card,
  when,
}: {
  card: EventCard;
  when?: string;
}) {
  const startsAt = when ?? card.next_session?.starts_at;
  const place = [card.venue?.name, card.locality?.name]
    .filter(Boolean)
    .join(", ");
  const distance = formatDistance(card.distance_km);
  return (
    <Link
      to={`/event/${card.id}`}
      className="event-card"
      data-testid="event-card"
    >
      {card.cover_url && (
        <img
          className="event-card__cover"
          src={card.cover_url}
          alt=""
          loading="lazy"
        />
      )}
      <div className="event-card__body">
        {startsAt && (
          <Typography.Label variant="medium-strong" className="accent">
            {formatWhen(startsAt, card.timezone)}
            {card.sessions_count > 1 &&
              ` · ещё сеансы: ${card.sessions_count - 1}`}
          </Typography.Label>
        )}
        <Typography.Headline variant="small-strong">
          {card.title}
        </Typography.Headline>
        {(place || distance) && (
          <Typography.Body variant="small" className="muted">
            {[place || null, distance].filter(Boolean).join(" · ")}
          </Typography.Body>
        )}
        <Typography.Body variant="small">{formatPrice(card)}</Typography.Body>
        <EventBadges card={card} />
      </div>
    </Link>
  );
}
