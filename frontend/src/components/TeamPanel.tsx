import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Crown, UserPlus, UserRound } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { createInvite, fetchMembers, removeMember, type Invite, type Org } from "../api/organizer";
import { shareContent } from "../bridge/actions";
import { ErrorBlock } from "../pages/Status";
import { formatDate } from "../lib/format";
import { Button } from "../ui/Button";
import { ListRow } from "../ui/ListRow";
import { Loading, Skeleton } from "../ui/Skeleton";
import { useToast } from "../ui/toastContext";
import { FormErrors } from "./FormErrors";

const ROLE = { owner: "Владелец", editor: "Редактор" };

/** Команда организации: участники, выход и приглашения (только владелец). */
export function TeamPanel({ org }: { org: Org }) {
  const client = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  const members = useQuery({ queryKey: ["members", org.id], queryFn: () => fetchMembers(org.id) });
  const isOwner = org.my_role === "owner";

  const remove = useMutation({
    mutationFn: (userId: number) => removeMember(org.id, userId),
    onSuccess: (_, userId) => {
      const me = members.data?.find((m) => m.is_me);
      if (me?.user_id === userId) {
        void client.invalidateQueries({ queryKey: ["orgs"] });
        toast.show("Готово: тебя больше нет в команде");
        navigate("/org/0", { replace: true });
      } else {
        toast.show("Участник убран из команды");
        void members.refetch();
      }
    },
  });
  const invite = useMutation({
    mutationFn: () => createInvite(org.id, "editor"),
    onSuccess: async (inv: Invite) => {
      const link = inv.url ?? inv.payload;
      const result = await shareContent({
        text: `Приглашение в команду «${org.name}» в «Афише рядом»`,
        maxLink: inv.url,
        webLink: link,
      });
      if (result === "copied") toast.show("Ссылка-приглашение скопирована");
    },
  });

  return (
    <div className="stack">
      {members.isPending && (
        <Loading>
          <Skeleton height={56} radius={10} />
        </Loading>
      )}
      {members.isError && <ErrorBlock message={members.error.message} onRetry={() => void members.refetch()} />}
      {members.data && (
        <div className="list">
          {members.data.map((m) => (
            <ListRow
              key={m.user_id}
              icon={m.role === "owner" ? <Crown size={18} aria-hidden /> : <UserRound size={18} aria-hidden />}
              title={`${m.name}${m.is_me ? " (ты)" : ""}`}
              subtitle={`${ROLE[m.role]} · с ${formatDate(m.joined_at)}`}
              after={
                (isOwner && !m.is_me) || (m.is_me && m.role === "editor") ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    loading={remove.isPending && remove.variables === m.user_id}
                    onClick={() => remove.mutate(m.user_id)}
                  >
                    {m.is_me ? "Выйти" : "Убрать"}
                  </Button>
                ) : undefined
              }
            />
          ))}
        </div>
      )}
      <FormErrors error={remove.error} />
      {isOwner && (
        <>
          <div>
            <Button variant="secondary" loading={invite.isPending} icon={<UserPlus size={18} aria-hidden />} onClick={() => invite.mutate()}>
              Пригласить редактора
            </Button>
          </div>
          {invite.data && (
            <div className="notice">
              <p className="small">
                Ссылка действует до {formatDate(invite.data.expires_at)}:{" "}
                <span className="pre-line" style={{ overflowWrap: "anywhere" }}>
                  {invite.data.url ?? invite.data.payload}
                </span>
              </p>
            </div>
          )}
          <FormErrors error={invite.error} />
        </>
      )}
    </div>
  );
}
