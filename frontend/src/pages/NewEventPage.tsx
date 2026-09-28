import { useMutation } from "@tanstack/react-query";
import { Wand2 } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import type { Me } from "../api/client";
import { draftFromText } from "../api/organizer";
import { hasConsent } from "../app/profile";
import { ConsentPrompt } from "../components/ConsentPrompt";
import { FormErrors } from "../components/FormErrors";
import { RequireMax } from "../components/RequireMax";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { Field, Textarea } from "../ui/Field";
import { Tabs } from "../ui/Tabs";
import { Draft, TierChoice } from "./DraftPage";

type Mode = "paste" | "form";

const MODES: { value: Mode; label: string }[] = [
  { value: "paste", label: "Вставить анонс" },
  { value: "form", label: "Заполнить форму" },
];
const MIN_TEXT = 10;
const MAX_TEXT = 4000;

/** Вставить анонс: правила из app/parsing разбирают текст в черновик, дальше — обычная форма. */
function PasteMode() {
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const [orgId, setOrgId] = useState<number | null>(null);
  const length = text.trim().length;
  const parse = useMutation({
    mutationFn: () => draftFromText(text.trim(), orgId),
    onSuccess: (event) => navigate(`/draft/${event.id}?step=0`, { replace: true }),
  });
  return (
    <div className="stack">
      <TierChoice orgId={orgId} onChange={setOrgId} />
      <Field
        label="Текст анонса"
        hint={`Вставь пост из группы или объявление. Найдём название, дату, цену, контакты. ${length}/${MAX_TEXT}`}
      >
        {(p) => (
          <Textarea
            {...p}
            rows={10}
            maxLength={MAX_TEXT}
            value={text}
            placeholder="Например: 5 октября в 18:00 в ДК — концерт хора «Рябинушка». Вход свободный. Тел. +7 900 000-00-00"
            onChange={(e) => setText(e.target.value)}
          />
        )}
      </Field>
      <FormErrors error={parse.error} />
      <Button
        variant="primary"
        size="lg"
        block
        icon={<Wand2 size={18} aria-hidden />}
        disabled={length < MIN_TEXT}
        loading={parse.isPending}
        onClick={() => parse.mutate()}
      >
        Разобрать и проверить
      </Button>
      <p className="small muted">Распознанное подсветим — останется проверить и отправить на модерацию.</p>
    </div>
  );
}

function NewEvent({ me }: { me: Me }) {
  const [mode, setMode] = useState<Mode>("paste");
  if (mode === "form") {
    return (
      <>
        <div className="page page--narrow page--flush">
          <Tabs label="Как добавить" value={mode} onChange={setMode} items={MODES} />
        </div>
        <Draft me={me} id={0} />
      </>
    );
  }
  return (
    <main className="page page--narrow">
      <div className="stack stack--loose">
        <div className="page-head">
          <p className="eyebrow">Новая афиша</p>
          <h1 className="h1">Добавить событие</h1>
        </div>
        <Tabs label="Как добавить" value={mode} onChange={setMode} items={MODES} />
        {hasConsent(me) ? (
          <PasteMode />
        ) : (
          <Card>
            <ConsentPrompt />
          </Card>
        )}
      </div>
    </main>
  );
}

/** /new: любой вошедший через MAX добавляет афишу — вставкой анонса или по шагам. */
export function NewEventPage() {
  return (
    <RequireMax title="Добавить афишу" text="Чтобы добавить афишу, войди через MAX: туда придёт итог модерации.">
      {(me) => <NewEvent me={me} />}
    </RequireMax>
  );
}
