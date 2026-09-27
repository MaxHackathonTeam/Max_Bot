import type { ReactNode } from "react";
import { cx } from "./classes";

export type BadgeTone = "plain" | "verified" | "free" | "pushkin" | "demo" | "danger" | "accent";

export function Badge({ tone = "plain", icon, children }: { tone?: BadgeTone; icon?: ReactNode; children: ReactNode }) {
  return (
    <span className={cx("badge", tone !== "plain" && `badge--${tone}`)}>
      {icon}
      {children}
    </span>
  );
}
