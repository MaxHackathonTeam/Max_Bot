import { useState } from "react";
import { hasConsent, useViewer } from "../app/profile";
import { useSession } from "../app/session";
import { readLocal, writeLocal } from "../lib/storage";
import { FeedPage, FeedSkeleton } from "./FeedPage";
import { OnboardingPage } from "./OnboardingPage";
import { ErrorScreen } from "./Status";

const ONBOARDED = "afisha.onboarded";

/** Главная: онбординг, пока не выбран населённый пункт, дальше — лента. */
export function HomePage() {
  const viewer = useViewer();
  const { inMax } = useSession();
  const [finished, setFinished] = useState(false);

  if (viewer.loading) return <FeedSkeleton />;
  if (viewer.error) return <ErrorScreen message={viewer.error.message} onRetry={viewer.retry} />;

  // В MAX первым шагом предлагаем согласие; отказ («Пока только посмотреть») запоминаем.
  const askConsent = inMax && viewer.me !== null && !hasConsent(viewer.me) && readLocal(ONBOARDED) !== "1";
  if (viewer.localityId === null || (!finished && askConsent)) {
    return (
      <OnboardingPage
        me={viewer.me}
        askConsent={askConsent}
        localityId={viewer.localityId}
        radius={viewer.radius}
        onFinish={() => {
          writeLocal(ONBOARDED, "1");
          setFinished(true);
        }}
      />
    );
  }
  return <FeedPage me={viewer.me} localityId={viewer.localityId} radius={viewer.radius} />;
}
