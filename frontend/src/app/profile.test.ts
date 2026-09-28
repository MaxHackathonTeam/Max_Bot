import { afterEach, describe, expect, it, vi } from "vitest";
import type { Me } from "../api/client";
import { readLocal, writeLocal } from "../lib/storage";
import { homeLocalityId, LOCAL_LOCALITY, localityTarget } from "./profile";

const consents = (accepted: boolean): Me["consents"] => [
  { doc: "terms", version: "1", accepted, accepted_at: null },
  { doc: "privacy", version: "1", accepted, accepted_at: null },
];

const me = (patch: Partial<Me> = {}): Me => ({
  id: 1,
  max_user_id: 100,
  first_name: "Аня",
  last_name: null,
  username: null,
  locality_id: null,
  has_home_point: false,
  radius_km: 25,
  interests: [],
  notify_digest: false,
  notify_reminders: true,
  consents: consents(true),
  needs_onboarding: false,
  is_admin: false,
  ...patch,
});

function fakeStorage(): Storage {
  const data = new Map<string, string>();
  return {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
    clear: () => data.clear(),
    key: () => null,
    get length() {
      return data.size;
    },
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("сохранение пункта", () => {
  it("вошедший с согласием — в профиль, гость — на устройство", () => {
    expect(localityTarget(me())).toBe("profile");
    expect(localityTarget(me({ consents: consents(false) }))).toBe("device");
    expect(localityTarget(null)).toBe("device");
  });

  it("гость: пункт берётся из localStorage", () => {
    vi.stubGlobal("window", { localStorage: fakeStorage() });
    writeLocal(LOCAL_LOCALITY, "42");
    expect(homeLocalityId(null)).toBe(42);
    expect(homeLocalityId(me({ locality_id: 7 }))).toBe(7);
  });

  it("без доступа к localStorage не падает", () => {
    vi.stubGlobal("window", {
      get localStorage(): Storage {
        throw new Error("SecurityError");
      },
    });
    expect(() => writeLocal(LOCAL_LOCALITY, "42")).not.toThrow();
    expect(readLocal(LOCAL_LOCALITY)).toBeNull();
    expect(homeLocalityId(null)).toBeNull();
  });
});
