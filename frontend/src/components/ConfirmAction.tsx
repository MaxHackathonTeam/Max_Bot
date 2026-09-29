import { CircleAlert } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Button } from "../ui/Button";
import type { ButtonLook } from "../ui/classes";

interface ConfirmActionProps {
  /** Кнопка до подтверждения. */
  label: string;
  icon?: ReactNode;
  variant?: ButtonLook["variant"];
  size?: ButtonLook["size"];
  disabled?: boolean;
  /** Что именно произойдёт — показываем перед «Да». */
  warning: string;
  confirmLabel: string;
  loading: boolean;
  onConfirm: () => void;
}

/** Действие, которое нельзя отменить, — в два нажатия: кнопка → предупреждение → «Да» / «Отмена». */
export function ConfirmAction({
  label,
  icon,
  variant = "ghost",
  size,
  disabled,
  warning,
  confirmLabel,
  loading,
  onConfirm,
}: ConfirmActionProps) {
  const [asking, setAsking] = useState(false);
  if (!asking) {
    return (
      <Button variant={variant} size={size} disabled={disabled} icon={icon} onClick={() => setAsking(true)}>
        {label}
      </Button>
    );
  }
  return (
    <div className="stack stack--tight">
      <p className="notice notice--danger small" role="alert">
        <CircleAlert size={16} aria-hidden />
        <span>{warning}</span>
      </p>
      <div className="row row--wrap">
        <Button variant="danger" size={size} loading={loading} icon={icon} onClick={onConfirm}>
          {confirmLabel}
        </Button>
        <Button variant="ghost" size={size} disabled={loading} onClick={() => setAsking(false)}>
          Отмена
        </Button>
      </div>
    </div>
  );
}
