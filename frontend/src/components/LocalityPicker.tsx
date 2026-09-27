import { useMutation, useQuery } from "@tanstack/react-query";
import { LocateFixed, MapPin, Search } from "lucide-react";
import { useState } from "react";
import { nearestLocalities, searchLocalities, type Locality } from "../api/client";
import { useDebounced } from "../hooks/useDebounced";
import { Button } from "../ui/Button";
import { Input } from "../ui/Field";
import { ListRow } from "../ui/ListRow";
import { Skeleton } from "../ui/Skeleton";

function label(locality: Locality): string {
  return [locality.kind, locality.municipality ?? locality.region].filter(Boolean).join(" · ");
}

function currentPosition(): Promise<GeolocationPosition> {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new Error("unsupported"));
      return;
    }
    navigator.geolocation.getCurrentPosition(resolve, reject, { timeout: 10_000, maximumAge: 600_000 });
  });
}

/**
 * Выбор населённого пункта (FR-ONB-2): поиск по названию или геолокация браузера.
 * В WebView MAX геолокация не гарантирована — основной путь поиск (§9 риски).
 */
export function LocalityPicker({ onPick, busy }: { onPick: (l: Locality) => void; busy?: boolean }) {
  const [query, setQuery] = useState("");
  const q = useDebounced(query.trim());
  const search = useQuery({
    queryKey: ["localities", q],
    queryFn: () => searchLocalities(q),
    enabled: q.length >= 2,
    staleTime: 300_000,
  });
  const locate = useMutation({
    mutationFn: async () => {
      const pos = await currentPosition();
      return nearestLocalities(pos.coords.latitude, pos.coords.longitude);
    },
  });

  const options = q.length >= 2 ? search.data : locate.data;
  return (
    <div className="stack">
      <div className="input-wrap">
        <Search size={18} aria-hidden />
        <Input
          type="search"
          placeholder="Название города или села"
          value={query}
          onChange={(e) => setQuery(e.target.value.slice(0, 100))}
          aria-label="Населённый пункт"
          autoComplete="off"
        />
      </div>
      <Button
        variant="secondary"
        onClick={() => locate.mutate()}
        loading={locate.isPending}
        disabled={busy}
        icon={<LocateFixed size={18} aria-hidden />}
      >
        Определить по геолокации
      </Button>
      {locate.isError && <p className="small muted">Не получилось определить место — введи название.</p>}
      {q.length >= 2 && search.isPending && (
        <div className="stack stack--tight" aria-hidden>
          <Skeleton height={56} radius={10} />
          <Skeleton height={56} radius={10} />
        </div>
      )}
      {search.isError && (
        <p className="small error-text" role="alert">
          {search.error.message}{" "}
          <button type="button" className="link-btn" onClick={() => void search.refetch()}>
            Повторить
          </button>
        </p>
      )}
      {options && options.length === 0 && <p className="small muted">Ничего не нашлось. Попробуй написать иначе.</p>}
      {options && options.length > 0 && (
        <div className="list" aria-busy={busy}>
          {options.map((l) => (
            <ListRow
              key={l.id}
              icon={<MapPin size={18} aria-hidden />}
              title={l.name}
              subtitle={label(l)}
              disabled={busy}
              onClick={() => onPick(l)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
