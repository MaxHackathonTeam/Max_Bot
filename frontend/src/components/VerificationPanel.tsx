import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BadgeCheck, CircleAlert, CircleCheck, CircleMinus, CircleX, Hourglass, RefreshCw, Smartphone } from "lucide-react";
import { useState, type ReactNode } from "react";
import {
  fetchVerification,
  recheckVerification,
  startVerification,
  type Org,
  type StepStatus,
  type Verification,
} from "../api/organizer";
import { formatDate } from "../lib/format";
import { ErrorBlock } from "../pages/Status";
import { Button } from "../ui/Button";
import { Chip } from "../ui/Chip";
import { Field, Input, Textarea } from "../ui/Field";
import { ListRow } from "../ui/ListRow";
import { Loading, Skeleton } from "../ui/Skeleton";
import { useToast } from "../ui/toastContext";
import { FormErrors } from "./FormErrors";

const STEP_ICON: Record<StepStatus, ReactNode> = {
  ok: <CircleCheck size={18} color="var(--green)" aria-label="Готово" />,
  failed: <CircleX size={18} color="var(--danger)" aria-label="Не прошло" />,
  pending: <Hourglass size={18} color="var(--ink-soft)" aria-label="Ждём" />,
  skipped: <CircleMinus size={18} color="var(--ink-faint)" aria-label="Пропущено" />,
};

function Steps({ request }: { request: Verification }) {
  return (
    <div className="list">
      {request.steps.map((s) => (
        <ListRow key={s.code} icon={STEP_ICON[s.status]} title={s.title} subtitle={s.message ?? undefined} />
      ))}
    </div>
  );
}

function StartForm({ org, onStarted }: { org: Org; onStarted: (v: Verification) => void }) {
  const [method, setMethod] = useState<"registry_auto" | "manual">("registry_auto");
  const [inn, setInn] = useState(org.inn ?? "");
  const [site, setSite] = useState(org.website ?? "");
  const [comment, setComment] = useState("");
  const start = useMutation({
    mutationFn: () =>
      startVerification(
        org.id,
        method === "registry_auto"
          ? { method, inn: inn.trim(), site_url: site.trim() }
          : { method, comment: comment.trim() || null },
      ),
    onSuccess: onStarted,
  });
  const autoReady = /^(\d{10}|\d{12})$/.test(inn.trim()) && /^https:\/\/\S+$/.test(site.trim());
  return (
    <div className="stack">
      <div className="chips" role="group" aria-label="Способ проверки">
        <Chip pressed={method === "registry_auto"} onClick={() => setMethod("registry_auto")}>
          По ИНН и сайту
        </Chip>
        <Chip pressed={method === "manual"} onClick={() => setMethod("manual")}>
          Через администратора
        </Chip>
      </div>
      {method === "registry_auto" ? (
        <>
          <p className="small muted">
            Проверим реквизиты, попросим подтвердить телефон в боте и найдём проверочный код на официальном сайте или
            странице ВК организации.
          </p>
          <Field label="ИНН">
            {(p) => (
              <Input {...p} inputMode="numeric" value={inn} onChange={(e) => setInn(e.target.value.replace(/\D/g, "").slice(0, 12))} />
            )}
          </Field>
          <Field label="Сайт или страница ВК">
            {(p) => <Input {...p} type="url" placeholder="https://" value={site} onChange={(e) => setSite(e.target.value)} />}
          </Field>
        </>
      ) : (
        <>
          <p className="small muted">
            Администратор свяжется с тобой и проверит вручную. Напиши, как с тобой связаться и чем подтвердить связь с
            организацией.
          </p>
          <Field label="Комментарий для администратора">
            {(p) => <Textarea {...p} rows={4} value={comment} onChange={(e) => setComment(e.target.value)} maxLength={1000} />}
          </Field>
        </>
      )}
      <FormErrors error={start.error} />
      <Button
        variant="primary"
        size="lg"
        block
        disabled={method === "registry_auto" && !autoReady}
        loading={start.isPending}
        onClick={() => start.mutate()}
      >
        Отправить на проверку
      </Button>
    </div>
  );
}

/** Экран верификации (§5.3): способ B по шагам или C через администратора. */
export function VerificationPanel({ org }: { org: Org }) {
  const client = useQueryClient();
  const toast = useToast();
  const key = ["verification", org.id];
  const query = useQuery({ queryKey: key, queryFn: () => fetchVerification(org.id) });
  const [again, setAgain] = useState(false);
  const recheck = useMutation({
    mutationFn: () => recheckVerification(org.id),
    onSuccess: (v) => {
      client.setQueryData(key, v);
      toast.show("Проверили ещё раз");
    },
  });
  const onStarted = (v: Verification) => {
    setAgain(false);
    client.setQueryData(key, v);
    toast.show("Заявка на проверку отправлена");
    void client.invalidateQueries({ queryKey: ["org", org.id] });
  };

  if (org.verified) {
    return (
      <div className="notice">
        <BadgeCheck size={18} aria-hidden />
        <span>
          Организация проверена{org.verified_at ? ` ${formatDate(org.verified_at)}` : ""}. События сразу попадают в
          «Официальные» с отметкой «Организатор проверен».
        </span>
      </div>
    );
  }
  if (query.isPending)
    return (
      <Loading>
        <Skeleton height={120} radius={14} />
      </Loading>
    );
  if (query.isError) return <ErrorBlock message={query.error.message} onRetry={() => void query.refetch()} />;

  const request = query.data;
  if (!request || again) return <StartForm org={org} onStarted={onStarted} />;

  const waitUntil = request.next_attempt_at ? new Date(request.next_attempt_at) : null;
  const canRecheck = request.method === "registry_auto" && request.status === "pending";
  const phonePending = request.steps.some((s) => s.code === "phone" && s.status === "pending");
  return (
    <div className="stack">
      {request.code && request.status === "pending" && (
        <div className="card card--sun stack">
          <p>Размести этот код на странице организации:</p>
          <p className="code-display">{request.code}</p>
          <p className="small muted">{request.site_url} — в тексте страницы, можно в подвале. После проверки код можно удалить.</p>
        </div>
      )}
      {phonePending && (
        <div className="notice notice--sun">
          <Smartphone size={18} aria-hidden />
          <span>Открой чат с ботом и нажми «Подтвердить телефон» — это твой собственный контакт MAX.</span>
        </div>
      )}
      <Steps request={request} />
      {request.decision_reason && (
        <div className="notice notice--danger">
          <CircleAlert size={18} aria-hidden />
          <span>{request.decision_reason}</span>
        </div>
      )}
      {canRecheck && (
        <div>
          <Button variant="secondary" loading={recheck.isPending} icon={<RefreshCw size={16} aria-hidden />} onClick={() => recheck.mutate()}>
            Проверить сайт ещё раз
          </Button>
        </div>
      )}
      {waitUntil && waitUntil > new Date() && (
        <p className="small muted">
          Повтор — не раньше {waitUntil.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}
        </p>
      )}
      <FormErrors error={recheck.error} />
      {["rejected", "revoked"].includes(request.status) && (
        <div>
          <Button variant="primary" onClick={() => setAgain(true)}>
            Подать заявку заново
          </Button>
        </div>
      )}
    </div>
  );
}
