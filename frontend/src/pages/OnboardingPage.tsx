import { Button, Typography } from '@maxhub/max-ui'
import { useState } from 'react'
import type { Me } from '../api/client'
import { hasConsent, useSetLocality, useUpdateMe } from '../app/profile'
import { ConsentPrompt } from '../components/ConsentPrompt'
import { InterestChips } from '../components/InterestChips'
import { LocalityPicker } from '../components/LocalityPicker'

type Step = 'consent' | 'locality' | 'interests'

/** Онбординг (FR-ONB-1…3): согласие → населённый пункт → интересы. */
export function OnboardingPage({
  me,
  localityId,
  onFinish,
}: {
  me: Me
  localityId: number | null
  onFinish: () => void
}) {
  const [step, setStep] = useState<Step>(hasConsent(me) ? 'locality' : 'consent')
  const [interests, setInterests] = useState<string[]>(me.interests)
  const setLocality = useSetLocality()
  const update = useUpdateMe()
  const afterConsent = () => (localityId === null ? setStep('locality') : onFinish())

  return (
    <main className="screen">
      <Typography.Headline variant="large-strong">
        {step === 'consent' && '👋 Привет! Это «Афиша рядом»'}
        {step === 'locality' && '📍 Где ты живёшь?'}
        {step === 'interests' && '✨ Что тебе интересно?'}
      </Typography.Headline>

      {step === 'consent' && (
        <>
          <Typography.Body variant="medium" className="muted">
            Концерты, спектакли, мастер-классы и праздники в твоём городе или селе и рядом.
          </Typography.Body>
          <ConsentPrompt onDone={afterConsent} onSkip={afterConsent} />
        </>
      )}

      {step === 'locality' && (
        <>
          <Typography.Body variant="medium" className="muted">
            Покажу события в этом населённом пункте и в радиусе {me.radius_km} км.
          </Typography.Body>
          <LocalityPicker
            busy={setLocality.isPending}
            onPick={(l) =>
              setLocality.mutate(
                { me, localityId: l.id },
                // Интересы сохраняются в профиль — спрашиваем только при согласии.
                { onSuccess: () => (hasConsent(me) ? setStep('interests') : onFinish()) },
              )
            }
          />
        </>
      )}

      {step === 'interests' && (
        <>
          <Typography.Body variant="medium" className="muted">
            Отметь, что нравится, — будем учитывать в подборках. Можно пропустить.
          </Typography.Body>
          <InterestChips
            selected={interests}
            onToggle={(slug) =>
              setInterests((s) => (s.includes(slug) ? s.filter((x) => x !== slug) : [...s, slug]))
            }
          />
          <Button
            size="large"
            stretched
            loading={update.isPending}
            onClick={() => update.mutate({ interests }, { onSuccess: onFinish })}
          >
            Готово
          </Button>
        </>
      )}
    </main>
  )
}
