import { useRef, type KeyboardEvent } from "react";

interface TabsProps<T extends string> {
  value: T;
  onChange: (value: T) => void;
  items: { value: T; label: string }[];
  label: string;
}

/** Вкладки по паттерну WAI-ARIA: стрелки переключают, Tab уходит дальше. */
export function Tabs<T extends string>({ value, onChange, items, label }: TabsProps<T>) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const delta = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!delta) return;
    event.preventDefault();
    const next = (index + delta + items.length) % items.length;
    onChange(items[next].value);
    refs.current[next]?.focus();
  }

  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {items.map((item, index) => (
        <button
          key={item.value}
          ref={(el) => {
            refs.current[index] = el;
          }}
          type="button"
          role="tab"
          className="tab"
          aria-selected={item.value === value}
          tabIndex={item.value === value ? 0 : -1}
          onClick={() => onChange(item.value)}
          onKeyDown={(event) => onKeyDown(event, index)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
