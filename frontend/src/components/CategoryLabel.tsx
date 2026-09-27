import type { ReactNode } from "react";
import { useCategories } from "../app/profile";
import { categoryLook } from "../lib/categories";

/** Категория события: иконка и название цветом категории. */
export function CategoryLabel({ slug, suffix }: { slug: string | null; suffix?: ReactNode }) {
  const categories = useCategories();
  const category = categories.data?.find((c) => c.slug === slug);
  if (!slug || !category) return null;
  const { icon: Icon, color } = categoryLook(slug);
  return (
    <span className="cat" style={{ color }}>
      <Icon size={15} aria-hidden />
      {category.name}
      {suffix}
    </span>
  );
}
