import type { CSSProperties, ReactNode } from "react";

interface SkeletonProps {
  width?: CSSProperties["width"];
  height?: CSSProperties["height"];
  radius?: CSSProperties["borderRadius"];
}

export function Skeleton({ width = "100%", height = 16, radius }: SkeletonProps) {
  return <span className="skeleton" aria-hidden style={{ width, height, borderRadius: radius }} />;
}

/** Обёртка для группы скелетонов: скринридер слышит одно «Загружаем». */
export function Loading({ children, label = "Загружаем" }: { children: ReactNode; label?: string }) {
  return (
    <div role="status" aria-live="polite" className="stack">
      <span className="visually-hidden">{label}</span>
      {children}
    </div>
  );
}
