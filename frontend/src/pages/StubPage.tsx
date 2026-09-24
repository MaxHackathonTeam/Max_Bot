import { Typography } from '@maxhub/max-ui'
import { useParams } from 'react-router-dom'

/** Заглушка экрана: наполнение — на этапах 2–4. */
export function StubPage({ title }: { title: string }) {
  const { id, token } = useParams()
  const ref = id ?? token
  return (
    <main className="screen">
      <Typography.Headline variant="medium-strong">{title}</Typography.Headline>
      {ref && (
        <Typography.Body variant="small" className="muted">
          № {ref}
        </Typography.Body>
      )}
      <Typography.Body variant="medium">Этот экран скоро появится.</Typography.Body>
    </main>
  )
}
