import { useInfiniteQuery } from "@tanstack/react-query";
import { BadgeCheck, Building, MapPin, Search, SearchX, X } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { KIND_LABELS, orgKindLabel, searchOrgs, type OrgSearchItem } from "../api/orgs";
import { homeLocalityId, useLocality, useMe } from "../app/profile";
import { DemoBadge } from "../components/Badges";
import { LocalityPicker } from "../components/LocalityPicker";
import { useDebounced } from "../hooks/useDebounced";
import { useOnVisible } from "../hooks/useOnVisible";
import { Button } from "../ui/Button";
import { Chip } from "../ui/Chip";
import { EmptyState } from "../ui/EmptyState";
import { Input } from "../ui/Field";
import { ListRow } from "../ui/ListRow";
import { Sheet } from "../ui/Sheet";
import { Loading, Skeleton } from "../ui/Skeleton";
import { ErrorBlock } from "./Status";

const KINDS = ["dk", "library", "museum", "club", "sport", "park", "nko", "municipal"] as const;
const MAX_QUERY = 100;

function parseId(raw: string | null): number | null {
  const n = Number(raw);
  return Number.isInteger(n) && n > 0 ? n : null;
}

function subtitle(org: OrgSearchItem): string {
  const events = org.future_events ? `событий впереди: ${org.future_events}` : "ближайших событий нет";
  return [org.locality?.name, orgKindLabel(org.kind), events].filter(Boolean).join(" · ");
}

/** Организации (/orgs): поиск по названию с опечатками, фильтры по пункту и виду — без входа. */
export function OrgsPage() {
  const me = useMe();
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get("q") ?? "");
  const q = useDebounced(search.trim());
  const kind = params.get("type");
  // По умолчанию — свой пункт, если он известен; «Везде» — явное locality=all.
  const all = params.get("locality") === "all";
  const localityId = all ? null : (parseId(params.get("locality")) ?? homeLocalityId(me.data));
  const locality = useLocality(localityId);
  const [placeOpen, setPlaceOpen] = useState(false);

  const update = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(patch)) {
      if (value === null) next.delete(key);
      else next.set(key, value);
    }
    setParams(next, { replace: true });
  };

  const query = { q, locality_id: localityId, type: kind };
  const orgs = useInfiniteQuery({
    queryKey: ["orgs-search", query],
    queryFn: ({ pageParam }) => searchOrgs({ ...query, cursor: pageParam }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const sentinel = useOnVisible<HTMLDivElement>(
    () => void orgs.fetchNextPage(),
    orgs.hasNextPage && !orgs.isFetchingNextPage,
  );
  const items = orgs.data?.pages.flatMap((p) => p.items) ?? [];
  const filtered = Boolean(q || kind || localityId);

  return (
    <main className="page page--narrow">
      <div className="stack stack--loose">
        <div className="page-head">
          <p className="eyebrow">Кто проводит события</p>
          <h1 className="h1">Организации</h1>
        </div>

        <div className="input-wrap">
          <Search size={18} aria-hidden />
          <Input
            type="search"
            placeholder="Название: дом культуры, библиотека…"
            value={search}
            onChange={(e) => {
              const value = e.target.value.slice(0, MAX_QUERY);
              setSearch(value);
              update({ q: value.trim() || null });
            }}
            aria-label="Поиск организаций"
          />
        </div>

        <div className="chips chips--scroll">
          <Chip pressed={localityId !== null} icon={<MapPin size={15} aria-hidden />} onClick={() => setPlaceOpen(true)}>
            {localityId !== null ? (locality.data?.name ?? "…") : "Везде"}
          </Chip>
          {localityId !== null && (
            <Chip icon={<X size={15} aria-hidden />} onClick={() => update({ locality: "all" })}>
              Везде
            </Chip>
          )}
          {KINDS.map((value) => (
            <Chip key={value} pressed={kind === value} onClick={() => update({ type: kind === value ? null : value })}>
              {KIND_LABELS[value]}
            </Chip>
          ))}
        </div>

        {orgs.isPending && (
          <Loading>
            <Skeleton height={60} radius={10} />
            <Skeleton height={60} radius={10} />
            <Skeleton height={60} radius={10} />
          </Loading>
        )}
        {orgs.isError && <ErrorBlock message={orgs.error.message} onRetry={() => void orgs.refetch()} />}

        {orgs.isSuccess && items.length === 0 && (
          <div data-testid="orgs-empty">
            {filtered ? (
              <EmptyState
                icon={<SearchX size={28} aria-hidden />}
                title="Ничего не нашли"
                text="Проверь название или убери фильтры — поищем по всем пунктам."
                action={
                  <Button
                    variant="secondary"
                    onClick={() => {
                      setSearch("");
                      update({ q: null, type: null, locality: "all" });
                    }}
                  >
                    Сбросить фильтры
                  </Button>
                }
              />
            ) : (
              <EmptyState
                icon={<Building size={28} aria-hidden />}
                title="Организаций пока нет"
                text="Здесь появятся дома культуры, библиотеки и клубы, которые публикуют афиши."
              />
            )}
          </div>
        )}

        {items.length > 0 && (
          <div className="list">
            {items.map((o) => (
              <ListRow
                key={o.id}
                to={`/org/${o.id}`}
                icon={o.verified ? <BadgeCheck size={18} aria-label="Проверена" /> : <Building size={18} aria-hidden />}
                title={
                  <>
                    {o.name} {o.is_demo && <DemoBadge />}
                  </>
                }
                subtitle={subtitle(o)}
              />
            ))}
          </div>
        )}
        {orgs.hasNextPage && (
          <div ref={sentinel} className="row">
            <Button variant="secondary" block loading={orgs.isFetchingNextPage} onClick={() => void orgs.fetchNextPage()}>
              Показать ещё
            </Button>
          </div>
        )}
      </div>

      <Sheet open={placeOpen} onClose={() => setPlaceOpen(false)} title="Где искать организации">
        <LocalityPicker
          onPick={(l) => {
            update({ locality: String(l.id) });
            setPlaceOpen(false);
          }}
        />
      </Sheet>
    </main>
  );
}
