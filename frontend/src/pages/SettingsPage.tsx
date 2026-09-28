import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Bell, Building, FileText, LogOut, MapPin, Newspaper, ShieldCheck, Smartphone, Trash } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { deleteMe, RADII } from "../api/client";
import {
  hasConsent,
  isMaxAccount,
  LOCAL_LOCALITY,
  LOCAL_RADIUS,
  useLocality,
  useSetLocality,
  useSetRadius,
  useUpdateMe,
  useViewer,
} from "../app/profile";
import { useSession } from "../app/session";
import { ConsentPrompt } from "../components/ConsentPrompt";
import { FormErrors } from "../components/FormErrors";
import { InterestChips } from "../components/InterestChips";
import { LocalityPicker } from "../components/LocalityPicker";
import { MaxLogin } from "../components/MaxLogin";
import { writePref } from "../lib/prefs";
import { writeLocal } from "../lib/storage";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { Chip } from "../ui/Chip";
import { ListRow } from "../ui/ListRow";
import { Sheet } from "../ui/Sheet";
import { Switch } from "../ui/Switch";
import { useToast } from "../ui/toastContext";
import { ErrorScreen, LoadingScreen } from "./Status";

/** Настройки (FR-ONB-4) и удаление данных (FR-ONB-5). Место и радиус работают и без аккаунта. */
export function SettingsPage() {
  const viewer = useViewer();
  const { me, localityId, radius } = viewer;
  const { inMax, hasToken, signOut } = useSession();
  const client = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  const update = useUpdateMe();
  const setLocality = useSetLocality();
  const setRadius = useSetRadius();
  const locality = useLocality(localityId);
  const [picking, setPicking] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const consent = me !== null && hasConsent(me);
  const maxAccount = isMaxAccount(me);

  const remove = useMutation({
    mutationFn: async () => {
      if (hasToken) await deleteMe();
    },
    onSuccess: () => {
      writePref(LOCAL_LOCALITY, null);
      writePref(LOCAL_RADIUS, null);
      writeLocal("afisha.onboarded", null);
      if (!inMax) signOut();
      client.clear();
      setConfirmDelete(false);
      toast.show("Данные удалены");
      navigate("/", { replace: true });
    },
  });

  if (viewer.loading) return <LoadingScreen />;
  if (viewer.error) return <ErrorScreen message={viewer.error.message} onRetry={viewer.retry} />;

  const saved = { onSuccess: () => toast.show("Сохранили") };

  return (
    <main className="page page--narrow">
      <div className="stack stack--loose">
        <div className="page-head">
          <p className="eyebrow">Профиль</p>
          <h1 className="h1">{me?.first_name ? `Привет, ${me.first_name}` : "Настройки"}</h1>
        </div>

        <section className="section stack">
          <h2 className="h3">Где искать события</h2>
          <div className="list">
            <ListRow
              icon={<MapPin size={18} aria-hidden />}
              title={locality.data?.name ?? "Не выбран"}
              subtitle="Изменить населённый пункт"
              onClick={() => setPicking(true)}
            />
          </div>
          <div className="chips" role="group" aria-label="Радиус поиска">
            {RADII.map((r) => (
              <Chip key={r} pressed={radius === r} disabled={setRadius.isPending} onClick={() => setRadius.mutate({ me, radius: r }, saved)}>
                {r} км
              </Chip>
            ))}
          </div>
          <FormErrors error={setRadius.error} />
        </section>

        {me && !consent && (
          <Card>
            <ConsentPrompt />
          </Card>
        )}

        {consent && (
          <section className="section stack">
            <h2 className="h3">Интересы</h2>
            <InterestChips
              selected={me.interests}
              onToggle={(slug) =>
                update.mutate({
                  interests: me.interests.includes(slug) ? me.interests.filter((s) => s !== slug) : [...me.interests, slug],
                })
              }
            />
          </section>
        )}

        {consent && maxAccount && (
          <section className="section stack">
            <h2 className="h3">Уведомления в боте</h2>
            <div className="list">
              <ListRow
                icon={<Bell size={18} aria-hidden />}
                title="Напоминания о «Пойду»"
                subtitle="За сутки и за 2 часа, кроме тихих часов 22:00–09:00"
                after={
                  <Switch label="Напоминания" checked={me.notify_reminders} onChange={(v) => update.mutate({ notify_reminders: v }, saved)} />
                }
              />
              <ListRow
                icon={<Newspaper size={18} aria-hidden />}
                title="Дайджест «На выходные»"
                subtitle="По четвергам, до 7 событий по интересам"
                after={<Switch label="Дайджест" checked={me.notify_digest} onChange={(v) => update.mutate({ notify_digest: v }, saved)} />}
              />
            </div>
          </section>
        )}
        <FormErrors error={update.error} />

        {!inMax && (
          <section className="section stack">
            <h2 className="h3">Аккаунт</h2>
            {maxAccount ? (
              <div className="list">
                <ListRow
                  icon={<Smartphone size={18} aria-hidden />}
                  title="Вход через MAX выполнен"
                  subtitle="Напоминания и кабинет организатора доступны"
                  after={
                    <Button variant="ghost" size="sm" icon={<LogOut size={16} aria-hidden />} onClick={signOut}>
                      Выйти
                    </Button>
                  }
                />
              </div>
            ) : (
              <Card>
                <MaxLogin compact />
              </Card>
            )}
          </section>
        )}

        <section className="section stack">
          <h2 className="h3">Ещё</h2>
          <div className="list">
            <ListRow icon={<Building size={18} aria-hidden />} title="Кабинет организатора" subtitle="Свои события, организация, проверка" to="/org/0" />
            <ListRow icon={<FileText size={18} aria-hidden />} title="Условия использования" to="/legal/terms" />
            <ListRow icon={<ShieldCheck size={18} aria-hidden />} title="Политика обработки персональных данных" to="/legal/privacy" />
            <ListRow icon={<MapPin size={18} aria-hidden />} title="Источники данных" subtitle="© участники OpenStreetMap, ODbL" to="/legal/data" />
          </div>
        </section>

        {confirmDelete ? (
          <div className="notice notice--danger" role="alert">
            <div className="stack">
              <p>
                {hasToken
                  ? "Удалим имя, место, интересы, «Пойду» и подписки. События, которые ты публиковал, останутся без привязки к тебе. Отменить нельзя."
                  : "Сотрём выбранное место и радиус с этого устройства."}
              </p>
              <div className="row row--wrap">
                <Button variant="secondary" onClick={() => setConfirmDelete(false)}>
                  Отмена
                </Button>
                <Button variant="danger" loading={remove.isPending} onClick={() => remove.mutate()}>
                  Удалить мои данные
                </Button>
              </div>
              <FormErrors error={remove.error} />
            </div>
          </div>
        ) : (
          <div>
            <Button variant="ghost" icon={<Trash size={18} aria-hidden />} onClick={() => setConfirmDelete(true)}>
              Удалить мои данные
            </Button>
          </div>
        )}
      </div>

      <Sheet open={picking} onClose={() => setPicking(false)} title="Где искать события">
        <LocalityPicker
          busy={setLocality.isPending}
          onPick={(l) =>
            setLocality.mutate(
              { me, localityId: l.id },
              {
                onSuccess: () => {
                  setPicking(false);
                  toast.show(`Теперь показываем афишу: ${l.name}`);
                },
              },
            )
          }
        />
        <FormErrors error={setLocality.error} />
      </Sheet>
    </main>
  );
}
