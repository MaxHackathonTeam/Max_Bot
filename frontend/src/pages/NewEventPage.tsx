import type { Me } from "../api/client";
import { RequireMax } from "../components/RequireMax";
import { Draft } from "./DraftPage";

function NewEvent({ me }: { me: Me }) {
  return <Draft me={me} id={0} />;
}

/** /new: любой вошедший через MAX добавляет афишу — форма по шагам. */
export function NewEventPage() {
  return (
    <RequireMax title="Добавить афишу" text="Чтобы добавить афишу, войди через MAX: туда придёт итог модерации.">
      {(me) => <NewEvent me={me} />}
    </RequireMax>
  );
}
