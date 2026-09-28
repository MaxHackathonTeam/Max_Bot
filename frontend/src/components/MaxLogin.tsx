import { ExternalLink, LogIn, RefreshCw, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { isToken, pollWebCode, requestWebCode, type WebCode } from "../api/auth";
import { ApiError } from "../api/client";
import { useSession } from "../app/session";
import { openExternal } from "../bridge/actions";
import { Button } from "../ui/Button";
import { buttonClass } from "../ui/classes";
import { Spinner } from "../ui/Spinner";
import { QrCode } from "./QrCode";
import { useToast } from "../ui/toastContext";

const POLL_MS = 2000;
const MAX_WAIT_S = 300;
const NETWORK_FAILS_LIMIT = 3;

type State =
  | { step: "idle" }
  | { step: "requesting" }
  | { step: "waiting"; code: WebCode; deadline: number }
  | { step: "expired" }
  | { step: "error"; message: string };

function left(deadline: number): string {
  const s = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/**
 * Вход через MAX с сайта: код → бот подтверждает → опрос /auth/web-code/poll каждые 2 с
 * (не дольше 5 минут). Данные гостя бэкенд переносит в аккаунт MAX.
 */
export function MaxLogin({
  onDone,
  compact = false,
  autoStart = false,
}: {
  onDone?: () => void;
  compact?: boolean;
  /** Сразу запросить код (модальное окно входа). */
  autoStart?: boolean;
}) {
  const { signIn } = useSession();
  const toast = useToast();
  const [state, setState] = useState<State>({ step: "idle" });
  const [, tick] = useState(0);
  const fails = useRef(0);
  const onDoneRef = useRef(onDone);
  useEffect(() => {
    onDoneRef.current = onDone;
  });

  const start = async () => {
    setState({ step: "requesting" });
    try {
      const code = await requestWebCode();
      fails.current = 0;
      const ttl = Math.min(code.expires_in, MAX_WAIT_S);
      setState({ step: "waiting", code, deadline: Date.now() + ttl * 1000 });
    } catch (error) {
      setState({ step: "error", message: error instanceof Error ? error.message : "Не получилось получить код" });
    }
  };

  const started = useRef(false);
  useEffect(() => {
    if (!autoStart || started.current) return;
    started.current = true;
    // Код запрашиваем один раз при открытии: started защищает от повторного вызова.
    void start();
  }, [autoStart]);

  const waiting = state.step === "waiting" ? state : null;
  useEffect(() => {
    if (!waiting) return;
    let stopped = false;
    const timer = window.setInterval(async () => {
      tick((n) => n + 1);
      if (Date.now() > waiting.deadline) {
        setState({ step: "expired" });
        return;
      }
      try {
        const result = await pollWebCode(waiting.code.code);
        if (stopped || !isToken(result)) return;
        stopped = true;
        signIn(result);
        toast.show("Готово, вход через MAX выполнен");
        onDoneRef.current?.();
      } catch (error) {
        if (stopped) return;
        if (error instanceof ApiError && error.status === 410) setState({ step: "expired" });
        else if (error instanceof ApiError && error.status === 0) {
          fails.current += 1;
          if (fails.current >= NETWORK_FAILS_LIMIT) setState({ step: "error", message: error.message });
        } else setState({ step: "error", message: error instanceof Error ? error.message : "Ошибка входа" });
      }
    }, POLL_MS);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [waiting, signIn, toast]);

  if (state.step === "idle")
    return (
      <Button variant="dark" size={compact ? "md" : "lg"} block={!compact} icon={<LogIn size={18} aria-hidden />} onClick={() => void start()}>
        Войти через MAX
      </Button>
    );

  if (state.step === "requesting")
    return (
      <Button variant="dark" size={compact ? "md" : "lg"} block={!compact} loading>
        Получаем код
      </Button>
    );

  if (state.step === "waiting")
    return (
      <div className="stack login-code">
        <div className="login-code__grid">
          <QrCode value={state.code.deeplink} label="QR-код для входа: наведи камеру телефона" />
          <div className="stack">
            <p className="small muted">Код для сверки в боте</p>
            <div className="code-display" aria-label={`Код ${state.code.code.split("").join(" ")}`}>
              {state.code.code}
            </div>
            <a
              className={buttonClass({ variant: "primary", size: "lg", block: true })}
              href={state.code.deeplink}
              target="_blank"
              rel="noreferrer"
              onClick={(e) => {
                // В MAX ссылку открывает Bridge, в браузере — обычная вкладка.
                e.preventDefault();
                openExternal(state.code.deeplink);
              }}
            >
              <ExternalLink size={18} aria-hidden />
              Открыть бота
            </a>
          </div>
        </div>
        <div className="row small muted" aria-live="polite">
          <Spinner />
          <span className="grow">
            Ждём подтверждения · код действует <span className="nowrap">ещё {left(state.deadline)}</span>
          </span>
        </div>
        <div className="row row--wrap">
          <Button variant="ghost" size="sm" icon={<RefreshCw size={16} aria-hidden />} onClick={() => void start()}>
            Получить новый код
          </Button>
          <Button variant="ghost" size="sm" icon={<X size={16} aria-hidden />} onClick={() => setState({ step: "idle" })}>
            Отмена
          </Button>
        </div>
      </div>
    );

  return (
    <div className="stack" role="alert">
      <p className={state.step === "error" ? "error-text" : undefined}>
        {state.step === "expired" ? "Код устарел — запроси новый." : state.message}
      </p>
      <Button variant="dark" block={!compact} icon={<RefreshCw size={18} aria-hidden />} onClick={() => void start()}>
        {state.step === "expired" ? "Получить новый код" : "Повторить"}
      </Button>
    </div>
  );
}
