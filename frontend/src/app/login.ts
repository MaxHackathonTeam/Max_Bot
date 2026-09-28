// Окно входа через MAX: одно на приложение, открывается из шапки и из действий,
// которым нужен аккаунт MAX («Добавить афишу»). В MAX вход автоматический.

import { createContext, useCallback, useContext } from "react";
import { isMaxAccount, useMe } from "./profile";
import { useSession } from "./session";

export interface LoginRequest {
  /** Пояснение над кодом, например «Чтобы добавить афишу, войди через MAX». */
  reason?: string;
  /** Куда перейти после входа. */
  next?: string;
}

export interface LoginPrompt {
  open: (request?: LoginRequest) => void;
}

export const LoginContext = createContext<LoginPrompt | null>(null);

export function useLoginPrompt(): LoginPrompt {
  const prompt = useContext(LoginContext);
  if (!prompt) throw new Error("useLoginPrompt вне LoginProvider");
  return prompt;
}

/**
 * Проверка перед действием: true — аккаунт MAX уже есть, действуй.
 * Иначе в MAX повторяем вход по initData, на сайте — открываем окно входа.
 */
export function useRequireLogin(): (request?: LoginRequest) => boolean {
  const session = useSession();
  const me = useMe();
  const prompt = useLoginPrompt();
  return useCallback(
    (request?: LoginRequest) => {
      if (isMaxAccount(me.data)) return true;
      if (session.inMax) void session.ensureAccount();
      else prompt.open(request);
      return false;
    },
    [me.data, session, prompt],
  );
}
