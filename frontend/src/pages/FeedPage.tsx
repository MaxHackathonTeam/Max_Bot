import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Baby, ChevronDown, CirclePlus, CreditCard, Search, SearchX, SlidersHorizontal } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { fetchEvents, type Me, type Radius, type Tier } from "../api/client";
import { useRequireLogin } from "../app/login";
import { useLocality, useSetLocality } from "../app/profile";
import { EventCardSkeleton, EventCardView } from "../components/EventCardView";
import { FilterPanel } from "../components/FilterPanel";
import { FormErrors } from "../components/FormErrors";
import { LocalityPicker } from "../components/LocalityPicker";
import { useDebounced } from "../hooks/useDebounced";
import { useOnVisible } from "../hooks/useOnVisible";
import {
  deeplinkFeed,
  feedToParams,
  parseFeed,
  resetPanel,
  sheetFilterCount,
  toEventQuery,
  type FeedFilters,
} from "../lib/feedParams";
import { Button } from "../ui/Button";
import { Chip } from "../ui/Chip";
import { EmptyState } from "../ui/EmptyState";
import { Input } from "../ui/Field";
import { Sheet } from "../ui/Sheet";
import { Skeleton } from "../ui/Skeleton";
import { Tabs } from "../ui/Tabs";
import { ErrorBlock } from "./Status";

const TABS: { value: Tier; label: string }[] = [
  { value: "official", label: "Официальные" },
  { value: "community", label: "От жителей" },
];
const MAX_RADIUS: Radius = 50;
const TAB_LABEL: Record<Tier, string> = { official: "Официальные", community: "От жителей" };
const ADD_REASON = "Чтобы добавить афишу, войди через MAX.";
const NEARBY_LIMIT = 4;

/** Фильтры не заданы — пустая выдача значит «в пункте ничего нет», а не «фильтры слишком строгие». */
function isPlain(f: FeedFilters): boolean {
  return !f.date && !f.free && !f.kids && !f.pushkin && !f.q && sheetFilterCount({ ...f, radius: null }) === 0;
}

function clearFilters(f: FeedFilters): FeedFilters {
  return { ...resetPanel(f), radius: f.radius, date: null, free: false, kids: false, pushkin: false, q: "" };
}

function AddFirstButton() {
  const navigate = useNavigate();
  const requireLogin = useRequireLogin();
  return (
    <Button
      variant="primary"
      icon={<CirclePlus size={18} aria-hidden />}
      onClick={() => requireLogin({ reason: ADD_REASON, next: "/new" }) && navigate("/new")}
    >
      Добавить первое событие
    </Button>
  );
}

/**
 * «Рядом»: ближайшие события в пределах 50 км, по расстоянию, в той же вкладке.
 * Вкладки по-прежнему не смешиваются.
 */
function Nearby({
  filters,
  localityId,
  timeZone,
  onWiden,
}: {
  filters: FeedFilters;
  localityId: number;
  timeZone?: string;
  onWiden: () => void;
}) {
  const query = {
    ...toEventQuery({ ...filters, sort: "distance", radius: MAX_RADIUS }, localityId, MAX_RADIUS, timeZone),
    limit: NEARBY_LIMIT,
  };
  const nearby = useQuery({ queryKey: ["events", "nearby", query], queryFn: () => fetchEvents(query) });
  if (nearby.isPending)
    return (
      <section className="stack" aria-busy aria-label="Рядом">
        <h2 className="h3">Рядом</h2>
        <div className="feed__grid">
          <EventCardSkeleton />
          <EventCardSkeleton />
        </div>
      </section>
    );
  if (nearby.isError || nearby.data.items.length === 0) return null;
  return (
    <section className="stack" aria-labelledby="nearby-title">
      <h2 className="h3" id="nearby-title">
        Рядом, до {MAX_RADIUS} км
      </h2>
      <div className="feed__grid">
        {nearby.data.items.map((card) => (
          <EventCardView key={card.id} card={card} />
        ))}
      </div>
      <Button variant="secondary" onClick={onWiden}>
        Показать всё в радиусе {MAX_RADIUS} км
      </Button>
    </section>
  );
}

export function FeedSkeleton() {
  return (
    <main className="page" aria-busy>
      <div className="feed">
        <aside className="feed__aside" />
        <div className="feed__main">
          <Skeleton width="50%" height={34} />
          <Skeleton height={44} radius={10} />
          <div className="feed__grid">
            <EventCardSkeleton />
            <EventCardSkeleton />
            <EventCardSkeleton />
            <EventCardSkeleton />
          </div>
        </div>
      </div>
    </main>
  );
}

/** Лента (FR-CAT): вкладки доверия не смешиваются, фильтры — в query-строке. */
export function FeedPage({ me, localityId, radius: baseRadius }: { me: Me | null; localityId: number; radius: Radius }) {
  const [params, setParams] = useSearchParams();
  const filters = parseFeed(params);
  const [search, setSearch] = useState(filters.q);
  const q = useDebounced(search.trim());
  const locality = useLocality(localityId);
  const setLocality = useSetLocality();
  const [placeOpen, setPlaceOpen] = useState(false);
  const [draft, setDraft] = useState<FeedFilters | null>(null);

  const setFilters = (next: FeedFilters) => setParams(feedToParams(next), { replace: true });
  const toggle = (patch: Partial<FeedFilters>) => setFilters({ ...filters, ...patch });

  // Диплинк feed_<preset> → фильтры (один раз при входе).
  useEffect(() => {
    const next = deeplinkFeed(params);
    if (next) setParams(next, { replace: true });
  }, [params, setParams]);

  useEffect(() => {
    if (q !== filters.q) setFilters({ ...filters, q });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- синхронизируем только поиск
  }, [q]);

  const radius = filters.radius ?? baseRadius;
  const query = toEventQuery(filters, localityId, baseRadius, locality.data?.timezone);
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
  const dateChip = (date: FeedFilters["date"], text: string) => (
    <Chip pressed={filters.date === date} onClick={() => toggle({ date: filters.date === date ? null : date })}>
      {text}
    </Chip>
  );

  return (
    <main className="page">
      <div className="feed">
        <aside className="feed__aside" aria-label="Фильтры">
          <h2 className="h3">Фильтры</h2>
          <FilterPanel value={filters} radius={baseRadius} onChange={setFilters} />
          {extra > 0 && (
            <Button variant="ghost" size="sm" onClick={() => setFilters(resetPanel(filters))}>
              Сбросить фильтры
            </Button>
          )}
        </aside>

        <div className="feed__main">
          <div className="page-head">
            <p className="eyebrow">Афиша · в радиусе {radius} км</p>
            <button type="button" className="place-switch" onClick={() => setPlaceOpen(true)} aria-label="Сменить населённый пункт">
              <span className="h1">{locality.data?.name ?? "…"}</span>
              <ChevronDown size={22} aria-hidden />
            </button>
          </div>

          <div className="input-wrap">
            <Search size={18} aria-hidden />
            <Input
              type="search"
              placeholder="Поиск: хор, ярмарка, кино…"
              value={search}
              onChange={(e) => setSearch(e.target.value.slice(0, 200))}
              aria-label="Поиск событий"
            />
          </div>

          <Tabs label="Источник событий" value={filters.tier} onChange={(tier) => toggle({ tier })} items={TABS} />
          {filters.tier === "community" && (
            <p className="small muted">События от жителей и непроверенных организаторов. Уточняй детали перед поездкой.</p>
          )}

          <div className="chips chips--scroll">
            {dateChip("today", "Сегодня")}
            {dateChip("tomorrow", "Завтра")}
            {dateChip("weekend", "Выходные")}
            {dateChip("week", "Неделя")}
            <Chip pressed={filters.free} onClick={() => toggle({ free: !filters.free })}>
              Бесплатно
            </Chip>
            <Chip pressed={filters.kids} icon={<Baby size={15} aria-hidden />} onClick={() => toggle({ kids: !filters.kids })}>
              Для детей
            </Chip>
            <Chip
              pressed={filters.pushkin}
              icon={<CreditCard size={15} aria-hidden />}
              onClick={() => toggle({ pushkin: !filters.pushkin })}
            >
              Пушкинская
            </Chip>
            <span className="filter-toggle">
              <Chip
                pressed={extra > 0}
                icon={<SlidersHorizontal size={15} aria-hidden />}
                count={extra || undefined}
                onClick={() => setDraft(filters)}
              >
                Фильтры
              </Chip>
            </span>
          </div>

          {feed.isPending && (
            <div className="feed__grid" aria-busy>
              <EventCardSkeleton />
              <EventCardSkeleton />
              <EventCardSkeleton />
              <EventCardSkeleton />
            </div>
          )}
          {feed.isError && <ErrorBlock message={feed.error.message} onRetry={() => void feed.refetch()} />}

          {feed.isSuccess && items.length === 0 && (
            <div data-testid="feed-empty" className="stack stack--loose">
              {isPlain(filters) ? (
                <EmptyState
                  icon={<SearchX size={28} aria-hidden />}
                  title="Здесь пока нет событий"
                  text={`В радиусе ${radius} км во вкладке «${TAB_LABEL[filters.tier]}» пусто. Расскажи о своём — это займёт пару минут.`}
                  action={<AddFirstButton />}
                />
              ) : (
                <EmptyState
                  icon={<SearchX size={28} aria-hidden />}
                  title="С такими фильтрами ничего нет"
                  text="Попробуй убрать фильтры или выбрать другие даты."
                  action={
                    <Button variant="secondary" onClick={() => setFilters(clearFilters(filters))}>
                      Сбросить фильтры
                    </Button>
                  }
                />
              )}
              {radius < MAX_RADIUS && <Nearby filters={filters} localityId={localityId} timeZone={locality.data?.timezone} onWiden={() => toggle({ radius: MAX_RADIUS })} />}
            </div>
          )}

          {items.length > 0 && (
            <div className="feed__grid">
              {items.map((card) => (
                <EventCardView key={card.id} card={card} />
              ))}
            </div>
          )}
          {feed.hasNextPage && (
            <div ref={sentinel} className="row">
              <Button variant="secondary" block loading={feed.isFetchingNextPage} onClick={() => void feed.fetchNextPage()}>
                Показать ещё
              </Button>
            </div>
          )}
        </div>
      </div>

      <Sheet
        open={draft !== null}
        onClose={() => setDraft(null)}
        title="Фильтры"
        footer={
          <div className="row">
            <Button variant="ghost" onClick={() => draft && setDraft(resetPanel(draft))}>
              Сбросить
            </Button>
            <Button
              variant="primary"
              className="grow"
              onClick={() => {
                if (draft) setFilters(draft);
                setDraft(null);
              }}
            >
              Показать
            </Button>
          </div>
        }
      >
        {draft && <FilterPanel value={draft} radius={baseRadius} onChange={setDraft} />}
      </Sheet>

      <Sheet open={placeOpen} onClose={() => setPlaceOpen(false)} title="Где искать события">
        <LocalityPicker
          busy={setLocality.isPending}
          onPick={(l) => setLocality.mutate({ me, localityId: l.id }, { onSuccess: () => setPlaceOpen(false) })}
        />
        <FormErrors error={setLocality.error} />
      </Sheet>
    </main>
  );
}
