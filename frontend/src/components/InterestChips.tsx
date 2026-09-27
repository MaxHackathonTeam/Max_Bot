import { useCategories } from "../app/profile";
import { categoryLook } from "../lib/categories";
import { Chip } from "../ui/Chip";
import { Skeleton } from "../ui/Skeleton";

export function InterestChips({ selected, onToggle }: { selected: string[]; onToggle: (slug: string) => void }) {
  const categories = useCategories();
  if (categories.isPending)
    return (
      <div className="chips" aria-hidden>
        {[90, 110, 80, 120, 100].map((w) => (
          <Skeleton key={w} width={w} height={36} radius={999} />
        ))}
      </div>
    );
  return (
    <div className="chips">
      {categories.data?.map((c) => {
        const Icon = categoryLook(c.slug).icon;
        return (
          <Chip key={c.slug} pressed={selected.includes(c.slug)} onClick={() => onToggle(c.slug)} icon={<Icon size={16} aria-hidden />}>
            {c.name}
          </Chip>
        );
      })}
    </div>
  );
}
