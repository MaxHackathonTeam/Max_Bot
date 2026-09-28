import { describe, expect, it } from "vitest";
import type { Locality } from "../api/client";
import { geoErrorText, highlightParts, localitySubtitle, moveActive } from "./localitySearch";

const locality = (patch: Partial<Locality> = {}): Locality => ({
  id: 1,
  name: "Панковка",
  kind: "посёлок",
  region: "Новгородская область",
  municipality: "Новгородский район",
  lat: 58.5,
  lon: 31.2,
  timezone: "Europe/Moscow",
  distance_km: null,
  ...patch,
});

describe("автоподстановка пункта", () => {
  it("подсвечивает совпадение без учёта регистра и ё", () => {
    expect(highlightParts("Панковка", "пан")).toEqual([
      { text: "Пан", match: true },
      { text: "ковка", match: false },
    ]);
    expect(highlightParts("Орёл", "орел")).toEqual([{ text: "Орёл", match: true }]);
    expect(highlightParts("Старая Русса", "")).toEqual([{ text: "Старая Русса", match: false }]);
  });

  it("подсвечивает все вхождения", () => {
    expect(highlightParts("Ново-Новое", "нов").filter((p) => p.match)).toHaveLength(2);
  });

  it("стрелки ходят по кругу", () => {
    expect(moveActive(-1, 1, 3)).toBe(0);
    expect(moveActive(-1, -1, 3)).toBe(2);
    expect(moveActive(2, 1, 3)).toBe(0);
    expect(moveActive(0, -1, 3)).toBe(2);
    expect(moveActive(0, 1, 0)).toBe(-1);
  });

  it("подпись с районом и регионом, без повторов и пустых", () => {
    expect(localitySubtitle(locality())).toBe("посёлок · Новгородский район · Новгородская область");
    expect(localitySubtitle(locality({ municipality: null }))).toBe("посёлок · Новгородская область");
    expect(localitySubtitle(locality({ kind: "pgt" }))).toBe("пгт · Новгородский район · Новгородская область");
    expect(localitySubtitle(locality({ kind: "other", municipality: null }))).toBe("Новгородская область");
  });

  it("понятная причина отказа геолокации", () => {
    expect(geoErrorText({ code: 1 })).toMatch(/закрыт/);
    expect(geoErrorText(new Error("unsupported"))).toMatch(/недоступна/);
    expect(geoErrorText(null)).toMatch(/Не получилось/);
  });
});
