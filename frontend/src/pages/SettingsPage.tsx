import { Button, CellList, CellSimple, Switch, Typography } from '@maxhub/max-ui'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { deleteMe, RADII, type Me } from '../api/client'
import { hasConsent, homeLocalityId, useLocality, useMe, useSetLocality, useUpdateMe } from '../app/profile'
import { Chip } from '../components/Chip'
import { ConsentPrompt } from '../components/ConsentPrompt'
import { InterestChips } from '../components/InterestChips'
import { LocalityPicker } from '../components/LocalityPicker'
import { writeLocal } from '../lib/storage'
import { ErrorScreen, LoadingScreen } from './Status'

function Settings({ me }: { me: Me }) {
  const client = useQueryClient()
  const navigate = useNavigate()
  const update = useUpdateMe()
  const setLocality = useSetLocality()
  const locality = useLocality(homeLocalityId(me))
  const [picking, setPicking] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const consent = hasConsent(me)

  const remove = useMutation({
    mutationFn: deleteMe,
    onSuccess: () => {
      writeLocal('afisha.locality_id', null)
      writeLocal('afisha.onboarded', null)
      // Сессию заводим заново: /me после удаления — «чистый» пользователь.
      client.clear()
      navigate('/', { replace: true })
    },
  })

  return (
    <main className="screen">
      <Typography.Headline variant="large-strong">⚙️ Настройки</Typography.Headline>

      <Typography.Label variant="medium-strong">Населённый пункт</Typography.Label>
      {picking ? (
        <LocalityPicker
          busy={setLocality.isPending}
          onPick={(l) => setLocality.mutate({ me, localityId: l.id }, { onSuccess: () => setPicking(false) })}
        />
      ) : (
        <CellList mode="island" filled>
          <CellSimple
            title={locality.data?.name ?? 'Не выбран'}
            subtitle="Изменить"
            showChevron
            onClick={() => setPicking(true)}
          />
        </CellList>
      )}

      {!consent && <ConsentPrompt />}

      <Typography.Label variant="medium-strong">Радиус поиска</Typography.Label>
      <div className="chips">
        {RADII.map((r) => (
          <Chip
            key={r}
            selected={me.radius_km === r}
            onClick={() => consent && update.mutate({ radius_km: r })}
          >
            {r} км
          </Chip>
        ))}
      </div>

      <Typography.Label variant="medium-strong">Интересы</Typography.Label>
      <InterestChips
        selected={me.interests}
        onToggle={(slug) =>
          consent &&
          update.mutate({
            interests: me.interests.includes(slug)
              ? me.interests.filter((s) => s !== slug)
              : [...me.interests, slug],
          })
        }
      />

      <Typography.Label variant="medium-strong">Уведомления в боте</Typography.Label>
      <CellList mode="island" filled>
        <CellSimple
          title="Напоминания о «Пойду»"
          subtitle="За сутки и за 2 часа, кроме тихих часов 22:00–09:00"
          after={
            <Switch
              checked={me.notify_reminders}
              disabled={!consent}
              onChange={(e) => update.mutate({ notify_reminders: e.target.checked })}
              aria-label="Напоминания"
            />
          }
        />
        <CellSimple
          title="Дайджест «На выходные»"
          subtitle="По четвергам, до 7 событий по интересам"
          after={
            <Switch
              checked={me.notify_digest}
              disabled={!consent}
              onChange={(e) => update.mutate({ notify_digest: e.target.checked })}
              aria-label="Дайджест"
            />
          }
        />
      </CellList>
      {update.isError && (
        <Typography.Body variant="small" className="error">
          {update.error.message}
        </Typography.Body>
      )}

      <Typography.Label variant="medium-strong">Документы</Typography.Label>
      <CellList mode="island" filled>
        <CellSimple asChild showChevron title="Условия использования">
          <Link to="/legal/terms" />
        </CellSimple>
        <CellSimple asChild showChevron title="Политика обработки персональных данных">
          <Link to="/legal/privacy" />
        </CellSimple>
      </CellList>

      {confirmDelete ? (
        <div className="notice notice--danger stack">
          <Typography.Body variant="medium">
            Удалим имя, место, интересы, «Пойду» и подписки. События, которые ты публиковал,
            останутся без привязки к тебе. Отменить нельзя.
          </Typography.Body>
          <div className="row">
            <Button size="medium" variant="secondary" onClick={() => setConfirmDelete(false)}>
              Отмена
            </Button>
            <Button
              size="medium"
              variant="destructive"
              stretched
              loading={remove.isPending}
              onClick={() => remove.mutate()}
            >
              Удалить мои данные
            </Button>
          </div>
          {remove.isError && (
            <Typography.Body variant="small" className="error">
              {remove.error.message}
            </Typography.Body>
          )}
        </div>
      ) : (
        <Button size="large" variant="ghost" onClick={() => setConfirmDelete(true)}>
          🗑 Удалить мои данные
        </Button>
      )}
    </main>
  )
}

/** Настройки (FR-ONB-4) и удаление данных (FR-ONB-5). */
export function SettingsPage() {
  const me = useMe()
  if (me.isPending) return <LoadingScreen />
  if (me.isError) return <ErrorScreen message={me.error.message} onRetry={() => void me.refetch()} />
  return <Settings me={me.data} />
}
