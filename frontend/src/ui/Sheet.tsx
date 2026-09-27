import { X } from "lucide-react";
import { useEffect, useId, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { IconButton } from "./Button";

interface SheetProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  /** Прилипающий низ с кнопками. */
  footer?: ReactNode;
}

/** Шторка снизу на телефоне и модальное окно на широком экране. Esc и клик по фону закрывают. */
export function Sheet({ open, onClose, title, children, footer }: SheetProps) {
  const titleId = useId();
  const panel = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    panel.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCloseRef.current();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
      previous?.focus?.();
    };
  }, [open]);

  if (!open) return null;
  return createPortal(
    <div className="sheet">
      <button type="button" className="sheet__backdrop" aria-label="Закрыть" tabIndex={-1} onClick={onClose} />
      <div ref={panel} className="sheet__panel" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
        <span className="sheet__grip" aria-hidden />
        <div className="sheet__head">
          <h2 className="h2" id={titleId}>
            {title}
          </h2>
          <IconButton label="Закрыть" onClick={onClose}>
            <X size={20} aria-hidden />
          </IconButton>
        </div>
        {children}
        {footer && <div className="sheet__foot">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}
