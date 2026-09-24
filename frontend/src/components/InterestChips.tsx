import { useCategories } from '../app/profile'
import { Chip } from './Chip'

export function InterestChips({
  selected,
  onToggle,
}: {
  selected: string[]
  onToggle: (slug: string) => void
}) {
  const categories = useCategories()
  return (
    <div className="chips chips--wrap">
      {categories.data?.map((c) => (
        <Chip key={c.slug} selected={selected.includes(c.slug)} onClick={() => onToggle(c.slug)}>
          {c.emoji} {c.name}
        </Chip>
      ))}
    </div>
  )
}
