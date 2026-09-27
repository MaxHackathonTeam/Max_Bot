import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Link, type LinkProps } from "react-router-dom";
import { buttonClass, cx, type ButtonLook } from "./classes";
import { Spinner } from "./Spinner";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, ButtonLook {
  loading?: boolean;
  icon?: ReactNode;
}

export function Button({
  variant,
  size,
  block,
  loading = false,
  icon,
  className,
  disabled,
  children,
  type = "button",
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cx(buttonClass({ variant, size, block }), className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <Spinner /> : icon}
      {children}
    </button>
  );
}

interface ButtonLinkProps extends LinkProps, ButtonLook {
  icon?: ReactNode;
}

/** Внутренняя навигация, выглядящая как кнопка. */
export function ButtonLink({ variant, size, block, icon, className, children, ...rest }: ButtonLinkProps) {
  return (
    <Link className={cx(buttonClass({ variant, size, block }), className)} {...rest}>
      {icon}
      {children}
    </Link>
  );
}

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Обязательная подпись для скринридера: у кнопки нет текста. */
  label: string;
}

export function IconButton({ label, className, children, type = "button", ...rest }: IconButtonProps) {
  return (
    <button type={type} className={cx("icon-btn", className)} aria-label={label} title={label} {...rest}>
      {children}
    </button>
  );
}
