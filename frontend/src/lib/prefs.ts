// Настройки на устройстве (место, радиус) с подпиской: без аккаунта они и есть профиль.

import { useSyncExternalStore } from "react";
import { readLocal, writeLocal } from "./storage";

const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function writePref(key: string, value: string | null): void {
  writeLocal(key, value);
  listeners.forEach((listener) => listener());
}

export function usePref(key: string): string | null {
  return useSyncExternalStore(subscribe, () => readLocal(key));
}
