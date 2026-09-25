// Профиль зрителя: /me и справочники. Без согласия населённый пункт хранится только
// на устройстве (FR-ONB-1: без согласия — только просмотр ленты), в профиль не пишется.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  acceptConsents,
  fetchCategories,
  fetchLocality,
  fetchMe,
  updateMe,
  type Me,
  type MeUpdate,
  type Radius,
} from "../api/client";
import { readLocal, writeLocal } from "../lib/storage";

const LOCAL_LOCALITY = "afisha.locality_id";
const REQUIRED_DOCS = new Set(["terms", "privacy"]);

export function hasConsent(me: Me): boolean {
  return me.consents
    .filter((c) => REQUIRED_DOCS.has(c.doc))
    .every((c) => c.accepted);
}

export function hasOrgConsent(me: Me): boolean {
  return (
    hasConsent(me) && me.consents.some((c) => c.doc === "org_pd" && c.accepted)
  );
}

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: fetchMe, staleTime: 60_000 });
}

export function useCategories() {
  return useQuery({
    queryKey: ["categories"],
    queryFn: fetchCategories,
    staleTime: Infinity,
  });
}

export function useLocality(id: number | null) {
  return useQuery({
    queryKey: ["locality", id],
    queryFn: () => fetchLocality(id as number),
    enabled: id !== null,
    staleTime: Infinity,
  });
}

/** Населённый пункт для ленты: из профиля, иначе выбранный на устройстве. */
export function homeLocalityId(me: Me): number | null {
  if (me.locality_id !== null) return me.locality_id;
  const local = Number(readLocal(LOCAL_LOCALITY));
  return Number.isInteger(local) && local > 0 ? local : null;
}

export function useUpdateMe() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (patch: MeUpdate) => updateMe(patch),
    onSuccess: (me) => client.setQueryData(["me"], me),
  });
}

export function useAcceptConsents() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const me = await acceptConsents(["terms", "privacy"]);
      // Выбранное до согласия место переносим в профиль.
      const local = homeLocalityId(me);
      if (me.locality_id === null && local !== null) {
        writeLocal(LOCAL_LOCALITY, null);
        return updateMe({ locality_id: local });
      }
      return me;
    },
    onSuccess: (me) => client.setQueryData(["me"], me),
  });
}

/** Сохранить место: в профиль при согласии, иначе только на устройстве. */
export function useSetLocality() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ me, localityId }: { me: Me; localityId: number }) => {
      if (hasConsent(me)) return updateMe({ locality_id: localityId });
      writeLocal(LOCAL_LOCALITY, String(localityId));
      return { ...me };
    },
    onSuccess: (me) => client.setQueryData(["me"], me),
  });
}

export function nextRadius(radius: number): Radius | null {
  const wider = ([5, 15, 30, 50] as Radius[]).find((r) => r > radius);
  return wider ?? null;
}
