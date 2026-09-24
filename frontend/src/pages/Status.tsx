import { Button, Spinner, Typography } from '@maxhub/max-ui'

export function LoadingScreen() {
  return (
    <main className="screen screen--center" aria-busy="true">
      <Spinner />
    </main>
  )
}

export function ErrorScreen({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <main className="screen screen--center">
      <Typography.Body variant="large">{message}</Typography.Body>
      {onRetry && (
        <Button size="medium" variant="secondary" onClick={onRetry}>
          Повторить
        </Button>
      )}
    </main>
  )
}
