// Тема сайта: «Светлая / Тёмная / Как в системе». Выбор — в localStorage, итог — на
// <html data-theme="light|dark">. Первую установку делает inline-скрипт в index.html (без
// мигания); здесь — смена темы и слежение за системной темой.
// В MAX Bridge (st.max.ru/js/max-web-app.js) поля темы нет, поэтому и в MAX работаем от
// prefers-color-scheme — так же делает MAX UI (useSystemColorScheme).

import { useSyncExternalStore } from "react";

export type ThemePref = "light" | "dark" | "system";
export type Theme = "light" | "dark";

export const THEME_KEY = "afisha.theme";
export const THEME_OPTIONS: [ThemePref, string][] = [
  ["light", "Светлая"],
  ["dark", "Тёмная"],
  ["system", "Как в системе"],
];
// Цвет полосы браузера — фон бумаги (--paper) в каждой теме.
const THEME_COLOR: Record<Theme, string> = { light: "#faf5eb", dark: "#1b1712" };

const DARK_QUERY = "(prefers-color-scheme: dark)";

function isPref(value: unknown): value is ThemePref {
  return value === "light" || value === "dark" || value === "system";
}

export function readPref(): ThemePref {
  try {
    const value = window.localStorage.getItem(THEME_KEY);
    return isPref(value) ? value : "system";
  } catch {
    return "system";
  }
}

function systemTheme(): Theme {
  return typeof window.matchMedia === "function" && window.matchMedia(DARK_QUERY).matches ? "dark" : "light";
}

export function resolveTheme(pref: ThemePref): Theme {
  return pref === "system" ? systemTheme() : pref;
}

function apply(pref: ThemePref): void {
  const theme = resolveTheme(pref);
  document.documentElement.dataset.theme = theme;
  document.querySelectorAll('meta[name="theme-color"]').forEach((meta) => {
    meta.setAttribute("content", THEME_COLOR[theme]);
  });
}

let current: ThemePref | null = null;
const listeners = new Set<() => void>();

function getPref(): ThemePref {
  current ??= readPref();
  return current;
}

export function setThemePref(pref: ThemePref): void {
  current = pref;
  try {
    if (pref === "system") window.localStorage.removeItem(THEME_KEY);
    else window.localStorage.setItem(THEME_KEY, pref);
  } catch {
    // Хранилище недоступно (приватный режим) — тема просто не запомнится.
  }
  apply(pref);
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  const media = typeof window.matchMedia === "function" ? window.matchMedia(DARK_QUERY) : null;
  const onSystemChange = () => {
    if (getPref() === "system") apply("system");
  };
  media?.addEventListener?.("change", onSystemChange);
  return () => {
    listeners.delete(listener);
    media?.removeEventListener?.("change", onSystemChange);
  };
}

export function useThemePref(): ThemePref {
  return useSyncExternalStore(subscribe, getPref, () => "system");
}
