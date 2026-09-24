import type { EventCard } from '../api/client'

/** Видимая плашка демо-данных (§7.2): обязательна везде, где показано демо-событие. */
export function DemoBadge() {
  return <span className="badge badge--demo">Демо-данные</span>
}

export function EventBadges({ card }: { card: EventCard }) {
  return (
    <div className="badges">
      {card.is_demo && <DemoBadge />}
      {card.org?.verified && <span className="badge badge--verified">✓ Организатор проверен</span>}
      {card.pushkin_card && <span className="badge badge--pushkin">💳 Пушкинская карта</span>}
      {card.price_type === 'free' && <span className="badge">Бесплатно</span>}
      {card.is_online && <span className="badge">Онлайн</span>}
      {card.age_rating !== null && <span className="badge">{card.age_rating}+</span>}
    </div>
  )
}
