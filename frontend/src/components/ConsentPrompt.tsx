import { Button, Typography } from '@maxhub/max-ui'
import { Link } from 'react-router-dom'
import { useAcceptConsents } from '../app/profile'

/** Согласие с условиями и политикой ПДн (FR-ONB-1). */
export function ConsentPrompt({ onDone, onSkip }: { onDone?: () => void; onSkip?: () => void }) {
  const accept = useAcceptConsents()
  return (
    <div className="stack">
      <Typography.Body variant="medium">
        Чтобы сохранять события и получать напоминания, прими{' '}
        <Link to="/legal/terms">условия использования</Link> и{' '}
        <Link to="/legal/privacy">политику обработки персональных данных</Link>.
      </Typography.Body>
      <Button
        size="large"
        stretched
        loading={accept.isPending}
        onClick={() => accept.mutate(undefined, { onSuccess: () => onDone?.() })}
      >
        ✅ Принимаю
      </Button>
      {onSkip && (
        <Button size="large" variant="ghost" stretched onClick={onSkip}>
          Пока только посмотреть
        </Button>
      )}
      {accept.isError && (
        <Typography.Body variant="small" className="error">
          {accept.error.message}
        </Typography.Body>
      )}
    </div>
  )
}
