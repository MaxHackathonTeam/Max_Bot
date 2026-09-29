import { Monitor, Moon, Sun } from "lucide-react";
import { setThemePref, THEME_OPTIONS, useThemePref, type ThemePref } from "../app/theme";
import { IconButton } from "../ui/Button";
import { Chip } from "../ui/Chip";

const ICONS = { light: Sun, dark: Moon, system: Monitor } as const;
const NEXT: Record<ThemePref, ThemePref> = { system: "light", light: "dark", dark: "system" };

/** Выбор темы в «Настройках»: три чипа. */
export function ThemeChips() {
  const pref = useThemePref();
  return (
    <div className="chips" role="group" aria-label="Тема оформления">
      {THEME_OPTIONS.map(([value, label]) => {
        const Icon = ICONS[value];
        return (
          <Chip key={value} pressed={pref === value} icon={<Icon size={16} aria-hidden />} onClick={() => setThemePref(value)}>
            {label}
          </Chip>
        );
      })}
    </div>
  );
}

/** Кнопка в шапке: по кругу «Как в системе» → «Светлая» → «Тёмная». */
export function ThemeToggle() {
  const pref = useThemePref();
  const Icon = ICONS[pref];
  const label = THEME_OPTIONS.find(([value]) => value === pref)?.[1] ?? "";
  return (
    <IconButton label={`Тема: ${label.toLowerCase()}. Сменить`} onClick={() => setThemePref(NEXT[pref])}>
      <Icon size={20} aria-hidden />
    </IconButton>
  );
}
