// Вид категорий: иконка lucide и приглушённый цвет из одной палитры (эмодзи из API не рисуем).

import {
  Clapperboard,
  Compass,
  Dices,
  Drama,
  Frame,
  Hammer,
  Music,
  PartyPopper,
  Presentation,
  Shapes,
  ToyBrick,
  Trophy,
  type LucideIcon,
} from "lucide-react";

export interface CategoryLook {
  icon: LucideIcon;
  color: string;
}

const LOOKS: Record<string, CategoryLook> = {
  concert: { icon: Music, color: "var(--cat-concert)" },
  theatre: { icon: Drama, color: "var(--cat-theatre)" },
  cinema: { icon: Clapperboard, color: "var(--cat-cinema)" },
  exhibition: { icon: Frame, color: "var(--cat-exhibition)" },
  masterclass: { icon: Hammer, color: "var(--cat-masterclass)" },
  lecture: { icon: Presentation, color: "var(--cat-lecture)" },
  festival: { icon: PartyPopper, color: "var(--cat-festival)" },
  sport: { icon: Trophy, color: "var(--cat-sport)" },
  excursion: { icon: Compass, color: "var(--cat-excursion)" },
  games: { icon: Dices, color: "var(--cat-games)" },
  kids: { icon: ToyBrick, color: "var(--cat-kids)" },
  other: { icon: Shapes, color: "var(--cat-other)" },
};

export function categoryLook(slug: string | null | undefined): CategoryLook {
  return LOOKS[slug ?? ""] ?? LOOKS.other;
}
