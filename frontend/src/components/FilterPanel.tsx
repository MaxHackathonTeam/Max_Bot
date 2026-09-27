import type { ReactNode } from "react";
import { RADII, type Radius } from "../api/client";
import type { FeedFilters } from "../lib/feedParams";
import { Chip } from "../ui/Chip";
import { Input } from "../ui/Field";
import { InterestChips } from "./InterestChips";

const FORMATS: [FeedFilters["format"], string][] = [
  ["all", "Все"],
  ["offline", "Очно"],
  ["online", "Онлайн"],
];
const SORTS: [FeedFilters["sort"], string][] = [
  [null, "По дате"],
  ["distance", "Ближе"],
];

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="filter-group">
      <legend className="eyebrow">{title}</legend>
      {children}
    </fieldset>
  );
}

/**
 * Редкие фильтры FR-CAT-2: радиус, категории, цена, формат, сортировка.
 * На десктопе стоит в боковой колонке и применяется сразу, на телефоне — в шторке.
 */
export function FilterPanel({
  value,
  radius,
  onChange,
}: {
  value: FeedFilters;
  radius: Radius;
  onChange: (next: FeedFilters) => void;
}) {
  const patch = (p: Partial<FeedFilters>) => onChange({ ...value, ...p });
  const current = value.radius ?? radius;

  return (
    <div className="stack stack--loose">
      <Group title="Радиус">
        <div className="chips">
          {RADII.map((r) => (
            <Chip key={r} pressed={current === r} onClick={() => patch({ radius: r })}>
              {r} км
            </Chip>
          ))}
        </div>
      </Group>

      <Group title="Категории">
        <InterestChips
          selected={value.categories}
          onToggle={(slug) =>
            patch({
              categories: value.categories.includes(slug)
                ? value.categories.filter((c) => c !== slug)
                : [...value.categories, slug],
            })
          }
        />
      </Group>

      <Group title="Цена до, ₽">
        <Input
          inputMode="numeric"
          placeholder="Любая"
          value={value.priceMax ?? ""}
          aria-label="Цена до, рублей"
          onChange={(e) => {
            const digits = e.target.value.replace(/\D/g, "").slice(0, 6);
            patch({ priceMax: digits ? Number(digits) : null });
          }}
        />
      </Group>

      <Group title="Формат">
        <div className="chips">
          {FORMATS.map(([f, text]) => (
            <Chip key={f} pressed={value.format === f} onClick={() => patch({ format: f })}>
              {text}
            </Chip>
          ))}
        </div>
      </Group>

      <Group title="Сортировка">
        <div className="chips">
          {SORTS.map(([s, text]) => (
            <Chip key={text} pressed={value.sort === s} onClick={() => patch({ sort: s })}>
              {text}
            </Chip>
          ))}
        </div>
      </Group>
    </div>
  );
}
