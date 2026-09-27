// Классы UI-кита. Отдельно от компонентов: react-refresh требует, чтобы .tsx экспортировал только компоненты.

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

export type ButtonVariant = "primary" | "dark" | "secondary" | "ghost" | "danger" | "on";
export type ButtonSize = "sm" | "md" | "lg";

export interface ButtonLook {
  variant?: ButtonVariant;
  size?: ButtonSize;
  block?: boolean;
}

export function buttonClass({ variant = "dark", size = "md", block }: ButtonLook = {}): string {
  return cx("btn", `btn--${variant}`, size !== "md" && `btn--${size}`, block && "btn--block");
}
