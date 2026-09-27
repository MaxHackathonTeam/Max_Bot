import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BadgeCheck,
  Ban,
  Bookmark,
  BookmarkCheck,
  CalendarX,
  ChevronRight,
  Clock,
  ExternalLink,
  Info,
  MapPin,
  MapPinned,
  MonitorPlay,
  Phone,
  Share2,
  Ticket,
  UserRound,
} from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ApiError,
  fetchEvent,
  prepareShareCard,
  saveEvent,
  unsaveEvent,
  type EventDetail,
  type SessionInfo,
} from "../api/client";
import { useSession } from "../app/session";
import { haptic, isMobileMax, openExternal, shareContent } from "../bridge/actions";
import { getWebApp } from "../bridge/webApp";
import { DemoBadge, EventBadges } from "../components/Badges";
import { CategoryLabel } from "../components/CategoryLabel";
import { ConsentPrompt } from "../components/ConsentPrompt";
import { formatDate, formatDateParts, formatDistance, formatPrice, formatTime, formatWhen } from "../lib/format";
import { Button } from "../ui/Button";
import { cx } from "../ui/classes";
import { Sheet } from "../ui/Sheet";
import { Loading, Skeleton } from "../ui/Skeleton";
import { useToast } from "../ui/toastContext";
import { ErrorScreen } from "./Status";

function EventSkeleton() {
  return (
    <main className="page">
      <Loading label="Загружаем событие">
        <div className="event">
          <div className="event__main">
            <Skeleton width={120} height={14} />
            <Skeleton width="80%" height={34} />
            <Skeleton width="50%" height={20} />
            <Skeleton height={90} radius={14} />
          </div>
          <div className="event__side">
            <Skeleton height={180} radius={14} />
          </div>
        </div>
      </Loading>
    </main>
  );
}

/** Строка сеанса с кнопкой «Пойду». Без аккаунта сначала создаём гостя. */
function SessionRow({ event, session }: { event: EventDetail; session: SessionInfo }) {
  const client = useQueryClient();
  const { ensureAccount } = useSession();
  const toast = useToast();
  const saved = event.saved_session_ids.includes(session.id);
  const [needConsent, setNeedConsent] = useState(false);
  const toggle = useMutation({
    mutationFn: async () => {
      await ensureAccount();
      return saved ? unsaveEvent(event.id, session.id) : saveEvent(event.id, session.id);
    },
    onSuccess: (out) => {
      if (!saved) haptic("success");
      client.setQueryData<EventDetail>(["event", event.id], (old) =>
        old ? { ...old, saved_session_ids: out.saved_session_ids } : old,
      );
      void client.invalidateQueries({ queryKey: ["saved"] });
      toast.show(saved ? "Убрали из «Пойду»" : "Добавили в «Пойду»");
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === "consent_required") setNeedConsent(true);
      else toast.show(error.message, "error");
    },
  });
  const cancelled = session.status === "cancelled";
  const disabled = event.is_past || cancelled;
  const parts = formatDateParts(session.starts_at, event.timezone);
  const end = session.ends_at ? `–${formatTime(session.ends_at, event.timezone)}` : "";

  return (
    <div className="session-row">
      <div className="session-row__when">
        <span className="session-row__date">
          {parts.day} {parts.month}, {parts.weekday}
        </span>
        <span className="session-row__time">
          {parts.time}
          {end}
          {cancelled && " · отменён"}
        </span>
      </div>
      <Button
        size="sm"
        variant={saved ? "secondary" : "primary"}
        className={cx(saved && "btn--on")}
        loading={toggle.isPending}
        disabled={disabled && !saved}
        aria-pressed={saved}
        icon={saved ? <BookmarkCheck size={16} aria-hidden /> : <Bookmark size={16} aria-hidden />}
        onClick={() => toggle.mutate()}
      >
        {saved ? "Иду" : "Пойду"}
      </Button>
      <Sheet open={needConsent} onClose={() => setNeedConsent(false)} title="Сохраним в «Пойду»">
        <ConsentPrompt
          onDone={() => {
            setNeedConsent(false);
            toggle.mutate();
          }}
        />
      </Sheet>
    </div>
  );
}

/** Карточка события (FR-EV-1…4). */
export function EventPage() {
  const id = Number(useParams().id);
  const valid = Number.isInteger(id) && id > 0;
  const event = useQuery({ queryKey: ["event", id], queryFn: () => fetchEvent(id), enabled: valid });
  const toast = useToast();
  const [sharing, setSharing] = useState(false);

  if (!valid) return <ErrorScreen message="Событие не найдено" />;
  if (event.isPending) return <EventSkeleton />;
  if (event.isError) return <ErrorScreen message={event.error.message} onRetry={() => void event.refetch()} />;

  const e = event.data;
  const distance = formatDistance(e.distance_km);
  const first = e.sessions[0];
  const when = first ? formatDateParts(first.starts_at, e.timezone) : null;
  const free = e.price_type === "free";
  const auto = (field: string) => (e.ai_fields.includes(field) ? <span className="muted"> · определено автоматически</span> : null);

  const share = async () => {
    setSharing(true);
    try {
      const text = `${e.title}${first ? `, ${formatWhen(first.starts_at, e.timezone)}` : ""}`;
      const webLink = `${window.location.origin}/event/${e.id}`;
      const bridge = getWebApp();
      // В мобильном MAX — карточка события от бота; если бот недоступен, обычная ссылка.
      if (bridge?.initData && isMobileMax(bridge.platform) && bridge.shareMaxContent) {
        try {
          const card = await prepareShareCard(e.id);
          await bridge.shareMaxContent({ mid: card.mid, chatType: card.chat_type });
          return;
        } catch {
          // fallback ниже
        }
      }
      const result = await shareContent({ text, maxLink: e.share_url, webLink });
      if (result === "copied") toast.show("Ссылка скопирована — отправь её в чат");
      if (result === "failed") toast.show(`Скопируй ссылку: ${webLink}`, "info");
    } finally {
      setSharing(false);
    }
  };

  return (
    <main className="page">
      <div className="event">
        <div className="event__main">
          {e.cover_url && <img className="event__cover" src={e.cover_url} alt="" />}
          {e.is_demo && (
            <div className="notice notice--demo">
              <DemoBadge />
              <span>Это демонстрационное событие — его нет в реальной афише.</span>
            </div>
          )}
          {e.is_past && (
            <div className="notice">
              <CalendarX size={18} aria-hidden />
              <span>Событие уже прошло</span>
            </div>
          )}
          {e.status === "cancelled" && (
            <div className="notice notice--danger">
              <Ban size={18} aria-hidden />
              <span>Событие отменено</span>
            </div>
          )}

          <div className="page-head">
            <CategoryLabel slug={e.category} suffix={auto("category")} />
            <h1 className="h1">{e.title}</h1>
            <EventBadges card={e} />
          </div>

          <div className="stack">
            {when && (
              <p className="fact">
                <Clock size={18} aria-hidden />
                <span>
                  {when.long}, {when.time}
                  {e.sessions.length > 1 && <span className="muted"> · сеансов: {e.sessions.length}</span>}
                </span>
              </p>
            )}
            {e.venue && (
              <p className="fact">
                <MapPin size={18} aria-hidden />
                <span>
                  {e.venue.name}
                  {e.venue.address && `, ${e.venue.address}`}
                  {e.locality && ` (${e.locality.name})`}
                  {distance && <span className="muted"> · {distance}</span>}
                </span>
              </p>
            )}
            {e.contacts && (
              <p className="fact">
                <Phone size={18} aria-hidden />
                <span>{e.contacts}</span>
              </p>
            )}
            {e.map_url && (
              <div>
                <Button variant="secondary" size="sm" icon={<MapPinned size={16} aria-hidden />} onClick={() => openExternal(e.map_url as string)}>
                  Открыть на карте
                </Button>
              </div>
            )}
          </div>

          {e.description && (
            <section className="stack">
              <h2 className="h3">О событии</h2>
              <p className="pre-line">{e.description}</p>
              {e.tags.length > 0 && (
                <p className="small muted">
                  {e.tags.map((t) => `#${t}`).join(" ")}
                  {auto("tags")}
                </p>
              )}
            </section>
          )}

          {e.org && (
            <div className="list">
              <Link className="list-row" to={`/org/${e.org.id}`}>
                <span className="list-row__icon">
                  {e.org.verified ? <BadgeCheck size={18} aria-hidden /> : <UserRound size={18} aria-hidden />}
                </span>
                <span className="list-row__text">
                  <span className="list-row__title">{e.org.name}</span>
                  <span className="list-row__subtitle">{e.org.verified ? "Организатор проверен" : "Организатор"}</span>
                </span>
                <ChevronRight size={18} className="list-row__chevron" aria-hidden />
              </Link>
            </div>
          )}

          <p className="small muted" data-testid="source">
            <Info size={14} aria-hidden /> Источник: {e.source.label} · обновлено {formatDate(e.source.updated_at)}
          </p>
        </div>

        <aside className="event__side">
          <div className="stub">
            <div className="stub__head">
              <span className={cx("price", free && "price--free")}>
                {formatPrice(e)}
                {e.age_rating !== null && ` · ${e.age_rating}+`}
              </span>
              {e.is_demo && <DemoBadge />}
            </div>
            <div className="stub__body">
              {e.sessions.length > 0 ? (
                <div>
                  {e.sessions.map((s) => (
                    <SessionRow key={s.id} event={e} session={s} />
                  ))}
                </div>
              ) : (
                <p className="muted">Дата уточняется.</p>
              )}
              {e.ticket_url && (
                <Button variant="dark" block icon={<Ticket size={18} aria-hidden />} onClick={() => openExternal(e.ticket_url as string)}>
                  {e.registration_required ? "Регистрация" : "Билеты"}
                  <ExternalLink size={14} aria-hidden />
                </Button>
              )}
              {e.online_url && (
                <Button variant="secondary" block icon={<MonitorPlay size={18} aria-hidden />} onClick={() => openExternal(e.online_url as string)}>
                  Трансляция
                </Button>
              )}
              <Button variant="ghost" block loading={sharing} icon={<Share2 size={18} aria-hidden />} onClick={() => void share()}>
                Поделиться
              </Button>
            </div>
          </div>
        </aside>
      </div>
    </main>
  );
}
