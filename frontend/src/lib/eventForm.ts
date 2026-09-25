// Форма события в 5 шагов (FR-PUB): состояние формы, перевод времени из пояса события
// в UTC и обратно, проверка шагов до отправки. Чистые функции, покрыты тестами.

import type {
  AgeRating,
  EventFields,
  EventManage,
  PriceType,
} from "../api/organizer";

export const STEPS = [
  "Главное",
  "Где и когда",
  "Цена и возраст",
  "Обложка и контакты",
  "Проверка",
] as const;
export const AGE_RATINGS: AgeRating[] = [0, 6, 12, 16, 18];

export interface SessionDraft {
  id: number | null;
  /** «YYYY-MM-DDTHH:mm» в часовом поясе события (значение input type=datetime-local). */
  starts: string;
  ends: string;
}

export interface EventForm {
  title: string;
  short_description: string;
  description: string;
  category: string | null;
  is_online: boolean;
  online_url: string;
  locality_id: number | null;
  locality_name: string | null;
  venue_id: number | null;
  venue_name: string | null;
  sessions: SessionDraft[];
  price_type: PriceType;
  price_min: string;
  price_max: string;
  pushkin_card: boolean;
  age_rating: AgeRating | null;
  registration_required: boolean;
  ticket_url: string;
  cover_media_id: number | null;
  cover_url: string | null;
  contacts: string;
  ramp: boolean;
  toilet: boolean;
  sign_language: boolean;
}

export function emptyForm(): EventForm {
  return {
    title: "",
    short_description: "",
    description: "",
    category: null,
    is_online: false,
    online_url: "",
    locality_id: null,
    locality_name: null,
    venue_id: null,
    venue_name: null,
    sessions: [{ id: null, starts: "", ends: "" }],
    price_type: "unknown",
    price_min: "",
    price_max: "",
    pushkin_card: false,
    age_rating: null,
    registration_required: false,
    ticket_url: "",
    cover_media_id: null,
    cover_url: null,
    contacts: "",
    ramp: false,
    toilet: false,
    sign_language: false,
  };
}

// --- Время в поясе события ----------------------------------------------------------------

function zonedParts(ms: number, timeZone: string): number[] {
  const formatter = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  const p: Record<string, number> = {};
  for (const part of formatter.formatToParts(new Date(ms)))
    p[part.type] = Number(part.value);
  return [p.year, p.month, p.day, p.hour, p.minute, p.second];
}

/** Смещение пояса относительно UTC в миллисекундах в момент ms. */
function offsetMs(ms: number, timeZone: string): number {
  const [y, mo, d, h, mi, s] = zonedParts(ms, timeZone);
  return Date.UTC(y, mo - 1, d, h, mi, s) - Math.floor(ms / 1000) * 1000;
}

const LOCAL_INPUT = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/;

/** «2026-09-27T18:00» в поясе события → ISO в UTC; null для пустого или неверного. */
export function zonedInputToIso(
  value: string,
  timeZone: string,
): string | null {
  const m = LOCAL_INPUT.exec(value);
  if (!m) return null;
  const [y, mo, d, h, mi] = m.slice(1).map(Number);
  const naive = Date.UTC(y, mo - 1, d, h, mi);
  // Две итерации: смещение могло смениться между naive и настоящим моментом.
  let utc = naive - offsetMs(naive, timeZone);
  utc = naive - offsetMs(utc, timeZone);
  return new Date(utc).toISOString();
}

/** ISO → «YYYY-MM-DDTHH:mm» в поясе события. */
export function isoToZonedInput(iso: string, timeZone: string): string {
  const [y, mo, d, h, mi] = zonedParts(new Date(iso).getTime(), timeZone);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${y}-${pad(mo)}-${pad(d)}T${pad(h)}:${pad(mi)}`;
}

// --- Форма ↔ API ------------------------------------------------------------------------

export function fromManage(event: EventManage): EventForm {
  const tz = event.timezone;
  const sessions = event.sessions
    .filter((s) => s.status !== "cancelled")
    .map((s) => ({
      id: s.id,
      starts: isoToZonedInput(s.starts_at, tz),
      ends: s.ends_at ? isoToZonedInput(s.ends_at, tz) : "",
    }));
  return {
    title: event.title,
    short_description: event.short_description ?? "",
    description: event.description ?? "",
    category: event.category,
    is_online: event.is_online,
    online_url: event.online_url ?? "",
    locality_id: event.locality_id,
    locality_name: event.locality_name,
    venue_id: event.venue?.id ?? null,
    venue_name: event.venue?.name ?? null,
    sessions: sessions.length > 0 ? sessions : emptyForm().sessions,
    price_type: event.price_type,
    price_min: event.price_min ?? "",
    price_max: event.price_max ?? "",
    pushkin_card: event.pushkin_card,
    age_rating: (AGE_RATINGS as number[]).includes(event.age_rating ?? -1)
      ? (event.age_rating as AgeRating)
      : null,
    registration_required: event.registration_required,
    ticket_url: event.ticket_url ?? "",
    cover_media_id: event.cover_media_id,
    cover_url: event.cover_url,
    contacts: event.contacts ?? "",
    ramp: Boolean(event.accessibility?.ramp),
    toilet: Boolean(event.accessibility?.toilet),
    sign_language: Boolean(event.accessibility?.sign_language),
  };
}

const orNull = (value: string) => (value.trim() ? value.trim() : null);

/** Поля шага для PATCH. Время сеансов переводится в UTC по поясу события. */
export function stepPayload(
  step: number,
  form: EventForm,
  timeZone: string,
): EventFields {
  switch (step) {
    case 0:
      return {
        title: form.title.trim(),
        short_description: orNull(form.short_description),
        description: orNull(form.description),
        category: form.category,
      };
    case 1:
      return {
        is_online: form.is_online,
        online_url: form.is_online ? orNull(form.online_url) : null,
        locality_id: form.locality_id,
        venue_id: form.is_online ? null : form.venue_id,
        sessions: form.sessions
          .map((s) => ({
            id: s.id,
            starts_at: zonedInputToIso(s.starts, timeZone),
            ends_at: s.ends ? zonedInputToIso(s.ends, timeZone) : null,
          }))
          .filter(
            (
              s,
            ): s is {
              id: number | null;
              starts_at: string;
              ends_at: string | null;
            } => s.starts_at !== null,
          ),
      };
    case 2: {
      const paid = form.price_type === "paid";
      return {
        price_type: form.price_type,
        price_min: paid ? orNull(form.price_min) : null,
        price_max: paid ? orNull(form.price_max) : null,
        pushkin_card: form.pushkin_card,
        age_rating: form.age_rating,
        registration_required: form.registration_required,
        ticket_url: orNull(form.ticket_url),
      };
    }
    case 3:
      return {
        cover_media_id: form.cover_media_id,
        contacts: orNull(form.contacts),
        accessibility: {
          ramp: form.ramp,
          toilet: form.toilet,
          sign_language: form.sign_language,
        },
      };
    default:
      return {};
  }
}

/** Сообщения о незаполненном на шаге; пустой список — можно дальше. */
export function stepErrors(
  step: number,
  form: EventForm,
  now: Date = new Date(),
  timeZone = "UTC",
): string[] {
  const errors: string[] = [];
  if (step === 0) {
    if (form.title.trim().length < 3)
      errors.push("Название — хотя бы 3 символа");
    if (!form.category) errors.push("Выбери категорию");
  }
  if (step === 1) {
    if (form.is_online && !/^https:\/\/\S+$/.test(form.online_url.trim())) {
      errors.push("Ссылка на трансляцию должна начинаться с https://");
    }
    if (!form.is_online && form.locality_id === null)
      errors.push("Выбери населённый пункт");
    const starts = form.sessions.map((s) =>
      zonedInputToIso(s.starts, timeZone),
    );
    if (starts.some((s) => s === null))
      errors.push("Укажи дату и время начала каждого сеанса");
    else if (!starts.some((s) => new Date(s as string) > now))
      errors.push("Нужен хотя бы один сеанс в будущем");
    form.sessions.forEach((s, i) => {
      const start = zonedInputToIso(s.starts, timeZone);
      const end = s.ends ? zonedInputToIso(s.ends, timeZone) : null;
      if (start && end && new Date(end) <= new Date(start))
        errors.push(`Сеанс ${i + 1}: конец раньше начала`);
    });
  }
  if (step === 2) {
    if (form.price_type === "unknown") errors.push("Укажи, платное ли событие");
    if (form.price_type === "paid") {
      const min = Number(form.price_min);
      const max = form.price_max ? Number(form.price_max) : min;
      if (!form.price_min || !Number.isFinite(min) || min < 0)
        errors.push("Укажи цену билета");
      else if (!Number.isFinite(max) || max < min)
        errors.push("Максимальная цена меньше минимальной");
    }
    if (
      form.ticket_url.trim() &&
      !/^https:\/\/\S+$/.test(form.ticket_url.trim())
    ) {
      errors.push("Ссылка на билеты должна начинаться с https://");
    }
  }
  return errors;
}
