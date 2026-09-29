// Диплинки startapp (§3.1): ev_<id>, org_<id>, draft_<id>, inv_<token>, feed_<preset>,
// mod_<id> (mod_0 — очередь модерации), legal_<doc>.
// Формат совпадает с разбором payload в боте (backend/app/bot/dispatcher.py).

const FEEDS = new Set(["today", "weekend", "pushkin", "kids", "free"]);

/** Путь внутри приложения для start_param или null, если параметр пустой или некорректный. */
export function startParamToPath(
  param: string | null | undefined,
): string | null {
  const value = param?.trim();
  if (!value) return null;

  let m = /^(ev|org|draft)_(\d{1,18})$/.exec(value);
  if (m) {
    const section = { ev: "event", org: "org", draft: "draft" }[
      m[1] as "ev" | "org" | "draft"
    ];
    return `/${section}/${m[2]}`;
  }
  m = /^mod_(\d{1,18})$/.exec(value);
  if (m) return m[1] === "0" ? "/moderation" : `/moderation/${m[1]}`;
  m = /^legal_(terms|privacy)$/.exec(value);
  if (m) return `/legal/${m[1]}`;
  m = /^inv_([A-Za-z0-9_-]{8,128})$/.exec(value);
  if (m) return `/invite/${m[1]}`;
  m = /^feed_([a-z]+)$/.exec(value);
  if (m && FEEDS.has(m[1])) return `/?feed=${m[1]}`;
  return null;
}
