import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, CircleCheck, CircleX, Undo2 } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { decideEvent, fetchAdminEvent, type AdminEventCard, type EventAction } from "../api/admin";
import { STATUS_LABELS } from "../api/organizer";
import { EventCardView } from "../components/EventCardView";
import { FormErrors } from "../components/FormErrors";
import { manageToCard } from "../lib/eventForm";
import { formatDate } from "../lib/format";
import { actorLabel, auditLabel, composeReason, REASON_TEMPLATES, verdictLabel } from "../lib/moderation";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { Chip } from "../ui/Chip";
import { Field, Textarea } from "../ui/Field";
import { Loading, Skeleton } from "../ui/Skeleton";
import { useToast } from "../ui/toastContext";
import { Summary } from "./DraftPage";
import { AdminOnly } from "./ModerationPage";
import { ErrorBlock, ErrorScreen } from "./Status";

const DONE: Record<EventAction, string> = {
  approve: "Опубликовано — автору ушло уведомление",
  reject: "Отклонено — автор получит причину в боте",
  return: "Вернули на доработку — автор получит комментарий",
};

/** Решение: причина обязательна для отказа и возврата (как в services/moderation.py). */
function Decision({ id, status }: { id: number; status: string | null }) {
  const client = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  const [template, setTemplate] = useState<string | null>(null);
  const [comment, setComment] = useState("");
  const reason = composeReason(template, comment);
  const decide = useMutation({
    mutationFn: (action: EventAction) => decideEvent(id, action, action === "approve" ? null : reason),
    onSuccess: (_, action) => {
      void client.invalidateQueries({ queryKey: ["admin-queue"] });
      void client.invalidateQueries({ queryKey: ["admin-event", id] });
      toast.show(DONE[action], "success");
      navigate("/moderation");
    },
  });
  const can = (action: EventAction) =>
    status === null ||
    {
      approve: ["pending", "hidden", "rejected"],
      reject: ["pending", "hidden", "published"],
      return: ["pending", "hidden"],
    }[action].includes(status);
  const busy = (action: EventAction) => decide.isPending && decide.variables === action;
  return (
    <Card className="stack">
      <h2 className="h2">Решение</h2>
      <div className="chips" role="group" aria-label="Шаблон причины">
        {REASON_TEMPLATES.map((t) => (
          <Chip key={t} pressed={template === t} onClick={() => setTemplate(template === t ? null : t)}>
            {t}
          </Chip>
        ))}
      </div>
      <Field label="Комментарий автору" hint="Для отказа и возврата нужен шаблон или комментарий.">
        {(p) => <Textarea {...p} rows={3} maxLength={900} value={comment} onChange={(e) => setComment(e.target.value)} />}
      </Field>
      <FormErrors error={decide.error} />
      <div className="row row--wrap">
        <Button
          variant="primary"
          disabled={!can("approve") || decide.isPending}
          loading={busy("approve")}
          icon={<CircleCheck size={18} aria-hidden />}
          onClick={() => decide.mutate("approve")}
        >
          Одобрить
        </Button>
        <Button
          variant="secondary"
          disabled={!can("return") || !reason || decide.isPending}
          loading={busy("return")}
          icon={<Undo2 size={18} aria-hidden />}
          onClick={() => decide.mutate("return")}
        >
          Вернуть на доработку
        </Button>
        <Button
          variant="danger"
          disabled={!can("reject") || !reason || decide.isPending}
          loading={busy("reject")}
          icon={<CircleX size={18} aria-hidden />}
          onClick={() => decide.mutate("reject")}
        >
          Отклонить
        </Button>
      </div>
    </Card>
  );
}

function CardDetails({ card }: { card: AdminEventCard }) {
  const { event, author, flags, decisions, history } = card;
  return (
    <>
      <div className="feed__grid feed__grid--one">
        <EventCardView card={manageToCard(event)} />
      </div>
      <Summary event={event} />
      <Card className="stack stack--tight">
        <h2 className="h2">Подробности</h2>
        <p className="small">
          {event.trust_tier === "official" ? "Официальные" : "От жителей"}
          {event.org_name ? ` · ${event.org_name}${event.org_verified ? " (проверена)" : ""}` : ""}
        </p>
        <p className="small">
          Автор: {author ? (author.name ?? `пользователь #${author.id}`) : "неизвестен"}
          {author?.max_user_id ? ` · MAX ${author.max_user_id}` : ""}
        </p>
        {event.contacts && <p className="small">Контакты: {event.contacts}</p>}
        {event.ticket_url && <p className="small">Билеты: {event.ticket_url}</p>}
        {event.online_url && <p className="small">Трансляция: {event.online_url}</p>}
        {event.description && <p className="small pre-line">{event.description}</p>}
      </Card>
      <Card className="stack stack--tight">
        <h2 className="h2">Флаги правил</h2>
        {flags.length === 0 ? (
          <p className="small muted">Правила ничего не нашли.</p>
        ) : (
          flags.map((f) => (
            <p key={`${f.code}-${f.field}`} className={`notice small ${f.kind === "content" ? "notice--danger" : "notice--sun"}`}>
              <CircleAlert size={16} aria-hidden />
              <span>{f.message}</span>
            </p>
          ))
        )}
      </Card>
      <Card className="stack stack--tight">
        <h2 className="h2">Решения</h2>
        {decisions.length === 0 ? (
          <p className="small muted">Решений ещё не было.</p>
        ) : (
          <ul className="stack stack--tight small">
            {decisions.map((d) => (
              <li key={d.id}>
                {formatDate(d.created_at)} · {actorLabel(d.actor_type)}: {verdictLabel(d.verdict)}
                {d.reasons && d.reasons.length > 0 ? ` — ${d.reasons.join("; ")}` : ""}
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card className="stack stack--tight">
        <h2 className="h2">История</h2>
        <ul className="stack stack--tight small">
          {history.map((h) => (
            <li key={h.id}>
              {formatDate(h.created_at)} · {actorLabel(h.actor_type)}: {auditLabel(h.action, h.diff)}
            </li>
          ))}
        </ul>
      </Card>
    </>
  );
}

function ModerationEvent({ id }: { id: number }) {
  const card = useQuery({ queryKey: ["admin-event", id], queryFn: () => fetchAdminEvent(id), retry: false });
  const event = card.data?.event;
  return (
    <main className="page page--narrow">
      <div className="stack stack--loose">
        <div className="page-head">
          <p className="eyebrow">
            <Link to="/moderation">Модерация</Link> · заявка #{id}
          </p>
          <h1 className="h1">{event?.title || "Заявка"}</h1>
          {event && (
            <div className="row row--wrap">
              <Badge tone={event.status === "pending" ? "accent" : "plain"}>
                {STATUS_LABELS[event.status] ?? event.status}
              </Badge>
              <span className="small muted">подано {formatDate(event.updated_at)}</span>
            </div>
          )}
        </div>
        {card.isPending && (
          <Loading>
            <Skeleton height={180} radius={14} />
            <Skeleton height={120} radius={14} />
          </Loading>
        )}
        {card.isError && <ErrorBlock message={card.error.message} onRetry={() => void card.refetch()} />}
        <Decision id={id} status={event?.status ?? null} />
        {card.isSuccess && <CardDetails card={card.data} />}
      </div>
    </main>
  );
}

/** /moderation/:id — карточка заявки со всеми полями, флагами, историей и решением. */
export function ModerationEventPage() {
  const id = Number(useParams().id);
  if (!Number.isInteger(id) || id <= 0) return <ErrorScreen message="Заявка не найдена." />;
  return <AdminOnly>{() => <ModerationEvent id={id} />}</AdminOnly>;
}
