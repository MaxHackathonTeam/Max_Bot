import { Link } from "react-router-dom";
import { useAcceptConsents } from "../app/profile";
import { Button } from "../ui/Button";
import { FormErrors } from "./FormErrors";

/** Согласие с условиями и политикой ПДн (FR-ONB-1). */
export function ConsentPrompt({ onDone, onSkip }: { onDone?: () => void; onSkip?: () => void }) {
  const accept = useAcceptConsents();
  return (
    <div className="stack">
      <p>
        Чтобы сохранять события и получать напоминания, прими{" "}
        <Link className="text-link" to="/legal/terms">
          условия использования
        </Link>{" "}
        и{" "}
        <Link className="text-link" to="/legal/privacy">
          политику обработки персональных данных
        </Link>
        .
      </p>
      <Button variant="primary" size="lg" block loading={accept.isPending} onClick={() => accept.mutate(undefined, { onSuccess: () => onDone?.() })}>
        Принимаю
      </Button>
      {onSkip && (
        <Button variant="ghost" block onClick={onSkip}>
          Пока только посмотреть
        </Button>
      )}
      <FormErrors error={accept.error} />
    </div>
  );
}
