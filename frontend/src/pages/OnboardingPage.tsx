import { useState } from "react";
import type { Me, Radius } from "../api/client";
import { hasConsent, useSetLocality, useUpdateMe } from "../app/profile";
import { ConsentPrompt } from "../components/ConsentPrompt";
import { FormErrors } from "../components/FormErrors";
import { InterestChips } from "../components/InterestChips";
import { LocalityPicker } from "../components/LocalityPicker";
import { Button } from "../ui/Button";

type Step = "consent" | "locality" | "interests";

const TITLES: Record<Step, string> = {
  consent: "Привет! Это «Афиша рядом»",
  locality: "Где ты живёшь?",
  interests: "Что тебе интересно?",
};

/**
 * Онбординг (FR-ONB-1…3). На сайте — только выбор места: смотреть афишу можно без входа.
 * В MAX — согласие → место → интересы (интересы хранятся в профиле, поэтому только с согласием).
 */
export function OnboardingPage({
  me,
  askConsent,
  localityId,
  radius,
  onFinish,
}: {
  me: Me | null;
  askConsent: boolean;
  localityId: number | null;
  radius: Radius;
  onFinish: () => void;
}) {
  const [step, setStep] = useState<Step>(askConsent ? "consent" : "locality");
  const [interests, setInterests] = useState<string[]>(me?.interests ?? []);
  const setLocality = useSetLocality();
  const update = useUpdateMe();
  const afterConsent = () => (localityId === null ? setStep("locality") : onFinish());

  return (
    <main className="page page--narrow">
      <div className="stack stack--loose">
        <div className="page-head">
          <p className="eyebrow">{step === "consent" ? "Добро пожаловать" : "Настроим афишу"}</p>
          <h1 className="h1">{TITLES[step]}</h1>
          {step === "consent" && (
            <p className="muted">Концерты, спектакли, мастер-классы и праздники в твоём городе или селе и рядом.</p>
          )}
          {step === "locality" && (
            <p className="muted">Покажем события в этом населённом пункте и в радиусе {radius} км. Поменять можно в любой момент.</p>
          )}
          {step === "interests" && (
            <p className="muted">Отметь, что нравится, — будем учитывать в подборках. Можно пропустить.</p>
          )}
        </div>

        {step === "consent" && <ConsentPrompt onDone={afterConsent} onSkip={afterConsent} />}

        {step === "locality" && (
          <>
            <LocalityPicker
              busy={setLocality.isPending}
              onPick={(l) =>
                setLocality.mutate(
                  { me, localityId: l.id },
                  { onSuccess: () => (me && hasConsent(me) ? setStep("interests") : onFinish()) },
                )
              }
            />
            <FormErrors error={setLocality.error} />
          </>
        )}

        {step === "interests" && (
          <>
            <InterestChips
              selected={interests}
              onToggle={(slug) => setInterests((s) => (s.includes(slug) ? s.filter((x) => x !== slug) : [...s, slug]))}
            />
            <div className="row">
              <Button variant="ghost" onClick={onFinish}>
                Пропустить
              </Button>
              <Button
                variant="primary"
                size="lg"
                className="grow"
                loading={update.isPending}
                onClick={() => update.mutate({ interests }, { onSuccess: onFinish })}
              >
                Готово
              </Button>
            </div>
            <FormErrors error={update.error} />
          </>
        )}
      </div>
    </main>
  );
}
