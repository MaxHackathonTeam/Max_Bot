import { ChevronDown, LogIn, UserRound } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { Link, useLocation } from "react-router-dom";
import { useLoginPrompt } from "../app/login";
import { displayName, menuItems } from "../app/menu";
import { isMaxAccount, useMe } from "../app/profile";
import { useSession } from "../app/session";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";

/** Шапка: «Войти через MAX» для гостя, меню профиля после входа. */
export function ProfileMenu() {
  const session = useSession();
  const me = useMe();
  const login = useLoginPrompt();
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);

  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    if (!open) return;
    root.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
    const onDown = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  if (!isMaxAccount(me.data)) {
    if (session.inMax) return null;
    return (
      <Button
        variant="dark"
        size="sm"
        icon={<LogIn size={16} aria-hidden />}
        loading={session.signingIn}
        onClick={() => login.open()}
      >
        Войти<span className="wide-only"> через MAX</span>
      </Button>
    );
  }

  const profile = me.data;
  const items = menuItems(profile, session.inMax);
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const all = Array.from(root.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? []);
    const index = all.indexOf(document.activeElement as HTMLElement);
    if (event.key === "Escape") {
      setOpen(false);
      trigger.current?.focus();
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const delta = event.key === "ArrowDown" ? 1 : -1;
      all[(index + delta + all.length) % all.length]?.focus();
    }
  };

  return (
    <div className="menu" ref={root} onKeyDown={onKeyDown}>
      <button
        ref={trigger}
        type="button"
        className="menu__trigger"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={menuId}
        aria-label={`Профиль: ${displayName(profile)}`}
        onClick={() => setOpen((v) => !v)}
      >
        <UserRound size={18} aria-hidden />
        <span className="menu__name">{displayName(profile)}</span>
        <ChevronDown size={16} aria-hidden />
      </button>
      {open && (
        <div className="menu__panel" id={menuId} role="menu" aria-label="Профиль">
          <div className="menu__head">
            <strong>{displayName(profile)}</strong>
            {profile.is_admin && <Badge tone="accent">Модератор</Badge>}
          </div>
          {items.map((item) =>
            item.to ? (
              <Link key={item.key} role="menuitem" className="menu__item" to={item.to}>
                {item.label}
              </Link>
            ) : (
              <button
                key={item.key}
                type="button"
                role="menuitem"
                className="menu__item"
                onClick={() => {
                  setOpen(false);
                  session.signOut();
                }}
              >
                {item.label}
              </button>
            ),
          )}
        </div>
      )}
    </div>
  );
}
