import { describe, expect, it } from "vitest";
import { formatDateParts, formatDistance, formatPrice, formatTime, formatWhen } from "./format";

describe("formatWhen", () => {
  it("показывает время в поясе события", () => {
    // 15:00 UTC — это 18:00 в Москве и 19:00 в Самаре.
    expect(formatWhen("2026-09-27T15:00:00Z", "Europe/Moscow")).toBe(
      "Вс 27.09, 18:00",
    );
    expect(formatWhen("2026-09-27T15:00:00Z", "Europe/Samara")).toBe(
      "Вс 27.09, 19:00",
    );
  });

  it("день недели по местной дате, а не по UTC", () => {
    // 22:30 UTC субботы — уже воскресенье 01:30 в Москве.
    expect(formatWhen("2026-09-26T22:30:00Z", "Europe/Moscow")).toBe(
      "Вс 27.09, 01:30",
    );
  });

  it("время конца сеанса", () => {
    expect(formatTime("2026-09-27T17:05:00Z", "Asia/Yekaterinburg")).toBe(
      "22:05",
    );
  });
});

describe("formatPrice", () => {
  it.each([
    [{ price_type: "free", price_min: null, price_max: null }, "Бесплатно"],
    [{ price_type: "donation", price_min: null, price_max: null }, "Донат"],
    [
      { price_type: "paid", price_min: null, price_max: null },
      "Цена не указана",
    ],
    [{ price_type: "paid", price_min: "300.00", price_max: "300.00" }, "300 ₽"],
    [
      { price_type: "paid", price_min: "1500", price_max: "3000" },
      "от 1 500 ₽",
    ],
    [{ price_type: "paid", price_min: "250", price_max: null }, "250 ₽"],
  ])("%o → %s", (card, text) => {
    expect(formatPrice(card)).toBe(text);
  });
});

describe("formatDistance", () => {
  it.each([
    [null, null],
    [0.4, "<1 км"],
    [7.25, "7,3 км"],
    [23.6, "24 км"],
  ])("%s → %s", (km, text) => {
    expect(formatDistance(km)).toBe(text);
  });
});

describe("formatDateParts", () => {
  it("раскладывает дату для карточки в поясе события", () => {
    expect(formatDateParts("2026-10-03T15:00:00Z", "Europe/Moscow")).toEqual({
      day: "3",
      month: "окт",
      weekday: "Сб",
      time: "18:00",
      long: "Сб, 3 октября",
    });
  });

  it("переход через полночь по местному времени меняет день", () => {
    const p = formatDateParts("2026-09-30T21:30:00Z", "Asia/Yekaterinburg");
    expect([p.day, p.month, p.weekday, p.time]).toEqual(["1", "окт", "Чт", "02:30"]);
  });
});
