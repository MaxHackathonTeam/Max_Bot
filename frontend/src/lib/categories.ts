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
  concert: { icon: Music, color: "#9c3d2e" },
  theatre: { icon: Drama, color: "#7a3b5e" },
  cinema: { icon: Clapperboard, color: "#3e4a6b" },
  exhibition: { icon: Frame, color: "#6b5a2e" },
  masterclass: { icon: Hammer, color: "#7a5a1f" },
  lecture: { icon: Presentation, color: "#3d5e63" },
  festival: { icon: PartyPopper, color: "#a8402a" },
  sport: { icon: Trophy, color: "#2f6b45" },
  excursion: { icon: Compass, color: "#4a6131" },
  games: { icon: Dices, color: "#5b4a7a" },
  kids: { icon: ToyBrick, color: "#9a4e2b" },
  other: { icon: Shapes, color: "#5b5247" },
};

export function categoryLook(slug: string | null | undefined): CategoryLook {
  return LOOKS[slug ?? ""] ?? LOOKS.other;
}
