import { describe, expect, it } from "vitest";
import { startParamToPath } from "./deeplink";

describe("startParamToPath", () => {
  it.each([
    ["ev_123", "/event/123"],
    [" org_7 ", "/org/7"],
    ["draft_55", "/draft/55"],
    ["inv_AbCdEf12_-", "/invite/AbCdEf12_-"],
    ["feed_weekend", "/?feed=weekend"],
  ])("%s → %s", (param, path) => {
    expect(startParamToPath(param)).toBe(path);
  });

  it.each([
    "",
    null,
    undefined,
    "ev_",
    "ev_abc",
    "feed_other",
    "inv_short",
    "ev_1/../admin",
  ])("отклоняет %s", (param) => {
    expect(startParamToPath(param)).toBeNull();
  });
});
