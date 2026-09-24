import { useState } from 'react'
import type { Me } from '../api/client'
import { hasConsent, homeLocalityId, useMe } from '../app/profile'
import { readLocal, writeLocal } from '../lib/storage'
import { FeedPage } from './FeedPage'
import { OnboardingPage } from './OnboardingPage'
import { ErrorScreen, LoadingScreen } from './Status'

const ONBOARDED = 'afisha.onboarded'

function needsOnboarding(me: Me): boolean {
  if (homeLocalityId(me) === null) return true
  // Отказ от согласия («Пока только посмотреть») запоминаем на устройстве.
  return !hasConsent(me) && readLocal(ONBOARDED) !== '1'
}

/** Главная: онбординг, пока не выбран населённый пункт, дальше — лента. */
export function HomePage() {
  const me = useMe()
  const [finished, setFinished] = useState(false)

  if (me.isPending) return <LoadingScreen />
  if (me.isError) return <ErrorScreen message={me.error.message} onRetry={() => void me.refetch()} />

  const localityId = homeLocalityId(me.data)
  if (localityId === null || (!finished && needsOnboarding(me.data))) {
    return (
      <OnboardingPage
        me={me.data}
        localityId={localityId}
        onFinish={() => {
          writeLocal(ONBOARDED, '1')
          setFinished(true)
        }}
      />
    )
  }
  return <FeedPage me={me.data} localityId={localityId} />
}
