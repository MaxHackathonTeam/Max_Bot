import { describe, expect, it } from "vitest";
import { authorStatus } from "./authorStatus";
import { auditLabel, composeReason, innValid } from "./moderation";

describe("ИНН", () => {
  it("совпадает с бэкендом (services/verification.py)", () => {
    expect(innValid("7707083893")).toBe(true);
    expect(innValid("7707083894")).toBe(false);
    expect(innValid("500100732259")).toBe(true);
    expect(innValid("500100732258")).toBe(false);
    expect(innValid("123")).toBe(false);
    expect(innValid("77070838a3")).toBe(false);
    expect(innValid(null)).toBe(false);
  });
});

describe("решение модератора", () => {
  it("причина: шаблон + комментарий", () => {
    expect(composeReason("Нет контактов организатора", " добавь телефон ")).toBe(
      "Нет контактов организатора. добавь телефон",
    );
    expect(composeReason(null, "  ")).toBeNull();
    expect(composeReason(null, "Дубль")).toBe("Дубль");
  });

  it("журнал показывает смену статуса и поля", () => {
    expect(auditLabel("event.moderation.admin", { verdict: "reject", status: ["pending", "draft"] })).toBe(
      "Решение модератора: pending → draft",
    );
    expect(auditLabel("event.update", { title: ["a", "b"], sessions: [] })).toBe("Изменено: title, sessions");
    expect(auditLabel("x.y", null)).toBe("x.y");
  });
});

describe("статусы в «Мои афиши»", () => {
  it("возврат на доработку — с причиной и повторной отправкой", () => {
    const s = authorStatus({ status: "draft", moderation_reason: "Нет даты" });
    expect(s).toMatchObject({ label: "Вернули на доработку", reason: "Нет даты", editable: true, resubmit: true });
  });

  it("отклонено — причина видна, можно исправить и отправить снова", () => {
    expect(authorStatus({ status: "rejected", moderation_reason: "Реклама" })).toMatchObject({
      label: "Отклонено",
      reason: "Реклама",
      resubmit: true,
      cancellable: false,
    });
  });

  it("опубликованное можно снять, черновик — нет", () => {
    expect(authorStatus({ status: "published", moderation_reason: null })).toMatchObject({
      label: "Опубликовано",
      cancellable: true,
      editable: false,
    });
    expect(authorStatus({ status: "draft", moderation_reason: null })).toMatchObject({
      label: "Черновик",
      resubmit: false,
      cancellable: false,
    });
    expect(authorStatus({ status: "pending", moderation_reason: null }).label).toBe("На проверке");
  });
});
