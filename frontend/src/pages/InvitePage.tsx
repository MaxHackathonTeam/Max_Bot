import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BadgeCheck, CircleAlert, Users } from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import type { Me } from "../api/client";
import { acceptInvite, fetchInvite } from "../api/organizer";
import { hasOrgConsent } from "../app/profile";
import { FormErrors } from "../components/FormErrors";
import { OrgConsent } from "../components/OrgConsent";
import { RequireMax } from "../components/RequireMax";
import { formatDate } from "../lib/format";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { useToast } from "../ui/toastContext";
import { ErrorScreen, LoadingScreen } from "./Status";

function Invite({ me, token }: { me: Me; token: string }) {
  const navigate = useNavigate();
  const client = useQueryClient();
  const toast = useToast();
  const preview = useQuery({ queryKey: ["invite", token], queryFn: () => fetchInvite(token), retry: false });
  const accept = useMutation({
    mutationFn: () => acceptInvite(token),
    onSuccess: (res) => {
      void client.invalidateQueries({ queryKey: ["orgs"] });
      toast.show("Ты в команде");
      navigate(`/org/${res.org_id}`, { replace: true });
    },
  });

  if (preview.isPending) return <LoadingScreen />;
  if (preview.isError) return <ErrorScreen message={preview.error.message} onRetry={() => void preview.refetch()} />;
  const invite = preview.data;

  return (
    <main className="page page--narrow">
      <div className="stack stack--loose">
        <div className="page-head">
          <p className="eyebrow">Приглашение в команду</p>
          <h1 className="h1">{invite.org_name}</h1>
          <p className="muted">Тебя приглашают {invite.role === "owner" ? "владельцем" : "редактором"} событий.</p>
        </div>
        {invite.grants_verification && (
          <div className="notice notice--sun">
            <BadgeCheck size={18} aria-hidden />
            <span>После принятия организация станет проверенной.</span>
          </div>
        )}
        {!invite.valid ? (
          <div className="notice notice--danger">
            <CircleAlert size={18} aria-hidden />
            <span>{invite.reason ?? "Приглашение больше не действует."}</span>
          </div>
        ) : hasOrgConsent(me) ? (
          <div className="stack">
            <p className="small muted">Действует до {formatDate(invite.expires_at)}</p>
            <Button variant="primary" size="lg" block loading={accept.isPending} icon={<Users size={18} aria-hidden />} onClick={() => accept.mutate()}>
              Принять приглашение
            </Button>
            <FormErrors error={accept.error} />
          </div>
        ) : (
          <Card>
            <OrgConsent me={me} />
          </Card>
        )}
      </div>
    </main>
  );
}

/** Приглашение в команду (inv_<token>). */
export function InvitePage() {
  const token = useParams().token ?? "";
  return (
    <RequireMax title="Приглашение в команду" text="Чтобы принять приглашение, войди через MAX — так мы узнаем, кого добавить в команду.">
      {(me) => <Invite me={me} token={token} />}
    </RequireMax>
  );
}
