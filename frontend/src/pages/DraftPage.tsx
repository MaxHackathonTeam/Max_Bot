import {
  Button,
  CellList,
  CellSimple,
  Input,
  Switch,
  Textarea,
  Typography,
} from "@maxhub/max-ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import {
  cancelEvent,
  createEvent,
  createVenue,
  deleteEvent,
  fetchManage,
  patchEvent,
  searchVenues,
  STATUS_LABELS,
  submitEvent,
  uploadMedia,
  type EventManage,
  type PriceType,
} from "../api/organizer";
import { hasConsent, useCategories, useLocality, useMe } from "../app/profile";
import { Chip } from "../components/Chip";
import { ConsentPrompt } from "../components/ConsentPrompt";
import { FormErrors } from "../components/FormErrors";
import { LocalityPicker } from "../components/LocalityPicker";
import { useDebounced } from "../hooks/useDebounced";
import {
  AGE_RATINGS,
  emptyForm,
  fromManage,
  STEPS,
  stepErrors,
  stepPayload,
  type EventForm,
} from "../lib/eventForm";
import { formatPrice, formatTime, formatWhen } from "../lib/format";
import { ErrorScreen, LoadingScreen } from "./Status";

type Update = (patch: Partial<EventForm>) => void;

const PRICES: [PriceType, string][] = [
  ["free", "Бесплатно"],
  ["paid", "Платно"],
  ["donation", "Донат"],
];

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <Typography.Label variant="medium-strong">{label}</Typography.Label>
      {children}
    </>
  );
}

function StepMain({ form, update }: { form: EventForm; update: Update }) {
  const categories = useCategories();
  return (
    <>
      <Field label="Название">
        <Input
          value={form.title}
          maxLength={255}
          onChange={(e) => update({ title: e.target.value })}
          aria-label="Название"
        />
      </Field>
      <Field label="Категория">
        <div className="chips chips--wrap">
          {(categories.data ?? []).map((c) => (
            <Chip
              key={c.slug}
              selected={form.category === c.slug}
              onClick={() => update({ category: c.slug })}
            >
              {c.emoji} {c.name}
            </Chip>
          ))}
        </div>
      </Field>
      <Field label="Коротко (для карточки)">
        <Input
          value={form.short_description}
          maxLength={512}
          onChange={(e) => update({ short_description: e.target.value })}
          aria-label="Кратко"
        />
      </Field>
      <Field label="Описание">
        <Textarea
          value={form.description}
          maxLength={8000}
          rows={6}
          onChange={(e) => update({ description: e.target.value })}
          aria-label="Описание"
        />
      </Field>
    </>
  );
}

function VenuePicker({
  form,
  update,
  orgId,
}: {
  form: EventForm;
  update: Update;
  orgId: number | null;
}) {
  const locality = useLocality(form.locality_id);
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const q = useDebounced(query.trim());
  const venues = useQuery({
    queryKey: ["venues", q, orgId],
    queryFn: () => searchVenues(q, orgId),
  });
  const add = useMutation({
    mutationFn: () => {
      const point = locality.data;
      if (!point) throw new Error("Сначала выбери населённый пункт");
      return createVenue({
        name: name.trim(),
        address: address.trim() || null,
        lat: point.lat,
        lon: point.lon,
        org_id: orgId,
        locality_id: point.id,
      });
    },
    onSuccess: (v) => {
      update({ venue_id: v.id, venue_name: v.name });
      setAdding(false);
    },
  });

  if (form.venue_id !== null) {
    return (
      <CellList mode="island" filled>
        <CellSimple
          title={`🏠 ${form.venue_name ?? "Площадка"}`}
          subtitle="Изменить"
          showChevron
          onClick={() => update({ venue_id: null, venue_name: null })}
        />
      </CellList>
    );
  }
  return (
    <div className="stack">
      <Input
        placeholder="Поиск площадки"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        aria-label="Площадка"
      />
      {(venues.data ?? []).length > 0 && (
        <CellList mode="island" filled>
          {(venues.data ?? []).slice(0, 8).map((v) => (
            <CellSimple
              key={v.id}
              title={v.name}
              subtitle={[v.address, v.locality_name]
                .filter(Boolean)
                .join(" · ")}
              onClick={() =>
                update({
                  venue_id: v.id,
                  venue_name: v.name,
                  locality_id: v.locality_id,
                  locality_name: v.locality_name,
                })
              }
            />
          ))}
        </CellList>
      )}
      {adding ? (
        <div className="notice stack">
          <Input
            placeholder="Название площадки"
            value={name}
            maxLength={255}
            onChange={(e) => setName(e.target.value)}
            aria-label="Название площадки"
          />
          <Input
            placeholder="Адрес"
            value={address}
            maxLength={500}
            onChange={(e) => setAddress(e.target.value)}
            aria-label="Адрес площадки"
          />
          <Typography.Body variant="small" className="muted">
            На карте площадка будет в центре выбранного населённого пункта.
          </Typography.Body>
          <Button
            size="medium"
            disabled={name.trim().length < 2 || !locality.data}
            loading={add.isPending}
            onClick={() => add.mutate()}
          >
            Добавить
          </Button>
          <FormErrors error={add.error} />
        </div>
      ) : (
        <Button
          size="medium"
          variant="ghost"
          disabled={form.locality_id === null}
          onClick={() => setAdding(true)}
        >
          ➕ Новая площадка
        </Button>
      )}
    </div>
  );
}

function StepWhere({
  form,
  update,
  orgId,
  timeZone,
}: {
  form: EventForm;
  update: Update;
  orgId: number | null;
  timeZone: string;
}) {
  const [picking, setPicking] = useState(form.locality_id === null);
  const setSession = (
    i: number,
    patch: Partial<EventForm["sessions"][number]>,
  ) =>
    update({
      sessions: form.sessions.map((s, j) => (j === i ? { ...s, ...patch } : s)),
    });
  return (
    <>
      <div className="chips">
        <Chip
          selected={!form.is_online}
          onClick={() => update({ is_online: false })}
        >
          📍 На месте
        </Chip>
        <Chip
          selected={form.is_online}
          onClick={() => update({ is_online: true })}
        >
          💻 Онлайн
        </Chip>
      </div>
      {form.is_online && (
        <Field label="Ссылка на трансляцию">
          <Input
            placeholder="https://"
            value={form.online_url}
            onChange={(e) => update({ online_url: e.target.value })}
            aria-label="Ссылка на трансляцию"
          />
        </Field>
      )}
      <Field label="Населённый пункт">
        {picking ? (
          <LocalityPicker
            onPick={(l) => {
              update({
                locality_id: l.id,
                locality_name: l.name,
                venue_id: null,
                venue_name: null,
              });
              setPicking(false);
            }}
          />
        ) : (
          <Button
            size="medium"
            variant="secondary"
            onClick={() => setPicking(true)}
          >
            📍 {form.locality_name ?? "Выбран"} · изменить
          </Button>
        )}
      </Field>
      {!form.is_online && (
        <Field label="Площадка (необязательно)">
          <VenuePicker form={form} update={update} orgId={orgId} />
        </Field>
      )}
      <Field label="Сеансы">
        <Typography.Body variant="small" className="muted">
          Время — местное для места события ({timeZone}).
        </Typography.Body>
        {form.sessions.map((s, i) => (
          <div key={s.id ?? `new-${i}`} className="notice stack">
            <label className="stack">
              <Typography.Body variant="small">Начало</Typography.Body>
              <input
                type="datetime-local"
                value={s.starts}
                onChange={(e) => setSession(i, { starts: e.target.value })}
              />
            </label>
            <label className="stack">
              <Typography.Body variant="small">
                Конец (необязательно)
              </Typography.Body>
              <input
                type="datetime-local"
                value={s.ends}
                onChange={(e) => setSession(i, { ends: e.target.value })}
              />
            </label>
            {form.sessions.length > 1 && (
              <Button
                size="small"
                variant="ghost"
                onClick={() =>
                  update({ sessions: form.sessions.filter((_, j) => j !== i) })
                }
              >
                Убрать сеанс
              </Button>
            )}
          </div>
        ))}
        {form.sessions.length < 50 && (
          <Button
            size="medium"
            variant="ghost"
            onClick={() =>
              update({
                sessions: [
                  ...form.sessions,
                  { id: null, starts: "", ends: "" },
                ],
              })
            }
          >
            ➕ Ещё сеанс
          </Button>
        )}
      </Field>
    </>
  );
}

function StepPrice({
  form,
  update,
  canPushkin,
}: {
  form: EventForm;
  update: Update;
  canPushkin: boolean;
}) {
  return (
    <>
      <Field label="Вход">
        <div className="chips">
          {PRICES.map(([value, label]) => (
            <Chip
              key={value}
              selected={form.price_type === value}
              onClick={() => update({ price_type: value })}
            >
              {label}
            </Chip>
          ))}
        </div>
      </Field>
      {form.price_type === "paid" && (
        <div className="row">
          <Input
            inputMode="decimal"
            placeholder="от, ₽"
            value={form.price_min}
            onChange={(e) => update({ price_min: e.target.value })}
            aria-label="Цена от"
          />
          <Input
            inputMode="decimal"
            placeholder="до, ₽"
            value={form.price_max}
            onChange={(e) => update({ price_max: e.target.value })}
            aria-label="Цена до"
          />
        </div>
      )}
      {canPushkin ? (
        <CellList mode="island" filled>
          <CellSimple
            title="💳 Пушкинская карта"
            after={
              <Switch
                checked={form.pushkin_card}
                onChange={(e) => update({ pushkin_card: e.target.checked })}
                aria-label="Пушкинская карта"
              />
            }
          />
        </CellList>
      ) : (
        <Typography.Body variant="small" className="muted">
          «Пушкинская карта» доступна только проверенным организациям.
        </Typography.Body>
      )}
      <Field label="Возраст">
        <div className="chips">
          {AGE_RATINGS.map((a) => (
            <Chip
              key={a}
              selected={form.age_rating === a}
              onClick={() =>
                update({ age_rating: form.age_rating === a ? null : a })
              }
            >
              {a}+
            </Chip>
          ))}
        </div>
      </Field>
      <CellList mode="island" filled>
        <CellSimple
          title="Нужна регистрация"
          after={
            <Switch
              checked={form.registration_required}
              onChange={(e) =>
                update({ registration_required: e.target.checked })
              }
              aria-label="Нужна регистрация"
            />
          }
        />
      </CellList>
      <Field label="Ссылка на билеты или регистрацию">
        <Input
          placeholder="https://"
          value={form.ticket_url}
          onChange={(e) => update({ ticket_url: e.target.value })}
          aria-label="Ссылка на билеты"
        />
      </Field>
    </>
  );
}

function StepCover({ form, update }: { form: EventForm; update: Update }) {
  const upload = useMutation({
    mutationFn: uploadMedia,
    onSuccess: (m) => update({ cover_media_id: m.id, cover_url: m.url }),
  });
  const toggle = (key: "ramp" | "toilet" | "sign_language", title: string) => (
    <CellSimple
      title={title}
      after={
        <Switch
          checked={form[key]}
          onChange={(e) => update({ [key]: e.target.checked })}
          aria-label={title}
        />
      }
    />
  );
  return (
    <>
      <Field label="Обложка">
        {form.cover_url && (
          <img className="cover" src={form.cover_url} alt="Обложка" />
        )}
        <input
          type="file"
          accept="image/jpeg,image/png,image/webp"
          aria-label="Загрузить обложку"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) upload.mutate(file);
            e.target.value = "";
          }}
        />
        {upload.isPending && (
          <Typography.Body variant="small">Загружаем…</Typography.Body>
        )}
        <Typography.Body variant="small" className="muted">
          JPEG, PNG или WebP до 5 МБ. Геометки и данные камеры удаляем.
        </Typography.Body>
        {form.cover_media_id !== null && (
          <Button
            size="small"
            variant="ghost"
            onClick={() => update({ cover_media_id: null, cover_url: null })}
          >
            Убрать обложку
          </Button>
        )}
        <FormErrors error={upload.error} />
      </Field>
      <Field label="Контакты для вопросов">
        <Input
          value={form.contacts}
          maxLength={500}
          onChange={(e) => update({ contacts: e.target.value })}
          aria-label="Контакты"
        />
      </Field>
      <Field label="Доступная среда">
        <CellList mode="island" filled>
          {toggle("ramp", "Пандус или вход без ступеней")}
          {toggle("toilet", "Доступный туалет")}
          {toggle("sign_language", "Сурдоперевод")}
        </CellList>
      </Field>
    </>
  );
}

function Summary({ event }: { event: EventManage }) {
  const where = event.is_online
    ? "Онлайн"
    : [event.venue?.name, event.locality_name].filter(Boolean).join(", ");
  return (
    <div className="stack">
      {event.cover_url && (
        <img className="cover" src={event.cover_url} alt="" />
      )}
      <Typography.Headline variant="medium-strong">
        {event.title}
      </Typography.Headline>
      <Typography.Body variant="medium">
        {where || "Место не указано"}
      </Typography.Body>
      {event.sessions
        .filter((s) => s.status !== "cancelled")
        .map((s) => (
          <Typography.Body key={s.id} variant="small">
            🗓 {formatWhen(s.starts_at, event.timezone)}
            {s.ends_at ? `–${formatTime(s.ends_at, event.timezone)}` : ""}
          </Typography.Body>
        ))}
      <Typography.Body variant="small">
        {event.price_type === "unknown"
          ? "Цена не указана"
          : formatPrice(event)}
        {event.age_rating !== null ? ` · ${event.age_rating}+` : ""}
        {event.pushkin_card ? " · 💳 Пушкинская карта" : ""}
      </Typography.Body>
      {event.short_description && (
        <Typography.Body variant="medium">
          {event.short_description}
        </Typography.Body>
      )}
    </div>
  );
}

function StepReview({ event }: { event: EventManage }) {
  const client = useQueryClient();
  const navigate = useNavigate();
  const set = (e: EventManage) => client.setQueryData(["manage", e.id], e);
  const submit = useMutation({
    mutationFn: () => submitEvent(event.id),
    onSuccess: set,
  });
  const cancel = useMutation({
    mutationFn: () => cancelEvent(event.id),
    onSuccess: set,
  });
  const remove = useMutation({
    mutationFn: () => deleteEvent(event.id),
    onSuccess: () =>
      navigate(
        event.organization_id ? `/org/${event.organization_id}` : "/org/0",
        { replace: true },
      ),
  });
  const official = event.trust_tier === "official";
  const canSubmit = event.status === "draft" || event.status === "rejected";
  return (
    <>
      <Summary event={event} />
      {canSubmit && (
        <Typography.Body variant="small" className="muted">
          {official
            ? "Событие сразу появится в «Официальных» с отметкой «Организатор проверен»."
            : "Событие проверит модерация, после этого оно появится в «От сообщества». Результат пришлём в бот."}
        </Typography.Body>
      )}
      <FormErrors error={submit.error ?? cancel.error ?? remove.error} />
      {canSubmit && (
        <Button
          size="large"
          stretched
          loading={submit.isPending}
          onClick={() => submit.mutate()}
        >
          {official ? "🚀 Опубликовать" : "📨 Отправить на проверку"}
        </Button>
      )}
      {event.status === "published" && (
        <Button size="large" variant="secondary" asChild>
          <Link to={`/event/${event.id}`}>Открыть карточку события</Link>
        </Button>
      )}
      {["published", "pending", "hidden"].includes(event.status) && (
        <Button
          size="medium"
          variant="ghost"
          loading={cancel.isPending}
          onClick={() => cancel.mutate()}
        >
          Отменить событие
        </Button>
      )}
      {event.status === "draft" && (
        <Button
          size="medium"
          variant="ghost"
          loading={remove.isPending}
          onClick={() => remove.mutate()}
        >
          🗑 Удалить черновик
        </Button>
      )}
    </>
  );
}

function Editor({
  event,
  orgId,
  initialStep,
}: {
  event: EventManage | null;
  orgId: number | null;
  initialStep: number;
}) {
  const client = useQueryClient();
  const navigate = useNavigate();
  const [form, setForm] = useState<EventForm>(() =>
    event ? fromManage(event) : emptyForm(),
  );
  const [step, setStep] = useState(event ? initialStep : 0);
  const [shown, setShown] = useState<string[]>([]);
  const update: Update = (patch) => setForm((f) => ({ ...f, ...patch }));
  const timeZone = event?.timezone ?? "Europe/Moscow";
  const organization = event?.organization_id ?? orgId;

  const save = useMutation({
    mutationFn: async (current: number): Promise<EventManage | null> => {
      if (!event) {
        const created = await createEvent({
          ...stepPayload(0, form, timeZone),
          title: form.title.trim(),
          organization_id: orgId,
        });
        navigate(`/draft/${created.id}?step=1`, { replace: true });
        return null;
      }
      if (current === 1) {
        // Сначала место: от него зависит часовой пояс, в котором заданы сеансы.
        const { sessions, ...place } = stepPayload(1, form, timeZone);
        const placed = await patchEvent(event.id, place);
        return patchEvent(event.id, {
          sessions: stepPayload(1, form, placed.timezone).sessions ?? sessions,
        });
      }
      return patchEvent(event.id, stepPayload(current, form, timeZone));
    },
    onSuccess: (saved, current) => {
      if (!saved) return;
      client.setQueryData(["manage", saved.id], saved);
      // Новые сеансы получили id — иначе следующее сохранение создаст их повторно.
      setForm((f) => ({ ...f, sessions: fromManage(saved).sessions }));
      setStep(current + 1);
    },
  });

  const next = () => {
    const errors = stepErrors(step, form, new Date(), timeZone);
    setShown(errors);
    if (errors.length === 0) save.mutate(step);
  };

  return (
    <main className="screen">
      <Typography.Headline variant="large-strong">
        {event ? "Событие" : "Новое событие"}
      </Typography.Headline>
      <div className="badges">
        {event && (
          <span className="badge">
            {STATUS_LABELS[event.status] ?? event.status}
          </span>
        )}
        <span
          className={
            event?.trust_tier === "official" ? "badge badge--verified" : "badge"
          }
        >
          {event?.trust_tier === "official"
            ? `✓ Официальное · ${event.org_name ?? ""}`
            : organization
              ? "От организации (не проверена) · «От сообщества»"
              : "От сообщества"}
        </span>
      </div>
      {event?.moderation_reason &&
        ["rejected", "hidden"].includes(event.status) && (
          <Typography.Body variant="small" className="notice notice--danger">
            Причина: {event.moderation_reason}
          </Typography.Body>
        )}

      <div className="tabs" role="tablist">
        {STEPS.map((title, i) => (
          <button
            key={title}
            type="button"
            role="tab"
            aria-selected={step === i}
            className={step === i ? "tab tab--on" : "tab"}
            disabled={!event}
            onClick={() => {
              setShown([]);
              setStep(i);
            }}
          >
            {i + 1}. {title}
          </button>
        ))}
      </div>

      {step === 0 && <StepMain form={form} update={update} />}
      {step === 1 && (
        <StepWhere
          form={form}
          update={update}
          orgId={organization}
          timeZone={timeZone}
        />
      )}
      {step === 2 && (
        <StepPrice
          form={form}
          update={update}
          canPushkin={event?.can_pushkin ?? false}
        />
      )}
      {step === 3 && <StepCover form={form} update={update} />}
      {step === 4 && event && <StepReview event={event} />}

      <FormErrors messages={shown} error={save.error} />
      {step < 4 && (
        <div className="row">
          {step > 0 && (
            <Button
              size="large"
              variant="secondary"
              onClick={() => setStep(step - 1)}
            >
              Назад
            </Button>
          )}
          <Button
            size="large"
            stretched
            loading={save.isPending}
            onClick={next}
          >
            {event ? "Сохранить и дальше" : "Создать черновик"}
          </Button>
        </div>
      )}
    </main>
  );
}

/** Форма события в 5 шагов (FR-PUB): /draft/0 — новое (?org=<id> — от организации). */
export function DraftPage() {
  const id = Number(useParams().id);
  const [params] = useSearchParams();
  const me = useMe();
  const orgParam = Number(params.get("org"));
  const orgId = Number.isInteger(orgParam) && orgParam > 0 ? orgParam : null;
  const stepParam = Number(params.get("step"));
  const initialStep =
    Number.isInteger(stepParam) && stepParam >= 0 && stepParam < STEPS.length
      ? stepParam
      : 0;
  const valid = Number.isInteger(id) && id >= 0;
  const event = useQuery({
    queryKey: ["manage", id],
    queryFn: () => fetchManage(id),
    enabled: valid && id > 0,
  });

  if (!valid) return <ErrorScreen message="Событие не найдено." />;
  if (me.isPending) return <LoadingScreen />;
  if (me.isError)
    return (
      <ErrorScreen
        message={me.error.message}
        onRetry={() => void me.refetch()}
      />
    );
  if (!hasConsent(me.data)) {
    return (
      <main className="screen">
        <Typography.Headline variant="large-strong">
          Новое событие
        </Typography.Headline>
        <ConsentPrompt />
      </main>
    );
  }
  if (id === 0)
    return <Editor key="new" event={null} orgId={orgId} initialStep={0} />;
  if (event.isPending) return <LoadingScreen />;
  if (event.isError)
    return (
      <ErrorScreen
        message={event.error.message}
        onRetry={() => void event.refetch()}
      />
    );
  return (
    <Editor
      key={id}
      event={event.data}
      orgId={event.data.organization_id}
      initialStep={initialStep}
    />
  );
}
