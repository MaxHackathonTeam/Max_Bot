import { Button, Input, Spinner, Typography } from "@maxhub/max-ui";
import { useInfiniteQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { fetchEvents, type Me, type Radius, type Tier } from "../api/client";
import { useLocality } from "../app/profile";
import { useSession } from "../app/session";
import { Chip } from "../components/Chip";
import { EventCardView } from "../components/EventCardView";
import { FilterSheet } from "../components/FilterSheet";
import { useDebounced } from "../hooks/useDebounced";
import { useOnVisible } from "../hooks/useOnVisible";
import {
  deeplinkFeed,
  feedToParams,
  parseFeed,
  sheetFilterCount,
  toEventQuery,
  type FeedFilters,
} from "../lib/feedParams";

const TABS: [Tier, string][] = [
  ["official", "Официальные"],
  ["community", "От сообщества"],
];
const MAX_RADIUS: Radius = 50;

/** Лента (FR-CAT): вкладки доверия не смешиваются, фильтры — в query-строке. */
export function FeedPage({ me, localityId }: { me: Me; localityId: number }) {
  const [params, setParams] = useSearchParams();
  const filters = parseFeed(params);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [search, setSearch] = useState(filters.q);
  const q = useDebounced(search.trim());
  const locality = useLocality(localityId);
  const { inMax } = useSession();

  const setFilters = (next: FeedFilters) =>
    setParams(feedToParams(next), { replace: true });
  const toggle = (patch: Partial<FeedFilters>) =>
    setFilters({ ...filters, ...patch });

  // Диплинк feed_<preset> → фильтры (один раз при входе).
  useEffect(() => {
    const next = deeplinkFeed(params);
    if (next) setParams(next, { replace: true });
  }, [params, setParams]);

  useEffect(() => {
    if (q !== filters.q) setFilters({ ...filters, q });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- синхронизируем только поиск
  }, [q]);

  const radius = (filters.radius ?? me.radius_km) as Radius;
  const query = toEventQuery(filters, localityId, radius);
  const feed = useInfiniteQuery({
    queryKey: ["events", query],
    queryFn: ({ pageParam }) => fetchEvents({ ...query, cursor: pageParam }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const sentinel = useOnVisible<HTMLDivElement>(
    () => void feed.fetchNextPage(),
    feed.hasNextPage && !feed.isFetchingNextPage,
  );
  const items = feed.data?.pages.flatMap((p) => p.items) ?? [];
  const extra = sheetFilterCount(filters);

  return (
    <main className="screen">
      <header className="feed-header">
        <div>
          <Typography.Headline variant="medium-strong">
            📍 {locality.data?.name ?? "…"}
          </Typography.Headline>
          <Typography.Body variant="small" className="muted">
            в радиусе {radius} км
          </Typography.Body>
        </div>
        <nav className="row">
          <Link className="icon-link" to="/saved" aria-label="Мои «Пойду»">
            ⭐
          </Link>
          <Link className="icon-link" to="/settings" aria-label="Настройки">
            ⚙️
          </Link>
        </nav>
      </header>

      {!inMax && (
        <Typography.Body variant="small" className="dev-badge">
          Режим разработки: вход без MAX (DEV_AUTH)
        </Typography.Body>
      )}

      <Input
        type="search"
        placeholder="Поиск: хор, ярмарка, кино…"
        value={search}
        onChange={(e) => setSearch(e.target.value.slice(0, 200))}
        aria-label="Поиск событий"
      />

      <div className="tabs" role="tablist">
        {TABS.map(([tier, text]) => (
          <button
            key={tier}
            type="button"
            role="tab"
            aria-selected={filters.tier === tier}
            className={filters.tier === tier ? "tab tab--on" : "tab"}
            onClick={() => toggle({ tier })}
          >
            {text}
          </button>
        ))}
      </div>
      {filters.tier === "community" && (
        <Typography.Body variant="small" className="muted">
          События от жителей и непроверенных организаторов. Уточняй детали перед
          поездкой.
        </Typography.Body>
      )}

      <div className="chips chips--scroll">
        <Chip
          selected={filters.date === "today"}
          onClick={() =>
            toggle({ date: filters.date === "today" ? null : "today" })
          }
        >
          Сегодня
        </Chip>
        <Chip
          selected={filters.date === "tomorrow"}
          onClick={() =>
            toggle({ date: filters.date === "tomorrow" ? null : "tomorrow" })
          }
        >
          Завтра
        </Chip>
        <Chip
          selected={filters.date === "weekend"}
          onClick={() =>
            toggle({ date: filters.date === "weekend" ? null : "weekend" })
          }
        >
          Выходные
        </Chip>
        <Chip
          selected={filters.free}
          onClick={() => toggle({ free: !filters.free })}
        >
          Бесплатно
        </Chip>
        <Chip
          selected={filters.pushkin}
          onClick={() => toggle({ pushkin: !filters.pushkin })}
        >
          💳 Пушкинская
        </Chip>
        <Chip selected={extra > 0} onClick={() => setSheetOpen(true)}>
          ⚙︎ Фильтры{extra > 0 ? ` · ${extra}` : ""}
        </Chip>
      </div>

      {feed.isPending && <Spinner />}
      {feed.isError && (
        <div className="stack">
          <Typography.Body variant="medium">
            {feed.error.message}
          </Typography.Body>
          <Button
            size="medium"
            variant="secondary"
            onClick={() => void feed.refetch()}
          >
            Повторить
          </Button>
        </div>
      )}

      {feed.isSuccess && items.length === 0 && (
        <div className="empty stack" data-testid="feed-empty">
          <Typography.Headline variant="small-strong">
            В радиусе {radius} км ничего не нашлось
          </Typography.Headline>
          {radius < MAX_RADIUS ? (
            <Button
              size="large"
              stretched
              onClick={() => toggle({ radius: MAX_RADIUS })}
            >
              Расширить до {MAX_RADIUS} км
            </Button>
          ) : (
            <Typography.Body variant="medium" className="muted">
              Попробуй убрать фильтры или загляни на вкладку «
              {filters.tier === "official" ? "От сообщества" : "Официальные"}».
            </Typography.Body>
          )}
        </div>
      )}

      <div className="stack">
        {items.map((card) => (
          <EventCardView key={card.id} card={card} />
        ))}
      </div>
      {feed.hasNextPage && (
        <div ref={sentinel} className="stack">
          <Button
            size="medium"
            variant="secondary"
            loading={feed.isFetchingNextPage}
            onClick={() => void feed.fetchNextPage()}
          >
            Показать ещё
          </Button>
        </div>
      )}

      {sheetOpen && (
        <FilterSheet
          value={filters}
          radius={me.radius_km}
          onClose={() => setSheetOpen(false)}
          onApply={(next) => {
            setFilters(next);
            setSheetOpen(false);
          }}
        />
      )}
    </main>
  );
}
