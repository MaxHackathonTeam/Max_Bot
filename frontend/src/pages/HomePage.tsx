import { CellList, CellSimple, Typography } from '@maxhub/max-ui'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { fetchMe } from '../api/client'
import { useSession } from '../app/session'
import { ErrorScreen, LoadingScreen } from './Status'

// Лента и онбординг — этап 2. Пока: приветствие по данным /me и ссылки на заглушки.
export function HomePage() {
  const me = useQuery({ queryKey: ['me'], queryFn: fetchMe })
  const { inMax } = useSession()

  if (me.isPending) return <LoadingScreen />
  if (me.isError) return <ErrorScreen message={me.error.message} onRetry={() => void me.refetch()} />

  const name = me.data.first_name
  return (
    <main className="screen">
      <Typography.Headline variant="large-strong" data-testid="greeting">
        {name ? `Привет, ${name}!` : 'Привет!'}
      </Typography.Headline>
      <Typography.Body variant="medium" className="muted">
        Скоро здесь появятся события рядом с тобой.
      </Typography.Body>
      {!inMax && (
        <Typography.Body variant="small" className="dev-badge">
          Режим разработки: вход без MAX (DEV_AUTH)
        </Typography.Body>
      )}
      <CellList mode="island" filled>
        <CellSimple asChild showChevron title="Настройки">
          <Link to="/settings" />
        </CellSimple>
      </CellList>
    </main>
  )
}
