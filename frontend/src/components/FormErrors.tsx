import { CircleAlert } from "lucide-react";
import { ApiError } from "../api/client";

/** Ошибка запроса: общее сообщение и ошибки полей из details.fields (422). */
export function FormErrors({ error, messages = [] }: { error?: Error | null; messages?: string[] }) {
  const lines = [...messages];
  if (error) {
    const fields = error instanceof ApiError ? error.fields : [];
    if (fields.length > 0) lines.push(...fields.map((f) => f.message));
    else lines.push(error.message);
  }
  if (lines.length === 0) return null;
  return (
    <div className="notice notice--danger" role="alert">
      <CircleAlert size={18} aria-hidden />
      <div className="stack stack--tight">
        {lines.map((line) => (
          <p key={line}>{line}</p>
        ))}
      </div>
    </div>
  );
}
