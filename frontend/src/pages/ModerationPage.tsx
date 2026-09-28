import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, CircleCheck, CircleX, Flag, Inbox, ShieldCheck, Undo2 } from "lucide-react";
import { useState, type ReactNode } from "react";
import type { Me } from "../api/client";
import { decideVerification, fetchQueue, type QueueFilter, type QueueVerification } from "../api/admin";
import { FormErrors } from "../components/FormErrors";
import { RequireMax } from "../components/RequireMax";
import { formatDate } from "../lib/format";
import { composeReason, innValid } from "../lib/moderation";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { Chip } from "../ui/Chip";
import { EmptyState } from "../ui/EmptyState";
import { Field, Textarea } from "../ui/Field";
import { ListRow } from "../ui/ListRow";
import { Loading, Skeleton } from "../ui/Skeleton";
import { Tabs } from "../ui/Tabs";
import { useToast } from "../ui/toastContext";
import { ErrorBlock } from "./Status";

/** Раздел только для модераторов: права проверяет бэкенд, здесь — понятное сообщение вместо 403. */
export function AdminOnly({ children }: { children: (me: Me) => ReactNode }) {
  return (
    <RequireMax title="Модерация" text="Войди через MAX, чтобы открыть раздел модератора.">
      {(me) =>
        me.is_admin ? (
          children(me)
        ) : (
          <main className="page page--narrow">
            <EmptyState
              icon={<ShieldCheck size={28} aria-hidden />}
              title="Раздел только для модераторов"
              text="Если ты модератор, попроси администратора выдать права."
            />
          </main>
        )
      }
    </RequireMax>
  );
}

type Section = "events" | "orgs";

const SECTIONS: { value: Section; label: string }[] = [
  { value: "events", label: "События" },
  { value: "orgs", label: "Организации" },
];

const FILTERS: { value: QueueFilter; label: string }[] = [
  { value: "new", label: "Новые" },
  { value: "returned", label: "Возвращённые" },
  { value: "all", label: "Все" },
];

function QueueSkeleton() {
  return (
    <Loading>
      <Skeleton height={64} radius={14} />
      <Skeleton height={64} radius={14} />
      <Skeleton height={64} radius={14} />
    </Loading>
  );
}

function EventsQueue({ filter, onFilter }: { filter: QueueFilter; onFilter: (f: QueueFilter) => void }) {
  const queue = useQuery({ queryKey: ["admin-queue", filter], queryFn: () => fetchQueue(filter) });
  return (
    <div className="stack">
      <div className="chips chips--scroll" role="group" aria-label="Какие заявки показать">
        {FILTERS.map((f) => (
          <Chip key={f.value} pressed={filter === f.value} onClick={() => onFilter(f.value)}>
            {f.label}
          </Chip>
        ))}
      </div>
      <p className="small muted">Сначала те, что подали раньше.</p>
      {queue.isPending && <QueueSkeleton />}
      {queue.isError && <ErrorBlock message={queue.error.message} onRetry={() => void queue.refetch()} />}
      {queue.isSuccess && queue.data.events.length === 0 && (
        <EmptyState icon={<Inbox size={28} aria-hidden />} title="Очередь пуста" text="Новых заявок нет — можно выдохнуть." />
      )}
      {queue.isSuccess && queue.data.events.length > 0 && (
        <div className="list">
          {queue.data.events.map((e) => (
            <ListRow
              key={e.id}
              to={`/moderation/${e.id}`}
              icon={e.reports > 0 ? <Flag size={18} aria-hidden /> : e.returned ? <Undo2 size={18} aria-hidden /> : undefined}
              title={e.title || "Без названия"}
              subtitle={[
                e.org_name ?? "От жителей",
                e.status === "hidden" ? "скрыто по жалобам" : null,
                e.reports > 0 ? `жалоб: ${e.reports}` : null,
                e.returned ? "уже было у модератора" : null,
                `подано ${formatDate(e.updated_at)}`,
              ]
                .filter(Boolean)
                .join(" · ")}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function VerificationCard({ request }: { request: QueueVerification }) {
  const client = useQueryClient();
  const toast = useToast();
  const [comment, setComment] = useState("");
  const decide = useMutation({
    mutationFn: (approve: boolean) => decideVerification(request.id, approve, composeReason(null, comment)),
    onSuccess: (_, approve) => {
      void client.invalidateQueries({ queryKey: ["admin-queue"] });
      toast.show(approve ? "Организация проверена" : "Заявка отклонена", "success");
    },
  });
  const inn = request.inn;
  return (
    <Card className="stack">
      <div className="row row--between row--wrap">
        <h3 className="h3">{request.org_name}</h3>
        <span className="small muted">{formatDate(request.created_at)}</span>
      </div>
      <p className="small">
        {request.method === "registry_auto" ? "Проверка по реестру" : "Ручная проверка"}
        {request.site_url ? ` · ${request.site_url}` : ""}
      </p>
      {inn && (
        <p className="row row--wrap">
          <span>ИНН {inn}</span>
          {innValid(inn) ? (
            <Badge tone="verified" icon={<CircleCheck size={14} aria-hidden />}>
              Контрольная сумма сходится
            </Badge>
          ) : (
            <Badge tone="danger" icon={<CircleX size={14} aria-hidden />}>
              Контрольная сумма не сходится
            </Badge>
          )}
        </p>
      )}
      {request.steps.length > 0 && (
        <ul className="stack stack--tight small">
          {request.steps.map((s) => (
            <li key={s.code}>
              {s.status === "ok" ? "✅" : s.status === "failed" ? "❌" : "⏳"} {s.title}
              {s.message ? ` — ${s.message}` : ""}
            </li>
          ))}
        </ul>
      )}
      <Field label="Комментарий" hint="Обязателен при отказе — его увидит организатор.">
        {(p) => <Textarea {...p} rows={2} maxLength={1000} value={comment} onChange={(e) => setComment(e.target.value)} />}
      </Field>
      <FormErrors error={decide.error} />
      <div className="row row--wrap">
        <Button variant="primary" size="sm" loading={decide.isPending && decide.variables} onClick={() => decide.mutate(true)}>
          Подтвердить
        </Button>
        <Button
          variant="danger"
          size="sm"
          disabled={!comment.trim()}
          loading={decide.isPending && !decide.variables}
          onClick={() => decide.mutate(false)}
        >
          Отклонить
        </Button>
      </div>
    </Card>
  );
}

function OrgsQueue() {
  const queue = useQuery({ queryKey: ["admin-queue", "all"], queryFn: () => fetchQueue("all") });
  if (queue.isPending) return <QueueSkeleton />;
  if (queue.isError) return <ErrorBlock message={queue.error.message} onRetry={() => void queue.refetch()} />;
  if (queue.data.verifications.length === 0)
    return <EmptyState icon={<Building2 size={28} aria-hidden />} title="Заявок на проверку нет" />;
  return (
    <div className="stack">
      {queue.data.verifications.map((r) => (
        <VerificationCard key={r.id} request={r} />
      ))}
    </div>
  );
}

function Moderation() {
  const [section, setSection] = useState<Section>("events");
  const [filter, setFilter] = useState<QueueFilter>("new");
  const all = useQuery({ queryKey: ["admin-queue", "all"], queryFn: () => fetchQueue("all") });
  return (
    <main className="page page--narrow">
      <div className="stack stack--loose">
        <div className="page-head">
          <p className="eyebrow">Модератор</p>
          <h1 className="h1">Модерация</h1>
          {all.isSuccess && (
            <p className="muted" aria-live="polite">
              В очереди: событий — {all.data.events.length}, организаций — {all.data.verifications.length}
            </p>
          )}
        </div>
        <Tabs label="Раздел модерации" value={section} onChange={setSection} items={SECTIONS} />
        {section === "events" ? <EventsQueue filter={filter} onFilter={setFilter} /> : <OrgsQueue />}
      </div>
    </main>
  );
}

/** /moderation — очередь событий и заявок организаций. */
export function ModerationPage() {
  return <AdminOnly>{() => <Moderation />}</AdminOnly>;
}
