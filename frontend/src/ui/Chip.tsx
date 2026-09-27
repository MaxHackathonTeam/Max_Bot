import type { ReactNode } from "react";

interface ChipProps {
  pressed?: boolean;
  onClick: () => void;
  icon?: ReactNode;
  /** Счётчик справа (например, число активных фильтров). */
  count?: number;
  disabled?: boolean;
  children: ReactNode;
}

export function Chip({ pressed, onClick, icon, count, disabled, children }: ChipProps) {
  return (
    <button type="button" className="chip" aria-pressed={pressed ?? undefined} onClick={onClick} disabled={disabled}>
      {icon}
      {children}
      {count ? <span className="chip__count">{count}</span> : null}
    </button>
  );
}
