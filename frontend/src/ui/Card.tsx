import type { HTMLAttributes } from "react";
import { cx } from "./classes";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  tone?: "plain" | "sun";
}

export function Card({ tone = "plain", className, ...rest }: CardProps) {
  return <div className={cx("card", tone === "sun" && "card--sun", className)} {...rest} />;
}
