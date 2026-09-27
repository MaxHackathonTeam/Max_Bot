import type { ReactNode } from "react";

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  text?: ReactNode;
  action?: ReactNode;
}

export function EmptyState({ icon, title, text, action }: EmptyStateProps) {
  return (
    <div className="empty">
      {icon && <span className="empty__icon">{icon}</span>}
      <p className="empty__title">{title}</p>
      {text && <p className="muted">{text}</p>}
      {action}
    </div>
  );
}
