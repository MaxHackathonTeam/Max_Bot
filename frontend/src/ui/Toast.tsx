import { Check, CircleAlert, Info } from "lucide-react";
import { useCallback, useMemo, useRef, useState, type ReactNode } from "react";
import { cx } from "./classes";
import { ToastContext, type ToastKind } from "./toastContext";

interface Item {
  id: number;
  message: string;
  kind: ToastKind;
}

const DURATION_MS = 3500;
const ICONS = { success: Check, info: Info, error: CircleAlert };

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Item[]>([]);
  const nextId = useRef(1);

  const show = useCallback((message: string, kind: ToastKind = "success") => {
    const id = nextId.current++;
    // Не больше трёх тостов одновременно.
    setItems((current) => [...current.slice(-2), { id, message, kind }]);
    window.setTimeout(() => setItems((current) => current.filter((item) => item.id !== id)), DURATION_MS);
  }, []);

  const api = useMemo(() => ({ show }), [show]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((item) => {
          const Icon = ICONS[item.kind];
          return (
            <div key={item.id} className={cx("toast", item.kind === "error" && "toast--error")}>
              <Icon size={18} aria-hidden />
              <span>{item.message}</span>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}
