// Вход без MAX (контракт переработки): гость — POST /auth/guest, вход через MAX с сайта —
// одноразовый код, который пользователь подтверждает в боте.
// Пока бэкенд не выкатил эндпоинты, в dev-сборке (import.meta.env.DEV) при 404/405
// включаются моки поверх /auth/max с фейковой initData — работает только с DEV_AUTH=1.

import { devInitData } from "../bridge/webApp";
import { ApiError, api, loginWithInitData, type TokenOut } from "./client";

export interface WebCode {
  code: string;
  /** https://max.ru/<bot>?start=login_<code> */
  deeplink: string;
  expires_in: number;
}

export type PollResult = { status: "pending" } | TokenOut;

export function isToken(result: PollResult): result is TokenOut {
  return "access_token" in result;
}

const MOCKS = import.meta.env.DEV;
const DEV_MAX_USER = 100000001;

function endpointMissing(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 404 || error.status === 405);
}

export async function loginGuest(): Promise<TokenOut> {
  try {
    return await api<TokenOut>("/auth/guest", { method: "POST" });
  } catch (error) {
    if (!MOCKS || !endpointMissing(error)) throw error;
    // Мок: отдельный dev-пользователь на каждого «гостя».
    const id = 200000000 + Math.floor(Math.random() * 99999999);
    return loginWithInitData(devInitData(id));
  }
}

// --- Вход по коду ------------------------------------------------------------------------

const MOCK_CONFIRM_MS = 6000;
const mockCodes = new Map<string, { created: number; ttl: number }>();

function mockCode(): WebCode {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  const code = Array.from({ length: 6 }, () => alphabet[Math.floor(Math.random() * alphabet.length)]).join("");
  mockCodes.set(code, { created: Date.now(), ttl: 300 });
  return { code, deeplink: `https://max.ru/?start=login_${code}`, expires_in: 300 };
}

/** Код для входа. Если передан токен гостя, бэкенд перенесёт его данные в аккаунт MAX. */
export async function requestWebCode(): Promise<WebCode> {
  try {
    return await api<WebCode>("/auth/web-code", { method: "POST" });
  } catch (error) {
    if (!MOCKS || !endpointMissing(error)) throw error;
    return mockCode();
  }
}

/** 202 {"status":"pending"} — ждём; 200 — токен; 410 — код истёк. */
export async function pollWebCode(code: string): Promise<PollResult> {
  const mock = mockCodes.get(code);
  if (mock) {
    const age = Date.now() - mock.created;
    if (age > mock.ttl * 1000) throw new ApiError(410, "code_expired", "Код устарел — запроси новый");
    if (age < MOCK_CONFIRM_MS) return { status: "pending" };
    mockCodes.delete(code);
    return loginWithInitData(devInitData(DEV_MAX_USER));
  }
  return api<PollResult>("/auth/web-code/poll", { method: "POST", body: JSON.stringify({ code }) });
}
