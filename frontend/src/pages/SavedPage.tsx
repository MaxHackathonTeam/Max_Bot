import { Spinner, Typography } from "@maxhub/max-ui";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { fetchSaved } from "../api/client";
import { EventCardView } from "../components/EventCardView";

type When = "upcoming" | "past";

/** «Мои Пойду»: предстоящие и прошедшие сеансы. */
export function SavedPage() {
  const [when, setWhen] = useState<When>("upcoming");
  const saved = useQuery({
    queryKey: ["saved", when],
    queryFn: () => fetchSaved(when),
  });

  return (
    <main className="screen">
      <Typography.Headline variant="large-strong">
        ⭐ Мои «Пойду»
      </Typography.Headline>
      <div className="tabs" role="tablist">
        {(
          [
            ["upcoming", "Предстоящие"],
            ["past", "Прошедшие"],
          ] as [When, string][]
        ).map(([value, text]) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={when === value}
            className={when === value ? "tab tab--on" : "tab"}
            onClick={() => setWhen(value)}
          >
            {text}
          </button>
        ))}
      </div>
      {saved.isPending && <Spinner />}
      {saved.isError && (
        <Typography.Body variant="medium">
          {saved.error.message}
        </Typography.Body>
      )}
      {saved.data?.length === 0 && (
        <Typography.Body variant="medium" className="muted">
          {when === "upcoming"
            ? "Пока пусто. Нажми «⭐ Пойду» в карточке события — напомним заранее."
            : "Здесь появятся события, на которые ты ходил."}
        </Typography.Body>
      )}
      <div className="stack">
        {saved.data?.map((item) => (
          <EventCardView
            key={item.session.id}
            card={item.event}
            when={item.session.starts_at}
          />
        ))}
      </div>
    </main>
  );
}
