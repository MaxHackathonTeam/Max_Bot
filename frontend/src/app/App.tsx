import { MaxUI, type PlatformType } from '@maxhub/max-ui'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import { useBackButton } from '../bridge/useBackButton'
import { getWebApp } from '../bridge/webApp'
import { HomePage } from '../pages/HomePage'
import { StubPage } from '../pages/StubPage'
import { AuthGate } from './auth'
import { startParamToPath } from './deeplink'
import { useSession } from './session'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
})

function platform(): PlatformType {
  return getWebApp()?.platform === 'ios' ? 'ios' : 'android'
}

function colorScheme(): 'light' | 'dark' {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

/** Один раз после входа переходит по диплинку start_param (§3.1). */
function DeeplinkRedirect() {
  const { startParam } = useSession()
  const navigate = useNavigate()
  const done = useRef(false)

  useEffect(() => {
    if (done.current) return
    done.current = true
    const path = startParamToPath(startParam)
    if (path) navigate(path, { replace: true })
  }, [startParam, navigate])
  return null
}

function AppRoutes() {
  useBackButton()
  return (
    <>
      <DeeplinkRedirect />
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/event/:id" element={<StubPage title="Событие" />} />
        <Route path="/org/:id" element={<StubPage title="Организатор" />} />
        <Route path="/draft/:id" element={<StubPage title="Черновик события" />} />
        <Route path="/invite/:token" element={<StubPage title="Приглашение в команду" />} />
        <Route path="/settings" element={<StubPage title="Настройки" />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  )
}

export function App() {
  useEffect(() => {
    getWebApp()?.ready?.()
  }, [])

  return (
    <MaxUI platform={platform()} colorScheme={colorScheme()}>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <AuthGate>
            <AppRoutes />
          </AuthGate>
        </BrowserRouter>
      </QueryClientProvider>
    </MaxUI>
  )
}
