// Пункты меню профиля. «Модерация» только для admin: фронт лишь скрывает раздел,
// права проверяет бэкенд (AdminDep).

import type { Me } from "../api/client";

export interface MenuItem {
  key: "my" | "moderation" | "settings" | "logout";
  label: string;
  to?: string;
}

export function displayName(me: Me): string {
  return [me.first_name, me.last_name].filter(Boolean).join(" ") || me.username || "Профиль";
}

export function menuItems(me: Me, inMax: boolean): MenuItem[] {
  const items: MenuItem[] = [{ key: "my", label: "Мои афиши", to: "/my" }];
  if (me.is_admin) items.push({ key: "moderation", label: "Модерация", to: "/moderation" });
  items.push({ key: "settings", label: "Настройки", to: "/settings" });
  // В MAX вход автоматический — выйти нельзя.
  if (!inMax) items.push({ key: "logout", label: "Выйти" });
  return items;
}
