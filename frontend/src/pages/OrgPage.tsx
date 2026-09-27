import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, BadgeCheck, Building, Info, PencilLine, Plus } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import type { Me } from "../api/client";
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
import { hasConsent, hasOrgConsent } from "../app/profile";
import { ConsentPrompt } from "../components/ConsentPrompt";
import { ManagedEventList, StatusChips } from "../components/ManagedEventList";
import { OrgConsent } from "../components/OrgConsent";
import { OrgForm } from "../components/OrgForm";
import { RequireMax } from "../components/RequireMax";
import { TeamPanel } from "../components/TeamPanel";
import { VerificationPanel } from "../components/VerificationPanel";
import { Badge } from "../ui/Badge";
import { Button, ButtonLink } from "../ui/Button";
import { Card } from "../ui/Card";
import { ListRow } from "../ui/ListRow";
import { Loading, Skeleton } from "../ui/Skeleton";
import { Tabs } from "../ui/Tabs";
import { useToast } from "../ui/toastContext";
import { ErrorBlock, ErrorScreen, LoadingScreen } from "./Status";

const kindLabel = (kind: string) => ORG_KINDS.find((k) => k.value === kind)?.label ?? kind;

function ListSkeleton() {
  return (
    <Loading>
      <Skeleton height={56} radius={10} />
      <Skeleton height={56} radius={10} />
    </Loading>
  );
}

/** /org/0 — мои организации и мои события «от сообщества». */
function Cabinet({ me }: { me: Me }) {
  const navigate = useNavigate();
  const client = useQueryClient();
  const toast = useToast();
  const [creating, setCreating] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const consent = hasConsent(me);
  const orgs = useQuery({ queryKey: ["orgs"], queryFn: fetchMyOrgs, enabled: consent });
  const events = useQuery({ queryKey: ["my-events", status], queryFn: () => fetchMyEvents(status), enabled: consent });
  const create = useMutation({
    mutationFn: createOrg,
    onSuccess: (org) => {
      void client.invalidateQueries({ queryKey: ["orgs"] });
      toast.show("Организация создана — теперь пройди проверку");
      navigate(`/org/${org.id}?tab=verify`);
    },
  });

  return (
    <main className="page page--narrow">
      <div className="stack stack--loose">
        <div className="page-head">
          <p className="eyebrow">Для организаторов</p>
          <h1 className="h1">Кабинет</h1>
        </div>

        {!consent ? (
          <Card>
            <ConsentPrompt />
          </Card>
        ) : (
          <>
            <section className="section stack">
              <div className="row row--between">
                <h2 className="h3">Мои события</h2>
                <ButtonLink to="/draft/0" variant="primary" size="sm" icon={<PencilLine size={16} aria-hidden />}>
                  Предложить событие
                </ButtonLink>
              </div>
              <p className="small muted">Без организации событие попадает в «От сообщества» после проверки.</p>
              <StatusChips value={status} onChange={setStatus} />
              {events.isPending && <ListSkeleton />}
              {events.isError && <ErrorBlock message={events.error.message} onRetry={() => void events.refetch()} />}
              {events.data && <ManagedEventList items={events.data} />}
            </section>

            <section className="section stack">
              <h2 className="h3">Мои организации</h2>
              {orgs.isPending && <ListSkeleton />}
              {orgs.isError && <ErrorBlock message={orgs.error.message} onRetry={() => void orgs.refetch()} />}
              {orgs.data && orgs.data.length > 0 && (
                <div className="list">
                  {orgs.data.map((o) => (
                    <ListRow
                      key={o.id}
                      to={`/org/${o.id}`}
                      icon={o.verified ? <BadgeCheck size={18} aria-hidden /> : <Building size={18} aria-hidden />}
                      title={o.name}
                      subtitle={`${kindLabel(o.kind)} · ${o.verified ? "проверена" : "не проверена"}`}
                    />
                  ))}
                </div>
              )}
              {creating ? (
                hasOrgConsent(me) ? (
                  <Card>
                    <OrgForm busy={create.isPending} error={create.error} submitLabel="Создать организацию" onSubmit={(b) => create.mutate(b)} />
                  </Card>
                ) : (
                  <OrgConsent me={me} />
                )
              ) : (
                <div>
                  <Button variant="secondary" icon={<Plus size={18} aria-hidden />} onClick={() => setCreating(true)}>
                    Добавить организацию
                  </Button>
                </div>
              )}
            </section>
          </>
        )}
      </div>
    </main>
  );
}

type Tab = "events" | "team" | "verify" | "profile";
const TABS: { value: Tab; label: string }[] = [
  { value: "events", label: "События" },
  { value: "team", label: "Команда" },
  { value: "verify", label: "Проверка" },
  { value: "profile", label: "Профиль" },
];

function OrgEvents({ org }: { org: Org }) {
  const [status, setStatus] = useState<string | null>(null);
  const events = useQuery({ queryKey: ["org-events", org.id, status], queryFn: () => fetchOrgEvents(org.id, status) });
  return (
    <div className="stack">
      <div>
        <ButtonLink to={`/draft/0?org=${org.id}`} variant="primary" icon={<PencilLine size={16} aria-hidden />}>
          Новое событие
        </ButtonLink>
      </div>
      {!org.verified && (
        <div className="notice notice--sun">
          <Info size={18} aria-hidden />
          <span>Пока организация не проверена, события уходят на модерацию и публикуются в «От сообщества».</span>
        </div>
      )}
      <StatusChips value={status} onChange={setStatus} />
      {events.isPending && <ListSkeleton />}
      {events.isError && <ErrorBlock message={events.error.message} onRetry={() => void events.refetch()} />}
      {events.data && <ManagedEventList items={events.data} />}
    </div>
  );
}

function OrgProfile({ org }: { org: Org }) {
  const client = useQueryClient();
  const toast = useToast();
  const update = useMutation({
    mutationFn: (body: Parameters<typeof updateOrg>[1]) => updateOrg(org.id, body),
    onSuccess: (o) => {
      client.setQueryData(["org", org.id], o);
      toast.show("Сохранили");
    },
  });
  if (org.my_role !== "owner") return <p className="muted">Профиль организации меняет владелец.</p>;
  return <OrgForm initial={org} busy={update.isPending} error={update.error} submitLabel="Сохранить" onSubmit={(b) => update.mutate(b)} />;
}

function OrgCabinet({ id }: { id: number }) {
  const [params] = useSearchParams();
  const initial = params.get("tab");
  const [tab, setTab] = useState<Tab>(TABS.find((t) => t.value === initial)?.value ?? "events");
  const org = useQuery({ queryKey: ["org", id], queryFn: () => fetchOrg(id) });

  if (org.isPending) return <LoadingScreen />;
  if (org.isError) return <ErrorScreen message={org.error.message} onRetry={() => void org.refetch()} />;
  if (org.data.my_role === null) return <ErrorScreen message="Ты не состоишь в команде этой организации." />;
  return (
    <main className="page page--narrow">
      <div className="stack stack--loose">
        <Link to="/org/0" className="text-link small">
          <ArrowLeft size={14} aria-hidden /> Все организации
        </Link>
        <div className="page-head">
          <p className="eyebrow">{kindLabel(org.data.kind)}</p>
          <h1 className="h1">{org.data.name}</h1>
          <div className="badges">
            {org.data.verified ? (
              <Badge tone="verified" icon={<BadgeCheck size={14} aria-hidden />}>
                Организатор проверен
              </Badge>
            ) : (
              <Badge>Не проверена</Badge>
            )}
          </div>
        </div>
        <Tabs label="Разделы организации" value={tab} onChange={setTab} items={TABS} />
        {tab === "events" && <OrgEvents org={org.data} />}
        {tab === "team" && <TeamPanel org={org.data} />}
        {tab === "verify" && <VerificationPanel org={org.data} />}
        {tab === "profile" && <OrgProfile org={org.data} />}
      </div>
    </main>
  );
}

/** Кабинет организатора (§3.1 org_<id>): /org/0 — список, /org/<id> — организация. */
export function OrgPage() {
  const id = Number(useParams().id);
  if (!Number.isInteger(id) || id < 0) return <ErrorScreen message="Организация не найдена." />;
  return (
    <RequireMax
      title="Кабинет организатора"
      text="Публиковать события и управлять организацией можно после входа через MAX: так мы связываемся с тобой в боте и присылаем итоги модерации."
    >
      {(me) => (id === 0 ? <Cabinet me={me} /> : <OrgCabinet key={id} id={id} />)}
    </RequireMax>
  );
}
