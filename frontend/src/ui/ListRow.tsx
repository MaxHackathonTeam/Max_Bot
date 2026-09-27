import { ChevronRight } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

interface ListRowProps {
  title: ReactNode;
  subtitle?: ReactNode;
  icon?: ReactNode;
  /** Элемент справа (переключатель, бейдж). */
  after?: ReactNode;
  to?: string;
  onClick?: () => void;
  disabled?: boolean;
}

export function ListRow({ title, subtitle, icon, after, to, onClick, disabled }: ListRowProps) {
  const content = (
    <>
      {icon && <span className="list-row__icon">{icon}</span>}
      <span className="list-row__text">
        <span className="list-row__title">{title}</span>
        {subtitle && <span className="list-row__subtitle">{subtitle}</span>}
      </span>
      {after}
      {(to || onClick) && !after && <ChevronRight className="list-row__chevron" size={18} aria-hidden />}
    </>
  );
  if (to)
    return (
      <Link className="list-row" to={to}>
        {content}
      </Link>
    );
  if (onClick)
    return (
      <button type="button" className="list-row" onClick={onClick} disabled={disabled}>
        {content}
      </button>
    );
  return <div className="list-row">{content}</div>;
}
