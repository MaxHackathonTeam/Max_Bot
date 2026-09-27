// Сессия без блокирующего входа: лента, поиск и карточка работают сразу.
// В MAX — вход по подписанной initData (/auth/max), в браузере — гость (/auth/guest)
// при первом действии, которому нужен аккаунт, или вход через MAX по коду.

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { loginGuest } from "../api/auth";
import { hasAccessToken, loginWithInitData, setAccessToken, setUnauthorizedHandler, type TokenOut } from "../api/client";
import { devInitData, getWebApp, loadBridge, maxInitData } from "../bridge/webApp";
import { readLocal, writeLocal } from "../lib/storage";
import { SessionContext, type Session } from "./session";

const TOKEN_KEY = "afisha.token";
// Токен, который истечёт в ближайшую минуту, не берём.
const EXPIRY_MARGIN_MS = 60_000;

function readStoredToken(): string | null {
  const raw = readLocal(TOKEN_KEY);
  if (!raw) return null;
  try {
    const stored = JSON.parse(raw) as { token?: unknown; expires_at?: unknown };
    if (typeof stored.token === "string" && Date.parse(String(stored.expires_at)) > Date.now() + EXPIRY_MARGIN_MS)
      return stored.token;
  } catch {
    // Повреждённая запись — удаляем ниже.
  }
  writeLocal(TOKEN_KEY, null);
  return null;
}

function urlParam(name: string): string | null {
  return new URLSearchParams(window.location.search).get(name);
}

interface State {
  inMax: boolean;
  booting: boolean;
  signingIn: boolean;
  hasToken: boolean;
  startParam: string | null;
}

function initialState(): State {
  const stored = readStoredToken();
  setAccessToken(stored);
  return {
    inMax: false,
    booting: !getWebApp(),
    signingIn: false,
    hasToken: stored !== null,
    startParam: urlParam("startapp"),
  };
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const [state, setState] = useState(initialState);
  const pending = useRef<Promise<void> | null>(null);

  const apply = useCallback(
    (token: TokenOut, persist: boolean) => {
      setAccessToken(token.access_token);
      writeLocal(TOKEN_KEY, persist ? JSON.stringify({ token: token.access_token, expires_at: token.expires_at }) : null);
      client.setQueryData(["me"], token.user);
      setState((s) => ({ ...s, hasToken: true, signingIn: false }));
    },
    [client],
  );

  const dropToken = useCallback(() => {
    setAccessToken(null);
    writeLocal(TOKEN_KEY, null);
    client.removeQueries({ queryKey: ["me"] });
    client.removeQueries({ queryKey: ["saved"] });
    setState((s) => ({ ...s, hasToken: false }));
  }, [client]);

  /** Один вход за раз: параллельные «Пойду» и «Настройки» ждут один и тот же запрос. */
  const run = useCallback(
    (login: () => Promise<TokenOut>, persist: boolean, onToken?: (token: TokenOut) => void) => {
      pending.current ??= (async () => {
        setState((s) => ({ ...s, signingIn: true }));
        try {
          const token = await login();
          apply(token, persist);
          onToken?.(token);
        } finally {
          setState((s) => ({ ...s, signingIn: false }));
          pending.current = null;
        }
      })();
      return pending.current;
    },
    [apply],
  );

  useEffect(() => {
    setUnauthorizedHandler(dropToken);
    return () => setUnauthorizedHandler(null);
  }, [dropToken]);

  useEffect(() => {
    let cancelled = false;
    void loadBridge().then(() => {
      if (cancelled) return;
      const initData = maxInitData();
      setState((s) => ({ ...s, booting: false, inMax: initData !== null }));
      if (initData) {
        getWebApp()?.ready?.();
        // В MAX токен не храним: initData при каждом запуске свежая.
        setAccessToken(null);
        run(
          () => loginWithInitData(initData),
          false,
          (token) => setState((s) => ({ ...s, startParam: token.start_param })),
        ).catch(() => {
          // Лента работает и без входа; ensureAccount повторит попытку.
          setState((s) => ({ ...s, hasToken: false }));
        });
        return;
      }
      const devUser = Number(urlParam("dev_user"));
      if (Number.isInteger(devUser) && devUser > 0) {
        run(() => loginWithInitData(devInitData(devUser, urlParam("startapp"))), true).catch(() => undefined);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [run]);

  const ensureAccount = useCallback(async () => {
    await loadBridge();
    if (pending.current) await pending.current;
    if (hasAccessToken()) return;
    const initData = maxInitData();
    await run(() => (initData ? loginWithInitData(initData) : loginGuest()), !initData);
  }, [run]);

  const signIn = useCallback(
    (token: TokenOut) => {
      apply(token, true);
      // Гость мог стать другим пользователем — всё персональное перечитываем.
      void client.invalidateQueries();
    },
    [apply, client],
  );

  const session = useMemo<Session>(
    () => ({ ...state, ensureAccount, signIn, signOut: dropToken }),
    [state, ensureAccount, signIn, dropToken],
  );

  return <SessionContext.Provider value={session}>{children}</SessionContext.Provider>;
}
