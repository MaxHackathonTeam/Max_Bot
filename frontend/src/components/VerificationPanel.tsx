import {
  Button,
  CellList,
  CellSimple,
  Input,
  Textarea,
  Typography,
} from "@maxhub/max-ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  fetchVerification,
  recheckVerification,
  startVerification,
  type Org,
  type StepStatus,
  type Verification,
} from "../api/organizer";
import { formatDate } from "../lib/format";
import { Chip } from "./Chip";
import { FormErrors } from "./FormErrors";

const STEP_ICON: Record<StepStatus, string> = {
  ok: "✅",
  failed: "❌",
  pending: "⏳",
  skipped: "➖",
};

function Steps({ request }: { request: Verification }) {
  return (
    <CellList mode="island" filled>
      {request.steps.map((s) => (
        <CellSimple
          key={s.code}
          title={`${STEP_ICON[s.status]} ${s.title}`}
          subtitle={s.message ?? undefined}
        />
      ))}
    </CellList>
  );
}

function StartForm({
  org,
  onStarted,
}: {
  org: Org;
  onStarted: (v: Verification) => void;
}) {
  const [method, setMethod] = useState<"registry_auto" | "manual">(
    "registry_auto",
  );
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
  const autoReady =
    /^(\d{10}|\d{12})$/.test(inn.trim()) && /^https:\/\/\S+$/.test(site.trim());
  return (
    <div className="stack">
      <div className="chips">
        <Chip
          selected={method === "registry_auto"}
          onClick={() => setMethod("registry_auto")}
        >
          По ИНН и сайту
        </Chip>
        <Chip
          selected={method === "manual"}
          onClick={() => setMethod("manual")}
        >
          Через администратора
        </Chip>
      </div>
      {method === "registry_auto" ? (
        <>
          <Typography.Body variant="small" className="muted">
            Сверим ИНН с ЕГРЮЛ/ЕГРИП, попросим подтвердить телефон в боте и
            найдём проверочный код на официальном сайте или странице ВК
            организации.
          </Typography.Body>
          <Input
            inputMode="numeric"
            placeholder="ИНН"
            value={inn}
            onChange={(e) =>
              setInn(e.target.value.replace(/\D/g, "").slice(0, 12))
            }
            aria-label="ИНН"
          />
          <Input
            placeholder="https://сайт-организации"
            value={site}
            onChange={(e) => setSite(e.target.value)}
            aria-label="Сайт"
          />
        </>
      ) : (
        <>
          <Typography.Body variant="small" className="muted">
            Администратор свяжется с тобой и проверит вручную. Напиши, как с
            тобой связаться и чем подтвердить связь с организацией.
          </Typography.Body>
          <Textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            maxLength={1000}
            aria-label="Комментарий"
          />
        </>
      )}
      <FormErrors error={start.error} />
      <Button
        size="large"
        stretched
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
  const key = ["verification", org.id];
  const query = useQuery({
    queryKey: key,
    queryFn: () => fetchVerification(org.id),
  });
  const [again, setAgain] = useState(false);
  const recheck = useMutation({
    mutationFn: () => recheckVerification(org.id),
    onSuccess: (v) => client.setQueryData(key, v),
  });
  const onStarted = (v: Verification) => {
    setAgain(false);
    client.setQueryData(key, v);
    void client.invalidateQueries({ queryKey: ["org", org.id] });
  };

  if (org.verified) {
    return (
      <div className="notice stack">
        <Typography.Body variant="medium">
          ✓ Организация проверена
          {org.verified_at ? ` ${formatDate(org.verified_at)}` : ""}. События
          сразу попадают в «Официальные» с отметкой «Организатор проверен».
        </Typography.Body>
      </div>
    );
  }
  if (query.isPending)
    return <Typography.Body variant="small">Загружаем…</Typography.Body>;
  if (query.isError) return <FormErrors error={query.error} />;

  const request = query.data;
  if (!request || again) return <StartForm org={org} onStarted={onStarted} />;

  const waitUntil = request.next_attempt_at
    ? new Date(request.next_attempt_at)
    : null;
  const canRecheck =
    request.method === "registry_auto" && request.status === "pending";
  const phonePending = request.steps.some(
    (s) => s.code === "phone" && s.status === "pending",
  );
  return (
    <div className="stack">
      {request.code && request.status === "pending" && (
        <div className="notice stack">
          <Typography.Body variant="medium">
            Размести этот код на странице организации:
          </Typography.Body>
          <Typography.Headline variant="medium-strong">
            {request.code}
          </Typography.Headline>
          <Typography.Body variant="small" className="muted">
            {request.site_url} — в тексте страницы, можно в подвале. После
            проверки код можно удалить.
          </Typography.Body>
        </div>
      )}
      {phonePending && (
        <Typography.Body variant="small" className="notice">
          📱 Открой чат с ботом и нажми «Подтвердить телефон» — это твой
          собственный контакт MAX.
        </Typography.Body>
      )}
      <Steps request={request} />
      {request.decision_reason && (
        <Typography.Body variant="small" className="notice notice--danger">
          {request.decision_reason}
        </Typography.Body>
      )}
      {canRecheck && (
        <Button
          size="medium"
          variant="secondary"
          loading={recheck.isPending}
          onClick={() => recheck.mutate()}
        >
          🔄 Проверить сайт ещё раз
        </Button>
      )}
      {waitUntil && waitUntil > new Date() && (
        <Typography.Body variant="small" className="muted">
          Повтор — не раньше{" "}
          {waitUntil.toLocaleTimeString("ru-RU", {
            hour: "2-digit",
            minute: "2-digit",
          })}
        </Typography.Body>
      )}
      <FormErrors error={recheck.error} />
      {["rejected", "revoked"].includes(request.status) && (
        <Button size="medium" onClick={() => setAgain(true)}>
          Подать заявку заново
        </Button>
      )}
    </div>
  );
}
