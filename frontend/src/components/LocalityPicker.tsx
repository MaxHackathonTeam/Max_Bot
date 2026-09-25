import {
  Button,
  CellList,
  CellSimple,
  Input,
  Spinner,
  Typography,
} from "@maxhub/max-ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import {
  nearestLocalities,
  searchLocalities,
  type Locality,
} from "../api/client";
import { useDebounced } from "../hooks/useDebounced";

function label(locality: Locality): string {
  return locality.municipality ?? locality.region ?? "";
}

function currentPosition(): Promise<GeolocationPosition> {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new Error("unsupported"));
      return;
    }
    navigator.geolocation.getCurrentPosition(resolve, reject, {
      timeout: 10_000,
      maximumAge: 600_000,
    });
  });
}

/**
 * Выбор населённого пункта (FR-ONB-2): поиск по названию с подсказками или геолокация
 * браузера. В WebView MAX геолокация не гарантирована — основной путь поиск (§9 риски).
 */
export function LocalityPicker({
  onPick,
  busy,
}: {
  onPick: (l: Locality) => void;
  busy?: boolean;
}) {
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
      <Input
        placeholder="Название города или села"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        aria-label="Населённый пункт"
      />
      <Button
        size="medium"
        variant="secondary"
        onClick={() => locate.mutate()}
        loading={locate.isPending}
        disabled={busy}
      >
        📍 Определить по геолокации
      </Button>
      {locate.isError && (
        <Typography.Body variant="small" className="muted">
          Не получилось определить место — введи название.
        </Typography.Body>
      )}
      {search.isFetching && <Spinner />}
      {search.isError && (
        <Typography.Body variant="small" className="muted">
          {search.error.message}
        </Typography.Body>
      )}
      {options && options.length === 0 && (
        <Typography.Body variant="small" className="muted">
          Ничего не нашлось. Попробуй написать иначе.
        </Typography.Body>
      )}
      {options && options.length > 0 && (
        <CellList mode="island" filled>
          {options.map((l) => (
            <CellSimple
              key={l.id}
              title={l.name}
              subtitle={label(l)}
              showChevron
              onClick={() => !busy && onPick(l)}
            />
          ))}
        </CellList>
      )}
    </div>
  );
}
