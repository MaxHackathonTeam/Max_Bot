import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { ArrowLeft, BadgeCheck, CalendarX, ExternalLink, Info, MapPin, Settings } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, type Tier } from "../api/client";
import { fetchOrg } from "../api/organizer";
import { fetchOrgPublic, fetchOrgPublicEvents, orgKindLabel, type OrgPublic } from "../api/orgs";
import { useSession } from "../app/session";
import { DemoBadge } from "../components/Badges";
import { EventCardSkeleton, EventCardView } from "../components/EventCardView";
import { useOnVisible } from "../hooks/useOnVisible";
import { Badge } from "../ui/Badge";
import { Button, ButtonLink } from "../ui/Button";
import { EmptyState } from "../ui/EmptyState";
import { Tabs } from "../ui/Tabs";
import { ErrorBlock, ErrorScreen, LoadingScreen } from "./Status";

const TIER_LABEL: Record<Tier, string> = { official: "Официальные", community: "От жителей" };

/** Роль вошедшего в команде организации (null — не участник или гость без входа). */
function useOrgRole(id: number) {
  const session = useSession();
  const org = useQuery({
    queryKey: ["org", id],
    queryFn: () => fetchOrg(id),
    enabled: session.hasToken,
    retry: false,
  });
  return org.data?.my_role ?? null;
}

function OrgEvents({ org }: { org: OrgPublic }) {
  const [tier, setTier] = useState<Tier>(org.official_events || !org.community_events ? "official" : "community");
  const events = useInfiniteQuery({
    queryKey: ["org-public-events", org.id, tier],
    queryFn: ({ pageParam }) => fetchOrgPublicEvents(org.id, tier, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const sentinel = useOnVisible<HTMLDivElement>(
    () => void events.fetchNextPage(),
    events.hasNextPage && !events.isFetchingNextPage,
  );
  const items = events.data?.pages.flatMap((p) => p.items) ?? [];
  const count: Record<Tier, number> = { official: org.official_events, community: org.community_events };

  return (
    <section className="section stack" aria-labelledby="org-events-title">
      <h2 className="h3" id="org-events-title">
        Афиши организации
      </h2>
      <Tabs
        label="Источник событий"
        value={tier}
        onChange={setTier}
        items={(["official", "community"] as Tier[]).map((value) => ({
          value,
          label: `${TIER_LABEL[value]} · ${count[value]}`,
        }))}
      />
      {tier === "community" && (
        <p className="small muted">События, которые прошли модерацию как «от жителей». Уточняй детали перед поездкой.</p>
      )}
      {events.isPending && (
        <div className="feed__grid" aria-busy>
          <EventCardSkeleton />
          <EventCardSkeleton />
        </div>
      )}
      {events.isError && <ErrorBlock message={events.error.message} onRetry={() => void events.refetch()} />}
      {events.isSuccess && items.length === 0 && (
        <EmptyState
          icon={<CalendarX size={28} aria-hidden />}
          title="Ближайших событий нет"
          text={`Во вкладке «${TIER_LABEL[tier]}» у организации пока пусто.`}
        />
      )}
      {items.length > 0 && (
        <div className="feed__grid">
          {items.map((card) => (
            <EventCardView key={card.id} card={card} />
          ))}
        </div>
      )}
      {events.hasNextPage && (
        <div ref={sentinel} className="row">
          <Button variant="secondary" block loading={events.isFetchingNextPage} onClick={() => void events.fetchNextPage()}>
            Показать ещё
          </Button>
        </div>
      )}
    </section>
  );
}

function Contacts({ org }: { org: OrgPublic }) {
  const links = [
    org.website ? { href: org.website, label: "Сайт" } : null,
    org.vk_url ? { href: org.vk_url, label: "ВКонтакте" } : null,
  ].filter((l) => l !== null);
  if (!org.address && links.length === 0) return null;
  return (
    <section className="section stack" aria-labelledby="org-contacts-title">
      <h2 className="h3" id="org-contacts-title">
        Контакты
      </h2>
      {org.address && (
        <p className="org-contact">
          <MapPin size={16} aria-hidden /> {org.address}
        </p>
      )}
      {links.length > 0 && (
        <div className="org-links">
          {links.map((l) => (
            <a key={l.href} className="text-link" href={l.href} target="_blank" rel="noopener noreferrer nofollow">
              {l.label} <ExternalLink size={14} aria-hidden />
            </a>
          ))}
        </div>
      )}
    </section>
  );
}

/**
 * Открытый профиль организации (/org/<id>): без входа, только публичные поля.
 * Участникам команды — кнопка «Управление» (кабинет, `?tab=`).
 */
export function OrgPublicPage({ id }: { id: number }) {
  const org = useQuery({ queryKey: ["org-public", id], queryFn: () => fetchOrgPublic(id), retry: false });
  const role = useOrgRole(id);
  const manage = role && (
    <ButtonLink to={`/org/${id}?tab=events`} variant="secondary" size="sm" icon={<Settings size={16} aria-hidden />}>
      Управление
    </ButtonLink>
  );

  if (org.isPending) return <LoadingScreen />;
  if (org.isError) {
    const missing = org.error instanceof ApiError && org.error.status === 404;
    if (missing && manage)
      return (
        <main className="page page--narrow">
          <div className="state-screen stack stack--loose">
            <p className="muted">Открытый профиль скрыт: проверка организации отозвана. Кабинет команды доступен.</p>
            <div>{manage}</div>
          </div>
        </main>
      );
    return missing ? (
      <ErrorScreen message="Организация не найдена." />
    ) : (
      <ErrorScreen message={org.error.message} onRetry={() => void org.refetch()} />
    );
  }

  const data = org.data;
  const place = [data.locality?.name, orgKindLabel(data.kind)].filter(Boolean).join(" · ");
  return (
    <main className="page page--narrow">
      <div className="stack stack--loose">
        <Link to="/orgs" className="text-link small">
          <ArrowLeft size={14} aria-hidden /> Все организации
        </Link>
        <div className="page-head">
          <p className="eyebrow">{place}</p>
          <div className="org-head">
            <h1 className="h1">{data.name}</h1>
            {manage}
          </div>
          <div className="badges">
            {data.verified ? (
              <Badge tone="verified" icon={<BadgeCheck size={14} aria-hidden />}>
                Организатор проверен
              </Badge>
            ) : (
              <Badge>Не проверена</Badge>
            )}
            {data.is_demo && <DemoBadge />}
          </div>
        </div>

        {data.is_demo && (
          <div className="notice notice--demo">
            <Info size={18} aria-hidden />
            <span>Демо-организация: создана для показа сервиса, её события — демо-данные.</span>
          </div>
        )}

        {data.description?.trim() && (
          <section className="section stack" aria-labelledby="org-about-title">
            <h2 className="h3" id="org-about-title">
              О нас
            </h2>
            <p className="org-about">{data.description}</p>
          </section>
        )}

        <Contacts org={data} />
        <OrgEvents org={data} />
      </div>
    </main>
  );
}
