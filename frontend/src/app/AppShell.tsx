import { Bookmark, Building, CalendarDays, ChevronLeft, CirclePlus, Landmark, UserRound } from "lucide-react";
import type { MouseEvent, ReactNode } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import { ProfileMenu } from "../components/ProfileMenu";
import { ThemeToggle } from "../components/ThemeSwitch";
import { IconButton } from "../ui/Button";
import { useRequireLogin } from "./login";
import { useSession } from "./session";

// top: false — на десктопе пункт заменяет меню профиля в шапке; short — подпись в нижней панели.
const NAV: { to: string; label: string; short?: string; icon: typeof Building; end: boolean; top: boolean }[] = [
  { to: "/", label: "Афиша", icon: CalendarDays, end: true, top: true },
  { to: "/saved", label: "Пойду", icon: Bookmark, end: false, top: true },
  { to: "/orgs", label: "Организации", short: "Площадки", icon: Landmark, end: false, top: true },
  { to: "/new", label: "Добавить", icon: CirclePlus, end: false, top: true },
  { to: "/org/0", label: "Кабинет", icon: Building, end: false, top: true },
  { to: "/settings", label: "Профиль", icon: UserRound, end: false, top: false },
];
const ADD_REASON = "Чтобы добавить афишу, войди через MAX.";
const TAB_ROOTS = new Set(NAV.map((item) => item.to));

/** Шапка, навигация (снизу на телефоне, в шапке на десктопе) и своя «Назад» вне MAX. */
export function AppShell({ children }: { children: ReactNode }) {
  const { inMax } = useSession();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  // В MAX «Назад» системная (useBackButton), в браузере — своя кнопка в шапке.
  const showBack = !inMax && !TAB_ROOTS.has(pathname);
  const requireLogin = useRequireLogin();
  // «Добавить» гостю сначала объясняет, зачем вход, и после входа ведёт на /new.
  const guard = (to: string) => (event: MouseEvent) => {
    if (to === "/new" && !requireLogin({ reason: ADD_REASON, next: "/new" })) event.preventDefault();
  };

  const back = () => {
    const idx = (window.history.state as { idx?: number } | null)?.idx ?? 0;
    if (idx > 0) navigate(-1);
    else navigate("/", { replace: true });
  };

  return (
    <div className="app">
      <a className="skip-link" href="#main">
        К содержимому
      </a>
      <header className="topbar">
        <div className="topbar__inner">
          {showBack && (
            <IconButton label="Назад" onClick={back}>
              <ChevronLeft size={22} aria-hidden />
            </IconButton>
          )}
          <Link to="/" className="brand" aria-label="Афиша рядом — на главную">
            <span className="brand__mark" aria-hidden />
            <span>
              афиша <span className="brand__accent">рядом</span>
            </span>
          </Link>
          <div className="topbar__end">
            <nav className="topnav" aria-label="Разделы">
              {NAV.filter((item) => item.top).map(({ to, label, icon: Icon, end }) => (
                <NavLink key={to} to={to} end={end} onClick={guard(to)}>
                  <Icon size={18} aria-hidden />
                  {label}
                </NavLink>
              ))}
            </nav>
            <ThemeToggle />
            <ProfileMenu />
          </div>
        </div>
      </header>
      <div id="main" className="app__main" tabIndex={-1}>
        {children}
      </div>
      <nav className="tabbar" aria-label="Разделы">
        {NAV.map(({ to, label, short, icon: Icon, end }) => (
          <NavLink key={to} to={to} end={end} onClick={guard(to)}>
            <Icon size={22} aria-hidden />
            {short ?? label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
