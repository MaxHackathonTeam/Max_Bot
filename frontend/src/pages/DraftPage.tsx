import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Accessibility,
  BadgeCheck,
  CalendarDays,
  CircleAlert,
  CreditCard,
  Eye,
  House,
  ImagePlus,
  MapPin,
  MonitorPlay,
  Plus,
  Rocket,
  Search,
  Send,
  Trash,
  X,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import type { Me } from "../api/client";
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
import { hasConsent, useCategories } from "../app/profile";
import { ConsentPrompt } from "../components/ConsentPrompt";
import { FormErrors } from "../components/FormErrors";
import { LocalityPicker } from "../components/LocalityPicker";
import { RequireMax } from "../components/RequireMax";
import { useDebounced } from "../hooks/useDebounced";
import { categoryLook } from "../lib/categories";
import { AGE_RATINGS, emptyForm, fromManage, STEPS, stepErrors, stepPayload, type EventForm } from "../lib/eventForm";
import { formatPrice, formatTime, formatWhen } from "../lib/format";
import { Badge } from "../ui/Badge";
import { Button, ButtonLink } from "../ui/Button";
import { Card } from "../ui/Card";
import { Chip } from "../ui/Chip";
import { Field, Input, Textarea } from "../ui/Field";
import { ListRow } from "../ui/ListRow";
import { Sheet } from "../ui/Sheet";
import { Switch } from "../ui/Switch";
import { useToast } from "../ui/toastContext";
import { ErrorScreen, LoadingScreen } from "./Status";

type Update = (patch: Partial<EventForm>) => void;

const PRICES: [PriceType, string][] = [
  ["free", "Бесплатно"],
  ["paid", "Платно"],
  ["donation", "Донат"],
];

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="filter-group">
      <legend className="field__label">{title}</legend>
      {children}
    </fieldset>
  );
}

function StepMain({ form, update }: { form: EventForm; update: Update }) {
  const categories = useCategories();
  return (
    <>
      <Field label="Название">
        {(p) => <Input {...p} value={form.title} maxLength={255} onChange={(e) => update({ title: e.target.value })} />}
      </Field>
      <Group title="Категория">
        <div className="chips">
          {(categories.data ?? []).map((c) => {
            const Icon = categoryLook(c.slug).icon;
            return (
              <Chip
                key={c.slug}
                pressed={form.category === c.slug}
                icon={<Icon size={15} aria-hidden />}
                onClick={() => update({ category: c.slug })}
              >
                {c.name}
              </Chip>
            );
          })}
        </div>
      </Group>
      <Field label="Коротко (для карточки)">
        {(p) => (
          <Input {...p} value={form.short_description} maxLength={512} onChange={(e) => update({ short_description: e.target.value })} />
        )}
      </Field>
      <Field label="Описание">
        {(p) => (
          <Textarea {...p} value={form.description} maxLength={8000} rows={6} onChange={(e) => update({ description: e.target.value })} />
        )}
      </Field>
    </>
  );
}

function VenuePicker({ form, update, orgId }: { form: EventForm; update: Update; orgId: number | null }) {
  const [query, setQuery] = useState("");
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const q = useDebounced(query.trim());
  const venues = useQuery({ queryKey: ["venues", q, orgId], queryFn: () => searchVenues(q, orgId) });
  const add = useMutation({
    mutationFn: () => {
      if (form.locality_id === null) throw new Error("Сначала выбери населённый пункт");
      // Координаты не спрашиваем: площадка встанет в центр населённого пункта.
      return createVenue({ name: name.trim(), address: address.trim() || null, org_id: orgId, locality_id: form.locality_id });
    },
    onSuccess: (v) => {
      update({ venue_id: v.id, venue_name: v.name });
      setAdding(false);
    },
  });

  if (form.venue_id !== null) {
    return (
      <div className="list">
        <ListRow
          icon={<House size={18} aria-hidden />}
          title={form.venue_name ?? "Площадка"}
          subtitle="Выбрать другую"
          onClick={() => update({ venue_id: null, venue_name: null })}
        />
      </div>
    );
  }
  return (
    <div className="stack">
      <div className="input-wrap">
        <Search size={18} aria-hidden />
        <Input placeholder="Поиск площадки" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Поиск площадки" />
      </div>
      {(venues.data ?? []).length > 0 && (
        <div className="list">
          {(venues.data ?? []).slice(0, 8).map((v) => (
            <ListRow
              key={v.id}
              icon={<House size={18} aria-hidden />}
              title={v.name}
              subtitle={[v.address, v.locality_name].filter(Boolean).join(" · ")}
              onClick={() => update({ venue_id: v.id, venue_name: v.name, locality_id: v.locality_id, locality_name: v.locality_name })}
            />
          ))}
        </div>
      )}
      {adding ? (
        <Card className="stack">
          <Field label="Название площадки">
            {(p) => <Input {...p} value={name} maxLength={255} onChange={(e) => setName(e.target.value)} />}
          </Field>
          <Field label="Адрес" hint="На карте площадка будет в центре выбранного населённого пункта.">
            {(p) => <Input {...p} value={address} maxLength={500} onChange={(e) => setAddress(e.target.value)} />}
          </Field>
          <div className="row">
            <Button variant="ghost" onClick={() => setAdding(false)}>
              Отмена
            </Button>
            <Button variant="primary" disabled={name.trim().length < 2 || form.locality_id === null} loading={add.isPending} onClick={() => add.mutate()}>
              Добавить
            </Button>
          </div>
          <FormErrors error={add.error} />
        </Card>
      ) : (
        <div>
          <Button variant="ghost" icon={<Plus size={16} aria-hidden />} disabled={form.locality_id === null} onClick={() => setAdding(true)}>
            Новая площадка
          </Button>
        </div>
      )}
    </div>
  );
}

function StepWhere({ form, update, orgId, timeZone }: { form: EventForm; update: Update; orgId: number | null; timeZone: string }) {
  const [picking, setPicking] = useState(false);
  const setSession = (i: number, patch: Partial<EventForm["sessions"][number]>) =>
    update({ sessions: form.sessions.map((s, j) => (j === i ? { ...s, ...patch } : s)) });
  return (
    <>
      <div className="chips" role="group" aria-label="Формат">
        <Chip pressed={!form.is_online} icon={<MapPin size={15} aria-hidden />} onClick={() => update({ is_online: false })}>
          На месте
        </Chip>
        <Chip pressed={form.is_online} icon={<MonitorPlay size={15} aria-hidden />} onClick={() => update({ is_online: true })}>
          Онлайн
        </Chip>
      </div>
      {form.is_online && (
        <Field label="Ссылка на трансляцию">
          {(p) => <Input {...p} type="url" placeholder="https://" value={form.online_url} onChange={(e) => update({ online_url: e.target.value })} />}
        </Field>
      )}
      <div className="field">
        <span className="field__label">Населённый пункт</span>
        <div>
          <Button variant="secondary" icon={<MapPin size={16} aria-hidden />} onClick={() => setPicking(true)}>
            {form.locality_name ?? "Выбрать"}
          </Button>
        </div>
      </div>
      {!form.is_online && (
        <Group title="Площадка (необязательно)">
          <VenuePicker form={form} update={update} orgId={orgId} />
        </Group>
      )}
      <Group title="Сеансы">
        <p className="small muted">Время — местное для места события ({timeZone}).</p>
        {form.sessions.map((s, i) => (
          <div key={s.id ?? `new-${i}`} className="session-edit">
            <Field label="Начало">
              {(p) => <Input {...p} type="datetime-local" value={s.starts} onChange={(e) => setSession(i, { starts: e.target.value })} />}
            </Field>
            <Field label="Конец (необязательно)">
              {(p) => <Input {...p} type="datetime-local" value={s.ends} onChange={(e) => setSession(i, { ends: e.target.value })} />}
            </Field>
            {form.sessions.length > 1 && (
              <Button variant="ghost" size="sm" icon={<X size={16} aria-hidden />} onClick={() => update({ sessions: form.sessions.filter((_, j) => j !== i) })}>
                Убрать
              </Button>
            )}
          </div>
        ))}
        {form.sessions.length < 50 && (
          <div>
            <Button variant="ghost" icon={<Plus size={16} aria-hidden />} onClick={() => update({ sessions: [...form.sessions, { id: null, starts: "", ends: "" }] })}>
              Ещё сеанс
            </Button>
          </div>
        )}
      </Group>
      <Sheet open={picking || form.locality_id === null} onClose={() => setPicking(false)} title="Где пройдёт событие">
        <LocalityPicker
          onPick={(l) => {
            update({ locality_id: l.id, locality_name: l.name, venue_id: null, venue_name: null });
            setPicking(false);
          }}
        />
      </Sheet>
    </>
  );
}

function StepPrice({ form, update, canPushkin }: { form: EventForm; update: Update; canPushkin: boolean }) {
  return (
    <>
      <Group title="Вход">
        <div className="chips">
          {PRICES.map(([value, label]) => (
            <Chip key={value} pressed={form.price_type === value} onClick={() => update({ price_type: value })}>
              {label}
            </Chip>
          ))}
        </div>
      </Group>
      {form.price_type === "paid" && (
        <div className="two-col">
          <Field label="Цена от, ₽">
            {(p) => <Input {...p} inputMode="decimal" value={form.price_min} onChange={(e) => update({ price_min: e.target.value })} />}
          </Field>
          <Field label="Цена до, ₽">
            {(p) => <Input {...p} inputMode="decimal" value={form.price_max} onChange={(e) => update({ price_max: e.target.value })} />}
          </Field>
        </div>
      )}
      <div className="list">
        {canPushkin ? (
          <ListRow
            icon={<CreditCard size={18} aria-hidden />}
            title="Пушкинская карта"
            after={<Switch label="Пушкинская карта" checked={form.pushkin_card} onChange={(v) => update({ pushkin_card: v })} />}
          />
        ) : (
          <ListRow icon={<CreditCard size={18} aria-hidden />} title="Пушкинская карта" subtitle="Доступна только проверенным организациям" />
        )}
        <ListRow
          title="Нужна регистрация"
          after={<Switch label="Нужна регистрация" checked={form.registration_required} onChange={(v) => update({ registration_required: v })} />}
        />
      </div>
      <Group title="Возраст">
        <div className="chips">
          {AGE_RATINGS.map((a) => (
            <Chip key={a} pressed={form.age_rating === a} onClick={() => update({ age_rating: form.age_rating === a ? null : a })}>
              {a}+
            </Chip>
          ))}
        </div>
      </Group>
      <Field label="Ссылка на билеты или регистрацию">
        {(p) => <Input {...p} type="url" placeholder="https://" value={form.ticket_url} onChange={(e) => update({ ticket_url: e.target.value })} />}
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
    <ListRow title={title} after={<Switch label={title} checked={form[key]} onChange={(v) => update({ [key]: v })} />} />
  );
  return (
    <>
      <Group title="Обложка">
        {form.cover_url && <img className="cover-preview" src={form.cover_url} alt="Обложка события" />}
        <div className="row row--wrap">
          <label className="btn btn--secondary">
            <ImagePlus size={18} aria-hidden />
            {upload.isPending ? "Загружаем…" : form.cover_url ? "Заменить" : "Загрузить"}
            <input
              type="file"
              className="visually-hidden"
              accept="image/jpeg,image/png,image/webp"
              disabled={upload.isPending}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) upload.mutate(file);
                e.target.value = "";
              }}
            />
          </label>
          {form.cover_media_id !== null && (
            <Button variant="ghost" icon={<Trash size={16} aria-hidden />} onClick={() => update({ cover_media_id: null, cover_url: null })}>
              Убрать
            </Button>
          )}
        </div>
        <p className="small muted">JPEG, PNG или WebP до 5 МБ. Геометки и данные камеры удаляем.</p>
        <FormErrors error={upload.error} />
      </Group>
      <Field label="Контакты для вопросов">
        {(p) => <Input {...p} value={form.contacts} maxLength={500} onChange={(e) => update({ contacts: e.target.value })} />}
      </Field>
      <Group title="Доступная среда">
        <div className="list">
          {toggle("ramp", "Пандус или вход без ступеней")}
          {toggle("toilet", "Доступный туалет")}
          {toggle("sign_language", "Сурдоперевод")}
        </div>
      </Group>
    </>
  );
}

function Summary({ event }: { event: EventManage }) {
  const where = event.is_online ? "Онлайн" : [event.venue?.name, event.locality_name].filter(Boolean).join(", ");
  return (
    <Card className="stack">
      {event.cover_url && <img className="cover-preview" src={event.cover_url} alt="" />}
      <h2 className="h2">{event.title}</h2>
      <p className="fact">
        <MapPin size={18} aria-hidden />
        <span>{where || "Место не указано"}</span>
      </p>
      {event.sessions
        .filter((s) => s.status !== "cancelled")
        .map((s) => (
          <p key={s.id} className="fact">
            <CalendarDays size={18} aria-hidden />
            <span>
              {formatWhen(s.starts_at, event.timezone)}
              {s.ends_at ? `–${formatTime(s.ends_at, event.timezone)}` : ""}
            </span>
          </p>
        ))}
      <p>
        {event.price_type === "unknown" ? "Цена не указана" : formatPrice(event)}
        {event.age_rating !== null ? ` · ${event.age_rating}+` : ""}
        {event.pushkin_card ? " · Пушкинская карта" : ""}
      </p>
      {event.accessibility && Object.values(event.accessibility).some(Boolean) && (
        <p className="fact small">
          <Accessibility size={16} aria-hidden />
          <span>Доступная среда</span>
        </p>
      )}
      {event.short_description && <p className="muted">{event.short_description}</p>}
    </Card>
  );
}

function StepReview({ event }: { event: EventManage }) {
  const client = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  const set = (e: EventManage) => client.setQueryData(["manage", e.id], e);
  const official = event.trust_tier === "official";
  const submit = useMutation({
    mutationFn: () => submitEvent(event.id),
    onSuccess: (e) => {
      set(e);
      toast.show(official ? "Опубликовано" : "Отправили на проверку — итог придёт в бот");
    },
  });
  const cancel = useMutation({
    mutationFn: () => cancelEvent(event.id),
    onSuccess: (e) => {
      set(e);
      toast.show("Событие отменено");
    },
  });
  const remove = useMutation({
    mutationFn: () => deleteEvent(event.id),
    onSuccess: () => {
      toast.show("Черновик удалён");
      navigate(event.organization_id ? `/org/${event.organization_id}` : "/org/0", { replace: true });
    },
  });
  const canSubmit = event.status === "draft" || event.status === "rejected";
  return (
    <>
      <Summary event={event} />
      {canSubmit && (
        <p className="small muted">
          {official
            ? "Событие сразу появится в «Официальных» с отметкой «Организатор проверен»."
            : "Событие проверит модерация, после этого оно появится в «От сообщества». Результат пришлём в бот."}
        </p>
      )}
      <FormErrors error={submit.error ?? cancel.error ?? remove.error} />
      {canSubmit && (
        <Button
          variant="primary"
          size="lg"
          block
          loading={submit.isPending}
          icon={official ? <Rocket size={18} aria-hidden /> : <Send size={18} aria-hidden />}
          onClick={() => submit.mutate()}
        >
          {official ? "Опубликовать" : "Отправить на проверку"}
        </Button>
      )}
      {event.status === "published" && (
        <ButtonLink to={`/event/${event.id}`} variant="secondary" size="lg" block icon={<Eye size={18} aria-hidden />}>
          Открыть карточку события
        </ButtonLink>
      )}
      <div className="row row--wrap">
        {["published", "pending", "hidden"].includes(event.status) && (
          <Button variant="ghost" loading={cancel.isPending} onClick={() => cancel.mutate()}>
            Отменить событие
          </Button>
        )}
        {event.status === "draft" && (
          <Button variant="ghost" loading={remove.isPending} icon={<Trash size={16} aria-hidden />} onClick={() => remove.mutate()}>
            Удалить черновик
          </Button>
        )}
      </div>
    </>
  );
}

function Editor({ event, orgId, initialStep }: { event: EventManage | null; orgId: number | null; initialStep: number }) {
  const client = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  const [form, setForm] = useState<EventForm>(() => (event ? fromManage(event) : emptyForm()));
  const [step, setStep] = useState(event ? initialStep : 0);
  const [shown, setShown] = useState<string[]>([]);
  const update: Update = (patch) => setForm((f) => ({ ...f, ...patch }));
  const timeZone = event?.timezone ?? "Europe/Moscow";
  const organization = event?.organization_id ?? orgId;

  const save = useMutation({
    mutationFn: async (current: number): Promise<EventManage | null> => {
      if (!event) {
        const created = await createEvent({ ...stepPayload(0, form, timeZone), title: form.title.trim(), organization_id: orgId });
        toast.show("Черновик создан");
        navigate(`/draft/${created.id}?step=1`, { replace: true });
        return null;
      }
      if (current === 1) {
        // Сначала место: от него зависит часовой пояс, в котором заданы сеансы.
        const { sessions, ...place } = stepPayload(1, form, timeZone);
        const placed = await patchEvent(event.id, place);
        return patchEvent(event.id, { sessions: stepPayload(1, form, placed.timezone).sessions ?? sessions });
      }
      return patchEvent(event.id, stepPayload(current, form, timeZone));
    },
    onSuccess: (saved, current) => {
      if (!saved) return;
      client.setQueryData(["manage", saved.id], saved);
      // Новые сеансы получили id — иначе следующее сохранение создаст их повторно.
      setForm((f) => ({ ...f, sessions: fromManage(saved).sessions }));
      setStep(current + 1);
      window.scrollTo({ top: 0 });
    },
  });

  const next = () => {
    const errors = stepErrors(step, form, new Date(), timeZone);
    setShown(errors);
    if (errors.length === 0) save.mutate(step);
  };

  return (
    <main className="page page--narrow">
      <div className="stack stack--loose">
        <div className="page-head">
          <p className="eyebrow">{event ? (STATUS_LABELS[event.status] ?? event.status) : "Черновик"}</p>
          <h1 className="h1">{event?.title || "Новое событие"}</h1>
          <div className="badges">
            {event?.trust_tier === "official" ? (
              <Badge tone="verified" icon={<BadgeCheck size={14} aria-hidden />}>
                Официальное · {event.org_name ?? ""}
              </Badge>
            ) : (
              <Badge>{organization ? "Организация не проверена · «От сообщества»" : "От сообщества"}</Badge>
            )}
          </div>
        </div>
        {event?.moderation_reason && ["rejected", "hidden"].includes(event.status) && (
          <div className="notice notice--danger">
            <CircleAlert size={18} aria-hidden />
            <span>Причина: {event.moderation_reason}</span>
          </div>
        )}

        <nav className="stepper" aria-label="Шаги формы">
          {STEPS.map((title, i) => (
            <button
              key={title}
              type="button"
              className="step"
              aria-current={step === i ? "step" : undefined}
              disabled={!event}
              onClick={() => {
                setShown([]);
                setStep(i);
              }}
            >
              <span className="step__num">{i + 1}</span>
              {title}
            </button>
          ))}
        </nav>

        <div className="stack">
          {step === 0 && <StepMain form={form} update={update} />}
          {step === 1 && <StepWhere form={form} update={update} orgId={organization} timeZone={timeZone} />}
          {step === 2 && <StepPrice form={form} update={update} canPushkin={event?.can_pushkin ?? false} />}
          {step === 3 && <StepCover form={form} update={update} />}
          {step === 4 && event && <StepReview event={event} />}
        </div>

        <FormErrors messages={shown} error={save.error} />
        {step < 4 && (
          <div className="row">
            {step > 0 && (
              <Button variant="secondary" size="lg" onClick={() => setStep(step - 1)}>
                Назад
              </Button>
            )}
            <Button variant="primary" size="lg" className="grow" loading={save.isPending} onClick={next}>
              {event ? "Сохранить и дальше" : "Создать черновик"}
            </Button>
          </div>
        )}
      </div>
    </main>
  );
}

function Draft({ me, id }: { me: Me; id: number }) {
  const [params] = useSearchParams();
  const orgParam = Number(params.get("org"));
  const orgId = Number.isInteger(orgParam) && orgParam > 0 ? orgParam : null;
  const stepParam = Number(params.get("step"));
  const initialStep = Number.isInteger(stepParam) && stepParam >= 0 && stepParam < STEPS.length ? stepParam : 0;
  const event = useQuery({ queryKey: ["manage", id], queryFn: () => fetchManage(id), enabled: id > 0 });

  if (!hasConsent(me)) {
    return (
      <main className="page page--narrow">
        <div className="stack stack--loose">
          <h1 className="h1">Новое событие</h1>
          <Card>
            <ConsentPrompt />
          </Card>
        </div>
      </main>
    );
  }
  if (id === 0) return <Editor key="new" event={null} orgId={orgId} initialStep={0} />;
  if (event.isPending) return <LoadingScreen />;
  if (event.isError) return <ErrorScreen message={event.error.message} onRetry={() => void event.refetch()} />;
  return <Editor key={id} event={event.data} orgId={event.data.organization_id} initialStep={initialStep} />;
}

/** Форма события в 5 шагов (FR-PUB): /draft/0 — новое (?org=<id> — от организации). */
export function DraftPage() {
  const id = Number(useParams().id);
  if (!Number.isInteger(id) || id < 0) return <ErrorScreen message="Событие не найдено." />;
  return (
    <RequireMax title="Предложить событие" text="Публиковать события можно после входа через MAX: туда придёт итог модерации и вопросы от жителей.">
      {(me) => <Draft me={me} id={id} />}
    </RequireMax>
  );
}
