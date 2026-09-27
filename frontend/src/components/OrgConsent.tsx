import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";
import { acceptConsents, type ConsentState, type Me } from "../api/client";
import { hasConsent } from "../app/profile";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { FormErrors } from "./FormErrors";

/** Согласие на обработку данных организатора (и базовые документы, если их ещё нет). */
export function OrgConsent({ me }: { me: Me }) {
  const client = useQueryClient();
  const base = hasConsent(me);
  const docs: ConsentState["doc"][] = base ? ["org_pd"] : ["terms", "privacy", "org_pd"];
  const accept = useMutation({
    mutationFn: () => acceptConsents(docs),
    onSuccess: (updated) => client.setQueryData(["me"], updated),
  });
  return (
    <Card tone="sun" className="stack">
      <div className="row">
        <ShieldCheck size={20} aria-hidden />
        <h2 className="h3">Нужно согласие</h2>
      </div>
      <p>
        Для работы от имени организации прими{" "}
        {!base && (
          <>
            <Link className="text-link" to="/legal/terms">
              условия
            </Link>
            ,{" "}
            <Link className="text-link" to="/legal/privacy">
              политику ПДн
            </Link>{" "}
            и{" "}
          </>
        )}
        <Link className="text-link" to="/legal/org_pd">
          согласие на обработку данных организатора
        </Link>
        : ИНН, контакты и телефон для проверки.
      </p>
      <Button variant="primary" block loading={accept.isPending} onClick={() => accept.mutate()}>
        Принимаю
      </Button>
      <FormErrors error={accept.error} />
    </Card>
  );
}
