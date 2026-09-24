import { useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { getWebApp } from './webApp'

/** Системная кнопка «Назад» MAX: видна на всех экранах, кроме главного. */
export function useBackButton(): void {
  const location = useLocation()
  const navigate = useNavigate()

  useEffect(() => {
    const button = getWebApp()?.BackButton
    if (!button) return
    if (location.pathname === '/') {
      button.hide()
      return
    }
    const onBack = () => {
      // Открыли сразу по диплинку — истории нет, возвращаемся на главную.
      const idx = (window.history.state as { idx?: number } | null)?.idx ?? 0
      if (idx > 0) navigate(-1)
      else navigate('/', { replace: true })
    }
    button.onClick(onBack)
    button.show()
    return () => button.offClick(onBack)
  }, [location.pathname, navigate])
}
