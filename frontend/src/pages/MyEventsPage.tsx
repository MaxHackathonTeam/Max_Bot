import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarPlus, CircleAlert, EyeOff, PencilLine, Send } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import type { Me } from "../api/client";
import { cancelEvent, fetchMyEvents, submitEvent, type MyEventItem } from "../api/organizer";
import { hasConsent } from "../app/profile";
import { ConsentPrompt } from "../components/ConsentPrompt";
import { FormErrors } from "../components/FormErrors";
import { StatusChips } from "../components/ManagedEventList";
import { RequireMax } from "../components/RequireMax";
import { authorStatus } from "../lib/authorStatus";
import { formatWhen } from "../lib/format";
import { Badge } from "../ui/Badge";
import { Button, ButtonLink } from "../ui/Button";
import { Card } from "../ui/Card";
import { EmptyState } from "../ui/EmptyState";
import { Loading, Skeleton } from "../ui/Skeleton";
import { useToast } from "../ui/toastContext";
import { ErrorBlock } from "./Status";

function MyEventRow({ event }: { event: MyEventItem }) {
  const client = useQueryClient();
  const toast = useToast();
  const refresh = () => void client.invalidateQueries({ queryKey: ["my-events"] });
  const resubmit = useMutation({
    mutationFn: () => submitEvent(event.id),
    onSuccess: (e) => {
      refresh();
      toast.show(e.status === "published" ? "Опубликовано" : "Отправили на проверку — итог придёт в бот", "success");
    },
  });
  const unpublish = useMutation({
    mutationFn: () => cancelEvent(event.id),
    onSuccess: () => {
      refresh();
      toast.show("Снято с публикации", "success");
    },
  });
  const status = authorStatus(event);
  const when = event.next_starts_at ? formatWhen(event.next_starts_at, event.timezone) : "без будущих сеансов";
  return (
    <Card className="stack stack--tight">
      <div className="row row--wrap">
        <Badge tone={status.tone}>{status.label}</Badge>
        <span className="small muted">{event.trust_tier === "official" ? "Официальные" : "От жителей"}</span>
      </div>
      <Link to={event.status === "published" ? `/event/${event.id}` : `/draft/${event.id}`} className="h3">
        {event.title || "Без названия"}
      </Link>
      <p className="small muted">{when}</p>
      {status.reason && (
        <p className="notice notice--danger small">
          <CircleAlert size={16} aria-hidden />
          <span>Причина: {status.reason}</span>
        </p>
      )}
      <FormErrors error={resubmit.error ?? unpublish.error} />
      <div className="row row--wrap">
        {status.editable && (
          <ButtonLink to={`/draft/${event.id}`} variant="secondary" size="sm" icon={<PencilLine size={16} aria-hidden />}>
            Редактировать
          </ButtonLink>
        )}
        {status.editable && (
          <Button size="sm" loading={resubmit.isPending} icon={<Send size={16} aria-hidden />} onClick={() => resubmit.mutate()}>
            {status.resubmit ? "Отправить снова" : "Отправить на проверку"}
          </Button>
        )}
        {status.cancellable && (
          <Button
            variant="ghost"
            size="sm"
            loading={unpublish.isPending}
            icon={<EyeOff size={16} aria-hidden />}
            onClick={() => unpublish.mutate()}
          >
            {event.status === "pending" ? "Отозвать" : "Снять с публикации"}
          </Button>
        )}
      </div>
    </Card>
  );
}

function MyEvents({ me }: { me: Me }) {
  const [status, setStatus] = useState<string | null>(null);
  const consent = hasConsent(me);
  const events = useQuery({ queryKey: ["my-events", status], queryFn: () => fetchMyEvents(status), enabled: consent });
  return (
    <main className="page page--narrow">
      <div className="stack stack--loose">
        <div className="page-head">
          <p className="eyebrow">Кабинет</p>
          <h1 className="h1">Мои афиши</h1>
        </div>
        {!consent ? (
          <Card>
            <ConsentPrompt />
          </Card>
        ) : (
          <>
            <div className="row row--wrap">
              <ButtonLink to="/new" variant="primary" icon={<CalendarPlus size={18} aria-hidden />}>
                Добавить афишу
              </ButtonLink>
            </div>
            <StatusChips value={status} onChange={setStatus} />
            {events.isPending && (
              <Loading>
                <Skeleton height={120} radius={14} />
                <Skeleton height={120} radius={14} />
              </Loading>
            )}
            {events.isError && <ErrorBlock message={events.error.message} onRetry={() => void events.refetch()} />}
            {events.isSuccess && events.data.length === 0 && (
              <EmptyState
                icon={<CalendarPlus size={28} aria-hidden />}
                title="Афиш пока нет"
                text="Добавь событие — жители увидят его после проверки."
              />
            )}
            {events.isSuccess && events.data.map((e) => <MyEventRow key={e.id} event={e} />)}
          </>
        )}
      </div>
    </main>
  );
}

/** /my — афиши автора: статусы, причина отказа, правка, повторная отправка, снятие. */
export function MyEventsPage() {
  return (
    <RequireMax title="Мои афиши" text="Войди через MAX, чтобы видеть свои афиши и ответы модерации.">
      {(me) => <MyEvents me={me} />}
    </RequireMax>
  );
}
