import { Building } from "lucide-react";
import type { ReactNode } from "react";
import type { Me } from "../api/client";
import { isMaxAccount, useMe } from "../app/profile";
import { useSession } from "../app/session";
import { ErrorScreen, LoadingScreen } from "../pages/Status";
import { Card } from "../ui/Card";
import { MaxLogin } from "./MaxLogin";

/**
 * Кабинет организатора, черновики и приглашения — только для аккаунта MAX:
 * в MAX вход автоматический, на сайте — по коду из бота.
 */
export function RequireMax({
  title,
  text,
  children,
}: {
  title: string;
  text: string;
  children: (me: Me) => ReactNode;
}) {
  const session = useSession();
  const me = useMe();

  if (session.booting || session.signingIn || (session.hasToken && me.isPending)) return <LoadingScreen />;
  if (me.isError) return <ErrorScreen message={me.error.message} onRetry={() => void me.refetch()} />;
  if (isMaxAccount(me.data)) return <>{children(me.data)}</>;
  if (session.inMax)
    return <ErrorScreen message="Не получилось войти через MAX." onRetry={() => void session.ensureAccount()} />;

  return (
    <main className="page page--narrow">
      <div className="state-screen stack stack--loose">
        <Building size={36} className="empty__icon" aria-hidden />
        <div className="stack">
          <h1 className="h1">{title}</h1>
          <p className="muted">{text}</p>
        </div>
        <Card className="stack">
          <MaxLogin />
        </Card>
      </div>
    </main>
  );
}
