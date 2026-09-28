import { useMutation, useQuery } from "@tanstack/react-query";
import { LocateFixed, MapPin, Search } from "lucide-react";
import { useId, useRef, useState, type KeyboardEvent } from "react";
import { nearestLocalities, searchLocalities, type Locality } from "../api/client";
import { useDebounced } from "../hooks/useDebounced";
import {
  geoErrorText,
  highlightParts,
  localitySubtitle,
  MAX_OPTIONS,
  MIN_QUERY,
  moveActive,
} from "../lib/localitySearch";
import { Button } from "../ui/Button";
import { Input } from "../ui/Field";
import { Skeleton } from "../ui/Skeleton";

function currentPosition(): Promise<GeolocationPosition> {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new Error("unsupported"));
      return;
    }
    navigator.geolocation.getCurrentPosition(resolve, reject, { timeout: 10_000, maximumAge: 600_000 });
  });
}

function Highlight({ text, query }: { text: string; query: string }) {
  return (
    <>
      {highlightParts(text, query).map((part, i) => (part.match ? <mark key={i}>{part.text}</mark> : part.text))}
    </>
  );
}

/**
 * Выбор населённого пункта (FR-ONB-2): автоподстановка по названию (combobox, стрелки,
 * Enter, Escape) или «Я здесь» по геолокации с подтверждением.
 * В WebView MAX геолокация не гарантирована — основной путь поиск (§9 риски).
 */
export function LocalityPicker({ onPick, busy }: { onPick: (l: Locality) => void; busy?: boolean }) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(-1);
  const [open, setOpen] = useState(true);
  const input = useRef<HTMLInputElement>(null);
  const listId = useId();
  const q = useDebounced(query.trim());
  const search = useQuery({
    queryKey: ["localities", q, MAX_OPTIONS],
    queryFn: () => searchLocalities(q, MAX_OPTIONS),
    enabled: q.length >= MIN_QUERY,
    staleTime: 300_000,
  });
  const locate = useMutation({
    mutationFn: async () => {
      const pos = await currentPosition();
      return nearestLocalities(pos.coords.latitude, pos.coords.longitude);
    },
    onError: () => input.current?.focus(),
  });

  const typing = q.length >= MIN_QUERY;
  const options = typing ? (search.data ?? []).slice(0, MAX_OPTIONS) : [];
  const expanded = typing && open && options.length > 0;
  const guess = !typing ? locate.data?.[0] : undefined;

  const pick = (locality: Locality) => {
    setOpen(false);
    setQuery(locality.name);
    onPick(locality);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setOpen(true);
      setActive((i) => moveActive(i, event.key === "ArrowDown" ? 1 : -1, options.length));
    } else if (event.key === "Enter" && expanded && active >= 0 && options[active]) {
      event.preventDefault();
      pick(options[active]);
    } else if (event.key === "Escape" && expanded) {
      event.preventDefault();
      setOpen(false);
      setActive(-1);
    }
  };

  return (
    <div className="stack">
      <div className="combo">
        <div className="input-wrap">
          <Search size={18} aria-hidden />
          <Input
            ref={input}
            type="text"
            role="combobox"
            aria-label="Населённый пункт"
            aria-autocomplete="list"
            aria-expanded={expanded}
            aria-controls={listId}
            aria-activedescendant={expanded && active >= 0 ? `${listId}-${active}` : undefined}
            placeholder="Название города или села"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value.slice(0, 100));
              setActive(-1);
              setOpen(true);
            }}
            onKeyDown={onKeyDown}
            autoComplete="off"
            enterKeyHint="search"
          />
        </div>
        <ul className="combo__list" id={listId} role="listbox" aria-label="Варианты" hidden={!expanded}>
          {options.map((l, i) => (
            <li
              key={l.id}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              aria-disabled={busy || undefined}
              className="combo__option"
              // mousedown, а не click: иначе фокус уходит с поля раньше выбора.
              onMouseDown={(e) => {
                e.preventDefault();
                if (!busy) pick(l);
              }}
              onMouseMove={() => setActive(i)}
            >
              <MapPin size={16} aria-hidden />
              <span>
                <span className="combo__name">
                  <Highlight text={l.name} query={q} />
                </span>
                <span className="combo__sub">{localitySubtitle(l)}</span>
              </span>
            </li>
          ))}
        </ul>
      </div>
      <p className="visually-hidden" aria-live="polite">
        {typing && search.data ? `Вариантов: ${options.length}` : ""}
      </p>

      {typing && search.isPending && (
        <div className="stack stack--tight" aria-hidden>
          <Skeleton height={48} radius={10} />
          <Skeleton height={48} radius={10} />
        </div>
      )}
      {typing && search.isError && (
        <p className="small error-text" role="alert">
          Не получилось загрузить пункты.{" "}
          <button type="button" className="link-btn" onClick={() => void search.refetch()}>
            Повторить
          </button>
        </p>
      )}
      {typing && search.data && options.length === 0 && (
        <p className="small muted">Ничего не нашлось. Попробуй написать иначе.</p>
      )}

      {!typing && (
        <Button
          variant="secondary"
          onClick={() => locate.mutate()}
          loading={locate.isPending}
          disabled={busy}
          icon={<LocateFixed size={18} aria-hidden />}
        >
          Я здесь
        </Button>
      )}
      {!typing && locate.isError && (
        <p className="small error-text" role="alert">
          {geoErrorText(locate.error)}
        </p>
      )}
      {!typing && locate.data && !guess && (
        <p className="small muted" role="status">
          Рядом не нашлось пунктов из справочника. Напиши название.
        </p>
      )}
      {guess && (
        <div className="notice" role="status">
          <p>
            Ты в <strong>{guess.name}</strong>?<span className="small muted"> {localitySubtitle(guess)}</span>
          </p>
          <div className="row">
            <Button size="sm" onClick={() => onPick(guess)} disabled={busy}>
              Да, это я
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                locate.reset();
                input.current?.focus();
              }}
            >
              Нет, найду сам
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
