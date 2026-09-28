import { describe, expect, it } from "vitest";
import {
  emptyForm,
  firstInvalidStep,
  isoToZonedInput,
  stepOfField,
  stepErrors,
  stepPayload,
  zonedInputToIso,
} from "./eventForm";

describe("время в поясе события", () => {
  it("переводит местное время в UTC", () => {
    expect(zonedInputToIso("2026-09-27T18:00", "Europe/Moscow")).toBe(
      "2026-09-27T15:00:00.000Z",
    );
    expect(zonedInputToIso("2026-09-27T18:00", "Asia/Yekaterinburg")).toBe(
      "2026-09-27T13:00:00.000Z",
    );
    expect(zonedInputToIso("2026-09-27T01:30", "Asia/Vladivostok")).toBe(
      "2026-09-26T15:30:00.000Z",
    );
  });

  it("обратное преобразование", () => {
    expect(isoToZonedInput("2026-09-27T15:00:00Z", "Europe/Moscow")).toBe(
      "2026-09-27T18:00",
    );
    expect(isoToZonedInput("2026-09-26T15:30:00Z", "Asia/Vladivostok")).toBe(
      "2026-09-27T01:30",
    );
  });

  it("пустое и неверное значение — null", () => {
    expect(zonedInputToIso("", "Europe/Moscow")).toBeNull();
    expect(zonedInputToIso("27.09.2026 18:00", "Europe/Moscow")).toBeNull();
  });
});

describe("шаги формы", () => {
  const now = new Date("2026-09-25T12:00:00Z");

  it("шаг 1 требует название и категорию", () => {
    expect(stepErrors(0, emptyForm(), now)).toHaveLength(2);
    expect(
      stepErrors(
        0,
        { ...emptyForm(), title: "Концерт", category: "concert" },
        now,
      ),
    ).toEqual([]);
  });

  it("шаг «Когда»: будущий сеанс, конец после начала", () => {
    const form = { ...emptyForm(), locality_id: 1 };
    expect(stepErrors(1, form, now)).toContain(
      "Укажи дату и время начала каждого сеанса",
    );
    const past = {
      ...form,
      sessions: [{ id: null, starts: "2026-09-20T18:00", ends: "" }],
    };
    expect(stepErrors(1, past, now)).toContain(
      "Нужен хотя бы один сеанс в будущем",
    );
    const bad = {
      ...form,
      sessions: [
        { id: null, starts: "2026-09-27T18:00", ends: "2026-09-27T17:00" },
      ],
    };
    expect(stepErrors(1, bad, now)).toEqual(["Сеанс 1: конец раньше начала"]);
  });

  it("шаг «Где»: пункт или https-ссылка онлайна", () => {
    expect(stepErrors(2, emptyForm(), now)).toEqual(["Выбери населённый пункт"]);
    expect(stepErrors(2, { ...emptyForm(), locality_id: 1 }, now)).toEqual([]);
    const online = { ...emptyForm(), is_online: true, online_url: "http://x" };
    expect(stepErrors(2, online, now)).toEqual([
      "Ссылка на трансляцию должна начинаться с https://",
    ]);
  });

  it("шаг «Цена и возраст»", () => {
    expect(stepErrors(3, emptyForm(), now)).toEqual([
      "Укажи, платное ли событие",
    ]);
    expect(stepErrors(3, { ...emptyForm(), price_type: "paid" }, now)).toEqual([
      "Укажи цену билета",
    ]);
    const range = {
      ...emptyForm(),
      price_type: "paid" as const,
      price_min: "500",
      price_max: "300",
    };
    expect(stepErrors(3, range, now)).toEqual([
      "Максимальная цена меньше минимальной",
    ]);
    expect(stepErrors(3, { ...emptyForm(), price_type: "free" }, now)).toEqual(
      [],
    );
  });

  it("payload «Когда» переводит сеансы в UTC, «Где» убирает площадку у онлайна", () => {
    const form = {
      ...emptyForm(),
      is_online: true,
      online_url: "https://stream.test",
      venue_id: 5,
      sessions: [{ id: 3, starts: "2026-09-27T18:00", ends: "" }],
    };
    expect(stepPayload(1, form, "Europe/Moscow")).toEqual({
      sessions: [
        { id: 3, starts_at: "2026-09-27T15:00:00.000Z", ends_at: null },
      ],
    });
    expect(stepPayload(2, form, "Europe/Moscow")).toEqual({
      is_online: true,
      online_url: "https://stream.test",
      locality_id: null,
      venue_id: null,
    });
  });

  it("payload шага 3 обнуляет цену у бесплатного", () => {
    const form = {
      ...emptyForm(),
      price_type: "free" as const,
      price_min: "100",
    };
    expect(stepPayload(3, form, "UTC")).toMatchObject({
      price_type: "free",
      price_min: null,
      price_max: null,
    });
  });
});

describe("проверка и превью", () => {
  const now = new Date("2026-09-25T12:00:00Z");

  it("первый шаг с ошибкой", () => {
    expect(firstInvalidStep(emptyForm(), now)).toBe(0);
    const filled = {
      ...emptyForm(),
      title: "Концерт хора",
      category: "concert",
      locality_id: 1,
      sessions: [{ id: null, starts: "2026-09-27T18:00", ends: "" }],
    };
    expect(firstInvalidStep(filled, now)).toBe(3);
    expect(firstInvalidStep({ ...filled, price_type: "free" }, now)).toBeNull();
  });

  it("поле из правил ведёт на свой шаг", () => {
    expect(stepOfField("title")).toBe(0);
    expect(stepOfField("sessions")).toBe(1);
    expect(stepOfField("venue_id")).toBe(2);
    expect(stepOfField("price_min")).toBe(3);
    expect(stepOfField("contacts")).toBe(4);
  });
});
