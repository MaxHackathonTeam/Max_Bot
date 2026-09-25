import { Button, Typography } from "@maxhub/max-ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { acceptInvite, fetchInvite } from "../api/organizer";
import { hasOrgConsent, useMe } from "../app/profile";
import { FormErrors } from "../components/FormErrors";
import { OrgConsent } from "../components/OrgConsent";
import { formatDate } from "../lib/format";
import { ErrorScreen, LoadingScreen } from "./Status";

/** Приглашение в команду (inv_<token>). */
export function InvitePage() {
  const token = useParams().token ?? "";
  const navigate = useNavigate();
  const client = useQueryClient();
  const me = useMe();
  const preview = useQuery({
    queryKey: ["invite", token],
    queryFn: () => fetchInvite(token),
    retry: false,
  });
  const accept = useMutation({
    mutationFn: () => acceptInvite(token),
    onSuccess: (res) => {
      void client.invalidateQueries({ queryKey: ["orgs"] });
      navigate(`/org/${res.org_id}`, { replace: true });
    },
  });

  if (preview.isPending || me.isPending) return <LoadingScreen />;
  if (preview.isError) return <ErrorScreen message={preview.error.message} />;
  if (me.isError) return <ErrorScreen message={me.error.message} />;
  const invite = preview.data;

  return (
    <main className="screen">
      <Typography.Headline variant="large-strong">
        🤝 Приглашение в команду
      </Typography.Headline>
      <Typography.Body variant="large">
        «{invite.org_name}» приглашает тебя{" "}
        {invite.role === "owner" ? "владельцем" : "редактором"} событий.
      </Typography.Body>
      {invite.grants_verification && (
        <Typography.Body variant="small" className="notice">
          После принятия организация станет проверенной.
        </Typography.Body>
      )}
      {!invite.valid ? (
        <Typography.Body variant="medium" className="notice notice--danger">
          {invite.reason ?? "Приглашение больше не действует."}
        </Typography.Body>
      ) : hasOrgConsent(me.data) ? (
        <>
          <Typography.Body variant="small" className="muted">
            Действует до {formatDate(invite.expires_at)}
          </Typography.Body>
          <Button
            size="large"
            stretched
            loading={accept.isPending}
            onClick={() => accept.mutate()}
          >
            Принять
          </Button>
          <FormErrors error={accept.error} />
        </>
      ) : (
        <OrgConsent me={me.data} />
      )}
    </main>
  );
}
