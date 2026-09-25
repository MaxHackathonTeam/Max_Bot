import { Button, CellList, CellSimple, Typography } from "@maxhub/max-ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import {
  createOrg,
  fetchMyEvents,
  fetchMyOrgs,
  fetchOrg,
  fetchOrgEvents,
  ORG_KINDS,
  updateOrg,
  type Org,
} from "../api/organizer";
import { hasConsent, hasOrgConsent, useMe } from "../app/profile";
import { ConsentPrompt } from "../components/ConsentPrompt";
import { ManagedEventList, StatusChips } from "../components/ManagedEventList";
import { OrgConsent } from "../components/OrgConsent";
import { OrgForm } from "../components/OrgForm";
import { TeamPanel } from "../components/TeamPanel";
import { VerificationPanel } from "../components/VerificationPanel";
import { ErrorScreen, LoadingScreen } from "./Status";

const kindLabel = (kind: string) =>
  ORG_KINDS.find((k) => k.value === kind)?.label ?? kind;

/** /org/0 — мои организации и мои события «от сообщества». */
function Cabinet() {
  const me = useMe();
  const navigate = useNavigate();
  const client = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const orgs = useQuery({ queryKey: ["orgs"], queryFn: fetchMyOrgs });
  const events = useQuery({
    queryKey: ["my-events", status],
    queryFn: () => fetchMyEvents(status),
  });
  const create = useMutation({
    mutationFn: createOrg,
    onSuccess: (org) => {
      void client.invalidateQueries({ queryKey: ["orgs"] });
      navigate(`/org/${org.id}?tab=verify`);
    },
  });

  if (me.isPending || orgs.isPending) return <LoadingScreen />;
  if (me.isError)
    return (
      <ErrorScreen
        message={me.error.message}
        onRetry={() => void me.refetch()}
      />
    );
  if (orgs.isError)
    return (
      <ErrorScreen
        message={orgs.error.message}
        onRetry={() => void orgs.refetch()}
      />
    );

  if (!hasConsent(me.data)) {
    return (
      <main className="screen">
        <Typography.Headline variant="large-strong">
          🏛 Кабинет организатора
        </Typography.Headline>
        <ConsentPrompt />
      </main>
    );
  }

  return (
    <main className="screen">
      <Typography.Headline variant="large-strong">
        🏛 Кабинет организатора
      </Typography.Headline>

      <Typography.Label variant="medium-strong">
        Мои организации
      </Typography.Label>
      {orgs.data.length > 0 && (
        <CellList mode="island" filled>
          {orgs.data.map((o) => (
            <CellSimple
              key={o.id}
              title={`${o.name}${o.verified ? " ✓" : ""}`}
              subtitle={`${kindLabel(o.kind)} · ${o.verified ? "проверена" : "не проверена"}`}
              showChevron
              onClick={() => navigate(`/org/${o.id}`)}
            />
          ))}
        </CellList>
      )}
      {creating ? (
        hasOrgConsent(me.data) ? (
          <OrgForm
            busy={create.isPending}
            error={create.error}
            submitLabel="Создать организацию"
            onSubmit={(b) => create.mutate(b)}
          />
        ) : (
          <OrgConsent me={me.data} />
        )
      ) : (
        <Button
          size="large"
          variant="secondary"
          onClick={() => setCreating(true)}
        >
          ➕ Добавить организацию
        </Button>
      )}

      <Typography.Label variant="medium-strong">Мои события</Typography.Label>
      <Typography.Body variant="small" className="muted">
        Без организации событие попадает в «От сообщества» после проверки.
      </Typography.Body>
      <Button size="large" onClick={() => navigate("/draft/0")}>
        ✍️ Предложить событие
      </Button>
      <StatusChips value={status} onChange={setStatus} />
      {events.isError ? (
        <ErrorScreen message={events.error.message} />
      ) : (
        <ManagedEventList items={events.data ?? []} />
      )}
    </main>
  );
}

type Tab = "events" | "team" | "verify" | "profile";
const TABS: [Tab, string][] = [
  ["events", "События"],
  ["team", "Команда"],
  ["verify", "Проверка"],
  ["profile", "Профиль"],
];

function OrgEvents({ org }: { org: Org }) {
  const navigate = useNavigate();
  const [status, setStatus] = useState<string | null>(null);
  const events = useQuery({
    queryKey: ["org-events", org.id, status],
    queryFn: () => fetchOrgEvents(org.id, status),
  });
  return (
    <div className="stack">
      <Button size="large" onClick={() => navigate(`/draft/0?org=${org.id}`)}>
        ✍️ Новое событие
      </Button>
      {!org.verified && (
        <Typography.Body variant="small" className="notice">
          Пока организация не проверена, события уходят на модерацию и
          публикуются в «От сообщества».
        </Typography.Body>
      )}
      <StatusChips value={status} onChange={setStatus} />
      {events.isError ? (
        <ErrorScreen message={events.error.message} />
      ) : (
        <ManagedEventList items={events.data ?? []} />
      )}
    </div>
  );
}

function OrgProfile({ org }: { org: Org }) {
  const client = useQueryClient();
  const update = useMutation({
    mutationFn: (body: Parameters<typeof updateOrg>[1]) =>
      updateOrg(org.id, body),
    onSuccess: (o) => client.setQueryData(["org", org.id], o),
  });
  if (org.my_role !== "owner") {
    return (
      <Typography.Body variant="small" className="muted">
        Профиль организации меняет владелец.
      </Typography.Body>
    );
  }
  return (
    <>
      {update.isSuccess && (
        <Typography.Body variant="small" className="notice">
          Сохранено ✅
        </Typography.Body>
      )}
      <OrgForm
        initial={org}
        busy={update.isPending}
        error={update.error}
        submitLabel="Сохранить"
        onSubmit={(b) => update.mutate(b)}
      />
    </>
  );
}

function OrgCabinet({ id }: { id: number }) {
  const [params] = useSearchParams();
  const initial = (params.get("tab") as Tab | null) ?? "events";
  const [tab, setTab] = useState<Tab>(
    TABS.some(([t]) => t === initial) ? initial : "events",
  );
  const org = useQuery({ queryKey: ["org", id], queryFn: () => fetchOrg(id) });

  if (org.isPending) return <LoadingScreen />;
  if (org.isError)
    return (
      <ErrorScreen
        message={org.error.message}
        onRetry={() => void org.refetch()}
      />
    );
  if (org.data.my_role === null) {
    return <ErrorScreen message="Ты не состоишь в команде этой организации." />;
  }
  return (
    <main className="screen">
      <Link to="/org/0" className="muted">
        ← Все организации
      </Link>
      <Typography.Headline variant="large-strong">
        {org.data.name}
      </Typography.Headline>
      <div className="badges">
        <span className="badge">{kindLabel(org.data.kind)}</span>
        {org.data.verified ? (
          <span className="badge badge--verified">✓ Организатор проверен</span>
        ) : (
          <span className="badge">Не проверена</span>
        )}
      </div>
      <div className="tabs" role="tablist">
        {TABS.map(([t, label]) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={tab === t}
            className={tab === t ? "tab tab--on" : "tab"}
            onClick={() => setTab(t)}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === "events" && <OrgEvents org={org.data} />}
      {tab === "team" && <TeamPanel org={org.data} />}
      {tab === "verify" && <VerificationPanel org={org.data} />}
      {tab === "profile" && <OrgProfile org={org.data} />}
    </main>
  );
}

/** Кабинет организатора (§3.1 org_<id>): /org/0 — список, /org/<id> — организация. */
export function OrgPage() {
  const id = Number(useParams().id);
  if (!Number.isInteger(id) || id < 0)
    return <ErrorScreen message="Организация не найдена." />;
  return id === 0 ? <Cabinet /> : <OrgCabinet key={id} id={id} />;
}
