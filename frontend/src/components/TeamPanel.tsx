import { Button, CellList, CellSimple, Typography } from "@maxhub/max-ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  createInvite,
  fetchMembers,
  removeMember,
  type Invite,
  type Org,
} from "../api/organizer";
import { shareContent } from "../bridge/actions";
import { formatDate } from "../lib/format";
import { FormErrors } from "./FormErrors";

const ROLE = { owner: "Владелец", editor: "Редактор" };

/** Команда организации: участники, выход и приглашения (только владелец). */
export function TeamPanel({ org }: { org: Org }) {
  const client = useQueryClient();
  const navigate = useNavigate();
  const members = useQuery({
    queryKey: ["members", org.id],
    queryFn: () => fetchMembers(org.id),
  });
  const isOwner = org.my_role === "owner";

  const remove = useMutation({
    mutationFn: (userId: number) => removeMember(org.id, userId),
    onSuccess: (_, userId) => {
      const me = members.data?.find((m) => m.is_me);
      if (me?.user_id === userId) {
        void client.invalidateQueries({ queryKey: ["orgs"] });
        navigate("/org/0", { replace: true });
      } else void members.refetch();
    },
  });
  const invite = useMutation({
    mutationFn: () => createInvite(org.id, "editor"),
    onSuccess: async (inv: Invite) => {
      await shareContent(
        `Приглашение в команду «${org.name}» в «Афише рядом»`,
        inv.url,
      );
    },
  });

  return (
    <div className="stack">
      {members.isError && <FormErrors error={members.error} />}
      <CellList mode="island" filled>
        {(members.data ?? []).map((m) => (
          <CellSimple
            key={m.user_id}
            title={`${m.name}${m.is_me ? " (ты)" : ""}`}
            subtitle={`${ROLE[m.role]} · с ${formatDate(m.joined_at)}`}
            after={
              (isOwner && !m.is_me) || (m.is_me && m.role === "editor") ? (
                <Button
                  size="small"
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
      </CellList>
      <FormErrors error={remove.error} />
      {isOwner && (
        <>
          <Button
            size="large"
            variant="secondary"
            loading={invite.isPending}
            onClick={() => invite.mutate()}
          >
            ➕ Пригласить редактора
          </Button>
          {invite.data && (
            <Typography.Body variant="small" className="notice">
              Ссылка действует до {formatDate(invite.data.expires_at)}:{" "}
              <span className="pre-line">
                {invite.data.url ?? invite.data.payload}
              </span>
            </Typography.Body>
          )}
          <FormErrors error={invite.error} />
        </>
      )}
    </div>
  );
}
