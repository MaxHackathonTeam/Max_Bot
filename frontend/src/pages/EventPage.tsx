import { Button, CellList, CellSimple, Typography } from "@maxhub/max-ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
import { useCategories } from "../app/profile";
import { haptic, openExternal, shareContent, isMobileMax } from "../bridge/actions";
import { getWebApp } from "../bridge/webApp";
import { DemoBadge, EventBadges } from "../components/Badges";
import { ConsentPrompt } from "../components/ConsentPrompt";
import {
  formatDate,
  formatDistance,
  formatPrice,
  formatTime,
  formatWhen,
} from "../lib/format";
import { ErrorScreen, LoadingScreen } from "./Status";

const SHARE_NOTES = {
  shared: null,
  copied: "Ссылка скопирована — отправь её в чат",
  opened: null,
} as const;

function sessionText(s: SessionInfo, tz: string): string {
  const start = formatWhen(s.starts_at, tz);
  const end = s.ends_at ? `–${formatTime(s.ends_at, tz)}` : "";
  const cancelled = s.status === "cancelled" ? " · отменён" : "";
  return `${start}${end}${cancelled}`;
}

function SessionRow({
  event,
  session,
}: {
  event: EventDetail;
  session: SessionInfo;
}) {
  const client = useQueryClient();
  const saved = event.saved_session_ids.includes(session.id);
  const [needConsent, setNeedConsent] = useState(false);
  const toggle = useMutation({
    mutationFn: () =>
      saved
        ? unsaveEvent(event.id, session.id)
        : saveEvent(event.id, session.id),
    onSuccess: (out) => {
      if (!saved) haptic("success");
      client.setQueryData<EventDetail>(["event", event.id], (old) =>
        old ? { ...old, saved_session_ids: out.saved_session_ids } : old,
      );
      void client.invalidateQueries({ queryKey: ["saved"] });
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === "consent_required")
        setNeedConsent(true);
    },
  });
  const disabled = event.is_past || session.status === "cancelled";

  return (
    <div className="session stack">
      <div className="row row--between">
        <Typography.Body variant="medium">
          {sessionText(session, event.timezone)}
        </Typography.Body>
        <Button
          size="small"
          variant={saved ? "secondary" : "primary"}
          loading={toggle.isPending}
          disabled={disabled && !saved}
          onClick={() => toggle.mutate()}
          aria-pressed={saved}
        >
          {saved ? "✓ Иду" : "⭐ Пойду"}
        </Button>
      </div>
      {toggle.isError && !needConsent && (
        <Typography.Body variant="small" className="error">
          {toggle.error.message}
        </Typography.Body>
      )}
      {needConsent && (
        <ConsentPrompt
          onDone={() => {
            setNeedConsent(false);
            toggle.mutate();
          }}
        />
      )}
    </div>
  );
}

/** Карточка события (FR-EV-1…4). */
export function EventPage() {
  const id = Number(useParams().id);
  const valid = Number.isInteger(id) && id > 0;
  const event = useQuery({
    queryKey: ["event", id],
    queryFn: () => fetchEvent(id),
    enabled: valid,
  });
  const categories = useCategories();
  const [shareNote, setShareNote] = useState<string | null>(null);

  if (!valid) return <ErrorScreen message="Событие не найдено" />;
  if (event.isPending) return <LoadingScreen />;
  if (event.isError) {
    return (
      <ErrorScreen
        message={event.error.message}
        onRetry={() => void event.refetch()}
      />
    );
  }

  const e = event.data;
  const category = categories.data?.find((c) => c.slug === e.category);
  const distance = formatDistance(e.distance_km);
  const share = async () => {
    const when = e.sessions[0]
      ? `, ${formatWhen(e.sessions[0].starts_at, e.timezone)}`
      : "";
    const bridge = getWebApp();
    if (isMobileMax(bridge?.platform) && bridge?.shareMaxContent) {
      try {
        const card = await prepareShareCard(e.id);
        await bridge.shareMaxContent({ mid: card.mid, chatType: card.chat_type });
        setShareNote(null);
        return;
      } catch {
        // Карточка требует доступного бота; обычная ссылка остаётся fallback.
      }
    }
    const result = await shareContent(`${e.title}${when}`, e.share_url);
    setShareNote(SHARE_NOTES[result]);
  };
  const auto = (field: string) =>
    e.ai_fields.includes(field) ? (
      <span className="muted"> · определено автоматически</span>
    ) : null;

  return (
    <main className="screen">
      {e.cover_url && <img className="cover" src={e.cover_url} alt="" />}
      {e.is_demo && (
        <div className="notice notice--demo">
          <DemoBadge /> Это демонстрационное событие — его нет в реальной афише.
        </div>
      )}
      {e.is_past && <div className="notice">Прошло</div>}
      {e.status === "cancelled" && (
        <div className="notice notice--danger">Отменено</div>
      )}

      {category && (
        <Typography.Label variant="medium-strong" className="accent">
          {category.emoji} {category.name}
          {auto("category")}
        </Typography.Label>
      )}
      <Typography.Headline variant="large-strong">
        {e.title}
      </Typography.Headline>
      <EventBadges card={e} />

      <Typography.Body variant="large">
        {formatPrice(e)}
        {e.age_rating !== null && ` · ${e.age_rating}+`}
      </Typography.Body>

      {e.sessions.length > 0 && (
        <section className="stack">
          <Typography.Label variant="medium-strong">
            {e.sessions.length > 1 ? "Сеансы" : "Когда"}
          </Typography.Label>
          {e.sessions.map((s) => (
            <SessionRow key={s.id} event={e} session={s} />
          ))}
        </section>
      )}

      {(e.ticket_url || e.online_url) && (
        <div className="row">
          {e.ticket_url && (
            <Button
              size="large"
              stretched
              onClick={() => openExternal(e.ticket_url as string)}
            >
              {e.registration_required ? "📝 Регистрация" : "🎟 Билеты"}
            </Button>
          )}
          {e.online_url && (
            <Button
              size="large"
              variant="secondary"
              stretched
              onClick={() => openExternal(e.online_url as string)}
            >
              🔗 Трансляция
            </Button>
          )}
        </div>
      )}

      {e.venue && (
        <section className="stack">
          <Typography.Label variant="medium-strong">Где</Typography.Label>
          <Typography.Body variant="medium">
            {e.venue.name}
            {e.venue.address && `, ${e.venue.address}`}
            {e.locality && ` (${e.locality.name})`}
            {distance && <span className="muted"> · {distance}</span>}
          </Typography.Body>
          {e.map_url && (
            <Button
              size="medium"
              variant="secondary"
              onClick={() => openExternal(e.map_url as string)}
            >
              🗺 Открыть в Яндекс.Картах
            </Button>
          )}
        </section>
      )}

      {e.description && (
        <section className="stack">
          <Typography.Label variant="medium-strong">О событии</Typography.Label>
          <Typography.Body variant="medium" className="pre-line">
            {e.description}
          </Typography.Body>
          {e.tags.length > 0 && (
            <Typography.Body variant="small" className="muted">
              {e.tags.map((t) => `#${t}`).join(" ")}
              {auto("tags")}
            </Typography.Body>
          )}
        </section>
      )}

      {e.contacts && (
        <Typography.Body variant="medium">☎️ {e.contacts}</Typography.Body>
      )}

      {e.org && (
        <CellList mode="island" filled>
          <CellSimple
            asChild
            showChevron
            title={e.org.name}
            subtitle={e.org.verified ? "✓ Организатор проверен" : "Организатор"}
          >
            <Link to={`/org/${e.org.id}`} />
          </CellSimple>
        </CellList>
      )}

      <Button
        size="large"
        variant="secondary"
        stretched
        onClick={() => void share()}
      >
        📤 Поделиться
      </Button>
      {shareNote && (
        <Typography.Body variant="small" className="muted" role="status">
          {shareNote}
        </Typography.Body>
      )}

      <Typography.Body variant="small" className="muted" data-testid="source">
        Источник: {e.source.label} · обновлено {formatDate(e.source.updated_at)}
      </Typography.Body>
    </main>
  );
}
