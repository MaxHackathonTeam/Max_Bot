import { Typography } from "@maxhub/max-ui";
import { ApiError } from "../api/client";

/** Ошибка запроса: общее сообщение и ошибки полей из details.fields (422). */
export function FormErrors({
  error,
  messages = [],
}: {
  error?: Error | null;
  messages?: string[];
}) {
  const lines = [...messages];
  if (error) {
    const fields = error instanceof ApiError ? error.fields : [];
    if (fields.length > 0) lines.push(...fields.map((f) => f.message));
    else lines.push(error.message);
  }
  if (lines.length === 0) return null;
  return (
    <div className="notice notice--danger stack" role="alert">
      {lines.map((line) => (
        <Typography.Body key={line} variant="small">
          {line}
        </Typography.Body>
      ))}
    </div>
  );
}
