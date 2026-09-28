import { describe, expect, it } from "vitest";
import type { Me } from "../api/client";
import { displayName, menuItems } from "./menu";

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
  consents: [],
  needs_onboarding: false,
  is_admin: false,
  ...patch,
});

describe("меню профиля", () => {
  it("скрывает модерацию для не-admin", () => {
    const keys = menuItems(me(), false).map((item) => item.key);
    expect(keys).toEqual(["my", "settings", "logout"]);
  });

  it("показывает модерацию admin", () => {
    const items = menuItems(me({ is_admin: true }), false);
    expect(items.find((item) => item.key === "moderation")?.to).toBe("/moderation");
  });

  it("в MAX нет «Выйти»", () => {
    expect(menuItems(me(), true).map((item) => item.key)).not.toContain("logout");
  });

  it("имя: имя и фамилия, потом ник, потом запасной вариант", () => {
    expect(displayName(me({ last_name: "Петрова" }))).toBe("Аня Петрова");
    expect(displayName(me({ first_name: null, username: "anya" }))).toBe("anya");
    expect(displayName(me({ first_name: null }))).toBe("Профиль");
  });
});
