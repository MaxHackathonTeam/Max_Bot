import { useCallback, useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { LoginContext, type LoginPrompt, type LoginRequest } from "../app/login";
import { Sheet } from "../ui/Sheet";
import { MaxLogin } from "./MaxLogin";

const DEFAULT_REASON = "Войди через MAX, чтобы добавлять афиши и получать ответы модерации в бот.";

/** Провайдер окна входа: код, QR, ссылка на бота и таймер (MaxLogin). */
export function LoginProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const [request, setRequest] = useState<LoginRequest | null>(null);
  const close = useCallback(() => setRequest(null), []);
  const open = useCallback((next?: LoginRequest) => setRequest(next ?? {}), []);
  const prompt = useMemo<LoginPrompt>(() => ({ open }), [open]);

  return (
    <LoginContext.Provider value={prompt}>
      {children}
      <Sheet open={request !== null} onClose={close} title="Вход через MAX">
        <div className="stack">
          <p>{request?.reason ?? DEFAULT_REASON}</p>
          <p className="small muted">
            Отсканируй QR телефоном или открой бота по кнопке и подтверди вход. Сайт войдёт сам.
          </p>
          <MaxLogin
            autoStart
            onDone={() => {
              const next = request?.next;
              close();
              if (next) navigate(next);
            }}
          />
        </div>
      </Sheet>
    </LoginContext.Provider>
  );
}
