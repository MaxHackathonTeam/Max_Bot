import { useEffect, useState } from 'react'

type ApiState = 'loading' | 'ok' | 'fail'

// Заглушка этапа 0: проверяет, что мини-апп отдаётся и видит API через nginx.
export function App() {
  const [api, setApi] = useState<ApiState>('loading')

  useEffect(() => {
    fetch('/api/v1/health')
      .then((r) => setApi(r.ok ? 'ok' : 'fail'))
      .catch(() => setApi('fail'))
  }, [])

  return (
    <main className="stub">
      <h1>Афиша рядом</h1>
      <p>События рядом с тобой — скоро здесь.</p>
      <p className="muted" data-testid="api-status">
        API: {api === 'loading' ? 'проверяем…' : api === 'ok' ? 'доступен' : 'недоступен'}
      </p>
    </main>
  )
}
