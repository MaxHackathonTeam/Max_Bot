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
  Search,
  Send,
  Trash,
  TriangleAlert,
  X,
} from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import type { Me } from "../api/client";
import {
  cancelEvent,
  checkEvent,
  createEvent,
  createVenue,
  deleteEvent,
  fetchManage,
  fetchMyOrgs,
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
import { EventCardView } from "../components/EventCardView";
import { FormErrors } from "../components/FormErrors";
import { LocalityPicker } from "../components/LocalityPicker";
import { RequireMax } from "../components/RequireMax";
import { useDebounced } from "../hooks/useDebounced";
import { categoryLook } from "../lib/categories";
import {
  AGE_RATINGS,
  emptyForm,
  firstInvalidStep,
  fromManage,
  manageToCard,
  STEP,
  STEPS,
  stepErrors,
  stepOfField,
  stepPayload,
  type EventForm,
} from "../lib/eventForm";
import { readLocal, writeLocal } from "../lib/storage";
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

function StepWhen({ form, update, timeZone }: { form: EventForm; update: Update; timeZone: string }) {
  const setSession = (i: number, patch: Partial<EventForm["sessions"][number]>) =>
    update({ sessions: form.sessions.map((s, j) => (j === i ? { ...s, ...patch } : s)) });
  return (
    <Group title="Сеансы">
      <p className="small muted">
        Время — местное для места события ({timeZone}). Если место ещё не выбрано, на шаге «Где» время пересчитаем.
      </p>
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
  );
}

function StepWhere({ form, update, orgId }: { form: EventForm; update: Update; orgId: number | null }) {
  const [picking, setPicking] = useState(false);
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
      <Sheet open={picking} onClose={() => setPicking(false)} title="Где пройдёт событие">
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

export function Summary({ event }: { event: EventManage }) {
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

/** Правила модерации до отправки: блокирующие нарушения и советы (POST /events/{id}/check). */
function Precheck({ event, onFix }: { event: EventManage; onFix: (step: number) => void }) {
  const check = useQuery({
    queryKey: ["check", event.id, event.updated_at],
    queryFn: () => checkEvent(event.id),
  });
  if (check.isPending) return <p className="small muted">Проверяем по правилам…</p>;
  if (check.isError) return <FormErrors error={check.error} />;
  const { violations, warnings } = check.data;
  if (violations.length === 0 && warnings.length === 0)
    return (
      <div className="notice" role="status">
        <BadgeCheck size={18} aria-hidden />
        <span>По правилам всё в порядке.</span>
      </div>
    );
  return (
    <div className="stack stack--tight" role="status">
      {violations.length > 0 && (
        <p className="small">С этими ошибками правила отклонят заявку сразу — исправь их перед отправкой.</p>
      )}
      {violations.map((v) => (
        <div key={`${v.code}-${v.field}`} className="notice notice--danger">
          <CircleAlert size={18} aria-hidden />
          <span>
            {v.message}{" "}
            <button type="button" className="link-btn" onClick={() => onFix(stepOfField(v.field))}>
              Исправить
            </button>
          </span>
        </div>
      ))}
      {warnings.map((w) => (
        <div key={w} className="notice notice--sun">
          <TriangleAlert size={18} aria-hidden />
          <span>{w}</span>
        </div>
      ))}
    </div>
  );
}

function StepReview({ event, onFix }: { event: EventManage; onFix: (step: number) => void }) {
  const client = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  const set = (e: EventManage) => client.setQueryData(["manage", e.id], e);
  const official = event.trust_tier === "official";
  const submit = useMutation({
    mutationFn: () => submitEvent(event.id),
    onSuccess: (e) => {
      set(e);
      if (e.status === "rejected") toast.show(`Правила отклонили: ${e.moderation_reason ?? "см. замечания"}`, "error");
      else toast.show("Отправили на проверку — итог придёт в бот");
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
      navigate(event.organization_id ? `/org/${event.organization_id}?tab=events` : "/my", { replace: true });
    },
  });
  const canSubmit = event.status === "draft" || event.status === "rejected";
  return (
    <>
      <section className="stack" aria-label="Как карточка выглядит в ленте">
        <p className="eyebrow">Так увидят в ленте</p>
        <div className="feed__grid feed__grid--one">
          <EventCardView card={manageToCard(event)} />
        </div>
      </section>
      <Summary event={event} />
      {canSubmit && <Precheck event={event} onFix={onFix} />}
      {canSubmit && (
        <p className="small muted">
          {official
            ? "Событие проверит модерация, после этого оно появится в «Официальных» с отметкой «Организатор проверен». Результат пришлём в бот."
            : "Событие проверит модерация, после этого оно появится в «От жителей». Результат пришлём в бот."}
        </p>
      )}
      <FormErrors error={submit.error ?? cancel.error ?? remove.error} />
      {canSubmit && (
        <Button
          variant="primary"
          size="lg"
          block
          loading={submit.isPending}
          icon={<Send size={18} aria-hidden />}
          onClick={() => submit.mutate()}
        >
          Отправить на проверку
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

const BACKUP = "afisha.draft_backup.";
const AUTOSAVE_MS = 1500;
/** Шаги, которые сохраняются на сервер сами: без сеансов и места (там пересчёт пояса). */
const AUTOSAVE_STEPS = new Set<number>([STEP.main, STEP.price, STEP.cover]);

interface Backup {
  form: EventForm;
  saved_at: string;
}

function readBackup(key: string): Backup | null {
  try {
    const raw = readLocal(BACKUP + key);
    return raw ? (JSON.parse(raw) as Backup) : null;
  } catch {
    return null;
  }
}

function writeBackup(key: string, form: EventForm | null): void {
  writeLocal(BACKUP + key, form ? JSON.stringify({ form, saved_at: new Date().toISOString() }) : null);
}

/** От чьего имени: от себя («От жителей») или от проверенной организации («Официальные»). */
export function TierChoice({ orgId, onChange }: { orgId: number | null; onChange: (id: number | null) => void }) {
  const orgs = useQuery({ queryKey: ["orgs"], queryFn: fetchMyOrgs, staleTime: 60_000 });
  const verified = (orgs.data ?? []).filter((o) => o.verified);
  if (verified.length === 0) return null;
  return (
    <Group title="Куда попадёт афиша">
      <div className="chips">
        <Chip pressed={orgId === null} onClick={() => onChange(null)}>
          От жителей · от себя
        </Chip>
        {verified.map((o) => (
          <Chip key={o.id} pressed={orgId === o.id} icon={<BadgeCheck size={15} aria-hidden />} onClick={() => onChange(o.id)}>
            Официальные · {o.name}
          </Chip>
        ))}
      </div>
    </Group>
  );
}

export function Editor({ event, orgId, initialStep }: { event: EventManage | null; orgId: number | null; initialStep: number }) {
  const client = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  const backupKey = event ? String(event.id) : "new";
  const [restore, setRestore] = useState<Backup | null>(() => {
    const backup = readBackup(backupKey);
    // Копия старше сохранённого на сервере не нужна.
    return backup && (!event || backup.saved_at > event.updated_at) ? backup : null;
  });
  const [form, setForm] = useState<EventForm>(() => (event ? fromManage(event) : emptyForm()));
  const [step, setStep] = useState(event ? initialStep : 0);
  const [shown, setShown] = useState<string[]>([]);
  const [owner, setOwner] = useState<number | null>(orgId);
  const dirty = useRef(false);
  const update: Update = (patch) => {
    dirty.current = true;
    setForm((f) => ({ ...f, ...patch }));
  };
  const timeZone = event?.timezone ?? "Europe/Moscow";
  const organization = event?.organization_id ?? owner;
  const editable = !event || ["draft", "rejected"].includes(event.status);

  const persist = async (current: number): Promise<EventManage> => {
    if (!event) throw new Error("Черновик ещё не создан");
    if (current === STEP.where) {
      // Сначала место: от него зависит пояс, в котором заданы сеансы.
      const placed = await patchEvent(event.id, stepPayload(STEP.where, form, timeZone));
      if (placed.timezone === timeZone) return placed;
      return patchEvent(event.id, stepPayload(STEP.when, form, placed.timezone));
    }
    return patchEvent(event.id, stepPayload(current, form, timeZone));
  };

  const save = useMutation({
    mutationFn: async (current: number): Promise<EventManage | null> => {
      if (!event) {
        const created = await createEvent({ ...stepPayload(0, form, timeZone), title: form.title.trim(), organization_id: owner });
        writeBackup("new", null);
        toast.show("Черновик создан");
        navigate(`/draft/${created.id}?step=${STEP.when}`, { replace: true });
        return null;
      }
      return persist(current);
    },
    onSuccess: (saved, current) => {
      if (!saved) return;
      client.setQueryData(["manage", saved.id], saved);
      writeBackup(backupKey, null);
      dirty.current = false;
      // Новые сеансы получили id — иначе следующее сохранение создаст их повторно.
      setForm((f) => ({ ...f, sessions: fromManage(saved).sessions }));
      setStep(current + 1);
      window.scrollTo({ top: 0 });
    },
  });

  // Автосохранение: копия на устройстве всегда, на сервер — для простых шагов без ошибок.
  const autosave = useMutation({
    mutationFn: (current: number) => persist(current),
    onSuccess: (saved) => {
      client.setQueryData(["manage", saved.id], saved);
      writeBackup(backupKey, null);
      dirty.current = false;
    },
  });
  useEffect(() => {
    if (!dirty.current || !editable) return;
    const timer = window.setTimeout(() => {
      writeBackup(backupKey, form);
      if (event && AUTOSAVE_STEPS.has(step) && stepErrors(step, form, new Date(), timeZone).length === 0)
        autosave.mutate(step);
    }, AUTOSAVE_MS);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- сохраняем только по изменению формы
  }, [form]);

  const goto = (target: number) => {
    setShown([]);
    setStep(target);
  };
  const next = () => {
    const errors = stepErrors(step, form, new Date(), timeZone);
    setShown(errors);
    if (errors.length > 0) return;
    // На «Проверку» — только когда все шаги заполнены.
    if (step === STEP.cover) {
      const bad = firstInvalidStep(form, new Date(), timeZone);
      if (bad !== null) {
        setShown([`Не заполнен шаг «${STEPS[bad]}»`, ...stepErrors(bad, form, new Date(), timeZone)]);
        setStep(bad);
        return;
      }
    }
    save.mutate(step);
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
              <Badge>{organization ? "Организация не проверена · «От жителей»" : "От жителей"}</Badge>
            )}
          </div>
        </div>
        {event?.moderation_reason && ["rejected", "hidden", "draft"].includes(event.status) && (
          <div className="notice notice--danger">
            <CircleAlert size={18} aria-hidden />
            <span>
              {event.status === "draft" ? "Вернули на доработку" : "Причина"}: {event.moderation_reason}
            </span>
          </div>
        )}
        {restore && (
          <div className="notice" role="status">
            <span>Есть несохранённые правки с этого устройства.</span>
            <div className="row">
              <Button
                size="sm"
                onClick={() => {
                  update(restore.form);
                  setRestore(null);
                }}
              >
                Вернуть
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  writeBackup(backupKey, null);
                  setRestore(null);
                }}
              >
                Не нужно
              </Button>
            </div>
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
              onClick={() => goto(i)}
            >
              <span className="step__num">{i + 1}</span>
              {title}
            </button>
          ))}
        </nav>

        <div className="stack">
          {step === STEP.main && !event && <TierChoice orgId={owner} onChange={setOwner} />}
          {step === STEP.main && <StepMain form={form} update={update} />}
          {step === STEP.when && <StepWhen form={form} update={update} timeZone={timeZone} />}
          {step === STEP.where && <StepWhere form={form} update={update} orgId={organization} />}
          {step === STEP.price && <StepPrice form={form} update={update} canPushkin={event?.can_pushkin ?? false} />}
          {step === STEP.cover && <StepCover form={form} update={update} />}
          {step === STEP.review && event && <StepReview event={event} onFix={goto} />}
        </div>

        <FormErrors messages={shown} error={save.error} />
        {step < STEP.review && (
          <div className="row">
            {step > 0 && (
              <Button variant="secondary" size="lg" onClick={() => goto(step - 1)}>
                Назад
              </Button>
            )}
            <Button variant="primary" size="lg" className="grow" loading={save.isPending} onClick={next}>
              {event ? "Сохранить и дальше" : "Создать черновик"}
            </Button>
          </div>
        )}
        {event && editable && (
          <p className="small muted" aria-live="polite">
            {autosave.isPending ? "Сохраняем…" : autosave.isError ? "Не удалось сохранить автоматически — нажми «Сохранить и дальше»." : "Правки сохраняются сами."}
          </p>
        )}
      </div>
    </main>
  );
}

export function Draft({ me, id }: { me: Me; id: number }) {
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

/** Форма события в 6 шагов (FR-PUB): /draft/0 — новое (?org=<id> — от организации). */
export function DraftPage() {
  const id = Number(useParams().id);
  if (!Number.isInteger(id) || id < 0) return <ErrorScreen message="Событие не найдено." />;
  return (
    <RequireMax title="Добавить афишу" text="Чтобы добавить афишу, войди через MAX: туда придёт итог модерации.">
      {(me) => <Draft me={me} id={id} />}
    </RequireMax>
  );
}
