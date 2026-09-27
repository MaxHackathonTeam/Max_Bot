import { cx } from "./classes";

export function Spinner({ large = false, label }: { large?: boolean; label?: string }) {
  return (
    <span
      className={cx("spinner", large && "spinner--lg")}
      role={label ? "status" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    />
  );
}
