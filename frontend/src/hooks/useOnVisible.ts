import { useEffect, useRef } from "react";

/** Вызывает callback, когда элемент-«дозорный» попадает в экран (бесконечная прокрутка). */
export function useOnVisible<T extends Element>(
  callback: () => void,
  enabled: boolean,
) {
  const ref = useRef<T | null>(null);
  const latest = useRef(callback);
  latest.current = callback;

  useEffect(() => {
    const node = ref.current;
    if (!node || !enabled || typeof IntersectionObserver === "undefined")
      return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) latest.current();
      },
      { rootMargin: "200px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [enabled]);
  return ref;
}
