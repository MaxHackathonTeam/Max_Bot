import { useQuery } from "@tanstack/react-query";
import { Bookmark, CalendarDays } from "lucide-react";
import { useState } from "react";
import { fetchSaved } from "../api/client";
import { useSession } from "../app/session";
import { EventCardSkeleton, EventCardView } from "../components/EventCardView";
import { ButtonLink } from "../ui/Button";
import { EmptyState } from "../ui/EmptyState";
import { Tabs } from "../ui/Tabs";
import { ErrorBlock } from "./Status";

type When = "upcoming" | "past";

const TABS: { value: When; label: string }[] = [
  { value: "upcoming", label: "Предстоящие" },
  { value: "past", label: "Прошедшие" },
];

/** «Мои Пойду»: предстоящие и прошедшие сеансы. Без аккаунта — подсказка, как сюда попасть. */
export function SavedPage() {
  const { hasToken, booting, signingIn } = useSession();
  const [when, setWhen] = useState<When>("upcoming");
  const saved = useQuery({ queryKey: ["saved", when], queryFn: () => fetchSaved(when), enabled: hasToken });
  const waiting = (hasToken && saved.isPending) || (!hasToken && (booting || signingIn));

  return (
    <main className="page page--narrow">
      <div className="stack stack--loose">
        <div className="page-head">
          <p className="eyebrow">Мой список</p>
          <h1 className="h1">Пойду</h1>
        </div>
        <Tabs label="Какие события" value={when} onChange={setWhen} items={TABS} />

        {waiting && (
          <div className="feed__grid" aria-busy>
            <EventCardSkeleton />
            <EventCardSkeleton />
          </div>
        )}
        {!hasToken && !waiting && (
          <EmptyState
            icon={<Bookmark size={28} aria-hidden />}
            title="Здесь пока пусто"
            text="Нажми «Пойду» в карточке события — оно появится здесь, а в MAX ещё и напомним заранее."
            action={
              <ButtonLink to="/" variant="primary" icon={<CalendarDays size={18} aria-hidden />}>
                Смотреть афишу
              </ButtonLink>
            }
          />
        )}
        {saved.isError && <ErrorBlock message={saved.error.message} onRetry={() => void saved.refetch()} />}
        {saved.data?.length === 0 && (
          <EmptyState
            icon={<Bookmark size={28} aria-hidden />}
            title={when === "upcoming" ? "Пока ничего не запланировано" : "Прошедших пока нет"}
            text={
              when === "upcoming"
                ? "Нажми «Пойду» в карточке события — оно появится здесь."
                : "Здесь появятся события, на которые ты собирался."
            }
            action={
              when === "upcoming" && (
                <ButtonLink to="/" variant="secondary">
                  К афише
                </ButtonLink>
              )
            }
          />
        )}
        {saved.data && saved.data.length > 0 && (
          <div className="feed__grid">
            {saved.data.map((item) => (
              <EventCardView key={item.session.id} card={item.event} when={item.session.starts_at} />
            ))}
          </div>
        )}
      </div>
    </main>
  );
}
