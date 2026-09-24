import { Button, Input, Typography } from '@maxhub/max-ui'
import { useState } from 'react'
import { RADII } from '../api/client'
import type { FeedFilters } from '../lib/feedParams'
import { Chip } from './Chip'
import { InterestChips } from './InterestChips'

const FORMATS: [FeedFilters['format'], string][] = [
  ['all', 'Все'],
  ['offline', 'Очно'],
  ['online', 'Онлайн'],
]
const SORTS: [FeedFilters['sort'], string][] = [
  [null, 'По дате'],
  ['distance', 'Ближе'],
]

/** «Шторка» с редкими фильтрами FR-CAT-2; частые — чипсами над лентой. */
export function FilterSheet({
  value,
  radius,
  onApply,
  onClose,
}: {
  value: FeedFilters
  radius: number
  onApply: (f: FeedFilters) => void
  onClose: () => void
}) {
  const [draft, setDraft] = useState(value)
  const [price, setPrice] = useState(value.priceMax === null ? '' : String(value.priceMax))
  const patch = (p: Partial<FeedFilters>) => setDraft((d) => ({ ...d, ...p }))
  const currentRadius = draft.radius ?? radius

  const apply = () => {
    const n = Number(price)
    onApply({ ...draft, priceMax: price.trim() && Number.isInteger(n) && n >= 0 ? n : null })
  }
  const reset = () => {
    setPrice('')
    setDraft({ ...draft, categories: [], priceMax: null, format: 'all', sort: null, radius: null })
  }

  return (
    <div className="sheet" role="dialog" aria-modal="true" aria-label="Фильтры">
      <button type="button" className="sheet__backdrop" aria-label="Закрыть" onClick={onClose} />
      <div className="sheet__panel stack">
        <Typography.Headline variant="small-strong">Фильтры</Typography.Headline>

        <Typography.Label variant="medium-strong">Радиус</Typography.Label>
        <div className="chips">
          {RADII.map((r) => (
            <Chip key={r} selected={currentRadius === r} onClick={() => patch({ radius: r })}>
              {r} км
            </Chip>
          ))}
        </div>

        <Typography.Label variant="medium-strong">Категории</Typography.Label>
        <InterestChips
          selected={draft.categories}
          onToggle={(slug) =>
            patch({
              categories: draft.categories.includes(slug)
                ? draft.categories.filter((c) => c !== slug)
                : [...draft.categories, slug],
            })
          }
        />

        <Typography.Label variant="medium-strong">Цена до, ₽</Typography.Label>
        <Input
          inputMode="numeric"
          placeholder="Любая"
          value={price}
          onChange={(e) => setPrice(e.target.value.replace(/\D/g, '').slice(0, 6))}
          aria-label="Цена до"
        />

        <Typography.Label variant="medium-strong">Формат</Typography.Label>
        <div className="chips">
          {FORMATS.map(([f, text]) => (
            <Chip key={f} selected={draft.format === f} onClick={() => patch({ format: f })}>
              {text}
            </Chip>
          ))}
        </div>

        <Typography.Label variant="medium-strong">Сортировка</Typography.Label>
        <div className="chips">
          {SORTS.map(([s, text]) => (
            <Chip key={text} selected={draft.sort === s} onClick={() => patch({ sort: s })}>
              {text}
            </Chip>
          ))}
        </div>

        <div className="row">
          <Button size="large" variant="secondary" onClick={reset}>
            Сбросить
          </Button>
          <Button size="large" stretched onClick={apply}>
            Показать
          </Button>
        </div>
      </div>
    </div>
  )
}
