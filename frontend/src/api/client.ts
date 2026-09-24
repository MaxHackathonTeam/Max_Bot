// Клиент API: JSON, Bearer-токен, ошибки формата {"error": {"code", "message", "details"}}.

export interface ConsentState {
  doc: 'terms' | 'privacy' | 'org_pd'
  version: string
  accepted: boolean
  accepted_at: string | null
}

export interface Me {
  id: number
  max_user_id: number | null
  first_name: string | null
  last_name: string | null
  username: string | null
  locality_id: number | null
  radius_km: number
  interests: string[]
  consents: ConsentState[]
  needs_onboarding: boolean
  is_admin: boolean
}

export interface TokenOut {
  access_token: string
  expires_at: string
  user: Me
  start_param: string | null
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

let accessToken: string | null = null

export function setAccessToken(token: string | null): void {
  accessToken = token
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body !== undefined) headers.set('Content-Type', 'application/json')
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)

  let response: Response
  try {
    response = await fetch(`/api/v1${path}`, { ...init, headers })
  } catch {
    throw new ApiError(0, 'network', 'Нет связи с сервером. Проверь интернет')
  }
  if (response.status === 204) return undefined as T
  const body: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const error = (body as { error?: { code?: string; message?: string } } | null)?.error
    throw new ApiError(
      response.status,
      error?.code ?? 'http_error',
      error?.message ?? 'Что-то пошло не так, попробуй ещё раз',
    )
  }
  return body as T
}

export function loginWithInitData(initData: string): Promise<TokenOut> {
  return api<TokenOut>('/auth/max', {
    method: 'POST',
    body: JSON.stringify({ init_data: initData }),
  })
}

export function fetchMe(): Promise<Me> {
  return api<Me>('/me')
}
