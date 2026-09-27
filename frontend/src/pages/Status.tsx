import { CircleAlert, RefreshCw } from "lucide-react";
import { Button } from "../ui/Button";
import { Loading, Skeleton } from "../ui/Skeleton";

/** Общий скелетон страницы — пока нет данных для конкретной разметки. */
export function LoadingScreen() {
  return (
    <main className="page page--narrow">
      <Loading>
        <Skeleton width="55%" height={30} />
        <Skeleton width="80%" height={16} />
        <Skeleton height={120} radius={14} />
        <Skeleton height={56} radius={14} />
        <Skeleton height={56} radius={14} />
      </Loading>
    </main>
  );
}

/** Ошибка в блоке: сообщение и «Повторить». */
export function ErrorBlock({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="empty" role="alert">
      <CircleAlert size={28} className="empty__icon" aria-hidden />
      <p className="empty__title">Что-то пошло не так</p>
      <p className="muted">{message}</p>
      {onRetry && (
        <Button variant="secondary" icon={<RefreshCw size={16} aria-hidden />} onClick={onRetry}>
          Повторить
        </Button>
      )}
    </div>
  );
}

export function ErrorScreen({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <main className="page page--narrow">
      <div className="state-screen">
        <ErrorBlock message={message} onRetry={onRetry} />
      </div>
    </main>
  );
}
