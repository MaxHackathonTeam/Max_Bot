import { BadgeCheck, CreditCard, MonitorPlay } from "lucide-react";
import type { EventCard } from "../api/client";
import { Badge } from "../ui/Badge";

/** Видимая плашка демо-данных (§7.2): обязательна везде, где показано демо-событие. */
export function DemoBadge() {
  return <Badge tone="demo">Демо-данные</Badge>;
}

export function EventBadges({ card, withPrice = false }: { card: EventCard; withPrice?: boolean }) {
  return (
    <div className="badges">
      {card.is_demo && <DemoBadge />}
      {card.org?.verified && (
        <Badge tone="verified" icon={<BadgeCheck size={14} aria-hidden />}>
          Организатор проверен
        </Badge>
      )}
      {card.pushkin_card && (
        <Badge tone="pushkin" icon={<CreditCard size={14} aria-hidden />}>
          Пушкинская карта
        </Badge>
      )}
      {withPrice && card.price_type === "free" && <Badge tone="free">Бесплатно</Badge>}
      {card.is_online && (
        <Badge icon={<MonitorPlay size={14} aria-hidden />}>Онлайн</Badge>
      )}
      {card.age_rating !== null && <Badge>{card.age_rating}+</Badge>}
    </div>
  );
}
