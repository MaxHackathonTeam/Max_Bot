// Профиль зрителя: /me и справочники. Без аккаунта или без согласия место и радиус
// хранятся только на устройстве (FR-ONB-1: без согласия — только просмотр ленты).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  acceptConsents,
  fetchCategories,
  fetchLocality,
  fetchMe,
  RADII,
  updateMe,
  type Me,
  type MeUpdate,
  type Radius,
} from "../api/client";
import { readLocal } from "../lib/storage";
import { usePref, writePref } from "../lib/prefs";
import { useSession } from "./session";

export const LOCAL_LOCALITY = "afisha.locality_id";
export const LOCAL_RADIUS = "afisha.radius_km";
export const DEFAULT_RADIUS: Radius = 15;
const REQUIRED_DOCS = new Set(["terms", "privacy"]);

export function hasConsent(me: Me): boolean {
  return me.consents.filter((c) => REQUIRED_DOCS.has(c.doc)).every((c) => c.accepted);
}

export function hasOrgConsent(me: Me): boolean {
  return hasConsent(me) && me.consents.some((c) => c.doc === "org_pd" && c.accepted);
}

/** Аккаунт MAX (а не гость): только ему доступны кабинет организатора и уведомления. */
export function isMaxAccount(me: Me | null | undefined): me is Me {
  return me != null && me.max_user_id !== null;
}

export function useMe() {
  const { hasToken } = useSession();
  return useQuery({ queryKey: ["me"], queryFn: fetchMe, staleTime: 60_000, enabled: hasToken });
}

export function useCategories() {
  return useQuery({ queryKey: ["categories"], queryFn: fetchCategories, staleTime: Infinity });
}

export function useLocality(id: number | null) {
  return useQuery({
    queryKey: ["locality", id],
    queryFn: () => fetchLocality(id as number),
    enabled: id !== null,
    staleTime: Infinity,
  });
}

function parseLocality(raw: string | null): number | null {
  const id = Number(raw);
  return Number.isInteger(id) && id > 0 ? id : null;
}

function parseRadius(raw: string | null): Radius {
  const r = Number(raw);
  return (RADII as number[]).includes(r) ? (r as Radius) : DEFAULT_RADIUS;
}

/** Населённый пункт для ленты: из профиля, иначе выбранный на устройстве. */
export function homeLocalityId(me: Me | null | undefined): number | null {
  return me?.locality_id ?? parseLocality(readLocal(LOCAL_LOCALITY));
}

export interface Viewer {
  me: Me | null;
  localityId: number | null;
  radius: Radius;
  /** Профиль ещё грузится — решать про онбординг рано. */
  loading: boolean;
  error: Error | null;
  retry: () => void;
}

/** Кто смотрит ленту: аккаунт (если есть) и его место с радиусом либо настройки устройства. */
export function useViewer(): Viewer {
  const session = useSession();
  const me = useMe();
  const localLocality = parseLocality(usePref(LOCAL_LOCALITY));
  const localRadius = parseRadius(usePref(LOCAL_RADIUS));
  const profile = me.data ?? null;
  const localityId = profile?.locality_id ?? localLocality;
  const useProfile = profile !== null && hasConsent(profile);
  return {
    me: profile,
    localityId,
    radius: useProfile ? parseRadius(String(profile.radius_km)) : localRadius,
    // Пока не ясно, MAX ли это и есть ли там профиль с местом, онбординг не показываем.
    loading:
      (session.hasToken && me.isPending) || (localityId === null && (session.booting || session.signingIn)),
    error: me.error,
    retry: () => void me.refetch(),
  };
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
      // Выбранные до согласия место и радиус переносим в профиль.
      const local = parseLocality(readLocal(LOCAL_LOCALITY));
      if (me.locality_id === null && local !== null) {
        const updated = await updateMe({ locality_id: local, radius_km: parseRadius(readLocal(LOCAL_RADIUS)) });
        writePref(LOCAL_LOCALITY, null);
        return updated;
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
    mutationFn: async ({ me, localityId }: { me: Me | null; localityId: number }) => {
      if (me && hasConsent(me)) return updateMe({ locality_id: localityId });
      writePref(LOCAL_LOCALITY, String(localityId));
      return null;
    },
    onSuccess: (me) => {
      if (me) client.setQueryData(["me"], me);
    },
  });
}

/** Сохранить радиус: в профиль при согласии, иначе на устройстве. */
export function useSetRadius() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ me, radius }: { me: Me | null; radius: Radius }) => {
      if (me && hasConsent(me)) return updateMe({ radius_km: radius });
      writePref(LOCAL_RADIUS, String(radius));
      return null;
    },
    onSuccess: (me) => {
      if (me) client.setQueryData(["me"], me);
    },
  });
}

export function nextRadius(radius: number): Radius | null {
  return RADII.find((r) => r > radius) ?? null;
}
