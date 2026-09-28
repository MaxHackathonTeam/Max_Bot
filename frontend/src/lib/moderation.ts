// Раздел модератора: проверка ИНН (как services/verification.py:inn_valid), шаблоны причин,
// подписи вердиктов и журнала. Чистые функции, покрыты тестами.

const INN10 = [2, 4, 10, 3, 5, 9, 4, 6, 8];
const INN12_1 = [7, 2, 4, 10, 3, 5, 9, 4, 6, 8];
const INN12_2 = [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8];

const control = (digits: number[], weights: number[]) =>
  (weights.reduce((sum, w, i) => sum + w * digits[i], 0) % 11) % 10;

/** Контрольные цифры ИНН: 10 знаков — юрлицо, 12 — ИП и физлицо. */
export function innValid(inn: string | null | undefined): boolean {
  if (!inn || !/^(\d{10}|\d{12})$/.test(inn)) return false;
  const d = [...inn].map(Number);
  if (d.length === 10) return control(d, INN10) === d[9];
  return control(d, INN12_1) === d[10] && control(d, INN12_2) === d[11];
}

/** Шаблоны причин отказа и возврата; модератор дописывает комментарий. */
export const REASON_TEMPLATES = [
  "Не указаны дата или место",
  "Похоже на рекламу, а не на событие",
  "Дубликат уже опубликованного события",
  "Нарушает правила площадки",
  "Неверная категория или возраст",
  "Нет контактов организатора",
] as const;

/** Итоговая причина: шаблон и комментарий через точку; пустое — null. */
export function composeReason(template: string | null, comment: string): string | null {
  const parts = [template?.trim(), comment.trim()].filter((p): p is string => Boolean(p));
  return parts.length > 0 ? parts.join(". ") : null;
}

const VERDICTS: Record<string, string> = {
  approve: "Одобрено",
  reject: "Отклонено",
  hide: "Скрыто",
  needs_review: "Нужна проверка",
};

const ACTORS: Record<string, string> = {
  admin: "модератор",
  rules: "правила",
  system: "система",
  user: "пользователь",
  llm: "автопроверка",
};

export const verdictLabel = (verdict: string) => VERDICTS[verdict] ?? verdict;
export const actorLabel = (actor: string) => ACTORS[actor] ?? actor;

const ACTIONS: Record<string, string> = {
  "event.create": "Создано",
  "event.update": "Изменено",
  "event.auto_fields": "Разобрано из анонса",
  "event.submit": "Отправлено на проверку",
  "event.cancel": "Снято автором",
  "event.report": "Жалоба",
  "event.moderation.admin": "Решение модератора",
  "event.moderation.rules": "Проверка правилами",
};

/** Строка журнала: «Изменено: title, sessions» или статус «pending → draft». */
export function auditLabel(action: string, diff: Record<string, unknown> | null): string {
  const label = ACTIONS[action] ?? action;
  const status = diff?.status;
  if (Array.isArray(status) && status.length === 2) return `${label}: ${status[0]} → ${status[1]}`;
  if (action === "event.update" && diff) {
    const fields = Object.keys(diff).filter((k) => k !== "status");
    if (fields.length > 0) return `${label}: ${fields.join(", ")}`;
  }
  return label;
}
