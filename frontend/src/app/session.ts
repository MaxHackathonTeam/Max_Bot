import { createContext, useContext } from "react";
import type { TokenOut } from "../api/client";

export interface Session {
  /** Сайт открыт внутри MAX (Bridge отдал подписанную initData). */
  inMax: boolean;
  /** Bridge ещё грузится — нельзя решить, MAX это или браузер. */
  booting: boolean;
  /** Идёт вход (MAX по initData, гость или по коду). */
  signingIn: boolean;
  /** Есть токен — можно звать эндпоинты, требующие входа. */
  hasToken: boolean;
  /** Диплинк: start_param из MAX (проверен бэкендом) или ?startapp= в браузере. */
  startParam: string | null;
  /** Гарантирует аккаунт: в MAX дожидается входа по initData, в браузере создаёт гостя. */
  ensureAccount: () => Promise<void>;
  /** Принять токен (вход по коду MAX). */
  signIn: (token: TokenOut) => void;
  /** Выйти (только в браузере; в MAX вход автоматический). */
  signOut: () => void;
}

export const SessionContext = createContext<Session | null>(null);

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession вне SessionProvider");
  return session;
}
