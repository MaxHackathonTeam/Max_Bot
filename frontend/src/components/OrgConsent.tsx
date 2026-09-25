import { Button, Typography } from "@maxhub/max-ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { acceptConsents, type ConsentState, type Me } from "../api/client";
import { hasConsent } from "../app/profile";
import { FormErrors } from "./FormErrors";

/** Согласие на обработку данных организатора (и базовые документы, если их ещё нет). */
export function OrgConsent({ me }: { me: Me }) {
  const client = useQueryClient();
  const base = hasConsent(me);
  const docs: ConsentState["doc"][] = base
    ? ["org_pd"]
    : ["terms", "privacy", "org_pd"];
  const accept = useMutation({
    mutationFn: () => acceptConsents(docs),
    onSuccess: (updated) => client.setQueryData(["me"], updated),
  });
  return (
    <div className="notice stack">
      <Typography.Body variant="medium">
        Для работы от имени организации прими{" "}
        {!base && (
          <>
            <Link to="/legal/terms">условия</Link>,{" "}
            <Link to="/legal/privacy">политику ПДн</Link> и{" "}
          </>
        )}
        <Link to="/legal/org_pd">
          согласие на обработку данных организатора
        </Link>
        : ИНН, контакты и телефон для проверки.
      </Typography.Body>
      <Button
        size="medium"
        stretched
        loading={accept.isPending}
        onClick={() => accept.mutate()}
      >
        ✅ Принимаю
      </Button>
      <FormErrors error={accept.error} />
    </div>
  );
}
