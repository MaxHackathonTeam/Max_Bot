import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { ApiError, loginWithInitData, setAccessToken, type TokenOut } from '../api/client'
import { getLaunch } from '../bridge/webApp'
import { ErrorScreen, LoadingScreen } from '../pages/Status'
import { SessionContext } from './session'

async function login(): Promise<TokenOut & { inMax: boolean }> {
  const launch = getLaunch()
  const token = await loginWithInitData(launch.initData)
  setAccessToken(token.access_token)
  return { ...token, inMax: launch.inMax }
}

/** Вход по initData (§11.1): до успешного входа остальное приложение не рендерится. */
export function AuthGate({ children }: { children: ReactNode }) {
  const auth = useQuery({ queryKey: ['auth'], queryFn: login, staleTime: Infinity, retry: false })

  if (auth.isPending) return <LoadingScreen />
  if (auth.isError) {
    const error = auth.error
    const outsideMax = !getLaunch().inMax && error instanceof ApiError && error.status === 401
    return (
      <ErrorScreen
        message={
          outsideMax
            ? 'Открой «Афишу рядом» из бота в MAX — кнопка «📍 Открыть афишу»'
            : error.message
        }
        onRetry={outsideMax ? undefined : () => void auth.refetch()}
      />
    )
  }
  return (
    <SessionContext.Provider value={{ startParam: auth.data.start_param, inMax: auth.data.inMax }}>
      {children}
    </SessionContext.Provider>
  )
}
